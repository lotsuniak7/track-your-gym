"""Режим тренировки: план дня → упражнения по одному → похвала в конце.
Прямо в тренировке можно заменить текущее упражнение или всю тренировку — только на сегодня."""

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

import keyboards as kb
import screens
from db import Database, DayExercise, Session, now_iso
from handlers.common import show_or_home
from screens import Screen
from workout_logic import next_undone, swap_all, swap_one
from workout_service import Workout, finish_workout, load_workout

router = Router(name="workout")


async def _load(cb: CallbackQuery, db: Database) -> Workout | None:
    """Текущая тренировка пользователя. Если её нет — показывает главную и возвращает None."""
    w = await load_workout(db, cb.from_user.id)
    if w is None:
        await show_or_home(cb, db, await screens.home_screen(db, cb.from_user.id), toast="Активной тренировки нет")
    return w


async def _show_step(cb: CallbackQuery, db: Database, w: Workout, target: DayExercise | None = None,
                     toast: str | None = None) -> None:
    if target is not None:
        w.current = target
    w.session.current_id = w.current.id
    await db.save_session(w.session)
    original_name = w.original(w.current.id).name if w.current.id in w.session.swaps else None
    screen = screens.step_screen(w.day, w.exercises, w.session, w.current, original_name)
    screen.widget = await screens.workout_widget(db, w)  # дальше тренировка идёт внутри виджета
    await show_or_home(cb, db, screen, toast=toast)


async def _finish(cb: CallbackQuery, db: Database, w: Workout) -> None:
    result = await finish_workout(db, cb.from_user.id, w)
    await show_or_home(cb, db, screens.finish_screen(result), toast="🏆 Тренировка завершена!")


# --- план дня и старт ---


@router.callback_query(kb.DayCb.filter(F.action == "view"))
async def day_overview(cb: CallbackQuery, callback_data: kb.DayCb, state: FSMContext, db: Database) -> None:
    await state.clear()
    await show_or_home(cb, db, await screens.overview_screen(db, cb.from_user.id, callback_data.id))


@router.callback_query(kb.DayCb.filter(F.action == "start"))
async def workout_start(cb: CallbackQuery, callback_data: kb.DayCb, db: Database) -> None:
    day = await db.get_day(cb.from_user.id, callback_data.id)
    if day is None:
        await show_or_home(cb, db, None)
        return
    exercises = await db.get_exercises(day.id)
    if not exercises:
        await cb.answer("Сначала добавь упражнения в этот день", show_alert=True)
        return
    session = Session(cb.from_user.id, day.id, exercises[0].id, set(), now_iso())
    await _show_step(cb, db, Workout(session, day, exercises, exercises, exercises[0]), toast="Погнали! 💪")


# --- шаги тренировки ---


@router.callback_query(kb.WoCb.filter(F.action == "resume"))
async def workout_resume(cb: CallbackQuery, db: Database) -> None:
    if w := await _load(cb, db):
        await _show_step(cb, db, w)


@router.callback_query(kb.WoCb.filter(F.action == "go"))
async def workout_go(cb: CallbackQuery, callback_data: kb.WoCb, db: Database) -> None:
    if w := await _load(cb, db):
        await _show_step(cb, db, w, next((e for e in w.exercises if e.id == callback_data.id), None))


@router.callback_query(kb.WoCb.filter(F.action == "done"))
async def workout_done(cb: CallbackQuery, db: Database) -> None:
    if w := await _load(cb, db):
        w.session.done.add(w.current.id)
        nxt = next_undone(w.exercises, w.session.done, w.current.id)
        if nxt is None:
            await _finish(cb, db, w)
        else:
            await _show_step(cb, db, w, nxt, toast="✅ Засчитано! Следующее 👇")


@router.callback_query(kb.WoCb.filter(F.action == "undo"))
async def workout_undo(cb: CallbackQuery, db: Database) -> None:
    if w := await _load(cb, db):
        w.session.done.discard(w.current.id)
        await _show_step(cb, db, w, toast="Отметка снята")


@router.callback_query(kb.WoCb.filter(F.action == "skip"))
async def workout_skip(cb: CallbackQuery, db: Database) -> None:
    if w := await _load(cb, db):
        nxt = next_undone(w.exercises, w.session.done, w.current.id)
        if nxt is not None:
            toast = "Вернёмся к нему позже ⏭" if w.current.id not in w.session.done else None
            await _show_step(cb, db, w, nxt, toast=toast)
        elif w.current.id in w.session.done:
            await _finish(cb, db, w)
        else:
            await cb.answer("Это последнее оставшееся упражнение 💪 Сделай его или нажми «Закончить».",
                            show_alert=True)


# --- быстрые замены на сегодня ---


@router.callback_query(kb.WoCb.filter(F.action == "swap"))
async def workout_swap(cb: CallbackQuery, db: Database) -> None:
    if w := await _load(cb, db):
        if w.current.id in w.session.done:
            await cb.answer("Это упражнение уже выполнено ✅", show_alert=True)
            return
        new = swap_one(w.original(w.current.id), w.exercises, w.session.swaps)
        if new is None:
            await cb.answer("Для этого упражнения нет замен в базе 🤷 Можно пропустить его ⏭", show_alert=True)
            return
        w.refresh()
        await _show_step(cb, db, w, toast=f"🔄 {new.name}. Не подходит — нажми ещё раз")


@router.callback_query(kb.WoCb.filter(F.action == "swap_all"))
async def workout_swap_all(cb: CallbackQuery, db: Database) -> None:
    if w := await _load(cb, db):
        changed = swap_all(w.originals, w.session.swaps, w.session.done)
        if not changed:
            await cb.answer("Нечего менять: всё выполнено или нет замен в базе", show_alert=True)
            return
        w.refresh()
        # Начинаем с первого невыполненного упражнения новой тренировки
        first = next((e for e in w.exercises if e.id not in w.session.done), w.current)
        await _show_step(cb, db, w, first, toast=f"🎲 Заменил упражнений: {changed}. Ещё раз — другой вариант")


@router.callback_query(kb.WoCb.filter(F.action == "unswap"))
async def workout_unswap(cb: CallbackQuery, db: Database) -> None:
    if w := await _load(cb, db):
        w.session.swaps.clear()
        w.refresh()
        await _show_step(cb, db, w, toast="↩️ Вернул упражнения из программы")


# --- план и завершение ---


@router.callback_query(kb.WoCb.filter(F.action == "plan"))
async def workout_plan(cb: CallbackQuery, db: Database) -> None:
    if w := await _load(cb, db):
        await db.save_session(w.session)
        await show_or_home(cb, db, await screens.overview_screen(db, cb.from_user.id, w.day.id))


@router.callback_query(kb.WoCb.filter(F.action == "finish"))
async def workout_finish(cb: CallbackQuery, db: Database) -> None:
    if w := await _load(cb, db):
        done, total = len(w.session.done), len(w.exercises)
        if done == total:
            await _finish(cb, db, w)
            return
        await show_or_home(cb, db, Screen(
            f"🏁 Закончить тренировку?\n\nВыполнено {done} из {total}, осталось {total - done}.",
            kb.confirm_kb(kb.WoCb(action="finish_ok"), kb.WoCb(action="resume"),
                          yes_text="🏁 Да, закончить", no_text="💪 Продолжить"),
        ))


@router.callback_query(kb.WoCb.filter(F.action == "finish_ok"))
async def workout_finish_ok(cb: CallbackQuery, db: Database) -> None:
    if w := await _load(cb, db):
        await _finish(cb, db, w)
