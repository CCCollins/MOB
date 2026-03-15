import argparse
import sys
import os
import logging

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

from config.settings import get_config

def main():
    parser = argparse.ArgumentParser(description="Militech Open Bot")
    parser.add_argument("--headless", action="store_true", help="Запуск без графического интерфейса (для серверов)")
    args = parser.parse_args()

    # Настройка логов
    log_level = get_config("log_level") or "INFO"
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    if args.headless:
        logging.info("🚀 Запуск в Headless-режиме (без GUI)...")
        import asyncio
        from core.bot_runner import start_bot
        try:
            asyncio.run(start_bot())
        except KeyboardInterrupt:
            logging.info("Остановка бота...")
    else:
        try:
            from interfaces.gui_app import AgentGUI
            app = AgentGUI()
            app.mainloop()
        except ImportError as e:
            logging.error(f"Не удалось запустить GUI: {e}")
            logging.info("Попробуйте запустить с флагом --headless")
            sys.exit(1)

if __name__ == "__main__":
    main()