import logging

from app.core.config import get_settings
from app.core.logging import StripQueryStringFilter, configure_logging


def _access_record(path: str) -> logging.LogRecord:
    # The same format and arguments uvicorn's access logger uses.
    return logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:5000", "GET", path, "1.1", 200),
        None,
    )


def test_the_query_string_is_cut_from_access_log_lines() -> None:
    record = _access_record("/api/v1/admin/candidates?q=jane%40example.com&limit=25")

    assert StripQueryStringFilter().filter(record) is True
    assert record.getMessage() == '127.0.0.1:5000 - "GET /api/v1/admin/candidates HTTP/1.1" 200'


def test_configure_logging_installs_the_filter_once() -> None:
    configure_logging(get_settings())
    configure_logging(get_settings())

    filters = logging.getLogger("uvicorn.access").filters
    assert sum(isinstance(f, StripQueryStringFilter) for f in filters) == 1
