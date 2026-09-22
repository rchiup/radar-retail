import asyncio, json
from pathlib import Path
from playwright.async_api import async_playwright

OUT = Path(r"backend/data/screenshots")
OUT.mkdir(parents=True, exist_ok=True)

CASES = [
    {
        "name": "walmart_mobile",
        "url": "https://www.lider.cl/supermercado/product/sku/00120013001946",
    },
    {
        "name": "ripley_mobile",
        "url": "https://simple.ripley.cl/jbl-charge-6-2000388472024p",
    },
]

async def probe(case):
    result = {"name": case["name"], "url": case["url"]}
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = await browser.new_context(
            **pw.devices["iPhone 13"],
            locale="es-CL",
        )
        page = await context.new_page()
        try:
            resp = await page.goto(case["url"], wait_until="domcontentloaded", timeout=35000)
            result["http_status"] = resp.status if resp else None
            try:
                await page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass
            html = (await page.content()).lower()
            text = ""
            try:
                text = await page.locator("body").inner_text(timeout=4000)
            except Exception:
                pass
            markers = [
                "un paso más", "just a moment", "robot or human", "captcha",
                "cf-browser-verification", "checking your browser",
            ]
            result["challenge_like"] = any(m in html or m in text.lower() for m in markers)
            # chilean prices
            import re
            prices = [int(m.replace(".", "")) for m in re.findall(r"\$\s*(\d{1,3}(?:\.\d{3})+)", text)]
            prices = [p for p in prices if 500 <= p <= 50_000_000]
            result["prices_found"] = prices[:5]
            shot = OUT / f"mobile-probe-{case['name']}.png"
            await page.screenshot(path=str(shot), full_page=True)
            result["screenshot"] = str(shot)
            result["screenshot_bytes"] = shot.stat().st_size
            result["title"] = await page.title()
            result["text_sample"] = text[:240].replace("\n", " ")
        except Exception as exc:
            result["error"] = str(exc)[:300]
        finally:
            await browser.close()
    return result

async def main():
    rows = []
    for case in CASES:
        rows.append(await probe(case))
    Path("backend/data/smoke-results").mkdir(parents=True, exist_ok=True)
    Path("backend/data/smoke-results/mobile_probe.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(rows, ensure_ascii=False, indent=2))

asyncio.run(main())
