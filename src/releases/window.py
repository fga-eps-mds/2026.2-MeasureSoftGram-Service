"""
Regra da janela da release, compartilhada pelos gráficos do MSG21
(TASK21.02.01, 21.03.01 e 21.04.01): um valor pertence à release quando
foi criado entre `start_at` e `end_at`, inclusive.
"""


def in_release_window(queryset, release):
    return queryset.filter(
        created_at__gte=release.start_at,
        created_at__lte=release.end_at,
    )


def latest_in_release_window(queryset, release):
    return in_release_window(queryset, release).order_by("-created_at").first()
