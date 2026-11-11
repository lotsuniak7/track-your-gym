"""Нажатия внутри HTML-виджетов (обновление widget_query из Bot API 10.4).

aiogram пока не знает этот тип обновления, поэтому ловим его мидлварью до роутеров.
Виджет шлёт короткую строку-действие, бот отвечает JSON-ом:
  {"s": состояние} — виджет перерисуется, {"e": "текст"} — покажет ошибку, {"t": "текст"} — техника.

Универсальный экран (все меню и редакторы) шлёт «~<callback_data>»: такое нажатие превращаем в обычный
callback и отдаём тем же хендлерам, что и кнопки. Ответ: {"v": новый экран} или {"u": правки текущего}
и/или {"t": подсказка}.

Действия главного экрана — заглавные буквы, тренировки — строчные:
  S:<день> начать · C продолжить · D:<день> изменить день · E редактор программы · P мои программы · R прогресс
  g:<упр> перейти · d:<упр>:<вес×10> выполнено · u:<упр> снять отметку · k пропустить · w:<упр> заменить
  a заменить всё · r вернуть как в программе · t:<упр> техника · p:<упр> фото · f закончить · h на главную
"""

import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware, Bot, Dispatcher
from aiogram.client.session.middlewares.base import BaseRequestMiddleware, NextRequestMiddlewareType
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.methods import AnswerCallbackQuery, TelegramMethod
from aiogram.types import TelegramObject, Update

import keyboards as kb
import screens
import ui
from data.exercises import CATALOG
from db import Database, Session, now_iso
from screens import Screen
from widgets import context
from widgets.api import AnswerWidgetQuery, EditMessageWidgetData
from workout_logic import next_undone, swap_all, swap_one
from workout_service import Workout, finish_workout, load_workout

log = logging.getLogger(__name__)

MAX_TIP = 450  # ответ виджету — до 1024 байт, кириллица занимает по 2 байта на букву
STALE = "Это старое сообщение. Нажми /start, чтобы открыть актуальное 👇"


class WidgetQueryMiddleware(BaseMiddleware):
    def __init__(self, dispatcher: Dispatcher):
        self.dispatcher = dispatcher

    async def __call__(self, handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
                       event: TelegramObject, data: dict[str, Any]) -> Any:
        query = (event.model_extra or {}).get("widget_query") if isinstance(event, Update) else None
        if query is None:
            return await handler(event, data)
        wq = WidgetQuery(data["bot"], data["db"], query, data.get("fsm_storage"))
        try:
            if wq.raw.startswith("~ph:"):
                await wq.send_photo(wq.raw[4:])
            elif wq.raw.startswith("~"):
                await self.as_callback(wq, query, event.update_id)
            else:
                await wq.handle()
        except Exception:  # noqa: BLE001 — виджет должен получить ответ, иначе увидит таймаут
            log.exception("Ошибка при обработке widget_query")
            await wq.answer(e="Что-то пошло не так. Нажми /start")
        return None

    async def as_callback(self, wq: "WidgetQuery", query: dict, update_id: int) -> None:
        """Нажатие в универсальном виджете → обычный callback для роутеров."""
        ctx = context.WidgetContext(wq.bot, wq.chat_id, wq.message_id)
        update = Update.model_validate({"update_id": update_id, "callback_query": {
            "id": context.CALLBACK_PREFIX + wq.id,
            "from": query["from"],
            "chat_instance": query.get("chat_instance", "widget"),
            "data": wq.raw[1:],
            "message": {"message_id": wq.message_id or 0, "date": int(time.time()),
                        "chat": query.get("chat") or {"id": wq.chat_id, "type": "private"}, "text": "·"},
        }}, context={"bot": wq.bot})
        token = context.current.set(ctx)
        try:
            await self.dispatcher.feed_update(wq.bot, update)
        finally:
            context.current.reset(token)

        payload: dict = {}
        if ctx.view is not None:
            payload["v"] = ctx.view
        elif ctx.patch is not None:
            payload["u"] = ctx.patch
        if ctx.toast:
            payload["e" if ctx.alert else "t"] = ctx.toast[:110]
        await wq.answer(**payload)
        shown = ctx.view if ctx.view is not None else ctx.patch
        if shown is not None:  # сохраняем в сообщении — экран переживёт перезапуск приложения
            await wq.store(json.dumps(shown, ensure_ascii=False, separators=(",", ":")))


class WidgetAnswerMiddleware(BaseRequestMiddleware):
    """cb.answer() на синтетический callback не уходит в Telegram, а попадает в ответ виджету."""

    async def __call__(self, make_request: NextRequestMiddlewareType, bot: Bot, method: TelegramMethod):
        if isinstance(method, AnswerCallbackQuery) and method.callback_query_id.startswith(context.CALLBACK_PREFIX):
            ctx = context.current.get()
            if ctx is not None and method.text:
                ctx.toast, ctx.alert = method.text, bool(method.show_alert)
            return True
        return await make_request(bot, method)


