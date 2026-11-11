"""Методы Bot API 10.4 для HTML-виджетов. В aiogram их пока нет, поэтому описываем сами.

Когда aiogram их добавит, этот файл можно заменить на встроенные bot.send_widget(...) и т.д.
"""

from aiogram.methods import TelegramMethod
from aiogram.types import InlineKeyboardMarkup, Message


class SendWidget(TelegramMethod[Message]):
    __returning__ = Message
    __api_method__ = "sendWidget"

    chat_id: int
    html: str
    caption: str | None = None
    chat_data: str | None = None
    allow_queries: bool | None = None
    disable_notification: bool | None = None
    reply_markup: InlineKeyboardMarkup | None = None


class AnswerWidgetQuery(TelegramMethod[bool]):
    __returning__ = bool
    __api_method__ = "answerWidgetQuery"

    widget_query_id: str
    data: str | None = None


class EditMessageWidgetData(TelegramMethod[bool]):
    __returning__ = bool
    __api_method__ = "editMessageWidgetData"

    chat_id: int
    message_id: int
    chat_data: str | None = None
