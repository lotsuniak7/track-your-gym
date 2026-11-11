"""Текущая тренировка пользователя: загрузка и завершение. Общая часть для кнопок и виджетов."""

from dataclasses import dataclass
from datetime import datetime, timezone

from db import Database, Day, DayExercise, Session
from workout_logic import apply_swaps, next_undone


@dataclass
class Workout:
    session: Session
    day: Day
    originals: list[DayExercise]  # как в программе
    exercises: list[DayExercise]  # с заменами на сегодня
    current: DayExercise

    def refresh(self) -> None:
        """Пересчитать упражнения после изменения замен."""
        self.exercises = apply_swaps(self.originals, self.session.swaps)
        self.current = next(e for e in self.exercises if e.id == self.current.id)

    def original(self, exercise_id: int) -> DayExercise:
        return next(e for e in self.originals if e.id == exercise_id)


@dataclass
class FinishResult:
    day: Day
    done: int
    total: int
    started_at: str
    number: int | None  # какая это тренировка по счёту; None — ничего не выполнено
    gender: str | None

    @property
    def minutes(self) -> int | None:
        try:
            value = int((datetime.now(timezone.utc) - datetime.fromisoformat(self.started_at)).total_seconds() // 60)
        except ValueError:
            return None
        return value if 0 < value < 600 else None


async def load_workout(db: Database, user_id: int) -> Workout | None:
    session = await db.get_session(user_id)
    day = await db.get_day(user_id, session.day_id) if session else None
    originals = await db.get_exercises(day.id) if day else []
    if session is None or day is None or not originals:
        if session:
            await db.delete_session(user_id)
        return None

    ids = {e.id for e in originals}
    session.done &= ids  # упражнения могли удалить в редакторе
    session.swaps = {k: v for k, v in session.swaps.items() if k in ids}
    exercises = apply_swaps(originals, session.swaps)
    current = next((e for e in exercises if e.id == session.current_id), None)
    if current is None:
        current = next_undone(exercises, session.done, None) or exercises[0]
        session.current_id = current.id
    return Workout(session, day, originals, exercises, current)


async def finish_workout(db: Database, user_id: int, w: Workout) -> FinishResult:
    done, total = len(w.session.done), len(w.exercises)
    number = await db.log_workout(user_id, w.day, done, total, w.session.started_at) if done else None
    await db.delete_session(user_id)
    user = await db.get_user(user_id)
    return FinishResult(w.day, done, total, w.session.started_at, number, user.gender if user else None)
