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
from config import get_config, get_config_dir
import agent
import database as db
import tools

_RESTART_PENDING_FILE = os.path.join(get_config_dir(), "restart_pending.json")

def _save_restart_pending(chat_id: int, message_id: int):
    try:
        with open(_RESTART_PENDING_FILE, "w", encoding="utf-8") as f:
            json.dump({"chat_id": chat_id, "message_id": message_id, "autostart": True}, f)
    except Exception as e:
        logging.warning(f"Не удалось сохранить restart_pending: {e}")

def _load_and_clear_restart_pending() -> dict | None:
    if not os.path.exists(_RESTART_PENDING_FILE):
        return None
    try:
        with open(_RESTART_PENDING_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        os.remove(_RESTART_PENDING_FILE)
        return data
    except Exception as e:
        logging.warning(f"Не удалось прочитать restart_pending: {e}")
        return None

def check_autostart() -> bool:
    """Возвращает True если этот запуск — результат /restart и нужен автостарт бота."""
    if not os.path.exists(_RESTART_PENDING_FILE):
        return False
    try:
        with open(_RESTART_PENDING_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get("autostart", False)
    except Exception:
        return False

dp = Dispatcher()

BOT_COMMANDS = [
    BotCommand(command="memorize",   description="Сохранить факты в память"),
    BotCommand(command="screenshot", description="Отправить скриншот системы"),
    BotCommand(command="clear",      description="Сбросить краткосрочную память"),
    BotCommand(command="restart",    description="Принудительно перезапустить"),
    BotCommand(command="shutdown",   description="Принудительно выключить"),
]

async def setup_bot_commands(bot: Bot):
    """Регистрирует команды в меню Telegram только если список изменился, и обрабатывает отложенное сообщение после рестарта."""
    try:
        current = await bot.get_my_commands()
        desired_tuples = [(c.command, c.description) for c in BOT_COMMANDS]
        current_tuples = [(c.command, c.description) for c in current]
        if current_tuples != desired_tuples:
            await bot.set_my_commands(BOT_COMMANDS)
            logging.info(f"✅ Команды бота обновлены: {[c.command for c in BOT_COMMANDS]}")
        else:
            logging.info("✅ Команды бота актуальны, обновление не требуется.")
    except Exception as e:
        logging.warning(f"⚠️ Не удалось проверить/зарегистрировать команды бота: {e}")

    pending = _load_and_clear_restart_pending()
    if pending:
        try:
            await bot.edit_message_text(
                chat_id=pending["chat_id"],
                message_id=pending["message_id"],
                text="✅ Бот успешно перезапущен и готов к работе.",
            )
            logging.info("✅ Сообщение о перезапуске обновлено.")
        except Exception as e:
            logging.warning(f"Не удалось обновить сообщение о перезапуске: {e}")

# ─── Вспомогательные функции ─────────────────────────────────────────────────

def _safe_markdown(text: str) -> str:
    """
    Приводит текст к виду, который Telegram Markdown v1 переварит без ошибок.
    - Заменяет ** на * (v1 не знает **)
    - Убирает незакрытые одиночные * и _ чтобы не сломать парсер
    - Обрезает до 4096 символов
    """
    # ** → * для жирного (Telegram Markdown v1 использует одиночные *)
    text = re.sub(r'\*\*(.+?)\*\*', r'*\1*', text, flags=re.DOTALL)
    # Убираем незакрытые маркеры — считаем количество * и _ вне кода
    # Простой способ: если нечётное кол-во * вне блоков кода — убираем лишний
    # Вместо сложного парсинга — просто экранируем одиночные * и _ не являющиеся парными
    lines = []
    for line in text.split('\n'):
        # Не трогаем строки с кодом
        if line.strip().startswith('`'):
            lines.append(line)
            continue
        # Считаем непарные * (не ** — уже заменены выше)
        stars = line.count('*')
        if stars % 2 != 0:
            # Непарная звёздочка — убираем последнюю одиночную
            line = line[::-1].replace('*', '', 1)[::-1]
        lines.append(line)
    return '\n'.join(lines)[:4096]


def is_allowed(user_id: int) -> bool:
    raw_ids = get_config("ALLOWED_TELEGRAM_IDS")
    if not raw_ids: return False
    allowed = [int(x.strip()) for x in raw_ids.split(",") if x.strip()]
    return user_id in allowed

def get_tg_updater(message: types.Message, bot: Bot):
    reply_to = message.message_id
    streaming_msg_id: list[int | None] = [None]

    async def _send_final(text: str):
        """Отправляет/редактирует финальное сообщение с Markdown, fallback на plain."""
        md = _safe_markdown(text)
        if streaming_msg_id[0] is not None:
            try:
                await bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=streaming_msg_id[0],
                    text=md, parse_mode="Markdown",
                )
                return
            except Exception:
                pass
            try:
                await bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=streaming_msg_id[0],
                    text=text[:4096],
                )
            except Exception as e:
                logging.error(f"TG edit Error: {e}")
        else:
            try:
                await bot.send_message(
                    message.chat.id, md,
                    parse_mode="Markdown",
                    reply_to_message_id=reply_to,
                )
                return
            except Exception:
                pass
            try:
                await bot.send_message(
                    message.chat.id, text[:4096],
                    reply_to_message_id=reply_to,
                )
            except Exception as e:
                logging.error(f"TG send Error: {e}")

    async def tg_updater(text, is_final=False):
        if is_final:
            await _send_final(text)
        else:
            if streaming_msg_id[0] is None:
                try:
                    sent = await bot.send_message(
                        message.chat.id, text[:4096],
                        reply_to_message_id=reply_to,
                    )
                    streaming_msg_id[0] = sent.message_id
                except Exception as e:
                    logging.error(f"TG stream send Error: {e}")
            else:
                try:
                    await bot.edit_message_text(
                        chat_id=message.chat.id,
                        message_id=streaming_msg_id[0],
                        text=text[:4096],
                    )
                except Exception:
                    pass
    return tg_updater

