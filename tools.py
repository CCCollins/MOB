import asyncio
import platform
import aiohttp
import os
import json
import io
import tempfile
import re
from config import get_env

def make_safe_filename(filename: str) -> str:
    return re.sub(r'[^\x00-\x7F]+', '_', filename)

async def convert_to_pdf(file_path: str, original_filename: str) -> str | None:
    api_key = get_env("DYNAMICPDF_API_KEY")
    if not api_key: return None
    ext = original_filename.lower().split('.')[-1]
    if ext in ['docx', 'doc']: input_type, mime = "word", 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    elif ext in['xlsx', 'xls']: input_type, mime = "excel", 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    else: return None

    resource_name = make_safe_filename(original_filename)
    instructions = json.dumps({"inputs":[{"type": input_type, "resourceName": resource_name}]})
    
    try:
        async with aiohttp.ClientSession() as session:
            with open(file_path, 'rb') as f:
                form = aiohttp.FormData()
                form.add_field('Instructions', io.BytesIO(instructions.encode('utf-8')), filename='instructions.json', content_type='application/json')
                form.add_field('Resource', f, filename=resource_name, content_type=mime)
                async with session.post("https://api.dpdf.io/v1.0/pdf", headers={"Authorization": f"Bearer {api_key}"}, data=form, ssl=False) as resp:
                    if resp.status != 200: return None
                    pdf_content = await resp.read()
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(pdf_content)
                return tmp.name
    except: return None

async def execute_terminal(command: str) -> str:
    try:
        if platform.system() == "Windows":
            shell_cmd = f"powershell -NoProfile -Command \"[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; {command}\""
        else: shell_cmd = command
        process = await asyncio.create_subprocess_shell(shell_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=120.0)
        output = stdout.decode('utf-8', errors='replace') + stderr.decode('utf-8', errors='replace')
        if len(output) > 2000: return output[:2000] + "\n...[ОБРЕЗАНО]..."
        return output if output.strip() else "Успешно (нет вывода)."
    except Exception as e: return f"Ошибка: {str(e)}"

async def web_search(query: str) -> str:
    api_key = get_env("BRAVE_API_KEY")
    if not api_key: return "Ключ Brave API не настроен."
    async with aiohttp.ClientSession() as session:
        async with session.get("https://api.search.brave.com/res/v1/web/search", headers={"Accept": "application/json", "X-Subscription-Token": api_key}, params={"q": query}) as response:
            if response.status != 200: return "Ошибка поиска."
            data = await response.json()
            results =[f"{i.get('title')} - {i.get('url')}\n{i.get('description')}" for i in data.get("web", {}).get("results", [])]
            return "\n".join(results) if results else "Ничего не найдено."

async def file_operation(action: str, filepath: str, content: str = "") -> str:
    try:
        if action == "read":
            with open(filepath, 'r', encoding='utf-8') as f:
                data = f.read()
                return data[:3000] + "\n[ОБРЕЗАНО]" if len(data) > 3000 else data
        elif action == "write":
            os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
            with open(filepath, 'w', encoding='utf-8') as f: f.write(content)
            return f"Файл {filepath} записан."
    except Exception as e: return f"Ошибка: {str(e)}"