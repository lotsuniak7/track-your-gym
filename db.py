"""Хранилище на SQLite.

users             — пол и активная программа
programs          — программы пользователя (их может быть несколько)
program_days      — тренировочные дни программы
day_exercises     — упражнения дня по порядку
workout_sessions  — текущая (незаконченная) тренировка: какое упражнение сейчас и что выполнено
workout_log       — завершённые тренировки
photo_cache       — file_id картинок, уже загруженных в Telegram
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

import aiosqlite

from data.exercises import CATALOG
from data.templates import TEMPLATES, Template

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id            INTEGER PRIMARY KEY,
    gender             TEXT,
    active_program_id  INTEGER,
    classic_ui         INTEGER NOT NULL DEFAULT 0,
    updated_at         TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS programs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    name        TEXT    NOT NULL,
    created_at  TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_programs_user ON programs(user_id);

CREATE TABLE IF NOT EXISTS program_days (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id  INTEGER NOT NULL REFERENCES programs(id) ON DELETE CASCADE,
    position    INTEGER NOT NULL,
    title       TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_program_days_program ON program_days(program_id, position);

CREATE TABLE IF NOT EXISTS day_exercises (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    day_id       INTEGER NOT NULL REFERENCES program_days(id) ON DELETE CASCADE,
    position     INTEGER NOT NULL,
    name         TEXT    NOT NULL,
    sets         INTEGER NOT NULL,
    reps         TEXT    NOT NULL,
    catalog_key  TEXT
);
CREATE INDEX IF NOT EXISTS idx_day_exercises_day ON day_exercises(day_id, position);

CREATE TABLE IF NOT EXISTS workout_sessions (
    user_id     INTEGER PRIMARY KEY,
    day_id      INTEGER NOT NULL REFERENCES program_days(id) ON DELETE CASCADE,
    current_id  INTEGER,
    done        TEXT NOT NULL DEFAULT '[]',
    swaps       TEXT NOT NULL DEFAULT '{}',
    message_id  INTEGER,
    started_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workout_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL,
    program_name  TEXT,
    day_title     TEXT,
    done_count    INTEGER NOT NULL,
    total_count   INTEGER NOT NULL,
    started_at    TEXT NOT NULL,
    finished_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);

-- Журнал выполненных упражнений: основа для отслеживания прогресса
CREATE TABLE IF NOT EXISTS exercise_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    key         TEXT    NOT NULL,   -- ключ из каталога или название своего упражнения в нижнем регистре
    name        TEXT    NOT NULL,
    weight      REAL,               -- кг; NULL — без веса или не указан
    sets        INTEGER NOT NULL,
    reps        TEXT    NOT NULL,
    created_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_exercise_log_user ON exercise_log(user_id, key, id);

CREATE TABLE IF NOT EXISTS feedback (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    username    TEXT,
    text        TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS photo_cache (
    image    TEXT PRIMARY KEY,
    file_id  TEXT NOT NULL
);
"""


@dataclass
class User:
    user_id: int
    gender: str | None
    active_program_id: int | None


@dataclass
class Program:
    id: int
    name: str
    day_count: int


@dataclass
class Day:
    id: int
    program_id: int
    program_name: str
    position: int
    title: str
    exercise_count: int


@dataclass
class DayExercise:
    id: int
    day_id: int
    position: int
    name: str
    sets: int
    reps: str
    catalog_key: str | None


@dataclass
class NewExercise:
    name: str
    sets: int
    reps: str
    catalog_key: str | None = None


