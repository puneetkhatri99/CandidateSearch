"""Saved searches: every search by meaning with its results, so a recruiter can reopen it for
free (user decision 2026-11-02). Each person sees only their own."""

import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, Integer, SmallInteger, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import TimestampedModel

# Each person's most recent un-starred searches kept; older ones are deleted on the next save.
HISTORY_LIMIT = 50


class SavedSearch(TimestampedModel):
    __tablename__ = "saved_searches"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    query: Mapped[str] = mapped_column(Text)
    # The filters the search ran with, budget read from the text included, as sent by the API.
    filters: Mapped[dict[str, Any]] = mapped_column(JSONB)  # Any: arbitrary JSON values
    checked: Mapped[int] = mapped_column(Integer)
    ranked_by: Mapped[str] = mapped_column(String(10))
    embedding_model: Mapped[str] = mapped_column(String(100))
    ranking_model: Mapped[str | None] = mapped_column(String(100))
    prompt_version: Mapped[str | None] = mapped_column(String(50))
    starred: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))

    __table_args__ = (Index("ix_saved_searches_user_id_created_at", "user_id", "created_at"),)


class SavedSearchMatch(TimestampedModel):
    """One candidate in a saved result. A row, not JSON in the search, so deleting a candidate
    also deletes the AI's notes about them (RULES §10)."""

    __tablename__ = "saved_search_matches"

    saved_search_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("saved_searches.id", ondelete="CASCADE"), index=True
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), index=True
    )
    section: Mapped[str] = mapped_column(String(20))  # "items" or "filtered_out"
    position: Mapped[int] = mapped_column(SmallInteger)
    fit: Mapped[str | None] = mapped_column(String(10))
    criteria: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)  # Any: Criterion as JSON
    failed_filters: Mapped[list[str]] = mapped_column(JSONB)
