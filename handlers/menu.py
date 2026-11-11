"""Главное меню, выбор раздела, список программ: создание, переключение, переименование, удаление."""

import logging
import os
from html import escape

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import keyboards as kb
import screens
import ui
from data.templates import SECTIONS_READY, TEMPLATES
from db import Database
from handlers.common import ask_text, reply_screen, show_or_home
from screens import Screen
from states import DayName, Feedback, ProgramName
from utils import clean_title

router = Router(name="menu")
log = logging.getLogger(__name__)


# --- команды ---


@router.message(CommandStart())
@router.message(Command("program"))
async def cmd_start(message: Message, state: FSMContext, db: Database) -> None:
    await state.clear()
    user = await db.get_user(message.from_user.id)
    if user and user.gender in SECTIONS_READY:
        screen = await screens.home_screen(db, message.from_user.id)
    else:
        screen = screens.start_screen()
    await ui.send(message.bot, message.chat.id, db, screen)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext, db: Database) -> None:
    await reply_screen(message, state, db, await screens.home_screen(db, message.from_user.id))


@router.message(Command("stats"))
async def cmd_stats(message: Message, state: FSMContext, db: Database) -> None:
    await reply_screen(message, state, db, await screens.stats_screen(db, message.from_user.id))


# --- обратная связь ---

FEEDBACK_CHAT = "feedback_chat"  # ключ настройки: id чата, куда бот пересылает отзывы

FEEDBACK_PROMPT = Screen(
    "💬 <b>Обратная связь</b>\n\n"
    "Напиши сообщением, чего не хватает: упражнения, функции или что работает не так.\n"
    "Я передам это автору бота.",
    kb.single_kb("❌ Отмена", kb.NavCb(to="home")),
)


@router.message(Command("feedback"))
async def cmd_feedback(message: Message, state: FSMContext, db: Database) -> None:
    await reply_screen(message, state, db, FEEDBACK_PROMPT, next_state=Feedback.waiting)


@router.callback_query(kb.NavCb.filter(F.to == "feedback"))
async def nav_feedback(cb: CallbackQuery, state: FSMContext, db: Database) -> None:
    await ask_text(cb, db, state, Feedback.waiting, FEEDBACK_PROMPT)


@router.message(Feedback.waiting, F.text)
async def feedback_entered(message: Message, state: FSMContext, db: Database) -> None:
    user = message.from_user
    text = message.text.strip()[:2000]
    feedback_id = await db.add_feedback(user.id, user.username, text)
    # Куда слать: в группу/канал для отзывов (см. handlers/admin.py), иначе — автору в личку
    admin_id = await db.get_setting(FEEDBACK_CHAT) or os.getenv("ADMIN_ID")
    if admin_id:
        who = escape(user.full_name) + (f" (@{user.username})" if user.username else "") + f" · id {user.id}"
        try:
            await message.bot.send_message(int(admin_id), f"💬 <b>Отзыв №{feedback_id}</b>\n{who}\n\n{escape(text)}")
        except Exception as e:  # noqa: BLE001 — отзыв уже в базе, не теряем его из-за ошибки доставки
            log.warning("Не удалось переслать отзыв №%s автору: %s", feedback_id, e)
    await message.answer("Спасибо! Передал автору 🙌")
    await reply_screen(message, state, db, await screens.home_screen(db, user.id))


# --- навигация ---


@router.callback_query(kb.NavCb.filter(F.to == "close"))
async def nav_close(cb: CallbackQuery) -> None:
    if isinstance(cb.message, Message):
        await ui.delete_or_disable(cb.bot, cb.message.chat.id, cb.message.message_id)
    await cb.answer()


@router.callback_query(kb.NavCb.filter(F.to == "start"))
async def nav_start(cb: CallbackQuery, state: FSMContext, db: Database) -> None:
    await state.clear()
    await show_or_home(cb, db, screens.start_screen())


@router.callback_query(kb.GenderCb.filter())
async def choose_gender(cb: CallbackQuery, callback_data: kb.GenderCb, state: FSMContext, db: Database) -> None:
    await state.clear()
    await db.set_gender(cb.from_user.id, callback_data.gender)
    if callback_data.gender not in SECTIONS_READY:
        await show_or_home(cb, db, screens.start_screen(note="🚧 Раздел в разработке, скоро добавим 💪"))
    else:
        await show_or_home(cb, db, await screens.home_screen(db, cb.from_user.id))


@router.callback_query(kb.NavCb.filter(F.to == "home"))
async def nav_home(cb: CallbackQuery, state: FSMContext, db: Database) -> None:
    await state.clear()
    await show_or_home(cb, db, await screens.home_screen(db, cb.from_user.id))


@router.callback_query(kb.NavCb.filter(F.to == "programs"))
async def nav_programs(cb: CallbackQuery, state: FSMContext, db: Database) -> None:
    await state.clear()
    await show_or_home(cb, db, await screens.programs_screen(db, cb.from_user.id))


@router.callback_query(kb.NavCb.filter(F.to == "new_program"))
async def nav_new_program(cb: CallbackQuery, state: FSMContext, db: Database) -> None:
    await state.clear()
    user = await db.get_user(cb.from_user.id)
    await show_or_home(cb, db, screens.new_program_screen(user.gender if user else None))


# --- создание программы ---


def _program_name_prompt(first_line: str, cancel, skip: bool) -> Screen:
    return Screen(
        f"{first_line}\n\nНапиши название, например: <i>Масса</i>, <i>Сушка</i>, <i>Своя PPL</i>.",
        kb.name_prompt_kb(cancel, skip=skip),
    )


