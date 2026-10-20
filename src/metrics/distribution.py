from statistics import fmean, pstdev, quantiles


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
