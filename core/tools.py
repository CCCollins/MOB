import asyncio
import platform
import aiohttp
import os
import json
import io
import tempfile
import time
import re
import base64
from config.settings import get_config
from openai import AsyncOpenAI
import httpx

try:
    import pyautogui
    import pyperclip
except ImportError:
    pyautogui = None
    pyperclip = None

try:
    from PIL import Image, ImageDraw, ImageFont, ImageGrab
except ImportError:
    ImageGrab = None
    from PIL import Image, ImageDraw, ImageFont

def _get_aiohttp_session(proxy_url: str):
    """Безопасное создание aiohttp.ClientSession с поддержкой HTTP Proxy + Auth."""
    if proxy_url:
        try:
            from aiohttp_socks import ProxyConnector
            return aiohttp.ClientSession(connector=ProxyConnector.from_url(proxy_url)), None
        except ImportError:
            return aiohttp.ClientSession(), proxy_url
    return aiohttp.ClientSession(), None


_SCREENSHOT_DIR = os.path.join(os.path.dirname(__file__), "screenshots")
_screenshots_cleared = False

def _get_screenshot_dir(clean: bool = False) -> str:
    global _screenshots_cleared
    os.makedirs(_SCREENSHOT_DIR, exist_ok=True)
    if clean and not _screenshots_cleared:
        for fname in os.listdir(_SCREENSHOT_DIR):
            try: os.remove(os.path.join(_SCREENSHOT_DIR, fname))
            except Exception: pass
        _screenshots_cleared = True
    return _SCREENSHOT_DIR

def make_safe_filename(filename: str) -> str:
    return re.sub(r'[^\x00-\x7F]+', '_', filename)

def _minimize_telegram():
    if pyautogui is None: return
    try:
        if platform.system() == "Windows":
            import ctypes, ctypes.wintypes
            EnumWindows = ctypes.windll.user32.EnumWindows
            EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
            GetWindowTextW = ctypes.windll.user32.GetWindowTextW
            IsWindowVisible = ctypes.windll.user32.IsWindowVisible
            ShowWindow = ctypes.windll.user32.ShowWindow
            handles =[]
            def _cb(hwnd, _):
                if IsWindowVisible(hwnd):
                    buf = ctypes.create_unicode_buffer(256)
                    GetWindowTextW(hwnd, buf, 256)
                    if "telegram" in buf.value.lower(): handles.append(hwnd)
                return True
            EnumWindows(EnumWindowsProc(_cb), 0)
            for hwnd in handles: ShowWindow(hwnd, 6)
    except Exception: pass

# --- ФУНКЦИИ ОС И КЛАВИАТУРЫ ---

async def type_text(text: str) -> str:
    if pyautogui is None: return "Ошибка: инструмент клавиатуры недоступен в Headless-режиме."
    try:
        if platform.system() == "Windows":
            import ctypes
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            has_ru = any('\u0400' <= c <= '\u04FF' for c in text)
            layout = 0x04190419 if has_ru else 0x04090409
            ctypes.windll.user32.PostMessageW(hwnd, 0x0050, 0, layout)
            await asyncio.sleep(0.1)
        elif platform.system() == "Linux":
            try:
                import subprocess
                has_ru = any('\u0400' <= c <= '\u04FF' for c in text)
                layout = 'ru' if has_ru else 'us'
                subprocess.run(['setxkbmap', layout], check=True)
                await asyncio.sleep(0.1)
            except Exception: pass

        for key in['ctrl', 'alt', 'shift', 'win', 'command']:
            pyautogui.keyUp(key)
            
        if pyperclip:
            pyperclip.copy(text)
        await asyncio.sleep(0.2)
        
        if platform.system() == "Darwin":
            pyautogui.hotkey('command', 'v')
        else:
            pyautogui.hotkey('shift', 'insert')
            
        await asyncio.sleep(0.1)
        return f"Текст успешно напечатан: {text}"
    except Exception as e:
        return f"Ошибка ввода текста: {e}"

async def press_key(key: str) -> str:
    if pyautogui is None: return "Ошибка: инструмент недоступен в Headless-режиме."
    try:
        pyautogui.press(key)
        return f"Клавиша '{key}' нажата"
    except Exception as e: return f"Ошибка нажатия: {str(e)}"

async def hotkey(*keys: str) -> str:
    if pyautogui is None: return "Ошибка: инструмент недоступен в Headless-режиме."
    try:
        pyautogui.hotkey(*keys)
        return f"Горячая клавиша {'+'.join(keys)} нажата"
    except Exception as e: return f"Ошибка горячей клавиши: {str(e)}"