# ─── Обработчики команд ───────────────────────────────────────────────────────

@dp.message(Command("memorize"))
async def cmd_memorize(message: types.Message, bot: Bot):
    if not is_allowed(message.from_user.id): return
    await message.answer("🧠 Запущен анализ краткосрочной памяти...")
    prompt = "ПРИНУДИТЕЛЬНАЯ ИНСТРУКЦИЯ: Изучи наш последний диалог и сохрани факты..."
    await agent.run_agent(str(message.from_user.id), prompt, source_channel="Telegram", tg_update_callback=get_tg_updater(message, bot), bot_instance=bot)

@dp.message(Command("screenshot"))
async def cmd_screenshot(message: types.Message, bot: Bot):
    if not is_allowed(message.from_user.id): return
    status_msg = await message.answer("📸 Делаю скриншот...")
    result = await tools.take_screenshot()
    try:
        await bot.delete_message(message.chat.id, status_msg.message_id)
    except Exception:
        pass
    if result.startswith("Ошибка"):
        await message.answer(result)
        return
    try:
        photo = FSInputFile(result)
        await bot.send_photo(message.chat.id, photo)
    except Exception as e:
        await message.answer(f"Не удалось отправить файл: {e}")

@dp.message(Command("clear"))
async def cmd_reset(message: types.Message):
    if not is_allowed(message.from_user.id): return
    db.clear_history(str(message.from_user.id))
    await message.answer("🧹 История сессии очищена.")

@dp.message(Command("restart"))
async def cmd_restart(message: types.Message, bot: Bot):
    """
    Принудительный перезапуск процесса бота через os.execv.
    Работает даже если агент завис — мы не ждём завершения задач,
    а сразу заменяем текущий процесс новым.
    После перезапуска сообщение "Перезапускаю..." автоматически обновится.
    """
    if not is_allowed(message.from_user.id): return

    logging.warning("🔄 Получена команда /restart — перезапускаю процесс...")
    try:
        sent = await message.answer("🔄 Перезапускаю бота... Подождите несколько секунд.")
        _save_restart_pending(chat_id=sent.chat.id, message_id=sent.message_id)
        try:
            await bot.session.close()
        except Exception:
            pass
    except Exception:
        pass

    os.execv(sys.executable, [sys.executable] + sys.argv)

@dp.message(Command("shutdown"))
async def cmd_shutdown(message: types.Message, bot: Bot):
    """Немедленно завершает процесс через os._exit(0) — работает даже при зависшем агенте."""
    if not is_allowed(message.from_user.id): return

    logging.warning("⏻ Получена команда /shutdown — выключаю процесс...")
    try:
        await message.answer("⏻ Выключаюсь...")
        await bot.session.close()
    except Exception:
        pass

    os._exit(0)

# ─── Обработчики сообщений ────────────────────────────────────────────────────

@dp.message(F.text)
async def handle_text(message: types.Message, bot: Bot):
    if not is_allowed(message.from_user.id): return
    await agent.run_agent(str(message.from_user.id), message.text, source_channel="Telegram", tg_update_callback=get_tg_updater(message, bot), bot_instance=bot)

@dp.message(F.photo | F.document)
async def handle_files(message: types.Message, bot: Bot):
    if not is_allowed(message.from_user.id): return

    file_id = message.photo[-1].file_id if message.photo else message.document.file_id
    file_info = await bot.get_file(file_id)
    downloaded_file = await bot.download_file(file_info.file_path)

    orig_name = message.document.file_name if message.document else "image.jpg"
    tmp_path = os.path.join(tempfile.gettempdir(), orig_name)
    with open(tmp_path, 'wb') as f:
        f.write(downloaded_file.read())

    caption_text = message.caption or "Опиши файл"
    ext = orig_name.lower().split('.')[-1]
    content = [{"type": "text", "text": caption_text}]

    if ext in ('docx', 'doc', 'xlsx', 'xls'):
        # Конвертируем офисные документы в PDF и отдаём агенту путь
        pdf_path = await tools.convert_to_pdf(tmp_path, orig_name)
        if pdf_path:
            with open(pdf_path, 'rb') as pdf_file:
                b64 = base64.b64encode(pdf_file.read()).decode('utf-8')
            content.append({"type": "image_url", "image_url": {"url": f"data:application/pdf;base64,{b64}"}})
            os.remove(pdf_path)
        else:
            # Если конвертация не удалась — передаём путь к оригиналу
            content[0]["text"] += f"\nФайл сохранён по пути: {tmp_path}"
    elif message.photo or ext in ('jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp'):
        with open(tmp_path, 'rb') as img_file:
            b64 = base64.b64encode(img_file.read()).decode('utf-8')
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
    else:
        # Прочие файлы (txt, pdf, zip и т.д.) — передаём агенту путь к файлу на диске
        content[0]["text"] += f"\nФайл '{orig_name}' сохранён по пути: {tmp_path}\nДля чтения текстового файла используй file_operation(read)."

    await agent.run_agent(str(message.from_user.id), content, source_channel="Telegram",
                          tg_update_callback=get_tg_updater(message, bot), bot_instance=bot)