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
import urllib.parse
from config.settings import get_config, get_config_dir
import os

try:
    import pyautogui
except ImportError:
    pyautogui = None

log = logging.getLogger("Agent")

active_sessions: dict[str, asyncio.Queue] = {}
user_locks: dict[str, asyncio.Lock] = {}

def reset_session_state():
    active_sessions.clear()
    user_locks.clear()

def get_system_prompt(source_channel: str) -> str:
    os_name = platform.system()
    if os_name == "Darwin": os_name = "macOS"
    current_time = datetime.now().strftime("%d.%m.%Y, %H:%M:%S (Локальное время)")
    
    screen_info = f"ЭКРАН: {pyautogui.size()[0]}x{pyautogui.size()[1]}." if pyautogui else "ЭКРАН: Недоступен (Headless)."
    work_dir = get_config("work_dir") or os.path.join(get_config_dir(), "workspace")

    channel_info = f"СТРОГОЕ ПРАВИЛО КАНАЛА СВЯЗИ:\nТекущий запрос пришел из: {source_channel}.\n"
    if source_channel == "GUI":
        channel_info += "Ты общаешься в локальном графическом интерфейсе (GUI). Все твои текстовые ответы УЖЕ выводятся пользователю на экран. КАТЕГОРИЧЕСКИ ЗАПРЕЩАЕТСЯ использовать функцию `send_telegram_message` для ответа пользователю! Просто генерируй текст."
    else:
        channel_info += "Пользователь пишет тебе из Telegram. Генерируй текст как обычно, он уйдет в Telegram автоматически. `send_telegram_message` используй ТОЛЬКО для инициации новых диалогов, когда ты просыпаешься сам в фоновом режиме."

    return f"""Ты — автономный, проактивный ИИ-агент (Оркестратор).
Твоя главная задача — ОРКЕСТРАЦИЯ (управление системой), а рутину делегируй другим моделям.
ТЕКУЩАЯ СИСТЕМА: {os_name} ({platform.platform()}). {screen_info} ВРЕМЯ: {current_time}.
{channel_info}

УПРАВЛЕНИЕ ИНТЕРФЕЙСОМ ОС (GUI):
⚠️ ГЛАВНОЕ ПРАВИЛО: НИКОГДА не пиши "я открыл", "я нашёл", "я отправил" если ты не вызвал соответствующий инструмент и не получил подтверждение. Любое заявление о выполненном действии без реального вызова инструмента — грубая ошибка. Если не сделал — так и скажи.

**ПРАВИЛО 1 — Клавиатура всегда приоритетнее мыши!**
Открыть программу: press_key('win') → type_text('имя') → press_key('enter').
Навигация по UI: press_key('tab'), press_key('enter'), hotkey(['alt','f4']).
Копировать/вставить: hotkey(['ctrl','c']) / hotkey(['ctrl','v']).

**ПРАВИЛО 2 — Workflow для клика мышью (только если клавиатурой невозможно):**
Вариант А (автоматически): smart_click(prompt='точное описание элемента') — сам сделает скриншот, найдёт и кликнет.
Вариант Б (вручную): take_screenshot() → analyze_screenshot(image_path=<путь>, prompt='Верни относительные координаты (0.0–1.0) центра элемента [X]. Только два числа через запятую.') → click_mouse(x, y) с пересчётом в пиксели.

**ПРАВИЛО 3 — После каждого клика делай take_screenshot() для проверки результата.**
Если интерфейс не изменился — попробуй другой подход (клавиатуру или другие координаты).

РАБОТА С ФАЙЛАМИ:
Рабочая папка по умолчанию: {work_dir}
Все создаваемые тобой файлы сохраняй туда. Раскидывай файлы по логическим подпапкам внутри рабочей папки (например: documents/, code/, images/, downloads/). Относительные пути автоматически считаются от рабочей папки.

ПРАВИЛА ТЕКСТА: Без символа # для заголовков. Заголовки: **жирный текст**. Списки: только эмодзи. Код: обратные кавычки.
СМАЙЛИКИ: Используй минимально (максимум 1-2 на сообщение). Категорически запрещено спамить длинными цепочками смайликов!

РАБОТА С БРАУЗЕРОМ И ИНТЕРНЕТОМ:
`web_search` — поиск по запросу (Brave). `open_url(url)` — открыть ссылку в браузере пользователя. `fetch_url(url)` — прочитать страницу (авто: сначала HTTP, потом headless Chromium). `browser_page(url, action, selector)` — явный headless Chromium, action='read'/'screenshot', selector — CSS-селектор блока.
Паттерн: если дана конкретная ссылка — сразу fetch_url. Если нужен поиск — web_search → fetch_url лучшего результата. Для скриншота сайта — browser_page(action='screenshot').

ДЕЛЕГИРОВАНИЕ ЗАДАЧ (ЭКОНОМИЯ ТОКЕНОВ И ВРЕМЕНИ):
- Для сложного программирования: вызывай `delegate_task_to_expert`.
- `ask_chat_model` — только если нужно написать текст ПОЛЬЗОВАТЕЛЮ в чат (ответить на вопрос, сгенерировать эссе, перевести). Если задача подразумевает напечатать что-то в программе на экране — это `type_text`, а не `ask_chat_model`.
ВАЖНО: Если ты вызвал `ask_chat_model`, больше ничего не пиши и не генерируй финальный текст, просто завершай работу!

ДОЛГОСРОЧНАЯ ПАМЯТЬ:
У тебя есть инструмент `memory_operation` — постоянная ассоциативная память.
В НАЧАЛЕ КАЖДОГО разговора автоматически вызывай memory_operation(action="search", query="...") по теме сообщения пользователя.
Если пользователь сообщает новые факты (о себе, задачах, системе) — сразу вызывай memory_operation(action="save").
ФОРМАТ: topic — короткий ключ, content — полное описание."""

