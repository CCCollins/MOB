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
from aiogram import Bot
import config
import telegram_app
import agent
from PIL import Image, ImageTk

def resource_path(relative_path):
    try: base_path = sys._MEIPASS
    except Exception: base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

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
        self.title("AI Agent Controller")
        self.geometry("900x700")
        
        try:
            if platform.system() == "Windows":
                self.iconbitmap(resource_path("icon.ico"))
            else:
                img = ImageTk.PhotoImage(Image.open(resource_path("icon.png")))
                self.wm_iconphoto(True, img)
        except Exception as e:
            logging.warning(f"Иконка не загружена: {e}")

        self.bot_thread = None
        self.async_loop = None
        self.is_running = False
        self.current_bot_textbox = None
        self.current_bot_frame = None
        self._cached_images =[]

        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(fill="both", expand=True, padx=10, pady=10)
        self.tabview.add("Chat")
        self.tabview.add("Settings")
        self.tabview.add("Logs")

        self.setup_settings_tab()
        self.setup_chat_tab()
        self.setup_logs_tab()

        self.btn_toggle = ctk.CTkButton(self, text="Запустить Агента", command=self.toggle_bot, fg_color="green", font=("Arial", 14, "bold"))
        self.btn_toggle.pack(pady=10)

    def setup_settings_tab(self):
        tab = self.tabview.tab("Settings")
        self.entries = {}
        tab.grid_columnconfigure(1, weight=1)

        env_vars =["TELEGRAM_TOKEN", "ALLOWED_TELEGRAM_IDS", "OPENROUTER_API_KEY", "BRAVE_API_KEY", "DYNAMICPDF_API_KEY"]
        
        current_row = 0
        for key in env_vars:
            ctk.CTkLabel(tab, text=key, font=("Arial", 12, "bold")).grid(row=current_row, column=0, padx=10, pady=5, sticky="w")
            is_secret = "TOKEN" in key or "KEY" in key
            e = ctk.CTkEntry(tab, show="*" if is_secret else "")
            e.insert(0, config.get_config(key))
            e.grid(row=current_row, column=1, padx=(10, 0), pady=5, sticky="we")
            self.entries[key] = e

            if is_secret:
                btn = ctk.CTkButton(tab, text="👁", width=40, fg_color="#555", hover_color="#777", command=lambda ent=e: self.toggle_visibility(ent))
                btn.grid(row=current_row, column=2, padx=10, pady=5)
            current_row += 1

        ctk.CTkLabel(tab, text="Main Model:", font=("Arial", 12, "bold")).grid(row=current_row, column=0, padx=10, pady=5, sticky="w")
        self.e_model_main = ctk.CTkEntry(tab)
        self.e_model_main.insert(0, config.get_config("model_main"))
        self.e_model_main.grid(row=current_row, column=1, padx=(10, 0), pady=5, sticky="we")
        current_row += 1

        ctk.CTkLabel(tab, text="Expert Model:", font=("Arial", 12, "bold")).grid(row=current_row, column=0, padx=10, pady=5, sticky="w")
        self.e_model_expert = ctk.CTkEntry(tab)
        self.e_model_expert.insert(0, config.get_config("model_expert"))
        self.e_model_expert.grid(row=current_row, column=1, padx=(10, 0), pady=5, sticky="we")
        current_row += 1
        
        ctk.CTkLabel(tab, text="Фоновая активность:", font=("Arial", 12, "bold")).grid(row=current_row, column=0, padx=10, pady=5, sticky="w")
        frame_bg = ctk.CTkFrame(tab, fg_color="transparent")
        frame_bg.grid(row=current_row, column=1, padx=(10, 0), pady=5, sticky="we")
        
        total_sec = config.get_config("bg_interval") or 28800
        self.e_bg_h = ctk.CTkEntry(frame_bg, width=50); self.e_bg_h.insert(0, str(total_sec // 3600)); self.e_bg_h.pack(side="left", padx=2)
        ctk.CTkLabel(frame_bg, text="ч ", font=("Arial", 12)).pack(side="left")
        self.e_bg_m = ctk.CTkEntry(frame_bg, width=50); self.e_bg_m.insert(0, str((total_sec % 3600) // 60)); self.e_bg_m.pack(side="left", padx=2)
        ctk.CTkLabel(frame_bg, text="м ", font=("Arial", 12)).pack(side="left")
        self.e_bg_s = ctk.CTkEntry(frame_bg, width=50); self.e_bg_s.insert(0, str(total_sec % 60)); self.e_bg_s.pack(side="left", padx=2)
        ctk.CTkLabel(frame_bg, text="с ", font=("Arial", 12)).pack(side="left")
        current_row += 1

        ctk.CTkLabel(tab, text="Макс. итераций:", font=("Arial", 12, "bold")).grid(row=current_row, column=0, padx=10, pady=5, sticky="w")
        self.e_max_iter = ctk.CTkEntry(tab)
        self.e_max_iter.insert(0, str(config.get_config("max_iterations") or 10))
        self.e_max_iter.grid(row=current_row, column=1, padx=(10, 0), pady=5, sticky="we")
        current_row += 1

        ctk.CTkLabel(tab, text="Уровень логов:", font=("Arial", 12, "bold")).grid(row=current_row, column=0, padx=10, pady=5, sticky="w")
        self.c_log = ctk.CTkComboBox(tab, values=["DEBUG", "INFO", "WARNING", "ERROR"])
        self.c_log.set(config.get_config("log_level") or "INFO")
        self.c_log.grid(row=current_row, column=1, padx=(10, 0), pady=5, sticky="we")
        current_row += 1

        btn_save = ctk.CTkButton(tab, text="💾 Сохранить", command=self.save_configs)
        btn_save.grid(row=current_row, column=0, columnspan=3, pady=20)

    def toggle_visibility(self, entry):
        entry.configure(show="" if entry.cget("show") == "*" else "*")

    def save_configs(self):
        data = {k: v.get().strip() for k, v in self.entries.items()}
        try: data["bg_interval"] = max(1, int(self.e_bg_h.get() or 0)*3600 + int(self.e_bg_m.get() or 0)*60 + int(self.e_bg_s.get() or 0))
        except ValueError: data["bg_interval"] = 28800
        data["max_iterations"] = int(self.e_max_iter.get() or 10)
        data["log_level"] = self.c_log.get()
        data["model_main"] = self.e_model_main.get().strip()
        data["model_expert"] = self.e_model_expert.get().strip()
        config.save_all(data)
        logging.getLogger().setLevel(data["log_level"])
        logging.info("Настройки сохранены в безопасную папку.")

    def setup_chat_tab(self):
        tab = self.tabview.tab("Chat")
        self.chat_scroll = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        self.chat_scroll.pack(fill="both", expand=True, padx=5, pady=5)
        
        frame = ctk.CTkFrame(tab, height=50)
        frame.pack(fill="x", padx=5, pady=5)
        self.msg_entry = ctk.CTkEntry(frame, placeholder_text="Написать агенту...", font=("Arial", 14))
        self.msg_entry.pack(side="left", fill="x", expand=True, padx=5, pady=5)
        self.msg_entry.bind("<Return>", lambda e: self.send_gui_msg())
        
        ctk.CTkButton(frame, text="Прикрепить", width=40, command=self.send_file_gui).pack(side="right", padx=5, pady=5)
        ctk.CTkButton(frame, text="Отправить", width=80, command=self.send_gui_msg).pack(side="right", padx=5, pady=5)

    def attach_copy_bindings(self, textbox):
        def copy_text(event=None):
            if event and event.char.lower() not in ('c', 'с'):
                return
            try:
                self.clipboard_clear()
                self.clipboard_append(textbox.selection_get())
            except Exception: pass
            return "break"
        textbox.bind("<Control-KeyPress>", copy_text)
        textbox.bind("<Command-KeyPress>", copy_text)

        menu = tk.Menu(self, tearoff=0, bg="#2b2b2b", fg="white", activebackground="#1f538d", activeforeground="white", borderwidth=0)
        menu.add_command(label="Копировать", command=lambda: copy_text())

        def show_menu(event):
            try: menu.tk_popup(event.x_root, event.y_root)
            finally: menu.grab_release()

        if platform.system() == "Darwin":
            textbox.bind("<Button-2>", show_menu)
            textbox.bind("<Control-Button-1>", show_menu)
        else:
            textbox.bind("<Button-3>", show_menu)

    def insert_markdown(self, textbox, text):
        """Парсит Markdown и вставляет красиво стилизованный текст"""
        textbox._textbox.tag_config("bold", font=("Arial", 14, "bold"))
        textbox._textbox.tag_config("italic", font=("Arial", 14, "italic"))
        textbox._textbox.tag_config("code", font=("Consolas", 13), foreground="#e6db74")
        
        parts = re.split(r'(\*\*.*?\*\*|__.*?__|```.*?```|`.*?`|\*.*?\*|_.*?_)', text, flags=re.DOTALL)
        for part in parts:
            if not part: continue
            if part.startswith('**') and part.endswith('**'): textbox.insert("end", part[2:-2], "bold")
            elif part.startswith('__') and part.endswith('__'): textbox.insert("end", part[2:-2], "bold")
            elif part.startswith('```') and part.endswith('```'): textbox.insert("end", part[3:-3].strip(), "code")
            elif part.startswith('`') and part.endswith('`'): textbox.insert("end", part[1:-1], "code")
            elif part.startswith('*') and part.endswith('*'): textbox.insert("end", part[1:-1], "italic")
            elif part.startswith('_') and part.endswith('_'): textbox.insert("end", part[1:-1], "italic")
            else: textbox.insert("end", part)

    def append_chat(self, sender, text, replace_last=False, close_bubble=False):
        is_attachment = isinstance(text, dict) and text.get("type") in ("file", "file_url", "image_url")

        # Если приходит вложение, заменяем предыдущую «статусную» бубльку агента
        if replace_last and is_attachment and getattr(self, 'current_bot_frame', None) is not None:
            try:
                self.current_bot_frame.destroy()
            except Exception:
                pass
            self.current_bot_frame = None
            self.current_bot_textbox = None

        if not replace_last or getattr(self, 'current_bot_textbox', None) is None or not isinstance(text, str):
            msg_frame = ctk.CTkFrame(self.chat_scroll, fg_color="transparent")
            msg_frame.pack(fill="x", padx=10, pady=5)

            bubble = ctk.CTkFrame(msg_frame, fg_color="#333333" if sender == "Агент" else "#1f538d", corner_radius=10)
            bubble.pack(side="left" if sender == "Агент" else "right", fill="x", expand=True, padx=(0 if sender=="Агент" else 50, 50 if sender=="Агент" else 0))
            if sender == "Агент":
                self.current_bot_frame = msg_frame

            lbl_sender = ctk.CTkLabel(bubble, text=sender, font=("Arial", 12, "bold"), text_color="#a0a0a0")
            lbl_sender.pack(anchor="w", padx=10, pady=(5, 0))

            if is_attachment:
                if text.get("type") == "image_url":
                    raw = text.get("image_url")
                    url = raw if isinstance(raw, str) else raw.get("url")

                    # Поддержка как data-uri, так и локальных путей
                    img = None
                    if url and os.path.exists(url):
                        try:
                            img_pil = Image.open(url)
                            img_pil.thumbnail((400, 400))
                            img = ImageTk.PhotoImage(img_pil)
                        except Exception:
                            img = None
                    if not img:
                        img = self._load_image_from_data_uri(url)

                    if img:
                        lbl_img = ctk.CTkLabel(bubble, image=img, text="")
                        lbl_img.pack(padx=10, pady=5)
                        self._cached_images.append(img)
                else:
                    filepath = text.get("filepath") or text.get("file_url", {}).get("url")
                    filename = text.get("filename") or (os.path.basename(filepath) if filepath else "")
                    lbl_file = ctk.CTkLabel(bubble, text=f"Файл: {filename}", font=("Arial", 14))
                    lbl_file.pack(anchor="w", padx=10, pady=5)
            else:
                tb = ctk.CTkTextbox(bubble, wrap="word", fg_color="transparent", border_width=0, font=("Arial", 14))
                tb.pack(fill="both", expand=True, padx=5, pady=5)
                if close_bubble:
                    self.insert_markdown(tb, text)
                else:
                    tb.insert("0.0", text)
                tb.configure(state="disabled")
                self.attach_copy_bindings(tb)
                
                # Точный расчет высоты пузыря
                est_lines = sum((len(line) // 60) + 1 for line in text.split('\n'))
                tb.configure(height=est_lines * 22 + 15)

                if sender == "Агент": self.current_bot_textbox = tb
        else:
            tb = self.current_bot_textbox
            tb.configure(state="normal")
            tb.delete("0.0", "end")
            if close_bubble:
                self.insert_markdown(tb, text)
            else:
                tb.insert("0.0", text)
            tb.configure(state="disabled")
            
            est_lines = sum((len(line) // 60) + 1 for line in text.split('\n'))
            tb.configure(height=est_lines * 22 + 15)

        if close_bubble and sender == "Агент":
            self.current_bot_textbox = None
            self.current_bot_frame = None

        self.chat_scroll.update_idletasks()
        self.chat_scroll._parent_canvas.yview_moveto(1.0)

    def _load_image_from_data_uri(self, data_uri: str):
        if not data_uri or not data_uri.startswith("data:"): return None
        try:
            _, b64 = data_uri.split(",", 1)
            img = Image.open(io.BytesIO(base64.b64decode(b64)))
            img.thumbnail((400, 400))
            return ImageTk.PhotoImage(img)
        except Exception: return None

    def send_gui_msg(self):
        msg = self.msg_entry.get()
        if not msg.strip() or not self.is_running: return
        self.msg_entry.delete(0, "end")
        self.append_chat("Вы", msg)
        
        if "GUI_USER" in agent.active_sessions:
            agent.active_sessions["GUI_USER"].put_nowait(msg)
            return

        def stream_callback(text, is_status):
            self.after(0, self.append_chat, "Агент", text, True, not is_status)

        asyncio.run_coroutine_threadsafe(agent.run_agent("GUI_USER", msg, gui_stream_callback=stream_callback), self.async_loop)

    def send_file_gui(self):
        if not self.is_running: return
        filepath = filedialog.askopenfilename()
        if not filepath: return
        filename = os.path.basename(filepath)
        mime, _ = mimetypes.guess_type(filepath)
        self.append_chat("Вы", f"Файл отправлен: {filename}")

        content =[{"type": "text", "text": f"Файл: {filename}"}]
        if mime and mime.startswith("image/"):
            with open(filepath, 'rb') as f:
                content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{base64.b64encode(f.read()).decode('utf-8')}"}})
        else:
            with open(filepath, 'rb') as f:
                content.append({"type": "file_url", "file_url": {"url": f"data:{mime or 'application/octet-stream'};base64,{base64.b64encode(f.read()).decode('utf-8')}", "filename": filename}})
        
        if "GUI_USER" in agent.active_sessions:
            agent.active_sessions["GUI_USER"].put_nowait(content)
            return

        def stream_callback(text, is_status):
            self.after(0, self.append_chat, "Агент", text, isinstance(text, str), not is_status)

        asyncio.run_coroutine_threadsafe(agent.run_agent("GUI_USER", content, gui_stream_callback=stream_callback), self.async_loop)

    def setup_logs_tab(self):
        self.log_box = ctk.CTkTextbox(self.tabview.tab("Logs"), state="disabled", font=("Consolas", 12))
        self.log_box.pack(fill="both", expand=True)
        handler = GUILogHandler(self.log_box)
        handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logger = logging.getLogger()
        logger.setLevel(config.get_config("log_level") or "INFO")
        logger.addHandler(handler)

    def toggle_bot(self):
        if not self.is_running:
            if not config.get_config("TELEGRAM_TOKEN").strip():
                logging.error("❌ ЗАПУСК ПРЕРВАН: Не указан TELEGRAM_TOKEN в настройках!")
                return
            self.btn_toggle.configure(text="Остановить Агента", fg_color="red")
            self.is_running = True
            self.bot_thread = threading.Thread(target=self.run_async_bot, daemon=True)
            self.bot_thread.start()
        else:
            self._force_stop_ui()
            if self.async_loop: self.async_loop.call_soon_threadsafe(self.async_loop.stop)

    def _force_stop_ui(self):
        self.btn_toggle.configure(text="Запустить Агента", fg_color="green")
        self.is_running = False

    def run_async_bot(self):
        self.async_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.async_loop)
        try: bot = Bot(token=config.get_config("TELEGRAM_TOKEN").strip())
        except Exception as e:
            logging.error(f"❌ Критическая ошибка: {e}")
            self.after(0, self._force_stop_ui)
            return
            
        async def bg_worker():
            await asyncio.sleep(5)
            while True:
                logging.info("Фоновое пробуждение агента...")
                await agent.run_agent("GUI_USER", "[СИСТЕМА: ФОНОВОЕ ПРОБУЖДЕНИЕ. Проверь логи, ответь IDLE.]", is_background=True, bot_instance=bot)
                await asyncio.sleep(config.get_config("bg_interval") or 28800)

        async def main_task():
            asyncio.create_task(bg_worker())
            logging.info("✅ Telegram-клиент успешно запущен.")
            await telegram_app.dp.start_polling(bot)

        try: self.async_loop.run_until_complete(main_task())
        except asyncio.CancelledError: pass
        finally:
            self.async_loop.run_until_complete(bot.session.close())
            self.async_loop.close()
            logging.info("🛑 Агент остановлен.")

if __name__ == "__main__":
    app = AgentGUI()
    app.mainloop()