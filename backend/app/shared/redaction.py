"""Removes direct identifiers (emails, URLs, phone numbers, names) from text before it is
embedded or ranked on.

Name redaction is deliberately aggressive: a name that is also an ordinary word ("Will",
"Rose") is removed wherever it appears. Losing a word costs far less than leaking identity.
"""

import re
import unicodedata
from collections.abc import Sequence

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_URL_RE = re.compile(r"(?:https?://|www\.)\S+|\b(?:[\w-]+\.)+[a-z]{2,}/\S*", re.IGNORECASE)
_PHONE_CANDIDATE_RE = re.compile(r"\+?\(?\d[\d\s().-]{8,}\d")
_YEAR_RE = re.compile(r"(?:19|20)\d{2}")
_NAME_SEPARATORS_RE = re.compile("[\\s\\-'\N{RIGHT SINGLE QUOTATION MARK}.]+")
_MIN_PHONE_DIGITS = 10
_MIN_NAME_PART_LENGTH = 2


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def _redact_phones(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        found = match.group()
        groups = re.findall(r"\d+", found)
        # Year ranges like "2015-2019-2023" have enough digits but aren't phone numbers.
        if all(_YEAR_RE.fullmatch(g) for g in groups):
            return found
        digits = sum(len(g) for g in groups)
        return "" if digits >= _MIN_PHONE_DIGITS else found

    return _PHONE_CANDIDATE_RE.sub(replace, text)


def contains_phone_number(text: str) -> bool:
    """The phone rule redact_identifiers uses: 10+ digits, year ranges excepted."""
    return _redact_phones(text) != text


def _name_variants(full_name: str) -> list[str]:
    name = _nfc(full_name).strip()
    parts = {p for p in _NAME_SEPARATORS_RE.split(name) if len(p) >= _MIN_NAME_PART_LENGTH}
    hyphen_free = {p for p in name.split() if len(p) >= _MIN_NAME_PART_LENGTH}
    # Longest first so "Mary-Jane" is removed whole before "Mary" and "Jane".
    return sorted({name, *hyphen_free, *parts}, key=len, reverse=True)


def redact_identifiers(text: str, names: Sequence[str]) -> str:
    text = _nfc(text)
    text = _EMAIL_RE.sub("", text)
    text = _URL_RE.sub("", text)
    text = _redact_phones(text)
    variants = {variant for name in names for variant in _name_variants(name)}
    for variant in sorted(variants, key=len, reverse=True):
        if not variant:
            continue
        text = re.sub(rf"(?<!\w){re.escape(variant)}(?!\w)", "", text, flags=re.IGNORECASE)
    return " ".join(text.split())
