import json
import time
import platform
import logging
import asyncio
from datetime import datetime
from openai import AsyncOpenAI
import database as db
import tools
from config import get_env, get_settings

log = logging.getLogger("Agent")

active_sessions: dict[str, asyncio.Queue] = {}
user_locks: dict[str, asyncio.Lock] = {}

def get_system_prompt() -> str:
    os_name = platform.system()
    if os_name == "Darwin": os_name = "macOS"
    current_time = datetime.now().strftime("%d.%m.%Y, %H:%M:%S (Локальное время машины)")
    
    return f"""Ты — автономный, проактивный ИИ-агент (Оркестратор).
ТЕКУЩАЯ СИСТЕМА: {os_name} ({platform.platform()}).
ТЕКУЩЕЕ ВРЕМЯ: {current_time}. Опирайся только на это время!

Твои возможности: Терминал, Поиск в сети, Чтение/Запись файлов, Долгая память, Отправка сообщений в Telegram.
ДЕЛЕГИРОВАНИЕ: Ты работаешь на быстрой модели. Если нужно написать скрипт/программу, НЕ ПИШИ КОД САМ. Вызови `delegate_task_to_expert`, дождись кода, сохрани в файл и выполни.
ПРАВИЛА ТЕКСТА: Без символа # для заголовков. Заголовки: **жирный текст**. Списки: только эмодзи. Код: обратные кавычки."""

async def run_agent(user_id: str, user_message, is_background=False, tg_update_callback=None, gui_stream_callback=None, bot_instance=None) -> bool:
    user_id = str(user_id)
    if user_id not in user_locks:
        user_locks[user_id] = asyncio.Lock()
        
    if user_locks[user_id].locked():
        if user_id in active_sessions:
            active_sessions[user_id].put_nowait(user_message)
        return False

    async with user_locks[user_id]:
        active_sessions[user_id] = asyncio.Queue()
        try:
            await _run_agent_core(user_id, user_message, is_background, tg_update_callback, gui_stream_callback, bot_instance)
        finally:
            active_sessions.pop(user_id, None)
        return True

