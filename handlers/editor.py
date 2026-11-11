"""Редактор дней и упражнений: всё кнопками, текст — только для названий."""

from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import keyboards as kb
import screens
from data.exercises import BODY_PARTS, CATALOG, MUSCLES, find_by_name, muscle_of
from data.templates import DAY_TITLE_PRESETS, REPS_PRESETS
from db import Database, NewExercise
from handlers.common import ask_text, reply_screen, show_or_home
from screens import Screen
from states import CustomExercise, DayName, PasteDay, ReplaceCustom
from utils import clean_title, parse_item, split_items

router = Router(name="editor")

MAX_DAY_EXERCISES = 15
MAX_SETS = 10


def _to_new_exercise(raw: str, default_sets: int, default_reps: str) -> NewExercise | None:
    parsed = parse_item(raw)
    if parsed is None:
        return None
    name, sets, reps = parsed
    item = find_by_name(name)  # совпало с базой — будет картинка и замены
    return NewExercise(item.name if item else name, sets or default_sets, reps or default_reps,
                       item.key if item else None)


# --- дни ---


async def _added_day_screen(db: Database, user_id: int, program_id: int, title: str) -> Screen | None:
    program = await db.get_program(user_id, program_id)
    if program is None:
        return None
    day_id = await db.add_day(program.id, title)
    day = await db.get_day(user_id, day_id)
    screen = await screens.groups_screen(db, day)
    screen.text = f"✅ День «{escape(title)}» добавлен.\n\n" + screen.text
    return screen


@router.callback_query(kb.PresetCb.filter())
async def day_preset(cb: CallbackQuery, callback_data: kb.PresetCb, state: FSMContext, db: Database) -> None:
    await state.clear()
    title = DAY_TITLE_PRESETS[callback_data.idx % len(DAY_TITLE_PRESETS)]
    await show_or_home(cb, db, await _added_day_screen(db, cb.from_user.id, callback_data.program_id, title))


@router.message(DayName.waiting, F.text)
async def day_name_entered(message: Message, state: FSMContext, db: Database) -> None:
    title = clean_title(message.text)
    data = await state.get_data()
    user_id = message.from_user.id
    if not title:
        await message.answer("Название пустое — напиши ещё раз 🙏")
        return
    if day_id := data.get("day_id"):
        if await db.get_day(user_id, day_id):
            await db.rename_day(day_id, title)
        screen = await screens.day_editor_screen(db, user_id, day_id, note="✏️ Название сохранено")
    else:
        screen = await _added_day_screen(db, user_id, data["program_id"], title)
    await reply_screen(message, state, db, screen)


@router.callback_query(kb.DayCb.filter(F.action == "edit"))
async def day_edit(cb: CallbackQuery, callback_data: kb.DayCb, state: FSMContext, db: Database) -> None:
    await state.clear()
    await show_or_home(cb, db, await screens.day_editor_screen(db, cb.from_user.id, callback_data.id))


@router.callback_query(kb.DayCb.filter(F.action == "rename"))
async def day_rename(cb: CallbackQuery, callback_data: kb.DayCb, state: FSMContext, db: Database) -> None:
    day = await db.get_day(cb.from_user.id, callback_data.id)
    if day is None:
        await show_or_home(cb, db, None)
        return
    await ask_text(cb, db, state, DayName.waiting, Screen(
        f"✏️ Новое название для дня «{escape(day.title)}»?",
        kb.single_kb("❌ Отмена", kb.DayCb(action="edit", id=day.id)),
    ), day_id=day.id)


@router.callback_query(kb.DayCb.filter(F.action == "delete"))
async def day_delete(cb: CallbackQuery, callback_data: kb.DayCb, db: Database) -> None:
    day = await db.get_day(cb.from_user.id, callback_data.id)
    if day is None:
        await show_or_home(cb, db, None)
        return
    await show_or_home(cb, db, Screen(
        f"🗑 Удалить день «{escape(day.title)}» со всеми упражнениями?",
        kb.confirm_kb(kb.DayCb(action="delete_ok", id=day.id), kb.DayCb(action="edit", id=day.id)),
    ))


