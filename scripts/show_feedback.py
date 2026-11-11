"""Показывает все отзывы из базы.  Запуск:  python -m scripts.show_feedback"""

import os
import sqlite3

from dotenv import load_dotenv

load_dotenv()
conn = sqlite3.connect(os.getenv("DB_PATH", "gym.db"))
try:
    rows = conn.execute("SELECT id, created_at, user_id, username, text FROM feedback ORDER BY id").fetchall()
except sqlite3.OperationalError:  # таблица появляется при первом запуске бота с обратной связью
    rows = []
    print("Отзывов пока нет: перезапусти бота, чтобы включилась обратная связь.")
for fid, created, user_id, username, text in rows:
    print(f"№{fid} · {created} · {'@' + username if username else user_id}\n{text}\n")
print(f"Всего: {len(rows)}")
