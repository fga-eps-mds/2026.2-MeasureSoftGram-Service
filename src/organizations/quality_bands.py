"""
Faixas de qualidade do produto (US30.01): a régua de 0 a 1 que pinta os gráficos e os badges.

São 5 faixas, da pior para a melhor (E a A), separadas por 4 cortes. O produto guarda só os
cortes em `Product.quality_band_limits`; `None` quer dizer que ele nunca alterou a régua e usa
os padrões daqui. O `GRADE_MAP` de `utils/badge.py` ainda repete esses cortes até a US30.03.
"""

from decimal import Decimal

BAND_KEYS = ("E", "D", "C", "B", "A")

DEFAULT_LIMITS = (Decimal("0.20"), Decimal("0.40"), Decimal("0.60"), Decimal("0.80"))

LOWEST = Decimal("0")
HIGHEST = Decimal("1")


def get_limits(product) -> tuple:
    """Os 4 cortes do produto, ou os padrões se ele nunca alterou as faixas."""
    if product.quality_band_limits is None:
        return DEFAULT_LIMITS
    return tuple(Decimal(str(limit)) for limit in product.quality_band_limits)


def build_bands(limits) -> list:
    """As 5 faixas de E a A: a primeira começa em 0, a última termina em 1 e o fim de uma é o início da seguinte."""
    edges = (LOWEST, *limits, HIGHEST)
    return [{"key": key, "min": edges[index], "max": edges[index + 1]} for index, key in enumerate(BAND_KEYS)]


def serialize(product, can_edit: bool) -> dict:
    return {
        "is_default": product.quality_band_limits is None,
        "can_edit": can_edit,
        "bands": [
            {"key": band["key"], "min": float(band["min"]), "max": float(band["max"])}
            for band in build_bands(get_limits(product))
        ],
    }


def format_limit(value: Decimal) -> str:
    """Limite como aparece na tela: duas casas e vírgula decimal (0,40)."""
    return f"{value:.2f}".replace(".", ",")


def error(band, field: str, detail: str) -> dict:
    return {"band": band, "field": field, "detail": detail}


def validate_bands(bands: list) -> list:
    """
    Erros de uma régua recebida no `PUT`, um por faixa e campo; lista vazia se ela for válida.

    Cada faixa precisa vir na ordem de E a A, começar onde a anterior termina (sem buraco nem
    sobreposição) e terminar depois de começar. A primeira começa em 0 e a última termina em 1;
    os valores ficam entre 0 e 1.
    """
    if [band["key"] for band in bands] != list(BAND_KEYS):
        return [error(None, "key", "Envie as 5 faixas na ordem E, D, C, B e A.")]

    return _range_errors(bands) or [*_edge_errors(bands), *_continuity_errors(bands)]


def _range_errors(bands: list) -> list:
    return [
        error(band["key"], field, "Use um valor entre 0 e 1.")
        for band in bands
        for field in ("min", "max")
        if not LOWEST <= band[field] <= HIGHEST
    ]


def _edge_errors(bands: list) -> list:
    errors = []
    if bands[0]["min"] != LOWEST:
        errors.append(error("E", "min", "A faixa E começa em 0."))
    if bands[-1]["max"] != HIGHEST:
        errors.append(error("A", "max", "A faixa A termina em 1."))
    return errors


def _continuity_errors(bands: list) -> list:
    errors = []
    for index, band in enumerate(bands):
        previous = bands[index - 1] if index > 0 else None
        if previous and band["min"] != previous["max"]:
            detail = f"A faixa {band['key']} começa onde a faixa {previous['key']} termina "
            errors.append(error(band["key"], "min", detail + f"({format_limit(previous['max'])})."))
        elif index == len(bands) - 1:
            # a faixa A termina em 1 (se não terminar, o erro já é o de _edge_errors): quem a esvazia é o fim da B
            if band["max"] == HIGHEST and band["max"] <= band["min"]:
                detail = f"O limite precisa ser menor que {format_limit(HIGHEST)}."
                errors.append(error(previous["key"], "max", detail))
        elif band["max"] <= band["min"]:
            errors.append(error(band["key"], "max", f"O limite precisa ser maior que {format_limit(band['min'])}."))
    return errors


def field_errors(serializer_errors: dict, data) -> list:
    """
    Os erros de formato do serializer (número inválido, casas decimais) no mesmo formato de
    `validate_bands`. O DRF indexa os erros de uma lista pela posição, como texto ou número.
    """
    bands_errors = serializer_errors.get("bands")
    items = bands_errors.items() if isinstance(bands_errors, dict) else enumerate(bands_errors or [])
    # sem a lista, ou com a lista num formato inesperado, o DRF manda mensagens soltas em vez de erros por faixa
    items = [(int(index), fields) for index, fields in items if str(index).isdigit() and isinstance(fields, dict)]
    shape_error = error(None, "bands", "Envie as 5 faixas na ordem E, D, C, B e A.")
    if not items:
        return [shape_error]

    sent = data.get("bands") if isinstance(data, dict) else None
    errors = []
    for position, fields in items:
        band = sent[position].get("key") if isinstance(sent, list) and isinstance(sent[position], dict) else None
        for field, messages in fields.items():
            if field not in ("key", "min", "max"):
                # a faixa não veio como objeto com key, min e max
                errors.append(shape_error)
                continue
            errors.extend(error(band, field, str(message)) for message in messages)
    # com alguma faixa fora do formato, o erro de formato vale para a régua toda: uma vez só
    return [shape_error] if shape_error in errors else errors


def limits_of(bands: list):
    """
    Os 4 cortes de uma régua válida, como texto para o JSON não perder as casas decimais.
    Cortes iguais aos padrões viram `None`: o produto volta a seguir os padrões.
    """
    limits = tuple(band["max"] for band in bands[:-1])
    if limits == DEFAULT_LIMITS:
        return None
    return [str(limit) for limit in limits]
