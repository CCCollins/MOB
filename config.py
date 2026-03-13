import os
import json
from dotenv import load_dotenv, set_key

ENV_FILE = ".env"
SETTINGS_FILE = "settings.json"

def init_configs():
    if not os.path.exists(ENV_FILE):
        with open(ENV_FILE, "w") as f:
            f.write("TELEGRAM_TOKEN=\nALLOWED_TELEGRAM_IDS=\nOPENROUTER_API_KEY=\nBRAVE_API_KEY=\nDYNAMICPDF_API_KEY=\n")
    if not os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "w") as f:
            json.dump({
                "bg_interval": 30,
                "max_iterations": 10,
                "log_level": "INFO",
                "model_main": "google/gemini-3-flash-preview",
                "model_expert": "anthropic/claude-haiku-4.5"
            }, f, indent=4)

init_configs()
load_dotenv(ENV_FILE)

def get_env(key):
    return os.getenv(key, "")

def set_env(key, value):
    set_key(ENV_FILE, key, value)
    os.environ[key] = value

def get_settings():
    try:
        with open(SETTINGS_FILE, "r") as f: return json.load(f)
    except: return {}

def save_settings(data):
    with open(SETTINGS_FILE, "w") as f: json.dump(data, f, indent=4)