@router.callback_query(kb.DayCb.filter(F.action == "delete_ok"))
async def day_delete_ok(cb: CallbackQuery, callback_data: kb.DayCb, db: Database) -> None:
    day = await db.get_day(cb.from_user.id, callback_data.id)
    if day is None:
        await show_or_home(cb, db, None)
        return
    await db.delete_day(day.id)
    await show_or_home(cb, db, await screens.program_editor_screen(db, cb.from_user.id, day.program_id),
                       toast="День удалён")


# --- добавление упражнений ---


@router.callback_query(kb.GroupCb.filter())
async def pick_group(cb: CallbackQuery, callback_data: kb.GroupCb, state: FSMContext, db: Database) -> None:
    await state.clear()
    day = await db.get_day(cb.from_user.id, callback_data.day_id)
    if day is None:
        await show_or_home(cb, db, None)
    elif callback_data.part in BODY_PARTS and callback_data.muscle in MUSCLES:
        await show_or_home(cb, db, await screens.group_exercises_screen(db, day, callback_data.part,
                                                                       callback_data.muscle))
    elif callback_data.part in BODY_PARTS:
        await show_or_home(cb, db, await screens.part_screen(db, day, callback_data.part))
    else:
        await show_or_home(cb, db, await screens.groups_screen(db, day))


@router.callback_query(kb.PickCb.filter())
async def pick_exercise(cb: CallbackQuery, callback_data: kb.PickCb, db: Database) -> None:
    day = await db.get_day(cb.from_user.id, callback_data.day_id)
    item = CATALOG.get(callback_data.key)
    if day is None or item is None:
        await show_or_home(cb, db, None)
        return
    exercises = await db.get_exercises(day.id)
    if any(e.catalog_key == item.key for e in exercises):
        await db.remove_last_by_key(day.id, item.key)
        toast = f"Убрано: {item.name}"
    elif len(exercises) >= MAX_DAY_EXERCISES:
        await cb.answer(f"В дне уже {MAX_DAY_EXERCISES} упражнений — это максимум", show_alert=True)
        return
    else:
        sets, reps = await db.usual_sets_reps(day.program_id)
        await db.add_exercises(day.id, [NewExercise(item.name, sets, reps, item.key)])
        toast = f"✅ Добавлено: {item.name} ({sets}×{reps})"
    muscle = muscle_of(item.group)
    part = next(p for p, (_, ms) in BODY_PARTS.items() if muscle in ms)
    await show_or_home(cb, db, await screens.group_exercises_screen(db, day, part, muscle.key), toast=toast)


@router.callback_query(kb.DayCb.filter(F.action == "custom"))
async def custom_prompt(cb: CallbackQuery, callback_data: kb.DayCb, state: FSMContext, db: Database) -> None:
    day = await db.get_day(cb.from_user.id, callback_data.id)
    if day is None:
        await show_or_home(cb, db, None)
        return
    sets, reps = await db.usual_sets_reps(day.program_id)
    await ask_text(cb, db, state, CustomExercise.waiting, Screen(
        f"✍️ <b>Своё упражнение в «{escape(day.title)}»</b>\n\n"
        "Напиши название. Можно несколько через запятую.\n"
        f"Подходы и повторения — по желанию: <code>Жим в Смите 4x6-8</code> (иначе {sets}×{escape(reps)}).",
        kb.single_kb("❌ Отмена", kb.GroupCb(day_id=day.id)),
    ), day_id=day.id)


@router.message(CustomExercise.waiting, F.text)
async def custom_entered(message: Message, state: FSMContext, db: Database) -> None:
    data = await state.get_data()
    user_id = message.from_user.id
    day = await db.get_day(user_id, data["day_id"])
    if day is None:
        await reply_screen(message, state, db, None)
        return
    sets, reps = await db.usual_sets_reps(day.program_id)
    free_slots = MAX_DAY_EXERCISES - day.exercise_count
    items = [e for raw in split_items(message.text) if (e := _to_new_exercise(raw, sets, reps))][:max(free_slots, 0)]
    if not items:
        await message.answer("Не понял название — напиши ещё раз 🙏")
        return
    await db.add_exercises(day.id, items)
    note = "✅ Добавлено: " + ", ".join(escape(e.name) for e in items)
    await reply_screen(message, state, db, await screens.day_editor_screen(db, user_id, day.id, note=note))


