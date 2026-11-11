"""Экраны бота: каждая функция собирает текст + клавиатуру (+ картинку).
Хендлеры только меняют данные и показывают нужный экран."""

import json
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import escape

from aiogram.types import InlineKeyboardMarkup, Message

import keyboards as kb
from data.exercises import BODY_PARTS, CATALOG, MUSCLES, alternatives_for, in_muscle, muscle_label
from data.templates import SECTIONS_READY, templates_for
from db import Database, Day, DayExercise, Session
from utils import plural
from widgets import render
from workout_logic import apply_swaps
from workout_service import FinishResult, Workout

SETS = ("подход", "подхода", "подходов")
EXERCISES = ("упражнение", "упражнения", "упражнений")
WORKOUTS = ("тренировка", "тренировки", "тренировок")


@dataclass
class Widget:
    """HTML-виджет вместо обычного сообщения. Если Telegram его не примет — покажем text + kb."""
    html: str
    caption: str | None
    chat_data: str | None = None
    on_sent: Callable[[Message], Awaitable[None]] | None = None


@dataclass
class Screen:
    text: str
    kb: InlineKeyboardMarkup
    image: str | None = None
    widget: Widget | None = None
    widget_text: str | None = None  # текст для универсального виджета, если обычный там избыточен


def _group(ex: DayExercise) -> str | None:
    return muscle_label(ex.catalog_key)


def _image(ex: DayExercise) -> str | None:
    item = CATALOG.get(ex.catalog_key) if ex.catalog_key else None
    return item.image if item else None


def _tip(ex: DayExercise) -> list[str]:
    item = CATALOG.get(ex.catalog_key) if ex.catalog_key else None
    return ["", f"📝 <i>{escape(item.tip)}</i>"] if item and item.tip else []


def _ex_line(i: int, ex: DayExercise, mark: str = "") -> str:
    return f"{mark}{i}. <b>{escape(ex.name)}</b> — {ex.sets} × {escape(ex.reps)}"


# --- меню и программы ---


def start_screen(note: str = "") -> Screen:
    text = ("👋 <b>Привет!</b>\n\nЯ твой тренировочный помощник: веду по тренировке упражнение за упражнением "
            "и хвалю в конце 💪")
    if note:
        text = note
    return Screen(f"{text}\n\nВыбери раздел:", kb.gender_kb())




async def home_screen(db: Database, user_id: int) -> Screen:
    user = await db.get_user(user_id)
    if user is None or user.gender not in SECTIONS_READY:
        return start_screen()

    program = await db.get_program(user_id, user.active_program_id)
    if program is None:
        if await db.list_programs(user_id):
            return await programs_screen(db, user_id)
        return Screen(
            "💪 <b>Давай соберём твою программу!</b>\n\n"
            "Программа — это набор тренировочных дней. Собери свою с нуля за пару минут "
            "или возьми готовый шаблон и поменяй под себя.",
            kb.no_program_kb(),
        )

    days = await db.get_days(program.id)
    lines = [f"🏠 <b>{escape(program.name)}</b>", ""]
    resume_label = None
    session = await db.get_session(user_id)
    session_day = await db.get_day(user_id, session.day_id) if session else None
    if session and session_day:
        exercises = await db.get_exercises(session_day.id)
        done = len(session.done & {e.id for e in exercises})
        lines += [f"⏱ Незаконченная тренировка: <b>{escape(session_day.title)}</b> ({done}/{len(exercises)})", ""]
        resume_label = f"▶️ Продолжить: {session_day.title[:25]} ({done}/{len(exercises)})"
    if days:
        lines.append("Какая тренировка сегодня? 👇")
    else:
        lines.append("В программе пока нет дней — добавь первый 👇")
    screen = Screen("\n".join(lines), kb.home_kb(program, days, resume_label))
    screen.widget = await _home_widget(db, user_id, program.name, days, session if session_day else None)
    return screen


async def _home_widget(db: Database, user_id: int, program_name: str, days: list[Day],
                       session: Session | None) -> Widget | None:
    items, session_info = [], None
    for day in days:
        exercises = await db.get_exercises(day.id)
        total_sets = sum(e.sets for e in exercises)
        items.append({
            "i": day.id, "t": day.title,
            "c": len(exercises), "cw": plural(len(exercises), EXERCISES),
            "s": total_sets, "sw": plural(total_sets, SETS),
            "x": [[e.name, f"{e.sets}×{e.reps}"] for e in exercises],
        })
        if session and session.day_id == day.id and exercises:
            session_info = {"i": day.id, "d": len(session.done & {e.id for e in exercises}), "t": len(exercises)}
    count = await db.workout_count(user_id)
    html = render.home_html(program_name, count, plural(count, WORKOUTS), items, session_info)
    return Widget(html, "Выбери день и жми «Начать» 💪") if html else None