@dataclass
class Session:
    user_id: int
    day_id: int
    current_id: int | None
    done: set[int] = field(default_factory=set)
    started_at: str = ""
    # Замены только на эту тренировку: id упражнения → ключ упражнения из каталога
    swaps: dict[int, str] = field(default_factory=dict)
    # Сообщение с виджетом этой тренировки — запросы от старых виджетов игнорируем
    message_id: int | None = None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: str):
        self.path = path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA foreign_keys = ON")
        await self._conn.executescript(SCHEMA)
        await self._upgrade_schema()
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()

    @property
    def conn(self) -> aiosqlite.Connection:
        assert self._conn is not None, "Database.connect() не вызван"
        return self._conn

    async def _one(self, sql: str, params=()) -> aiosqlite.Row | None:
        async with self.conn.execute(sql, params) as cur:
            return await cur.fetchone()

    async def _all(self, sql: str, params=()) -> list[aiosqlite.Row]:
        async with self.conn.execute(sql, params) as cur:
            return list(await cur.fetchall())

    # --- пользователи ---

    async def get_user(self, user_id: int) -> User | None:
        row = await self._one("SELECT * FROM users WHERE user_id = ?", (user_id,))
        if row is None:
            return None
        return User(row["user_id"], row["gender"], row["active_program_id"])

    async def set_gender(self, user_id: int, gender: str) -> None:
        await self.conn.execute(
            """INSERT INTO users (user_id, gender) VALUES (?, ?)
               ON CONFLICT(user_id) DO UPDATE SET gender = excluded.gender, updated_at = CURRENT_TIMESTAMP""",
            (user_id, gender),
        )
        await self.conn.commit()

    async def set_active_program(self, user_id: int, program_id: int | None) -> None:
        await self.conn.execute(
            """INSERT INTO users (user_id, active_program_id) VALUES (?, ?)
               ON CONFLICT(user_id) DO UPDATE SET active_program_id = excluded.active_program_id,
                                                  updated_at = CURRENT_TIMESTAMP""",
            (user_id, program_id),
        )
        await self.conn.commit()

    # --- программы ---

    _PROGRAM_SQL = """SELECT p.id, p.name,
                             (SELECT COUNT(*) FROM program_days d WHERE d.program_id = p.id) AS day_count
                      FROM programs p"""

    async def list_programs(self, user_id: int) -> list[Program]:
        rows = await self._all(f"{self._PROGRAM_SQL} WHERE p.user_id = ? ORDER BY p.id", (user_id,))
        return [Program(r["id"], r["name"], r["day_count"]) for r in rows]

    async def get_program(self, user_id: int, program_id: int | None) -> Program | None:
        if program_id is None:
            return None
        r = await self._one(f"{self._PROGRAM_SQL} WHERE p.id = ? AND p.user_id = ?", (program_id, user_id))
        return Program(r["id"], r["name"], r["day_count"]) if r else None

    async def create_program(self, user_id: int, name: str,
                             days: list[tuple[str, list[NewExercise]]] = ()) -> int:
        cur = await self.conn.execute("INSERT INTO programs (user_id, name) VALUES (?, ?)", (user_id, name))
        program_id = cur.lastrowid
        for position, (title, exercises) in enumerate(days):
            day_cur = await self.conn.execute(
                "INSERT INTO program_days (program_id, position, title) VALUES (?, ?, ?)",
                (program_id, position, title),
            )
            await self._insert_exercises(day_cur.lastrowid, exercises)
        await self.conn.commit()
        await self.set_active_program(user_id, program_id)
        return program_id

    async def create_from_template(self, user_id: int, template: Template) -> int:
        return await self.create_program(user_id, template.title, [
            (day.title, [NewExercise(CATALOG[e.key].name, e.sets, e.reps, e.key) for e in day.exercises])
            for day in template.days
        ])

    async def rename_program(self, program_id: int, name: str) -> None:
        await self.conn.execute("UPDATE programs SET name = ? WHERE id = ?", (name, program_id))
        await self.conn.commit()

    async def delete_program(self, user_id: int, program_id: int) -> None:
        await self.conn.execute("DELETE FROM programs WHERE id = ? AND user_id = ?", (program_id, user_id))
        user = await self.get_user(user_id)
        if user and user.active_program_id == program_id:
            fallback = await self._one("SELECT id FROM programs WHERE user_id = ? ORDER BY id DESC", (user_id,))
            await self.conn.execute(
                "UPDATE users SET active_program_id = ? WHERE user_id = ?",
                (fallback["id"] if fallback else None, user_id),
            )
        await self.conn.commit()

    # --- дни ---

    _DAY_SQL = """SELECT d.id, d.program_id, p.name AS program_name, d.position, d.title,
                         (SELECT COUNT(*) FROM day_exercises e WHERE e.day_id = d.id) AS exercise_count
                  FROM program_days d JOIN programs p ON p.id = d.program_id"""

    @staticmethod
    def _to_day(r: aiosqlite.Row) -> Day:
        return Day(r["id"], r["program_id"], r["program_name"], r["position"], r["title"], r["exercise_count"])

    async def get_days(self, program_id: int) -> list[Day]:
        rows = await self._all(f"{self._DAY_SQL} WHERE d.program_id = ? ORDER BY d.position, d.id", (program_id,))
        return [self._to_day(r) for r in rows]

    async def get_day(self, user_id: int, day_id: int | None) -> Day | None:
        if day_id is None:
            return None
        r = await self._one(f"{self._DAY_SQL} WHERE d.id = ? AND p.user_id = ?", (day_id, user_id))
        return self._to_day(r) if r else None

    async def add_day(self, program_id: int, title: str) -> int:
        position = await self._next_position("program_days", "program_id", program_id)
        cur = await self.conn.execute(
            "INSERT INTO program_days (program_id, position, title) VALUES (?, ?, ?)", (program_id, position, title)
        )
        await self.conn.commit()
        return cur.lastrowid

    async def rename_day(self, day_id: int, title: str) -> None:
        await self.conn.execute("UPDATE program_days SET title = ? WHERE id = ?", (title, day_id))
        await self.conn.commit()

    async def delete_day(self, day_id: int) -> None:
        await self.conn.execute("DELETE FROM program_days WHERE id = ?", (day_id,))
        await self.conn.commit()

    # --- упражнения ---

    @staticmethod
    def _to_exercise(r: aiosqlite.Row) -> DayExercise:
        return DayExercise(r["id"], r["day_id"], r["position"], r["name"], r["sets"], r["reps"], r["catalog_key"])

    async def get_exercises(self, day_id: int) -> list[DayExercise]:
        rows = await self._all("SELECT * FROM day_exercises WHERE day_id = ? ORDER BY position, id", (day_id,))
        return [self._to_exercise(r) for r in rows]

    async def get_exercise(self, user_id: int, exercise_id: int) -> DayExercise | None:
        r = await self._one(
            """SELECT e.* FROM day_exercises e
               JOIN program_days d ON d.id = e.day_id JOIN programs p ON p.id = d.program_id
               WHERE e.id = ? AND p.user_id = ?""",
            (exercise_id, user_id),
        )
        return self._to_exercise(r) if r else None

    async def add_exercises(self, day_id: int, exercises: list[NewExercise]) -> None:
        await self._insert_exercises(day_id, exercises)
        await self.conn.commit()

    async def remove_last_by_key(self, day_id: int, catalog_key: str) -> None:
        await self.conn.execute(
            """DELETE FROM day_exercises WHERE id = (
                   SELECT id FROM day_exercises WHERE day_id = ? AND catalog_key = ?
                   ORDER BY position DESC, id DESC LIMIT 1)""",
            (day_id, catalog_key),
        )
        await self.conn.commit()

    async def update_exercise(self, exercise_id: int, *, name: str | None = None, catalog_key: str | None = ...,
                              sets: int | None = None, reps: str | None = None) -> None:
        fields, params = [], []
        if name is not None:
            fields.append("name = ?"); params.append(name)
        if catalog_key is not ...:
            fields.append("catalog_key = ?"); params.append(catalog_key)
        if sets is not None:
            fields.append("sets = ?"); params.append(sets)
        if reps is not None:
            fields.append("reps = ?"); params.append(reps)
        if not fields:
            return
        await self.conn.execute(f"UPDATE day_exercises SET {', '.join(fields)} WHERE id = ?", (*params, exercise_id))
        await self.conn.commit()

    async def delete_exercise(self, exercise_id: int) -> None:
        await self.conn.execute("DELETE FROM day_exercises WHERE id = ?", (exercise_id,))
        await self.conn.commit()

    async def move_exercise_up(self, ex: DayExercise) -> bool:
        prev = await self._one(
            """SELECT id, position FROM day_exercises
               WHERE day_id = ? AND (position < ? OR (position = ? AND id < ?))
               ORDER BY position DESC, id DESC LIMIT 1""",
            (ex.day_id, ex.position, ex.position, ex.id),
        )
        if prev is None:
            return False
        new_pos = prev["position"] if prev["position"] != ex.position else ex.position - 1
        await self.conn.execute("UPDATE day_exercises SET position = ? WHERE id = ?", (new_pos, ex.id))
        await self.conn.execute("UPDATE day_exercises SET position = ? WHERE id = ?", (ex.position, prev["id"]))
        await self.conn.commit()
        return True

    async def replace_day_exercises(self, day_id: int, exercises: list[NewExercise]) -> None:
        await self.conn.execute("DELETE FROM day_exercises WHERE day_id = ?", (day_id,))
        await self._insert_exercises(day_id, exercises)
        await self.conn.commit()

    async def usual_sets_reps(self, program_id: int) -> tuple[int, str]:
        """Самые частые подходы×повторения в программе — их ставим новым упражнениям."""
        r = await self._one(
            """SELECT e.sets, e.reps, COUNT(*) AS c FROM day_exercises e
               JOIN program_days d ON d.id = e.day_id
               WHERE d.program_id = ? GROUP BY e.sets, e.reps ORDER BY c DESC LIMIT 1""",
            (program_id,),
        )
        return (r["sets"], r["reps"]) if r else (3, "8–12")

    # --- тренировка ---

    async def get_session(self, user_id: int) -> Session | None:
        r = await self._one("SELECT * FROM workout_sessions WHERE user_id = ?", (user_id,))
        if r is None:
            return None
        swaps = {int(k): v for k, v in json.loads(r["swaps"]).items()}
        return Session(r["user_id"], r["day_id"], r["current_id"], set(json.loads(r["done"])), r["started_at"], swaps,
                       r["message_id"])

    async def set_session_message(self, user_id: int, message_id: int | None) -> None:
        await self.conn.execute("UPDATE workout_sessions SET message_id = ? WHERE user_id = ?", (message_id, user_id))
        await self.conn.commit()

    async def workout_count(self, user_id: int) -> int:
        r = await self._one("SELECT COUNT(*) AS c FROM workout_log WHERE user_id = ?", (user_id,))
        return r["c"]

    async def save_session(self, s: Session) -> None:
        await self.conn.execute(
            """INSERT INTO workout_sessions (user_id, day_id, current_id, done, swaps, message_id, started_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET day_id = excluded.day_id, current_id = excluded.current_id,
                                                  done = excluded.done, swaps = excluded.swaps,
                                                  message_id = excluded.message_id,
                                                  started_at = excluded.started_at""",
            (s.user_id, s.day_id, s.current_id, json.dumps(sorted(s.done)), json.dumps(s.swaps), s.message_id,
             s.started_at),
        )
        await self.conn.commit()

    async def delete_session(self, user_id: int) -> None:
        await self.conn.execute("DELETE FROM workout_sessions WHERE user_id = ?", (user_id,))
        await self.conn.commit()

    async def log_workout(self, user_id: int, day: Day, done: int, total: int, started_at: str) -> int:
        """Сохраняет тренировку и возвращает, какая она по счёту."""
        await self.conn.execute(
            """INSERT INTO workout_log (user_id, program_name, day_title, done_count, total_count, started_at, finished_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (user_id, day.program_name, day.title, done, total, started_at, now_iso()),
        )
        await self.conn.commit()
        r = await self._one("SELECT COUNT(*) AS c FROM workout_log WHERE user_id = ?", (user_id,))
        return r["c"]

    # --- настройки бота ---

    async def get_setting(self, key: str) -> str | None:
        r = await self._one("SELECT value FROM settings WHERE key = ?", (key,))
        return r["value"] if r else None

    async def set_setting(self, key: str, value: str | None) -> None:
        if value is None:
            await self.conn.execute("DELETE FROM settings WHERE key = ?", (key,))
        else:
            await self.conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
        await self.conn.commit()

    # --- прогресс ---

    @staticmethod
    def exercise_key(ex: DayExercise) -> str:
        return ex.catalog_key or ex.name.strip().lower()

    async def log_exercise(self, user_id: int, ex: DayExercise, weight: float | None) -> None:
        await self.conn.execute(
            "INSERT INTO exercise_log (user_id, key, name, weight, sets, reps, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, self.exercise_key(ex), ex.name, weight, ex.sets, ex.reps, now_iso()),
        )
        await self.conn.commit()

    async def unlog_exercise(self, user_id: int, ex: DayExercise, since: str) -> None:
        """Убрать запись о выполнении в текущей тренировке (сняли отметку)."""
        await self.conn.execute(
            """DELETE FROM exercise_log WHERE id = (
                   SELECT id FROM exercise_log WHERE user_id = ? AND key = ? AND created_at >= ?
                   ORDER BY id DESC LIMIT 1)""",
            (user_id, self.exercise_key(ex), since),
        )
        await self.conn.commit()

    async def last_weights(self, user_id: int) -> dict[str, float]:
        """Последний указанный вес по каждому упражнению."""
        rows = await self._all(
            """SELECT key, weight FROM exercise_log WHERE id IN (
                   SELECT MAX(id) FROM exercise_log WHERE user_id = ? AND weight IS NOT NULL GROUP BY key)""",
            (user_id,),
        )
        return {r["key"]: r["weight"] for r in rows}

    async def weight_progress(self, user_id: int, limit: int) -> list[aiosqlite.Row]:
        """По упражнениям с весом: первый, последний и лучший вес, сколько раз делали. Свежие — первыми."""
        return await self._all(
            """SELECT g.key, g.times, g.best, l.name, f.weight AS first, l.weight AS last
               FROM (SELECT key, COUNT(*) AS times, MAX(weight) AS best, MAX(id) AS last_id, MIN(id) AS first_id
                     FROM exercise_log WHERE user_id = ? AND weight IS NOT NULL GROUP BY key) g
               JOIN exercise_log l ON l.id = g.last_id
               JOIN exercise_log f ON f.id = g.first_id
               ORDER BY g.last_id DESC LIMIT ?""",
            (user_id, limit),
        )

    async def recent_workouts(self, user_id: int, limit: int) -> list[aiosqlite.Row]:
        return await self._all(
            "SELECT day_title, done_count, total_count, finished_at FROM workout_log WHERE user_id = ? "
            "ORDER BY id DESC LIMIT ?", (user_id, limit),
        )

    async def workouts_since(self, user_id: int, since_iso: str) -> int:
        r = await self._one("SELECT COUNT(*) AS c FROM workout_log WHERE user_id = ? AND finished_at >= ?",
                            (user_id, since_iso))
        return r["c"]

    # --- обратная связь ---

    async def add_feedback(self, user_id: int, username: str | None, text: str) -> int:
        cur = await self.conn.execute(
            "INSERT INTO feedback (user_id, username, text) VALUES (?, ?, ?)", (user_id, username, text)
        )
        await self.conn.commit()
        return cur.lastrowid

    # --- кэш картинок ---

    async def get_photo_file_id(self, image: str) -> str | None:
        r = await self._one("SELECT file_id FROM photo_cache WHERE image = ?", (image,))
        return r["file_id"] if r else None

    async def save_photo_file_id(self, image: str, file_id: str) -> None:
        await self.conn.execute("INSERT OR REPLACE INTO photo_cache (image, file_id) VALUES (?, ?)", (image, file_id))
        await self.conn.commit()

    # --- внутреннее ---

    async def _next_position(self, table: str, parent_col: str, parent_id: int) -> int:
        r = await self._one(f"SELECT COALESCE(MAX(position) + 1, 0) AS p FROM {table} WHERE {parent_col} = ?",
                            (parent_id,))
        return r["p"]

    async def _insert_exercises(self, day_id: int, exercises: list[NewExercise]) -> None:
        start = await self._next_position("day_exercises", "day_id", day_id)
        await self.conn.executemany(
            "INSERT INTO day_exercises (day_id, position, name, sets, reps, catalog_key) VALUES (?, ?, ?, ?, ?, ?)",
            [(day_id, start + i, e.name, e.sets, e.reps, e.catalog_key) for i, e in enumerate(exercises)],
        )

    async def _upgrade_schema(self) -> None:
        columns = {r["name"] for r in await self._all("PRAGMA table_info(users)")}
        if "active_program_id" not in columns:
            await self.conn.execute("ALTER TABLE users ADD COLUMN active_program_id INTEGER")
        session_columns = {r["name"] for r in await self._all("PRAGMA table_info(workout_sessions)")}
        if "swaps" not in session_columns:
            await self.conn.execute("ALTER TABLE workout_sessions ADD COLUMN swaps TEXT NOT NULL DEFAULT '{}'")
        if "message_id" not in session_columns:
            await self.conn.execute("ALTER TABLE workout_sessions ADD COLUMN message_id INTEGER")
        if "classic_ui" not in columns:
            await self.conn.execute("ALTER TABLE users ADD COLUMN classic_ui INTEGER NOT NULL DEFAULT 0")

        # Версия 1 хранила одну программу в user_exercises (день = pull/legs/push/fullbody).
        # Переносим её в «Мою программу», чтобы ничего не потерялось.
        if not await self._one("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'user_exercises'"):
            return
        legacy = await self._all("SELECT * FROM user_exercises ORDER BY user_id, day, position")
        by_user: dict[int, dict[str, list[NewExercise]]] = {}
        for r in legacy:
            by_user.setdefault(r["user_id"], {}).setdefault(r["day"], []).append(
                NewExercise(r["name"], r["sets"], r["reps"], r["catalog_key"])
            )
        template = TEMPLATES["ppl"]
        for user_id, days in by_user.items():
            await self.create_program(user_id, "Моя программа", [
                (tday.title, days.get(tday.legacy_key) or [
                    NewExercise(CATALOG[e.key].name, e.sets, e.reps, e.key) for e in tday.exercises
                ])
                for tday in template.days
            ])
        await self.conn.execute("DROP TABLE user_exercises")
