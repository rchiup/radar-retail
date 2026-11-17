import csv
import hashlib
import hmac
import io
import importlib.util
import ipaddress
import logging
import math
import json
import os
import re
import secrets
import sqlite3
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal
from urllib.parse import quote_plus, urlparse
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from openpyxl import load_workbook
from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from pricebot import fetch_price, fetch_prices, known_retailers
from backend.cloud_scraper import (
    CloudConfigError,
    assert_retail_cloud_allowed,
    webhook_requirement_note,
)


logger = logging.getLogger("radar-retail")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s radar %(message)s")
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)


BASE_DIR = Path(__file__).resolve().parent
DIST_DIR = BASE_DIR.parent / "dist"
DATA_DIR = Path(os.getenv("RADAR_DATA_DIR", BASE_DIR / "data"))
SCREENSHOTS_DIR = Path(os.getenv("RADAR_SCREENSHOTS_DIR", DATA_DIR / "screenshots"))
DB_PATH = DATA_DIR / "radar-retail.sqlite3"
LOG_PATH = Path(os.getenv("RADAR_LOG_PATH", DATA_DIR / "radar-retail.log"))
MAX_UPLOAD_BYTES = 12 * 1024 * 1024
MAX_PRODUCTS = 5_000

DATA_DIR.mkdir(parents=True, exist_ok=True)
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
try:
    file_handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s radar %(message)s"))
    logging.getLogger().addHandler(file_handler)
except OSError:
    logger.warning("event=log_file_unavailable path=%s", LOG_PATH)

app = FastAPI(title="Radar Retail API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/screenshots", StaticFiles(directory=SCREENSHOTS_DIR), name="screenshots")


# In-memory cancel flags for the current process. Survives only while the API is up.
_CANCEL_REQUESTED: set[str] = set()


class CampaignCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    client: str = Field(default="", max_length=120)
    start_date: date
    end_date: date


class CampaignRunRequest(BaseModel):
    method: Literal["curl", "playwright"] = "playwright"
    screenshot: bool = True
    only_failed: bool = False
    google_fallback: bool = True
    capture_mode: Literal["local", "cloud"] = "local"


class PriceRequest(BaseModel):
    retail: str = Field(..., examples=["falabella_cl"])
    sku: str | None = Field(default=None, examples=["145731903"])
    url: str | None = None
    method: Literal["curl", "playwright"] = "curl"
    screenshot: bool = True
    campaign: str | None = Field(default=None, examples=["Cyber lentes"])
    campaign_start: str | None = None
    campaign_end: str | None = None
    google_fallback: bool = True


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def config_value(name: str) -> str | None:
    """Read runtime config, falling back to an ignored local .env for development."""
    value = os.getenv(name)
    if value:
        return value.strip()
    local_env = BASE_DIR.parent / ".env"
    if local_env.exists():
        for line in local_env.read_text(encoding="utf-8").splitlines():
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


SESSION_COOKIE = "radar_session"
SESSION_SECONDS = 8 * 60 * 60
_LOGIN_ATTEMPTS: dict[str, list[float]] = {}


def local_request(request: Request) -> bool:
    """Only direct loopback development can run without an access key."""
    if os.getenv("RAILWAY_ENVIRONMENT_ID") or os.getenv("RADAR_REQUIRE_AUTH") == "1":
        return False
    peer = request.client.host if request.client else ""
    hostname = request.url.hostname or ""
    return peer in {"127.0.0.1", "::1"} and hostname in {"127.0.0.1", "localhost", "::1"}


def valid_session(value: str | None, secret: str | None) -> bool:
    if not value or not secret:
        return False
    try:
        expires, nonce, signature = value.split(".")
        payload = f"{expires}.{nonce}"
        expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        return int(expires) > time.time() and hmac.compare_digest(signature, expected)
    except (ValueError, TypeError):
        return False


def authenticated(request: Request) -> bool:
    secret = config_value("RADAR_ACCESS_TOKEN")
    return (not secret and local_request(request)) or valid_session(request.cookies.get(SESSION_COOKIE), secret)


@app.middleware("http")
async def protect_private_data(request: Request, call_next):
    path = request.url.path
    protected = path.startswith(("/api/", "/screenshots/")) or path in {"/docs", "/redoc", "/openapi.json"}
    public = path in {"/api/health", "/api/auth/session", "/api/auth/login", "/api/auth/logout"}
    if protected and not public and not authenticated(request):
        configured = bool(config_value("RADAR_ACCESS_TOKEN"))
        return JSONResponse(
            {"detail": "Inicia sesión para acceder." if configured else "Configura RADAR_ACCESS_TOKEN en el servidor para habilitar el acceso remoto."},
            status_code=401 if configured else 503,
            headers={"Cache-Control": "no-store"},
        )
    if protected and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        origin = request.headers.get("origin")
        if origin:
            origin_url = urlparse(origin)
            same_origin = origin_url.netloc.lower() == request.url.netloc.lower()
            local_frontend = local_request(request) and origin_url.hostname in {"127.0.0.1", "localhost", "::1"}
            if not same_origin and not local_frontend:
                return JSONResponse({"detail": "Origen de solicitud no permitido."}, status_code=403)
    response = await call_next(request)
    if protected:
        response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    return response


class LoginRequest(BaseModel):
    token: str = Field(min_length=1, max_length=512)


@app.get("/api/auth/session")
def session_status(request: Request) -> dict:
    return {
        "authenticated": authenticated(request),
        "required": bool(config_value("RADAR_ACCESS_TOKEN")) or not local_request(request),
        "configured": bool(config_value("RADAR_ACCESS_TOKEN")),
    }


@app.post("/api/auth/login")
def login(payload: LoginRequest, request: Request) -> Response:
    secret = config_value("RADAR_ACCESS_TOKEN")
    if not secret:
        if local_request(request):
            return JSONResponse({"authenticated": True, "required": False, "configured": False})
        raise HTTPException(status_code=503, detail="El acceso remoto requiere RADAR_ACCESS_TOKEN configurado.")
    peer = request.client.host if request.client else "unknown"
    cutoff = time.time() - 900
    attempts = [stamp for stamp in _LOGIN_ATTEMPTS.get(peer, []) if stamp > cutoff]
    if len(attempts) >= 5:
        raise HTTPException(status_code=429, detail="Demasiados intentos. Intenta nuevamente en 15 minutos.")
    if not hmac.compare_digest(payload.token.encode(), secret.encode()):
        if len(_LOGIN_ATTEMPTS) > 1000:
            _LOGIN_ATTEMPTS.clear()
        _LOGIN_ATTEMPTS[peer] = [*attempts, time.time()]
        raise HTTPException(status_code=401, detail="Clave de acceso incorrecta.")
    _LOGIN_ATTEMPTS.pop(peer, None)
    cookie_payload = f"{int(time.time()) + SESSION_SECONDS}.{secrets.token_hex(16)}"
    signature = hmac.new(secret.encode(), cookie_payload.encode(), hashlib.sha256).hexdigest()
    response = JSONResponse({"authenticated": True, "required": True, "configured": True})
    response.set_cookie(
        SESSION_COOKIE, f"{cookie_payload}.{signature}", max_age=SESSION_SECONDS,
        httponly=True, secure=request.url.scheme == "https" or bool(os.getenv("RAILWAY_ENVIRONMENT_ID")),
        samesite="lax", path="/",
    )
    return response


@app.post("/api/auth/logout")
def logout() -> Response:
    response = JSONResponse({"authenticated": False})
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


def safe_url(value: str | None) -> str:
    """Keep query strings/tokens out of logs while preserving host and path."""
    if not value:
        return ""
    parsed = urlparse(value)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}" if parsed.netloc else "[url-invalida]"


def proxy_for_retailer(retailer: str) -> str | None:
    """Select an explicitly configured, authorized proxy profile per retailer."""
    specific = os.getenv(f"PRICEBOT_PROXY_{normalize_header(retailer).upper()}")
    return specific or os.getenv("PRICEBOT_PROXY") or None


def db() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