# --- СКРИНШОТЫ И ЗРЕНИЕ ---

async def take_screenshot(output_path: str | None = None, minimize_telegram: bool = True) -> str:
    if ImageGrab is None: return "Ошибка: Модуль создания скриншотов недоступен (вероятно Headless-режим)."
    try:
        if minimize_telegram:
            _minimize_telegram()
            await asyncio.sleep(0.5)
        screenshots_dir = _get_screenshot_dir(clean=True)
        filename = os.path.basename(output_path) if output_path else f"screenshot_{int(time.time())}.png"
        out_path = os.path.join(screenshots_dir, filename)

        if platform.system() == "Linux":
            try:
                screenshot = ImageGrab.grab()
                screenshot.save(out_path)
            except Exception:
                import subprocess
                result = subprocess.run(["scrot", "-z", out_path], capture_output=True, timeout=10)
                if result.returncode != 0:
                    return f"Ошибка scrot: {result.stderr.decode()}"
        else:
            screenshot = ImageGrab.grab()
            screenshot.save(out_path)

        return out_path.replace("\\", "/")
    except Exception as e:
        return f"Ошибка: {str(e)}"

def _get_font(size: int = 13):
    for path in["arialbd.ttf", "arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]:
        try: return ImageFont.truetype(path, size)
        except Exception: pass
    return ImageFont.load_default()

def _annotate_with_grid(image_path: str, cols: int = 10, rows: int = 7) -> tuple[str, dict]:
    img = Image.open(image_path).convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    font = _get_font(13)
    w, h = img.size
    step_x, step_y = w // cols, h // rows
    coords_map = {}

    for row in range(rows + 1):
        for col in range(cols + 1):
            cx, cy = min(col * step_x, w - 1), min(row * step_y, h - 1)
            label = f"({cx},{cy})"
            coords_map[label] = (cx, cy)
            draw.ellipse([cx - 4, cy - 4, cx + 4, cy + 4], fill=(255, 60, 60, 230))
            tx, ty = min(cx + 6, w - 40), min(cy + 4, h - 20)
            draw.rectangle([tx - 2, ty - 2, tx + 40, ty + 15], fill=(0, 0, 0, 170))
            draw.text((tx, ty), label, fill=(255, 230, 80, 255), font=font)

    result = Image.alpha_composite(img, overlay).convert("RGB")
    out_path = image_path.replace(".png", "_grid.png")
    result.save(out_path)
    return out_path.replace("\\", "/"), coords_map

async def take_annotated_screenshot(output_path: str | None = None) -> tuple[str, str, dict]:
    orig_path = await take_screenshot(output_path)
    if orig_path.startswith("Ошибка"): return orig_path, orig_path, {}
    grid_path, coords_map = _annotate_with_grid(orig_path)
    return orig_path, grid_path, coords_map

async def analyze_screenshot(image_path: str, prompt: str, use_grid: bool = False) -> str:
    try:
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
        actual_path = image_path
        grid_hint = ""
        if use_grid:
            actual_path, _ = _annotate_with_grid(image_path)
            grid_hint = "\nНА СКРИНШОТЕ НАНЕСЕНА СЕТКА. Назови координаты (x,y) ближайшей точки к нужному элементу."
        with open(actual_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        response = await client.chat.completions.create(
            model=get_config("model_main"),
            messages=[{"role": "user", "content":[{"type": "text", "text": prompt + grid_hint}, {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}]}]
        )
        return response.choices[0].message.content
    except Exception as e: return f"Ошибка анализа: {str(e)}"

async def smart_click(prompt: str, max_attempts: int = 3) -> str:
    if pyautogui is None: return "Ошибка: инструмент недоступен в Headless-режиме."
    try:
        orig_path, grid_path, _ = await take_annotated_screenshot()
        if orig_path.startswith("Ошибка"): return orig_path
        ai_prompt = f"Найди на скриншоте элемент: «{prompt}»\nОТВЕТЬ СТРОГО В ФОРМАТЕ: (x,y) — точные координаты центра элемента. Пример: (320,240)"
        for _ in range(max_attempts):
            resp = await analyze_screenshot(grid_path, ai_prompt)
            m = re.search(r"\(?\s*(-?\d+)\s*[;,]\s*(-?\d+)\s*\)?", resp)
            if m:
                x, y = int(m.group(1)), int(m.group(2))
                pyautogui.click(x, y)
                return f"Клик по «{prompt}» в ({x}, {y})"
            await asyncio.sleep(0.3)
        return f"Не удалось определить координаты. Ответ ИИ: {resp}"
    except Exception as e: return f"Ошибка smart_click: {str(e)}"

# --- ПРОЧИЕ ИНСТРУМЕНТЫ ---

async def convert_to_pdf(file_path: str, original_filename: str) -> str | None:
    api_key = get_config("DYNAMICPDF_API_KEY")
    proxy = get_config("PROXY_URL") or None
    if not api_key: return None
    ext = original_filename.lower().split('.')[-1]
    if ext in ['docx', 'doc']: input_type, mime = "word", 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    elif ext in ['xlsx', 'xls']: input_type, mime = "excel", 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    else: return None
    resource_name = make_safe_filename(original_filename)
    try:
        session, proxy_arg = _get_aiohttp_session(proxy)
        async with session:
            with open(file_path, 'rb') as f:
                form = aiohttp.FormData()
                form.add_field('Instructions', io.BytesIO(json.dumps({"inputs":[{"type": input_type, "resourceName": resource_name}]}).encode('utf-8')), filename='instructions.json', content_type='application/json')
                form.add_field('Resource', f, filename=resource_name, content_type=mime)
                async with session.post("https://api.dpdf.io/v1.0/pdf", headers={"Authorization": f"Bearer {api_key}"}, data=form, ssl=False, proxy=proxy_arg) as resp:
                    if resp.status != 200: return None
                    pdf_content = await resp.read()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(pdf_content)
            return tmp.name.replace("\\", "/")
    except: return None

async def execute_terminal(command: str) -> str:
    try:
        shell_cmd = f"powershell -NoProfile -Command \"[Console]::OutputEncoding =[System.Text.Encoding]::UTF8; {command}\"" if platform.system() == "Windows" else command
        process = await asyncio.create_subprocess_shell(shell_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=120.0)
        output = stdout.decode('utf-8', errors='replace') + stderr.decode('utf-8', errors='replace')
        return output[:2000] + "\n...[ОБРЕЗАНО]..." if len(output) > 2000 else output if output.strip() else "Успешно."
    except Exception as e: return f"Ошибка: {str(e)}"

async def web_search(query: str) -> str:
    api_key = get_config("BRAVE_API_KEY")
    proxy = get_config("PROXY_URL") or None
    if not api_key: return "Ключ Brave API не настроен."
    
    session, proxy_arg = _get_aiohttp_session(proxy)
    async with session:
        async with session.get("https://api.search.brave.com/res/v1/web/search", headers={"Accept": "application/json", "X-Subscription-Token": api_key}, params={"q": query}, proxy=proxy_arg) as response:
            if response.status != 200: return "Ошибка поиска."
            return "\n".join([f"{i.get('title')} - {i.get('url')}\n{i.get('description')}" for i in (await response.json()).get("web", {}).get("results", [])]) or "Ничего не найдено."

async def file_operation(action: str, filepath: str, content: str = "") -> str:
    try:
        if action == "read":
            with open(filepath, 'r', encoding='utf-8') as f:
                data = f.read()
                return data[:3000] + "\n[ОБРЕЗАНО]" if len(data) > 3000 else data
        elif action == "write":
            os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
            with open(filepath, 'w', encoding='utf-8') as f: f.write(content)
            return f"Файл записан: {filepath.replace(chr(92), '/')}"
    except Exception as e: return f"Ошибка: {str(e)}"

def _resolve_xy(x: float, y: float, relative: bool = False) -> tuple[int, int]:
    w, h = pyautogui.size()
    return int(x * w), int(y * h) if relative else (int(x), int(y))

async def click_mouse(x: float, y: float, relative: bool = False, clicks: int = 1, button: str = "left") -> str:
    if pyautogui is None: return "Ошибка: инструмент недоступен в Headless-режиме."
    try:
        xx, yy = _resolve_xy(x, y, relative)
        pyautogui.click(xx, yy, clicks=clicks, button=button)
        return f"Клик ({button}) в ({xx}, {yy})"
    except Exception as e: return f"Ошибка клика: {str(e)}"

async def scroll_mouse(x: float, y: float, clicks: int, relative: bool = False) -> str:
    if pyautogui is None: return "Ошибка: инструмент недоступен в Headless-режиме."
    try:
        xx, yy = _resolve_xy(x, y, relative)
        pyautogui.moveTo(xx, yy)
        pyautogui.scroll(clicks, xx, yy)
        return f"Скролл в ({xx}, {yy})"
    except Exception as e: return f"Ошибка скролла: {str(e)}"