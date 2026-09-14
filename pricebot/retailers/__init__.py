"""Retailer registry.

Adding a retailer:
  1. create a module next to `falabella_cl.py` with a settings class plus one
     subclass per transport (`CurlFetcher`, `PlaywrightFetcher`);
  2. register it below under the key callers pass as `retail`.
"""

from .abc_cl import AbcCurl, AbcPlaywright
from .base import ProductFetcher
from .claro_cl import ClaroCurl, ClaroPlaywright
from .easy_cl import EasyCurl, EasyPlaywright
from .falabella_cl import FalabellaCurl, FalabellaPlaywright
from .hites_cl import HitesCurl, HitesPlaywright
from .jumbo_cl import JumboCurl, JumboPlaywright
from .paris_cl import ParisCurl, ParisPlaywright
from .ripley_cl import RipleyCurl, RipleyPlaywright
from .sodimac_cl import SodimacCurl, SodimacPlaywright
from .tottus_cl import TottusCurl, TottusPlaywright
from .walmart_cl import WalmartCurl, WalmartPlaywright

RETAILERS: dict = {
    "abc_cl":       {"curl": AbcCurl,       "playwright": AbcPlaywright},
    "claro_cl":     {"curl": ClaroCurl,     "playwright": ClaroPlaywright},
    "easy_cl":      {"curl": EasyCurl,      "playwright": EasyPlaywright},
    "falabella_cl": {"curl": FalabellaCurl, "playwright": FalabellaPlaywright},
    "hites_cl":     {"curl": HitesCurl,     "playwright": HitesPlaywright},
    "jumbo_cl":     {"curl": JumboCurl,     "playwright": JumboPlaywright},
    "paris_cl":     {"curl": ParisCurl,     "playwright": ParisPlaywright},
    "ripley_cl":    {"curl": RipleyCurl,    "playwright": RipleyPlaywright},
    "sodimac_cl":   {"curl": SodimacCurl,   "playwright": SodimacPlaywright},
    "tottus_cl":    {"curl": TottusCurl,    "playwright": TottusPlaywright},
    "walmart_cl":   {"curl": WalmartCurl,   "playwright": WalmartPlaywright},
}


def get_fetcher(retail: str, method: str) -> ProductFetcher:
    """Instantiate the fetcher for a retailer and fetch method."""
    key = (retail or "").strip().lower()
    transports = RETAILERS.get(key)
    if transports is None:
        raise ValueError(
            f"Unknown retail {retail!r}. Known retailers: {', '.join(sorted(RETAILERS))}"
        )
    fetcher_class = transports.get(method)
    if fetcher_class is None:
        raise ValueError(
            f"Retail {key!r} has no {method!r} transport. "
            f"Available: {', '.join(sorted(transports))}"
        )
    return fetcher_class()


def known_retailers() -> list:
    return sorted(RETAILERS)
