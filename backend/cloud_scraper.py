"""Optional Web Scraper Cloud integration for Radar Retail.

Cloud is secondary. Local Playwright captures remain the auditable source of truth.
Never treat Google results or Cloud JSON without screenshots as official retailer evidence.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger("radar-retail")

DEMO_SITEMAP_ID = "1528123"
DEMO_SITEMAP_NAME = "webscraper-io-test-site"


class CloudConfigError(ValueError):
    """Raised when Cloud is misconfigured for retail campaigns."""


def cloud_token() -> str | None:
    value = os.getenv("WEBSCRAPER_TOKEN") or os.getenv("WEB_SCRAPER_TOKEN")
    return value.strip() if value else None


def configured_sitemap_id() -> str | None:
    value = os.getenv("WEBSCRAPER_SITEMAP_ID") or os.getenv("WEB_SCRAPER_SITEMAP_ID")
    return value.strip() if value else None


def assert_retail_cloud_allowed(sitemap_id: str | None = None) -> str:
    """Block the demo sitemap and require an explicit retail sitemap id."""
    sitemap = (sitemap_id or configured_sitemap_id() or "").strip()
    if not sitemap:
        raise CloudConfigError(
            "Falta WEBSCRAPER_SITEMAP_ID. Configura un sitemap real de retailers chilenos."
        )
    if sitemap == DEMO_SITEMAP_ID:
        raise CloudConfigError(
            f"El sitemap {DEMO_SITEMAP_ID} ({DEMO_SITEMAP_NAME}) es solo de demostración "
            "de webscraper.io y no sirve para campañas retail. Configura un sitemap real "
            "antes de usar modo Cloud."
        )
    if not cloud_token():
        raise CloudConfigError(
            "Falta WEBSCRAPER_TOKEN en variables de entorno. No se exponen tokens en logs."
        )
    return sitemap


def cloud_status_label(status: str | None) -> str:
    mapping = {
        "waiting-to-be-scheduled": "en cola",
        "running": "corriendo",
        "finished": "terminado",
        "failed": "fallido",
        "stopped": "detenido",
    }
    key = (status or "").strip().lower()
    return mapping.get(key, status or "desconocido")


def summarize_cloud_job(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize Cloud job metadata without secrets."""
    return {
        "cloud_job_id": payload.get("id") or payload.get("job_id"),
        "cloud_status": payload.get("status"),
        "cloud_status_label": cloud_status_label(payload.get("status")),
        "sitemap_id": payload.get("sitemap_id"),
        "pages": payload.get("pages") or payload.get("page_count"),
        "failed_pages": payload.get("failed") or payload.get("failed_pages"),
        "records": payload.get("records") or payload.get("record_count") or 0,
        "note": (
            "Cloud no garantiza un PNG auditable por SKU. "
            "Si no hay screenshot, márcalo explícitamente."
        ),
    }


def webhook_requirement_note() -> str:
    return (
        "El webhook de Cloud requiere una URL pública HTTPS. "
        "localhost no es alcanzable desde Internet; usa polling seguro como respaldo."
    )
