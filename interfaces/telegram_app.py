import os
import sys
import re
import json
import tempfile
import base64
import logging
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import FSInputFile, BotCommand
from config.settings import get_config, get_config_dir
import core.agent as agent
import core.database as db
import core.tools as tools

_RESTART_PENDING_FILE = os.path.join(get_config_dir(), "restart_pending.json")

_PDF_READER_SCRIPT = os.path.join(get_config_dir(), "read_pdf.py")

def _ensure_pdf_reader():
    """Создаёт универсальный скрипт read_pdf.py в папке конфига (один раз)."""
    if os.path.exists(_PDF_READER_SCRIPT):
        return
    script = '''#!/usr/bin/env python3
"""
read_pdf.py — универсальный ридер PDF с поддержкой OCR.
Использование:
    python read_pdf.py <path_to_pdf> [--ocr] [--pages 1-3,5]
    python read_pdf.py <path_to_pdf> --lang rus+eng
"""
import sys, os, argparse

def parse_pages(spec, total):
    pages = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            pages.update(range(int(a)-1, min(int(b), total)))
        else:
            pages.add(int(part)-1)
    return sorted(p for p in pages if 0 <= p < total)

def extract_with_pymupdf(pdf_path, pages):
    import fitz
    doc = fitz.open(pdf_path)
    target = pages if pages is not None else list(range(len(doc)))
    return "\\n".join(f"--- Страница {i+1} ---\\n{doc[i].get_text()}" for i in target)

def extract_with_ocr(pdf_path, pages, lang="rus+eng"):
    import fitz
    from PIL import Image
    import pytesseract, io
    doc = fitz.open(pdf_path)
    target = pages if pages is not None else list(range(len(doc)))
    parts = []
    for i in target:
        pix = doc[i].get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        parts.append(f"--- Страница {i+1} (OCR) ---\\n{pytesseract.image_to_string(img, lang=lang)}")
    return "\\n".join(parts)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--ocr", action="store_true")
    ap.add_argument("--pages", default=None)
    ap.add_argument("--lang", default="rus+eng")
    args = ap.parse_args()
    if not os.path.exists(args.pdf):
        print(f"ОШИБКА: файл не найден: {args.pdf}", file=sys.stderr); sys.exit(1)
    try:
        import fitz
    except ImportError:
        print("ОШИБКА: pip install pymupdf", file=sys.stderr); sys.exit(1)
    total = len(fitz.open(args.pdf))
    pages = parse_pages(args.pages, total) if args.pages else None
    if args.ocr:
        print(extract_with_ocr(args.pdf, pages, args.lang))
    else:
        result = extract_with_pymupdf(args.pdf, pages)
        if len(result.replace("--- Страница", "").strip()) < 50:
            print("[INFO] Текст не найден — пробую OCR...", file=sys.stderr)
            try:
                result = extract_with_ocr(args.pdf, pages, args.lang)
            except Exception as e:
                result += f"\\n[OCR недоступен: {e}]"
        print(result)

if __name__ == "__main__":
    main()
'''
    try:
        with open(_PDF_READER_SCRIPT, "w", encoding="utf-8") as f:
            f.write(script)
        logging.info(f"✅ Создан скрипт чтения PDF: {_PDF_READER_SCRIPT}")
    except Exception as e:
        logging.warning(f"⚠️ Не удалось создать read_pdf.py: {e}")

_ensure_pdf_reader()

def _save_restart_pending(chat_id: int, message_id: int):
    try:
        with open(_RESTART_PENDING_FILE, "w", encoding="utf-8") as f:
            json.dump({"chat_id": chat_id, "message_id": message_id, "autostart": True}, f)
    except Exception as e:
        logging.warning(f"Не удалось сохранить restart_pending: {e}")