async def programs_screen(db: Database, user_id: int) -> Screen:
    user = await db.get_user(user_id)
    programs = await db.list_programs(user_id)
    active_id = user.active_program_id if user else None
    lines = ["🔀 <b>Мои программы</b>", ""]
    if programs:
        lines.append("Нажми на программу, чтобы заниматься по ней. ⚙️ — изменить.")
        lines.append("Старые программы сохраняются — к ним можно вернуться в любой момент.")
    else:
        lines.append("Программ пока нет.")
    return Screen("\n".join(lines), kb.programs_kb(programs, active_id))


def new_program_screen(gender: str | None) -> Screen:
    return Screen(
        "➕ <b>Новая программа</b>\n\n"
        "🛠 <b>С нуля</b> — придумаешь название, добавишь дни и упражнения кнопками.\n"
        "📦 <b>Шаблон</b> — готовая программа, которую можно сразу поменять под себя.",
        kb.new_program_kb(templates_for(gender)),
    )


async def program_editor_screen(db: Database, user_id: int, program_id: int, note: str = "") -> Screen | None:
    program = await db.get_program(user_id, program_id)
    if program is None:
        return None
    user = await db.get_user(user_id)
    is_active = bool(user and user.active_program_id == program.id)
    days = await db.get_days(program.id)
    lines = []
    if note:
        lines += [note, ""]
    lines.append(f"⚙️ <b>{escape(program.name)}</b>" + ("  ✅ активная" if is_active else ""))
    lines.append("")
    head = list(lines)
    if days:
        lines += [f"{i}. {escape(d.title)} — {d.exercise_count} упр." for i, d in enumerate(days, 1)]
        lines += ["", "Нажми на день, чтобы изменить упражнения."]
        head.append("Нажми на день, чтобы изменить упражнения.")
    else:
        lines.append("Дней пока нет — нажми «➕ Добавить день».")
        head.append(lines[-1])
    return Screen("\n".join(lines), kb.program_editor_kb(program, days, is_active), widget_text="\n".join(head))


# --- редактор дня ---


async def day_editor_screen(db: Database, user_id: int, day_id: int, note: str = "") -> Screen | None:
    day = await db.get_day(user_id, day_id)
    if day is None:
        return None
    exercises = await db.get_exercises(day.id)
    lines = []
    if note:
        lines += [note, ""]
    lines += [f"✏️ <b>{escape(day.title)}</b>", f"<i>{escape(day.program_name)}</i>", ""]
    head = lines[:-1]
    if exercises:
        lines += [_ex_line(i, ex) for i, ex in enumerate(exercises, 1)]
        lines += ["", "Нажми на упражнение: подходы, повторения, замена, удаление."]
    else:
        lines.append("Упражнений пока нет — нажми «➕ Добавить».")
        head.append(lines[-1])
    return Screen("\n".join(lines), kb.day_editor_kb(day, exercises), widget_text="\n".join(head))


async def _added_keys(db: Database, day: Day) -> set[str]:
    return {e.catalog_key for e in await db.get_exercises(day.id) if e.catalog_key}


async def groups_screen(db: Database, day: Day) -> Screen:
    return Screen(
        f"➕ <b>{escape(day.title)}</b> — что качаем?\n\nВыбери часть тела, потом конкретную мышцу.",
        kb.parts_kb(day.id, await _added_keys(db, day)),
    )


async def part_screen(db: Database, day: Day, part: str) -> Screen:
    title = BODY_PARTS[part][0]
    return Screen(
        f"➕ <b>{escape(title)}</b> — какая мышца?\n\n✅ — сколько упражнений уже добавлено в «{escape(day.title)}».",
        kb.muscles_kb(day.id, part, await _added_keys(db, day)),
    )


async def group_exercises_screen(db: Database, day: Day, part: str, muscle: str) -> Screen:
    title = f"{BODY_PARTS[part][0]} · {MUSCLES[muscle].title}"
    return Screen(
        f"➕ <b>{escape(title)}</b>\n\n"
        f"Нажимай на упражнения — они сразу добавятся в «{escape(day.title)}» (✅).\n"
        "Нажмёшь ещё раз — уберётся.",
        kb.group_exercises_kb(day.id, part, in_muscle(muscle), await _added_keys(db, day)),
    )


