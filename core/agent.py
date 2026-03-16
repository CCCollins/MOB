import json
import time
import platform
import logging
import asyncio
import httpx
from datetime import datetime
from openai import AsyncOpenAI
from aiogram.types import FSInputFile
import core.database as db
import core.tools as tools
from config.settings import get_config

try:
    import pyautogui
except ImportError:
    pyautogui = None

log = logging.getLogger("Agent")

active_sessions: dict[str, asyncio.Queue] = {}
user_locks: dict[str, asyncio.Lock] = {}

def reset_session_state():
    """Вызывается при старте нового event loop — очищает Lock/Queue,
    привязанные к старому loop, чтобы избежать 'bound to a different event loop'."""
    active_sessions.clear()
    user_locks.clear()

def get_system_prompt(source_channel: str) -> str:
    os_name = platform.system()
    if os_name == "Darwin": os_name = "macOS"
    current_time = datetime.now().strftime("%d.%m.%Y, %H:%M:%S (Локальное время)")
    
    screen_info = f"ЭКРАН: {pyautogui.size()[0]}x{pyautogui.size()[1]}." if pyautogui else "ЭКРАН: Недоступен (Headless)."

    channel_info = f"СТРОГОЕ ПРАВИЛО КАНАЛА СВЯЗИ:\nТекущий запрос пришел из: {source_channel}.\n"
    if source_channel == "GUI":
        channel_info += "Ты общаешься в локальном графическом интерфейсе (GUI). Все твои текстовые ответы УЖЕ выводятся пользователю на экран. КАТЕГОРИЧЕСКИ ЗАПРЕЩАЕТСЯ использовать функцию `send_telegram_message` для ответа пользователю! Просто генерируй текст."
    else:
        channel_info += "Пользователь пишет тебе из Telegram. Генерируй текст как обычно, он уйдет в Telegram автоматически. `send_telegram_message` используй ТОЛЬКО для инициации новых диалогов, когда ты просыпаешься сам в фоновом режиме."

    return f"""Ты — автономный, проактивный ИИ-агент (Оркестратор).
ТЕКУЩАЯ СИСТЕМА: {os_name} ({platform.platform()}). {screen_info} ВРЕМЯ: {current_time}.
{channel_info}

УПРАВЛЕНИЕ ИНТЕРФЕЙСОМ ОС (GUI):
Зрение (скриншоты) и мышь часто ошибаются. САМЫЙ НАДЕЖНЫЙ СПОСОБ УПРАВЛЕНИЯ — КЛАВИАТУРА!
Чтобы открыть программу: Вызови press_key('win') -> Вызови type_text('имя программы') -> Вызови press_key('enter').
Чтобы перемещаться по кнопкам/меню: Используй press_key('tab') или hotkey(['alt', 'tab']).
Используй клики мышью (smart_click) ТОЛЬКО если сделать это клавиатурой невозможно. 

ПРАВИЛА ТЕКСТА: Без символа # для заголовков. Заголовки: **жирный текст**. Списки: только эмодзи. Код: обратные кавычки.
ДЕЛЕГИРОВАНИЕ: Для сложного кода вызывай `delegate_task_to_expert`, сохраняй результат в файл и выполняй.

ДОЛГОСРОЧНАЯ ПАМЯТЬ (ОБЯЗАТЕЛЬНО):
У тебя есть инструмент `memory_operation` — постоянная ассоциативная память, которая сохраняется между сессиями.

ПОИСК: В НАЧАЛЕ КАЖДОГО разговора автоматически вызывай memory_operation(action="search", query="...") по теме сообщения пользователя. Это позволяет вспомнить важный контекст из прошлых сессий.

СОХРАНЕНИЕ — сохраняй СРАЗУ (не жди команды /memorize) если пользователь сообщает:
  - важные факты о системе, задачах, договорённостях
  - любую информацию, которая пригодится в будущих сессиях

ФОРМАТ: topic — короткий ключ (например "имя_пользователя", "роль_агента", "проект_X"), content — полное описание.
ОБНОВЛЕНИЕ: Если факт изменился — вызывай save с тем же topic (перезапишет старую запись).
НИКОГДА не говори "я запомнил" если не вызвал memory_operation(action="save") — это ложь."""

