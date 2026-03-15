import asyncio
import logging
from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from config.settings import get_config
import interfaces.telegram_app as telegram_app
import core.agent as agent

async def start_bot(bot_provided=None):
    """Единая точка запуска асинхронных задач бота (Telegram Polling + Фоновые таски)."""
    token = get_config("TELEGRAM_TOKEN").strip()
    proxy = get_config("PROXY_URL").strip()
    
    if bot_provided is None:
        session = AiohttpSession(proxy=proxy) if proxy else None
        try:
            bot = Bot(token=token, session=session) if token else None
        except Exception as e:
            logging.warning(f"⚠️ Ошибка создания Telegram Bot (Проверьте токен/прокси): {e}")
            bot = None
    else:
        bot = bot_provided

    bg_autostart = get_config("bg_autostart")

    async def bg_worker():
        interval = get_config("bg_interval") or 28800
        if bg_autostart:
            logging.info("🔄 Фоновая активность при старте включена — первый запуск через 5с.")
            await asyncio.sleep(5)
        else:
            logging.info(f"💤 Фоновая активность отключена — первое пробуждение через {interval // 3600}ч {(interval % 3600) // 60}м.")
            await asyncio.sleep(interval)
            
        while True:
            logging.info("🌅 Фоновое пробуждение агента — начало...")
            t_start = asyncio.get_event_loop().time()
            await agent.run_agent("GUI_USER", "[СИСТЕМА: ФОНОВОЕ ПРОБУЖДЕНИЕ. Проверь логи, задачи, процессы. Подумай, что бы ты хотел сделать?]", is_background=True, bot_instance=bot)
            elapsed = asyncio.get_event_loop().time() - t_start
            logging.info(f"✅ Фоновое пробуждение завершено за {elapsed:.1f}с.")
            
            interval = get_config("bg_interval") or 28800
            logging.info(f"💤 Следующее пробуждение через {interval // 3600}ч {(interval % 3600) // 60}м.")
            await asyncio.sleep(interval)

    asyncio.create_task(bg_worker())

    if bot is not None:
        await telegram_app.setup_bot_commands(bot)
        logging.info("✅ Telegram-клиент успешно запущен.")
        await telegram_app.dp.start_polling(bot, handle_signals=False)
    else:
        logging.info("✅ Агент запущен (режим работы без Telegram).")
        while True:
            await asyncio.sleep(3600)