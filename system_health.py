import os
import psutil
import datetime

def get_system_report():
    print(f"--- ОТЧЕТ СИСТЕМЫ JAR-V-IS ({datetime.datetime.now().strftime('%H:%M:%S')}) ---")
    
    # 1. Загрузка CPU и RAM
    cpu_usage = psutil.cpu_percent(interval=1)
    memory = psutil.virtual_memory()
    print(f"Процессор: {cpu_usage}%")
    print(f"Память: {memory.percent}% ({memory.used // (1024**2)}MB / {memory.total // (1024**2)}MB)")
    
    # 2. Проверка места на диске
    disk = psutil.disk_usage('/')
    print(f"Диск C: Свободно {disk.free // (1024**3)}GB из {disk.total // (1024**3)}GB")
    
    # 3. Поиск себя в процессах (файла run.py)
    my_processes = []
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            if proc.info['cmdline'] and 'run.py' in str(proc.info['cmdline']):
                my_processes.append(proc.info['pid'])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
            
    if my_processes:
        print(f"Статус агента: РАБОТАЕТ (PID: {my_processes})")
    else:
        print("Статус агента: ВНЕШНИЙ ЗАПУСК")
    print("-" * 40)

if __name__ == '__main__':
    get_system_report()
