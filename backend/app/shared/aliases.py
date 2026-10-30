"""Different spellings of the same skill or city, so a hard filter doesn't drop a candidate
who wrote "postgresql" for a job asking for "postgres". Values are compared lower-cased, the
way tags are stored (shared.validation.normalize_tag).

shortcut: a hand-kept list of common spellings; replace with a maintained taxonomy when
recruiters report misses it doesn't cover.
"""

_SKILL_GROUPS: tuple[frozenset[str], ...] = tuple(
    frozenset(group)
    for group in (
        {"postgres", "postgresql", "psql"},
        {"javascript", "js"},
        {"typescript", "ts"},
        {"react", "reactjs", "react.js"},
        {"node", "nodejs", "node.js"},
        {"vue", "vuejs", "vue.js"},
        {"next.js", "nextjs"},
        {"kubernetes", "k8s"},
        {"golang", "go"},
        {"python", "python3"},
        {"c#", "csharp"},
        {".net", "dotnet"},
        {"aws", "amazon web services"},
        {"gcp", "google cloud", "google cloud platform"},
        {"machine learning", "ml"},
        {"mongodb", "mongo"},
    )
)

_CITY_GROUPS: tuple[frozenset[str], ...] = tuple(
    frozenset(group)
    for group in (
        {"bengaluru", "bangalore"},
        {"gurugram", "gurgaon"},
        {"mumbai", "bombay"},
        {"chennai", "madras"},
        {"kolkata", "calcutta"},
        {"delhi", "new delhi"},
        {"pune", "poona"},
        {"thiruvananthapuram", "trivandrum"},
        {"kochi", "cochin"},
        {"vadodara", "baroda"},
        {"munich", "münchen"},
        {"cologne", "köln"},
    )
)


def _spellings(value: str, groups: tuple[frozenset[str], ...]) -> frozenset[str]:
    key = " ".join(value.split()).lower()
    return next((group for group in groups if key in group), frozenset({key}))


def skill_spellings(skill: str) -> frozenset[str]:
    """Every accepted spelling of a skill, itself included."""
    return _spellings(skill, _SKILL_GROUPS)


def city_spellings(city: str) -> frozenset[str]:
    """Every accepted spelling of a city, itself included."""
    return _spellings(city, _CITY_GROUPS)
