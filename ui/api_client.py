"""
IDP — Intelligent Document Gateway
API client for the Streamlit UI.

All HTTP calls to the backend go through this module.
Set IDP_API_URL env var to override the default backend address.
"""
import os
from typing import Any

import requests

BASE_URL = os.getenv("IDP_API_URL", "http://localhost:8000")


def _url(path: str) -> str:
    return f"{BASE_URL}/api{path}"


def _get(path: str, params: dict | None = None) -> Any:
    clean = {k: v for k, v in (params or {}).items() if v is not None}
    r = requests.get(_url(path), params=clean, timeout=30)
    _raise_for_status(r)
    return r.json()


def _post_json(path: str, payload: dict | None = None) -> Any:
    r = requests.post(_url(path), json=payload or {}, timeout=30)
    _raise_for_status(r)
    return r.json()


class APIError(Exception):
    """Raised when the backend returns a non-2xx response."""
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"HTTP {status_code}: {detail}")


def _raise_for_status(r: requests.Response) -> None:
    """Raise APIError with the backend's detail message."""
    if not r.ok:
        try:
            detail = r.json().get("detail", r.text)
        except Exception:
            detail = r.text
        raise APIError(r.status_code, detail)


def _post_form(path: str, files=None, data: dict | None = None) -> Any:
    r = requests.post(_url(path), files=files, data=data, timeout=120)
    _raise_for_status(r)
    return r.json()


def _put(path: str, payload: dict | None = None) -> Any:
    r = requests.put(_url(path), json=payload or {}, timeout=30)
    _raise_for_status(r)
    return r.json()


def _delete(path: str) -> None:
    r = requests.delete(_url(path), timeout=30)
    _raise_for_status(r)


# ── Schemas ────────────────────────────────────────────────────────────────

def list_schemas(status: str | None = None) -> list:
    return _get("/schemas/", {"status": status})


def get_schema(schema_id: str) -> dict:
    return _get(f"/schemas/{schema_id}")


def create_schema(payload: dict) -> dict:
    return _post_json("/schemas/", payload)


def update_schema(schema_id: str, payload: dict) -> dict:
    return _put(f"/schemas/{schema_id}", payload)


def activate_schema(schema_id: str) -> dict:
    return _post_json(f"/schemas/{schema_id}/activate")


def archive_schema(schema_id: str) -> None:
    _delete(f"/schemas/{schema_id}")


def duplicate_schema(schema_id: str) -> dict:
    return _post_json(f"/schemas/{schema_id}/duplicate")


def propose_schema(file_bytes: bytes, filename: str, document_type: str = "") -> dict:
    return _post_form(
        "/schemas/propose",
        files={"file": (filename, file_bytes)},
        data={"document_type": document_type},
    )


def test_schema(schema_id: str, file_bytes: bytes, filename: str) -> dict:
    return _post_form(
        f"/schemas/{schema_id}/test",
        files={"file": (filename, file_bytes)},
    )


def list_schema_versions(schema_id: str) -> dict:
    return _get(f"/schemas/{schema_id}/versions")


def restore_schema_version(schema_id: str, version: int) -> dict:
    return _post_json(f"/schemas/{schema_id}/versions/{version}/restore")


def list_schema_feedback(schema_id: str, applied: bool | None = None) -> dict:
    params: dict = {}
    if applied is not None:
        params["applied"] = applied
    return _get(f"/schemas/{schema_id}/feedback", params)


def apply_schema_feedback(schema_id: str) -> dict:
    return _post_json(f"/schemas/{schema_id}/apply-feedback")


# ── Documents ──────────────────────────────────────────────────────────────

def list_documents(
    state: str | None = None,
    schema_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list:
    return _get("/documents/", {
        "state": state,
        "schema_id": schema_id,
        "limit": limit,
        "offset": offset,
    })


def upload_document(
    file_bytes: bytes,
    filename: str,
    schema_id: str,
    label: str = "",
    require_review: bool = False,
) -> dict:
    return _post_form(
        "/documents/upload",
        files={"file": (filename, file_bytes)},
        data={
            "schema_id": schema_id,
            "label": label,
            "require_review": str(require_review).lower(),
        },
    )


def get_document_status(doc_id: str) -> dict:
    return _get(f"/documents/{doc_id}/status")


def get_document_result(doc_id: str) -> dict:
    return _get(f"/documents/{doc_id}/result")


def approve_document(doc_id: str) -> dict:
    return _put(f"/documents/{doc_id}/approve")


def reject_document(doc_id: str, reason: str = "") -> dict:
    return _put(f"/documents/{doc_id}/reject", {"reason": reason})


def edit_field(doc_id: str, field_key: str, value: Any) -> dict:
    return _put(f"/documents/{doc_id}/fields/{field_key}", {"value": value})


def retry_document(doc_id: str) -> dict:
    return _post_json(f"/documents/{doc_id}/retry")


def get_audit(doc_id: str) -> list:
    return _get(f"/documents/{doc_id}/audit")


def download_json(doc_id: str) -> bytes:
    r = requests.get(f"{BASE_URL}/api/documents/{doc_id}/download", timeout=30)
    r.raise_for_status()
    return r.content


# ── Dashboard ──────────────────────────────────────────────────────────────

def get_dashboard_stats() -> dict:
    return _get("/dashboard/stats")


def get_dashboard_queue() -> dict:
    return _get("/dashboard/queue")


def get_dashboard_history(**kwargs) -> dict:
    return _get("/dashboard/history", {k: v for k, v in kwargs.items() if v is not None})


def get_dashboard_analytics(days: int = 30) -> dict:
    return _get("/dashboard/analytics", {"days": days})
