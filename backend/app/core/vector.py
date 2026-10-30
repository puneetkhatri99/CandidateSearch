"""SQLAlchemy type for pgvector's `vector(n)` column, without the extra `pgvector` package."""

from collections.abc import Callable

from sqlalchemy import Text, cast
from sqlalchemy.engine import Dialect
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.types import UserDefinedType


class Vector(UserDefinedType[list[float]]):
    cache_ok = True

    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions

    def get_col_spec(self, **_: object) -> str:
        return f"vector({self.dimensions})"

    def bind_processor(self, dialect: Dialect) -> Callable[[list[float] | None], str | None]:
        def process(value: list[float] | None) -> str | None:
            if value is None:
                return None
            return "[" + ",".join(repr(float(x)) for x in value) + "]"

        return process

    def bind_expression(self, bindvalue: ColumnElement[list[float]]) -> ColumnElement[list[float]]:
        # asyncpg has no codec for unknown types such as `vector`, so the parameter travels as
        # text and Postgres converts it; the inner cast pins the parameter type to text.
        return cast(cast(bindvalue, Text), self)
