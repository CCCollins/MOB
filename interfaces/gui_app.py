import os
import sys
import tkinter as tk
import customtkinter as ctk
import threading
import asyncio
import logging
import platform
import io
import mimetypes
import base64
import re
from tkinter import filedialog
import config.settings as config
import core.agent as agent
import core.tools as tools
import interfaces.telegram_app as telegram_app
from core.bot_runner import start_bot
from PIL import Image
import webbrowser

def resource_path(relative_path):
    try: base_path = sys._MEIPASS
    except Exception: base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def _win_cyrillic_bind(inner, copy_fn, paste_fn, cut_fn, sel_fn, undo_fn, redo_fn=None):
    if platform.system() != "Windows":
        return
    KEYCODE_MAP = {
        67: copy_fn,   
        86: paste_fn,  
        88: cut_fn,    
        65: sel_fn,    
        90: undo_fn,   
    }
    def _handler(e):
        if not (e.state & 0x4):  
            return
        if e.keysym not in ('??', '?'):  
            return
        fn = KEYCODE_MAP.get(e.keycode)
        if fn is None:
            return
        if e.keycode == 90 and redo_fn and (e.state & 0x1):  
            return redo_fn()
        return fn()
    inner.bind("<KeyPress>", _handler, add="+")

class GUILogHandler(logging.Handler):
    def __init__(self, textbox):
        super().__init__()
        self.textbox = textbox

    def emit(self, record):
        msg = self.format(record)
        def append():
            self.textbox.configure(state="normal")
            self.textbox.insert("end", msg + "\n")
            self.textbox.see("end")
            self.textbox.configure(state="disabled")
        self.textbox.after(0, append)