def init_db() -> None:
    with db() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS campaigns (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                client TEXT NOT NULL DEFAULT '',
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft',
                source_filename TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_run_at TEXT,
                last_error TEXT
            );

            CREATE TABLE IF NOT EXISTS products (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
                sku TEXT NOT NULL DEFAULT '',
                name TEXT NOT NULL DEFAULT 'Producto sin descripcion',
                category TEXT NOT NULL DEFAULT 'Sin categoria',
                retailer TEXT NOT NULL,
                url TEXT NOT NULL DEFAULT '',
                regular_price REAL NOT NULL DEFAULT 0,
                promo_price REAL NOT NULL DEFAULT 0,
                detected_price REAL,
                original_price REAL,
                status TEXT NOT NULL DEFAULT 'pending',
                captured_at TEXT,
                screenshot_url TEXT,
                fallback_screenshot_url TEXT,
                ip_used TEXT,
                error TEXT,
                evidence_source TEXT NOT NULL DEFAULT 'retailer',
                evidence_confidence TEXT NOT NULL DEFAULT 'official',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_products_campaign ON products(campaign_id);
            CREATE INDEX IF NOT EXISTS idx_products_status ON products(campaign_id, status);

            CREATE TABLE IF NOT EXISTS price_observations (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
                product_id TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
                sku TEXT NOT NULL DEFAULT '',
                retailer TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                price REAL,
                status TEXT NOT NULL,
                evidence_source TEXT NOT NULL DEFAULT 'retailer',
                screenshot_url TEXT,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_price_observations_product
                ON price_observations(sku, retailer, observed_at);

            CREATE TABLE IF NOT EXISTS comparable_prices (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
                group_id TEXT NOT NULL,
                sku TEXT NOT NULL,
                name TEXT NOT NULL DEFAULT '',
                retailer TEXT NOT NULL,
                price REAL NOT NULL,
                observed_at TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'import',
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_comparables_campaign
                ON comparable_prices(campaign_id, group_id);

            CREATE TABLE IF NOT EXISTS inventory_metrics (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
                sku TEXT NOT NULL,
                name TEXT NOT NULL DEFAULT '',
                retailer TEXT NOT NULL,
                stock REAL,
                sales_30d REAL,
                daily_sales REAL,
                lead_time_days REAL,
                safety_stock REAL NOT NULL DEFAULT 0,
                coverage_days REAL,
                risk TEXT NOT NULL DEFAULT 'insufficient',
                stockout_date TEXT,
                action TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_inventory_campaign_sku_retailer
                ON inventory_metrics(campaign_id, sku, retailer);
            """
        )
        for column, definition in (("fallback_screenshot_url", "TEXT"), ("evidence_source", "TEXT NOT NULL DEFAULT 'retailer'"), ("evidence_confidence", "TEXT NOT NULL DEFAULT 'official'")):
            try:
                connection.execute(f"ALTER TABLE products ADD COLUMN {column} {definition}")
            except sqlite3.OperationalError:
                pass
        for column, definition in (
            ("run_started_at", "TEXT"),
            ("run_ended_at", "TEXT"),
            ("capture_mode", "TEXT NOT NULL DEFAULT 'local'"),
            ("cloud_job_id", "TEXT"),
            ("cloud_status", "TEXT"),
        ):
            try:
                connection.execute(f"ALTER TABLE campaigns ADD COLUMN {column} {definition}")
            except sqlite3.OperationalError:
                pass
        try:
            connection.execute("ALTER TABLE campaigns ADD COLUMN is_demo INTEGER NOT NULL DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        connection.execute(
            "UPDATE products SET status = 'pending', error = 'La corrida anterior fue interrumpida.' WHERE status = 'running'"
        )
        connection.execute(
            "UPDATE campaigns SET status = 'ready', last_error = 'La corrida anterior fue interrumpida.' WHERE status = 'running'"
        )


init_db()


def normalize_header(header: str) -> str:
    return (
        str(header or "")
        .strip()
        .lower()
        .replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
        .replace("ñ", "n")
        .replace(" ", "_")
        .replace("-", "_")
    )


def normalize_retailer(value: str) -> str:
    aliases = {
        "abc": "abc_cl",
        "abc_cl": "abc_cl",
        "claro": "claro_cl",
        "claro_cl": "claro_cl",
        "falabella": "falabella_cl",
        "falabella_cl": "falabella_cl",
        "hites": "hites_cl",
        "hites_cl": "hites_cl",
        "sodimac": "sodimac_cl",
        "sodimac_cl": "sodimac_cl",
        "paris": "paris_cl",
        "paris_cl": "paris_cl",
        "ripley": "ripley_cl",
        "ripley_cl": "ripley_cl",
        "jumbo": "jumbo_cl",
        "jumbo_cl": "jumbo_cl",
        "easy": "easy_cl",
        "easy_cl": "easy_cl",
        "tottus": "tottus_cl",
        "tottus_cl": "tottus_cl",
        "walmart": "walmart_cl",
        "lider": "walmart_cl",
        "walmart_lider": "walmart_cl",
        "walmart_cl": "walmart_cl",
    }
    normalized = normalize_header(value)
    return aliases.get(normalized, normalized or "falabella_cl")


def pick(row: dict[str, str], keys: list[str]) -> str:
    return next((row[key].strip() for key in keys if row.get(key) and row[key].strip()), "")


def cell_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def parse_number(value: str) -> float:
    cleaned = str(value or "").strip().replace("$", "").replace(" ", "")
    if not cleaned:
        return 0
    if "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif cleaned.count(".") == 1 and len(cleaned.rsplit(".", 1)[1]) == 3:
        cleaned = cleaned.replace(".", "")
    cleaned = "".join(char for char in cleaned if char.isdigit() or char in ".-")
    try:
        return float(cleaned) if cleaned else 0
    except ValueError:
        return 0


def product_from_row(row: dict[str, str], default_retailer: str) -> dict[str, str | float]:
    return {
        "sku": pick(row, ["sku", "sku_retail", "id", "codigo"]),
        "name": pick(row, ["descripcion", "description", "nombre", "producto", "name"])
        or "Producto sin descripcion",
        "category": pick(row, ["categoria", "category"]) or "Sin categoria",
        "retailer": normalize_retailer(pick(row, ["retailer", "retail", "cadena", "tienda"]) or default_retailer),
        "url": pick(row, ["url", "link", "enlace"]),
        "regular_price": parse_number(
            pick(row, ["precio_base", "base_price", "precio", "own_price", "pvp", "precio_lista"])
        ),
        "promo_price": parse_number(
            pick(
                row,
                [
                    "precio_nuevo",
                    "new_price",
                    "target_price",
                    "precio_objetivo",
                    "pvp_descuento",
                    "precio_descuento",
                    "precio_campana",
                ],
            )
        ),
    }


def parse_campaign_file(filename: str, content: bytes) -> list[dict[str, str | float]]:
    suffix = Path(filename).suffix.lower()
    if suffix not in {".csv", ".xlsx"}:
        raise ValueError("Formato no soportado. Usa un archivo CSV o XLSX.")

    products: list[dict[str, str | float]] = []
    if suffix == ".xlsx":
        workbook = load_workbook(io.BytesIO(content), data_only=True, read_only=False)
        for sheet in workbook.worksheets:
            rows = list(sheet.iter_rows())
            if not rows:
                continue
            headers = [normalize_header(cell_text(cell.value)) for cell in rows[0]]
            default_retailer = normalize_retailer(sheet.title)
            for cells in rows[1:]:
                row: dict[str, str] = {}
                for index, cell in enumerate(cells):
                    if index >= len(headers) or not headers[index]:
                        continue
                    value = cell_text(cell.value)
                    if headers[index] in {"url", "link", "enlace"} and cell.hyperlink:
                        value = cell.hyperlink.target or value
                    row[headers[index]] = value
                product = product_from_row(row, default_retailer)
                if product["sku"] or product["url"]:
                    products.append(product)
                if len(products) > MAX_PRODUCTS:
                    raise ValueError(f"El archivo supera el máximo de {MAX_PRODUCTS} productos.")
    else:
        text = content.decode("utf-8-sig")
        sample = text[:4096]
        delimiter = ";" if sample.count(";") > sample.count(",") else ","
        reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
        default_retailer = normalize_retailer(Path(filename).stem)
        for raw_row in reader:
            row = {normalize_header(key): cell_text(value) for key, value in raw_row.items() if key}
            product = product_from_row(row, default_retailer)
            if product["sku"] or product["url"]:
                products.append(product)
            if len(products) > MAX_PRODUCTS:
                raise ValueError(f"El archivo supera el máximo de {MAX_PRODUCTS} productos.")

    unique: dict[tuple[str, str, str], dict[str, str | float]] = {}
    for product in products:
        key = (str(product["retailer"]), str(product["sku"]), str(product["url"]))
        unique[key] = product
    return list(unique.values())


def parse_tabular_file(filename: str, content: bytes) -> list[dict[str, str]]:
    """Read CSV/XLSX rows without guessing business meaning."""
    suffix = Path(filename).suffix.lower()
    if suffix not in {".csv", ".xlsx"}:
        raise ValueError("Formato no soportado. Usa un archivo CSV o XLSX.")
    rows: list[dict[str, str]] = []
    if suffix == ".xlsx":
        workbook = load_workbook(io.BytesIO(content), data_only=True, read_only=True)
        for sheet in workbook.worksheets:
            values = iter(sheet.iter_rows(values_only=True))
            first_row = next(values, None)
            if not first_row:
                continue
            headers = [normalize_header(cell_text(value)) for value in first_row]
            for cells in values:
                row = {
                    headers[index]: cell_text(value)
                    for index, value in enumerate(cells)
                    if index < len(headers) and headers[index]
                }
                if any(row.values()):
                    rows.append(row)
                    if len(rows) > MAX_PRODUCTS:
                        workbook.close()
                        raise ValueError(f"El archivo supera el máximo de {MAX_PRODUCTS} filas.")
        workbook.close()
    else:
        text = content.decode("utf-8-sig")
        sample = text[:4096]
        delimiter = ";" if sample.count(";") > sample.count(",") else ","
        reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
        rows = [
            {normalize_header(key): cell_text(value) for key, value in raw.items() if key}
            for raw in reader
            if any(cell_text(value) for value in raw.values())
        ]
    if len(rows) > MAX_PRODUCTS:
        raise ValueError(f"El archivo supera el máximo de {MAX_PRODUCTS} filas.")
    return rows


def inventory_row(row: dict[str, str]) -> dict:
    sku = pick(row, ["sku", "codigo", "id"])
    retailer = normalize_retailer(pick(row, ["retailer", "retail", "cadena", "tienda"]) or "general")
    stock_value = pick(row, ["stock", "inventario", "unidades"])
    sales_value = pick(row, ["ventas_30d", "sales_30d", "ventas_ultimos_30_dias"])
    daily_value = pick(row, ["venta_diaria", "daily_sales", "velocidad_venta"])
    lead_value = pick(row, ["lead_time", "lead_time_days", "plazo_reposicion", "dias_reposicion"])
    safety_value = pick(row, ["stock_seguridad", "safety_stock"])
    def nonnegative(value: str) -> float | None:
        if not value:
            return None
        numeric = value.strip().replace("$", "").replace(" ", "")
        if not re.fullmatch(r"\+?\d+(?:[.,]\d+)*", numeric):
            return None
        number = parse_number(numeric)
        return number if math.isfinite(number) and number >= 0 else None

    stock = nonnegative(stock_value)
    sales_30d = nonnegative(sales_value)
    daily_sales = nonnegative(daily_value) if daily_value else ((sales_30d / 30) if sales_30d is not None else None)
    lead_time = nonnegative(lead_value)
    safety_stock = nonnegative(safety_value) if safety_value else 0
    invalid = any(value and nonnegative(value) is None for value in [stock_value, sales_value, daily_value, lead_value, safety_value])
    if safety_stock is None:
        safety_stock = 0
    coverage = (max(stock - safety_stock, 0) / daily_sales) if stock is not None and daily_sales and daily_sales > 0 else None
    # Exhaustion uses physical stock; replenishment coverage reserves safety stock.
    stockout_date = (date.today() + timedelta(days=max(int(stock / daily_sales), 0))).isoformat() if stock is not None and daily_sales and daily_sales > 0 else None
    if invalid:
        risk = "insufficient"
        action = "Corregir datos inválidos o negativos; usa números mayores o iguales a cero."
        coverage = None
        stockout_date = None
    elif stock is not None and stock <= 0:
        coverage = 0
        risk = "critical"
        action = "Sin stock disponible: reponer ahora y revisar compromisos de venta."
        stockout_date = date.today().isoformat()
    elif stock is not None and daily_sales == 0 and lead_time is not None:
        risk = "low"
        action = "Sin ventas en el período informado; no se estima agotamiento. Revisar rotación."
        stockout_date = None
    elif coverage is None or lead_time is None:
        risk = "insufficient"
        action = "Completar stock, ventas y lead time para calcular el riesgo."
        stockout_date = None
    elif coverage <= lead_time:
        risk = "critical"
        action = f"Reponer ahora: la cobertura ({coverage:.1f} días) no alcanza el lead time ({lead_time:.0f} días)."
    elif coverage <= lead_time * 1.5:
        risk = "high"
        action = "Acelerar la orden de compra y revisar ventas diariamente."
    elif coverage <= lead_time * 2.5:
        risk = "medium"
        action = "Programar reposición y monitorear la velocidad de venta."
    else:
        risk = "low"
        action = "Cobertura saludable; mantener monitoreo semanal."
    return {
        "sku": sku,
        "name": pick(row, ["nombre", "name", "producto", "descripcion"]),
        "retailer": retailer,
        "stock": stock,
        "sales_30d": sales_30d,
        "daily_sales": daily_sales,
        "lead_time_days": lead_time,
        "safety_stock": safety_stock,
        "coverage_days": round(coverage, 1) if coverage is not None else None,
        "risk": risk,
        "stockout_date": stockout_date,
        "action": action,
    }


def validate_retail_url(retailer: str, url: str | None) -> None:
    if not url:
        return
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("La URL debe usar HTTPS.")
    try:
        address = ipaddress.ip_address(parsed.hostname)
        if address.is_private or address.is_loopback or address.is_link_local:
            raise ValueError("La URL apunta a una red no permitida.")
    except ValueError as exc:
        if "no permitida" in str(exc):
            raise
    allowed_domains = {
        "abc_cl": ("abc.cl",),
        "claro_cl": ("clarochile.cl", "tienda.clarochile.cl"),
        "falabella_cl": ("falabella.com",),
        "hites_cl": ("hites.com",),
        "sodimac_cl": ("sodimac.cl",),
        "paris_cl": ("paris.cl",),
        "ripley_cl": ("ripley.cl",),
        "jumbo_cl": ("jumbo.cl",),
        "easy_cl": ("easy.cl",),
        "tottus_cl": ("tottus.cl",),
        "walmart_cl": ("lider.cl", "walmart.cl"),
    }
    domains = allowed_domains.get(retailer, ())
    host = parsed.hostname.lower()
    if domains and not any(host == domain or host.endswith(f".{domain}") for domain in domains):
        raise ValueError(f"La URL no pertenece al dominio oficial de {retailer}.")


def slug(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip()).strip("-").lower()
    return cleaned[:70] or "campana"


def safe_csv(value: object) -> object:
    if isinstance(value, str) and value[:1] in {"=", "+", "-", "@"}:
        return f"'{value}"
    return value


def public_product(row: sqlite3.Row) -> dict:
    item = dict(row)
    item["regular_price"] = item["regular_price"] or 0
    item["promo_price"] = item["promo_price"] or 0
    detected = item.get("detected_price")
    target = item.get("promo_price")
    item["difference"] = (detected - target) if detected is not None and target else None
    return item


def campaign_payload(campaign_id: str) -> dict:
    with db() as connection:
        campaign = connection.execute("SELECT * FROM campaigns WHERE id = ?", (campaign_id,)).fetchone()
        if campaign is None:
            raise HTTPException(status_code=404, detail="Campaña no encontrada.")
        product_rows = connection.execute(
            "SELECT * FROM products WHERE campaign_id = ? ORDER BY created_at, sku", (campaign_id,)
        ).fetchall()

    products = [public_product(row) for row in product_rows]
    counts = {
        "total": len(products),
        "pending": sum(product["status"] == "pending" for product in products),
        "running": sum(product["status"] == "running" for product in products),
        "compliant": sum(product["status"] == "compliant" for product in products),
        "non_compliant": sum(product["status"] == "non_compliant" for product in products),
        "no_price": sum(product["status"] == "no_price" for product in products),
        "error": sum(product["status"] == "error" for product in products),
        "blocked": sum(product["status"] == "blocked" for product in products),
        "needs_review": sum(product["status"] == "needs_review" for product in products),
    }
    counts["processed"] = (
        counts["compliant"] + counts["non_compliant"] + counts["no_price"]
        + counts["error"] + counts["blocked"] + counts["needs_review"]
        + sum(product["status"] == "captured_unverified" for product in products)
    )
    counts["evidence_official"] = sum(
        bool(product.get("screenshot_url"))
        and product.get("evidence_source", "retailer") == "retailer"
        and product.get("detected_price") is not None
        for product in products
    )
    counts["evidence_google"] = sum(bool(product.get("fallback_screenshot_url")) for product in products)
    # Visual artifacts available in UI/ZIP (official and/or Google), without implying compliance.
    counts["evidence"] = sum(
        bool(product.get("screenshot_url") or product.get("fallback_screenshot_url"))
        for product in products
    )
    by_retailer: dict[str, int] = {}
    for product in products:
        by_retailer[product["retailer"]] = by_retailer.get(product["retailer"], 0) + 1
    counts["by_retailer"] = by_retailer
    return {**dict(campaign), "summary": counts, "products": products}


DEMO_RETAILERS = ["falabella_cl", "paris_cl", "ripley_cl", "walmart_cl", "abc_cl"]
DEMO_PRODUCTS = [
    ("JBLGO4", "JBL Go 4", 49990),
    ("JBLFLIP7", "JBL Flip 7", 129990),
    ("JBLCHARGE6", "JBL Charge 6", 189990),
    ("JBLXTREME4", "JBL Xtreme 4", 329990),
    ("JBLPB120", "JBL PartyBox Club 120", 429990),
    ("JBLT520", "JBL Tune 520BT", 44990),
    ("JBLT770", "JBL Tune 770NC", 109990),
    ("JBLWAVE", "JBL Wave Buds 2", 59990),
    ("JBLLIVE", "JBL Live Beam 3", 159990),
    ("JBLSB180", "JBL Soundbar SB180", 219990),
]


def seed_demo_campaign() -> dict:
    """Create a coherent offline demo. All rows are explicitly marked as synthetic."""
    with db() as connection:
        existing = connection.execute(
            "SELECT id FROM campaigns WHERE is_demo = 1 ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    if existing:
        return campaign_payload(existing["id"])

    campaign_id = uuid4().hex
    timestamp = now_iso()
    start = date.today() - timedelta(days=5)
    end = date.today() + timedelta(days=5)
    with db() as connection:
        connection.execute(
            """
            INSERT INTO campaigns
                (id, name, client, start_date, end_date, status, source_filename, created_at,
                 updated_at, last_run_at, run_started_at, run_ended_at, capture_mode, is_demo)
            VALUES (?, ?, ?, ?, ?, 'completed_with_errors', ?, ?, ?, ?, ?, ?, 'demo', 1)
            """,
            (
                campaign_id, "DEMO · Portafolio Audio Chile", "Datos ficticios",
                start.isoformat(), end.isoformat(), "demo-offline-50-sku.csv", timestamp,
                timestamp, timestamp, timestamp, timestamp,
            ),
        )
        for group_index, (base_sku, name, base_price) in enumerate(DEMO_PRODUCTS):
            for retail_index, retailer in enumerate(DEMO_RETAILERS):
                product_id = uuid4().hex
                sku = f"{base_sku}-{retail_index + 1:02d}"
                regular = round(base_price * (1.16 + retail_index * 0.018), -1)
                target = round(base_price * (0.94 + (retail_index % 2) * 0.015), -1)
                variation = ((group_index * 7 + retail_index * 11) % 19) - 8
                observed = round(target * (1 + variation / 100), -1)
                status = "compliant" if observed <= target else "non_compliant"
                connection.execute(
                    """
                    INSERT INTO products (
                        id, campaign_id, sku, name, category, retailer, url, regular_price,
                        promo_price, detected_price, status, captured_at, evidence_source,
                        evidence_confidence, error, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 'Audio', ?, '', ?, ?, ?, ?, ?, 'demo', 'demo', ?, ?, ?)
                    """,
                    (
                        product_id, campaign_id, sku, name, retailer, regular, target, observed,
                        status, timestamp,
                        "Dato DEMO: resultado simulado, sin pantallazo ni evidencia oficial.",
                        timestamp, timestamp,
                    ),
                )
                for week in range(6, -1, -1):
                    drift = ((group_index * 3 + retail_index * 5 + week * 2) % 13) - 6
                    historic_price = observed if week == 0 else round(observed * (1 + drift / 100), -1)
                    historic_status = "compliant" if historic_price <= target else "non_compliant"
                    observed_at = (datetime.now().astimezone() - timedelta(days=week * 7)).isoformat(timespec="seconds")
                    connection.execute(
                        """
                        INSERT INTO price_observations
                            (id, campaign_id, product_id, sku, retailer, observed_at, price,
                             status, evidence_source, screenshot_url, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'demo', NULL, ?)
                        """,
                        (uuid4().hex, campaign_id, product_id, sku, retailer, observed_at, historic_price, historic_status, timestamp),
                    )
                connection.execute(
                    """
                    INSERT INTO comparable_prices
                        (id, campaign_id, group_id, sku, name, retailer, price, observed_at, source, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'demo', ?)
                    """,
                    (uuid4().hex, campaign_id, base_sku, sku, name, retailer, observed, timestamp, timestamp),
                )
                stock = 18 + ((group_index * 17 + retail_index * 13) % 130)
                sales_30d = 24 + ((group_index * 29 + retail_index * 19) % 170)
                lead_time = 7 + ((group_index + retail_index * 3) % 18)
                inventory = inventory_row({
                    "sku": sku,
                    "nombre": name,
                    "retailer": retailer,
                    "stock": str(stock),
                    "ventas_30d": str(sales_30d),
                    "lead_time": str(lead_time),
                    "stock_seguridad": str(5 + group_index % 8),
                })
                connection.execute(
                    """
                    INSERT INTO inventory_metrics
                        (id, campaign_id, sku, name, retailer, stock, sales_30d, daily_sales,
                         lead_time_days, safety_stock, coverage_days, risk, stockout_date,
                         action, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        uuid4().hex, campaign_id, inventory["sku"], inventory["name"], inventory["retailer"],
                        inventory["stock"], inventory["sales_30d"], inventory["daily_sales"],
                        inventory["lead_time_days"], inventory["safety_stock"], inventory["coverage_days"],
                        inventory["risk"], inventory["stockout_date"], inventory["action"], timestamp, timestamp,
                    ),
                )
    return campaign_payload(campaign_id)


def comparable_payload(campaign_id: str) -> dict:
    campaign_payload(campaign_id)
    with db() as connection:
        rows = [dict(row) for row in connection.execute(
            "SELECT * FROM comparable_prices WHERE campaign_id = ? ORDER BY group_id, price",
            (campaign_id,),
        ).fetchall()]
    # Preserve history, but compare only the latest price per explicit association.
    latest: dict[tuple[str, str, str], dict] = {}
    for row in rows:
        key = (row["group_id"], row["sku"], row["retailer"])
        if key not in latest or row["observed_at"] >= latest[key]["observed_at"]:
            latest[key] = row
    current_rows = list(latest.values())
    groups: list[dict] = []
    for group_id in sorted({row["group_id"] for row in rows}):
        items = sorted([row for row in current_rows if row["group_id"] == group_id], key=lambda item: item["price"])
        prices = [float(item["price"]) for item in items if item["price"] is not None]
        comparable = len({item["retailer"] for item in items}) >= 2
        groups.append({
            "group_id": group_id,
            "name": items[0]["name"] if items else group_id,
            "items": items,
            "history": [row for row in rows if row["group_id"] == group_id],
            "min_price": min(prices) if prices else None,
            "max_price": max(prices) if prices else None,
            "comparable": comparable,
            "gap": (max(prices) - min(prices)) if prices and comparable else None,
            "gap_percent": round(((max(prices) / min(prices)) - 1) * 100, 1) if prices and min(prices) and comparable else None,
        })
    return {"groups": groups, "count": len(current_rows), "history_count": len(rows), "group_count": len(groups)}


def inventory_payload(campaign_id: str) -> dict:
    campaign_payload(campaign_id)
    with db() as connection:
        rows = [dict(row) for row in connection.execute(
            "SELECT * FROM inventory_metrics WHERE campaign_id = ? ORDER BY CASE risk WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 WHEN 'low' THEN 4 ELSE 5 END, coverage_days",
            (campaign_id,),
        ).fetchall()]
    summary = {risk: sum(row["risk"] == risk for row in rows) for risk in ["critical", "high", "medium", "low", "insufficient"]}
    return {"items": rows, "count": len(rows), "summary": summary}


def intelligence_payload(campaign_id: str) -> dict:
    campaign = campaign_payload(campaign_id)
    comparables = comparable_payload(campaign_id)
    inventory = inventory_payload(campaign_id)
    processed = campaign["summary"]["compliant"] + campaign["summary"]["non_compliant"]
    compliance = round(campaign["summary"]["compliant"] / processed * 100, 1) if processed else None
    commercial_gaps = sorted(
        [product for product in campaign["products"] if product["status"] == "non_compliant" and product["difference"] is not None],
        key=lambda product: product["difference"], reverse=True,
    )
    actions = []
    critical_stock = inventory["summary"].get("critical", 0)
    if critical_stock:
        actions.append({"priority": "critical", "title": f"Reponer {critical_stock} SKU con quiebre inminente", "detail": "La cobertura es menor o igual al lead time.", "view": "inventory"})
    if campaign["summary"]["non_compliant"]:
        actions.append({"priority": "high", "title": f"Corregir {campaign['summary']['non_compliant']} incumplimientos promocionales", "detail": "El precio observado supera el precio acordado.", "view": "audit"})
    large_gaps = sum((group.get("gap_percent") or 0) >= 12 for group in comparables["groups"])
    if large_gaps:
        actions.append({"priority": "medium", "title": f"Revisar {large_gaps} brechas competitivas sobre 12%", "detail": "Existen equivalencias explícitas con dispersión relevante.", "view": "competition"})
    if not actions:
        actions.append({"priority": "low", "title": "Operación sin alertas críticas", "detail": "Mantener monitoreo y actualizar las fuentes.", "view": "audit"})
    missing_inputs = []
    if not processed:
        missing_inputs.append("precios observados y objetivos promocionales")
    if not inventory["count"] or inventory["summary"].get("insufficient", 0):
        missing_inputs.append("stock, ventas y lead time")
    if not comparables["count"]:
        missing_inputs.append("asociaciones de productos comparables")
    if missing_inputs:
        if len(actions) == 1 and actions[0]["priority"] == "low":
            actions.clear()
        actions.append({"priority": "medium", "title": "Completar datos para ampliar el diagnóstico", "detail": "Faltan: " + "; ".join(missing_inputs) + ".", "view": "audit"})
    return {
        "campaign_id": campaign_id,
        "is_demo": bool(campaign.get("is_demo")),
        "monitored_skus": campaign["summary"]["total"],
        "compliance_percent": compliance,
        "critical_alerts": critical_stock + campaign["summary"]["non_compliant"],
        "price_gap_total": round(sum(max(product["difference"] or 0, 0) for product in commercial_gaps), 0),
        "stock_risk": inventory["summary"],
        "top_gaps": commercial_gaps[:5],
        "actions": actions[:5],
        "comparable_groups": comparables["groups"][:6],
    }


def screenshot_font(size: int) -> ImageFont.ImageFont:
    candidates = [
        Path(os.getenv("WINDIR", "C:/Windows")) / "Fonts" / "arial.ttf",
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default(size=size)


def annotate_screenshot(path: Path, request: PriceRequest, result: dict, captured_at: datetime) -> None:
    if not path.exists():
        return
    with Image.open(path) as source:
        image = source.convert("RGB")
    banner_height = 108
    annotated = Image.new("RGB", (image.width, image.height + banner_height), "#101713")
    annotated.paste(image, (0, banner_height))
    draw = ImageDraw.Draw(annotated)
    font = screenshot_font(20)
    small_font = screenshot_font(16)
    price = result.get("new_price")
    price_text = f"${price:,.0f}".replace(",", ".") if isinstance(price, (int, float)) else "sin precio"
    timestamp = captured_at.strftime("%Y-%m-%d %H:%M:%S") + " Chile"
    campaign_range = ""
    if request.campaign_start or request.campaign_end:
        campaign_range = f" | Vigencia: {request.campaign_start or '-'} a {request.campaign_end or '-'}"
    source = str(result.get("evidence_source") or "retailer")
    public_seal = (os.getenv("RADAR_EVIDENCE_DISCLAIMER", "internal").strip().lower() == "public")
    if source == "google_reference" and public_seal:
        title = f"Referencia publica | {request.campaign or 'Campaña sin nombre'} | {request.retail}"
    else:
        title = f"Evidencia Radar Retail | {request.campaign or 'Campaña sin nombre'} | {request.retail}"
    detail = (
        f"Captura: {timestamp} | SKU: {request.sku or '-'} | Precio observado: {price_text}"
        f" | IP: {result.get('ip_used') or '-'}"
    )
    link = str(result.get("used_link") or request.url or "")
    draw.rectangle((0, 0, image.width, banner_height), fill="#101713")
    draw.text((24, 14), title[:150], fill="#F4F7F2", font=font)
    draw.text((24, 44), (detail + campaign_range)[:190], fill="#B7F36A", font=small_font)
    draw.text((24, 72), link[:190], fill="#D8E1D9", font=small_font)
    annotated.save(path, format="PNG", optimize=True)


def render_indirect_evidence_card(
    path: Path,
    *,
    retailer: str,
    sku: str,
    product_url: str | None,
    google_price: float | int | None,
    search_url: str,
    captured_at: datetime,
    note: str,
    source_label: str = "referencia pública de Google",
    confidence: Literal["low", "medium"] = "low",
) -> None:
    """Render a clearly identified derived reference, never an official screenshot."""
    path.parent.mkdir(parents=True, exist_ok=True)

    width, height = 1440, 900
    image = Image.new("RGB", (width, height), "#F4F6F2")
    draw = ImageDraw.Draw(image)
    title_font = screenshot_font(30)
    body_font = screenshot_font(22)
    small_font = screenshot_font(18)
    price_font = screenshot_font(64)
    brand_font = screenshot_font(20)

    # Soft SaaS header (not a retailer clone).
    draw.rectangle((0, 0, width, 96), fill="#13241B")
    draw.text((40, 30), "Radar Retail", fill="#C8F16D", font=brand_font)
    draw.text((200, 28), "Referencia de monitoreo", fill="#F4F7F2", font=title_font)

    confidence_label = "media" if confidence == "medium" else "baja"
    disclaimer = f"Fuente pública · confianza {confidence_label} · ficha generada, no es pantallazo oficial"
    draw.rectangle((0, 96, width, 148), fill="#3D2A12")
    draw.text((40, 110), disclaimer, fill="#F8E3B0", font=small_font)
    content_top = 180

    # Card body
    draw.rounded_rectangle((36, content_top, width - 36, height - 36), radius=24, fill="#FFFFFF")
    draw.rectangle((36, content_top, 48, height - 36), fill="#C8F16D")

    retailer_label = retailer.replace("_", " ").title()
    price_text = (
        f"${int(google_price):,}".replace(",", ".")
        if isinstance(google_price, (int, float))
        else "Sin precio"
    )

    y = content_top + 36
    draw.text((72, y), retailer_label, fill="#14231B", font=title_font)
    y += 48
    draw.text((72, y), f"SKU {sku or '-'}", fill="#435149", font=body_font)
    y += 56
    draw.text((72, y), price_text, fill="#1F6F4A", font=price_font)
    y += 90
    meta = [
        f"Fecha: {captured_at.strftime('%Y-%m-%d %H:%M:%S')} Chile",
        f"URL: {(product_url or '-')[:108]}",
        f"Fuente de precio: {source_label}",
        note[:140] if note else "",
    ]
    for line in meta:
        if not line:
            continue
        draw.text((72, y), line, fill="#718078", font=small_font)
        y += 36

    footer = "Radar Retail · referencia derivada de fuente pública · no oficial"
    draw.text((72, height - 78), footer, fill="#9AA59C", font=small_font)
    image.save(path, format="PNG", optimize=True)



def google_reference_fallback(retailer: str, sku: str, url: str | None, screenshot_path: Path | None) -> dict:
    """Evidencia secundaria desde Google + ficha recreada para uso interno de marca."""
    query = f"{retailer.replace('_', ' ')} {sku}" if sku else f"{retailer.replace('_', ' ')} {url or ''}"
    search_url = "https://www.google.com/search?q=" + quote_plus(query)
    captured_at = datetime.now().astimezone()
    result = {
        "new_price": None,
        "original_price": None,
        "used_link": search_url,
        "evidence_source": "google_reference",
        "evidence_confidence": "low",
        "ip_used": None,
        "error": "Recreacion interna desde Google (no oficial del retail)",
    }
    serp_path = None
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
            page = browser.new_page(locale="es-CL", viewport={"width": 1440, "height": 1100})
            response = page.goto(search_url, wait_until="domcontentloaded", timeout=20_000)
            body_text = page.locator("body").inner_text(timeout=5_000)
            prices = []
            for match in re.finditer(r"\$\s*(\d{1,3}(?:[.]\d{3})+)", body_text):
                value = int(match.group(1).replace(".", ""))
                if 500 <= value <= 50_000_000:
                    prices.append(value)
            if prices:
                result["new_price"] = prices[0]
            if screenshot_path:
                screenshot_path.parent.mkdir(parents=True, exist_ok=True)
                serp_path = screenshot_path.with_name(screenshot_path.stem + "-serp.png")
                page.screenshot(path=str(serp_path), full_page=True)
            result["http_status"] = response.status if response else None
            browser.close()
    except Exception as exc:
        result["error"] = f"Google fallback unavailable: {str(exc)[:180]}"
        logger.warning("event=google_fallback_failed retailer=%s sku=%s error=%s", retailer, sku, str(exc)[:180])

    if screenshot_path:
        render_indirect_evidence_card(
            screenshot_path,
            retailer=retailer,
            sku=sku,
            product_url=url,
            google_price=result.get("new_price"),
            search_url=search_url,
            captured_at=captured_at,
            note="Generada porque la ficha oficial no entrego precio (bloqueo, layout o sin dato).",
        )
        result["screenshot_path"] = str(screenshot_path)
        if serp_path and Path(serp_path).exists():
            result["serp_screenshot_path"] = str(serp_path)

    logger.info(
        "event=fallback_used retailer=%s sku=%s price=%s screenshot=%s",
        retailer,
        sku,
        result.get("new_price"),
        bool(result.get("screenshot_path")),
    )
    return result


def store_capture(
    product: sqlite3.Row,
    campaign: sqlite3.Row,
    options: CampaignRunRequest,
    outcome: dict | Exception,
    screenshot_path: Path | None,
) -> None:
    captured_at = datetime.now().astimezone()
    product_id = product["id"]
    if isinstance(outcome, Exception):
        proxy_secret = os.getenv("PRICEBOT_PROXY")
        message = str(outcome)
        if proxy_secret:
            message = message.replace(proxy_secret, "[protegido]")
        message = re.sub(r"https?://\S+", lambda match: safe_url(match.group(0)), message)
        logger.warning(
            "event=product_error campaign=%s retailer=%s sku=%s url=%s error=%s",
            campaign["id"], product["retailer"], product["sku"], safe_url(product["url"]), message[:240],
        )
        outcome = {"new_price": None, "original_price": None, "used_link": product["url"],
                   "error": message[:700], "evidence_source": "retailer",
                   "evidence_confidence": "official"}

    request = PriceRequest(
        retail=product["retailer"],
        sku=product["sku"] or None,
        url=product["url"] or None,
        method=options.method,
        screenshot=options.screenshot,
        campaign=campaign["name"],
        campaign_start=campaign["start_date"],
        campaign_end=campaign["end_date"],
    )
    # Search/category landings are not SKU-level evidence, even if the page
    # happens to contain prices for other products.
    parsed_path = urlparse(str(product["url"] or "")).path.lower()
    if any(marker in parsed_path for marker in ("/search", "searchresult", "/catalogo")):
        outcome["new_price"] = None
        outcome["error"] = "URL de búsqueda/categoría; se requiere ficha directa del SKU"
        outcome["evidence_source"] = "retailer"
        outcome["evidence_confidence"] = "official"
    if screenshot_path and screenshot_path.exists():
        # Ripley's mobile response can expose the price in public structured data
        # while rendering only its reviews component. Do not present that reviews
        # page as price evidence: replace it with a transparent structured-data card.
        if (
            product["retailer"] == "ripley_cl"
            and outcome.get("new_price") is not None
            and outcome.get("screenshot_focus") == "unavailable"
        ):
            render_indirect_evidence_card(
                screenshot_path,
                retailer="ripley_cl",
                sku=product["sku"],
                product_url=product["url"],
                google_price=outcome.get("new_price"),
                search_url=product["url"],
                captured_at=captured_at,
                note="La versión móvil entregó reseñas; el precio proviene del JSON-LD público de la ficha.",
                source_label="datos estructurados públicos de Ripley",
                confidence="medium",
            )
            outcome["evidence_source"] = "retailer_structured"
            outcome["evidence_confidence"] = "medium"
        else:
            annotate_screenshot(screenshot_path, request, outcome, captured_at)
    # If the official page is blocked/empty, keep it and add a separate Google
    # reference screenshot. Google evidence is never treated as official compliance.
    fallback = None
    fallback_path = None
    if options.google_fallback and outcome.get("new_price") is None:
        fallback_path = SCREENSHOTS_DIR / f"{slug(campaign['name'])}-{product['retailer']}-{slug(product['sku'] or 'url')}-google-{uuid4().hex[:10]}.png"
        fallback = google_reference_fallback(product["retailer"], product["sku"], product["url"], fallback_path)
        if fallback.get("screenshot_path"):
            annotate_screenshot(fallback_path, request, fallback, captured_at)
            # Keep Google as secondary reference only. Never copy its price into the
            # official observed price used for compliance decisions.
            outcome = {
                **outcome,
                "google_reference_price": fallback.get("new_price"),
                "fallback_screenshot_url": f"/screenshots/{fallback_path.name}",
                "evidence_source": "google_reference",
                "evidence_confidence": "low",
            }
            logger.info(
                "event=fallback_used campaign=%s retailer=%s sku=%s google_price=%s",
                campaign["id"], product["retailer"], product["sku"], fallback.get("new_price"),
            )
    detected = outcome.get("new_price")
    detected_number = float(detected) if isinstance(detected, (int, float)) else None
    if detected_number is not None and detected_number < 500:
        logger.warning("event=price_rejected_too_low campaign=%s retailer=%s sku=%s detected=%s", campaign["id"], product["retailer"], product["sku"], detected_number)
        detected_number = None
        outcome["new_price"] = None
        outcome["error"] = (outcome.get("error") or "") + " | Precio descartado por valor inválido"
    target = float(product["promo_price"] or 0)
    error_text = str(outcome.get("error") or "").lower()
    http_status = outcome.get("http_status")
    blocked_signals = (
        "anti-bot", "captcha", "cloudflare", "blocked", "http 403", "http 429",
        "403", "429", "robot or human",
    )
    is_blocked = (
        http_status in {403, 429}
        or any(signal in error_text for signal in blocked_signals)
        or "challenge" in error_text
    )
    if outcome.get("status") == "PRODUCT_NOT_FOUND":
        status = "no_price"
    elif is_blocked and detected_number is None:
        status = "blocked"
        outcome["error"] = (outcome.get("error") or "Acceso bloqueado por el retail") + " | Requiere revisión manual"
        logger.warning(
            "event=page_blocked campaign=%s retailer=%s sku=%s http_status=%s error=%s",
            campaign["id"], product["retailer"], product["sku"], http_status, str(outcome.get("error"))[:180],
        )
    elif detected_number is None and outcome.get("evidence_source") == "google_reference":
        status = "needs_review"
    elif detected_number is None:
        status = "no_price"
    elif outcome.get("evidence_source") == "google_reference":
        # Should not happen for official price, but keep defensive.
        status = "needs_review"
    elif not target:
        status = "captured_unverified"
    elif detected_number <= target:
        status = "compliant"
    else:
        status = "non_compliant"
    screenshot_url = f"/screenshots/{screenshot_path.name}" if screenshot_path and screenshot_path.exists() else None
    fallback_url = outcome.get("fallback_screenshot_url") if isinstance(outcome, dict) else None
    # Never promote Google reference screenshots to the official evidence slot.
    with db() as connection:
        connection.execute(
            """
            UPDATE products
            SET detected_price = ?, original_price = ?, status = ?, captured_at = ?, screenshot_url = ?,
                fallback_screenshot_url = ?, evidence_source = ?, evidence_confidence = ?,
                ip_used = ?, url = ?, error = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                detected_number,
                outcome.get("original_price"),
                status,
                captured_at.isoformat(timespec="seconds"),
                screenshot_url,
                fallback_url,
                outcome.get("evidence_source", "retailer"),
                outcome.get("evidence_confidence", "official"),
                outcome.get("ip_used"),
                outcome.get("used_link") or request.url or "",
                outcome.get("error"),
                now_iso(),
                product_id,
            ),
        )
        connection.execute(
            """
            INSERT INTO price_observations
                (id, campaign_id, product_id, sku, retailer, observed_at, price, status,
                 evidence_source, screenshot_url, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uuid4().hex,
                campaign["id"],
                product_id,
                product["sku"] or "",
                product["retailer"],
                captured_at.isoformat(timespec="seconds"),
                detected_number,
                status,
                outcome.get("evidence_source", "retailer"),
                screenshot_url or fallback_url,
                now_iso(),
            ),
        )
    logger.info(
        "event=product_result campaign=%s retailer=%s sku=%s status=%s detected=%s target=%s evidence=%s url=%s error=%s",
        campaign["id"], product["retailer"], product["sku"], status, detected_number, target,
        bool(screenshot_url), safe_url(outcome.get("used_link") or request.url),
        str(outcome.get("error") or "")[:180],
    )


def capture_batch(products: list[sqlite3.Row], campaign: sqlite3.Row, options: CampaignRunRequest) -> None:
    if not products:
        return
    retailer = products[0]["retailer"]
    started = time.perf_counter()
    proxy = proxy_for_retailer(retailer)
    logger.info(
        "event=retailer_batch_start campaign=%s retailer=%s products=%s method=%s screenshots=%s proxy_configured=%s",
        campaign["id"], retailer, len(products), options.method, options.screenshot, bool(proxy),
    )
    items: list[dict] = []
    product_by_id = {product["id"]: product for product in products}
    screenshot_by_id: dict[str, Path | None] = {}

    for product in products:
        screenshot_path = None
        if options.screenshot and options.method == "playwright":
            screenshot_path = SCREENSHOTS_DIR / (
                f"{slug(campaign['name'])}-{retailer}-{slug(product['sku'] or 'url')}-{uuid4().hex[:10]}.png"
            )
        try:
            validate_retail_url(retailer, product["url"] or None)
        except ValueError as exc:
            store_capture(product, campaign, options, exc, None)
            logger.warning(
                "event=url_rejected campaign=%s retailer=%s sku=%s url=%s reason=%s",
                campaign["id"], retailer, product["sku"], safe_url(product["url"]), str(exc)[:180],
            )
            continue
        items.append(
            {
                "product_id": product["id"],
                "sku": product["sku"] or None,
                "url": product["url"] or None,
                "screenshot_to": str(screenshot_path) if screenshot_path else None,
            }
        )
        screenshot_by_id[product["id"]] = screenshot_path

    if not items:
        return
    timestamp = now_iso()
    with db() as connection:
        connection.executemany(
            "UPDATE products SET status = 'running', error = NULL, updated_at = ? WHERE id = ?",
            [(timestamp, item["product_id"]) for item in items],
        )
    try:
        fetch_started = time.perf_counter()
        outcomes = fetch_prices(
            retailer,
            items,
            method=options.method,
            proxy=proxy,
            mode="fifo",
        )
        logger.info(
            "event=retailer_batch_fetch_complete campaign=%s retailer=%s products=%s duration_ms=%s",
            campaign["id"], retailer, len(items), round((time.perf_counter() - fetch_started) * 1000),
        )
    except Exception as exc:
        logger.exception("event=retailer_batch_exception campaign=%s retailer=%s error=%s", campaign["id"], retailer, str(exc)[:240])
        outcomes = [(item, exc) for item in items]
    for item, outcome in outcomes:
        product_id = item["product_id"]
        store_capture(product_by_id[product_id], campaign, options, outcome, screenshot_by_id[product_id])
    logger.info(
        "event=retailer_batch_end campaign=%s retailer=%s duration_ms=%s",
        campaign["id"], retailer, round((time.perf_counter() - started) * 1000),
    )


def run_campaign_job(campaign_id: str, options: CampaignRunRequest) -> None:
    job_started = time.perf_counter()
    logger.info("event=campaign_start campaign=%s method=%s screenshots=%s only_failed=%s", campaign_id, options.method, options.screenshot, options.only_failed)
    try:
        with db() as connection:
            campaign = connection.execute("SELECT * FROM campaigns WHERE id = ?", (campaign_id,)).fetchone()
            if campaign is None:
                return
            if options.only_failed:
                products = connection.execute(
                    "SELECT * FROM products WHERE campaign_id = ? AND status IN ('pending', 'error', 'no_price') ORDER BY created_at",
                    (campaign_id,),
                ).fetchall()
            else:
                products = connection.execute(
                    "SELECT * FROM products WHERE campaign_id = ? ORDER BY created_at", (campaign_id,)
                ).fetchall()
        groups: dict[str, list[sqlite3.Row]] = {}
        for product in products:
            groups.setdefault(product["retailer"], []).append(product)
        cancelled = False
        for retail_products in groups.values():
            if campaign_id in _CANCEL_REQUESTED:
                cancelled = True
                break
            chunk_size = 6 if options.method == "playwright" else 25
            for start in range(0, len(retail_products), chunk_size):
                if campaign_id in _CANCEL_REQUESTED:
                    cancelled = True
                    break
                capture_batch(retail_products[start : start + chunk_size], campaign, options)
            if cancelled:
                break
        with db() as connection:
            errors = connection.execute(
                "SELECT COUNT(*) FROM products WHERE campaign_id = ? AND status IN ('error', 'no_price', 'blocked', 'needs_review')",
                (campaign_id,),
            ).fetchone()[0]
            pending_left = connection.execute(
                "SELECT COUNT(*) FROM products WHERE campaign_id = ? AND status IN ('pending', 'running')",
                (campaign_id,),
            ).fetchone()[0]
            if cancelled:
                connection.execute(
                    "UPDATE products SET status = 'needs_review', error = COALESCE(error, '') || ' | Campaña cancelada', updated_at = ? WHERE campaign_id = ? AND status IN ('pending', 'running')",
                    (now_iso(), campaign_id),
                )
            finished = now_iso()
            final_status = (
                "completed_with_errors" if (errors or cancelled or pending_left) else "completed"
            )
            connection.execute(
                """
                UPDATE campaigns
                SET status = ?, updated_at = ?, last_run_at = ?, run_ended_at = ?,
                    last_error = ?
                WHERE id = ?
                """,
                (
                    final_status,
                    finished,
                    finished,
                    finished,
                    ("Cancelada por el usuario." if cancelled else None),
                    campaign_id,
                ),
            )
        _CANCEL_REQUESTED.discard(campaign_id)
        logger.info(
            "event=campaign_end campaign=%s status=%s errors=%s cancelled=%s duration_ms=%s",
            campaign_id,
            final_status,
            errors,
            cancelled,
            round((time.perf_counter() - job_started) * 1000),
        )
    except Exception as exc:
        logger.exception("event=campaign_exception campaign=%s error=%s", campaign_id, str(exc)[:300])
        _CANCEL_REQUESTED.discard(campaign_id)
        with db() as connection:
            connection.execute(
                "UPDATE campaigns SET status = 'ready', updated_at = ?, run_ended_at = ?, last_error = ? WHERE id = ?",
                (now_iso(), now_iso(), str(exc)[:700], campaign_id),
            )


def report_csv(campaign: dict) -> bytes:
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(
        [
            "Campaña", "Cliente", "Inicio", "Término", "SKU", "Descripción", "Retail", "URL", "PVP",
            "PVP Descuento", "Precio observado", "Diferencia", "Cumplimiento", "Fecha captura", "IP",
            "Evidencia oficial", "Evidencia Google", "Fuente evidencia", "Confianza", "Error", "Evidencia indirecta",
        ]
    )
    labels = {
        "pending": "Pendiente", "running": "Capturando", "compliant": "Cumple",
        "non_compliant": "No cumple", "captured_unverified": "Sin precio objetivo",
        "no_price": "Sin precio", "error": "Error",
        "blocked": "Bloqueado", "needs_review": "Requiere revisión",
    }
    for product in campaign["products"]:
        source = product.get("evidence_source") or "retailer"
        screenshot = product.get("screenshot_url") or ""
        is_demo = bool(campaign.get("is_demo")) or source == "demo"
        official = screenshot if source == "retailer" and not is_demo else ""
        google = "" if is_demo else ((product.get("fallback_screenshot_url") or screenshot) if source == "google_reference" else (product.get("fallback_screenshot_url") or ""))
        indirect = screenshot if source not in {"retailer", "google_reference", "demo"} and not is_demo else ""
        writer.writerow(
            [
                safe_csv(campaign["name"]), safe_csv(campaign["client"]), campaign["start_date"], campaign["end_date"],
                safe_csv(product["sku"]), safe_csv(product["name"]), product["retailer"], safe_csv(product["url"]),
                product["regular_price"], product["promo_price"],
                product["detected_price"] if product["detected_price"] is not None else "",
                product["difference"] if product["difference"] is not None else "",
                labels.get(product["status"], product["status"]), product["captured_at"] or "", product["ip_used"] or "",
                official, google,
                source, product.get("evidence_confidence") or "",
                safe_csv(product["error"] or ""),
                indirect,
            ]
        )
    return ("\ufeff" + output.getvalue()).encode("utf-8")


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "browser_available": importlib.util.find_spec("playwright") is not None,
    }


@app.get("/api/retailers")
def retailers() -> dict[str, list[str]]:
    return {"retailers": known_retailers()}


@app.get("/api/campaigns")
def list_campaigns() -> dict[str, list[dict]]:
    with db() as connection:
        rows = connection.execute("SELECT id FROM campaigns ORDER BY created_at DESC").fetchall()
    return {"campaigns": [campaign_payload(row["id"]) for row in rows]}


@app.post("/api/demo", status_code=201)
def create_demo() -> dict:
    return seed_demo_campaign()


@app.post("/api/campaigns", status_code=201)
def create_campaign(request: CampaignCreate) -> dict:
    if request.end_date < request.start_date:
        raise HTTPException(status_code=400, detail="La fecha de término no puede ser anterior al inicio.")
    campaign_id = uuid4().hex
    timestamp = now_iso()
    with db() as connection:
        connection.execute(
            """
            INSERT INTO campaigns (id, name, client, start_date, end_date, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'draft', ?, ?)
            """,
            (
                campaign_id, request.name.strip(), request.client.strip(), request.start_date.isoformat(),
                request.end_date.isoformat(), timestamp, timestamp,
            ),
        )
    logger.info("event=campaign_created campaign=%s name=%s client=%s start=%s end=%s", campaign_id, request.name.strip(), request.client.strip(), request.start_date, request.end_date)
    return campaign_payload(campaign_id)


@app.get("/api/campaigns/{campaign_id}")
def get_campaign(campaign_id: str) -> dict:
    return campaign_payload(campaign_id)


@app.get("/api/campaigns/{campaign_id}/intelligence")
def campaign_intelligence(campaign_id: str) -> dict:
    return intelligence_payload(campaign_id)


@app.get("/api/campaigns/{campaign_id}/comparables")
def get_comparables(campaign_id: str) -> dict:
    return comparable_payload(campaign_id)


@app.post("/api/campaigns/{campaign_id}/comparables/import")
async def import_comparables(
    campaign_id: str, file: UploadFile = File(...), replace: bool = Form(default=True),
) -> dict:
    campaign_payload(campaign_id)
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="El archivo supera el máximo de 12 MB.")
    try:
        rows = await run_in_threadpool(parse_tabular_file, file.filename or "comparables.csv", content)
    except (ValueError, UnicodeDecodeError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    parsed = []
    for row_number, row in enumerate(rows, start=2):
        group_id = pick(row, ["grupo_comparable", "group_id", "grupo", "comparable_id"])
        sku = pick(row, ["sku", "codigo", "id"])
        retailer_value = pick(row, ["retailer", "retail", "cadena", "tienda"])
        retailer = normalize_retailer(retailer_value) if retailer_value else ""
        price_value = pick(row, ["precio", "price", "precio_observado", "observed_price"])
        numeric_price = price_value.replace("$", "").replace(" ", "")
        if not re.fullmatch(r"\d+(?:[.,]\d+)*", numeric_price):
            continue
        price = parse_number(price_value)
        if not group_id or not sku or not retailer or not math.isfinite(price) or price <= 0:
            continue
        observed_value = pick(row, ["fecha", "observed_at", "fecha_observacion"])
        try:
            observed_at = datetime.fromisoformat(observed_value.replace("Z", "+00:00")) if observed_value else datetime.now().astimezone()
            if observed_at.tzinfo is None:
                observed_at = observed_at.astimezone()
            observed_at = observed_at.astimezone().isoformat(timespec="seconds")
        except ValueError:
            continue
        parsed.append({
            "group_id": group_id,
            "sku": sku,
            "name": pick(row, ["nombre", "name", "producto", "descripcion"]) or group_id,
            "retailer": retailer,
            "price": price,
            "observed_at": observed_at,
            "row": row_number,
        })
    if not parsed:
        raise HTTPException(
            status_code=400,
            detail="No encontramos comparables válidos. Usa grupo_comparable, SKU, retailer y precio.",
        )
    timestamp = now_iso()
    with db() as connection:
        if replace:
            connection.execute("DELETE FROM comparable_prices WHERE campaign_id = ?", (campaign_id,))
        for item in parsed:
            connection.execute(
                """
                INSERT INTO comparable_prices
                    (id, campaign_id, group_id, sku, name, retailer, price, observed_at, source, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'import', ?)
                """,
                (
                    uuid4().hex, campaign_id, item["group_id"], item["sku"], item["name"],
                    item["retailer"], item["price"], item["observed_at"], timestamp,
                ),
            )
    result = comparable_payload(campaign_id)
    result["imported"] = len(parsed)
    result["skipped"] = len(rows) - len(parsed)
    result["filename"] = file.filename or "comparables.csv"
    return result


@app.get("/api/campaigns/{campaign_id}/inventory")
def get_inventory(campaign_id: str) -> dict:
    return inventory_payload(campaign_id)


@app.post("/api/campaigns/{campaign_id}/inventory/import")
async def import_inventory(
    campaign_id: str, file: UploadFile = File(...), replace: bool = Form(default=True),
) -> dict:
    campaign_payload(campaign_id)
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="El archivo supera el máximo de 12 MB.")
    try:
        rows = await run_in_threadpool(parse_tabular_file, file.filename or "inventario.csv", content)
    except (ValueError, UnicodeDecodeError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    parsed = [inventory_row(row) for row in rows]
    parsed = [item for item in parsed if item["sku"]]
    if not parsed:
        raise HTTPException(status_code=400, detail="No encontramos filas con SKU. Usa SKU, stock, ventas_30d y lead_time.")
    timestamp = now_iso()
    with db() as connection:
        if replace:
            connection.execute("DELETE FROM inventory_metrics WHERE campaign_id = ?", (campaign_id,))
        for item in parsed:
            connection.execute(
                """
                INSERT INTO inventory_metrics
                    (id, campaign_id, sku, name, retailer, stock, sales_30d, daily_sales,
                     lead_time_days, safety_stock, coverage_days, risk, stockout_date,
                     action, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(campaign_id, sku, retailer) DO UPDATE SET
                    name = excluded.name, stock = excluded.stock, sales_30d = excluded.sales_30d,
                    daily_sales = excluded.daily_sales, lead_time_days = excluded.lead_time_days,
                    safety_stock = excluded.safety_stock, coverage_days = excluded.coverage_days,
                    risk = excluded.risk, stockout_date = excluded.stockout_date,
                    action = excluded.action, updated_at = excluded.updated_at
                """,
                (
                    uuid4().hex, campaign_id, item["sku"], item["name"], item["retailer"],
                    item["stock"], item["sales_30d"], item["daily_sales"], item["lead_time_days"],
                    item["safety_stock"], item["coverage_days"], item["risk"], item["stockout_date"],
                    item["action"], timestamp, timestamp,
                ),
            )
    result = inventory_payload(campaign_id)
    result["imported"] = len(parsed)
    result["filename"] = file.filename or "inventario.csv"
    return result


@app.get("/api/campaigns/{campaign_id}/brief")
def campaign_brief(campaign_id: str) -> dict:
    campaign = campaign_payload(campaign_id)
    intelligence = intelligence_payload(campaign_id)
    inventory = inventory_payload(campaign_id)
    comparables = comparable_payload(campaign_id)
    findings = []
    for action in intelligence["actions"]:
        findings.append({
            "severity": action["priority"],
            "title": action["title"],
            "detail": action["detail"],
            "recommendation": (
                "Asignar responsable y resolver dentro de 24 horas."
                if action["priority"] in {"critical", "high"}
                else "Incluir en la próxima revisión comercial."
            ),
        })
    return {
        "title": f"Radar Brief · {campaign['name']}",
        "generated_at": now_iso(),
        "is_demo": bool(campaign.get("is_demo")),
        "period": {"start": campaign["start_date"], "end": campaign["end_date"]},
        "executive_summary": (
            f"Se monitorearon {campaign['summary']['total']} SKU. "
            + (f"El cumplimiento promocional es {intelligence['compliance_percent']}%. " if intelligence['compliance_percent'] is not None else "El cumplimiento promocional está sin datos evaluables. ")
            + f"Hay {inventory['summary'].get('critical', 0)} riesgos críticos de quiebre y "
            f"{comparables['group_count']} grupos comparables explícitos."
        ),
        "metrics": {
            "sku": campaign["summary"]["total"],
            "compliance_percent": intelligence["compliance_percent"],
            "non_compliant": campaign["summary"]["non_compliant"],
            "critical_stock": inventory["summary"].get("critical", 0),
            "comparable_groups": comparables["group_count"],
        },
        "findings": findings,
        "methodology": "Reglas determinísticas sobre precios, grupos comparables explícitos e inventario importado. No se inventan datos faltantes.",
    }


@app.get("/api/campaigns/{campaign_id}/price-history")
def price_history(
    campaign_id: str,
    sku: str | None = Query(default=None),
    retailer: str | None = Query(default=None),
) -> dict:
    campaign_payload(campaign_id)
    clauses = ["campaign_id = ?"]
    values: list[str] = [campaign_id]
    if sku:
        clauses.append("sku = ?")
        values.append(sku.strip())
    if retailer:
        clauses.append("retailer = ?")
        values.append(retailer.strip())
    with db() as connection:
        rows = connection.execute(
            "SELECT id, product_id, sku, retailer, observed_at, price, status, evidence_source, screenshot_url "
            f"FROM price_observations WHERE {' AND '.join(clauses)} ORDER BY observed_at DESC",
            values,
        ).fetchall()
    observations = [dict(row) for row in rows]
    priced = [row["price"] for row in observations if row["price"] is not None]
    return {
        "observations": observations,
        "count": len(observations),
        "min_price": min(priced) if priced else None,
        "max_price": max(priced) if priced else None,
        "latest_price": priced[0] if priced else None,
    }


@app.post("/api/campaigns/{campaign_id}/import")
async def import_products(
    campaign_id: str, file: UploadFile = File(...), replace: bool = Form(default=True),
) -> dict:
    campaign_payload(campaign_id)
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="El archivo supera el máximo de 12 MB.")
    try:
        products = await run_in_threadpool(parse_campaign_file, file.filename or "campana.csv", content)
    except (ValueError, UnicodeDecodeError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not products:
        raise HTTPException(status_code=400, detail="El archivo no contiene productos. Usa SKU, Link, PVP y PVP Descuento.")

    logger.info("event=products_imported campaign=%s filename=%s bytes=%s products=%s replace=%s retailers=%s", campaign_id, file.filename or "campana", len(content), len(products), replace, sorted({str(product['retailer']) for product in products}))

    supported = set(known_retailers())
    unsupported = sorted({str(product["retailer"]) for product in products if product["retailer"] not in supported})
    timestamp = now_iso()
    with db() as connection:
        if replace:
            connection.execute("DELETE FROM products WHERE campaign_id = ?", (campaign_id,))
        for product in products:
            connection.execute(
                """
                INSERT INTO products (
                    id, campaign_id, sku, name, category, retailer, url, regular_price, promo_price,
                    status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                """,
                (
                    uuid4().hex, campaign_id, product["sku"], product["name"], product["category"],
                    product["retailer"], product["url"], product["regular_price"], product["promo_price"],
                    timestamp, timestamp,
                ),
            )
        connection.execute(
            "UPDATE campaigns SET status = 'ready', source_filename = ?, updated_at = ?, last_error = NULL WHERE id = ?",
            (file.filename or "campana", timestamp, campaign_id),
        )
    payload = campaign_payload(campaign_id)
    retailers_found = sorted({str(product["retailer"]) for product in products})
    empty_sku = sum(1 for product in products if not str(product.get("sku") or "").strip())
    empty_url = sum(1 for product in products if not str(product.get("url") or "").strip())
    invalid_links = []
    for product in products:
        url = str(product.get("url") or "").strip()
        if not url:
            continue
        try:
            validate_retail_url(str(product["retailer"]), url)
        except ValueError as exc:
            invalid_links.append({
                "sku": product.get("sku"),
                "retailer": product.get("retailer"),
                "url": url,
                "reason": str(exc),
            })
    filename = file.filename or "campana"
    # Detect marketing names like "8-retails" that do not match the actual file content.
    digits = re.findall(r"(\d+)\s*[-_]?\s*retail", filename.lower())
    claimed_retails = int(digits[0]) if digits else None
    filename_mismatch = (
        claimed_retails is not None and claimed_retails != len(retailers_found)
    )
    payload["import"] = {
        "filename": filename,
        "count": len(products),
        "unsupported_retailers": unsupported,
        "retailers_found": retailers_found,
        "retailers_count": len(retailers_found),
        "by_retailer": payload["summary"].get("by_retailer", {}),
        "empty_sku": empty_sku,
        "empty_url": empty_url,
        "invalid_links": invalid_links[:50],
        "invalid_links_count": len(invalid_links),
        "claimed_retails_in_filename": claimed_retails,
        "filename_retail_mismatch": filename_mismatch,
        "summary_message": (
            f"{len(products)} productos · {len(retailers_found)} retails detectados"
            + (
                f" (el nombre del archivo sugiere {claimed_retails})"
                if filename_mismatch else ""
            )
        ),
    }
    return payload


@app.post("/api/campaigns/{campaign_id}/run", status_code=202)
def run_campaign(campaign_id: str, request: CampaignRunRequest, background_tasks: BackgroundTasks) -> dict:
    campaign = campaign_payload(campaign_id)
    if campaign.get("is_demo"):
        return campaign
    if campaign["status"] == "running":
        raise HTTPException(status_code=409, detail="La campaña ya se está ejecutando.")
    if not campaign["products"]:
        raise HTTPException(status_code=400, detail="Carga productos antes de ejecutar la campaña.")
    if request.capture_mode == "cloud":
        try:
            sitemap_id = assert_retail_cloud_allowed()
        except CloudConfigError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        raise HTTPException(
            status_code=400,
            detail=(
                f"Modo Cloud preparado para sitemap {sitemap_id}, pero la importación robusta "
                f"de resultados aún es experimental. {webhook_requirement_note()} "
                "Usa capture_mode=local para evidencias auditables PNG."
            ),
        )
    if request.method == "playwright" and importlib.util.find_spec("playwright") is None:
        raise HTTPException(status_code=400, detail="El navegador de captura no está instalado.")
    failed_like = (
        campaign["summary"]["error"]
        + campaign["summary"]["no_price"]
        + campaign["summary"].get("blocked", 0)
        + campaign["summary"].get("needs_review", 0)
    )
    if request.only_failed and not failed_like:
        raise HTTPException(status_code=400, detail="No hay productos fallidos para reintentar.")

    timestamp = now_iso()
    _CANCEL_REQUESTED.discard(campaign_id)
    with db() as connection:
        if request.only_failed:
            connection.execute(
                "UPDATE products SET status = 'pending', error = NULL, updated_at = ? WHERE campaign_id = ? AND status IN ('error', 'no_price', 'blocked', 'needs_review')",
                (timestamp, campaign_id),
            )
        else:
            connection.execute(
                """
                UPDATE products SET status = 'pending', detected_price = NULL, original_price = NULL,
                    captured_at = NULL, screenshot_url = NULL, fallback_screenshot_url = NULL,
                    evidence_source = 'retailer', evidence_confidence = 'official',
                    ip_used = NULL, error = NULL, updated_at = ?
                WHERE campaign_id = ?
                """,
                (timestamp, campaign_id),
            )
        connection.execute(
            """
            UPDATE campaigns
            SET status = 'running', updated_at = ?, last_error = NULL,
                run_started_at = ?, run_ended_at = NULL, capture_mode = ?,
                cloud_job_id = NULL, cloud_status = NULL
            WHERE id = ?
            """,
            (timestamp, timestamp, request.capture_mode, campaign_id),
        )
    background_tasks.add_task(run_campaign_job, campaign_id, request)
    return campaign_payload(campaign_id)


@app.post("/api/campaigns/{campaign_id}/cancel", status_code=202)
def cancel_campaign(campaign_id: str) -> dict:
    campaign = campaign_payload(campaign_id)
    if campaign["status"] != "running":
        raise HTTPException(status_code=400, detail="La campaña no está en ejecución.")
    _CANCEL_REQUESTED.add(campaign_id)
    logger.info("event=campaign_cancel_requested campaign=%s", campaign_id)
    with db() as connection:
        connection.execute(
            "UPDATE campaigns SET last_error = ?, updated_at = ? WHERE id = ?",
            ("Cancelación solicitada. La campaña se detendrá al terminar el lote actual.", now_iso(), campaign_id),
        )
    return campaign_payload(campaign_id)


@app.get("/api/campaigns/{campaign_id}/report.csv")
def download_report(campaign_id: str) -> Response:
    campaign = campaign_payload(campaign_id)
    filename = f"reporte-{slug(campaign['name'])}.csv"
    return Response(
        report_csv(campaign), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/campaigns/{campaign_id}/evidence.zip")
def download_evidence(campaign_id: str) -> StreamingResponse:
    campaign = campaign_payload(campaign_id)
    archive = io.BytesIO()
    with ZipFile(archive, "w", ZIP_DEFLATED) as bundle:
        bundle.writestr(f"reporte-{slug(campaign['name'])}.csv", report_csv(campaign))
        for index, product in enumerate(campaign["products"], start=1):
            source = product.get("evidence_source") or "retailer"
            if campaign.get("is_demo") or source == "demo":
                continue
            official = product.get("screenshot_url")
            if official and source == "retailer":
                path = SCREENSHOTS_DIR / Path(official).name
                if path.exists() and path.is_file():
                    name = f"{index:04d}-{slug(product['retailer'])}-{slug(product['sku'] or 'sin-sku')}-oficial.png"
                    bundle.write(path, f"evidencias/{name}")
            elif official:
                path = SCREENSHOTS_DIR / Path(official).name
                if path.exists() and path.is_file():
                    kind = "datos-estructurados" if source == "retailer_structured" else "referencia-google" if source == "google_reference" else "referencia-indirecta"
                    name = f"{index:04d}-{slug(product['retailer'])}-{slug(product['sku'] or 'sin-sku')}-{kind}.png"
                    bundle.write(path, f"evidencias-indirectas/{name}")
            fallback = product.get("fallback_screenshot_url")
            if fallback and fallback != official:
                path = SCREENSHOTS_DIR / Path(fallback).name
                if path.exists() and path.is_file():
                    name = f"{index:04d}-{slug(product['retailer'])}-{slug(product['sku'] or 'sin-sku')}-referencia-google.png"
                    bundle.write(path, f"evidencias-indirectas/{name}")
    archive.seek(0)
    filename = f"evidencias-{slug(campaign['name'])}.zip"
    return StreamingResponse(
        archive, media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/import-campaign")
async def import_campaign(file: UploadFile = File(...)) -> dict:
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="El archivo supera el máximo de 12 MB.")
    try:
        products = await run_in_threadpool(parse_campaign_file, file.filename or "campaign.csv", content)
    except (ValueError, UnicodeDecodeError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not products:
        raise HTTPException(status_code=400, detail="El archivo no contiene productos.")
    legacy_products = [
        {
            "id": uuid4().hex, "sku": product["sku"], "name": product["name"], "category": product["category"],
            "retailer": product["retailer"], "url": product["url"], "ownPrice": product["regular_price"],
            "targetPrice": product["promo_price"], "marketLow": product["promo_price"], "leader": "Pendiente",
            "gap": 0, "stock": "OK", "marginRisk": "Medio", "evidence": "Pendiente",
        }
        for product in products
    ]
    return {"filename": file.filename or "campana", "count": len(products), "products": legacy_products}


@app.post("/api/fetch-price")
async def fetch_price_for_product(request: PriceRequest) -> dict:
    sku_value = request.sku.strip() if request.sku else None
    url_value = request.url.strip() if request.url else None
    if request.retail not in set(known_retailers()):
        raise HTTPException(status_code=400, detail=f"Retailer no soportado: {request.retail}")
    if not sku_value and not url_value:
        raise HTTPException(status_code=400, detail="Debes ingresar SKU o URL.")
    try:
        validate_retail_url(request.retail, url_value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    screenshot_path = None
    if request.screenshot and request.method == "playwright":
        screenshot_path = SCREENSHOTS_DIR / f"{request.retail}-{slug(sku_value or 'url')}-{uuid4().hex[:10]}.png"
    captured_at = datetime.now().astimezone()
    try:
        result = await run_in_threadpool(
            fetch_price, request.retail, sku=sku_value, url=url_value, method=request.method,
            proxy=proxy_for_retailer(request.retail),
            screenshot_to=str(screenshot_path) if screenshot_path else None,
        )
    except ModuleNotFoundError as exc:
        raise HTTPException(status_code=400, detail="Falta instalar el navegador de captura.") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="El retail no respondió correctamente. Intenta nuevamente.") from exc
    captured_at = datetime.now().astimezone()
    if screenshot_path:
        if (
            request.retail == "ripley_cl"
            and result.get("new_price") is not None
            and result.get("screenshot_focus") == "unavailable"
        ):
            await run_in_threadpool(
                render_indirect_evidence_card,
                screenshot_path,
                retailer="ripley_cl",
                sku=sku_value or "",
                product_url=url_value,
                google_price=result.get("new_price"),
                search_url=url_value or "",
                captured_at=captured_at,
                note="La versión móvil entregó reseñas; el precio proviene del JSON-LD público de la ficha.",
                source_label="datos estructurados públicos de Ripley",
                confidence="medium",
            )
            result["evidence_source"] = "retailer_structured"
            result["evidence_confidence"] = "medium"
        else:
            await run_in_threadpool(annotate_screenshot, screenshot_path, request, result, captured_at)
    fallback_url = None
    if request.google_fallback and result.get("new_price") is None:
        fallback_path = SCREENSHOTS_DIR / f"google-{request.retail}-{slug(sku_value or 'url')}-{uuid4().hex[:10]}.png"
        fallback = await run_in_threadpool(google_reference_fallback, request.retail, sku_value or "", url_value, fallback_path)
        if fallback.get("screenshot_path"):
            await run_in_threadpool(annotate_screenshot, fallback_path, request, fallback, captured_at)
            fallback_url = f"/screenshots/{fallback_path.name}"
            result = {**result, "google_reference": fallback, "evidence_source": "google_reference", "evidence_confidence": "low"}
    return {
        "retail": request.retail, "sku": sku_value, "url": url_value, "method": request.method,
        "captured_at": captured_at.isoformat(timespec="seconds"), "result": result,
        "screenshot_url": f"/screenshots/{screenshot_path.name}" if screenshot_path and screenshot_path.exists() else None,
        "fallback_screenshot_url": fallback_url,
    }


if DIST_DIR.exists():
    app.mount("/", StaticFiles(directory=DIST_DIR, html=True), name="frontend")