def exercise_edit_screen(ex: DayExercise) -> Screen:
    lines = [f"<b>{escape(ex.name)}</b>", ""]
    if group := _group(ex):
        lines.append(f"💪 {escape(group)}")
    lines.append(f"🔁 {ex.sets} {plural(ex.sets, SETS)} × {escape(ex.reps)}")
    lines += _tip(ex)
    lines += ["", "➖ ➕ — подходы, ниже — повторения."]
    return Screen("\n".join(lines), kb.exercise_edit_kb(ex), _image(ex))


def replace_screen(ex: DayExercise) -> Screen:
    alternatives = alternatives_for(ex.catalog_key)
    if alternatives:
        text = f"🔄 Чем заменить <b>{escape(ex.name)}</b>?\n\nВарианты на ту же группу мышц:"
    else:
        text = f"🔄 Для <b>{escape(ex.name)}</b> нет готовых замен — введи своё название."
    return Screen(text, kb.alternatives_kb(ex, alternatives))


# --- тренировка ---


async def overview_screen(db: Database, user_id: int, day_id: int) -> Screen | None:
    day = await db.get_day(user_id, day_id)
    if day is None:
        return None
    exercises = await db.get_exercises(day.id)
    session = await db.get_session(user_id)
    in_progress = session is not None and session.day_id == day.id
    if in_progress:
        exercises = apply_swaps(exercises, session.swaps)

    lines = [f"🏋️ <b>{escape(day.title)}</b>", ""]
    if exercises:
        lines.append("Вот всё, что нужно сделать сегодня:")
        lines.append("")
        for i, ex in enumerate(exercises, 1):
            mark = ""
            if in_progress:
                mark = ("✅ " if ex.id in session.done else "") + ("🔄 " if ex.id in session.swaps else "")
            lines.append(_ex_line(i, ex, mark))
        total_sets = sum(e.sets for e in exercises)
        lines += ["", f"Всего: {len(exercises)} {plural(len(exercises), EXERCISES)}, "
                      f"{total_sets} {plural(total_sets, SETS)}."]
    else:
        lines.append("В этом дне пока нет упражнений — добавь их через «✏️ Изменить день».")

    progress = None
    if in_progress and exercises:
        progress = f"{len(session.done & {e.id for e in exercises})}/{len(exercises)}"
    return Screen("\n".join(lines), kb.overview_kb(day, bool(exercises), progress))


def workout_state(session: Session) -> str:
    """Состояние тренировки для chat_data виджета."""
    return json.dumps({"c": session.current_id, "d": sorted(session.done)}, separators=(",", ":"))


async def workout_widget(db: Database, w: Workout) -> Widget | None:
    items = []
    weights = await db.last_weights(w.session.user_id)
    for ex in w.exercises:
        catalog = CATALOG.get(ex.catalog_key or "")
        item = {"i": ex.id, "n": ex.name, "s": ex.sets, "r": ex.reps}
        if label := muscle_label(ex.catalog_key):
            item["m"] = label
        if ex.id in w.session.swaps:
            item["o"] = w.original(ex.id).name
        if catalog and catalog.tip:
            item["h"] = 1
        if weight := weights.get(db.exercise_key(ex)):
            item["w"] = int(weight) if float(weight).is_integer() else weight
        items.append(item)
    html = render.workout_html(w.day.title, items, bool(w.session.swaps))
    if html is None:
        return None

    async def remember(message: Message) -> None:
        await db.set_session_message(w.session.user_id, message.message_id)

    return Widget(html, f"🏋️ {w.day.title}", workout_state(w.session), remember)


def step_screen(day: Day, exercises: list[DayExercise], session: Session, current: DayExercise,
                original_name: str | None = None) -> Screen:
    """exercises — уже с заменами на сегодня; original_name — что было в программе, если текущее заменено."""
    index = next(i for i, e in enumerate(exercises, 1) if e.id == current.id)
    done_count = len(session.done & {e.id for e in exercises})
    progress = "".join("🟩" if e.id in session.done else ("🟨" if e.id == current.id else "⬜") for e in exercises)

    lines = [
        f"🏋️ {escape(day.title)} · упражнение {index} из {len(exercises)}",
        "",
        f"<b>{escape(current.name)}</b>",
        f"🔁 {current.sets} {plural(current.sets, SETS)} × {escape(current.reps)} повторений",
    ]
    if group := _group(current):
        lines.append(f"💪 {escape(group)}")
    if original_name:
        lines.append(f"🔄 Замена на сегодня · в программе: {escape(original_name)}")
    lines += _tip(current)
    if current.id in session.done:
        lines += ["", "✅ Уже выполнено"]
    lines += ["", f"{progress}  {done_count}/{len(exercises)}"]
    return Screen("\n".join(lines), kb.step_kb(exercises, session.done, current, bool(session.swaps)),
                  _image(current))


def _kg(value: float) -> str:
    return f"{value:g}"


