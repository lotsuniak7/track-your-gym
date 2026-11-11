"""Служебное: куда бот пересылает отзывы.

Автор бота (ADMIN_ID из .env) добавляет бота в свою группу или канал — и отзывы начинают приходить туда,
а не в личный чат с ботом. Убрал бота из чата — отзывы снова идут в личку.
"""

import logging
import os

from aiogram import Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import ChatMemberUpdated

from db import Database
from handlers.menu import FEEDBACK_CHAT

router = Router(name="admin")
log = logging.getLogger(__name__)


@router.my_chat_member()
async def bot_membership_changed(event: ChatMemberUpdated, db: Database) -> None:
    admin_id = os.getenv("ADMIN_ID")
    if event.chat.type == "private" or not admin_id or event.from_user.id != int(admin_id):
        return
    status = event.new_chat_member.status
    if status in ("member", "administrator"):
        await db.set_setting(FEEDBACK_CHAT, str(event.chat.id))
        text = "✅ Отзывы из бота теперь будут приходить сюда."
        try:
            await event.bot.send_message(event.chat.id, text)
        except TelegramAPIError:  # в канале без прав на публикацию написать нельзя
            await db.set_setting(FEEDBACK_CHAT, None)
            text = (f"⚠️ Не могу писать в «{event.chat.title}». Дай мне право публиковать сообщения "
                    "(в канале — сделай администратором) и добавь ещё раз.")
        try:
            await event.bot.send_message(int(admin_id), text if text.startswith("⚠️")
                                         else f"✅ Отзывы теперь приходят в «{event.chat.title}».")
        except TelegramAPIError as e:
            log.warning("Не удалось написать автору: %s", e)
    elif status in ("left", "kicked") and await db.get_setting(FEEDBACK_CHAT) == str(event.chat.id):
        await db.set_setting(FEEDBACK_CHAT, None)
        try:
            await event.bot.send_message(int(admin_id), "ℹ️ Меня убрали из чата отзывов — снова шлю их тебе в личку.")
        except TelegramAPIError as e:
            log.warning("Не удалось написать автору: %s", e)
