import os
import json
import platform

def get_config_dir():
    if platform.system() == "Windows":
        base = os.getenv("APPDATA", os.path.expanduser("~"))
    elif platform.system() == "Darwin":
        base = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    else:
        base = os.path.join(os.path.expanduser("~"), ".config")
    
    d = os.path.join(base, "MOB")
    os.makedirs(d, exist_ok=True)
    return d

CONFIG_FILE = os.path.join(get_config_dir(), "config.json")

DEFAULT_CONFIG = {
    "TELEGRAM_TOKEN": "",
    "ALLOWED_TELEGRAM_IDS": "",
    "OPENROUTER_API_KEY": "",
    "BRAVE_API_KEY": "",
    "DYNAMICPDF_API_KEY": "",
    "PROXY_URL": "",
    "bg_interval": 28800,
    "bg_autostart": False,
    "max_iterations": 15,
    "history_limit": 40,
    "log_level": "INFO",
    "model_main": "google/gemini-3-flash-preview",
    "model_expert": "anthropic/claude-haiku-4.5",
    "work_dir": ""
}

def init_configs():
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, indent=4)

init_configs()

def get_config(key):
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get(key, DEFAULT_CONFIG.get(key, ""))
    except Exception:
        return DEFAULT_CONFIG.get(key, "")

def save_all(data):
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            current = json.load(f)
    except Exception:
        current = DEFAULT_CONFIG.copy()
        
    current.update(data)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(current, f, indent=4)
