from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any
from urllib.parse import ParseResult, unquote, urlparse, urlunparse

import psycopg
from psycopg import Connection, sql

from migration_toolkit.audit import target_url_from_env


class DisposableTargetError(RuntimeError):
    pass


DATABASE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")

DEFAULT_ALLOWED_PREFIXES: tuple[str, ...] = (
    "legacy_import_",
    "migration_smoke_",
    "disposable_",
    "tmp_migration_",
    "smoke_",
)

PROTECTED_DATABASE_NAMES: frozenset[str] = frozenset(
    {
        "postgres",
        "template0",
        "template1",
        "local",
        "prod",
        "production",
        "staging",
        "target_current",
    }
)


@dataclass(frozen=True)
class DisposableTargetOptions:
    target_url: str | None = None
    database_name: str | None = None
    maintenance_database: str = "postgres"
    owner: str | None = None
    allowed_prefixes: tuple[str, ...] = DEFAULT_ALLOWED_PREFIXES
    execute: bool = False
    confirm_name: str | None = None


@dataclass
class DisposableTargetReport:
    status: str
    dry_run: bool
    database_name: str
    maintenance_database: str
    allowed_prefixes: tuple[str, ...]
    owner: str | None
    terminated_connections: int = 0
    actions: list[str] | None = None
    next_steps: list[str] | None = None


def database_name_from_url(database_url: str) -> str:
    parsed = urlparse(database_url)
    database_name = unquote(parsed.path.lstrip("/"))
    if not database_name:
        raise DisposableTargetError("Target URL does not include a database name.")
    return database_name


def username_from_url(database_url: str) -> str | None:
    return urlparse(database_url).username


def database_url_with_name(database_url: str, database_name: str) -> str:
    parsed = urlparse(database_url)
    replaced = ParseResult(
        scheme=parsed.scheme,
        netloc=parsed.netloc,
        path=f"/{database_name}",
        params=parsed.params,
        query=parsed.query,
        fragment=parsed.fragment,
    )
    return urlunparse(replaced)


def validate_disposable_database_name(
    database_name: str,
    *,
    allowed_prefixes: tuple[str, ...] = DEFAULT_ALLOWED_PREFIXES,
    execute: bool = False,
    confirm_name: str | None = None,
) -> None:
    if not DATABASE_NAME_RE.fullmatch(database_name):
        raise DisposableTargetError(
            "Unsafe database name. Use only letters, numbers, and underscores, starting with a letter or underscore."
        )
    if database_name.lower() in PROTECTED_DATABASE_NAMES:
        raise DisposableTargetError(f"Refusing to recreate protected database: {database_name}")
    if not any(database_name.startswith(prefix) for prefix in allowed_prefixes):
        formatted = ", ".join(allowed_prefixes)
        raise DisposableTargetError(
            f"Refusing to recreate database {database_name!r}; name must start with one of: {formatted}"
        )
    if execute and confirm_name != database_name:
        raise DisposableTargetError(
            "Destructive recreate requires --confirm-name to exactly match the disposable database name."
        )


def build_disposable_target_report(
    options: DisposableTargetOptions,
    *,
    status: str,
    database_name: str,
    terminated_connections: int = 0,
) -> DisposableTargetReport:
    actions = [
        f"Terminate active connections to {database_name}",
        f"Drop database {database_name} if it exists",
        f"Create empty database {database_name}",
    ]
    return DisposableTargetReport(
        status=status,
        dry_run=not options.execute,
        database_name=database_name,
        maintenance_database=options.maintenance_database,
        allowed_prefixes=options.allowed_prefixes,
        owner=options.owner,
        terminated_connections=terminated_connections,
        actions=actions,
        next_steps=[
            "Apply the current backend Django migrations to the recreated target database.",
            "Create or verify the approved target publication author.",
            "Run a dry-run import and preserve the generated manifest.",
        ],
    )


def recreate_database(conn: Connection[Any], *, database_name: str, owner: str | None) -> int:
    conn.autocommit = True
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT count(*)
            FROM pg_stat_activity
            WHERE datname = %s
              AND pid <> pg_backend_pid()
              AND pg_terminate_backend(pid)
            """,
            (database_name,),
        )
        terminated_connections = int(cursor.fetchone()[0] or 0)
        cursor.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database_name)))
        if owner:
            cursor.execute(
                sql.SQL("CREATE DATABASE {} OWNER {}").format(
                    sql.Identifier(database_name),
                    sql.Identifier(owner),
                )
            )
        else:
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    return terminated_connections


def recreate_disposable_target(options: DisposableTargetOptions) -> DisposableTargetReport:
    target_url = options.target_url or target_url_from_env()
    database_name = options.database_name or database_name_from_url(target_url)
    owner = options.owner or username_from_url(target_url)
    normalized_options = DisposableTargetOptions(
        target_url=target_url,
        database_name=database_name,
        maintenance_database=options.maintenance_database,
        owner=owner,
        allowed_prefixes=options.allowed_prefixes,
        execute=options.execute,
        confirm_name=options.confirm_name,
    )
    validate_disposable_database_name(
        database_name,
        allowed_prefixes=options.allowed_prefixes,
        execute=options.execute,
        confirm_name=options.confirm_name,
    )

    if not options.execute:
        return build_disposable_target_report(normalized_options, status="planned", database_name=database_name)

    maintenance_url = database_url_with_name(target_url, options.maintenance_database)
    try:
        with psycopg.connect(maintenance_url) as conn:
            terminated_connections = recreate_database(conn, database_name=database_name, owner=owner)
    except psycopg.Error as exc:
        raise DisposableTargetError(f"Could not recreate disposable target database {database_name}: {exc}") from exc

    return build_disposable_target_report(
        normalized_options,
        status="recreated",
        database_name=database_name,
        terminated_connections=terminated_connections,
    )


def report_to_dict(report: DisposableTargetReport) -> dict[str, Any]:
    return {
        "status": report.status,
        "dry_run": report.dry_run,
        "database_name": report.database_name,
        "maintenance_database": report.maintenance_database,
        "allowed_prefixes": list(report.allowed_prefixes),
        "owner": report.owner,
        "terminated_connections": report.terminated_connections,
        "actions": report.actions or [],
        "next_steps": report.next_steps or [],
    }


def render_report_json(report: DisposableTargetReport) -> str:
    return json.dumps(report_to_dict(report), indent=2, sort_keys=True) + "\n"
