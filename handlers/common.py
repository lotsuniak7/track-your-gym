from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import screens
import ui
from db import Database
from screens import Screen


async def show_or_home(cb: CallbackQuery, db: Database, screen: Screen | None, toast: str | None = None) -> None:
    """Показать экран; если объект уже удалён — вернуть на главную."""
    if screen is None:
        await ui.show(cb, db, await screens.home_screen(db, cb.from_user.id))
        await cb.answer("Это уже удалено или изменено 🙏", show_alert=True)
        return
    await ui.show(cb, db, screen)
    await cb.answer(toast)


async def ask_text(cb: CallbackQuery, db: Database, state: FSMContext, new_state, screen: Screen, **data) -> None:
    """Перейти в режим ввода текста: показать подсказку и запомнить её id, чтобы потом убрать."""
    await state.clear()
    await state.set_state(new_state)
    prompt_id = await ui.show(cb, db, screen)
    await state.update_data(prompt_id=prompt_id, **data)
    await cb.answer()


async def reply_screen(message: Message, state: FSMContext, db: Database, screen: Screen | None,
                       next_state=None, **data) -> None:
    """После ввода текста: убрать старую подсказку и прислать новый экран.
    Если передан next_state — новый экран сам становится подсказкой для следующего ввода."""
    old = await state.get_data()
    await ui.delete_or_disable(message.bot, message.chat.id, old.get("prompt_id"))
    await state.clear()
    if screen is None:
        screen = await screens.home_screen(db, message.from_user.id)
    sent = await ui.send(message.bot, message.chat.id, db, screen)
    if next_state is not None:
        await state.set_state(next_state)
        await state.update_data(prompt_id=sent.message_id, **data)
