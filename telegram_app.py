import os
import tempfile
import base64
import logging
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.methods import TelegramMethod
from aiogram.types import FSInputFile
from config import get_config
import agent
import database as db
import tools

class SendMessageDraft(TelegramMethod[bool]):
    __returning__ = bool
    __api_method__ = "sendMessageDraft"
    chat_id: int | str
    draft_id: int
    text: str
    parse_mode: str | None = None
    message_thread_id: int | None = None

dp = Dispatcher()

def is_allowed(user_id: int) -> bool:
    raw_ids = get_config("ALLOWED_TELEGRAM_IDS")
    if not raw_ids: return False
    allowed =[int(x.strip()) for x in raw_ids.split(",") if x.strip()]
    return user_id in allowed

def get_tg_updater(message: types.Message, bot: Bot):
    async def tg_updater(text, is_final=False):
        if is_final:
            try: await bot(SendMessageDraft(chat_id=message.chat.id, draft_id=message.message_id, text=" "))
            except: pass
            
            try: await bot.send_message(message.chat.id, text, parse_mode="Markdown")
            except:
                try: await bot.send_message(message.chat.id, text)
                except Exception as e: logging.error(f"TG Error: {e}")
        else:
            try:
                p_mode = "HTML" if "🛠" in text or "⏳" in text or "❌" in text else None
                await bot(SendMessageDraft(chat_id=message.chat.id, draft_id=message.message_id, text=text[:4096], parse_mode=p_mode))
            except: pass
    return tg_updater

@dp.message(Command("reset"))
async def cmd_reset(message: types.Message):
    if not is_allowed(message.from_user.id): return
    db.clear_history(str(message.from_user.id))
    await message.answer("🧹 История сессии очищена.")

@dp.message(Command("memorize"))
async def cmd_memorize(message: types.Message, bot: Bot):
    if not is_allowed(message.from_user.id): return
    await message.answer("🧠 Запущен анализ краткосрочной памяти...")
    prompt = "ПРИНУДИТЕЛЬНАЯ ИНСТРУКЦИЯ: Изучи наш последний диалог и сохрани факты..."
    await agent.run_agent(str(message.from_user.id), prompt, tg_update_callback=get_tg_updater(message, bot), bot_instance=bot)

@dp.message(Command("screenshot"))
async def cmd_screenshot(message: types.Message, bot: Bot):
    if not is_allowed(message.from_user.id): return
    await message.answer("📸 Делаю скриншот...")
    result = await tools.take_screenshot()
    if result.startswith("Ошибка"):
        await message.answer(result)
        return
    try:
        photo = FSInputFile(result)
        await bot.send_photo(message.chat.id, photo)
    except Exception as e:
        try:
            doc = FSInputFile(result)
            await bot.send_document(message.chat.id, doc)
        except Exception as e2:
            await message.answer(f"Не удалось отправить файл: {e2}")

@dp.message(F.text)
async def handle_text(message: types.Message, bot: Bot):
    if not is_allowed(message.from_user.id): return
    await agent.run_agent(str(message.from_user.id), message.text, tg_update_callback=get_tg_updater(message, bot), bot_instance=bot)

@dp.message(F.photo | F.document)
async def handle_files(message: types.Message, bot: Bot):
    if not is_allowed(message.from_user.id): return
    
    file_id = message.photo[-1].file_id if message.photo else message.document.file_id
    file_info = await bot.get_file(file_id)
    downloaded_file = await bot.download_file(file_info.file_path)
    
    orig_name = message.document.file_name if message.document else "image.jpg"
    tmp_path = os.path.join(tempfile.gettempdir(), orig_name)
    with open(tmp_path, 'wb') as f: f.write(downloaded_file.read())

    content =[{"type": "text", "text": message.caption or "Опиши файл"}]
    ext = orig_name.lower().split('.')[-1]
    
    if ext in['docx', 'doc', 'xlsx', 'xls']:
        pdf_path = await tools.convert_to_pdf(tmp_path, orig_name)
        if pdf_path:
            with open(pdf_path, 'rb') as pdf_file:
                content.append({"type": "image_url", "image_url": {"url": f"data:application/pdf;base64,{base64.b64encode(pdf_file.read()).decode('utf-8')}"}})
            os.remove(pdf_path)
        else: content[0]["text"] += f"\n[СИСТЕМА]: Сбой конвертации. Файл: {tmp_path}"
    elif message.photo or ext in['jpg', 'jpeg', 'png']:
        with open(tmp_path, 'rb') as img_file:
            content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64.b64encode(img_file.read()).decode('utf-8')}"}})
    else: content[0]["text"] += f"\n[СИСТЕМА]: Файл сохранен: {tmp_path.replace(chr(92), '/')}"

    await agent.run_agent(str(message.from_user.id), content, tg_update_callback=get_tg_updater(message, bot), bot_instance=bot)