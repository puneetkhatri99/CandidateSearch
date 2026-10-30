"""Operational commands.

    python -m app.cli create-admin --email you@company.com --name "Your Name"
    python -m app.cli embed-backfill
    python -m app.cli maintenance [--once]

The password is read with getpass (never echoed, never in shell history), or from stdin
with --password-stdin for automation.
"""

import argparse
import asyncio
import getpass
import sys

import structlog

from app.core.config import get_settings
from app.core.db import get_engine, get_sessionmaker, register_all_models
from app.core.embeddings import (
    EmbeddingConfigurationError,
    close_embedding_provider,
    get_embedding_provider,
)
from app.core.errors import AppError
from app.core.logging import configure_logging
from app.core.maintenance import run_maintenance
from app.features.auth import Role, create_user
from app.features.embeddings import TARGETS, embed_stale
from app.maintenance import maintenance_tasks

logger = structlog.get_logger("cli")


def _read_password(from_stdin: bool) -> str:
    if from_stdin:
        # Windows pipes end lines with "\r\n", and PowerShell may prefix a UTF-8 BOM; either
        # would silently become part of the password.
        return sys.stdin.readline().removeprefix("﻿").rstrip("\r\n")
    password = getpass.getpass("Password (min 12 characters): ")
    if password != getpass.getpass("Repeat password: "):
        raise SystemExit("Passwords do not match.")
    return password


async def _create_user(email: str, name: str, password: str, role: Role) -> None:
    try:
        async with get_sessionmaker()() as session:
            user = await create_user(
                session, email=email, full_name=name, password=password, role=role
            )
        logger.info("user_created", user_id=str(user.id), role=user.role)
    except AppError as exc:
        logger.error("user_not_created", reason=exc.message)
        raise SystemExit(1) from exc
    finally:
        await get_engine().dispose()


async def _embed_backfill() -> None:
    """Embed every stale job, then every stale candidate, and exit. No server needed."""
    provider = get_embedding_provider()
    try:
        for target in TARGETS:
            embedded = failed = blocked = 0
            while True:
                async with get_sessionmaker()() as session:
                    outcome = await embed_stale(session, provider, target, trigger="cli")
                embedded, failed = embedded + outcome.embedded, failed + outcome.failed
                blocked += outcome.blocked
                # Done when nothing is left (failures wait out their retry delay), or the budget
                # refused: the rest would be refused too.
                if outcome.blocked or not (outcome.embedded or outcome.failed):
                    break
            logger.info(
                "embed_backfill_completed",
                target=target.name,
                embedded=embedded,
                failed=failed,
                blocked=blocked,
            )
    finally:
        await close_embedding_provider()
        await get_engine().dispose()


async def _maintenance(once: bool) -> None:
    try:
        await run_maintenance(maintenance_tasks(), once=once)
    finally:
        await close_embedding_provider()
        await get_engine().dispose()


def _run_maintenance_command(once: bool) -> None:
    try:
        asyncio.run(_maintenance(once))
    except KeyboardInterrupt:
        logger.info("maintenance_stopped")
    except Exception as exc:
        logger.error("maintenance_failed", error_type=type(exc).__name__)
        raise SystemExit(1) from exc


def _run_embed_backfill() -> None:
    try:
        asyncio.run(_embed_backfill())
    except EmbeddingConfigurationError as exc:
        logger.error("embedding_not_configured", reason=str(exc))
        raise SystemExit(1) from exc


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("embed-backfill", help="embed every stale candidate and job, then exit")
    maintenance = commands.add_parser(
        "maintenance", help="run the background tasks: embed stale documents, prune old rows"
    )
    maintenance.add_argument("--once", action="store_true", help="run every task once, then exit")
    create = commands.add_parser("create-admin", help="create a staff user (admin by default)")
    create.add_argument("--email", required=True)
    create.add_argument("--name", required=True)
    create.add_argument("--role", choices=["admin", "recruiter"], default="admin")
    create.add_argument("--password-stdin", action="store_true")
    args = parser.parse_args()

    configure_logging(get_settings())
    register_all_models()
    if args.command == "embed-backfill":
        _run_embed_backfill()
        return
    if args.command == "maintenance":
        _run_maintenance_command(args.once)
        return
    password = _read_password(args.password_stdin)
    asyncio.run(_create_user(args.email, args.name, password, args.role))


if __name__ == "__main__":
    main()
