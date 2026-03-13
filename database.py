import sqlite3
import json
from datetime import datetime

DB_FILE = "agent_memory.db"

def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS memory (topic TEXT PRIMARY KEY, content TEXT, updated_at DATETIME, access_count INTEGER DEFAULT 1)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS chat_history (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, message_json TEXT, timestamp DATETIME)''')

def add_to_history(user_id: str, message: dict):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("INSERT INTO chat_history (user_id, message_json, timestamp) VALUES (?, ?, ?)", (str(user_id), json.dumps(message), datetime.now().isoformat()))
        conn.execute("DELETE FROM chat_history WHERE id NOT IN (SELECT id FROM chat_history WHERE user_id = ? ORDER BY id DESC LIMIT 40) AND user_id = ?", (str(user_id), str(user_id)))

def get_history(user_id: str) -> list:
    with sqlite3.connect(DB_FILE) as conn:
        rows = conn.execute("SELECT message_json FROM chat_history WHERE user_id = ? ORDER BY id ASC", (str(user_id),)).fetchall()
        return [json.loads(row[0]) for row in rows]

def clear_history(user_id: str):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("DELETE FROM chat_history WHERE user_id = ?", (str(user_id),))

def memory_operation(action: str, topic: str = "", content: str = "", query: str = "") -> str:
    try:
        with sqlite3.connect(DB_FILE) as conn:
            if action == "save":
                if not topic or not content: return "Ошибка: нужны topic и content."
                conn.execute('''INSERT INTO memory (topic, content, updated_at, access_count) VALUES (?, ?, ?, 1) ON CONFLICT(topic) DO UPDATE SET content=excluded.content, updated_at=excluded.updated_at, access_count=1''', (topic, content, datetime.now().isoformat()))
                return f"Успешно сохранено: '{topic}'"
            elif action == "search":
                if not query: return "Ошибка: нужен query."
                results = conn.execute('''SELECT topic, content FROM memory WHERE topic LIKE ? OR content LIKE ? ORDER BY access_count DESC, updated_at DESC LIMIT 3''', (f'%{query}%', f'%{query}%')).fetchall()
                if not results: return "Ничего не найдено."
                for r in results: conn.execute('UPDATE memory SET access_count = access_count + 1, updated_at = ? WHERE topic = ?', (datetime.now().isoformat(), r[0]))
                return "Найдены воспоминания:\n" + "\n".join([f"[{r[0]}]: {r[1]}" for r in results])
            elif action == "forget":
                if not topic: return "Ошибка: нужен topic."
                conn.execute('DELETE FROM memory WHERE topic = ?', (topic,))
                return f"Воспоминание '{topic}' удалено."
            return "Неизвестное действие."
    except Exception as e: return f"Ошибка БД: {e}"

init_db()