# --- вставка дня списком ---


def _paste_screen(day_id: int, day_title: str, items: list[dict]) -> Screen:
    lines = [
        f"📝 <b>Новый список для «{escape(day_title)}»</b>",
        "",
        "Отправь упражнения — по одному в сообщении или сразу списком (через запятую или с новой строки).",
        "Подходы — по желанию: <code>Жим гантелей 3x6-8</code>",
        "",
    ]
    if items:
        lines.append("Сейчас в списке:")
        lines += [f"{i}. {escape(it['name'])} — {it['sets']} × {escape(it['reps'])}" for i, it in enumerate(items, 1)]
        lines += ["", "Жми «✅ Сохранить день» — старый список заменится этим."]
    else:
        lines.append("Список пока пуст.")
    return Screen("\n".join(lines), kb.paste_kb(day_id, bool(items)))


@router.callback_query(kb.DayCb.filter(F.action == "paste"))
async def paste_start(cb: CallbackQuery, callback_data: kb.DayCb, state: FSMContext, db: Database) -> None:
    day = await db.get_day(cb.from_user.id, callback_data.id)
    if day is None:
        await show_or_home(cb, db, None)
        return
    await ask_text(cb, db, state, PasteDay.waiting, _paste_screen(day.id, day.title, []), day_id=day.id, items=[])


@router.message(PasteDay.waiting, F.text)
async def paste_collect(message: Message, state: FSMContext, db: Database) -> None:
    data = await state.get_data()
    day = await db.get_day(message.from_user.id, data["day_id"])
    if day is None:
        await reply_screen(message, state, db, None)
        return
    sets, reps = await db.usual_sets_reps(day.program_id)
    items: list[dict] = data["items"]
    for raw in split_items(message.text):
        if len(items) >= MAX_DAY_EXERCISES:
            break
        if ex := _to_new_exercise(raw, sets, reps):
            items.append({"name": ex.name, "sets": ex.sets, "reps": ex.reps, "key": ex.catalog_key})
    await reply_screen(message, state, db, _paste_screen(day.id, day.title, items),
                       next_state=PasteDay.waiting, day_id=day.id, items=items)


@router.callback_query(kb.DayCb.filter(F.action == "paste_done"), PasteDay.waiting)
async def paste_save(cb: CallbackQuery, state: FSMContext, db: Database) -> None:
    data = await state.get_data()
    await state.clear()
    day = await db.get_day(cb.from_user.id, data["day_id"])
    if day is None or not data["items"]:
        await show_or_home(cb, db, None)
        return
    await db.replace_day_exercises(day.id, [NewExercise(i["name"], i["sets"], i["reps"], i["key"]) for i in data["items"]])
    await show_or_home(cb, db, await screens.day_editor_screen(db, cb.from_user.id, day.id), toast="День сохранён ✅")


# --- одно упражнение ---


async def _exercise_or_home(cb: CallbackQuery, db: Database, exercise_id: int):
    ex = await db.get_exercise(cb.from_user.id, exercise_id)
    if ex is None:
        await show_or_home(cb, db, None)
    return ex


@router.callback_query(kb.ExCb.filter(F.action == "edit"))
async def exercise_edit(cb: CallbackQuery, callback_data: kb.ExCb, state: FSMContext, db: Database) -> None:
    await state.clear()
    if ex := await _exercise_or_home(cb, db, callback_data.id):
        await show_or_home(cb, db, screens.exercise_edit_screen(ex))


@router.callback_query(kb.ExCb.filter(F.action.in_({"minus", "plus"})))
async def exercise_sets(cb: CallbackQuery, callback_data: kb.ExCb, db: Database) -> None:
    if ex := await _exercise_or_home(cb, db, callback_data.id):
        sets = max(1, min(MAX_SETS, ex.sets + (1 if callback_data.action == "plus" else -1)))
        if sets == ex.sets:
            await cb.answer()
            return
        await db.update_exercise(ex.id, sets=sets)
        ex.sets = sets
        await show_or_home(cb, db, screens.exercise_edit_screen(ex), toast=f"Подходов: {sets}")