async def run_agent(user_id: str, user_message, source_channel="GUI", is_background=False, tg_update_callback=None, gui_stream_callback=None, bot_instance=None) -> bool:
    user_id = str(user_id)

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
        # Убираем служебные system-записи об ошибках и прерываниях
        msgs = [m for m in msgs if not (
            m.get("role") == "system" and
            isinstance(m.get("content"), str) and
            (m["content"].startswith("[ОШИБКА") or m["content"].startswith("[ПРЕРВАНО"))
        )]

        # Шаг 1: нормализуем все tool_call ID до 40 символов ПЕРВЫМ делом,
        # чтобы assistant и tool записи использовали одинаковые ID
        def _norm_id(id_str: str) -> str:
            return id_str[-40:] if id_str and len(id_str) > 40 else id_str

        normalized = []
        for msg in msgs:
            msg = dict(msg)  # не мутируем оригинал из БД
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                msg["tool_calls"] = [
                    dict(tc, id=_norm_id(tc.get("id", "")))
                    for tc in msg["tool_calls"]
                ]
            if msg.get("role") == "tool" and msg.get("tool_call_id"):
                msg["tool_call_id"] = _norm_id(msg["tool_call_id"])
            normalized.append(msg)

        # Шаг 2: собираем ID всех tool_result — они отвечают на какой-то tool_use
        answered_ids = {
            m["tool_call_id"]
            for m in normalized
            if m.get("role") == "tool" and m.get("tool_call_id")
        }

        # Шаг 3: убираем assistant+tool_calls без ответа
        result = []
        for msg in normalized:
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                call_ids = [tc.get("id") for tc in msg["tool_calls"] if tc.get("id")]
                if call_ids and not any(cid in answered_ids for cid in call_ids):
                    continue
            result.append(msg)

        # Шаг 4: собираем ID всех tool_use которые остались в assistant
        assistant_call_ids = {
            tc.get("id")
            for msg in result
            if msg.get("role") == "assistant" and msg.get("tool_calls")
            for tc in msg["tool_calls"]
            if tc.get("id")
        }

        # Шаг 5: убираем tool_result без соответствующего tool_use
        final = [
            msg for msg in result
            if not (msg.get("role") == "tool" and msg.get("tool_call_id") not in assistant_call_ids)
        ]

        removed = len(msgs) - len(final)
        if removed > 0:
            logging.warning(f"[Agent] История {user_id}: найдено {removed} висячих tool_call записей, они исключены из контекста запроса (БД не изменяется).")

        return final

    raw_history = db.get_history(user_id)
    clean_history = _sanitize_messages(raw_history)

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

    system_msg = {"role": "system", "content": system_content}
    
    # === УМНЫЙ ОПТИМИЗАТОР КОНТЕКСТА ===
    ctx_limit_raw = get_config("LOCAL_CONTEXT_SIZE")
    ctx_limit = int(ctx_limit_raw) if ctx_limit_raw else 8192

    def _estimate_tokens(msg):
        tokens = 0
        content = msg.get("content", "")
        if isinstance(content, str):
            tokens += len(content) // 4
        elif isinstance(content, list):
            for item in content:
                if item.get("type") == "text":
                    tokens += len(item.get("text", "")) // 4
                elif item.get("type") == "image_url":
                    tokens += 1000  
        if msg.get("tool_calls"):
            tokens += len(str(msg["tool_calls"])) // 4
        return tokens

    budget = ctx_limit - 2500 - _estimate_tokens(system_msg)
    if budget < 1000: budget = 1000 

    kept_history =[]
    for msg in reversed(clean_history):
        cost = _estimate_tokens(msg)
        if budget - cost >= 0:
            budget -= cost
            kept_history.insert(0, msg)
        else:
            logging.warning(f"[{user_id}] Контекст заполнен! Старые сообщения отрезаны, чтобы избежать 500 ошибки.")
            break

    messages = [system_msg] + kept_history

    # Настройка URL и прокси
    base_url = get_config("OPENAI_BASE_URL")
    if base_url:
        base_url = base_url.strip().rstrip("/")
        if any(x in base_url for x in["localhost", "127.0.0.1", "0.0.0.0"]) and not base_url.endswith("/v1"):
            base_url += "/v1"
    else:
        base_url = "https://openrouter.ai/api/v1"

    api_key = get_config("OPENROUTER_API_KEY") or "sk-local-dummy-key"
    is_local_api = "127.0.0.1" in base_url or "localhost" in base_url or "0.0.0.0" in base_url

    def _flatten_for_local(msgs: list) -> list:
        """Преобразует историю в простой user/assistant/system формат для локальных моделей.
        - role:tool → role:user
        - assistant без content → текстовое описание вызова
        - Подряд идущие одинаковые роли (кроме system) схлопываются
        - Гарантирует что последнее сообщение — user
        """
        result = []

        for msg in msgs:
            role = msg.get("role")

            if role == "system":
                # Пропускаем системные записи об ошибках из БД — это не настоящий system prompt
                content = msg.get("content", "")
                if content.startswith("[ОШИБКА") or content.startswith("[ПРЕРВАНО"):
                    continue
                result.append({"role": "system", "content": content})
                continue

            if role == "tool":
                tool_name = msg.get("name", "tool")
                content = msg.get("content", "")
                result.append({"role": "user", "content": f"[Результат {tool_name}]:\n{content}"})
                continue

            if role == "assistant":
                text = msg.get("content") or ""
                tool_calls = msg.get("tool_calls")
                if tool_calls and not text:
                    names = ", ".join(tc.get("function", {}).get("name", "?") for tc in tool_calls)
                    text = f"[Вызываю: {names}]"
                result.append({"role": "assistant", "content": text or "…"})
                continue

            if role == "user":
                content = msg.get("content", "")
                if isinstance(content, list):
                    text_parts = []
                    image_parts = []
                    for p in content:
                        if p.get("type") == "text":
                            text_parts.append(p.get("text", ""))
                        elif p.get("type") in ("image_url", "image"):
                            image_parts.append(p)
                    if image_parts:
                        result.append({"role": "user", "content": [{"type": "text", "text": "\n".join(text_parts)}] + image_parts})
                    else:
                        result.append({"role": "user", "content": "\n".join(text_parts) or "?"})
                else:
                    result.append({"role": "user", "content": content or "?"})
                continue

        # Схлопываем подряд идущие одинаковые роли (кроме system)
        merged = []
        for m in result:
            role = m["role"]
            if role == "system":
                merged.append(dict(m))
                continue
            if merged and merged[-1]["role"] == role:
                prev_c = merged[-1]["content"]
                cur_c = m["content"]
                if isinstance(prev_c, list) or isinstance(cur_c, list):
                    if isinstance(prev_c, str):
                        prev_c = [{"type": "text", "text": prev_c}]
                    if isinstance(cur_c, str):
                        cur_c = [{"type": "text", "text": cur_c}]
                    merged[-1]["content"] = prev_c + [{"type": "text", "text": "\n---\n"}] + cur_c
                else:
                    sep = "\n\n---\n\n" if role == "user" else "\n"
                    merged[-1]["content"] = prev_c + sep + cur_c
            else:
                merged.append(dict(m))

        # Убираем system в самый конец если он вдруг там оказался
        # и гарантируем что последнее не-system сообщение — user
        non_system = [m for m in merged if m["role"] != "system"]
        systems = [m for m in merged if m["role"] == "system"]
        if non_system and non_system[-1]["role"] != "user":
            non_system.append({"role": "user", "content": "Продолжай."})
        final = systems + non_system

        log.debug(f"[flatten] roles: {[m['role'] for m in final]}")
        return final

    proxy_raw = get_config("PROXY_URL")
    proxy_url = None
    http_client = None

    if proxy_raw and proxy_raw.strip() and not is_local_api:
        proxy_raw = proxy_raw.strip()
        
        if not proxy_raw.startswith("http") and not proxy_raw.startswith("socks"):
            parts = proxy_raw.split(":")
            if len(parts) == 4:
                ip, port, user, pwd = parts
                user_enc = urllib.parse.quote(user)
                pwd_enc = urllib.parse.quote(pwd)
                proxy_url = f"http://{user_enc}:{pwd_enc}@{ip}:{port}"
            else:
                proxy_url = f"http://{proxy_raw}"
        else:
            proxy_url = proxy_raw

        try:
            http_client = httpx.AsyncClient(proxy=proxy_url)
        except TypeError:
            http_client = httpx.AsyncClient(proxies=proxy_url)

    client = AsyncOpenAI(
        base_url=base_url, 
        api_key=api_key,
        http_client=http_client
    )

    try:
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
            {"type": "function", "function": {"name": "ask_chat_model", "description": "Делегировать написание длинных текстов, стихов или размышлений быстрой чат-модели. Ответ уйдёт НАПРЯМУЮ пользователю в чат (GUI или Telegram). НЕЛЬЗЯ использовать если нужно напечатать текст в программе на экране компьютера — для этого используй type_text.", "parameters": {"type": "object", "properties": {"prompt": {"type": "string", "description": "Полный текст задачи для чат-модели со всем контекстом"}}, "required":["prompt"]}}},
            {"type": "function", "function": {"name": "delegate_task_to_expert", "description": "Делегировать сложный код умной модели-кодеру.", "parameters": {"type": "object", "properties": {"task": {"type": "string"}, "context": {"type": "string"}}, "required":["task"]}}},
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
            {"type": "function", "function": {"name": "type_text", "description": "Напечатать текст в активном окне на экране (в программе ОС: браузере, Telegram, редакторе и т.д.). Используй это когда нужно что-то написать в приложении на компьютере.", "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required":["text"]}}},
            {"type": "function", "function": {"name": "press_key", "description": "Нажать 1 клавишу (enter, tab, win).", "parameters": {"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"]}}},
            {"type": "function", "function": {"name": "hotkey", "description": "Горячая клавиша (['alt', 'tab']).", "parameters": {"type": "object", "properties": {"keys": {"type": "array", "items": {"type": "string"}}}, "required": ["keys"]}}},
            {"type": "function", "function": {"name": "smart_click", "description": "Умный клик по элементу через зрение.", "parameters": {"type": "object", "properties": {"prompt": {"type": "string"}}, "required":["prompt"]}}},
            {"type": "function", "function": {"name": "open_url", "description": "Открыть URL в браузере по умолчанию на компьютере пользователя. Используй для открытия сайтов, документации, ссылок из поиска.", "parameters": {"type": "object", "properties": {"url": {"type": "string", "description": "Полный URL (https://...)"}}, "required": ["url"]}}},
            {"type": "function", "function": {"name": "fetch_url", "description": "Прочитать содержимое страницы. Сначала пробует быстрый HTTP, при неудаче автоматически переключается на headless-браузер с JS. Используй для чтения статей, GitHub, документации, новостей.", "parameters": {"type": "object", "properties": {"url": {"type": "string"}, "max_chars": {"type": "integer", "description": "Максимум символов (по умолч. 8000)"}}, "required": ["url"]}}},
            {"type": "function", "function": {"name": "browser_page", "description": "Headless Chromium (Playwright). Используй для JS-сайтов, SPA, авторизованных страниц. action='read' — вернуть текст, action='screenshot' — скриншот страницы. selector — CSS-селектор для конкретного блока.", "parameters": {"type": "object", "properties": {"url": {"type": "string"}, "action": {"type": "string", "enum": ["read", "screenshot"], "description": "read или screenshot"}, "selector": {"type": "string", "description": "CSS-селектор (опционально)"}, "max_chars": {"type": "integer"}}, "required": ["url"]}}},
            {"type": "function", "function": {"name": "checko_api", "description": "Поиск компаний и ИП через Checko API.", "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum":["search", "company"]}, "query": {"type": "string"}}, "required": ["action", "query"]}}},
        ]

        max_iter = int(get_config("max_iterations") or 10)
        keep_chain = bool(get_config("keep_chain"))
        chain_thoughts: list[str] =[]
        _last_tool_sig: str | None = None   # для детектирования зацикливания
        _loop_count: int = 0

        def _format_chain(current_status: str = "") -> str:
            parts =[]
            for i, t in enumerate(chain_thoughts, 1):
                parts.append(f"**Шаг {i}:** {t}")
            if current_status:
                parts.append(current_status)
            return "\n\n".join(parts)

        for iteration in range(max_iter):

            full_text, tool_calls_dict, last_edit = "", {}, 0
            try:
                send_messages = _flatten_for_local(messages) if is_local_api else messages
                # Для локальных моделей после нескольких итераций добавляем явный стоп-хинт
                if is_local_api and iteration > 0 and send_messages and send_messages[-1]["role"] == "user":
                    hint = "\n\n[ИНСТРУКЦИЯ]: Если задача уже выполнена или результат получен — ОБЯЗАТЕЛЬНО напиши итоговый ответ пользователю текстом и НЕ вызывай больше инструменты."
                    last = send_messages[-1]
                    if isinstance(last["content"], str):
                        send_messages = send_messages[:-1] + [{"role": "user", "content": last["content"] + hint}]
                stream = await client.chat.completions.create(
                    model=get_config("model_orchestrator"),
                    messages=send_messages,
                    tools=TOOLS,
                    tool_choice="auto",
                    stream=True,
                    **({"max_tokens": max(512, ctx_limit // 4)} if is_local_api else {})
                )
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

            # Детектирование зацикливания: та же функция с теми же аргументами
            if is_local_api and tool_calls:
                sig = str([(tc["function"]["name"], tc["function"]["arguments"]) for tc in tool_calls])
                if sig == _last_tool_sig:
                    _loop_count += 1
                else:
                    _last_tool_sig = sig
                    _loop_count = 0
                if _loop_count >= 2:
                    log.warning(f"[{user_id}] Обнаружено зацикливание инструмента, принудительно завершаю.")
                    final_ans = full_text.strip() or "✅ Задача выполнена."
                    await _tg_final(final_ans)
                    _gui_final(final_ans)
                    return

            while not active_sessions[user_id].empty():
                new_msg = active_sessions[user_id].get_nowait()
                intr_msg = (
                    {"role": "user", "content": f"[СРОЧНОЕ УТОЧНЕНИЕ ПОЛЬЗОВАТЕЛЯ]: {new_msg}"}
                    if isinstance(new_msg, str)
                    else {"role": "user", "content":[
                        {"type": "text", "text": f"[СРОЧНОЕ УТОЧНЕНИЕ]: {new_msg[0]['text']}"},
                        new_msg[1]
                    ]}
                )
                messages.append(intr_msg)
                db.add_to_history(user_id, intr_msg)

            if not tool_calls:
                if not active_sessions[user_id].empty(): continue
                final_ans = full_text.strip() if full_text.strip() else "✅ Задача завершена."
                if not keep_chain and chain_thoughts:
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
                    if thought:
                        await _tg_final(thought)
                        _gui_final(thought)
                    _gui_status(status_msg)
                    await _tg_stream(status_msg)
                else:
                    if thought and (not chain_thoughts or chain_thoughts[-1] != thought):
                        chain_thoughts.append(thought)
                    combined_msg = _format_chain(status_msg)
                    _gui_status(combined_msg)
                    await _tg_stream(combined_msg)
                
                result = ""
                should_return_after_tool = False

                if f_name == "execute_terminal": result = await tools.execute_terminal(args.get("command", ""))
                elif f_name == "web_search": result = await tools.web_search(args.get("query", ""))
                elif f_name == "file_operation": result = await tools.file_operation(args.get("action", ""), args.get("filepath", ""), args.get("content", ""))
                elif f_name == "take_screenshot":
                    result = await tools.take_screenshot(args.get("output_path", ""))
                    result = f"Скриншот сделан и сохранен: {result}"
                elif f_name == "take_annotated_screenshot":
                    orig_path, annotated_path, coords_map = await tools.take_annotated_screenshot(args.get("output_path", ""))
                    if orig_path.startswith("Ошибка"):
                        result = orig_path
                    else:
                        result = (
                            f"Скриншот сохранён: {annotated_path}\n"
                            f"Используй analyze_screenshot(image_path='{annotated_path}', prompt='...') для анализа."
                        )
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
                elif f_name == "ask_chat_model":
                    try:
                        chat_resp = await client.chat.completions.create(
                            model=get_config("model_chat"),
                            messages=[{"role": "user", "content": args.get("prompt")}]
                        )
                        chat_text = chat_resp.choices[0].message.content
                        if bot_instance and source_channel == "Telegram":
                            await bot_instance.send_message(user_id, chat_text, parse_mode=None)
                        elif source_channel == "GUI" and gui_stream_callback:
                            gui_stream_callback(chat_text, False)
                        result = "[ask_chat_model: ответ отправлен пользователю]"
                        should_return_after_tool = True 
                    except Exception as e:
                        result = f"Ошибка чат-модели: {e}"
                elif f_name == "send_telegram_message":
                    if bot_instance:
                        try:
                            await bot_instance.send_message(user_id, f"🤖 [Агент]:\n{args.get('text')}")
                            result = "Отправлено"
                        except Exception as e: result = f"Ошибка TG: {e}"
                elif f_name == "analyze_screenshot": result = await tools.analyze_screenshot(args.get("image_path", ""), args.get("prompt", ""), use_grid=args.get("use_grid", False))
                elif f_name == "click_mouse":
                    result = await tools.click_mouse(args.get("x", 0), args.get("y", 0), button=args.get("button", "left"))
                    await asyncio.sleep(0.6)
                    shot = await tools.take_screenshot()
                    result += f"\n[Скриншот после клика: {shot}]"
                elif f_name == "type_text":
                    result = await tools.type_text(args.get("text", ""))
                    await asyncio.sleep(0.3)
                elif f_name == "press_key":
                    result = await tools.press_key(args.get("key", ""))
                    await asyncio.sleep(0.3)
                elif f_name == "hotkey": result = await tools.hotkey(*args.get("keys",[]))
                elif f_name == "smart_click":
                    result = await tools.smart_click(args.get("prompt", ""), max_attempts=args.get("max_attempts", 3))
                    await asyncio.sleep(0.6)
                    shot = await tools.take_screenshot()
                    result += f"\n[Скриншот после клика: {shot}]"
                elif f_name == "checko_api": result = await tools.checko_api(args.get("action", ""), args.get("query", ""))
                elif f_name == "open_url": result = await tools.open_url(args.get("url", ""))
                elif f_name == "fetch_url": result = await tools.fetch_url(args.get("url", ""), args.get("max_chars", 8000))
                elif f_name == "browser_page": result = await tools.browser_page(args.get("url", ""), args.get("action", "read"), args.get("selector", ""), args.get("max_chars", 8000))

                tool_msg = {"role": "tool", "tool_call_id": tc["id"], "name": f_name, "content": str(result)}
                db.add_to_history(user_id, tool_msg)
                messages.append(tool_msg)

                if should_return_after_tool:
                    return

                analyzing_msg = "⏳ Анализирую результат..."
                if keep_chain:
                    _gui_status(analyzing_msg)
                    await _tg_stream(analyzing_msg)
                else:
                    combined_msg = _format_chain(analyzing_msg)
                    _gui_status(combined_msg)
                    await _tg_stream(combined_msg)

        final_limit = "⚠️ Достигнут лимит итераций задач."
        if not keep_chain and chain_thoughts:
            final_limit = _format_chain(final_limit)
        await _tg_final(final_limit)
        _gui_final(final_limit)
        db.add_to_history(user_id, {"role": "system", "content": "[ПРЕРВАНО ПО ЛИМИТУ]"})

    finally:
        await client.close()
        if http_client:
            await http_client.aclose()