def _load_and_clear_restart_pending() -> dict | None:
    if not os.path.exists(_RESTART_PENDING_FILE): return None
    try:
        with open(_RESTART_PENDING_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        os.remove(_RESTART_PENDING_FILE)
        return data
    except Exception as e:
        logging.warning(f"Не удалось прочитать restart_pending: {e}")
        return None

def check_autostart() -> bool:
    if not os.path.exists(_RESTART_PENDING_FILE): return False
    try:
        with open(_RESTART_PENDING_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get("autostart", False)
    except Exception: return False

BOT_COMMANDS =[
    BotCommand(command="memorize",   description="Сохранить факты в память"),
    BotCommand(command="screenshot", description="Отправить скриншот системы"),
    BotCommand(command="clear",      description="Сбросить краткосрочную память"),
    BotCommand(command="update",     description="Обновить код и перезапустить"),
    BotCommand(command="restart",    description="Принудительно перезапустить"),
    BotCommand(command="shutdown",   description="Принудительно выключить"),
]

async def setup_bot_commands(bot: Bot):
    try:
        current = await bot.get_my_commands()
        desired_tuples =[(c.command, c.description) for c in BOT_COMMANDS]
        current_tuples =[(c.command, c.description) for c in current]
        if current_tuples != desired_tuples:
            await bot.set_my_commands(BOT_COMMANDS)
            logging.info(f"✅ Команды бота обновлены: {[c.command for c in BOT_COMMANDS]}")
    except Exception as e:
        logging.warning(f"⚠️ Не удалось зарегистрировать команды бота: {e}")

    pending = _load_and_clear_restart_pending()
    if pending:
        try:
            await bot.edit_message_text(chat_id=pending["chat_id"], message_id=pending["message_id"], text="✅ Бот успешно перезапущен и готов к работе.")
        except Exception: pass

def _safe_markdown(text: str) -> str:
    # ### Заголовки → *Заголовок* (жирный без #)
    text = re.sub(r'^#{1,6}\s+(.+)$', r'*\1*', text, flags=re.MULTILINE)
    # **bold** → *bold* (Markdown v1)
    text = re.sub(r'\*\*(.+?)\*\*', r'*\1*', text, flags=re.DOTALL)
    # Маркеры списков: "*   ", "-   ", "•   " → "• "
    text = re.sub(r'^[ \t]*[\*\-•][ \t]+', '• ', text, flags=re.MULTILINE)
    # Экранируем одиночные [ и ] вне ссылок — ломают парсер
    text = re.sub(r'\[([^\]]*)\](?!\()', r'[\1]', text)
    # Убираем _italic_ — Markdown v1 его ненадёжно поддерживает
    text = re.sub(r'(?<!\w)_([^_\n]+)_(?!\w)', r'\1', text)
    return text[:4096]

def is_allowed(user_id: int) -> bool:
    raw_ids = get_config("ALLOWED_TELEGRAM_IDS")
    if not raw_ids: return False
    allowed =[int(x.strip()) for x in raw_ids.split(",") if x.strip()]
    return user_id in allowed

def get_tg_updater(message: types.Message, bot: Bot):
    reply_to = message.message_id
    streaming_msg_id: list[int | None] = [None]

    async def tg_updater(text, is_final=False):
        md = _safe_markdown(text)
        try:
            if streaming_msg_id[0] is None:
                sent = await bot.send_message(message.chat.id, md, parse_mode="Markdown", reply_to_message_id=reply_to)
                streaming_msg_id[0] = sent.message_id
            else:
                await bot.edit_message_text(chat_id=message.chat.id, message_id=streaming_msg_id[0], text=md, parse_mode="Markdown")
            
            if is_final:
                streaming_msg_id[0] = None
            return
        except Exception:
            pass
        
        try:
            if streaming_msg_id[0] is None:
                sent = await bot.send_message(message.chat.id, text[:4096], reply_to_message_id=reply_to)
                streaming_msg_id[0] = sent.message_id
            else:
                await bot.edit_message_text(chat_id=message.chat.id, message_id=streaming_msg_id[0], text=text[:4096])
            
            if is_final:
                streaming_msg_id[0] = None
        except Exception as e:
            logging.error(f"TG Error: {e}")

    return tg_updater

# ── Хендлеры ─────────────────────────

async def cmd_memorize(message: types.Message, bot: Bot):
    if not is_allowed(message.from_user.id): return
    await message.answer("🧠 Запущен анализ краткосрочной памяти...")
    prompt = "ПРИНУДИТЕЛЬНАЯ ИНСТРУКЦИЯ: Изучи наш последний диалог и сохрани факты..."
    await agent.run_agent(str(message.from_user.id), prompt, source_channel="Telegram", tg_update_callback=get_tg_updater(message, bot), bot_instance=bot)

async def cmd_screenshot(message: types.Message, bot: Bot):
    if not is_allowed(message.from_user.id): return
    status_msg = await message.answer("📸 Делаю скриншот...")
    result = await tools.take_screenshot()
    try: await bot.delete_message(message.chat.id, status_msg.message_id)
    except Exception: pass
    if result.startswith("Ошибка"):
        await message.answer(result)
        return
    try:
        await bot.send_photo(message.chat.id, FSInputFile(result))
    except Exception as e:
        await message.answer(f"Не удалось отправить: {e}")

async def cmd_reset(message: types.Message):
    if not is_allowed(message.from_user.id): return
    db.clear_history(str(message.from_user.id))
    await message.answer("🧹 История сессии очищена.")

async def cmd_update(message: types.Message, bot: Bot):
    if not is_allowed(message.from_user.id): return
    logging.warning("🔄 Получена команда /update — обновляю исходный код...")
    await message.answer("🔄 Скачиваю обновления (git pull)...")
    import subprocess
    try:
        res = subprocess.run(["git", "pull"], capture_output=True, text=True, timeout=30)
        await message.answer(f"Результат Git:\n```text\n{res.stdout}\n{res.stderr}\n```", parse_mode="Markdown")
        await cmd_restart(message, bot)
    except Exception as e:
        await message.answer(f"❌ Ошибка обновления: {e}")

async def cmd_restart(message: types.Message, bot: Bot):
    if not is_allowed(message.from_user.id): return
    logging.warning("🔄 Получена команда /restart — перезапускаю процесс...")
    try:
        sent = await message.answer("🔄 Перезапускаю бота... Подождите несколько секунд.")
        _save_restart_pending(chat_id=sent.chat.id, message_id=sent.message_id)
        await bot.session.close()
    except Exception: pass
    os.execv(sys.executable,[sys.executable] + sys.argv)

async def cmd_shutdown(message: types.Message, bot: Bot):
    if not is_allowed(message.from_user.id): return
    logging.warning("⏻ Получена команда /shutdown — выключаю процесс...")
    try:
        await message.answer("⏻ Выключаюсь...")
        await bot.session.close()
    except Exception: pass
    os._exit(0)

async def handle_text(message: types.Message, bot: Bot):
    if not is_allowed(message.from_user.id): return
    await agent.run_agent(str(message.from_user.id), message.text, source_channel="Telegram", tg_update_callback=get_tg_updater(message, bot), bot_instance=bot)

async def handle_files(message: types.Message, bot: Bot):
    if not is_allowed(message.from_user.id): return

    file_id = message.photo[-1].file_id if message.photo else message.document.file_id
    file_info = await bot.get_file(file_id)
    downloaded_file = await bot.download_file(file_info.file_path)

    orig_name = message.document.file_name if message.document else "image.jpg"
    tmp_path = os.path.join(tempfile.gettempdir(), orig_name)
    with open(tmp_path, 'wb') as f: f.write(downloaded_file.read())

    caption_text = message.caption or "Опиши файл"
    ext = orig_name.lower().split('.')[-1]
    content =[{"type": "text", "text": caption_text}]

    if ext in ('docx', 'doc', 'xlsx', 'xls', 'pdf'):
        if ext == 'pdf':
            content[0]["text"] += (
                f"\n\n[ФАЙЛ СОХРАНЁН]: {tmp_path}\n"
                f"Для извлечения текста используй готовый скрипт:\n"
                f"  execute_terminal('python3 {_PDF_READER_SCRIPT} \"{tmp_path}\"')\n"
                f"Если PDF сканированный (нет текста) — добавь флаг --ocr:\n"
                f"  execute_terminal('python3 {_PDF_READER_SCRIPT} \"{tmp_path}\" --ocr')\n"
                f"Можно читать конкретные страницы: --pages 1-3,5"
            )
        else:
            content[0]["text"] += f"\n\n[ФАЙЛ СОХРАНЁН]: {tmp_path}\nМодель: Это документ. Для чтения используй `execute_terminal` (python-docx, openpyxl или короткий Python-скрипт)."
    elif message.photo or ext in ('jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp'):
        with open(tmp_path, 'rb') as img_file: b64 = base64.b64encode(img_file.read()).decode('utf-8')
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
    else:
        content[0]["text"] += f"\nФайл '{orig_name}' сохранён по пути: {tmp_path}\nДля чтения текстового файла используй file_operation(read, '{tmp_path}')."

    await agent.run_agent(str(message.from_user.id), content, source_channel="Telegram", tg_update_callback=get_tg_updater(message, bot), bot_instance=bot)

def make_dispatcher() -> Dispatcher:
    new_dp = Dispatcher()
    new_dp.message.register(cmd_memorize,   Command("memorize"))
    new_dp.message.register(cmd_screenshot, Command("screenshot"))
    new_dp.message.register(cmd_reset,      Command("clear"))
    new_dp.message.register(cmd_update,     Command("update"))
    new_dp.message.register(cmd_restart,    Command("restart"))
    new_dp.message.register(cmd_shutdown,   Command("shutdown"))
    new_dp.message.register(handle_text,    F.text)
    new_dp.message.register(handle_files,   F.photo | F.document)
    return new_dp