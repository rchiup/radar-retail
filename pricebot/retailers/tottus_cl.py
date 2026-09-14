"""Tottus Chile. Same platform as Falabella, different host."""

from .browser import PlaywrightFetcher
from .curl import CurlFetcher
from .falabella_cl import FalabellaPlatform


class TottusCL(FalabellaPlatform):
    URL_TEMPLATE = "https://tottus.falabella.com/tottus-cl/product/{sku}"


class TottusCurl(TottusCL, CurlFetcher): pass
class TottusPlaywright(TottusCL, PlaywrightFetcher): pass
