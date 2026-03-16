import argparse
import sys
import os
import logging

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

from config.settings import get_config, save_all

def run_interactive_setup():
    print("\n=====================================================")
    print("⚙️ Интерактивная настройка бота (нажмите Enter для пропуска)")
    print("=====================================================")
    
    PROMPTS = {
        "TELEGRAM_TOKEN": "Telegram Bot Token",
        "ALLOWED_TELEGRAM_IDS": "Разрешенные Telegram ID (через запятую)",
        "OPENROUTER_API_KEY": "OpenRouter API Key",
        "BRAVE_API_KEY": "Brave Search API Key",
        "DYNAMICPDF_API_KEY": "DynamicPDF API Key",
        "CHECKO_API_KEY": "Checko API Key",
        "PROXY_URL": "Proxy URL (http://...)",
        "model_orchestrator": "Оркестратор (управление ОС и задачами)",
        "model_chat": "Чат-модель (общение и генерация текста)",
        "model_expert": "Эксперт-модель (написание кода)",
        "max_iterations": "Максимальное число итераций",
        "history_limit": "Лимит истории сообщений",
        "bg_interval": "Интервал фоновых пробуждений (в секундах)",
        "bg_autostart": "Запускать фон при старте (True/False)",
        "keep_chain": "Цепочка рассуждений (True/False)",
        "log_level": "Уровень логирования (INFO/DEBUG/WARNING/ERROR)",
        "work_dir": "Рабочая папка (путь)",
    }
    
    updates = {}
    for key, desc in PROMPTS.items():
        current_val = get_config(key)
        
        display_val = str(current_val)
        if current_val and any(x in key for x in ["TOKEN", "KEY", "PROXY"]):
            display_val = f"{display_val[:5]}...{display_val[-4:]}" if len(display_val) > 8 else "***"
        elif current_val == "":
            display_val = "не задано"
        
        prompt_str = f"{desc} [{display_val}]: "
        user_input = input(prompt_str).strip()
        
        if user_input:
            if key in ["bg_autostart", "keep_chain"]:
                updates[key] = user_input.lower() in ["true", "1", "yes", "y", "да", "t"]
            elif key in ["max_iterations", "history_limit", "bg_interval"]:
                try:
                    updates[key] = int(user_input)
                except ValueError:
                    print(f"⚠️ Ошибка ввода для {key}. Ожидалось число. Настройка пропущена.")
            else:
                updates[key] = user_input

    if updates:
        save_all(updates)
        print("\n✅ Настройки успешно сохранены!\n")
    else:
        print("\nℹ️ Изменений не внесено.\n")

def main():
    parser = argparse.ArgumentParser(description="Militech Open Bot")
    parser.add_argument("--headless", action="store_true", help="Запуск без графического интерфейса (для серверов)")
    parser.add_argument("--setup", action="store_true", help="Запустить интерактивную настройку в терминале")
    parser.add_argument("--set", nargs=2, metavar=('KEY', 'VALUE'), action='append', help="Установить настройку напрямую (например: --set TELEGRAM_TOKEN 12345)")
    args = parser.parse_args()

    if args.set:
        updates = {k: v for k, v in args.set}
        save_all(updates)
        print(f"✅ Настройки успешно сохранены: {list(updates.keys())}")
        if not args.headless and not args.setup:
            sys.exit(0)

    if args.setup:
        run_interactive_setup()
        if not args.headless:
            sys.exit(0)

    log_level = get_config("log_level") or "INFO"
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    if args.headless:
        token = get_config("TELEGRAM_TOKEN")
        if not token:
            run_interactive_setup()

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