# Militech Open Bot

Автономный ИИ-агент (Оркестратор), способный взаимодействовать с системой пользователя, искать информацию в интернете, читать веб-страницы через встроенный headless-браузер, работать с файлами и выполнять фоновые задачи — через графический интерфейс или в скрытом (Headless) режиме.

## Структура проекта

```
MOB/
├── run.py                  — точка входа (GUI или Headless)
├── config/
│   └── settings.py         — конфигурация (хранится в зашифрованном config.mobcfg)
├── core/
│   ├── agent.py            — ИИ-агент, цикл итераций, диспетчер инструментов
│   ├── bot_runner.py       — запуск Telegram polling + фоновые задачи
│   ├── database.py         — история чата и долгосрочная память (SQLite)
│   └── tools.py            — инструменты: терминал, браузер, мышь, скриншоты, поиск
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
Скрипт автоматически установит все зависимости, включая Playwright и Chromium для headless-браузера.
*(Для Android GUI не поддерживается напрямую, используйте режим `--headless`. Headless-браузер на Android недоступен.)*

**Windows**
```bash
pip install -r requirements.txt
playwright install chromium
python run.py
```

## Headless-режим (сервер и Android)

```bash
python run.py --headless
```

В этом режиме графическое окно не создаётся, бот управляется только через Telegram. Инструменты GUI ОС (мышь, скриншоты) автоматически отключаются на серверах, но **продолжают работать на Android** (команды перенаправляются в `su -c` или `adb shell`). Headless-браузер работает на серверах без дисплея.

**Интерактивная настройка в терминале:**
При первом запуске `run.py --headless` без токена скрипт предложит ввести параметры прямо в консоли.
Принудительно вызвать меню настройки повторно:
```bash
python run.py --setup
```

Установить параметры напрямую (удобно для автоматизации):
```bash
python run.py --set TELEGRAM_TOKEN "ваш_токен" --set ALLOWED_TELEGRAM_IDS "12345678"
```

## Инструменты агента

Агент управляет системой через набор встроенных инструментов:

| Инструмент | Описание |
|---|---|
| `execute_terminal` | Выполнение команд ОС и скриптов |
| `web_search` | Поиск через Brave Search API |
| `fetch_url` | Чтение страницы: сначала HTTP, при неудаче — headless Chromium |
| `browser_page` | Явный headless Chromium (JS-сайты, скриншот страницы, CSS-селектор) |
| `open_url` | Открыть ссылку в браузере пользователя |
| `file_operation` | Чтение и запись файлов |
| `memory_operation` | Долгосрочная ассоциативная память (сохранить / найти / забыть) |
| `take_screenshot` | Скриншот экрана |
| `analyze_screenshot` | Анализ скриншота через Vision-модель |
| `smart_click` | Умный клик по элементу через Vision |
| `click_mouse` / `type_text` / `press_key` / `hotkey` | Управление мышью и клавиатурой |
| `send_file` | Отправить файл пользователю (Telegram или GUI) |
| `ask_chat_model` | Делегировать генерацию текста чат-модели |
| `delegate_task_to_expert` | Делегировать написание кода эксперт-модели |
| `send_telegram_message` | Инициировать сообщение в Telegram (фоновый режим) |
| `checko_api` | Поиск компаний и ИП (Checko API) |

**Работа с PDF:** при первом запуске в папке конфига автоматически создаётся скрипт `read_pdf.py` с поддержкой OCR. Агент использует его через `execute_terminal`:
```bash
python3 read_pdf.py document.pdf            # обычное извлечение текста
python3 read_pdf.py document.pdf --ocr      # принудительный OCR (сканы)
python3 read_pdf.py document.pdf --pages 1-3,5  # конкретные страницы
```
Для OCR требуется установленный [Tesseract](https://github.com/UB-Mannheim/tesseract/wiki) с языковым пакетом `rus`.

## Настройки ролей ИИ и конфигурация

Конфигурация построена на 3-уровневой архитектуре моделей:

| Роль | По умолчанию | Описание |
|---|---|---|
| **Оркестратор** | `anthropic/claude-haiku-4.5` | Управляет ОС, принимает решения, вызывает инструменты, анализирует скриншоты. Требует Vision. |
| **Чат / Текст** | `google/gemini-3-flash-preview` | Быстрая модель для генерации текстов, перевода и общения. |
| **Эксперт** | `qwen/qwen3-coder-plus` | Вызывается Оркестратором для сложного программного кода. |

Поддерживаются локальные модели через LM Studio или любой OpenAI-совместимый сервер — укажите Base URL в настройках. При использовании локального API контекст автоматически обрезается по параметру **Токены** (LOCAL_CONTEXT_SIZE).

**Остальные параметры:**

| Параметр | Описание |
|---|---|
| Telegram Token | Токен бота от @BotFather |
| Разрешённые TG ID | ID пользователей через запятую |
| OpenRouter API Key | Ключ для доступа к моделям |
| Base URL | URL локального сервера (LM Studio, Ollama и др.) |
| Brave Search API Key | Ключ для веб-поиска |
| Checko API Key | Ключ для поиска контрагентов (опционально) |
| DynamicPDF API Key | Конвертация docx/xlsx в PDF (опционально) |
| Proxy | HTTP/SOCKS прокси (опционально) |
| Рабочая папка | Папка по умолчанию для всех создаваемых файлов |
| Токены (LOCAL_CONTEXT_SIZE) | Лимит контекста для локальных моделей |

Команды в Telegram: `/clear`, `/memorize`, `/screenshot`, `/update`, `/restart`, `/shutdown`.

## Сборка (PyInstaller)

```bash
pyinstaller MOB.spec          # обычная версия
pyinstaller MOB_Portable.spec # portable-версия (данные рядом с exe)
```

Готовая portable-папка `dist/MOB_Portable/` хранит все данные в локальной папке `data/`.

> **Примечание:** Playwright (headless-браузер) и Tesseract (OCR) не упаковываются в exe автоматически. После установки собранного приложения на новой машине нужно выполнить `playwright install chromium` и установить Tesseract отдельно.