class WidgetQuery:
    def __init__(self, bot: Bot, db: Database, query: dict, fsm_storage=None):
        self.bot, self.db = bot, db
        self.id: str = query["id"]
        self.user_id: int = query["from"]["id"]
        self.chat_id: int = (query.get("chat") or {}).get("id", self.user_id)
        self.message_id: int | None = query.get("message_id")
        self.raw = str(query.get("data", ""))
        self.action, *args = self.raw.split(":")
        numbers = [int(a) if a.isdigit() else None for a in args]
        self.arg = numbers[0] if numbers else None
        self.arg2 = numbers[1] if len(numbers) > 1 else None  # вес ×10 для «выполнено»
        self.answered = False
        # aiogram не знает про widget_query, поэтому контекст FSM собираем сами
        self.state = FSMContext(fsm_storage, StorageKey(bot.id, self.chat_id, self.user_id)) if fsm_storage else None

    # --- ответы ---

    async def answer(self, **payload) -> None:
        if self.answered:
            return
        self.answered = True
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) if payload else None
        try:
            await self.bot(AnswerWidgetQuery(widget_query_id=self.id, data=data))
        except TelegramAPIError as e:
            log.warning("Не удалось ответить виджету: %s", e)

    async def set_state(self, state_json: str) -> None:
        """Ответить новым состоянием и сохранить его в сообщении — оно переживёт перезапуск приложения."""
        await self.answer(s=json.loads(state_json))
        await self.store(state_json)

    async def store(self, chat_data: str) -> None:
        if not self.message_id:
            return
        try:
            await self.bot(EditMessageWidgetData(chat_id=self.chat_id, message_id=self.message_id,
                                                 chat_data=chat_data))
        except TelegramAPIError as e:
            if "not modified" not in str(e):
                log.warning("Не удалось обновить состояние виджета: %s", e)

    async def send_photo(self, image: str) -> None:
        """Фото упражнения отдельным сообщением (в виджет картинки не помещаются)."""
        await self.answer()
        item = next((ex for ex in CATALOG.values() if ex.image == image), None)
        if item is None:
            return
        try:
            sent = await self.bot.send_photo(
                self.chat_id, await ui.photo_source(self.db, item.image),
                caption=f"<b>{item.name}</b>",
                reply_markup=kb.single_kb("✖️ Закрыть", kb.NavCb(to="close")),
            )
            await ui.remember_photo(self.db, item.image, sent)
        except TelegramAPIError as e:
            log.warning("Не удалось отправить фото %s: %s", image, e)

    async def replace_with(self, screen: Screen) -> None:
        """Открыть другой экран: новым сообщением, а это — убрать."""
        await self.answer()
        if self.state:
            await self.state.clear()
        await ui.send(self.bot, self.chat_id, self.db, screen)
        await ui.delete_or_disable(self.bot, self.chat_id, self.message_id)

    # --- разбор действия ---

    async def handle(self) -> None:
        handler = {
            "S": self.start, "C": self.resume, "D": self.edit_day, "E": self.edit_program, "P": self.programs,
            "R": self.stats,
            "h": self.home, "g": self.go, "d": self.done, "u": self.undo, "k": self.skip, "w": self.swap,
            "a": self.swap_everything, "r": self.unswap, "t": self.tip, "p": self.photo, "f": self.finish,
        }.get(self.action)
        if handler is None:
            await self.answer(e=STALE)
            return
        await handler()
        await self.answer()  # на случай, если действие само не ответило

    # --- главный экран ---

    async def home(self) -> None:
        await self.replace_with(await screens.home_screen(self.db, self.user_id))

    async def programs(self) -> None:
        await self.replace_with(await screens.programs_screen(self.db, self.user_id))

    async def stats(self) -> None:
        await self.replace_with(await screens.stats_screen(self.db, self.user_id))

    async def edit_program(self) -> None:
        user = await self.db.get_user(self.user_id)
        screen = await screens.program_editor_screen(self.db, self.user_id, user.active_program_id) \
            if user and user.active_program_id else None
        await self.replace_with(screen or await screens.programs_screen(self.db, self.user_id))

    async def edit_day(self) -> None:
        screen = await screens.day_editor_screen(self.db, self.user_id, self.arg) if self.arg else None
        if screen is None:
            await self.answer(e=STALE)
            return
        await self.replace_with(screen)

    async def start(self) -> None:
        day = await self.db.get_day(self.user_id, self.arg)
        exercises = await self.db.get_exercises(day.id) if day else []
        if day is None:
            await self.answer(e=STALE)
        elif not exercises:
            await self.answer(e="Сначала добавь упражнения в этот день")
        else:
            session = Session(self.user_id, day.id, exercises[0].id, set(), now_iso())
            await self.db.save_session(session)
            await self.open_workout(Workout(session, day, exercises, exercises, exercises[0]))

    async def resume(self) -> None:
        w = await load_workout(self.db, self.user_id)
        if w is None:
            await self.answer(e="Незаконченной тренировки нет — начни новую")
            return
        await self.open_workout(w)

    async def open_workout(self, w: Workout) -> None:
        w.session.current_id = w.current.id
        await self.db.save_session(w.session)
        original = w.original(w.current.id).name if w.current.id in w.session.swaps else None
        screen = screens.step_screen(w.day, w.exercises, w.session, w.current, original)
        screen.widget = await screens.workout_widget(self.db, w)
        await self.replace_with(screen)

    # --- тренировка ---

    async def workout(self, need_exercise: bool = False) -> Workout | None:
        """Тренировка, к которой относится этот виджет. Отвечает ошибкой, если виджет устарел."""
        w = await load_workout(self.db, self.user_id)
        if w is None or (w.session.message_id and self.message_id and w.session.message_id != self.message_id):
            await self.answer(e=STALE)
            return None
        if need_exercise:
            target = next((e for e in w.exercises if e.id == self.arg), None)
            if target is None:
                await self.answer(e=STALE)
                return None
            w.current = target
        return w

    async def save(self, w: Workout) -> None:
        w.session.current_id = w.current.id
        await self.db.save_session(w.session)
        await self.set_state(screens.workout_state(w.session))

    async def go(self) -> None:
        if w := await self.workout(need_exercise=True):
            await self.save(w)

    async def done(self) -> None:
        if w := await self.workout(need_exercise=True):
            if w.current.id not in w.session.done:  # в журнал прогресса — один раз за тренировку
                weight = self.arg2 / 10 if self.arg2 else None
                await self.db.log_exercise(self.user_id, w.current, weight if weight and weight <= 1000 else None)
            w.session.done.add(w.current.id)
            nxt = next_undone(w.exercises, w.session.done, w.current.id)
            if nxt is None:
                await self.finish_now(w)
            else:
                w.current = nxt
                await self.save(w)

    async def undo(self) -> None:
        if w := await self.workout(need_exercise=True):
            if w.current.id in w.session.done:
                await self.db.unlog_exercise(self.user_id, w.current, w.session.started_at)
            w.session.done.discard(w.current.id)
            await self.save(w)

    async def skip(self) -> None:
        if w := await self.workout():
            nxt = next_undone(w.exercises, w.session.done, w.current.id)
            if nxt is not None:
                w.current = nxt
                await self.save(w)
            elif w.current.id in w.session.done:
                await self.finish_now(w)
            else:
                await self.answer(e="Это последнее упражнение — сделай его или нажми «Закончить» 💪")

    async def finish(self) -> None:
        if w := await self.workout():
            await self.finish_now(w)

    async def finish_now(self, w: Workout) -> None:
        result = await finish_workout(self.db, self.user_id, w)
        await self.set_state(screens.finish_state(result))

    async def swap(self) -> None:
        if w := await self.workout(need_exercise=True):
            if w.current.id in w.session.done:
                await self.answer(e="Это упражнение уже выполнено ✅")
            elif swap_one(w.original(w.current.id), w.exercises, w.session.swaps) is None:
                await self.answer(e="Для этого упражнения нет замен в базе — можно пропустить")
            else:
                w.refresh()
                await self.open_workout(w)

    async def swap_everything(self) -> None:
        if w := await self.workout():
            if not swap_all(w.originals, w.session.swaps, w.session.done):
                await self.answer(e="Нечего менять: всё выполнено или нет замен в базе")
                return
            w.refresh()
            w.current = next((e for e in w.exercises if e.id not in w.session.done), w.current)
            await self.open_workout(w)

    async def unswap(self) -> None:
        if w := await self.workout():
            w.session.swaps.clear()
            w.refresh()
            await self.open_workout(w)

    async def tip(self) -> None:
        if w := await self.workout(need_exercise=True):
            item = CATALOG.get(w.current.catalog_key or "")
            if item is None or not item.tip:
                await self.answer(e="Для этого упражнения нет описания техники")
            else:
                await self.answer(t=item.tip[:MAX_TIP])

    async def photo(self) -> None:
        if w := await self.workout(need_exercise=True):
            item = CATALOG.get(w.current.catalog_key or "")
            if item is None or not item.image:
                await self.answer(e="Для этого упражнения нет фото")
                return
            await self.send_photo(item.image)
