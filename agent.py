import os
import sys
import json
import base64
import asyncio
import platform
import aiohttp
import tempfile
import io
import re
import logging
import time
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.methods import TelegramMethod
from typing import Optional
from openai import AsyncOpenAI
import sqlite3
from datetime import datetime

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)

# Загрузка переменных
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ALLOWED_IDS =[int(id.strip()) for id in os.getenv("ALLOWED_TELEGRAM_IDS", "").split(",") if id.strip()]
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
BRAVE_API_KEY = os.getenv("BRAVE_API_KEY")
DYNAMICPDF_API_KEY = os.getenv("DYNAMICPDF_API_KEY")

# Настройки моделей
MODEL_NAME = "google/gemini-3-flash-preview"       # Быстрая модель (Оркестратор)
EXPERT_MODEL = "anthropic/claude-haiku-4.5"     # Умная модель (Senior разработчик/аналитик)

# --- НАТИВНЫЙ СТРИМИНГ TELEGRAM API ---
class SendMessageDraft(TelegramMethod[bool]):
    __returning__ = bool
    __api_method__ = "sendMessageDraft"
    chat_id: int | str
    draft_id: int
    text: str
    parse_mode: Optional[str] = None
    message_thread_id: Optional[int] = None

# --- ДИНАМИЧЕСКИЙ СИСТЕМНЫЙ ПРОМПТ (ВРЕМЯ ВСЕГДА АКТУАЛЬНО) ---
def get_system_prompt() -> str:
    os_name = platform.system()
    if os_name == "Darwin": os_name = "macOS"
    os_details = platform.platform()
    
    # Берем точное время системы в момент запроса
    current_time = datetime.now().strftime("%d.%m.%Y, %H:%M:%S (Локальное время машины)")

    FORMATTING_RULES = """
    КРИТИЧЕСКИ ВАЖНЫЕ ПРАВИЛА ФОРМАТИРОВАНИЯ ДЛЯ TELEGRAM:
    1. ЗАПРЕЩЕНО использовать символ # для заголовков (он ломает разметку).
    2. Для заголовков и подзаголовков используй **жирный текст**.
    3. Для выделения используй __курсив__ или **жирный**.
    4. Для списков используй ТОЛЬКО эмодзи (например: 🔹, ⚙️, 📌, ✅) вместо дефисов или звездочек.
    5. Ссылки: [текст](url) - встраивай естественно в текст.
    6. Код оборачивай в обратные кавычки `код` или блоки ```язык ... ```.
    """

    return f"""Ты — автономный, проактивный ИИ-агент (Оркестратор).
ТЕКУЩАЯ СИСТЕМА: {os_name} ({os_details}).
ТЕКУЩЕЕ ВРЕМЯ: {current_time}. Опирайся только на это время!

Твои базовые возможности:
1. Выполнение команд терминала.
2. Поиск в интернете.
3. Чтение/запись файлов.
4. Долгая память.
5. Инициация общения через send_telegram_message.

ДЕЛЕГИРОВАНИЕ СЛОЖНЫХ ЗАДАЧ (САМОУЛУЧШЕНИЕ):
Ты работаешь на быстрой модели. Если пользователь просит написать сложный скрипт, программу, или провести глубокую аналитику — НЕ ПИШИ КОД САМ. Используй инструмент `delegate_task_to_expert`. Он вызовет мощную модель {EXPERT_MODEL}. Получив от нее готовый код, сохрани его в файл (в папке ./custom_tools/) и выполни. Улучшай код, если он выдает ошибки.

ФОНОВАЯ АКТИВНОСТЬ: Периодически ты будешь просыпаться без команды. Проверяй систему, вспоминай цели из памяти. Если делать нечего, отвечай 'IDLE'. Если нашел что-то важное — сообщи пользователю!
{FORMATTING_RULES}"""

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()
openai_client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)
MAIN_ADMIN_ID = ALLOWED_IDS[0] if ALLOWED_IDS else None

