"""Sodimac Chile.

Served from sodimac.falabella.com, not www.sodimac.cl: the latter answers 200 for any
product path and silently redirects to its home page, which would look like a product
page with no price.
"""

from .browser import PlaywrightFetcher
from .curl import CurlFetcher
from .falabella_cl import FalabellaPlatform


class SodimacCL(FalabellaPlatform):
    URL_TEMPLATE = "https://sodimac.falabella.com/sodimac-cl/product/{sku}"


class SodimacCurl(SodimacCL, CurlFetcher): pass
class SodimacPlaywright(SodimacCL, PlaywrightFetcher): pass
