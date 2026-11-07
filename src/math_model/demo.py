"""Dados de demonstração de um repositório que ainda não tem coleta real.

Atende ao pedido do PO de poder "ver como fica" um repositório antes da primeira
análise, sem repetir o defeito da #150 (BUG05.06), em que o onboarding gravava
métricas inventadas como se fossem reais. As regras aqui são:

- só sob pedido: o Front chama este cálculo quando a pessoa clica em
  "Ver dados de demonstração" no estado vazio do repositório;
- nunca gravado: usa apenas a fase build_* do MathModelServices (cálculo em
  memória) e não chama persist_all nem save() em nenhuma entidade;
- sempre identificado: a resposta leva is_demo=True e um aviso, e o Front
  mostra uma faixa fixa enquanto os dados de demonstração estão na tela;
- só para repositório sem dados: com coleta real, a view recusa (409).

Os valores passam pelo mesmo modelo matemático (msgram-core) de uma coleta real,
a partir de um payload fictício que varia de forma determinística por
repositório, para o gráfico de pulso ter uma evolução para mostrar.
"""

import random
from datetime import timedelta

from django.utils import timezone

from math_model.services import MathModelServices
from math_model.utils import parse_release_configuration
from release_configuration.models import ReleaseConfiguration
from release_configuration.serializers import ReleaseConfigurationSerializer
from utils import staticfiles

DEMO_COLLECTIONS = 6
DEMO_INTERVAL_DAYS = 7
DEMO_NOTICE = (
    "Dados fictícios de demonstração: não foram coletados deste repositório, "
    "não são gravados e desaparecem quando a primeira análise real chegar."
)
DEMO_FILES = ("demo/modulo_a.py", "demo/modulo_b.py", "demo/modulo_c.py")
DEMO_TEST_FILES = ("demo/tests/test_modulo_a.py", "demo/tests/test_modulo_b.py")


def repository_has_real_data(repository) -> bool:
    """Há coleta real quando existe qualquer métrica coletada ou TSQMI gravado."""
    return repository.collected_metrics.exists() or repository.calculated_tsqmis.exists()


def _release_configuration(product):
    """A configuração do produto, ou a pré-configuração padrão em memória.

    A instância padrão não é salva: este fluxo não pode escrever no banco.
    """
    configuration = product.release_configuration.first()
    if configuration is not None:
        return configuration
    return ReleaseConfiguration(
        name="Default pre-config",
        product=product,
        data=staticfiles.DEFAULT_PRE_CONFIG,
    )


def build_demo_payload(rng: random.Random, step: int, total_steps: int) -> dict:
    """Payload fictício no formato da Action (GitHub + SonarQube).

    `step` vai de 0 a total_steps - 1; a qualidade melhora um pouco a cada
    coleta, com ruído, para o pulso não ser uma linha reta.
    """
    progress = step / max(total_steps - 1, 1)

    def jitter(base, spread, minimum=0.0, maximum=None):
        value = base + rng.uniform(-spread, spread)
        value = max(minimum, value)
        return min(maximum, value) if maximum is not None else value

    files = [
        {
            "qualifier": "FIL",
            "path": path,
            "measures": [
                {"metric": "coverage", "value": round(jitter(45 + 35 * progress, 8, 0, 100), 1)},
                {"metric": "complexity", "value": round(jitter(14 - 6 * progress, 3, 1))},
                {"metric": "functions", "value": round(jitter(12, 4, 1))},
                {"metric": "comment_lines_density", "value": round(jitter(8 + 10 * progress, 4, 0, 100), 1)},
                {"metric": "duplicated_lines_density", "value": round(jitter(12 - 9 * progress, 3, 0, 100), 1)},
                {"metric": "ncloc", "value": round(jitter(180 + 40 * step, 30, 10))},
            ],
        }
        for path in DEMO_FILES
    ]
    tests = [
        {
            "qualifier": "UTS",
            "path": path,
            "measures": [
                {"metric": "tests", "value": round(jitter(6 + 4 * step, 2, 1))},
                {"metric": "test_execution_time", "value": round(jitter(120 - 40 * progress, 20, 10))},
            ],
        }
        for path in DEMO_TEST_FILES
    ]
    total_issues = round(jitter(20, 4, 2))
    total_builds = round(jitter(10, 3, 1))
    return {
        "github": {
            "metrics": [
                {"name": "total_issues", "value": total_issues},
                {"name": "resolved_issues", "value": round(total_issues * (0.4 + 0.5 * progress))},
                {"name": "sum_ci_feedback_times", "value": round(total_builds * jitter(300 - 120 * progress, 40, 30))},
                {"name": "total_builds", "value": total_builds},
            ],
        },
        "sonarqube": {
            "components": [
                *files,
                *tests,
                {
                    "qualifier": "TRK",
                    "path": "",
                    "measures": [
                        {"metric": "test_failures", "value": round(jitter(2 - 2 * progress, 1, 0))},
                        {"metric": "test_errors", "value": 0},
                    ],
                },
            ],
        },
    }


def build_demo_data(repository, now=None) -> dict:
    """Calcula, sem gravar, o TSQMI e o histórico das características de demonstração."""
    product = repository.product
    now = now or timezone.now()
    release_configuration = _release_configuration(product)
    char_keys, subchar_keys, measure_keys = parse_release_configuration(
        ReleaseConfigurationSerializer(release_configuration).data,
    )

    rng = random.Random(repository.id)
    characteristics = {}
    tsqmi_history = []

    for step in range(DEMO_COLLECTIONS):
        created_at = (now - timedelta(days=DEMO_INTERVAL_DAYS * (DEMO_COLLECTIONS - 1 - step))).isoformat()
        services = MathModelServices(repository, product)

        collected = services.build_collected_metrics(build_demo_payload(rng, step, DEMO_COLLECTIONS))
        _, measure_values = services.build_calculated_measures(measure_keys, release_configuration, collected)
        _, subchar_values = services.build_calculated_subcharacteristics(
            subchar_keys, release_configuration, measure_values
        )
        chars, char_values = services.build_calculated_characteristics(
            char_keys, release_configuration, subchar_values
        )
        tsqmi = services.build_tsqmi(release_configuration, char_values)

        for calculated in chars:
            supported = calculated.characteristic
            entry = characteristics.setdefault(
                supported.key,
                {
                    "id": supported.id,
                    "key": supported.key,
                    "name": supported.name,
                    "description": supported.description,
                    "history": [],
                },
            )
            entry["history"].append(
                {
                    "id": None,
                    "characteristic_id": supported.id,
                    "value": calculated.value,
                    "created_at": created_at,
                }
            )
        tsqmi_history.append({"id": None, "value": tsqmi.value, "created_at": created_at})

    results = list(characteristics.values())
    return {
        "is_demo": True,
        "notice": DEMO_NOTICE,
        "generated_at": now.isoformat(),
        "latest_tsqmi": tsqmi_history[-1],
        "tsqmi_history": tsqmi_history,
        "historical_characteristics": {"count": len(results), "results": results},
    }