async def _run_agent_core(user_id, user_message, is_background, tg_update_callback, gui_stream_callback, bot_instance):
    if user_message: db.add_to_history(user_id, {"role": "user", "content": user_message})
    messages =[{"role": "system", "content": get_system_prompt()}] + db.get_history(user_id)
    
    settings = get_settings()
    client = AsyncOpenAI(base_url="https://openrouter.ai/api/v1", api_key=get_env("OPENROUTER_API_KEY"))

    # Разделяем логику для TG (со стримингом) и GUI (без стриминга, только замена статусов)
    async def _tg_stream(text):
        if tg_update_callback: await tg_update_callback(text, False)
    async def _tg_final(text):
        if tg_update_callback: await tg_update_callback(text, True)
    
    def _gui_status(text):
        if gui_stream_callback: gui_stream_callback(text, True)
    def _gui_final(text):
        if gui_stream_callback: gui_stream_callback(text, False)

    _gui_status("⏳ Думаю...")
    await _tg_stream("⏳ Думаю...")

    TOOLS =[
        {"type": "function", "function": {"name": "delegate_task_to_expert", "description": "Делегировать сложный код умной модели.", "parameters": {"type": "object", "properties": {"task": {"type": "string"}, "context": {"type": "string"}}, "required":["task"]}}},
        {"type": "function", "function": {"name": "execute_terminal", "description": "Выполнить команду ОС.", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}},
        {"type": "function", "function": {"name": "web_search", "description": "Поиск в сети.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required":["query"]}}},
        {"type": "function", "function": {"name": "file_operation", "description": "Чтение/запись файлов.", "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum":["read", "write"]}, "filepath": {"type": "string"}, "content": {"type": "string"}}, "required": ["action", "filepath"]}}},
        {"type": "function", "function": {"name": "memory_operation", "description": "Ассоциативная память.", "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum":["save", "search", "forget"]}, "topic": {"type": "string"}, "content": {"type": "string"}, "query": {"type": "string"}}, "required": ["action"]}}},
        {"type": "function", "function": {"name": "send_telegram_message", "description": "Написать пользователю в Telegram.", "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required":["text"]}}}
    ]

    for iteration in range(int(settings.get("max_iterations", 10))):
        
        while not active_sessions[user_id].empty():
            new_msg = active_sessions[user_id].get_nowait()
            if isinstance(new_msg, str):
                intr_msg = {"role": "user", "content": f"[СРОЧНОЕ УТОЧНЕНИЕ ПОЛЬЗОВАТЕЛЯ]: {new_msg}"}
            else:
                new_msg[0]["text"] = f"[СРОЧНОЕ УТОЧНЕНИЕ ПОЛЬЗОВАТЕЛЯ]: {new_msg[0]['text']}"
                intr_msg = {"role": "user", "content": new_msg}
            
            messages.append(intr_msg)
            db.add_to_history(user_id, intr_msg)
            log.info(f"Получено уточнение от пользователя {user_id} в процессе работы.")

        full_text, tool_calls_dict, last_edit = "", {}, 0
        try:
            stream = await client.chat.completions.create(model=settings["model_main"], messages=messages, tools=TOOLS, tool_choice="auto", stream=True)
            async for chunk in stream:
                if not chunk.choices: continue
                delta = chunk.choices[0].delta
                if delta.content:
                    full_text += delta.content
                    if time.time() - last_edit > 0.3:
                        await _tg_stream(full_text)
                        last_edit = time.time()
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in tool_calls_dict: tool_calls_dict[idx] = {"id": tc.id, "type": "function", "function": {"name": tc.function.name or "", "arguments": ""}}
                        if tc.function.arguments: tool_calls_dict[idx]["function"]["arguments"] += tc.function.arguments
        except Exception as e:
            await _tg_final(f"❌ Ошибка API: {e}")
            _gui_final(f"❌ Ошибка API: {e}")
            db.add_to_history(user_id, {"role": "system", "content": f"[ОШИБКА API: {e}]"})
            return

        tool_calls = list(tool_calls_dict.values())
        msg_to_save = {"role": "assistant"}
        if full_text: msg_to_save["content"] = full_text
        if tool_calls: msg_to_save["tool_calls"] = tool_calls
        db.add_to_history(user_id, msg_to_save)
        messages.append(msg_to_save)

        if not tool_calls:
            if not active_sessions[user_id].empty():
                continue
            await _tg_final(full_text)
            _gui_final(full_text)
            return

        if full_text: 
            await _tg_final(full_text)
            _gui_final(full_text)

        for tc in tool_calls:
            f_name = tc["function"]["name"]
            try: args = json.loads(tc["function"]["arguments"])
            except: args = {}
            
            status_msg = f"🛠 <b>Выполняю:</b> {f_name}\n<code>{str(args)[:50]}...</code>"
            _gui_status(status_msg)
            await _tg_stream(status_msg)
            log.info(f"Agent Action: {f_name}")
            
            result = ""
            if f_name == "execute_terminal": result = await tools.execute_terminal(args.get("command", ""))
            elif f_name == "web_search": result = await tools.web_search(args.get("query", ""))
            elif f_name == "file_operation": result = await tools.file_operation(args.get("action", ""), args.get("filepath", ""), args.get("content", ""))
            elif f_name == "memory_operation": result = db.memory_operation(args.get("action", ""), args.get("topic", ""), args.get("content", ""), args.get("query", ""))
            elif f_name == "delegate_task_to_expert":
                try:
                    exp_resp = await client.chat.completions.create(model=settings["model_expert"], messages=[{"role": "user", "content": f"Задача: {args.get('task')}\nКонтекст: {args.get('context')}"}])
                    result = exp_resp.choices[0].message.content
                except Exception as e: result = f"Ошибка эксперта: {e}"
            elif f_name == "send_telegram_message":
                if bot_instance:
                    allowed =[id.strip() for id in get_env("ALLOWED_TELEGRAM_IDS").split(",") if id.strip()]
                    if allowed:
                        try:
                            await bot_instance.send_message(allowed[0], f"🤖 [Агент]:\n{args.get('text')}")
                            result = "Отправлено"
                        except Exception as e: result = f"Ошибка TG: {e}"
                else: result = "Telegram Bot не запущен."

            tool_msg = {"role": "tool", "tool_call_id": tc["id"], "name": f_name, "content": str(result)}
            db.add_to_history(user_id, tool_msg)
            messages.append(tool_msg)
            
            _gui_status("⏳ Анализирую результат...")
            await _tg_stream("⏳ Анализирую результат...")

    await _tg_final("⚠️ Достигнут лимит итераций задач.")
    _gui_final("⚠️ Достигнут лимит итераций задач.")
    db.add_to_history(user_id, {"role": "system", "content": "[ПРЕРВАНО ПО ЛИМИТУ]"})