@router.callback_query(kb.ExCb.filter(F.action == "noop"))
async def exercise_noop(cb: CallbackQuery) -> None:
    await cb.answer("Меняй кнопками ➖ и ➕")


@router.callback_query(kb.RepsCb.filter())
async def exercise_reps(cb: CallbackQuery, callback_data: kb.RepsCb, db: Database) -> None:
    if ex := await _exercise_or_home(cb, db, callback_data.id):
        reps = REPS_PRESETS[callback_data.idx % len(REPS_PRESETS)]
        if reps == ex.reps:
            await cb.answer()
            return
        await db.update_exercise(ex.id, reps=reps)
        ex.reps = reps
        await show_or_home(cb, db, screens.exercise_edit_screen(ex), toast=f"Повторений: {reps}")


@router.callback_query(kb.ExCb.filter(F.action == "up"))
async def exercise_up(cb: CallbackQuery, callback_data: kb.ExCb, db: Database) -> None:
    if ex := await _exercise_or_home(cb, db, callback_data.id):
        if not await db.move_exercise_up(ex):
            await cb.answer("Оно и так первое 👆")
            return
        position = [e.id for e in await db.get_exercises(ex.day_id)].index(ex.id) + 1
        await cb.answer(f"Теперь это упражнение №{position}")


@router.callback_query(kb.ExCb.filter(F.action == "delete"))
async def exercise_delete(cb: CallbackQuery, callback_data: kb.ExCb, db: Database) -> None:
    if ex := await _exercise_or_home(cb, db, callback_data.id):
        await db.delete_exercise(ex.id)
        await show_or_home(cb, db, await screens.day_editor_screen(
            db, cb.from_user.id, ex.day_id, note=f"🗑 Удалено: {escape(ex.name)}"))


@router.callback_query(kb.ExCb.filter(F.action == "replace"))
async def exercise_replace(cb: CallbackQuery, callback_data: kb.ExCb, state: FSMContext, db: Database) -> None:
    await state.clear()
    if ex := await _exercise_or_home(cb, db, callback_data.id):
        await show_or_home(cb, db, screens.replace_screen(ex))


@router.callback_query(kb.AltCb.filter())
async def exercise_replace_pick(cb: CallbackQuery, callback_data: kb.AltCb, db: Database) -> None:
    item = CATALOG.get(callback_data.key)
    if (ex := await _exercise_or_home(cb, db, callback_data.id)) and item:
        await db.update_exercise(ex.id, name=item.name, catalog_key=item.key)
        ex.name, ex.catalog_key = item.name, item.key
        await show_or_home(cb, db, screens.exercise_edit_screen(ex), toast="Заменено ✅")


@router.callback_query(kb.ExCb.filter(F.action == "custom"))
async def exercise_replace_custom(cb: CallbackQuery, callback_data: kb.ExCb, state: FSMContext, db: Database) -> None:
    if ex := await _exercise_or_home(cb, db, callback_data.id):
        await ask_text(cb, db, state, ReplaceCustom.waiting, Screen(
            f"✍️ Чем заменить <b>{escape(ex.name)}</b>?\n\n"
            f"Напиши название. Можно с подходами: <code>Жим в Смите 4x6-8</code> (иначе {ex.sets}×{escape(ex.reps)}).",
            kb.single_kb("❌ Отмена", kb.ExCb(action="edit", id=ex.id)),
        ), exercise_id=ex.id)


@router.message(ReplaceCustom.waiting, F.text)
async def exercise_replace_custom_entered(message: Message, state: FSMContext, db: Database) -> None:
    data = await state.get_data()
    ex = await db.get_exercise(message.from_user.id, data["exercise_id"])
    if ex is None:
        await reply_screen(message, state, db, None)
        return
    new = _to_new_exercise(message.text, ex.sets, ex.reps)
    if new is None:
        await message.answer("Не понял название — напиши ещё раз 🙏")
        return
    await db.update_exercise(ex.id, name=new.name, catalog_key=new.catalog_key, sets=new.sets, reps=new.reps)
    ex.name, ex.catalog_key, ex.sets, ex.reps = new.name, new.catalog_key, new.sets, new.reps
    await reply_screen(message, state, db, screens.exercise_edit_screen(ex))
