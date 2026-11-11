"""Логика тренировки без Telegram: порядок упражнений и быстрые замены на сегодня."""

import random
from dataclasses import replace

from data.exercises import CATALOG, Exercise, in_group
from db import DayExercise


def next_undone(exercises: list[DayExercise], done: set[int], after_id: int | None) -> DayExercise | None:
    """Следующее невыполненное упражнение после after_id (по кругу), не считая само after_id."""
    ids = [e.id for e in exercises]
    start = ids.index(after_id) if after_id in ids else -1
    for step in range(1, len(exercises) + 1):
        ex = exercises[(start + step) % len(exercises)]
        if ex.id not in done and ex.id != after_id:
            return ex
    return None


def apply_swaps(exercises: list[DayExercise], swaps: dict[int, str]) -> list[DayExercise]:
    """Упражнения дня с учётом замен на сегодня. Подходы и повторения остаются из программы."""
    result = []
    for ex in exercises:
        item = CATALOG.get(swaps.get(ex.id, ""))
        result.append(replace(ex, name=item.name, catalog_key=item.key) if item else ex)
    return result


def _set_swap(swaps: dict[int, str], original: DayExercise, new_key: str) -> None:
    if new_key == original.catalog_key:
        swaps.pop(original.id, None)  # вернулись к упражнению из программы
    else:
        swaps[original.id] = new_key


def swap_one(original: DayExercise, effective: list[DayExercise], swaps: dict[int, str]) -> Exercise | None:
    """Следующее упражнение той же группы мышц (по кругу, без повторов в этом дне).
    Нажимаешь ещё раз — предлагает следующее; дойдя до конца, возвращает исходное."""
    base = CATALOG.get(original.catalog_key or "")
    if base is None:
        return None
    group = in_group(base.group)
    keys = [g.key for g in group]
    current_key = next((e.catalog_key for e in effective if e.id == original.id), base.key)
    taken = {e.catalog_key for e in effective if e.id != original.id}
    start = keys.index(current_key) if current_key in keys else keys.index(base.key)
    for step in range(1, len(group)):
        candidate = group[(start + step) % len(group)]
        if candidate.key not in taken:
            _set_swap(swaps, original, candidate.key)
            return candidate
    return None


def swap_all(originals: list[DayExercise], swaps: dict[int, str], done: set[int]) -> int:
    """Случайно меняет все невыполненные упражнения на другие из тех же групп мышц. Возвращает, сколько заменил."""
    changed = 0
    for original in originals:
        if original.id in done:
            continue
        base = CATALOG.get(original.catalog_key or "")
        if base is None:
            continue  # своё упражнение без группы — оставляем
        effective = apply_swaps(originals, swaps)
        current_key = next(e.catalog_key for e in effective if e.id == original.id)
        taken = {e.catalog_key for e in effective if e.id != original.id}
        choices = [g for g in in_group(base.group) if g.key not in taken and g.key != current_key]
        if choices:
            _set_swap(swaps, original, random.choice(choices).key)
            changed += 1
    return changed
