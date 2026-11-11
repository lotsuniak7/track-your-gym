import re

MAX_NAME_LEN = 60

# "Жим лёжа 3x10", "Жим лёжа - 4х8-12", "Планка 3*60"
_ITEM_RE = re.compile(
    r"^(?P<name>.+?)[\s:—–-]*(?P<sets>\d{1,2})\s*[xх×*]\s*(?P<reps>\d{1,3}(?:\s*[-–]\s*\d{1,3})?)$",
    re.IGNORECASE,
)
_PREFIX_RE = re.compile(r"^\s*(?:\d{1,2}[.)]|[-•*])\s*")


def parse_item(raw: str) -> tuple[str, int | None, str | None] | None:
    """'1. Жим лёжа 3x8-12' → ('Жим лёжа', 3, '8–12'). Без подходов → (название, None, None)."""
    text = _PREFIX_RE.sub("", raw).strip()
    if not text:
        return None
    sets = reps = None
    if m := _ITEM_RE.match(text):
        text = m["name"].strip()
        sets = max(1, min(int(m["sets"]), 20))
        reps = re.sub(r"\s*[-–]\s*", "–", m["reps"])
    return text[:MAX_NAME_LEN], sets, reps


def split_items(text: str) -> list[str]:
    return [part for part in re.split(r"[\n,;]+", text) if part.strip()]


def plural(n: int, forms: tuple[str, str, str]) -> str:
    """plural(3, ("подход", "подхода", "подходов")) → 'подхода'."""
    n = abs(n) % 100
    if 11 <= n <= 14:
        return forms[2]
    n %= 10
    if n == 1:
        return forms[0]
    if 2 <= n <= 4:
        return forms[1]
    return forms[2]


def clean_title(text: str, limit: int = 40) -> str:
    return " ".join(text.split())[:limit]
