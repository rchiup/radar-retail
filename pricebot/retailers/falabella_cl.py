"""Falabella Chile, and the storefront platform it shares with Sodimac and Tottus.

The three run the same software on different hosts, so they share everything except
the URL template. See sodimac_cl.py and tottus_cl.py.
"""

from .browser import PlaywrightFetcher
from .curl import CurlFetcher


class FalabellaPlatform:
    """Settings common to every storefront on Falabella's platform."""

    # Sodimac and Tottus answer 200 with a "page not found" body for a missing SKU;
    # falabella.com returns its search-style phrase. Both are absent from valid
    # product pages on all three hosts — verified before adding either.
    NOT_FOUND_MARKERS = ("no encontramos resultados", "página no encontrada")
    WAIT_SELECTOR = '[class*="price"], [data-internet-price], [class*="Price"]'
    LOCALE = "es-CL"
    TIMEZONE = "America/Santiago"


class FalabellaCL(FalabellaPlatform):
    URL_TEMPLATE = "https://www.falabella.com/falabella-cl/product/{sku}"


class FalabellaCurl(FalabellaCL, CurlFetcher): pass
class FalabellaPlaywright(FalabellaCL, PlaywrightFetcher): pass
