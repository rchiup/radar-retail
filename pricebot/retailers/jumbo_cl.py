"""Jumbo Chile (VTEX).

Product URLs are https://www.jumbo.cl/<slug>-<sku>/p and the slug is NOT optional —
a SKU alone gives a 404 — so every product needs its link.
"""

from .browser import PlaywrightFetcher
from .curl import CurlFetcher


class JumboCL:
    URL_TEMPLATE = ""  # requires a link per product
    NOT_FOUND_MARKERS = ("página no encontrada", "not found")
    WAIT_SELECTOR = '[class*="price"], [class*="Price"]'
    LOCALE = "es-CL"
    TIMEZONE = "America/Santiago"


class JumboCurl(JumboCL, CurlFetcher): pass
class JumboPlaywright(JumboCL, PlaywrightFetcher): pass
