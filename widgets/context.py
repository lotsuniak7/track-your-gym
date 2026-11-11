"""Контекст нажатия внутри универсального виджета.

Такое нажатие мы превращаем в обычный callback и отдаём существующим хендлерам. Пока хендлер работает,
здесь копится результат: новый экран (если его можно показать прямо в этом же сообщении) и всплывающая
подсказка из cb.answer(). В конце всё уходит виджету одним ответом.
"""

from contextvars import ContextVar
from dataclasses import dataclass

from aiogram import Bot

CALLBACK_PREFIX = "wq:"  # id синтетического callback-а: «wq:<id widget_query>»


@dataclass
class WidgetContext:
    bot: Bot
    chat_id: int
    message_id: int | None
    view: dict | None = None   # экран, который виджет нарисует на месте текущего
    patch: dict | None = None  # или только изменившиеся кнопки/текст текущего экрана
    toast: str | None = None
    alert: bool = False
    replaced: bool = False     # экран ушёл новым сообщением, это — удалено


current: ContextVar[WidgetContext | None] = ContextVar("widget_context", default=None)
