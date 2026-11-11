from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from data.exercises import BODY_PARTS, Exercise, in_muscle
from data.templates import DAY_TITLE_PRESETS, REPS_PRESETS, Template
from db import Day, DayExercise, Program


class NavCb(CallbackData, prefix="n"):
    to: str  # start | home | programs | new_program | scratch | skip_name | close | feedback


class GenderCb(CallbackData, prefix="g"):
    gender: str


class ProgCb(CallbackData, prefix="p"):
    action: str  # switch | edit | rename | delete | delete_ok | add_day
    id: int


class TplCb(CallbackData, prefix="t"):
    key: str


class DayCb(CallbackData, prefix="d"):
    action: str  # view | start | edit | rename | delete | delete_ok | custom | paste | paste_done
    id: int


class PresetCb(CallbackData, prefix="dp"):
    program_id: int
    idx: int


class GroupCb(CallbackData, prefix="gr"):
    """Выбор упражнений: без part — части тела, с part — мышцы, с muscle — упражнения."""
    day_id: int
    part: str = ""
    muscle: str = ""


class PickCb(CallbackData, prefix="pk"):
    day_id: int
    key: str


class ExCb(CallbackData, prefix="x"):
    action: str  # edit | minus | plus | up | delete | replace | custom | noop
    id: int


class RepsCb(CallbackData, prefix="r"):
    id: int
    idx: int


class AltCb(CallbackData, prefix="a"):
    id: int
    key: str


class WoCb(CallbackData, prefix="w"):
    action: str  # resume | go | done | undo | skip | swap | swap_all | unswap | plan | finish | finish_ok
    id: int = 0


def _short(text: str, limit: int = 30) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _builder() -> InlineKeyboardBuilder:
    return InlineKeyboardBuilder()