async def run_agent(user_id: str, user_message, source_channel="GUI", is_background=False, tg_update_callback=None, gui_stream_callback=None, bot_instance=None) -> bool:
    user_id = str(user_id)

    # Пересоздаём Lock/Queue если они привязаны к старому (закрытому) event loop
    if user_id in user_locks:
        try:
            current_loop = asyncio.get_running_loop()
            lk_loop = getattr(user_locks[user_id], '_loop', None)
            if lk_loop is not None and lk_loop is not current_loop:
                user_locks.pop(user_id, None)
                active_sessions.pop(user_id, None)
        except Exception:
            user_locks.pop(user_id, None)
            active_sessions.pop(user_id, None)

    if user_id not in user_locks:
        user_locks[user_id] = asyncio.Lock()
        
    if user_locks[user_id].locked():
        if user_id in active_sessions: active_sessions[user_id].put_nowait(user_message)
        return False

    async with user_locks[user_id]:
        active_sessions[user_id] = asyncio.Queue()
        try:
            await _run_agent_core(user_id, user_message, source_channel, is_background, tg_update_callback, gui_stream_callback, bot_instance)
        finally:
            active_sessions.pop(user_id, None)
            
        return True

async def _run_agent_core(user_id, user_message, source_channel, is_background, tg_update_callback, gui_stream_callback, bot_instance):
    if user_message: db.add_to_history(user_id, {"role": "user", "content": user_message})

    def _sanitize_messages(msgs):
        """
        Удаляет только «висячие» assistant-сообщения с tool_calls, у которых нет
        соответствующих tool-результатов. Все остальные сообщения сохраняются.
        """
        # Собираем id всех tool_call_id из tool-сообщений
        answered_ids = set()
        for msg in msgs:
            if msg.get("role") == "tool" and msg.get("tool_call_id"):
                answered_ids.add(msg["tool_call_id"])

        result = []
        for msg in msgs:
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                # Проверяем, есть ли ответ хотя бы на один tool_call
                call_ids = [tc.get("id") for tc in msg["tool_calls"] if tc.get("id")]
                if call_ids and not any(cid in answered_ids for cid in call_ids):
                    # Висячий tool_call — пропускаем assistant-сообщение
                    # и следом идущие tool-сообщения (их всё равно нет, но на всякий случай)
                    continue
            result.append(msg)

        assistant_call_ids = set()
        for msg in result:
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    if tc.get("id"):
                        assistant_call_ids.add(tc["id"])

        final = []
        for msg in result:
            if msg.get("role") == "tool" and msg.get("tool_call_id") not in assistant_call_ids:
                continue
            final.append(msg)

        return final

    raw_history = db.get_history(user_id)
    clean_history = _sanitize_messages(raw_history)

    if len(clean_history) != len(raw_history):
        removed = len(raw_history) - len(clean_history)
        logging.warning(f"[Agent] История {user_id}: найдено {removed} висячих tool_call записей, они исключены из контекста запроса (БД не изменяется).")

    memory_context = ""
    if user_message:
        query_text = user_message if isinstance(user_message, str) else (
            next((p["text"] for p in user_message if isinstance(p, dict) and p.get("type") == "text"), "")
        )
        if query_text:
            mem_result = db.memory_operation("search", query=query_text[:120])
            if mem_result and "Ничего не найдено" not in mem_result:
                memory_context = f"[ПАМЯТЬ из прошлых сессий]:\n{mem_result}\n"

    system_content = get_system_prompt(source_channel)
    if memory_context:
        system_content = system_content + "\n\n" + memory_context

    messages =[{"role": "system", "content": system_content}] + clean_history
    
    proxy_url = get_config("PROXY_URL") or None
    http_client = None
    if proxy_url:
        try:
            http_client = httpx.AsyncClient(proxy=proxy_url)
        except TypeError:
            http_client = httpx.AsyncClient(proxies=proxy_url)

    client = AsyncOpenAI(
        base_url="https://openrouter.ai/api/v1", 
        api_key=get_config("OPENROUTER_API_KEY"),
        http_client=http_client
    )

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
        {"type": "function", "function": {"name": "execute_terminal", "description": "Выполнить команду ОС.", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required":["command"]}}},
        {"type": "function", "function": {"name": "web_search", "description": "Поиск в сети.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required":["query"]}}},
        {"type": "function", "function": {"name": "file_operation", "description": "Чтение/запись файлов.", "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum":["read", "write"]}, "filepath": {"type": "string"}, "content": {"type": "string"}}, "required":["action", "filepath"]}}},
        {"type": "function", "function": {"name": "take_screenshot", "description": "Сделать обычный скриншот.", "parameters": {"type": "object", "properties": {"output_path": {"type": "string"}}}}},
        {"type": "function", "function": {"name": "take_annotated_screenshot", "description": "Сделать размеченный скриншот (Set-of-Mark) для ИИ зрения.", "parameters": {"type": "object", "properties": {"output_path": {"type": "string"}}}}},
        {"type": "function", "function": {"name": "send_file", "description": "Отправить файл/картинку пользователю в Telegram/GUI.", "parameters": {"type": "object", "properties": {"filepath": {"type": "string"}, "caption": {"type": "string"}}, "required":["filepath"]}}},
        {"type": "function", "function": {"name": "memory_operation", "description": "Ассоциативная память.", "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum":["save", "search", "forget"]}, "topic": {"type": "string"}, "content": {"type": "string"}, "query": {"type": "string"}}, "required":["action"]}}},
        {"type": "function", "function": {"name": "send_telegram_message", "description": "Инициировать сообщение в Telegram.", "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required":["text"]}}},
        {"type": "function", "function": {"name": "analyze_screenshot", "description": "Анализ скриншота.", "parameters": {"type": "object", "properties": {"image_path": {"type": "string"}, "prompt": {"type": "string"}, "use_grid": {"type": "boolean"}}, "required":["image_path", "prompt"]}}},
        {"type": "function", "function": {"name": "click_mouse", "description": "Клик мышью по координатам.", "parameters": {"type": "object", "properties": {"x": {"type": "number"}, "y": {"type": "number"}, "button": {"type": "string"}}, "required":["x", "y"]}}},
        {"type": "function", "function": {"name": "type_text", "description": "Ввести текст с клавиатуры.", "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}}},
        {"type": "function", "function": {"name": "press_key", "description": "Нажать 1 клавишу (enter, tab, win).", "parameters": {"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"]}}},
        {"type": "function", "function": {"name": "hotkey", "description": "Горячая клавиша (['alt', 'tab']).", "parameters": {"type": "object", "properties": {"keys": {"type": "array", "items": {"type": "string"}}}, "required": ["keys"]}}},
        {"type": "function", "function": {"name": "smart_click", "description": "Умный клик по элементу через зрение.", "parameters": {"type": "object", "properties": {"prompt": {"type": "string"}}, "required": ["prompt"]}}}
    ]

    max_iter = int(get_config("max_iterations") or 10)
    keep_chain = bool(get_config("keep_chain"))
    chain_thoughts: list[str] = []   # накопленные рассуждения при keep_chain=True

    def _format_chain(current_status: str = "") -> str:
        """Собирает все прошлые мысли + текущий статус в одно сообщение."""
        parts = []
        for i, t in enumerate(chain_thoughts, 1):
            parts.append(f"**Шаг {i}:** {t}")
        if current_status:
            parts.append(current_status)
        return "\n\n".join(parts)

    for iteration in range(max_iter):

        full_text, tool_calls_dict, last_edit = "", {}, 0
        try:
            stream = await client.chat.completions.create(model=get_config("model_main"), messages=messages, tools=TOOLS, tool_choice="auto", stream=True)
            async for chunk in stream:
                if not chunk.choices: continue
                delta = chunk.choices[0].delta
                if delta.content:
                    full_text += delta.content
                    if time.time() - last_edit > 0.4:
                        await _tg_stream(full_text)
                        last_edit = time.time()
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in tool_calls_dict: tool_calls_dict[idx] = {"id": tc.id, "type": "function", "function": {"name": tc.function.name or "", "arguments": ""}}
                        if tc.function.arguments: tool_calls_dict[idx]["function"]["arguments"] += tc.function.arguments
            log.info(f"[{source_channel}/{user_id}] Итерация {iteration + 1} — 200 OK"
                     + (f", инструменты: {[t['function']['name'] for t in tool_calls_dict.values()]}" if tool_calls_dict else ", текстовый ответ"))
        except Exception as e:
            log.error(f"[{source_channel}/{user_id}] Итерация {iteration + 1} — ошибка: {e}")
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

        while not active_sessions[user_id].empty():
            new_msg = active_sessions[user_id].get_nowait()
            intr_msg = (
                {"role": "user", "content": f"[СРОЧНОЕ УТОЧНЕНИЕ ПОЛЬЗОВАТЕЛЯ]: {new_msg}"}
                if isinstance(new_msg, str)
                else {"role": "user", "content": [
                    {"type": "text", "text": f"[СРОЧНОЕ УТОЧНЕНИЕ]: {new_msg[0]['text']}"},
                    new_msg[1]
                ]}
            )
            messages.append(intr_msg)
            db.add_to_history(user_id, intr_msg)

        if not tool_calls:
            if not active_sessions[user_id].empty(): continue
            final_ans = full_text.strip() if full_text.strip() else "✅ Задача завершена."
            if keep_chain and chain_thoughts:
                final_ans = _format_chain(f"**Итог:** {final_ans}")
            await _tg_final(final_ans)
            _gui_final(final_ans)
            return

        thought = full_text.strip()

        for tc in tool_calls:
            f_name = tc["function"]["name"]
            try: args = json.loads(tc["function"]["arguments"])
            except: args = {}

            status_msg = f"🛠 **Выполняю:** `{f_name}`\n`{str(args)[:50]}...`"
            if keep_chain:
                if thought and (not chain_thoughts or chain_thoughts[-1] != thought):
                    chain_thoughts.append(thought)
                combined_msg = _format_chain(status_msg)
            else:
                combined_msg = f"{thought}\n\n{status_msg}" if thought else status_msg
            _gui_status(combined_msg)
            await _tg_stream(combined_msg)
            
            result = ""
            if f_name == "execute_terminal": result = await tools.execute_terminal(args.get("command", ""))
            elif f_name == "web_search": result = await tools.web_search(args.get("query", ""))
            elif f_name == "file_operation": result = await tools.file_operation(args.get("action", ""), args.get("filepath", ""), args.get("content", ""))
            elif f_name == "take_screenshot":
                result = await tools.take_screenshot(args.get("output_path", ""))
                result = f"Скриншот сделан и сохранен: {result}"
            elif f_name == "take_annotated_screenshot":
                orig_path, annotated_path, coords_map = await tools.take_annotated_screenshot(args.get("output_path", ""))
                result = f"Размеченный скриншот сохранён: {annotated_path}\nМеток найдено: {len(coords_map)}"
            elif f_name == "send_file":
                filepath, caption = args.get("filepath", ""), args.get("caption", "")
                if bot_instance and source_channel == "Telegram":
                    try:
                        f_input = FSInputFile(filepath)
                        if filepath.lower().endswith((".png", ".jpg", ".jpeg")): await bot_instance.send_photo(user_id, f_input, caption=caption or None)
                        else: await bot_instance.send_document(user_id, f_input, caption=caption or None)
                        result = "Успешно отправлено в Telegram"
                    except Exception as e: result = f"Ошибка TG: {e}"
                elif source_channel == "GUI" and gui_stream_callback and filepath:
                    gui_stream_callback({"type": "file", "filepath": filepath, "caption": caption}, False)
                    result = "Успешно выведено в GUI"
                else: result = "Не отправлено (отсутствует нужный канал)."
            elif f_name == "memory_operation": result = db.memory_operation(args.get("action", ""), args.get("topic", ""), args.get("content", ""), args.get("query", ""))
            elif f_name == "delegate_task_to_expert":
                try: result = (await client.chat.completions.create(model=get_config("model_expert"), messages=[{"role": "user", "content": f"Задача: {args.get('task')}\nКонтекст: {args.get('context')}"}])).choices[0].message.content
                except Exception as e: result = f"Ошибка эксперта: {e}"
            elif f_name == "send_telegram_message":
                if bot_instance:
                    try:
                        await bot_instance.send_message(user_id, f"🤖 [Агент]:\n{args.get('text')}")
                        result = "Отправлено"
                    except Exception as e: result = f"Ошибка TG: {e}"
            elif f_name == "analyze_screenshot": result = await tools.analyze_screenshot(args.get("image_path", ""), args.get("prompt", ""), use_grid=args.get("use_grid", False))
            elif f_name == "click_mouse": result = await tools.click_mouse(args.get("x", 0), args.get("y", 0), button=args.get("button", "left"))
            elif f_name == "type_text": result = await tools.type_text(args.get("text", ""))
            elif f_name == "press_key": result = await tools.press_key(args.get("key", ""))
            elif f_name == "hotkey": result = await tools.hotkey(*args.get("keys",[]))
            elif f_name == "smart_click": result = await tools.smart_click(args.get("prompt", ""), max_attempts=args.get("max_attempts", 3))

            tool_msg = {"role": "tool", "tool_call_id": tc["id"], "name": f_name, "content": str(result)}
            db.add_to_history(user_id, tool_msg)
            messages.append(tool_msg)

            analyzing_msg = f"{thought}\n\n⏳ Анализирую результат..." if thought else "⏳ Анализирую результат..."
            if keep_chain:
                analyzing_msg = _format_chain("⏳ Анализирую результат...")
            _gui_status(analyzing_msg)
            await _tg_stream(analyzing_msg)

    final_limit = "⚠️ Достигнут лимит итераций задач."
    if keep_chain and chain_thoughts:
        final_limit = _format_chain(final_limit)
    await _tg_final(final_limit)
    _gui_final(final_limit)
    db.add_to_history(user_id, {"role": "system", "content": "[ПРЕРВАНО ПО ЛИМИТУ]"})