@router.callback_query(kb.NavCb.filter(F.to == "scratch"))
async def create_scratch(cb: CallbackQuery, state: FSMContext, db: Database) -> None:
    await ask_text(cb, db, state, ProgramName.waiting,
                   _program_name_prompt("🛠 <b>Как назовём программу?</b>", kb.NavCb(to="new_program"), skip=True),
                   program_id=None)


def _first_day_prompt(program_id: int, program_name: str) -> Screen:
    return Screen(
        f"✅ Программа «{escape(program_name)}» создана и выбрана.\n\n"
        "📅 <b>Добавим первый тренировочный день.</b>\nВыбери название или напиши своё:",
        kb.day_name_kb(program_id),
    )


async def _create_program(user_id: int, name: str, db: Database) -> tuple[int, str]:
    if not name:
        name = f"Программа {len(await db.list_programs(user_id)) + 1}"
    return await db.create_program(user_id, name), name


@router.callback_query(kb.NavCb.filter(F.to == "skip_name"), ProgramName.waiting)
async def create_skip_name(cb: CallbackQuery, state: FSMContext, db: Database) -> None:
    program_id, name = await _create_program(cb.from_user.id, "", db)
    await ask_text(cb, db, state, DayName.waiting, _first_day_prompt(program_id, name), program_id=program_id)


@router.message(ProgramName.waiting, F.text)
async def program_name_entered(message: Message, state: FSMContext, db: Database) -> None:
    name = clean_title(message.text)
    data = await state.get_data()
    user_id = message.from_user.id

    if data.get("program_id") is None:
        program_id, name = await _create_program(user_id, name, db)
        await reply_screen(message, state, db, _first_day_prompt(program_id, name),
                           next_state=DayName.waiting, program_id=program_id)
        return

    program = await db.get_program(user_id, data["program_id"])
    if program and name:
        await db.rename_program(program.id, name)
    screen = await screens.program_editor_screen(db, user_id, data["program_id"], note="✏️ Название сохранено")
    await reply_screen(message, state, db, screen)


@router.callback_query(kb.TplCb.filter())
async def create_from_template(cb: CallbackQuery, callback_data: kb.TplCb, state: FSMContext, db: Database) -> None:
    await state.clear()
    template = TEMPLATES.get(callback_data.key)
    if template is None:
        await cb.answer("Шаблон не найден", show_alert=True)
        return
    program_id = await db.create_from_template(cb.from_user.id, template)
    await show_or_home(cb, db, await screens.program_editor_screen(
        db, cb.from_user.id, program_id,
        note="📦 Программа создана и выбрана. Меняй под себя: нажми на день.",
    ))


# --- действия с программой ---


@router.callback_query(kb.ProgCb.filter(F.action == "switch"))
async def program_switch(cb: CallbackQuery, callback_data: kb.ProgCb, state: FSMContext, db: Database) -> None:
    await state.clear()
    program = await db.get_program(cb.from_user.id, callback_data.id)
    if program is None:
        await show_or_home(cb, db, None)
        return
    await db.set_active_program(cb.from_user.id, program.id)
    await show_or_home(cb, db, await screens.home_screen(db, cb.from_user.id), toast=f"Занимаешься по «{program.name}» ✅")


@router.callback_query(kb.ProgCb.filter(F.action == "edit"))
async def program_edit(cb: CallbackQuery, callback_data: kb.ProgCb, state: FSMContext, db: Database) -> None:
    await state.clear()
    await show_or_home(cb, db, await screens.program_editor_screen(db, cb.from_user.id, callback_data.id))


@router.callback_query(kb.ProgCb.filter(F.action == "rename"))
async def program_rename(cb: CallbackQuery, callback_data: kb.ProgCb, state: FSMContext, db: Database) -> None:
    program = await db.get_program(cb.from_user.id, callback_data.id)
    if program is None:
        await show_or_home(cb, db, None)
        return
    await ask_text(cb, db, state, ProgramName.waiting,
                   _program_name_prompt(f"✏️ Новое название для «{escape(program.name)}»?",
                                        kb.ProgCb(action="edit", id=program.id), skip=False),
                   program_id=program.id)


@router.callback_query(kb.ProgCb.filter(F.action == "delete"))
async def program_delete(cb: CallbackQuery, callback_data: kb.ProgCb, db: Database) -> None:
    program = await db.get_program(cb.from_user.id, callback_data.id)
    if program is None:
        await show_or_home(cb, db, None)
        return
    await show_or_home(cb, db, Screen(
        f"🗑 Удалить программу «{escape(program.name)}»?\n\nВсе её дни и упражнения удалятся без возврата.",
        kb.confirm_kb(kb.ProgCb(action="delete_ok", id=program.id), kb.ProgCb(action="edit", id=program.id)),
    ))


@router.callback_query(kb.ProgCb.filter(F.action == "delete_ok"))
async def program_delete_ok(cb: CallbackQuery, callback_data: kb.ProgCb, db: Database) -> None:
    await db.delete_program(cb.from_user.id, callback_data.id)
    await show_or_home(cb, db, await screens.programs_screen(db, cb.from_user.id), toast="Программа удалена")


@router.callback_query(kb.ProgCb.filter(F.action == "add_day"))
async def program_add_day(cb: CallbackQuery, callback_data: kb.ProgCb, state: FSMContext, db: Database) -> None:
    program = await db.get_program(cb.from_user.id, callback_data.id)
    if program is None:
        await show_or_home(cb, db, None)
        return
    await ask_text(cb, db, state, DayName.waiting, Screen(
        f"📅 <b>Новый день в «{escape(program.name)}»</b>\n\nВыбери название или напиши своё:",
        kb.day_name_kb(program.id),
    ), program_id=program.id)
