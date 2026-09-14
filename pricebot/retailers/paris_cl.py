"""Paris Chile.

A SKU alone resolves: https://www.paris.cl/<sku>.html redirects to the slug URL.
The server HTML carries no JSON-LD, so prices come from the CSS fallback.
"""

from .browser import PlaywrightFetcher
from .curl import CurlFetcher


class ParisCL:
    URL_TEMPLATE = "https://www.paris.cl/{sku}.html"
    NOT_FOUND_MARKERS = ("no encontramos resultados", "página no encontrada")
    WAIT_SELECTOR = '[class*="price"], [class*="Price"]'
    LOCALE = "es-CL"
    TIMEZONE = "America/Santiago"


class ParisCurl(ParisCL, CurlFetcher): pass
class ParisPlaywright(ParisCL, PlaywrightFetcher): pass
