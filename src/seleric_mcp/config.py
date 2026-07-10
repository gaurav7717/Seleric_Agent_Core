"""Environment configuration. Loads .env then .env.local (overrides), same
convention as seleric_systems. All secrets stay server-side; nothing here is
ever placed in a tool response.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_env() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    load_dotenv(PROJECT_ROOT / ".env.local", override=True)


@dataclass(frozen=True)
class Settings:
    cube_api_url: str
    seleric_api_key: str
    cubejs_api_secret: str
    pipeboard_mcp_url: str
    pipeboard_token: str
    write_enabled: bool
    mcp_service_token: str
    approval_secret: str
    caller_scopes: frozenset[str]
    db_path: Path
    catalogue_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "catalogue")

    # --- behavior tunables (all overridable via env; defaults live only here) ---
    # term resolution bands (see catalogue_service.service)
    resolve_auto_threshold: float = 0.85
    resolve_ambiguous_threshold: float = 0.60
    resolve_runner_up_margin: float = 0.05
    # query limits / timeouts
    default_row_limit: int = 500
    max_row_limit: int = 5000
    cube_timeout_seconds: float = 30.0
    # stored-result and idempotency windows
    result_ttl_minutes: int = 60
    idempotency_window_hours: int = 24
    # insight engine
    top_movers_limit: int = 10
    anomaly_sigma: float = 3.0
    anomaly_min_points: int = 14
    # freshness resource cache
    freshness_cache_ttl_seconds: int = 600


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    return float(raw) if raw else default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    return int(raw) if raw else default


def load_settings() -> Settings:
    _load_env()
    db_raw = os.getenv("SELERIC_MCP_DB", "var/seleric_mcp.db")
    db_path = Path(db_raw)
    if not db_path.is_absolute():
        db_path = PROJECT_ROOT / db_path
    scopes = frozenset(
        s.strip()
        for s in os.getenv("SELERIC_MCP_SCOPES", "metrics:read").split(",")
        if s.strip()
    )
    defaults = Settings.__dataclass_fields__
    return Settings(
        cube_api_url=os.getenv("CUBE_API_URL", "http://127.0.0.1:4001").rstrip("/"),
        seleric_api_key=os.getenv("SELERIC_API_KEY", ""),
        cubejs_api_secret=os.getenv("CUBEJS_API_SECRET", ""),
        pipeboard_mcp_url=os.getenv("PIPEBOARD_MCP_URL", "https://meta-ads.mcp.pipeboard.co").rstrip("/"),
        pipeboard_token=os.getenv("PIPEBOARD_TOKEN", ""),
        write_enabled=os.getenv("WRITE_ENABLED", "false") == "true",
        mcp_service_token=os.getenv("MCP_SERVICE_TOKEN", ""),
        approval_secret=os.getenv("APPROVAL_SECRET", ""),
        caller_scopes=scopes,
        db_path=db_path,
        resolve_auto_threshold=_env_float(
            "SELERIC_RESOLVE_AUTO_THRESHOLD", defaults["resolve_auto_threshold"].default
        ),
        resolve_ambiguous_threshold=_env_float(
            "SELERIC_RESOLVE_AMBIGUOUS_THRESHOLD",
            defaults["resolve_ambiguous_threshold"].default,
        ),
        resolve_runner_up_margin=_env_float(
            "SELERIC_RESOLVE_RUNNER_UP_MARGIN", defaults["resolve_runner_up_margin"].default
        ),
        default_row_limit=_env_int("SELERIC_DEFAULT_ROW_LIMIT", defaults["default_row_limit"].default),
        max_row_limit=_env_int("SELERIC_MAX_ROW_LIMIT", defaults["max_row_limit"].default),
        cube_timeout_seconds=_env_float("SELERIC_CUBE_TIMEOUT_S", defaults["cube_timeout_seconds"].default),
        result_ttl_minutes=_env_int("SELERIC_RESULT_TTL_MINUTES", defaults["result_ttl_minutes"].default),
        idempotency_window_hours=_env_int(
            "SELERIC_IDEMPOTENCY_WINDOW_HOURS", defaults["idempotency_window_hours"].default
        ),
        top_movers_limit=_env_int("SELERIC_TOP_MOVERS_LIMIT", defaults["top_movers_limit"].default),
        anomaly_sigma=_env_float("SELERIC_ANOMALY_SIGMA", defaults["anomaly_sigma"].default),
        anomaly_min_points=_env_int("SELERIC_ANOMALY_MIN_POINTS", defaults["anomaly_min_points"].default),
        freshness_cache_ttl_seconds=_env_int(
            "SELERIC_FRESHNESS_CACHE_TTL_S", defaults["freshness_cache_ttl_seconds"].default
        ),
    )