async def stats_screen(db: Database, user_id: int) -> Screen:
    """Прогресс: сколько тренировок и как растут веса."""
    now = datetime.now(timezone.utc)
    total = await db.workout_count(user_id)
    week = await db.workouts_since(user_id, (now - timedelta(days=7)).isoformat(timespec="seconds"))
    month = await db.workouts_since(user_id, (now - timedelta(days=30)).isoformat(timespec="seconds"))
    lines = ["📊 <b>Прогресс</b>", "",
             f"🏋️ Тренировок: <b>{total}</b> · за 7 дней: <b>{week}</b> · за 30 дней: <b>{month}</b>"]

    if recent := await db.recent_workouts(user_id, 3):
        lines += ["", "<b>Последние тренировки</b>"]
        for r in recent:
            date = datetime.fromisoformat(r["finished_at"]).astimezone().strftime("%d.%m")
            lines.append(f"{date} · {escape(r['day_title'][:24])} — {r['done_count']}/{r['total_count']}")

    if weights := await db.weight_progress(user_id, 6):
        lines += ["", "<b>Веса</b>"]
        for r in weights:
            diff = r["last"] - r["first"]
            change = f" ({'+' if diff > 0 else '−'}{_kg(abs(diff))})" if diff else ""
            record = f", рекорд {_kg(r['best'])}" if r["best"] > r["last"] else ""
            lines.append(f"{escape(r['name'][:26])}: <b>{_kg(r['last'])} кг</b>{change}{record}")
    elif total:
        lines += ["", "Указывай вес в тренировке кнопками −/+ — здесь появится, как он растёт."]
    else:
        lines += ["", "Пока пусто. Проведи первую тренировку — и здесь появится статистика 💪"]
    return Screen("\n".join(lines), kb.single_kb("🏠 На главную", kb.NavCb(to="home")))


PRAISE_FULL = {
    "male": [
        "Красавчик! Всё сделал на 100% 💪",
        "Мощно! Мышцы скажут тебе спасибо 🔥",
        "Вот это работа! Так держать, чемпион 🏆",
        "Машина! Ни одного пропуска 🚀",
        "Легенда зала! Отличная тренировка 💥",
    ],
    "female": [
        "Умница! Всё сделала на 100% 💪",
        "Красотка! Мышцы скажут тебе спасибо 🔥",
        "Вот это работа! Так держать, чемпионка 🏆",
        "Огонь! Ни одного пропуска 🚀",
        "Королева зала! Отличная тренировка 👑",
    ],
}
PRAISE_PARTIAL = {
    "male": [
        "Хорошая работа! Главное — что ты пришёл и сделал 💪",
        "Неплохо! В следующий раз добьём всё до конца 🔥",
        "Молодец! Каждая тренировка приближает к цели 🚀",
    ],
    "female": [
        "Хорошая работа! Главное — что ты пришла и сделала 💪",
        "Неплохо! В следующий раз добьём всё до конца 🔥",
        "Молодец! Каждая тренировка приближает к цели 🚀",
    ],
}


def praise_for(gender: str | None, done: int, total: int) -> str:
    if done == 0:
        return "Ничего не отмечено — не страшно, в следующий раз всё получится 💪"
    praises = PRAISE_FULL if done >= total else PRAISE_PARTIAL
    return random.choice(praises.get(gender or "male", praises["male"]))


def finish_state(r: FinishResult) -> str:
    """Экран финиша для chat_data виджета."""
    return json.dumps({"f": {
        "a": int(r.done >= r.total and r.done > 0), "p": praise_for(r.gender, r.done, r.total),
        "d": r.done, "t": r.total, "m": r.minutes or 0, "n": r.number or 0,
    }}, ensure_ascii=False, separators=(",", ":"))


def finish_screen(r: FinishResult) -> Screen:
    day, done, total, workout_number = r.day, r.done, r.total, r.number
    if done == 0:
        return Screen(
            "🏁 Тренировка закрыта.\n\nНичего не отмечено — не страшно, в следующий раз всё получится 💪",
            kb.single_kb("🏠 На главную", kb.NavCb(to="home")),
        )
    praise = praise_for(r.gender, done, total)
    lines = [
        "🏆 <b>Тренировка завершена!</b>",
        "",
        praise,
        "",
        f"📋 {escape(day.title)}",
        f"✅ Выполнено: {done} из {total}",
    ]
    if r.minutes:
        lines.append(f"⏱ Время: {r.minutes} мин")
    if workout_number:
        lines.append(f"🔥 Это твоя {workout_number}-я тренировка")
    return Screen("\n".join(lines), kb.single_kb("🏠 На главную", kb.NavCb(to="home")))
