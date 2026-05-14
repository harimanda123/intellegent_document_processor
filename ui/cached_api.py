"""
Cached wrappers for read-only API calls.

Uses @st.cache_data so identical calls within the TTL window
return the cached result instantly without hitting the backend.

Mutation functions (create, update, delete) live in api_client directly
and must call the relevant .clear() method after writes.
"""
import streamlit as st
import api_client as api


@st.cache_data(ttl=60, show_spinner=False)
def list_schemas(status: str | None = None) -> list:
    """Cached schema list — refreshes every 60 s or when explicitly cleared."""
    return api.list_schemas(status=status)


@st.cache_data(ttl=30, show_spinner=False)
def get_dashboard_stats() -> dict:
    return api.get_dashboard_stats()


@st.cache_data(ttl=15, show_spinner=False)
def get_dashboard_queue() -> dict:
    return api.get_dashboard_queue()


@st.cache_data(ttl=20, show_spinner=False)
def get_dashboard_history(
    state: str | None = None,
    schema_id: str | None = None,
    source: str | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    return api.get_dashboard_history(
        state=state,
        schema_id=schema_id,
        source=source,
        search=search,
        limit=limit,
        offset=offset,
    )


@st.cache_data(ttl=120, show_spinner=False)
def get_dashboard_analytics(days: int = 30) -> dict:
    return api.get_dashboard_analytics(days=days)


@st.cache_data(ttl=10, show_spinner=False)
def list_documents(
    state: str | None = None,
    schema_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list:
    return api.list_documents(state=state, schema_id=schema_id, limit=limit)


def invalidate_schemas() -> None:
    """Call after any schema mutation (create / update / activate / archive)."""
    list_schemas.clear()


def invalidate_documents() -> None:
    """Call after uploading or retrying a document."""
    list_documents.clear()


def invalidate_live() -> None:
    """Call when the user manually refreshes the dashboard."""
    get_dashboard_stats.clear()
    get_dashboard_queue.clear()
    get_dashboard_history.clear()
