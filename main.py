import asyncio
import logging
import os
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand
from dotenv import load_dotenv

from db import Database
from handlers import build_router
from handlers.widget import WidgetAnswerMiddleware, WidgetQueryMiddleware


async def main() -> None:
    load_dotenv()
    token = os.getenv("BOT_TOKEN")
    if not token:
        sys.exit("BOT_TOKEN не задан. Скопируй .env.example в .env и впиши токен.")

    db = Database(os.getenv("DB_PATH", "gym.db"))
    await db.connect()

    bot = Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp["db"] = db  # попадает в хендлеры аргументом `db`
    dp.include_router(build_router())
    dp.update.outer_middleware(WidgetQueryMiddleware(dp))  # нажатия внутри HTML-виджетов
    bot.session.middleware(WidgetAnswerMiddleware())

    await bot.set_my_commands([
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="program", description="Моя программа"),
        BotCommand(command="feedback", description="Обратная связь"),
        BotCommand(command="cancel", description="Отменить ввод"),
        BotCommand(command="stats", description="Мой прогресс"),
    ])

    try:
        # widget_query aiogram сам не запросит — добавляем к типам обновлений, которые слушают роутеры
        await dp.start_polling(bot, allowed_updates=[*dp.resolve_used_update_types(), "widget_query"])
    finally:
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(main())
