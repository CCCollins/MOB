import os
import json
import platform
import sys
import hashlib
import base64

# ── Определение режима и директорий ──────────────────────────────────────────

def _is_portable() -> bool:
    return os.path.isdir(os.path.join(_get_exe_dir(), "data"))

def _get_exe_dir() -> str:
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.abspath(os.path.dirname(sys.argv[0]))

def get_config_dir():
    if _is_portable():
        d = os.path.join(_get_exe_dir(), "data")
    elif platform.system() == "Windows":
        d = os.path.join(os.getenv("APPDATA", os.path.expanduser("~")), "MOB")
    elif platform.system() == "Darwin":
        d = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "MOB")
    else:
        d = os.path.join(os.path.expanduser("~"), ".config", "MOB")
    os.makedirs(d, exist_ok=True)
    return d

# ── Шифрование: машинный ключ (без ручного пароля) ───────────────────────────

_MAGIC = b"MOB\x01"

def _machine_key() -> bytes:
    """Детерминированный ключ на основе машинных идентификаторов.
    Не требует пароля пользователя — файл читается только на том же ПК."""
    parts = [
        platform.node(),               # имя хоста
        str(os.path.expanduser("~")),  # домашняя директория
        platform.system(),
        platform.machine(),
    ]
    # На Windows добавляем MachineGuid из реестра если доступен
    if platform.system() == "Windows":
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                 r"SOFTWARE\Microsoft\Cryptography")
            guid, _ = winreg.QueryValueEx(key, "MachineGuid")
            parts.append(guid)
        except Exception:
            pass
    seed = "|".join(parts).encode("utf-8")
    # PBKDF2 с фиксированной солью (публичной) — безопасность обеспечивается
    # уникальностью машинных данных, а не секретностью соли
    dk = hashlib.pbkdf2_hmac("sha256", seed,
                              b"MOB-machine-salt-v1", iterations=200_000, dklen=32)
    return base64.urlsafe_b64encode(dk)

def _encrypt(data: str) -> bytes:
    from cryptography.fernet import Fernet
    return _MAGIC + Fernet(_machine_key()).encrypt(data.encode("utf-8"))

def _decrypt(raw: bytes) -> str:
    from cryptography.fernet import Fernet, InvalidToken
    if not raw.startswith(_MAGIC):
        raise ValueError("Неверный формат файла конфига.")
    try:
        return Fernet(_machine_key()).decrypt(raw[len(_MAGIC):]).decode("utf-8")
    except InvalidToken:
        raise ValueError("Не удалось расшифровать конфиг (другая машина или повреждён файл).")

# ── Пути к файлам конфига ─────────────────────────────────────────────────────

CONFIG_FILE   = os.path.join(get_config_dir(), "config.mobcfg")

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
    "keep_chain": False,
    "model_main": "google/gemini-3-flash-preview",
    "model_expert": "qwen/qwen3-coder-plus",
    "work_dir": "",
}

# ── Чтение / запись ───────────────────────────────────────────────────────────

def _read_raw() -> dict:
    """Читает конфиг из зашифрованного .mobcfg файла."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "rb") as f:
                return json.loads(_decrypt(f.read()))
        except Exception:
            pass
    return {}

def _write_raw(data: dict):
    """Записывает конфиг в зашифрованный .mobcfg файл."""
    with open(CONFIG_FILE, "wb") as f:
        f.write(_encrypt(json.dumps(data, indent=4, ensure_ascii=False)))

def init_configs():
    if not os.path.exists(CONFIG_FILE):
        _write_raw(DEFAULT_CONFIG.copy())

init_configs()

def get_config(key):
    try:
        data = _read_raw()
        return data.get(key, DEFAULT_CONFIG.get(key, ""))
    except Exception:
        return DEFAULT_CONFIG.get(key, "")

def save_all(data: dict):
    try:
        current = _read_raw()
    except Exception:
        current = DEFAULT_CONFIG.copy()
    current.update(data)
    _write_raw(current)