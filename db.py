import os
import time
from typing import Optional

import psycopg2
from psycopg2 import OperationalError

from receiver.config import get_config, log_event


DEFAULTS = {
    "host": "postgres",
    "port": "5432",
    "dbname": "mini_pacs",
    "user": "mini_pacs",
    "password": "mini_pacs",
}

_CONN: Optional[psycopg2.extensions.connection] = None


def _db_params() -> dict:
    return {
        "host": os.getenv("POSTGRES_HOST", DEFAULTS["host"]),
        "port": int(os.getenv("POSTGRES_PORT", DEFAULTS["port"])),
        "dbname": os.getenv("POSTGRES_DB", DEFAULTS["dbname"]),
        "user": os.getenv("POSTGRES_USER", DEFAULTS["user"]),
        "password": os.getenv("POSTGRES_PASSWORD", DEFAULTS["password"]),
    }


def _connect_with_retry(max_attempts: int = 10, delay_seconds: int = 2) -> psycopg2.extensions.connection:
    params = _db_params()
    ae_title = get_config()["edge"]["ae_title"]
    last_error: Optional[str] = None

    for attempt in range(1, max_attempts + 1):
        try:
            conn = psycopg2.connect(**params)
            conn.autocommit = True
            log_event(
                "info",
                "db",
                study_uid=None,
                sop_uid=None,
                ae_title=ae_title,
                remote_ip=None,
                outcome="connected",
                error=None,
            )
            return conn
        except OperationalError as exc:
            last_error = str(exc)
            time.sleep(delay_seconds)

    log_event(
        "error",
        "db",
        study_uid=None,
        sop_uid=None,
        ae_title=ae_title,
        remote_ip=None,
        outcome="connection_failed",
        error=last_error,
    )
    raise SystemExit("PostgreSQL not ready")


def get_connection() -> psycopg2.extensions.connection:
    global _CONN
    if _CONN is not None and _CONN.closed == 0:
        return _CONN
    _CONN = _connect_with_retry()
    return _CONN
