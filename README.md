# Militech Open Bot

Автономный ИИ-агент (Оркестратор), способный взаимодействовать с системой пользователя, искать информацию в интернете и выполнять фоновые задачи через графический интерфейс или в скрытом (Headless) режиме.

## Структура проекта

```
MOB/
├── run.py                  — точка входа (GUI или Headless)
├── config/
│   └── settings.py         — конфигурация (хранится в зашифрованном config.mobcfg)
├── core/
│   ├── agent.py            — ИИ-агент, цикл итераций, инструменты
│   ├── bot_runner.py       — запуск Telegram polling + фоновые задачи
│   ├── database.py         — история чата и долгосрочная память (SQLite)
│   └── tools.py            — инструменты ОС: терминал, мышь, скриншоты, поиск
├── interfaces/
│   ├── gui_app.py          — графический интерфейс (customtkinter)
│   └── telegram_app.py     — Telegram-бот (aiogram)
├── requirements.txt
├── install_linux.sh
├── MOB.spec                — сборка обычной версии (PyInstaller)
└── MOB_Portable.spec       — сборка portable-версии (PyInstaller)
```

## Требования

- Python **3.10+**
- Работает на Windows, macOS, Linux (X11 и Wayland), а также на Android (через Termux, поддержка Root и ADB).
- API-ключи: [OpenRouter](https://openrouter.ai/settings/keys) (обязательно), [Brave Search](https://api-dashboard.search.brave.com/app/keys) (для поиска), [Telegram Bot Token](https://t.me/BotFather) (для Telegram)

## Установка и запуск

**Linux / Android (Termux)**
```bash
chmod +x install_linux.sh
./install_linux.sh
./run.sh
```
*(Для Android GUI не поддерживается напрямую, используйте режим `--headless` см. ниже).*

**Windows**
```bash
pip install -r requirements.txt
python run.py
```

## Headless-режим (сервер и Android)

```bash
python run.py --headless
```

В этом режиме графическое окно не создается, а бот доступен для управления только через Telegram. Инструменты GUI ОС (мышь, скриншоты) автоматически отключаются на серверах, но **продолжают работать на Android** (скрипт автоматически перенаправляет их в команды `su -c` или `adb shell`).

**Интерактивная настройка в терминале:**
При самом первом запуске `run.py --headless` скрипт обнаружит, что токена нет, и автоматически предложит вам ввести все необходимые параметры прямо в консоли.
Чтобы принудительно вызвать это меню настройки повторно, используйте команду:
```bash
python run.py --setup
```

Также вы можете менять любые параметры напрямую из терминала аргументом `--set` (удобно для скриптов автоматизации):
```bash
python run.py --set TELEGRAM_TOKEN "ваш_токен" --set ALLOWED_TELEGRAM_IDS "12345678"
```

## Настройки ролей ИИ и Конфигурация

Конфигурация бота построена на 3-уровневой архитектуре моделей:

| Роль | По умолчанию | Описание |
|---|---|---|
| **Оркестратор** | `anthropic/claude-haiku-4.5` | Управляет всей ОС, принимает решения, вызывает инструменты, анализирует скриншоты. Требует поддержки мультимодальности (Vision). |
| **Чат / Текст** | `google/gemini-3-flash-preview` | Быстрая и дешёвая модель для генерации больших текстов, перевода и простого общения. |
| **Эксперт** | `qwen/qwen3-coder-plus` | Вызывается Оркестратором исключительно для генерации сложного программного кода. |

**Остальные параметры:**

| Параметр | Описание |
|---|---|
| Telegram Token | Токен бота от @BotFather |
| Разрешённые TG ID | ID пользователей через запятую |
| OpenRouter API Key | Ключ для доступа к моделям |
| Brave Search API Key | Ключ для веб-поиска |
| Checko API Key | Ключ для поиска контрагентов (опционально) |
| Proxy | HTTP/SOCKS прокси (опционально) |
| Рабочая папка | Папка по умолчанию для всех сохраняемых файлов |

Команды чата в Telegram: `/clear`, `/memorize`, `/screenshot`, `/restart`, `/shutdown`.

## Portable-версия

Соберите через PyInstaller: `pyinstaller MOB_Portable.spec`.
Готовая папка `dist/MOB_Portable/` хранит все данные в локальной папке `data/`.