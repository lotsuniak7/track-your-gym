"""Всё, что не поймали остальные роутеры. Подключается последним."""

from aiogram import Router
from aiogram.types import CallbackQuery, Message

router = Router(name="fallback")


@router.message()
async def unknown_message(message: Message) -> None:
    await message.answer("Не понял 🤔 Нажми /start, чтобы открыть меню, или /program — сразу к программе.")


@router.callback_query()
async def stale_button(cb: CallbackQuery) -> None:
    await cb.answer("Эта кнопка устарела. Нажми /start 🙏", show_alert=True)