class AgentGUI(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        self.title("Militech Open Bot - Панель Управления")
        self.geometry("900x700")
        
        try:
            if platform.system() == "Windows": self.iconbitmap(resource_path("icon.ico"))
            else:
                _ico = Image.open(resource_path("icon.png"))
                import tkinter as _tk_ico
                _ico_tk = _tk_ico.PhotoImage(file=resource_path("icon.png")) if resource_path("icon.png").endswith(".png") else None
                if _ico_tk: self.wm_iconphoto(True, _ico_tk)
        except Exception: pass

        self.bot_thread = None
        self.async_loop = None
        self.is_running = False
        self.current_bot_textbox = None
        self.current_bot_frame = None

        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(fill="both", expand=True, padx=10, pady=10)
        self.tabview.add("Чат")
        self.tabview.add("Настройки")
        self.tabview.add("Логи")

        self.setup_settings_tab()
        self.setup_chat_tab()
        self.setup_logs_tab()

        self.btn_toggle = ctk.CTkButton(self, text="Запустить Агента", command=self.toggle_bot, fg_color="green", font=("Arial", 14, "bold"))
        self.btn_toggle.pack(pady=(10, 2))

        self.btn_kill = ctk.CTkButton(self, text="⏻ Принудительно выключить", command=self.force_quit, fg_color="#222", hover_color="#550000", font=("Arial", 11))
        self.btn_kill.pack(pady=(0, 10))

        if telegram_app.check_autostart():
            logging.info("🔄 Обнаружен флаг автозапуска — запускаю агента автоматически...")
            self.after(500, self.toggle_bot)

    def setup_settings_tab(self):
        tab_frame = self.tabview.tab("Настройки")
        tab = ctk.CTkScrollableFrame(tab_frame, fg_color="transparent")
        tab.pack(fill="both", expand=True)
        self.entries = {}
        tab.grid_columnconfigure(1, weight=1)

        F = ("Segoe UI", 12)
        F_BOLD = ("Segoe UI", 12, "bold")

        def _label(parent, text): return ctk.CTkLabel(parent, text=text, font=F_BOLD)

        KEY_LINKS = {
            "TELEGRAM_TOKEN":       ("Telegram Bot Token",   "https://telegram.me/BotFather"),
            "ALLOWED_TELEGRAM_IDS": ("Разрешенные TG ID",    "https://tg-user.id/"),
            "OPENROUTER_API_KEY":   ("OpenRouter API Key",   "https://openrouter.ai/settings/keys"),
            "OPENAI_BASE_URL":      ("API Base URL", "https://www.token-calculator.com/blog/llm-api-reference-base-urls-model-ids-2025"),
            "BRAVE_API_KEY":        ("Brave Search API Key", "https://api-dashboard.search.brave.com/app/keys"),
            "DYNAMICPDF_API_KEY":   ("DynamicPDF API Key",   "https://dpdf.io/"),
            "CHECKO_API_KEY":       ("Checko API Key",       "https://checko.ru/integration/api"),
            "PROXY_URL":            ("Proxy (http://...)",   "https://proxy6.net/"),
        }

        def _make_link_label(parent, display_name, url):
            frame = tk.Frame(parent, bg="#2b2b2b")
            if url:
                icon = tk.Label(frame, text="↗", font=("Segoe UI", 10), fg="#5a9fd4", bg="#2b2b2b")
                icon.pack(side="left", padx=(0, 3))
                text_lbl = tk.Label(frame, text=display_name, font=("Segoe UI", 12, "bold"), fg="#5a9fd4", bg="#2b2b2b", cursor="hand2")
                text_lbl.pack(side="left")
                def _on_enter(_): text_lbl.configure(fg="#89c4f4"); icon.configure(fg="#89c4f4")
                def _on_leave(_): text_lbl.configure(fg="#5a9fd4"); icon.configure(fg="#5a9fd4")
                for w in (frame, icon, text_lbl):
                    w.bind("<Enter>", _on_enter)
                    w.bind("<Leave>", _on_leave)
                    w.bind("<Button-1>", lambda e, u=url: webbrowser.open(u))
            else:
                icon = tk.Label(frame, text="  ", font=("Segoe UI", 10), bg="#2b2b2b")
                icon.pack(side="left", padx=(0, 4))
                text_lbl = tk.Label(frame, text=display_name, font=("Segoe UI", 12, "bold"), fg="#dce4ee", bg="#2b2b2b")
                text_lbl.pack(side="left")
            return frame

        current_row = 0
        for key, (display_name, url) in KEY_LINKS.items():
            lbl = _make_link_label(tab, display_name, url)
            lbl.grid(row=current_row, column=0, padx=10, pady=5, sticky="w")

            is_secret = "TOKEN" in key or "KEY" in key or "PROXY" in key
            e = ctk.CTkEntry(tab, font=F, show="*" if is_secret else "")
            e.insert(0, config.get_config(key))
            e.grid(row=current_row, column=1, padx=(10, 0), pady=5, sticky="we")
            self._bind_entry(e)
            self.entries[key] = e

            if is_secret:
                btn = ctk.CTkButton(tab, text="👁", width=40, font=F, fg_color="#555", hover_color="#777", command=lambda ent=e: self.toggle_visibility(ent))
                btn.grid(row=current_row, column=2, padx=10, pady=5)
            current_row += 1

        _label(tab, "Роли и Модели ИИ:").grid(row=current_row, column=0, padx=10, pady=5, sticky="nw")
        row_models = ctk.CTkFrame(tab, fg_color="transparent")
        row_models.grid(row=current_row, column=1, columnspan=2, sticky="we", padx=(10, 10), pady=5)
        
        LBL_W = 40
        
        lbl_orch = ctk.CTkLabel(row_models, text="Оркестр.:", font=F, width=LBL_W, anchor="e")
        lbl_orch.pack(side="left", padx=(0, 5))
        self.e_model_orchestrator = ctk.CTkEntry(row_models, font=F, width=50)
        self.e_model_orchestrator.insert(0, config.get_config("model_orchestrator"))
        self.e_model_orchestrator.pack(side="left", fill="x", expand=True, padx=(0, 15))
        self._bind_entry(self.e_model_orchestrator)
        
        lbl_chat = ctk.CTkLabel(row_models, text="Чат:", font=F, width=LBL_W, anchor="e")
        lbl_chat.pack(side="left", padx=(0, 5))
        self.e_model_chat = ctk.CTkEntry(row_models, font=F, width=50)
        self.e_model_chat.insert(0, config.get_config("model_chat"))
        self.e_model_chat.pack(side="left", fill="x", expand=True, padx=(0, 15))
        self._bind_entry(self.e_model_chat)
        
        lbl_exp = ctk.CTkLabel(row_models, text="Код:", font=F, width=LBL_W, anchor="e")
        lbl_exp.pack(side="left", padx=(0, 5))
        self.e_model_expert = ctk.CTkEntry(row_models, font=F, width=50)
        self.e_model_expert.insert(0, config.get_config("model_expert"))
        self.e_model_expert.pack(side="left", fill="x", expand=True, padx=(0, 0))
        self._bind_entry(self.e_model_expert)
        current_row += 1

        _label(tab, "Лимиты и Логи:").grid(row=current_row, column=0, padx=10, pady=5, sticky="w")
        row_limits = ctk.CTkFrame(tab, fg_color="transparent")
        row_limits.grid(row=current_row, column=1, columnspan=2, sticky="we", padx=(10, 0), pady=5)
        
        _label(row_limits, "Итераций:").pack(side="left", padx=(0, 5))
        self.e_max_iter = ctk.CTkEntry(row_limits, width=50, font=F)
        self.e_max_iter.insert(0, str(config.get_config("max_iterations") or 10))
        self.e_max_iter.pack(side="left", padx=(0, 15))
        self._bind_entry(self.e_max_iter)
        
        _label(row_limits, "История (сообщ.):").pack(side="left", padx=(0, 5))
        self.e_history_limit = ctk.CTkEntry(row_limits, width=50, font=F)
        self.e_history_limit.insert(0, str(config.get_config("history_limit") or 40))
        self.e_history_limit.pack(side="left", padx=(0, 15))
        self._bind_entry(self.e_history_limit)

        _label(row_limits, "Токены:").pack(side="left", padx=(0, 5))
        self.e_ctx_limit = ctk.CTkEntry(row_limits, width=60, font=F)
        self.e_ctx_limit.insert(0, str(config.get_config("LOCAL_CONTEXT_SIZE") or 4096))
        self.e_ctx_limit.pack(side="left", padx=(0, 15))
        self._bind_entry(self.e_ctx_limit)
        
        _label(row_limits, "Логи:").pack(side="left", padx=(0, 5))
        self.c_log = ctk.CTkComboBox(row_limits, values=["DEBUG", "INFO", "WARNING", "ERROR"], width=100, font=F)
        self.c_log.set(config.get_config("log_level") or "INFO")
        self.c_log.pack(side="left", padx=(0, 15))

        self._keep_chain_var = tk.BooleanVar(value=bool(config.get_config("keep_chain")))
        current_row += 1

        _label(tab, "Фоновая активность:").grid(row=current_row, column=0, padx=10, pady=5, sticky="w")
        frame_bg = ctk.CTkFrame(tab, fg_color="transparent")
        frame_bg.grid(row=current_row, column=1, columnspan=2, sticky="we", padx=(10, 0), pady=5)
        total_sec = config.get_config("bg_interval") or 28800
        self.e_bg_h = ctk.CTkEntry(frame_bg, width=40, font=F); self.e_bg_h.insert(0, str(total_sec // 3600)); self.e_bg_h.pack(side="left", padx=(0, 2)); self._bind_entry(self.e_bg_h)
        ctk.CTkLabel(frame_bg, text="ч", font=F).pack(side="left", padx=(0, 6))
        self.e_bg_m = ctk.CTkEntry(frame_bg, width=40, font=F); self.e_bg_m.insert(0, str((total_sec % 3600) // 60)); self.e_bg_m.pack(side="left", padx=(0, 2)); self._bind_entry(self.e_bg_m)
        ctk.CTkLabel(frame_bg, text="м", font=F).pack(side="left", padx=(0, 6))
        self.e_bg_s = ctk.CTkEntry(frame_bg, width=40, font=F); self.e_bg_s.insert(0, str(total_sec % 60)); self.e_bg_s.pack(side="left", padx=(0, 2)); self._bind_entry(self.e_bg_s)
        ctk.CTkLabel(frame_bg, text="с", font=F).pack(side="left", padx=(0, 15))
        self._bg_autostart_var = tk.BooleanVar(value=bool(config.get_config("bg_autostart")))
        ctk.CTkCheckBox(frame_bg, text="Проверять при старте", variable=self._bg_autostart_var, font=F).pack(side="left", padx=(0, 15))
        ctk.CTkCheckBox(frame_bg, text="Цепочка рассуждений", variable=self._keep_chain_var, font=F).pack(side="left")
        current_row += 1

        _label(tab, "Рабочая папка:").grid(row=current_row, column=0, padx=10, pady=5, sticky="w")
        self.e_work_dir = ctk.CTkEntry(tab, font=F); self.e_work_dir.insert(0, config.get_config("work_dir") or ""); self.e_work_dir.grid(row=current_row, column=1, padx=(10, 0), pady=5, sticky="we"); self._bind_entry(self.e_work_dir)
        def _browse_work_dir():
            d = filedialog.askdirectory(title="Выберите рабочую папку")
            if d: self.e_work_dir.delete(0, "end"); self.e_work_dir.insert(0, d)
        ctk.CTkButton(tab, text="📂", width=40, font=F, fg_color="#555", hover_color="#777", command=_browse_work_dir).grid(row=current_row, column=2, padx=10, pady=5)
        current_row += 1

        frame_actions = ctk.CTkFrame(tab, fg_color="transparent")
        frame_actions.grid(row=current_row, column=0, columnspan=3, pady=(20, 16))
        ctk.CTkButton(frame_actions, text="💾 Сохранить", font=F_BOLD, width=150,
                      command=self.save_configs).pack(side="left", padx=6)
        ctk.CTkButton(frame_actions, text="📤 Экспорт", font=F, width=120,
                      fg_color="#3a5a3a", hover_color="#4a7a4a",
                      command=self.export_config).pack(side="left", padx=6)
        ctk.CTkButton(frame_actions, text="📥 Импорт", font=F, width=120,
                      fg_color="#3a3a5a", hover_color="#4a4a7a",
                      command=self.import_config).pack(side="left", padx=6)
        ctk.CTkButton(frame_actions, text="🔴 Сброс", font=F, width=110,
                      fg_color="#5a2a2a", hover_color="#7a3a3a",
                      command=self.reset_configs).pack(side="left", padx=6)

    @staticmethod
    def _make_undo_funcs(inner):
        undo_stack, redo_stack, _last_saved = [], [], [""]

        def _snapshot():
            val = inner.get()
            if val != _last_saved[0]:
                undo_stack.append((_last_saved[0], inner.index("insert")))
                redo_stack.clear()
                _last_saved[0] = val

        def _undo(e=None):
            _snapshot()
            if not undo_stack: return "break"
            val, pos = undo_stack.pop()
            redo_stack.append((inner.get(), inner.index("insert")))
            _last_saved[0] = val
            inner.delete(0, "end"); inner.insert(0, val)
            try: inner.icursor(min(pos, len(val)))
            except: pass
            return "break"

        def _redo(e=None):
            if not redo_stack: return "break"
            val, pos = redo_stack.pop()
            undo_stack.append((inner.get(), inner.index("insert")))
            _last_saved[0] = val
            inner.delete(0, "end"); inner.insert(0, val)
            try: inner.icursor(min(pos, len(val)))
            except: pass
            return "break"

        def _select_all(e=None):
            inner.select_range(0, "end"); inner.icursor("end")
            return "break"

        def _copy(e=None):
            try: inner.clipboard_clear(); inner.clipboard_append(inner.selection_get())
            except: pass
            return "break"

        def _paste(e=None):
            try:
                _snapshot()
                text = inner.clipboard_get()
                try: inner.delete("sel.first", "sel.last")
                except: pass
                inner.insert("insert", text)
            except: pass
            return "break"

        def _cut(e=None):
            try:
                _snapshot()
                sel = inner.selection_get()
                inner.clipboard_clear(); inner.clipboard_append(sel)
                inner.delete("sel.first", "sel.last")
            except: pass
            return "break"

        return _snapshot, _undo, _redo, _select_all, _copy, _paste, _cut

    def _bind_entry(self, entry: ctk.CTkEntry):
        inner = entry._entry
        _snapshot, _undo, _redo, _sel, _copy, _paste, _cut = self._make_undo_funcs(inner)

        inner.bind("<KeyRelease>", lambda e: inner.after(10, _snapshot))

        mod = "Command" if platform.system() == "Darwin" else "Control"
        inner.bind(f"<{mod}-c>", _copy); inner.bind(f"<{mod}-C>", _copy)
        inner.bind(f"<{mod}-v>", _paste); inner.bind(f"<{mod}-V>", _paste)
        inner.bind(f"<{mod}-x>", _cut); inner.bind(f"<{mod}-X>", _cut)
        inner.bind(f"<{mod}-a>", _sel); inner.bind(f"<{mod}-A>", _sel)
        inner.bind(f"<{mod}-z>", _undo); inner.bind(f"<{mod}-Z>", _undo)
        inner.bind(f"<{mod}-Shift-z>", _redo); inner.bind(f"<{mod}-Shift-Z>", _redo)
        _win_cyrillic_bind(inner, _copy, _paste, _cut, _sel, _undo, _redo)

    def toggle_visibility(self, entry):
        entry.configure(show="" if entry.cget("show") == "*" else "*")

    def save_configs(self):
        data = {k: v.get().strip() for k, v in self.entries.items()}
        try: data["bg_interval"] = max(1, int(self.e_bg_h.get() or 0)*3600 + int(self.e_bg_m.get() or 0)*60 + int(self.e_bg_s.get() or 0))
        except ValueError: data["bg_interval"] = 28800
        data["bg_autostart"] = self._bg_autostart_var.get()
        data["max_iterations"] = int(self.e_max_iter.get() or 10)
        try: data["history_limit"] = max(4, int(self.e_history_limit.get() or 40))
        except ValueError: data["history_limit"] = 40
        try: data["LOCAL_CONTEXT_SIZE"] = int(self.e_ctx_limit.get() or 4096)
        except ValueError: data["LOCAL_CONTEXT_SIZE"] = 4096
        data["log_level"] = self.c_log.get()
        data["keep_chain"] = self._keep_chain_var.get()
        data["model_orchestrator"] = self.e_model_orchestrator.get().strip()
        data["model_chat"] = self.e_model_chat.get().strip()
        data["model_expert"] = self.e_model_expert.get().strip()
        data["work_dir"] = self.e_work_dir.get().strip()
        config.save_all(data)
        logging.getLogger().setLevel(data["log_level"])
        logging.info("Настройки сохранены.")

    def reset_configs(self):
        d = config.DEFAULT_CONFIG
        config.save_all(d)

        for key, entry in self.entries.items():
            entry.delete(0, "end")
            entry.insert(0, str(d.get(key, "")))

        for attr, cfg_key in[
            ("e_model_orchestrator", "model_orchestrator"), 
            ("e_model_chat", "model_chat"), 
            ("e_model_expert", "model_expert"),
            ("e_work_dir", "work_dir"),
        ]:
            w = getattr(self, attr); w.delete(0, "end"); w.insert(0, str(d.get(cfg_key, "")))

        t = int(d.get("bg_interval", 28800))
        for attr, val in[("e_bg_h", t // 3600), ("e_bg_m", (t % 3600) // 60), ("e_bg_s", t % 60)]:
            w = getattr(self, attr); w.delete(0, "end"); w.insert(0, str(val))

        self._bg_autostart_var.set(bool(d.get("bg_autostart", False)))
        self._keep_chain_var.set(bool(d.get("keep_chain", False)))
        self.e_max_iter.delete(0, "end"); self.e_max_iter.insert(0, str(d.get("max_iterations", 10)))
        self.e_history_limit.delete(0, "end"); self.e_history_limit.insert(0, str(d.get("history_limit", 40)))
        self.e_ctx_limit.delete(0, "end"); self.e_ctx_limit.insert(0, str(d.get("LOCAL_CONTEXT_SIZE", 4096)))
        self.c_log.set(d.get("log_level", "INFO"))

        logging.info("🔴 Настройки сброшены к значениям по умолчанию.")

    @staticmethod
    def _ask_password(title: str, confirm: bool = False) -> str | None:
        dlg = ctk.CTkToplevel()
        dlg.title(title)
        dlg.resizable(False, False)
        dlg.grab_set()
        dlg.lift()
        dlg.focus_force()
        dlg.geometry("380x" + ("200" if confirm else "160"))

        result = [None]

        ctk.CTkLabel(dlg, text="Пароль для шифрования:", font=("Segoe UI", 13)).pack(pady=(18, 4))
        e1 = ctk.CTkEntry(dlg, show="*", width=280, font=("Segoe UI", 13))
        e1.pack(pady=4)
        e1.focus()

        e2 = None
        if confirm:
            ctk.CTkLabel(dlg, text="Подтвердите пароль:", font=("Segoe UI", 13)).pack(pady=(6, 4))
            e2 = ctk.CTkEntry(dlg, show="*", width=280, font=("Segoe UI", 13))
            e2.pack(pady=4)

        err_lbl = ctk.CTkLabel(dlg, text="", font=("Segoe UI", 11), text_color="#ff6060")
        err_lbl.pack()

        def _ok(event=None):
            pwd = e1.get()
            if not pwd:
                err_lbl.configure(text="Пароль не может быть пустым.")
                return
            if confirm and e2 and e2.get() != pwd:
                err_lbl.configure(text="Пароли не совпадают.")
                return
            result[0] = pwd
            dlg.destroy()

        def _cancel(event=None):
            dlg.destroy()

        btn_frame = ctk.CTkFrame(dlg, fg_color="transparent")
        btn_frame.pack(pady=8)
        ctk.CTkButton(btn_frame, text="✓ OK", width=100, command=_ok).pack(side="left", padx=8)
        ctk.CTkButton(btn_frame, text="✕ Отмена", width=100, fg_color="#3a3a3a", hover_color="#550000", command=_cancel).pack(side="left", padx=8)
        e1.bind("<Return>", _ok)
        if e2: e2.bind("<Return>", _ok)
        dlg.bind("<Escape>", _cancel)
        dlg.wait_window()
        return result[0]

    @staticmethod
    def _derive_key(password: str, salt: bytes) -> bytes:
        import hashlib, base64 as _b64
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations=600_000, dklen=32)
        return _b64.urlsafe_b64encode(dk)

    def export_config(self):
        try:
            from cryptography.fernet import Fernet
        except ImportError:
            import tkinter.messagebox as mb
            mb.showerror("Ошибка", "Установите пакет cryptography:\npip install cryptography")
            return

        password = self._ask_password("Экспорт настроек", confirm=True)
        if not password:
            return

        path = filedialog.asksaveasfilename(
            title="Сохранить файл настроек",
            defaultextension=".mobcfg",
            filetypes=[("MOB Config", "*.mobcfg"), ("Все файлы", "*.*")]
        )
        if not path:
            return

        try:
            import json as _json
            raw = _json.dumps(config._read_raw(), indent=4, ensure_ascii=False)

            salt = os.urandom(32)
            key = self._derive_key(password, salt)
            token = Fernet(key).encrypt(raw.encode("utf-8"))

            magic = b"MOB\x01"
            with open(path, "wb") as f:
                f.write(magic + salt + token)

            logging.info(f"✅ Настройки экспортированы: {path}")
            import tkinter.messagebox as mb
            mb.showinfo("Экспорт", f"Настройки успешно экспортированы:\n{path}")
        except Exception as e:
            import tkinter.messagebox as mb
            mb.showerror("Ошибка экспорта", str(e))
            logging.error(f"Ошибка экспорта настроек: {e}")

    def import_config(self):
        try:
            from cryptography.fernet import Fernet, InvalidToken
        except ImportError:
            import tkinter.messagebox as mb
            mb.showerror("Ошибка", "Установите пакет cryptography:\npip install cryptography")
            return

        path = filedialog.askopenfilename(
            title="Открыть файл настроек",
            filetypes=[("MOB Config", "*.mobcfg"), ("Все файлы", "*.*")]
        )
        if not path:
            return

        password = self._ask_password("Импорт настроек", confirm=False)
        if not password:
            return

        try:
            import json as _json
            with open(path, "rb") as f:
                data = f.read()

            magic = b"MOB\x01"
            if not data.startswith(magic):
                raise ValueError("Файл не является корректным MOB-конфигом.")

            salt = data[4:36]
            token = data[36:]
            key = self._derive_key(password, salt)

            try:
                decrypted = Fernet(key).decrypt(token).decode("utf-8")
            except InvalidToken:
                import tkinter.messagebox as mb
                mb.showerror("Ошибка импорта", "Неверный пароль или файл повреждён.")
                return

            cfg = _json.loads(decrypted)
            config.save_all(cfg)

            for key_name, entry in self.entries.items():
                if key_name in cfg:
                    entry.delete(0, "end")
                    entry.insert(0, str(cfg[key_name]))

            for attr, cfg_key in[
                ("e_model_orchestrator", "model_orchestrator"), 
                ("e_model_chat", "model_chat"), 
                ("e_model_expert", "model_expert"),
                ("e_work_dir", "work_dir"),
            ]:
                if cfg_key in cfg:
                    w = getattr(self, attr)
                    w.delete(0, "end")
                    w.insert(0, str(cfg[cfg_key]))

            if "bg_interval" in cfg:
                t = int(cfg["bg_interval"])
                for attr, val in[("e_bg_h", t // 3600), ("e_bg_m", (t % 3600) // 60), ("e_bg_s", t % 60)]:
                    w = getattr(self, attr); w.delete(0, "end"); w.insert(0, str(val))
            if "bg_autostart" in cfg:
                self._bg_autostart_var.set(bool(cfg["bg_autostart"]))
            if "keep_chain" in cfg:
                self._keep_chain_var.set(bool(cfg["keep_chain"]))
            if "max_iterations" in cfg:
                self.e_max_iter.delete(0, "end"); self.e_max_iter.insert(0, str(cfg["max_iterations"]))
            if "history_limit" in cfg:
                self.e_history_limit.delete(0, "end"); self.e_history_limit.insert(0, str(cfg["history_limit"]))
            if "LOCAL_CONTEXT_SIZE" in cfg:
                self.e_ctx_limit.delete(0, "end"); self.e_ctx_limit.insert(0, str(cfg["LOCAL_CONTEXT_SIZE"]))
            if "log_level" in cfg:
                self.c_log.set(cfg["log_level"])

            logging.info(f"✅ Настройки импортированы из: {path}")
            import tkinter.messagebox as mb
            mb.showinfo("Импорт", "Настройки успешно импортированы и применены!")
        except Exception as e:
            import tkinter.messagebox as mb
            mb.showerror("Ошибка импорта", str(e))
            logging.error(f"Ошибка импорта настроек: {e}")

    def setup_chat_tab(self):
        tab = self.tabview.tab("Чат")
        self.chat_scroll = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        self.chat_scroll.pack(fill="both", expand=True, padx=5, pady=5)

        frame = ctk.CTkFrame(tab, fg_color="transparent")
        frame.pack(fill="x", padx=5, pady=5)

        def _make_icon_btn(parent, text, command, tooltip_text):
            btn = ctk.CTkButton(parent, text=text, width=40, height=40, font=("Segoe UI Emoji", 18), fg_color="transparent", hover_color="#3a3a3a", corner_radius=8, command=command)
            btn.pack(side="left", padx=2)
            return btn

        icon_frame = ctk.CTkFrame(frame, fg_color="transparent")
        icon_frame.pack(side="right", padx=(4, 0))

        def _show_commands_menu():
            menu = tk.Menu(self, tearoff=0, bg="#2b2b2b", fg="white", activebackground="#1f538d", activeforeground="white", font=("Segoe UI", 12), borderwidth=0)
            for cmd in telegram_app.BOT_COMMANDS:
                def _run_cmd(c=cmd.command):
                    self.msg_entry.delete("1.0", "end"); self.msg_entry.insert("1.0", f"/{c}"); self.msg_entry.focus(); self.after(50, self.send_gui_msg)
                menu.add_command(label=f"/{cmd.command}  —  {cmd.description}", command=_run_cmd)
            
            items_count = len(telegram_app.BOT_COMMANDS)
            est_height = items_count * 28 + 10
            est_width = 300
            
            btn_x = self._cmd_menu_btn.winfo_rootx()
            btn_y = self._cmd_menu_btn.winfo_rooty()
            btn_w = self._cmd_menu_btn.winfo_width()
            
            x = btn_x - est_width + btn_w
            y = btn_y - est_height
            
            menu.tk_popup(x, y)

        self._cmd_menu_btn = _make_icon_btn(icon_frame, "☰", _show_commands_menu, "Команды")
        _make_icon_btn(icon_frame, "📎", self.send_file_gui, "Прикрепить файл")
        _make_icon_btn(icon_frame, "➤", self.send_gui_msg,  "Отправить")

        self.msg_entry = ctk.CTkTextbox(frame, height=40, wrap="word", font=("Segoe UI", 13), border_width=1, corner_radius=8)
        self.msg_entry.pack(side="left", fill="x", expand=True, padx=(0, 4), pady=2)
        self._hide_scrollbar(self.msg_entry)
        self.msg_entry._textbox.configure(undo=True, maxundo=-1)

        inner = self.msg_entry._textbox

        def _on_copy(e=None):
            try: 
                self.clipboard_clear()
                self.clipboard_append(inner.selection_get())
            except Exception: pass
            return "break"

        def _on_paste(e=None):
            try:
                text_to_paste = self.clipboard_get()
                try: inner.delete("sel.first", "sel.last")
                except Exception: pass
                inner.insert("insert", text_to_paste)
            except Exception: pass
            return "break"

        def _on_cut(e=None):
            try:
                sel = inner.selection_get()
                self.clipboard_clear()
                self.clipboard_append(sel)
                inner.delete("sel.first", "sel.last")
            except Exception: pass
            return "break"

        def _on_select_all(e=None):
            inner.tag_add("sel", "1.0", "end")
            return "break"

        def _on_undo(e=None):
            try: inner.edit_undo()
            except Exception: pass
            return "break"

        def _on_backspace(e=None):
            try:
                inner.delete("sel.first", "sel.last")
                return "break"
            except Exception: pass
            inner.delete("insert-1c wordstart", "insert")
            return "break"

        def _on_delete(e=None):
            try:
                inner.delete("sel.first", "sel.last")
                return "break"
            except Exception: pass
            inner.delete("insert", "insert wordend")
            return "break"

        mod = "Command" if platform.system() == "Darwin" else "Control"
        def safe_bind(seq, func):
            try: inner.bind(seq, func)
            except tk.TclError: pass

        for k in['c', 'C', 'с', 'С', 'Cyrillic_es', 'cyrillic_es']: safe_bind(f"<{mod}-KeyPress-{k}>", _on_copy)
        for k in['v', 'V', 'м', 'М', 'Cyrillic_em', 'cyrillic_em']: safe_bind(f"<{mod}-KeyPress-{k}>", _on_paste)
        for k in['x', 'X', 'ч', 'Ч', 'Cyrillic_che', 'cyrillic_che']: safe_bind(f"<{mod}-KeyPress-{k}>", _on_cut)
        for k in['a', 'A', 'ф', 'Ф', 'Cyrillic_ef', 'cyrillic_ef']: safe_bind(f"<{mod}-KeyPress-{k}>", _on_select_all)
        for k in['z', 'Z', 'я', 'Я', 'Cyrillic_ya', 'cyrillic_ya']: safe_bind(f"<{mod}-KeyPress-{k}>", _on_undo)
        _win_cyrillic_bind(inner, _on_copy, _on_paste, _on_cut, _on_select_all, _on_undo)
        
        safe_bind(f"<{mod}-BackSpace>", _on_backspace)
        safe_bind(f"<{mod}-Delete>", _on_delete)

        def _resize_entry(e=None):
            lines = int(self.msg_entry._textbox.index("end-1c").split(".")[0])
            self.msg_entry.configure(height=max(40, min(lines * 22 + 10, 120)))
        
        def _entry_send(e):
            if e.state & 0x1: return
            self.send_gui_msg()
            return "break"

        self.msg_entry.bind("<Return>", _entry_send)
        self.msg_entry.bind("<KeyRelease>", _resize_entry)

    FONT_MAIN = ("Segoe UI", 13)
    FONT_BOLD = ("Segoe UI", 13, "bold")
    FONT_ITALIC = ("Segoe UI", 13, "italic")
    FONT_CODE = ("Consolas", 12)
    COLOR_CODE = "#e6db74"

    def _hide_scrollbar(self, tb):
        for _attr in ("_scrollbar", "_y_scrollbar", "_scrollbar_y"):
            _sb = getattr(tb, _attr, None)
            if _sb is not None:
                try: _sb.configure(width=0)
                except Exception: pass
                break

    def attach_copy_bindings(self, textbox):
        inner = textbox._textbox

        def _on_copy(e=None):
            try:
                self.clipboard_clear()
                self.clipboard_append(inner.selection_get())
            except Exception: pass
            return "break"

        def _on_select_all(e=None):
            try: inner.tag_add("sel", "1.0", "end")
            except Exception: pass
            return "break"

        mod = "Command" if platform.system() == "Darwin" else "Control"
        def safe_bind(seq, func):
            try: inner.bind(seq, func)
            except tk.TclError: pass

        for k in['c', 'C', 'с', 'С', 'Cyrillic_es', 'cyrillic_es']: safe_bind(f"<{mod}-KeyPress-{k}>", _on_copy)
        for k in['a', 'A', 'ф', 'Ф', 'Cyrillic_ef', 'cyrillic_ef']: safe_bind(f"<{mod}-KeyPress-{k}>", _on_select_all)
        _win_cyrillic_bind(inner, _on_copy, None, None, _on_select_all, None)

        menu = tk.Menu(self, tearoff=0, bg="#2b2b2b", fg="white", activebackground="#1f538d", activeforeground="white", borderwidth=0)
        menu.add_command(label="Копировать", command=_on_copy)

        def show_menu(event):
            menu.tk_popup(event.x_root, event.y_root)

        if platform.system() == "Darwin":
            textbox.bind("<Button-2>", show_menu)
            textbox.bind("<Control-Button-1>", show_menu)
        else:
            textbox.bind("<Button-3>", show_menu)

    def insert_markdown(self, tb, text):
        inner = tb._textbox
        inner.tag_config("bold", font=self.FONT_BOLD)
        inner.tag_config("italic", font=self.FONT_ITALIC)
        inner.tag_config("code", font=self.FONT_CODE, foreground=self.COLOR_CODE)
        inner.tag_config("normal", font=self.FONT_MAIN)
        inner.tag_config("link", font=self.FONT_MAIN, foreground="#4a9eff", underline=True)
        
        def _strip_inline(s):
            s = re.sub(r'\*\*(.+?)\*\*', r'\1', s)
            s = re.sub(r'__(.+?)__', r'\1', s)
            s = re.sub(r'\*(.+?)\*', r'\1', s)
            s = re.sub(r'_(.+?)_', r'\1', s)
            return s

        splitter = re.compile(
            r'('
            r'\[[^\]]*\]\(https?://[^\)\s]+\)'
            r'|```[\s\S]*?```'
            r'|`[^`\n]+`'
            r'|\*\*[^*\n]+\*\*'
            r'|__[^_\n]+__'
            r'|(?<![*\s])\*(?!\*)[^*\n]+(?<![\s])\*(?!\*)'
            r'|(?<![_\s])_(?!_)[^_\n]+(?<![\s])_(?!_)'
            r')' 
        )
        link_counter = [0]

        for seg in splitter.split(text):
            if not seg: continue
            m_link = re.match(r'^\[([^\]]*)\]\((https?://[^\)\s]+)\)$', seg)
            if m_link:
                label = _strip_inline(m_link.group(1))
                url = m_link.group(2)
                tag = f"link_{link_counter[0]}"; link_counter[0] += 1
                inner.tag_config(tag, font=self.FONT_MAIN, foreground="#4a9eff", underline=True)
                inner.tag_bind(tag, "<Button-1>", lambda e, u=url: webbrowser.open(u))
                inner.tag_bind(tag, "<Enter>", lambda e: inner.configure(cursor="hand2"))
                inner.tag_bind(tag, "<Leave>", lambda e: inner.configure(cursor=""))
                inner.insert("end", label, tag)
            elif seg.startswith('```'): inner.insert("end", seg[3:-3].strip('\n') + '\n', "code")
            elif seg.startswith('`'): inner.insert("end", seg[1:-1], "code")
            elif seg.startswith('**') or seg.startswith('__'): inner.insert("end", seg[2:-2], "bold")
            elif seg.startswith('*') or seg.startswith('_'): inner.insert("end", seg[1:-1], "italic")
            else: inner.insert("end", seg, "normal")

    def _calc_tb_height(self, text: str, chars_per_line: int = 72) -> int:
        line_px = 21
        pad_px  = 20
        lines = 0
        for line in text.split('\n'):
            lines += max(1, (max(0, len(line) - 1) // chars_per_line) + 1)
        return max(line_px + pad_px, lines * line_px + pad_px + 4)

    def _make_ctk_image(self, img_pil: Image.Image, max_size: tuple = (400, 400)) -> ctk.CTkImage:
        img_pil = img_pil.copy()
        img_pil.thumbnail(max_size, Image.LANCZOS)
        return ctk.CTkImage(light_image=img_pil, dark_image=img_pil, size=img_pil.size)

    def _load_pil_from_data_uri(self, data_uri: str):
        if not data_uri or not data_uri.startswith("data:"): return None
        try:
            _, b64 = data_uri.split(",", 1)
            return Image.open(io.BytesIO(base64.b64decode(b64)))
        except Exception: return None

    def _open_image_viewer(self, img_pil: Image.Image):
        viewer = ctk.CTkToplevel(self)
        viewer.title("Просмотр изображения")
        viewer.grab_set()
        viewer.lift()
        viewer.focus_force()

        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        max_w = int(screen_w * 0.9)
        max_h = int(screen_h * 0.85)

        img_view = img_pil.copy()
        img_view.thumbnail((max_w, max_h - 70), Image.LANCZOS)
        ctk_img = ctk.CTkImage(light_image=img_view, dark_image=img_view, size=img_view.size)

        win_w = max(img_view.width + 20, 160)
        win_h = img_view.height + 70
        x = (screen_w - win_w) // 2
        y = (screen_h - win_h) // 2
        viewer.geometry(f"{win_w}x{win_h}+{x}+{y}")
        viewer.resizable(False, False)

        ctk.CTkLabel(viewer, image=ctk_img, text="").pack(padx=10, pady=(10, 4))

        def _save():
            path = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG", "*.png"), ("JPEG", "*.jpg"), ("Все файлы", "*.*")])
            if path:
                try: img_pil.save(path)
                except Exception as e: logging.error(f"Не удалось сохранить: {e}")

        btn_frame = ctk.CTkFrame(viewer, fg_color="transparent")
        btn_frame.pack(pady=(0, 10))
        ctk.CTkButton(btn_frame, text="💾 Сохранить", command=_save, width=130, fg_color="#555", hover_color="#777").pack(side="left", padx=6)
        ctk.CTkButton(btn_frame, text="✕ Закрыть", command=viewer.destroy, width=100, fg_color="#3a3a3a", hover_color="#550000").pack(side="left", padx=6)

    def append_chat(self, sender, text, replace_last=False, close_bubble=False):
        is_attachment = isinstance(text, dict) and text.get("type") in ("file", "file_url", "image_url")
        msg_frame = None

        if replace_last and is_attachment and getattr(self, 'current_bot_frame', None) is not None:
            try: self.current_bot_frame.destroy()
            except Exception: pass
            self.current_bot_frame = None
            self.current_bot_textbox = None

        def _make_tb(parent):
            tb = ctk.CTkTextbox(parent, wrap="word", fg_color="transparent", border_width=0)
            self._hide_scrollbar(tb)
            tb._textbox.configure(font=self.FONT_MAIN)
            tb.pack(fill="both", expand=True, padx=8, pady=(2, 6))
            return tb

        def _fill_tb(tb, content, is_final):
            tb.configure(state="normal")
            tb.delete("0.0", "end")
            self.insert_markdown(tb, content)
            tb.configure(state="disabled")
            tb.configure(height=self._calc_tb_height(content))
            self._hide_scrollbar(tb)

            def _fit_to_content():
                try:
                    inner = tb._textbox
                    inner.update_idletasks()
                    last_idx = inner.index("end-1c")
                    info = inner.dlineinfo(last_idx)
                    if info is None: return False
                    content_px = info[1] + info[3]
                    try: pad_y = int(inner.cget("pady") or 2) * 2 + 8
                    except Exception: pad_y = 12
                    tb.configure(height=content_px + pad_y + 24)
                    self._hide_scrollbar(tb)
                    return True
                except Exception:
                    self._hide_scrollbar(tb)
                    return False

            def _try_fit(attempt=0):
                if not _fit_to_content() and attempt < 6:
                    tb.after(40, lambda: _try_fit(attempt + 1))

            tb.after(20, _try_fit)

        if not replace_last or getattr(self, 'current_bot_textbox', None) is None or not isinstance(text, str):
            msg_frame = ctk.CTkFrame(self.chat_scroll, fg_color="transparent")
            msg_frame.pack(fill="x", padx=10, pady=3)

            is_agent = sender == "Агент"
            bubble = ctk.CTkFrame(msg_frame, fg_color="#2b2b2b" if is_agent else "#1a4a7a", corner_radius=12)
            bubble.pack(side="left" if is_agent else "right", fill="x", expand=True, padx=(0 if is_agent else 60, 60 if is_agent else 0))
            
            if is_agent: self.current_bot_frame = msg_frame
            ctk.CTkLabel(bubble, text=sender, font=("Segoe UI", 11, "bold"), text_color="#888888").pack(anchor="w", padx=10, pady=(6, 0))

            if is_attachment:
                if text.get("type") == "image_url":
                    raw = text.get("image_url")
                    url = raw if isinstance(raw, str) else raw.get("url")
                    img_pil = None
                    if url and os.path.exists(url):
                        try: img_pil = Image.open(url)
                        except Exception: pass
                    if img_pil is None and url:
                        img_pil = self._load_pil_from_data_uri(url)
                    if img_pil is not None:
                        ctk_img = self._make_ctk_image(img_pil)
                        lbl = ctk.CTkLabel(bubble, image=ctk_img, text="", cursor="hand2")
                        lbl.pack(padx=10, pady=6)
                        lbl.bind("<Button-1>", lambda e, p=img_pil: self._open_image_viewer(p))
                    else:
                        ctk.CTkLabel(bubble, text="[Изображение]", font=self.FONT_MAIN).pack(anchor="w", padx=10, pady=6)
                elif text.get("type") == "file":
                    filepath = text.get("filepath", "")
                    caption  = text.get("caption", "")
                    filename = os.path.basename(filepath) if filepath else "файл"
                    ext = filepath.lower().rsplit('.', 1)[-1] if '.' in filepath else ""
                    if ext in ("png", "jpg", "jpeg", "gif", "bmp", "webp") and os.path.exists(filepath):
                        try:
                            img_pil = Image.open(filepath)
                            ctk_img = self._make_ctk_image(img_pil)
                            lbl = ctk.CTkLabel(bubble, image=ctk_img, text="", cursor="hand2")
                            lbl.pack(padx=10, pady=6)
                            lbl.bind("<Button-1>", lambda e, p=img_pil: self._open_image_viewer(p))
                        except Exception:
                            ctk.CTkLabel(bubble, text=f"📄 {filename}", font=self.FONT_MAIN).pack(anchor="w", padx=10, pady=6)
                    else:
                        ctk.CTkLabel(bubble, text=f"📄 {filename}", font=self.FONT_MAIN).pack(anchor="w", padx=10, pady=6)
                    if caption:
                        ctk.CTkLabel(bubble, text=caption, font=self.FONT_MAIN, wraplength=360).pack(anchor="w", padx=10, pady=(0, 6))
                else:
                    filepath = text.get("filepath") or text.get("file_url", {}).get("url", "")
                    filename = text.get("filename") or (os.path.basename(filepath) if filepath else "файл")
                    ctk.CTkLabel(bubble, text=f"📄 {filename}", font=self.FONT_MAIN).pack(anchor="w", padx=10, pady=6)
            else:
                tb = _make_tb(bubble)
                _fill_tb(tb, text, close_bubble)
                self.attach_copy_bindings(tb)
                if is_agent:
                    self.current_bot_textbox = tb

        else:
            _fill_tb(self.current_bot_textbox, text, close_bubble)

        if close_bubble and sender == "Агент":
            self.current_bot_textbox = None
            self.current_bot_frame = None

        self.chat_scroll.update_idletasks()
        self.chat_scroll._parent_canvas.yview_moveto(1.0)
        return msg_frame

    def send_gui_msg(self):
        msg = self.msg_entry.get("1.0", "end").strip()
        if not msg: return
        self.msg_entry.delete("1.0", "end")
        
        if msg.startswith("/"):
            cmd = msg.split()[0].lstrip("/").lower()
            if cmd == "clear":
                import core.database as db
                db.clear_history("GUI_USER")
                self.append_chat("Система", "🧹 История сессии очищена.", close_bubble=True)
                return
            elif cmd == "screenshot":
                status_frame = self.append_chat("Система", "📸 Делаю скриншот...")
                async def _do_screenshot():
                    result = await tools.take_screenshot()
                    def _finish():
                        if status_frame is not None:
                            try: status_frame.destroy()
                            except Exception: pass
                        if result.startswith("Ошибка"): self.append_chat("Система", result, close_bubble=True)
                        else: self.append_chat("Система", {"type": "image_url", "image_url": {"url": result}}, close_bubble=True)
                    self.after(0, _finish)
                asyncio.run_coroutine_threadsafe(_do_screenshot(), self.async_loop)
                return
            elif cmd == "memorize":
                self.append_chat("Вы", msg)
                self._dispatch_to_agent("ПРИНУДИТЕЛЬНАЯ ИНСТРУКЦИЯ: Изучи наш последний диалог и сохрани факты...")
                return
            elif cmd == "update":
                self.append_chat("Система", "🔄 Обновляю исходный код (git pull)...")
                import subprocess
                try:
                    res = subprocess.run(["git", "pull"], capture_output=True, text=True, timeout=30)
                    self.append_chat("Система", f"Результат Git:\n{res.stdout}\n{res.stderr}")
                    self.append_chat("Система", "⚠️ Теперь остановите агента и перезапустите программу для применения обновлений.", close_bubble=True)
                except Exception as e:
                    self.append_chat("Система", f"Ошибка: {e}", close_bubble=True)
                return
            elif cmd == "restart":
                self.append_chat("Система", "🔄 Перезапуск недоступен в GUI. Используйте кнопку.", close_bubble=True)
                return
            elif cmd == "shutdown":
                self.force_quit()
                return

        self.append_chat("Вы", msg)
        self._dispatch_to_agent(msg)

    def _dispatch_to_agent(self, content):
        if not self.async_loop or self.async_loop.is_closed():
            self.append_chat("Система", "⚠️ Агент не запущен. Нажмите «Запустить Агента».", close_bubble=True)
            return
        def stream_callback(text, is_status): 
            self.after(0, self.append_chat, "Агент", text, isinstance(text, str), not is_status)
        if "GUI_USER" in agent.active_sessions:
            agent.active_sessions["GUI_USER"].put_nowait(content)
            return
        asyncio.run_coroutine_threadsafe(
            agent.run_agent("GUI_USER", content, source_channel="GUI", gui_stream_callback=stream_callback),
            self.async_loop
        )

    def send_file_gui(self):
        if not self.is_running: return
        filepath = filedialog.askopenfilename()
        if not filepath: return
        filename = os.path.basename(filepath)
        mime, _ = mimetypes.guess_type(filepath)
        ext = filename.lower().rsplit('.', 1)[-1] if '.' in filename else ''
        self.append_chat("Вы", f"Файл отправлен: {filename}")

        try:
            with open(filepath, 'rb') as f:
                raw = f.read()
            b64 = base64.b64encode(raw).decode('utf-8')
        except Exception as e:
            self.append_chat("Система", f"Не удалось прочитать файл: {e}")
            return

        if mime and mime.startswith("image/"):
            self.append_chat("Вы", {"type": "image_url", "image_url": {"url": filepath}})
            content =[
                {"type": "text", "text": f"Пользователь прислал изображение: {filename}"},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            ]
            self._dispatch_to_agent(content)

        elif ext == 'pdf' or mime == 'application/pdf':
            pdf_reader = os.path.join(config.get_config_dir(), "read_pdf.py")
            content =[
                {"type": "text", "text": (
                    f"Пользователь прислал PDF-документ: {filename}\nПолный путь: {filepath}\n\n"
                    f"Для извлечения текста используй готовый скрипт:\n"
                    f"  execute_terminal('python3 {pdf_reader} \"{filepath}\"')\n"
                    f"Если PDF сканированный (нет текста) — добавь флаг --ocr:\n"
                    f"  execute_terminal('python3 {pdf_reader} \"{filepath}\" --ocr')\n"
                    f"Можно читать конкретные страницы: --pages 1-3,5"
                )}
            ]
            self._dispatch_to_agent(content)

        elif ext in ('docx', 'doc', 'xlsx', 'xls'):
            content =[
                {"type": "text", "text": (
                    f"Пользователь прислал офисный документ: {filename}\nПолный путь: {filepath}\n\n"
                    f"Используй `execute_terminal` с Python-скриптом для его чтения "
                    f"(python-docx для .docx/.doc, openpyxl для .xlsx/.xls)."
                )}
            ]
            self._dispatch_to_agent(content)
            return

        elif ext in ('txt', 'py', 'js', 'ts', 'json', 'csv', 'md', 'yaml', 'yml', 'xml', 'html', 'css', 'log'):
            try: text_content = raw.decode('utf-8', errors='replace')
            except Exception: text_content = raw.decode('latin-1', errors='replace')
            content =[{"type": "text", "text": f"Пользователь прислал файл `{filename}`:\n\n```\n{text_content[:8000]}\n```"}]
            self._dispatch_to_agent(content)
        else:
            content =[{"type": "text", "text": (
                f"Пользователь прислал файл: {filename}\n"
                f"Полный путь: {filepath}\n"
                f"MIME-тип: {mime or 'неизвестен'}\n"
                f"Для чтения используй file_operation(read, filepath)."
            )}]
            self._dispatch_to_agent(content)

    def setup_logs_tab(self):
        self.log_box = ctk.CTkTextbox(self.tabview.tab("Логи"), state="disabled", font=("Consolas", 12))
        self.log_box.pack(fill="both", expand=True)
        self.attach_copy_bindings(self.log_box)
        handler = GUILogHandler(self.log_box)
        handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logging.getLogger().addHandler(handler)

    def toggle_bot(self):
        if not self.is_running:
            self.btn_toggle.configure(text="Остановить Агента", fg_color="red")
            self.is_running = True
            self.async_loop = None  
            self.bot_thread = threading.Thread(target=self._run_async_bot_thread, daemon=True)
            self.bot_thread.start()
        else:
            self.btn_toggle.configure(text="Запустить Агента", fg_color="green")
            self.is_running = False
            if self.async_loop and not self.async_loop.is_closed():
                self.async_loop.call_soon_threadsafe(self.async_loop.stop)

    def _run_async_bot_thread(self):
        loop = asyncio.new_event_loop()
        self.async_loop = loop
        asyncio.set_event_loop(loop)
        agent.reset_session_state()
        try:
            loop.run_until_complete(start_bot())
        except asyncio.CancelledError: pass
        except Exception as e: logging.error(e)
        finally:
            try:
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            except Exception: pass
            loop.close()
            self.async_loop = None
            logging.info("🛑 Агент остановлен.")

    def force_quit(self):
        os._exit(0)