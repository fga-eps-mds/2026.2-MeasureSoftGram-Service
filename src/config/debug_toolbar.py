"""
Quando o django-debug-toolbar entra em ação no ambiente de desenvolvimento.
"""

from debug_toolbar.middleware import show_toolbar


def show_toolbar_for_pages(request) -> bool:
    """
    O toolbar só aparece em páginas HTML (admin, API navegável do DRF). As chamadas JSON do front
    pagavam a instrumentação dele (SQL, cache, sinais, templates) sem nunca exibi-lo: ~45% a mais
    de tempo por requisição no runserver.
    """
    return show_toolbar(request) and "text/html" in request.headers.get("Accept", "")