# --- БАЗА ДАННЫХ ПАМЯТИ И ИСТОРИИ ЧАТА ---
def init_db():
    conn = sqlite3.connect("agent_memory.db")
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS memory (topic TEXT PRIMARY KEY, content TEXT, updated_at DATETIME, access_count INTEGER DEFAULT 1)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS chat_history (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, message_json TEXT, timestamp DATETIME)''')
    conn.commit()
    conn.close()

init_db()

def add_to_history(user_id: int, message: dict):
    conn = sqlite3.connect("agent_memory.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO chat_history (user_id, message_json, timestamp) VALUES (?, ?, ?)",
                   (user_id, json.dumps(message), datetime.now().isoformat()))
    cursor.execute("""
        DELETE FROM chat_history 
        WHERE id NOT IN (
            SELECT id FROM chat_history WHERE user_id = ? ORDER BY id DESC LIMIT 40
        ) AND user_id = ?
    """, (user_id, user_id))
    conn.commit()
    conn.close()

def get_history(user_id: int) -> list:
    conn = sqlite3.connect("agent_memory.db")
    cursor = conn.cursor()
    cursor.execute("SELECT message_json FROM chat_history WHERE user_id = ? ORDER BY id ASC", (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return [json.loads(row[0]) for row in rows]

def clear_history(user_id: int):
    conn = sqlite3.connect("agent_memory.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM chat_history WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ И ИНСТРУМЕНТЫ ---

def make_safe_filename(filename: str) -> str:
    return re.sub(r'[^\x00-\x7F]+', '_', filename)

async def convert_to_pdf_dynamicpdf(file_path: str, original_filename: str) -> str | None:
    if not DYNAMICPDF_API_KEY: return None
    ext = original_filename.lower().split('.')[-1]
    if ext in ['docx', 'doc']: input_type, mime = "word", 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    elif ext in ['xlsx', 'xls']: input_type, mime = "excel", 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    else: return None

    resource_name = make_safe_filename(original_filename)
    instructions_json_str = json.dumps({"inputs":[{"type": input_type, "resourceName": resource_name}]})
    url = "https://api.dpdf.io/v1.0/pdf"
    headers = {"Authorization": f"Bearer {DYNAMICPDF_API_KEY}"}

    try:
        async with aiohttp.ClientSession() as session:
            with open(file_path, 'rb') as resource_file:
                form = aiohttp.FormData()
                form.add_field('Instructions', io.BytesIO(instructions_json_str.encode('utf-8')), filename='instructions.json', content_type='application/json')
                form.add_field('Resource', resource_file, filename=resource_name, content_type=mime)
                async with session.post(url, headers=headers, data=form, ssl=False) as response:
                    if response.status != 200: return None
                    pdf_content = await response.read()
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_pdf:
                tmp_pdf.write(pdf_content)
                return tmp_pdf.name
    except Exception: return None

async def delegate_task_to_expert(task_description: str, context: str = "") -> str:
    """Инструмент для вызова более умной модели."""
    try:
        prompt = f"Ты — Senior Software Engineer и Аналитик. Твоя задача — выполнить поручение безупречно.\n\nКонтекст:\n{context}\n\nЗадача:\n{task_description}\n\nВыдай готовый результат (если это код — только код с комментариями)."
        response = await openai_client.chat.completions.create(
            model=EXPERT_MODEL,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Ошибка при вызове экспертной модели: {e}"

async def execute_terminal(command: str) -> str:
    try:
        if platform.system() == "Windows":
            shell_cmd = f"powershell -NoProfile -Command \"[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; {command}\""
        else:
            shell_cmd = command

        process = await asyncio.create_subprocess_shell(shell_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=120.0)
        output = stdout.decode('utf-8', errors='replace') + stderr.decode('utf-8', errors='replace')
        
        if len(output) > 2000: return output[:2000] + "\n...[ОБРЕЗАНО]..."
        return output if output.strip() else "Успешно (нет вывода)."
    except Exception as e: return f"Ошибка: {str(e)}"

async def web_search(query: str) -> str:
    url = "https://api.search.brave.com/res/v1/web/search"
    headers = {"Accept": "application/json", "X-Subscription-Token": BRAVE_API_KEY}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, params={"q": query}) as response:
            if response.status != 200: return "Ошибка поиска."
            data = await response.json()
            results =[f"{i.get('title')} - {i.get('url')}\n{i.get('description')}" for i in data.get("web", {}).get("results", [])]
            return "\n".join(results) if results else "Ничего не найдено."

async def file_operation(action: str, filepath: str, content: str = "") -> str:
    try:
        if action == "read":
            with open(filepath, 'r', encoding='utf-8') as f:
                data = f.read()
                return data[:3000] + "\n[ОБРЕЗАНО]" if len(data) > 3000 else data
        elif action == "write":
            os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
            with open(filepath, 'w', encoding='utf-8') as f: f.write(content)
            return f"Файл записан."
    except Exception as e: return f"Ошибка: {str(e)}"

def memory_operation(action: str, topic: str = "", content: str = "", query: str = "") -> str:
    conn = sqlite3.connect("agent_memory.db")
    cursor = conn.cursor()
    try:
        if action == "save":
            if not topic or not content: return "Ошибка: нужны topic и content."
            cursor.execute('''INSERT INTO memory (topic, content, updated_at, access_count) VALUES (?, ?, ?, 1) ON CONFLICT(topic) DO UPDATE SET content=excluded.content, updated_at=excluded.updated_at, access_count=1''', (topic, content, datetime.now().isoformat()))
            conn.commit()
            return f"Успешно сохранено: '{topic}'"
        elif action == "search":
            if not query: return "Ошибка: нужен query."
            cursor.execute('''SELECT topic, content FROM memory WHERE topic LIKE ? OR content LIKE ? ORDER BY access_count DESC, updated_at DESC LIMIT 3''', (f'%{query}%', f'%{query}%'))
            results = cursor.fetchall()
            if not results: return "Ничего не найдено."
            for row in results: cursor.execute('UPDATE memory SET access_count = access_count + 1, updated_at = ? WHERE topic = ?', (datetime.now().isoformat(), row[0]))
            conn.commit()
            return "Найдены воспоминания:\n" + "\n".join([f"[{r[0]}]: {r[1]}" for r in results])
        elif action == "forget":
            if not topic: return "Ошибка: нужен topic."
            cursor.execute('DELETE FROM memory WHERE topic = ?', (topic,))
            conn.commit()
            return f"Воспоминание '{topic}' удалено."
        return "Неизвестное действие."
    except Exception as e: return f"Ошибка БД: {e}"
    finally: conn.close()

async def send_telegram_message(text: str) -> str:
    if MAIN_ADMIN_ID:
        try:
            await bot.send_message(MAIN_ADMIN_ID, f"🤖[Агент]:\n{text}")
            return "Отправлено."
        except Exception as e: return f"Ошибка: {e}"
    return "Нет ID админа."

TOOLS =[
    {"type": "function", "function": {"name": "delegate_task_to_expert", "description": "Делегировать написание кода (скриптов) или сложную аналитику более умной модели.", "parameters": {"type": "object", "properties": {"task_description": {"type": "string", "description": "Подробное ТЗ для программиста."}, "context": {"type": "string", "description": "Любые известные тебе данные системы/ошибки, чтобы помочь эксперту."}}, "required":["task_description"]}}},
    {"type": "function", "function": {"name": "execute_terminal", "description": "Выполнить bash/powershell команду.", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}},
    {"type": "function", "function": {"name": "web_search", "description": "Поиск в сети.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "file_operation", "description": "Чтение/запись файлов.", "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum":["read", "write"]}, "filepath": {"type": "string"}, "content": {"type": "string"}}, "required": ["action", "filepath"]}}},
    {"type": "function", "function": {"name": "memory_operation", "description": "Долгая ассоциативная память.", "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum":["save", "search", "forget"]}, "topic": {"type": "string"}, "content": {"type": "string"}, "query": {"type": "string"}}, "required": ["action"]}}},
    {"type": "function", "function": {"name": "send_telegram_message", "description": "Написать пользователю.", "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}}}
]

# --- ЦИКЛ АГЕНТА (ReAct) ---

async def run_agent(user_id: int, user_message, is_background=False, tg_message: types.Message = None):
    if user_message:
        add_to_history(user_id, {"role": "user", "content": user_message})

    # Динамически получаем актуальный промпт со временем ПРИ КАЖДОМ ЗАПРОСЕ
    messages =[{"role": "system", "content": get_system_prompt()}] + get_history(user_id)

    chat_id = tg_message.chat.id if tg_message else None
    draft_id = tg_message.message_id if tg_message else None
    thread_id = tg_message.message_thread_id if tg_message else None

    async def update_draft(text: str, parse_mode: Optional[str] = None):
        if not tg_message or is_background: return
        try:
            await bot(SendMessageDraft(chat_id=chat_id, draft_id=draft_id, text=text[:4096], parse_mode=parse_mode, message_thread_id=thread_id))
        except Exception: pass

    await update_draft("⏳ <i>Думаю...</i>", parse_mode="HTML")

    iterations = 0
    max_iterations = 5 if is_background else 10

    while iterations < max_iterations:
        iterations += 1
        full_text = ""
        tool_calls_dict = {}
        last_edit_time = 0

        try:
            response_stream = await openai_client.chat.completions.create(
                model=MODEL_NAME, messages=messages, tools=TOOLS, tool_choice="auto", stream=True 
            )
            
            async for chunk in response_stream:
                if not chunk.choices: continue
                delta = chunk.choices[0].delta

                if delta.content:
                    full_text += delta.content
                    if time.time() - last_edit_time > 0.3:
                        await update_draft(full_text, parse_mode=None)
                        last_edit_time = time.time()

                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in tool_calls_dict:
                            tool_calls_dict[idx] = {"id": tc.id, "type": "function", "function": {"name": tc.function.name or "", "arguments": ""}}
                        if tc.function.arguments: tool_calls_dict[idx]["function"]["arguments"] += tc.function.arguments

        except Exception as e:
            log.error(f"Ошибка API: {e}")
            await update_draft("")
            error_msg = f"❌ <b>Ошибка сервера нейросети:</b>\n<code>{e}</code>"
            if tg_message: await tg_message.answer(error_msg, parse_mode="HTML")
            add_to_history(user_id, {"role": "system", "content": f"[ОШИБКА API. Сообщение оборвано: {e}]"})
            return None

        tool_calls = list(tool_calls_dict.values())
        assistant_msg = {"role": "assistant"}
        if full_text: assistant_msg["content"] = full_text
        if tool_calls: assistant_msg["tool_calls"] = tool_calls
        
        add_to_history(user_id, assistant_msg)
        messages.append(assistant_msg)

        if not tool_calls:
            if full_text and tg_message:
                try: await bot.send_message(chat_id, full_text, parse_mode="Markdown")
                except Exception: await bot.send_message(chat_id, full_text)
            await update_draft("")
            if is_background and "IDLE" in full_text.strip(): return None
            return full_text

        if full_text and tg_message:
            try: await bot.send_message(chat_id, full_text, parse_mode="Markdown")
            except Exception: await bot.send_message(chat_id, full_text)

        # Выполнение инструментов
        for tc in tool_calls:
            func_name = tc["function"]["name"]
            try: args = json.loads(tc["function"]["arguments"])
            except: args = {}
            
            safe_args = str(args)[:100] + "..." if len(str(args)) > 100 else str(args)
            await update_draft(f"🛠 <b>Выполняю:</b> {func_name}\n<code>{safe_args}</code>", parse_mode="HTML")
            log.info(f"Агент вызывает: {func_name}({args})")
            
            result = ""
            if func_name == "execute_terminal": result = await execute_terminal(args.get("command", ""))
            elif func_name == "web_search": result = await web_search(args.get("query", ""))
            elif func_name == "file_operation": result = await file_operation(args.get("action", ""), args.get("filepath", ""), args.get("content", ""))
            elif func_name == "memory_operation": result = memory_operation(args.get("action", ""), args.get("topic", ""), args.get("content", ""), args.get("query", ""))
            elif func_name == "send_telegram_message": result = await send_telegram_message(args.get("text", ""))
            elif func_name == "delegate_task_to_expert": result = await delegate_task_to_expert(args.get("task_description", ""), args.get("context", ""))

            tool_msg = {"role": "tool", "tool_call_id": tc["id"], "name": func_name, "content": str(result)}
            add_to_history(user_id, tool_msg)
            messages.append(tool_msg)
            
            await update_draft("⏳ <i>Анализирую результат...</i>", parse_mode="HTML")

    await update_draft("") 
    warning = "⚠️ Агент достиг лимита итераций (задач) и был принудительно остановлен."
    if tg_message: await tg_message.answer(warning)
    add_to_history(user_id, {"role": "system", "content": "[СИСТЕМА: ПРОЦЕСС ПРЕРВАН ПО ЛИМИТУ ИТЕРАЦИЙ. Ответь пользователю.]"})
    return None

# --- ФОНОВАЯ АКТИВНОСТЬ ---

async def background_worker():
    await asyncio.sleep(60)
    while True:
        if MAIN_ADMIN_ID:
            log.info("Запуск фоновой проверки агента...")
            bg_prompt = "[СИСТЕМНОЕ СОБЫТИЕ: ФОНОВОЕ ПРОБУЖДЕНИЕ]\nПроверь свои логи, память на наличие отложенных задач или состояние системы. Если нужно что-то сделать - делай, если нужно предупредить пользователя - используй send_telegram_message. Если делать нечего, просто ответь одним словом 'IDLE'."
            await run_agent(MAIN_ADMIN_ID, bg_prompt, is_background=True)
        await asyncio.sleep(30000) 

# --- КОМАНДЫ (УПРАВЛЕНИЕ) ---

@dp.message(F.from_user.id.in_(ALLOWED_IDS) == False)
async def block_unauthorized(message: types.Message):
    await message.answer("Доступ запрещен.")

@dp.message(Command("reset"))
async def cmd_reset(message: types.Message):
    clear_history(message.from_user.id)
    await message.answer("🧹 Краткосрочная память (история сессии) успешно очищена.")

@dp.message(Command("restart"))
async def cmd_restart(message: types.Message):
    await message.answer("🔄 Перезапускаю процесс агента...")
    os.execv(sys.executable, ['python'] + sys.argv)

@dp.message(Command("stop"))
async def cmd_stop(message: types.Message):
    await message.answer("🛑 Агент отключается. До связи.")
    sys.exit(0)

@dp.message(Command("memorize"))
async def cmd_memorize(message: types.Message):
    await message.answer("🧠 Запущен анализ краткосрочной памяти для извлечения долгосрочных фактов...")
    prompt = "ПРИНУДИТЕЛЬНАЯ ИНСТРУКЦИЯ: Изучи наш последний диалог. Выдели важные факты, настройки или контекст, и сохрани их в долгосрочную память через инструмент `memory_operation` (action='save'). Если ничего важного нет, ответь 'Новых данных для долгосрочной памяти не найдено'."
    await run_agent(message.from_user.id, prompt, tg_message=message)

# --- ОБРАБОТЧИКИ ТЕКСТА И ФАЙЛОВ ---

@dp.message(F.text)
async def handle_text(message: types.Message):
    await run_agent(message.from_user.id, message.text, tg_message=message)

@dp.message(F.photo | F.document)
async def handle_files(message: types.Message):
    async def update_draft(text: str):
        try: await bot(SendMessageDraft(chat_id=message.chat.id, draft_id=message.message_id, text=text, parse_mode="HTML", message_thread_id=message.message_thread_id))
        except: pass

    await update_draft("⏳ <i>Скачиваю файл...</i>")
    
    file_id = message.photo[-1].file_id if message.photo else message.document.file_id
    file_info = await bot.get_file(file_id)
    downloaded_file = await bot.download_file(file_info.file_path)
    
    orig_name = message.document.file_name if message.document else "image.jpg"
    tmp_path = os.path.join(tempfile.gettempdir(), orig_name)
    with open(tmp_path, 'wb') as f: f.write(downloaded_file.read())

    user_text = message.caption or "Опиши этот файл и выполни нужные действия."
    content =[{"type": "text", "text": user_text}]

    ext = orig_name.lower().split('.')[-1]
    if ext in ['docx', 'doc', 'xlsx', 'xls']:
        await update_draft("⏳ <i>Конвертирую документ в PDF...</i>")
        pdf_path = await convert_to_pdf_dynamicpdf(tmp_path, orig_name)
        if pdf_path:
            with open(pdf_path, 'rb') as pdf_file:
                base64_pdf = base64.b64encode(pdf_file.read()).decode('utf-8')
                content.append({"type": "image_url", "image_url": {"url": f"data:application/pdf;base64,{base64_pdf}"}})
            os.remove(pdf_path)
        else: content[0]["text"] += f"\n\n[СИСТЕМА]: Сбой конвертации. Исходник сохранен: {tmp_path}."
    elif message.photo or ext in['jpg', 'jpeg', 'png']:
        with open(tmp_path, 'rb') as img_file:
            base64_image = base64.b64encode(img_file.read()).decode('utf-8')
            content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}})
    else: content[0]["text"] += f"\n\n[СИСТЕМА]: Файл сохранен локально по пути: {tmp_path}."

    await update_draft("") 
    await run_agent(message.from_user.id, content, tg_message=message)

async def main():
    log.info(f"Агент запущен на ОС: {platform.system()} ({platform.platform()})")
    asyncio.create_task(background_worker())
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Агент остановлен пользователем.")
        sys.exit(0)