"""Отрисовка экранов HTML-виджетами. Если Telegram виджет не принял — тот же экран обычным сообщением с кнопками."""

import json
import logging
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import CallbackQuery, FSInputFile, Message

from data.exercises import IMAGE_URL
from db import Database
from screens import Screen, Widget
from widgets import context, render
from widgets.api import SendWidget

log = logging.getLogger(__name__)

IMAGES_DIR = Path(__file__).resolve().parent / "images"


async def photo_source(db: Database, image: str) -> str | FSInputFile:
    if file_id := await db.get_photo_file_id(image):
        return file_id
    local = IMAGES_DIR / f"{image}.jpg"
    if local.exists():
        return FSInputFile(local)
    return IMAGE_URL.format(image=image)


async def remember_photo(db: Database, image: str, sent: Message) -> None:
    if sent.photo:
        await db.save_photo_file_id(image, sent.photo[-1].file_id)


async def delete_or_disable(bot: Bot, chat_id: int, message_id: int | None) -> None:
    if not message_id:
        return
    try:
        await bot.delete_message(chat_id, message_id)
    except TelegramBadRequest:
        # сообщения старше 48 часов удалить нельзя — хотя бы уберём кнопки
        try:
            await bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=None)
        except TelegramBadRequest:
            pass


MAX_INPLACE = 760  # ответ виджету и chat_data — до 1024 байт; оставляем запас под подсказку


# Экран, вшитый в HTML универсального виджета: (chat_id, message_id) → view. Нужен, чтобы слать виджету
# только изменившиеся кнопки. После перезапуска бота пуст — тогда экран просто придёт новым сообщением.
_bases: dict[tuple[int, int], dict] = {}
MAX_BASES = 2000


def _size(data: dict) -> int:
    return len(json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode())


def to_view(screen: Screen) -> dict:
    rows = [[(b.text, b.callback_data) for b in row if b.callback_data] for row in screen.kb.inline_keyboard]
    return render.screen_view(screen.widget_text or screen.text, rows, screen.image)


def _widget_for(screen: Screen) -> Widget | None:
    """Особый виджет экрана (главная, тренировка) или универсальный — для всех остальных."""
    if screen.widget:
        return screen.widget
    view = to_view(screen)
    html = render.menu_html(view)
    if html is None:
        return None

    async def remember(message: Message) -> None:
        if len(_bases) >= MAX_BASES:
            _bases.pop(next(iter(_bases)))
        _bases[(message.chat.id, message.message_id)] = view

    return Widget(html, None, on_sent=remember)


async def send(bot: Bot, chat_id: int, db: Database, screen: Screen) -> Message:
    """Отправить экран новым сообщением: виджетом, а если не вышло — обычным сообщением с кнопками."""
    widget = _widget_for(screen)
    if widget:
        try:
            sent = await bot(SendWidget(chat_id=chat_id, html=widget.html, caption=widget.caption,
                                        chat_data=widget.chat_data, allow_queries=True))
            if widget.on_sent:
                await widget.on_sent(sent)
            return sent
        except TelegramAPIError as e:
            log.warning("Виджет не отправился, показываю обычный экран: %s", e)
    if screen.image:
        try:
            sent = await bot.send_photo(chat_id, await photo_source(db, screen.image),
                                        caption=screen.text, reply_markup=screen.kb)
            await remember_photo(db, screen.image, sent)
            return sent
        except TelegramBadRequest as e:
            log.warning("Не удалось отправить картинку %s: %s", screen.image, e)
    return await bot.send_message(chat_id, screen.text, reply_markup=screen.kb)


async def show(cb: CallbackQuery, db: Database, screen: Screen) -> int | None:
    """Показать экран вместо того, на кнопку которого нажали. Возвращает id сообщения с экраном."""
    ctx = context.current.get()
    if ctx is not None:  # нажали внутри универсального виджета
        if not screen.widget:
            view, key = to_view(screen), (ctx.chat_id, ctx.message_id)
            if _size(view) <= MAX_INPLACE:
                ctx.view, ctx.patch = view, None  # маленький экран виджет перерисует сам, без нового сообщения
                _bases.pop(key, None)
                return ctx.message_id
            base = _bases.get(key)
            patch = render.view_patch(base, view) if base else None
            if patch is not None and _size(patch) <= MAX_INPLACE:
                ctx.patch, ctx.view = patch, None  # большой экран, но поменялась пара кнопок — шлём только их
                return ctx.message_id
        _bases.pop((ctx.chat_id, ctx.message_id), None)
        sent = await send(ctx.bot, ctx.chat_id, db, screen)
        await delete_or_disable(ctx.bot, ctx.chat_id, ctx.message_id)
        ctx.replaced, ctx.view, ctx.patch = True, None, None
        return sent.message_id

    # Нажали обычную кнопку (запасной экран или старое сообщение) — новый экран шлём виджетом, старый убираем
    msg = cb.message
    sent = await send(cb.bot, cb.from_user.id, db, screen)
    if isinstance(msg, Message):
        await delete_or_disable(msg.bot, msg.chat.id, msg.message_id)
    return sent.message_id
