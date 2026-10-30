"""Structured logging: JSON in deployed environments, readable console output locally."""

import logging
import sys

import structlog

from app.core.config import Settings


class StripQueryStringFilter(logging.Filter):
    """uvicorn's access log prints the full URL; query strings carry searches (names, emails)."""

    def filter(self, record: logging.LogRecord) -> bool:
        # uvicorn passes (client, method, path_with_query, http_version, status).
        args = record.args
        if isinstance(args, tuple) and len(args) == 5 and isinstance(args[2], str):
            record.args = (args[0], args[1], args[2].split("?", 1)[0], args[3], args[4])
        return True


def configure_logging(settings: Settings) -> None:
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]
    renderer: structlog.types.Processor = (
        structlog.dev.ConsoleRenderer()
        if settings.environment == "local"
        else structlog.processors.JSONRenderer()
    )

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping()[settings.log_level.upper()]
        ),
        logger_factory=structlog.PrintLoggerFactory(sys.stdout),
        cache_logger_on_first_use=True,
    )
    # The OpenAI SDK logs request options (including input text) at debug level; keep it quiet.
    for noisy_logger in ("openai", "httpx", "httpx2"):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)
    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, StripQueryStringFilter) for f in access_logger.filters):
        access_logger.addFilter(StripQueryStringFilter())
