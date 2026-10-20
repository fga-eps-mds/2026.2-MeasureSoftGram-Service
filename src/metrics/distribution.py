from datetime import timedelta
from statistics import fmean, pstdev, quantiles

from metrics.models import CollectedMetric
from releases.window import latest_in_release_window

# As linhas de uma coleta têm created_at um pouco diferentes (cada CollectedMetric
# recebe o próprio timezone.now()). Mesma tolerância de
# SupportedMetric.get_latest_metric_values (metrics/models.py:113).
COLLECTION_TOLERANCE = timedelta(minutes=20)


def summarize(values):
    """
    Resumo estatístico dos valores de uma métrica entre os arquivos (CA3).

    Quartis pelo método `inclusive` (o `linear` do NumPy). O desvio padrão é
    populacional, porque os arquivos do repositório são a população inteira.
    """
    if not values:
        return None

    ordered = sorted(values)
    if len(ordered) == 1:
        # no Python 3.12, `quantiles` exige pelo menos dois valores
        q1 = median = q3 = ordered[0]
    else:
        q1, median, q3 = quantiles(ordered, n=4, method="inclusive")

    return {
        "count": len(ordered),
        "min": ordered[0],
        "q1": q1,
        "median": median,
        "q3": q3,
        "max": ordered[-1],
        "mean": fmean(ordered),
        "std_dev": pstdev(ordered),
    }


def _latest_value_by_path(queryset):
    values = {}
    for path, value in queryset.order_by("-created_at").values_list("path", "value"):
        values.setdefault(path, value)
    return values


def get_repository_distribution(repository, metric_key, release):
    """
    Valores por arquivo de uma métrica na última coleta do repositório dentro
    da janela da release (CA7). Arquivos com ncloc = 0 ficam fora, como em
    MathModelServices._resolve_metric_params_in_memory.
    """
    file_rows = CollectedMetric.objects.filter(repository=repository, qualifier="FIL")
    # âncora: a última linha da coleta, de qualquer métrica, para que o ncloc gravado
    # logo depois da métrica pedida (na mesma coleta) fique dentro da janela
    anchor = latest_in_release_window(file_rows, release)
    if anchor is None:
        return {"collected_at": None, "excluded_files": 0, "summary": None, "files": []}

    collection = file_rows.filter(
        created_at__gte=max(anchor.created_at - COLLECTION_TOLERANCE, release.start_at),
        created_at__lte=anchor.created_at,
    )
    ncloc_by_path = _latest_value_by_path(collection.filter(metric__key="ncloc"))
    empty_paths = {path for path, ncloc in ncloc_by_path.items() if ncloc == 0}
    value_by_path = _latest_value_by_path(collection.filter(metric__key=metric_key))

    files = [
        {"path": path, "value": value}
        for path, value in sorted(value_by_path.items())
        if path not in empty_paths
    ]
    return {
        "collected_at": anchor.created_at,
        "excluded_files": len(value_by_path) - len(files),
        "summary": summarize([file["value"] for file in files]),
        "files": files,
    }
