import os
import sys
import customtkinter as ctk
import threading
import asyncio
import logging
import platform
import time
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
            e.insert(0, config.get_env(key))
            e.grid(row=current_row, column=1, padx=(10, 0), pady=5, sticky="we")
            self.entries[key] = e

            if is_secret:
                btn = ctk.CTkButton(tab, text="👁", width=40, fg_color="#555", hover_color="#777", command=lambda ent=e: self.toggle_visibility(ent))
                btn.grid(row=current_row, column=2, padx=10, pady=5)
            current_row += 1

        sets = config.get_settings()
        
        ctk.CTkLabel(tab, text="Main Model (Оркестратор):", font=("Arial", 12, "bold")).grid(row=current_row, column=0, padx=10, pady=5, sticky="w")
        self.e_model_main = ctk.CTkEntry(tab)
        self.e_model_main.insert(0, sets.get("model_main", "google/gemini-3-flash-preview"))
        self.e_model_main.grid(row=current_row, column=1, padx=(10, 0), pady=5, sticky="we")
        current_row += 1

        ctk.CTkLabel(tab, text="Expert Model (Кодер/Аналитик):", font=("Arial", 12, "bold")).grid(row=current_row, column=0, padx=10, pady=5, sticky="w")
        self.e_model_expert = ctk.CTkEntry(tab)
        self.e_model_expert.insert(0, sets.get("model_expert", "anthropic/claude-haiku-4.5"))
        self.e_model_expert.grid(row=current_row, column=1, padx=(10, 0), pady=5, sticky="we")
        current_row += 1
        
        ctk.CTkLabel(tab, text="Фоновая активность:", font=("Arial", 12, "bold")).grid(row=current_row, column=0, padx=10, pady=5, sticky="w")
        frame_bg = ctk.CTkFrame(tab, fg_color="transparent")
        frame_bg.grid(row=current_row, column=1, padx=(10, 0), pady=5, sticky="we")
        total_sec = sets.get("bg_interval", 30)
        hours = total_sec // 3600
        minutes = (total_sec % 3600) // 60
        seconds = total_sec % 60
        self.e_bg_h = ctk.CTkEntry(frame_bg, width=50, placeholder_text="ч")
        self.e_bg_h.insert(0, str(hours))
        self.e_bg_h.pack(side="left", padx=2)
        ctk.CTkLabel(frame_bg, text="ч ", font=("Arial", 12)).pack(side="left")
        self.e_bg_m = ctk.CTkEntry(frame_bg, width=50, placeholder_text="м")
        self.e_bg_m.insert(0, str(minutes))
        self.e_bg_m.pack(side="left", padx=2)
        ctk.CTkLabel(frame_bg, text="м ", font=("Arial", 12)).pack(side="left")
        self.e_bg_s = ctk.CTkEntry(frame_bg, width=50, placeholder_text="с")
        self.e_bg_s.insert(0, str(seconds))
        self.e_bg_s.pack(side="left", padx=2)
        ctk.CTkLabel(frame_bg, text="с ", font=("Arial", 12)).pack(side="left")
        current_row += 1

        ctk.CTkLabel(tab, text="Максимум итераций:", font=("Arial", 12, "bold")).grid(row=current_row, column=0, padx=10, pady=5, sticky="w")
        self.e_max_iter = ctk.CTkEntry(tab)
        self.e_max_iter.insert(0, str(sets.get("max_iterations", 10)))
        self.e_max_iter.grid(row=current_row, column=1, padx=(10, 0), pady=5, sticky="we")
        current_row += 1

        ctk.CTkLabel(tab, text="Уровень логов:", font=("Arial", 12, "bold")).grid(row=current_row, column=0, padx=10, pady=5, sticky="w")
        self.c_log = ctk.CTkComboBox(tab, values=["DEBUG", "INFO", "WARNING", "ERROR"])
        self.c_log.set(sets.get("log_level", "INFO"))
        self.c_log.grid(row=current_row, column=1, padx=(10, 0), pady=5, sticky="we")
        current_row += 1

        btn_save = ctk.CTkButton(tab, text="💾 Сохранить настройки", command=self.save_configs)
        btn_save.grid(row=current_row, column=0, columnspan=3, pady=20)

    def toggle_visibility(self, entry):
        if entry.cget("show") == "*": entry.configure(show="")
        else: entry.configure(show="*")

    def save_configs(self):
        for k, v in self.entries.items(): config.set_env(k, v.get())
        try:
            hours = int(self.e_bg_h.get() or 0)
            minutes = int(self.e_bg_m.get() or 0)
            seconds = int(self.e_bg_s.get() or 0)
            bg_interval = hours * 3600 + minutes * 60 + seconds
            if bg_interval <= 0: bg_interval = 30
        except ValueError:
            bg_interval = 30
        config.save_settings({
            "bg_interval": bg_interval,
            "max_iterations": int(self.e_max_iter.get()),
            "log_level": self.c_log.get(),
            "model_main": self.e_model_main.get().strip(),
            "model_expert": self.e_model_expert.get().strip()
        })
        logging.getLogger().setLevel(self.c_log.get())
        logging.info("Настройки успешно сохранены.")

    def setup_chat_tab(self):
        tab = self.tabview.tab("Chat")
        self.chat_scroll = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        self.chat_scroll.pack(fill="both", expand=True, padx=5, pady=5)
        
        frame = ctk.CTkFrame(tab, height=50)
        frame.pack(fill="x", padx=5, pady=5)
        self.msg_entry = ctk.CTkEntry(frame, placeholder_text="Написать агенту...", font=("Arial", 14))
        self.msg_entry.pack(side="left", fill="x", expand=True, padx=5, pady=5)
        self.msg_entry.bind("<Return>", lambda e: self.send_gui_msg())
        
        ctk.CTkButton(frame, text="Отправить", width=80, command=self.send_gui_msg).pack(side="right", padx=5, pady=5)

    def append_chat(self, sender, text, replace_last=False, close_bubble=False):
        if not replace_last or getattr(self, 'current_bot_textbox', None) is None:
            msg_frame = ctk.CTkFrame(self.chat_scroll, fg_color="transparent")
            msg_frame.pack(fill="x", padx=10, pady=5)

            bubble_color = "#333333" if sender == "Агент" else "#1f538d"
            bubble = ctk.CTkFrame(msg_frame, fg_color=bubble_color, corner_radius=10)
            bubble.pack(side="left" if sender == "Агент" else "right", fill="x", expand=True, padx=(0 if sender=="Агент" else 50, 50 if sender=="Агент" else 0))

            lbl_sender = ctk.CTkLabel(bubble, text=sender, font=("Arial", 12, "bold"), text_color="#a0a0a0")
            lbl_sender.pack(anchor="w", padx=10, pady=(5, 0))

            tb = ctk.CTkTextbox(bubble, wrap="word", fg_color="transparent", border_width=0, font=("Arial", 14))
            tb.insert("1.0", text)
            tb.configure(state="disabled")
            tb.pack(fill="both", expand=True, padx=5, pady=5)
            
            # Корректная высота
            lines = text.count('\n') + sum(len(line) // 60 for line in text.split('\n')) + 1
            tb.configure(height=lines * 20 + 10)

            if sender == "Агент":
                self.current_bot_textbox = tb
        else:
            tb = self.current_bot_textbox
            tb.configure(state="normal")
            tb.delete("1.0", "end")
            tb.insert("1.0", text)
            
            lines = text.count('\n') + sum(len(line) // 60 for line in text.split('\n')) + 1
            tb.configure(height=lines * 20 + 10)
            tb.configure(state="disabled")

        if close_bubble and sender == "Агент":
            self.current_bot_textbox = None

        self.chat_scroll.update_idletasks()
        self.chat_scroll._parent_canvas.yview_moveto(1.0)

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

        asyncio.run_coroutine_threadsafe(
            agent.run_agent("GUI_USER", msg, gui_stream_callback=stream_callback), 
            self.async_loop
        )

    def setup_logs_tab(self):
        self.log_box = ctk.CTkTextbox(self.tabview.tab("Logs"), state="disabled", font=("Consolas", 12))
        self.log_box.pack(fill="both", expand=True)
        handler = GUILogHandler(self.log_box)
        handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logger = logging.getLogger()
        logger.setLevel(config.get_settings().get("log_level", "INFO"))
        logger.addHandler(handler)

    def toggle_bot(self):
        if not self.is_running:
            token = config.get_env("TELEGRAM_TOKEN").strip()
            if not token:
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
        
        try: bot = Bot(token=config.get_env("TELEGRAM_TOKEN").strip())
        except Exception as e:
            logging.error(f"❌ Критическая ошибка при инициализации Telegram Bot: {e}")
            self.after(0, self._force_stop_ui)
            return
            
        async def bg_worker():
            await asyncio.sleep(5)
            while True:
                sets = config.get_settings()
                logging.info("Фоновое пробуждение агента...")
                await agent.run_agent("GUI_USER", "[СИСТЕМА: ФОНОВОЕ ПРОБУЖДЕНИЕ. Проверь ПК, логи, задачи.]", is_background=True, bot_instance=bot)
                await asyncio.sleep(sets.get("bg_interval", 30))

        async def main_task():
            asyncio.create_task(bg_worker())
            logging.info("✅ Telegram-клиент успешно запущен. Ожидание сообщений...")
            await telegram_app.dp.start_polling(bot)

        try: self.async_loop.run_until_complete(main_task())
        except asyncio.CancelledError: pass
        except Exception as e: logging.error(f"❌ Ошибка в главном цикле: {e}")
        finally:
            self.async_loop.run_until_complete(bot.session.close())
            self.async_loop.close()
            logging.info("🛑 Агент полностью остановлен.")

if __name__ == "__main__":
    app = AgentGUI()
    app.mainloop()