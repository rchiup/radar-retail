"""Discover public JBL product URLs for a test workbook.

This intentionally uses conservative requests, one domain at a time, with a delay.
It never bypasses CAPTCHA/Cloudflare; blocked domains are reported in the output.
"""
import csv, html, re, time
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen

OUT = Path("outputs/jbl-stress-test")
OUT.mkdir(parents=True, exist_ok=True)
TARGETS = {
    "abc_cl": "https://www.abc.cl/tecnologia/audio/parlantes-portatiles/jbl/",
    "jumbo_cl": "https://www.jumbo.cl/search?query=jbl",
    "hites_cl": "https://www.hites.com/especiales/tecnologia/audifonos-y-parlantes-bluetooth/f/jbl/",
    "tottus_cl": "https://tottus.falabella.com/tottus-cl/search?Ntt=jbl",
    "movistar": "https://tienda.movistar.cl/catalogsearch/result/?q=jbl",
    "entel": "https://store.entel.cl/search?q=jbl",
    "claro": "https://catalogo.clarochile.cl/search?q=jbl",
    "falabella_cl": "https://www.falabella.com/falabella-cl/brand/JBL",
    "mercado_libre": "https://listado.mercadolibre.cl/jbl",
    "walmart_cl": "https://www.lider.cl/catalogo/searchresult?Ntt=jbl",
    "ripley_cl": "https://simple.ripley.cl/search/jbl",
    "sodimac_cl": "https://www.sodimac.cl/sodimac-cl/marca/JBL",
    "easy_cl": "https://www.easy.cl/easy-cl/search?text=jbl",
    "paris_cl": "https://www.paris.cl/electro/audio/parlantes-bluetooth-portables/parlantes-bluetooh-y-portables/jbl/",
}
PRODUCT_HINTS = ("/product/", "/articulo/", ".html", "/p/", "-jbl-")
BAD_HINTS = ("/search", "/category/", "/marca/", "/brand/", "/catalogo", "/lista/", "/especiales/", "?q=", "?ntt=")

def fetch(url: str) -> tuple[str, int, str]:
    req = Request(url, headers={"User-Agent": "RadarRetailResearch/1.0 (contacto del proyecto)"})
    try:
        with urlopen(req, timeout=20) as response:
            return response.read().decode("utf-8", "ignore"), response.status, ""
    except Exception as exc:
        return "", 0, str(exc)[:180]

def discover(retailer: str, page_url: str) -> list[dict]:
    body, status, error = fetch(page_url)
    if error:
        return [{"retailer": retailer, "url": "", "status": f"fetch_error: {error}", "verified": "no"}]
    urls = []
    for raw in re.findall(r"(?:href|data-href)=[\"']([^\"']+)[\"']", body, flags=re.I):
        candidate = html.unescape(urljoin(page_url, raw)).split("#", 1)[0]
        low = candidate.lower()
        if "jbl" not in low and "jbl" not in body[max(0, body.find(raw)-200):body.find(raw)+200].lower():
            continue
        if any(h in low for h in PRODUCT_HINTS) and not any(h in low for h in BAD_HINTS):
            if candidate not in urls:
                urls.append(candidate)
        if len(urls) >= 12:
            break
    if not urls:
        return [{"retailer": retailer, "url": "", "status": f"no_product_links_http_{status}", "verified": "no"}]
    return [{"retailer": retailer, "url": u, "status": f"http_{status}", "verified": "candidate"} for u in urls]

rows = []
for retailer, page in TARGETS.items():
    print(f"{retailer}: {page}")
    rows.extend(discover(retailer, page))
    time.sleep(2)
with (OUT / "jbl-direct-links.csv").open("w", newline="", encoding="utf-8-sig") as fh:
    writer = csv.DictWriter(fh, fieldnames=["retailer", "url", "status", "verified"])
    writer.writeheader(); writer.writerows(rows)
print(f"saved {len(rows)} rows")
