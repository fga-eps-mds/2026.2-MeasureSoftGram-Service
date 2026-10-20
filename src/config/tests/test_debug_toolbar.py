from django.test import RequestFactory, SimpleTestCase, override_settings

from config.debug_toolbar import show_toolbar_for_pages

AXIOS_ACCEPT = "application/json, text/plain, */*"
BROWSER_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"


@override_settings(DEBUG=True, INTERNAL_IPS=["127.0.0.1"])
class ShowToolbarForPagesTestCase(SimpleTestCase):
    def request(self, accept):
        return RequestFactory().get("/api/v1/organizations/", HTTP_ACCEPT=accept, REMOTE_ADDR="127.0.0.1")

    def test_shows_on_html_pages(self):
        self.assertTrue(show_toolbar_for_pages(self.request(BROWSER_ACCEPT)))

    def test_skips_json_calls_from_the_front(self):
        self.assertFalse(show_toolbar_for_pages(self.request(AXIOS_ACCEPT)))

    @override_settings(DEBUG=False)
    def test_never_shows_without_debug(self):
        self.assertFalse(show_toolbar_for_pages(self.request(BROWSER_ACCEPT)))