def _pairs(n: int) -> list[int]:
    """Разметка по две кнопки в ряд для n кнопок."""
    return [2] * (n // 2) + [1] * (n % 2)


# --- главное меню и программы ---


def gender_kb() -> InlineKeyboardMarkup:
    kb = _builder()
    kb.button(text="🙋‍♂️ Мужчина", callback_data=GenderCb(gender="male"))
    kb.button(text="🙋‍♀️ Девушка", callback_data=GenderCb(gender="female"))
    kb.adjust(2)
    return kb.as_markup()


def no_program_kb() -> InlineKeyboardMarkup:
    kb = _builder()
    kb.button(text="➕ Создать программу", callback_data=NavCb(to="new_program"))
    kb.button(text="⬅️ Главное меню", callback_data=NavCb(to="start"))
    kb.adjust(1)
    return kb.as_markup()


def home_kb(program: Program, days: list[Day], resume_label: str | None) -> InlineKeyboardMarkup:
    kb = _builder()
    if resume_label:
        kb.button(text=resume_label, callback_data=WoCb(action="resume"))
    for day in days:
        kb.button(text=f"💪 {_short(day.title, 34)}", callback_data=DayCb(action="view", id=day.id))
    if not days:
        kb.button(text="➕ Добавить день", callback_data=ProgCb(action="add_day", id=program.id))
    kb.button(text="⚙️ Редактировать программу", callback_data=ProgCb(action="edit", id=program.id))
    kb.button(text="🔀 Мои программы", callback_data=NavCb(to="programs"))
    kb.button(text="⬅️ Главное меню", callback_data=NavCb(to="start"))
    kb.adjust(1)
    return kb.as_markup()


def programs_kb(programs: list[Program], active_id: int | None) -> InlineKeyboardMarkup:
    kb = _builder()
    for p in programs:
        mark = "✅ " if p.id == active_id else ""
        kb.button(text=f"{mark}{_short(p.name)}", callback_data=ProgCb(action="switch", id=p.id))
        kb.button(text="⚙️", callback_data=ProgCb(action="edit", id=p.id))
    kb.button(text="➕ Новая программа", callback_data=NavCb(to="new_program"))
    kb.button(text="💬 Обратная связь", callback_data=NavCb(to="feedback"))
    kb.button(text="🏠 На главную", callback_data=NavCb(to="home"))
    kb.button(text="👤 Сменить раздел", callback_data=NavCb(to="start"))
    kb.adjust(*([2] * len(programs)), 1, 1, 2)
    return kb.as_markup()


def new_program_kb(templates: list[Template]) -> InlineKeyboardMarkup:
    kb = _builder()
    kb.button(text="🛠 Собрать с нуля", callback_data=NavCb(to="scratch"))
    for tpl in templates:
        kb.button(text=f"📦 Шаблон: {tpl.title}", callback_data=TplCb(key=tpl.key))
    kb.button(text="⬅️ Назад", callback_data=NavCb(to="programs"))
    kb.adjust(1)
    return kb.as_markup()


def name_prompt_kb(cancel: CallbackData, skip: bool = False) -> InlineKeyboardMarkup:
    kb = _builder()
    if skip:
        kb.button(text="⏭ Пропустить", callback_data=NavCb(to="skip_name"))
    kb.button(text="❌ Отмена", callback_data=cancel)
    kb.adjust(1)
    return kb.as_markup()


def program_editor_kb(program: Program, days: list[Day], is_active: bool) -> InlineKeyboardMarkup:
    kb = _builder()
    for i, day in enumerate(days, 1):
        kb.button(text=f"{i}. {_short(day.title)} · {day.exercise_count} упр.", callback_data=DayCb(action="edit", id=day.id))
    kb.button(text="➕ Добавить день", callback_data=ProgCb(action="add_day", id=program.id))
    kb.button(text="✏️ Название", callback_data=ProgCb(action="rename", id=program.id))
    kb.button(text="🗑 Удалить", callback_data=ProgCb(action="delete", id=program.id))
    if not is_active:
        kb.button(text="✅ Заниматься по этой программе", callback_data=ProgCb(action="switch", id=program.id))
    kb.button(text="🔀 Мои программы", callback_data=NavCb(to="programs"))
    kb.button(text="🏠 На главную", callback_data=NavCb(to="home"))
    kb.adjust(*([1] * (len(days) + 1)), 2, *([1] if not is_active else []), 2)
    return kb.as_markup()


def confirm_kb(yes: CallbackData, no: CallbackData,
               yes_text: str = "🗑 Да, удалить", no_text: str = "❌ Нет") -> InlineKeyboardMarkup:
    kb = _builder()
    kb.button(text=yes_text, callback_data=yes)
    kb.button(text=no_text, callback_data=no)
    kb.adjust(2)
    return kb.as_markup()


# --- редактор дня ---


def day_name_kb(program_id: int) -> InlineKeyboardMarkup:
    kb = _builder()
    for i, title in enumerate(DAY_TITLE_PRESETS):
        kb.button(text=title, callback_data=PresetCb(program_id=program_id, idx=i))
    kb.button(text="❌ Отмена", callback_data=ProgCb(action="edit", id=program_id))
    kb.adjust(*_pairs(len(DAY_TITLE_PRESETS)), 1)
    return kb.as_markup()


def day_editor_kb(day: Day, exercises: list[DayExercise]) -> InlineKeyboardMarkup:
    kb = _builder()
    for i, ex in enumerate(exercises, 1):
        kb.button(text=f"{i}. {_short(ex.name, 26)} · {ex.sets}×{ex.reps}", callback_data=ExCb(action="edit", id=ex.id))
    kb.button(text="➕ Добавить", callback_data=GroupCb(day_id=day.id))
    kb.button(text="📝 Списком", callback_data=DayCb(action="paste", id=day.id))
    kb.button(text="✏️ Название дня", callback_data=DayCb(action="rename", id=day.id))
    kb.button(text="🗑 Удалить день", callback_data=DayCb(action="delete", id=day.id))
    kb.button(text="▶️ К тренировке", callback_data=DayCb(action="view", id=day.id))
    kb.button(text="⬅️ К программе", callback_data=ProgCb(action="edit", id=day.program_id))
    kb.adjust(*([1] * len(exercises)), 2, 2, 2)
    return kb.as_markup()


def _added_mark(n: int) -> str:
    return f"  ✅ {n}" if n else ""


def parts_kb(day_id: int, added: set[str]) -> InlineKeyboardMarkup:
    kb = _builder()
    for part, (title, muscles) in BODY_PARTS.items():
        n = sum(ex.key in added for m in muscles for ex in in_muscle(m.key))
        kb.button(text=title + _added_mark(n), callback_data=GroupCb(day_id=day_id, part=part))
    kb.button(text="✍️ Своё упражнение", callback_data=DayCb(action="custom", id=day_id))
    kb.button(text="💬 Нет нужного?", callback_data=NavCb(to="feedback"))
    kb.button(text="✅ Готово", callback_data=DayCb(action="edit", id=day_id))
    kb.adjust(*_pairs(len(BODY_PARTS)), 2, 1)
    return kb.as_markup()


def muscles_kb(day_id: int, part: str, added: set[str]) -> InlineKeyboardMarkup:
    kb = _builder()
    for m in BODY_PARTS[part][1]:
        n = sum(ex.key in added for ex in in_muscle(m.key))
        kb.button(text=m.title + _added_mark(n), callback_data=GroupCb(day_id=day_id, part=part, muscle=m.key))
    kb.button(text="⬅️ Части тела", callback_data=GroupCb(day_id=day_id))
    kb.button(text="✅ Готово", callback_data=DayCb(action="edit", id=day_id))
    kb.adjust(*([1] * len(BODY_PARTS[part][1])), 2)
    return kb.as_markup()


def group_exercises_kb(day_id: int, part: str, exercises: list[Exercise], added: set[str]) -> InlineKeyboardMarkup:
    kb = _builder()
    for ex in exercises:
        mark = "✅ " if ex.key in added else "➕ "
        kb.button(text=mark + ex.name, callback_data=PickCb(day_id=day_id, key=ex.key))
    kb.button(text=f"⬅️ {BODY_PARTS[part][0]}", callback_data=GroupCb(day_id=day_id, part=part))
    kb.button(text="✅ Готово", callback_data=DayCb(action="edit", id=day_id))
    kb.adjust(*([1] * len(exercises)), 2)
    return kb.as_markup()


def exercise_edit_kb(ex: DayExercise) -> InlineKeyboardMarkup:
    kb = _builder()
    kb.button(text="➖", callback_data=ExCb(action="minus", id=ex.id))
    kb.button(text=f"{ex.sets} подх.", callback_data=ExCb(action="noop", id=ex.id))
    kb.button(text="➕", callback_data=ExCb(action="plus", id=ex.id))
    for i, reps in enumerate(REPS_PRESETS):
        kb.button(text=f"· {reps} ·" if reps == ex.reps else reps, callback_data=RepsCb(id=ex.id, idx=i))
    kb.button(text="🔄 Заменить", callback_data=ExCb(action="replace", id=ex.id))
    kb.button(text="⬆️ Выше", callback_data=ExCb(action="up", id=ex.id))
    kb.button(text="🗑 Удалить", callback_data=ExCb(action="delete", id=ex.id))
    kb.button(text="⬅️ К дню", callback_data=DayCb(action="edit", id=ex.day_id))
    kb.adjust(3, len(REPS_PRESETS), 2, 2)
    return kb.as_markup()


def alternatives_kb(ex: DayExercise, alternatives: list[Exercise]) -> InlineKeyboardMarkup:
    kb = _builder()
    for alt in alternatives:
        kb.button(text=alt.name, callback_data=AltCb(id=ex.id, key=alt.key))
    kb.button(text="✍️ Своё название", callback_data=ExCb(action="custom", id=ex.id))
    kb.button(text="⬅️ Назад", callback_data=ExCb(action="edit", id=ex.id))
    kb.adjust(1)
    return kb.as_markup()


def single_kb(text: str, callback: CallbackData) -> InlineKeyboardMarkup:
    kb = _builder()
    kb.button(text=text, callback_data=callback)
    return kb.as_markup()


def paste_kb(day_id: int, has_items: bool) -> InlineKeyboardMarkup:
    kb = _builder()
    if has_items:
        kb.button(text="✅ Сохранить день", callback_data=DayCb(action="paste_done", id=day_id))
    kb.button(text="❌ Отмена", callback_data=DayCb(action="edit", id=day_id))
    kb.adjust(1)
    return kb.as_markup()


# --- тренировка ---


def overview_kb(day: Day, has_exercises: bool, progress: str | None) -> InlineKeyboardMarkup:
    kb = _builder()
    if progress:
        kb.button(text=f"▶️ Продолжить ({progress})", callback_data=WoCb(action="resume"))
        kb.button(text="🔁 Начать заново", callback_data=DayCb(action="start", id=day.id))
    elif has_exercises:
        kb.button(text="▶️ Начать тренировку", callback_data=DayCb(action="start", id=day.id))
    kb.button(text="✏️ Изменить день", callback_data=DayCb(action="edit", id=day.id))
    kb.button(text="🏠 На главную", callback_data=NavCb(to="home"))
    kb.adjust(1)
    return kb.as_markup()


def step_kb(exercises: list[DayExercise], done: set[int], current: DayExercise,
            has_swaps: bool) -> InlineKeyboardMarkup:
    kb = _builder()
    if current.id in done:
        kb.button(text="↩️ Снять отметку", callback_data=WoCb(action="undo"))
        kb.button(text="➡️ Дальше", callback_data=WoCb(action="skip"))
    else:
        kb.button(text="✅ Выполнено", callback_data=WoCb(action="done"))
        kb.button(text="⏭ Пропустить", callback_data=WoCb(action="skip"))
    for i, ex in enumerate(exercises, 1):
        if ex.id == current.id:
            label = f"👉 {i}"
        elif ex.id in done:
            label = f"✅ {i}"
        else:
            label = str(i)
        kb.button(text=label, callback_data=WoCb(action="go", id=ex.id))
    kb.button(text="🔄 Заменить это", callback_data=WoCb(action="swap"))
    kb.button(text="🎲 Заменить всё", callback_data=WoCb(action="swap_all"))
    if has_swaps:
        kb.button(text="↩️ Вернуть как в программе", callback_data=WoCb(action="unswap"))
    kb.button(text="📋 План дня", callback_data=WoCb(action="plan"))
    kb.button(text="🏁 Закончить", callback_data=WoCb(action="finish"))
    n = len(exercises)
    per_row = n if n <= 6 else -(-n // -(-n // 6))  # до 6 в ряд, ряды примерно поровну
    rows = [per_row] * (n // per_row) + ([n % per_row] if n % per_row else [])
    kb.adjust(1, 1, *rows, 2, *([1] if has_swaps else []), 2)
    return kb.as_markup()
