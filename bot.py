import os
import anthropic
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes
from google.oauth2 import service_account
from googleapiclient.discovery import build
from datetime import datetime, timedelta
import pytz
import re
import tempfile
import httpx

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
GOOGLE_SERVICE_ACCOUNT_EMAIL = os.environ["GOOGLE_SERVICE_ACCOUNT_EMAIL"]
GOOGLE_PRIVATE_KEY = os.environ["GOOGLE_PRIVATE_KEY"].replace("\\n", "\n")
GOOGLE_CALENDAR_ID = os.environ["GOOGLE_CALENDAR_ID"]
TODOIST_API_KEY = os.environ["TODOIST_API_KEY"]
TAVILY_API_KEY = os.environ["TAVILY_API_KEY"]

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

def remove_markdown(text):
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'__(.+?)__', r'\1', text)
    text = re.sub(r'_(.+?)_', r'\1', text)
    return text

def get_calendar_service():
    credentials = service_account.Credentials.from_service_account_info(
        {
            "type": "service_account",
            "project_id": "mybot-498411",
            "private_key_id": "2e8aaaab131f6888e293ae10fc5dde5d1b71cbe6",
            "private_key": GOOGLE_PRIVATE_KEY,
            "client_email": GOOGLE_SERVICE_ACCOUNT_EMAIL,
            "client_id": "118272816733687920731",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        },
        scopes=["https://www.googleapis.com/auth/calendar"]
    )
    return build("calendar", "v3", credentials=credentials)

def get_events_for_date(date_str):
    try:
        service = get_calendar_service()
        tz = pytz.timezone("Europe/Moscow")
        dt = tz.localize(datetime.strptime(date_str, "%Y-%m-%d"))
        start = dt.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        end = dt.replace(hour=23, minute=59, second=59, microsecond=0).isoformat()
        result = service.events().list(
            calendarId=GOOGLE_CALENDAR_ID, timeMin=start, timeMax=end,
            singleEvents=True, orderBy="startTime"
        ).execute()
        events = result.get("items", [])
        if not events:
            return f"На {date_str} событий нет.", []
        text = f"📅 События на {date_str}:\n"
        event_list = []
        for i, e in enumerate(events):
            st = e["start"].get("dateTime", e["start"].get("date", ""))
            t = datetime.fromisoformat(st).astimezone(tz).strftime("%H:%M") if "T" in st else "весь день"
            name = e.get("summary", "Без названия")
            text += f"{i+1}. {t} — {name}\n"
            event_list.append({"id": e["id"], "summary": name, "time": t})
        return text, event_list
    except Exception as ex:
        return f"Ошибка: {ex}", []

def get_today_events():
    tz = pytz.timezone("Europe/Moscow")
    text, _ = get_events_for_date(datetime.now(tz).strftime("%Y-%m-%d"))
    return text

def get_tomorrow_events():
    tz = pytz.timezone("Europe/Moscow")
    text, _ = get_events_for_date((datetime.now(tz) + timedelta(days=1)).strftime("%Y-%m-%d"))
    return text

def get_week_events():
    try:
        service = get_calendar_service()
        tz = pytz.timezone("Europe/Moscow")
        now = datetime.now(tz)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        end = (now + timedelta(days=7)).replace(hour=23, minute=59, second=59).isoformat()
        result = service.events().list(
            calendarId=GOOGLE_CALENDAR_ID, timeMin=start, timeMax=end,
            singleEvents=True, orderBy="startTime"
        ).execute()
        events = result.get("items", [])
        if not events:
            return "На ближайшие 7 дней событий нет."
        text = "📅 Ближайшие 7 дней:\n"
        for e in events:
            st = e["start"].get("dateTime", e["start"].get("date", ""))
            t = datetime.fromisoformat(st).astimezone(tz).strftime("%d.%m %H:%M") if "T" in st else st
            text += f"• {t} — {e.get('summary', 'Без названия')}\n"
        return text
    except Exception as ex:
        return f"Ошибка: {ex}"

def get_free_blocks(date_str, work_start="09:00", work_end="22:00", min_block_minutes=60):
    """Возвращает свободные блоки в расписании на дату."""
    try:
        service = get_calendar_service()
        tz = pytz.timezone("Europe/Moscow")
        dt = tz.localize(datetime.strptime(date_str, "%Y-%m-%d"))

        # Границы рабочего дня
        day_start = dt.replace(hour=int(work_start.split(":")[0]), minute=int(work_start.split(":")[1]), second=0, microsecond=0)
        day_end = dt.replace(hour=int(work_end.split(":")[0]), minute=int(work_end.split(":")[1]), second=0, microsecond=0)

        result = service.events().list(
            calendarId=GOOGLE_CALENDAR_ID,
            timeMin=day_start.isoformat(),
            timeMax=day_end.isoformat(),
            singleEvents=True, orderBy="startTime"
        ).execute()
        events = result.get("items", [])

        # Строим занятые интервалы
        busy = []
        for e in events:
            s = e["start"].get("dateTime")
            en = e["end"].get("dateTime")
            if s and en:
                busy.append((
                    datetime.fromisoformat(s).astimezone(tz),
                    datetime.fromisoformat(en).astimezone(tz)
                ))
        busy.sort(key=lambda x: x[0])

        # Ищем свободные блоки
        free_blocks = []
        cursor = day_start
        for b_start, b_end in busy:
            if b_start > cursor:
                gap_minutes = int((b_start - cursor).total_seconds() / 60)
                if gap_minutes >= min_block_minutes:
                    free_blocks.append({
                        "from": cursor.strftime("%H:%M"),
                        "to": b_start.strftime("%H:%M"),
                        "minutes": gap_minutes
                    })
            cursor = max(cursor, b_end)

        # Остаток после последнего события
        if cursor < day_end:
            gap_minutes = int((day_end - cursor).total_seconds() / 60)
            if gap_minutes >= min_block_minutes:
                free_blocks.append({
                    "from": cursor.strftime("%H:%M"),
                    "to": day_end.strftime("%H:%M"),
                    "minutes": gap_minutes
                })

        return free_blocks
    except Exception as ex:
        return []

def plan_day(date_str):
    """Возвращает полную картину дня: события + свободные блоки."""
    events_text, events = get_events_for_date(date_str)
    free_blocks = get_free_blocks(date_str)

    text = events_text + "\n"
    if free_blocks:
        text += "\n⏳ Свободные блоки:\n"
        for b in free_blocks:
            hours = b["minutes"] // 60
            mins = b["minutes"] % 60
            duration = f"{hours}ч {mins}м" if hours else f"{mins}м"
            text += f"• {b['from']} – {b['to']} ({duration})\n"
    else:
        text += "\nСвободных блоков нет — день плотный."
    return text

def add_event(summary, date_str, time_str, duration_hours=1):
    try:
        service = get_calendar_service()
        tz = pytz.timezone("Europe/Moscow")
        dt_start = tz.localize(datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M"))
        dt_end = dt_start + timedelta(hours=float(duration_hours))
        event = {
            "summary": summary,
            "start": {"dateTime": dt_start.isoformat(), "timeZone": "Europe/Moscow"},
            "end": {"dateTime": dt_end.isoformat(), "timeZone": "Europe/Moscow"},
        }
        service.events().insert(calendarId=GOOGLE_CALENDAR_ID, body=event).execute()
        return f"✅ Добавлено в календарь: {summary} — {date_str} в {time_str}"
    except Exception as ex:
        return f"Ошибка: {ex}"

def find_event_id(date_str, name_fragment):
    _, events = get_events_for_date(date_str)
    for e in events:
        if name_fragment.lower() in e["summary"].lower():
            return e["id"], e["summary"]
    return None, None

def delete_event(event_id):
    try:
        get_calendar_service().events().delete(calendarId=GOOGLE_CALENDAR_ID, eventId=event_id).execute()
        return "✅ Событие удалено."
    except Exception as ex:
        return f"Ошибка: {ex}"

def move_event(event_id, new_date_str, new_time_str):
    try:
        service = get_calendar_service()
        tz = pytz.timezone("Europe/Moscow")
        event = service.events().get(calendarId=GOOGLE_CALENDAR_ID, eventId=event_id).execute()
        duration = datetime.fromisoformat(event["end"]["dateTime"]) - datetime.fromisoformat(event["start"]["dateTime"])
        new_start = tz.localize(datetime.strptime(f"{new_date_str} {new_time_str}", "%Y-%m-%d %H:%M"))
        event["start"] = {"dateTime": new_start.isoformat(), "timeZone": "Europe/Moscow"}
        event["end"] = {"dateTime": (new_start + duration).isoformat(), "timeZone": "Europe/Moscow"}
        service.events().update(calendarId=GOOGLE_CALENDAR_ID, eventId=event_id, body=event).execute()
        return f"✅ Перенесено на {new_date_str} в {new_time_str}"
    except Exception as ex:
        return f"Ошибка: {ex}"

TODOIST_BASE = "https://api.todoist.com/api/v1"
TODOIST_HEADERS = {"Authorization": f"Bearer {TODOIST_API_KEY}"}
PRIORITY_MAP = {"p1": 4, "p2": 3, "p3": 2, "p4": 1}
PRIORITY_EMOJI = {4: "🔴", 3: "🟠", 2: "🔵", 1: "⚪"}

def get_todoist_tasks():
    try:
        tasks = httpx.get(f"{TODOIST_BASE}/tasks", headers=TODOIST_HEADERS, timeout=10).json()
        if not tasks:
            return "В Todoist задач нет."
        text = "📋 Задачи:\n"
        for t in sorted(tasks, key=lambda x: -x.get("priority", 1)):
            emoji = PRIORITY_EMOJI.get(t.get("priority", 1), "⚪")
            due = f" (до {t['due']['date']})" if t.get("due") else ""
            text += f"{emoji} {t['content']}{due}\n"
        return text
    except Exception as ex:
        return f"Ошибка Todoist: {ex}"

def add_todoist_task(content, priority="p3", due_date=None):
    try:
        body = {"content": content, "priority": PRIORITY_MAP.get(priority.lower(), 2)}
        if due_date:
            body["due_date"] = due_date
        headers = {**TODOIST_HEADERS, "Content-Type": "application/json"}
        resp = httpx.post(f"{TODOIST_BASE}/tasks", headers=headers, json=body, timeout=10)
        print(f"[Todoist add] status={resp.status_code} body={resp.text[:300]}")
        if resp.status_code not in (200, 204):
            return f"Ошибка Todoist {resp.status_code}: {resp.text[:200]}"
        return f"✅ Добавлено в Todoist: {PRIORITY_EMOJI.get(body['priority'], '⚪')} {content}"
    except Exception as ex:
        return f"Ошибка: {ex}"

def find_todoist_task(tasks, task_name):
    """Ищет задачу: точное совпадение → один substring. Защита от ложных матчей."""
    name_lower = task_name.lower().strip()
    for t in tasks:
        if t["content"].lower().strip() == name_lower:
            return t
    matches = [t for t in tasks if name_lower in t["content"].lower()]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        names = ", ".join('"' + t["content"] + '"' for t in matches[:5])
        return {"error": f"Найдено несколько задач: {names}. Уточни название."}
    return None

def complete_todoist_task(task_name):
    try:
        tasks = httpx.get(f"{TODOIST_BASE}/tasks", headers=TODOIST_HEADERS, timeout=10).json()
        t = find_todoist_task(tasks, task_name)
        if t is None:
            return f"Задача не найдена: {task_name}"
        if "error" in t:
            return t["error"]
        httpx.post(f"{TODOIST_BASE}/tasks/{t['id']}/close", headers=TODOIST_HEADERS, timeout=10)
        return f"✅ Выполнено: {t['content']}"
    except Exception as ex:
        return f"Ошибка: {ex}"

def delete_todoist_task(task_name):
    try:
        tasks = httpx.get(f"{TODOIST_BASE}/tasks", headers=TODOIST_HEADERS, timeout=10).json()
        t = find_todoist_task(tasks, task_name)
        if t is None:
            return f"Задача не найдена: {task_name}"
        if "error" in t:
            return t["error"]
        httpx.delete(f"{TODOIST_BASE}/tasks/{t['id']}", headers=TODOIST_HEADERS, timeout=10)
        return f"✅ Удалено: {t['content']}"
    except Exception as ex:
        return f"Ошибка: {ex}"

def update_todoist_task(task_name, new_content=None, new_priority=None, new_due_date=None):
    try:
        tasks = httpx.get(f"{TODOIST_BASE}/tasks", headers=TODOIST_HEADERS, timeout=10).json()
        t = find_todoist_task(tasks, task_name)
        if t is None:
            return f"Задача не найдена: {task_name}"
        if "error" in t:
            return t["error"]
        body = {}
        if new_content:
            body["content"] = new_content
        if new_priority:
            body["priority"] = PRIORITY_MAP.get(new_priority.lower(), t.get("priority", 2))
        if new_due_date:
            body["due_date"] = new_due_date
        httpx.post(f"{TODOIST_BASE}/tasks/{t['id']}", headers=TODOIST_HEADERS, json=body, timeout=10)
        return f"✅ Обновлено: {new_content or t['content']}"
    except Exception as ex:
        return f"Ошибка: {ex}"

def web_search(query, search_depth="basic"):
    try:
        resp = httpx.post(
            "https://api.tavily.com/search",
            json={
                "api_key": TAVILY_API_KEY,
                "query": query,
                "search_depth": search_depth,
                "max_results": 5,
                "include_answer": True,
            },
            timeout=15
        )
        data = resp.json()
        results = data.get("results", [])
        answer = data.get("answer", "")
        if not results:
            return "Ничего не найдено."
        text = ""
        if answer:
            text += f"Краткий ответ: {answer}\n\n"
        text += "Результаты:\n"
        for r in results[:4]:
            text += f"- {r.get('title', '')}\n  {r.get('url', '')}\n  {r.get('content', '')[:150]}...\n\n"
        return text
    except Exception as ex:
        return f"Ошибка поиска: {ex}"

async def transcribe_voice(file_path):
    try:
        with open(file_path, "rb") as f:
            audio_data = f.read()

        if len(audio_data) < 100:
            return "Ошибка: аудиофайл пустой или повреждён"

        # Конвертируем .oga → .mp3 через ffmpeg для надёжности
        import subprocess
        mp3_path = file_path.replace(".oga", ".mp3")
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", file_path, "-ar", "16000", "-ac", "1", "-b:a", "32k", mp3_path],
            capture_output=True, timeout=30
        )
        if result.returncode != 0:
            # ffmpeg недоступен — шлём .oga напрямую
            send_path = file_path
            send_name = "voice.oga"
            send_type = "audio/ogg"
        else:
            send_path = mp3_path
            send_name = "voice.mp3"
            send_type = "audio/mpeg"

        with open(send_path, "rb") as f:
            send_data = f.read()

        async with httpx.AsyncClient(timeout=60) as http:
            response = await http.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                files={"file": (send_name, send_data, send_type)},
                data={"model": "whisper-1", "language": "ru"},
            )

        print(f"[Whisper] status={response.status_code} body={response.text[:300]}")

        if response.status_code != 200:
            return f"Ошибка Whisper {response.status_code}: {response.text[:200]}"

        data = response.json()
        text = data.get("text", "").strip()
        if not text:
            return "Whisper вернул пустой текст — попробуй ещё раз"
        return text

    except Exception as ex:
        return f"Ошибка распознавания: {ex}"

TOOLS = [
    {
        "name": "web_search",
        "description": "Поиск в интернете. Используй для поиска кортов, тиров, картингов рядом с Ивантеевкой; книг и статей; координат адресов для такси; любой актуальной информации.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "search_depth": {"type": "string", "description": "basic или advanced"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "add_calendar_event",
        "description": "Добавить событие в Google Calendar — встречу или активность привязанную к времени.",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "date": {"type": "string", "description": "YYYY-MM-DD"},
                "time": {"type": "string", "description": "HH:MM"},
                "duration_hours": {"type": "number"}
            },
            "required": ["summary", "date", "time"]
        }
    },
    {
        "name": "delete_calendar_event",
        "description": "Удалить событие из Google Calendar.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string"},
                "event_name": {"type": "string"}
            },
            "required": ["date", "event_name"]
        }
    },
    {
        "name": "move_calendar_event",
        "description": "Перенести событие в Google Calendar.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string"},
                "event_name": {"type": "string"},
                "new_date": {"type": "string"},
                "new_time": {"type": "string"}
            },
            "required": ["date", "event_name", "new_date", "new_time"]
        }
    },
    {
        "name": "get_calendar_events",
        "description": "Получить события календаря на дату.",
        "input_schema": {
            "type": "object",
            "properties": {"date": {"type": "string"}},
            "required": ["date"]
        }
    },
    {
        "name": "add_todoist_task",
        "description": "Добавить задачу в Todoist — дела без конкретного времени.",
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {"type": "string"},
                "priority": {"type": "string", "description": "p1/p2/p3/p4"},
                "due_date": {"type": "string"}
            },
            "required": ["content", "priority"]
        }
    },
    {
        "name": "plan_day",
        "description": "Показать план дня: события в календаре + свободные блоки времени. Используй когда Михаил просит распланировать день, спрашивает что есть в расписании или когда видишь что ему нужно найти свободное время.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "YYYY-MM-DD"}
            },
            "required": ["date"]
        }
    },
    {
        "name": "get_todoist_tasks",
        "description": "Получить все задачи из Todoist.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "complete_todoist_task",
        "description": "Отметить задачу выполненной в Todoist.",
        "input_schema": {
            "type": "object",
            "properties": {"task_name": {"type": "string"}},
            "required": ["task_name"]
        }
    },
    {
        "name": "delete_todoist_task",
        "description": "Удалить задачу из Todoist.",
        "input_schema": {
            "type": "object",
            "properties": {"task_name": {"type": "string"}},
            "required": ["task_name"]
        }
    },
    {
        "name": "compose_message",
        "description": "Составить сообщение от имени ассистента Михаила Павловича Житарь для отправки другому человеку через Telegram. Используй когда Михаил просит написать/связаться/передать что-то кому-то. ВСЕГДА используй этот инструмент для исходящих сообщений — не пиши текст просто в чат.",
        "input_schema": {
            "type": "object",
            "properties": {
                "recipient_name": {"type": "string", "description": "Имя получателя (например: Артём, партнёр, клиент)"},
                "recipient_username": {"type": "string", "description": "Telegram username или номер телефона получателя (например: @artem_username или +79001234567)"},
                "message_text": {"type": "string", "description": "Полный текст сообщения. Начинай с приветствия и представления: Здравствуйте, меня зовут [имя получателя], я ассистент Михаила Павловича Житарь. Пишу по его поручению."},
                "message_purpose": {"type": "string", "description": "Краткое описание цели сообщения для отчёта Михаилу"}
            },
            "required": ["recipient_name", "recipient_username", "message_text", "message_purpose"]
        }
    },
    {
        "name": "update_todoist_task",
        "description": "Изменить задачу в Todoist.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_name": {"type": "string"},
                "new_content": {"type": "string"},
                "new_priority": {"type": "string"},
                "new_due_date": {"type": "string"}
            },
            "required": ["task_name"]
        }
    }
]

SYSTEM_PROMPT = (
    "Ты — персональный ИИ-ассистент Михаила Житаря. Говори на ты, коротко, без воды.\n"
    "НЕ используй markdown — никаких звёздочек, решёток, подчёркиваний. Только текст и эмодзи.\n\n"
    "ПРАВИЛО: КАЛЕНДАРЬ vs TODOIST\n"
    "Календарь = событие привязанное к времени (встреча, тренировка, поездка)\n"
    "Todoist = задача без конкретного времени (позвонить, написать, сделать что-то)\n\n"
    "Приоритеты Todoist:\n"
    "P1 — срочно+важно (деньги прямо сейчас)\n"
    "P2 — важно, не срочно (стратегия)\n"
    "P3 — обычные задачи\n"
    "P4 — низкий приоритет\n\n"
    "СВОБОДНЫЕ БЛОКИ В РАСПИСАНИИ\n"
    "Когда видишь свободный блок 1.5+ часа — предлагай 2-3 варианта чем заняться.\n"
    "Формат: назови варианты, спроси что выбирает.\n"
    "Когда выбирает — сразу ищи через web_search и присылай конкретные адреса, ссылки, контакты.\n"
    "Предлагай иногда что-то новое для кругозора.\n\n"
    "ЯНДЕКС ТАКСИ\n"
    "Известные адреса Михаила:\n"
    "- Дом: Ивантеевка, Голландский квартал, дом 17 → lat=55.970304, lon=37.874909\n"
    "- Работа/офис: Пушкино, Ярославское шоссе, 114 → lat=55.996300, lon=37.868790\n"
    "- Родители: Пушкино, проезд Чапаева, 9/11 → lat=55.988170, lon=37.852367\n"
    "\n"
    "Правило: определи откуда едет Михаил по контексту:\n"
    "- Пишет \"домой\", \"с работы\", \"из офиса\" → старт с работы (55.996300, 37.868790)\n"
    "- Пишет \"на работу\", \"в офис\", нет уточнения → старт из дома (55.970304, 37.874909)\n"
    "- Пишет \"от родителей\", \"с Чапаева\" → старт от родителей (55.988170, 37.852367)\n"
    "- Пишет \"к родителям\" → конец маршрута родители, старт определи по контексту\n"
    "\n"
    "Когда определил старт и конец:\n"
    "1. Если конечная точка не из известных — найди координаты через web_search\n"
    "2. Составь ссылку: https://3.redirect.appmetrica.yandex.com/route?start-lat=START_LAT&start-lon=START_LON&end-lat=END_LAT&end-lon=END_LON&appmetrica_tracking_id=1178268795219780156\n"
    "3. Пришли с текстом: Открыть маршрут в Яндекс Go\n\n"
    "ПРОФИЛЬ МИХАИЛА\n"
    "Возраст: 27 лет\n"
    "Адрес: Ивантеевка, Голландский квартал, дом 17\n"
    "Семья: жена Анна 25 лет, сын 1.3 года, дочка 2.5 года\n"
    "Бизнес: YStaler, оборот 35 млн/мес Wildberries, партнёрство 50/50\n"
    "Инвестиции: облигации, купоны, реинвестирование\n"
    "Режим: встаёт 8:00, цель — спать до 00:00\n"
    "Рабочие часы: пн 6ч, вт 5ч, ср 5ч, чт 4ч, пт 5ч\n"
    "Спорт (травма плеча — силовые нельзя): турник, пресс, кардио, теннис, настольный теннис\n"
    "Хочет попробовать: теннис, настольный теннис, тир\n"
    "Учёба: 1) ИИ 2) Продажи e-commerce 3) Маркетинг бренда 4) Публичная речь\n"
    "Хобби: охота, стрельба, компьютеры, баня, СПА, вейкборд, картинг, машины, пиво с друзьями\n\n"
    "ПРИОРИТЕТЫ БИЗНЕСА\n"
    "1. Wildberries — оборот и прибыль\n"
    "2. Сайт и Telegram — стратегия\n"
    "3. Тренеры и амбассадоры — долгосрочно\n"
    "4. Инвестиции — пассивный доход\n\n"
    "GTD: максимум 3 ключевые задачи в день. Если задачу может сделать кто-то другой — скажи прямо.\n"
    "Принцип: не разобраться с сайтом, а написать Артёму про домен.\n\n"
    "НАПИСАТЬ СООБЩЕНИЕ ОТ ИМЕНИ МИХАИЛА\n"
    "Когда Михаил просит написать кому-то — используй инструмент compose_message.\n"
    "Правила составления сообщений:\n"
    "1. Представляйся: 'Здравствуйте! Меня зовут [имя], я ассистент Михаила Павловича Житарь.'\n"
    "2. Тон — вежливый, деловой, конкретный. Без воды.\n"
    "3. Если цель — договориться о встрече: предложи конкретное время.\n"
    "4. Если нужно задать вопрос — задай его чётко, один-два максимум.\n"
    "5. Заканчивай: 'С уважением, ассистент Михаила Житарь'\n"
    "6. После составления — покажи черновик Михаилу и жди подтверждения.\n"
    "7. Если Михаил не указал username — спроси: 'На какой username/номер отправлять?'\n"
    "8. Не отправляй пока Михаил не скажет 'ок' или 'отправляй'."
)

user_histories = {}
# Хранит черновики сообщений ожидающих подтверждения
# {user_id: {"recipient": "@username", "text": "...", "context": "..."}}
pending_messages = {}

def build_tg_deeplink(username: str, text: str) -> str:
    """Формирует deeplink который открывает чат с готовым текстом."""
    import urllib.parse
    # Убираем @ если есть
    username = username.lstrip("@")
    encoded = urllib.parse.quote(text, safe="")
    return f"https://t.me/{username}?text={encoded}"

def compose_outgoing_message(recipient_name: str, recipient_username: str, context: str) -> str:
    """Составляет текст сообщения от имени ассистента Михаила."""
    # Это вызывается из Claude через tool — Claude сам составит текст
    # Функция просто форматирует финальное сообщение
    return f"Составляю сообщение для {recipient_name}..."

async def process_with_claude(user_id, message_text):
    if user_id not in user_histories:
        user_histories[user_id] = []

    tz = pytz.timezone("Europe/Moscow")
    now = datetime.now(tz)
    today_date = now.strftime("%Y-%m-%d")
    tomorrow_date = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    weekdays = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]

    calendar_context = ""
    if any(kw in message_text.lower() for kw in ["завтра", "план на завтра"]):
        calendar_context = "\n\n" + get_tomorrow_events()
    elif any(kw in message_text.lower() for kw in ["сегодня", "план на день", "утро", "вечер", "распланируй"]):
        calendar_context = "\n\n" + get_today_events()

    full_msg = f"{message_text}\n\n[Сегодня: {today_date} ({weekdays[now.weekday()]}). Завтра: {tomorrow_date}]{calendar_context}"
    user_histories[user_id].append({"role": "user", "content": full_msg})

    if len(user_histories[user_id]) > 20:
        user_histories[user_id] = user_histories[user_id][-20:]

    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        tools=TOOLS,
        messages=user_histories[user_id]
    )

    while response.stop_reason == "tool_use":
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                inp = block.input
                n = block.name
                if n == "web_search":
                    result = web_search(inp["query"], inp.get("search_depth", "basic"))
                elif n == "add_calendar_event":
                    result = add_event(inp["summary"], inp["date"], inp["time"], inp.get("duration_hours", 1))
                elif n == "delete_calendar_event":
                    eid, ename = find_event_id(inp["date"], inp["event_name"])
                    result = delete_event(eid) + f" ({ename})" if eid else f"Не найдено: {inp['event_name']}"
                elif n == "move_calendar_event":
                    eid, ename = find_event_id(inp["date"], inp["event_name"])
                    result = move_event(eid, inp["new_date"], inp["new_time"]) + f" ({ename})" if eid else f"Не найдено: {inp['event_name']}"
                elif n == "get_calendar_events":
                    result, _ = get_events_for_date(inp["date"])
                elif n == "add_todoist_task":
                    result = add_todoist_task(inp["content"], inp.get("priority", "p3"), inp.get("due_date"))
                elif n == "plan_day":
                    result = plan_day(inp["date"])
                elif n == "get_todoist_tasks":
                    result = get_todoist_tasks()
                elif n == "complete_todoist_task":
                    result = complete_todoist_task(inp["task_name"])
                elif n == "delete_todoist_task":
                    result = delete_todoist_task(inp["task_name"])
                elif n == "update_todoist_task":
                    result = update_todoist_task(inp["task_name"], inp.get("new_content"), inp.get("new_priority"), inp.get("new_due_date"))
                elif n == "compose_message":
                    # Claude составил текст — сохраняем черновик
                    pending_messages[user_id] = {
                        "recipient_name": inp.get("recipient_name", ""),
                        "recipient_username": inp.get("recipient_username", ""),
                        "text": inp["message_text"],
                    }
                    result = f"ЧЕРНОВИК_ГОТОВ: {inp['message_text']}"
                else:
                    result = "Неизвестный инструмент"
                tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": result})

        user_histories[user_id].append({"role": "assistant", "content": response.content})
        user_histories[user_id].append({"role": "user", "content": tool_results})
        response = client.messages.create(
            model="claude-sonnet-4-5", max_tokens=2000,
            system=SYSTEM_PROMPT, tools=TOOLS,
            messages=user_histories[user_id]
        )

    reply = remove_markdown(response.content[0].text)
    user_histories[user_id].append({"role": "assistant", "content": reply})
    return reply

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет, Михаил. Готов работать.\n\n"
        "Команды:\n"
        "/today — события на сегодня\n"
        "/tomorrow — события на завтра\n"
        "/week — события на неделю\n"
        "/tasks — задачи из Todoist\n"
        "/clear — сбросить историю\n"
        "/review — еженедельный GTD-обзор\n"
        "/todoist_check — диагностика Todoist\n\n"
        "Пишешь или говоришь — я здесь."
    )

async def today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(get_today_events())

async def tomorrow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(get_tomorrow_events())

async def week(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(get_week_events())

async def tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(get_todoist_tasks())

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip().lower()
    try:
        # Проверяем — есть ли черновик ожидающий подтверждения
        if user_id in pending_messages:
            draft = pending_messages[user_id]

            if text in ["ок", "окей", "отправляй", "да", "👍", "хорошо", "отправить", "го"]:
                # Подтверждено — строим deeplink и отправляем
                username = draft["recipient_username"].lstrip("@")
                link = build_tg_deeplink(username, draft["text"])
                del pending_messages[user_id]
                await update.message.reply_text(
                    f"✉️ Открой чат и нажми отправить:",
                    reply_markup=__import__("telegram").InlineKeyboardMarkup([
                        [__import__("telegram").InlineKeyboardButton(
                            f"📨 Написать {draft['recipient_name']}",
                            url=link
                        )]
                    ])
                )
                return

            elif text in ["отмена", "нет", "стоп", "cancel"]:
                del pending_messages[user_id]
                await update.message.reply_text("Отменено. Черновик удалён.")
                return

            else:
                # Михаил правит текст — обновляем черновик
                edit_prompt = (
                    f"Михаил хочет изменить черновик сообщения для {draft['recipient_name']}. "
                    f"Текущий текст: {draft['text']}\n\n"
                    f"Правка от Михаила: {update.message.text}\n\n"
                    f"Перепиши сообщение с учётом правки и используй инструмент compose_message."
                )
                reply = await process_with_claude(user_id, edit_prompt)
                # После правки — снова показываем черновик
                if user_id in pending_messages:
                    new_draft = pending_messages[user_id]
                    await update.message.reply_text(
                        f"✏️ Обновлённый черновик для {new_draft['recipient_name']} (@{new_draft['recipient_username']}):\n\n"
                        f"{new_draft['text']}\n\n"
                        f"Отправить? (ок / правь дальше / отмена)"
                    )
                else:
                    await update.message.reply_text(reply)
                return

        reply = await process_with_claude(user_id, update.message.text)

        # Если Claude использовал compose_message — показываем черновик на согласование
        if user_id in pending_messages:
            draft = pending_messages[user_id]
            await update.message.reply_text(
                f"✉️ Черновик для {draft['recipient_name']} (@{draft['recipient_username']}):\n\n"
                f"{draft['text']}\n\n"
                f"Отправить? (ок / правь / отмена)"
            )
        else:
            await update.message.reply_text(reply)

    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    try:
        tg_file = await context.bot.get_file(update.message.voice.file_id)
        with tempfile.NamedTemporaryFile(suffix=".oga", delete=False) as tmp:
            await tg_file.download_to_drive(tmp.name)
            text = await transcribe_voice(tmp.name)
        await update.message.reply_text(f"🎤 {text}")
        if "ошибка" not in text.lower() and "не удалось" not in text.lower():
            reply = await process_with_claude(user_id, text)
            await update.message.reply_text(reply)
    except Exception as e:
        await update.message.reply_text(f"Ошибка голосового: {e}")

async def todoist_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Диагностика Todoist — проверяет токен и создаёт тестовую задачу."""
    try:
        # Проверяем GET
        resp = httpx.get(f"{TODOIST_BASE}/tasks", headers=TODOIST_HEADERS, timeout=10)
        if resp.status_code != 200:
            await update.message.reply_text(f"❌ GET /tasks — {resp.status_code}: {resp.text[:200]}")
            return

        tasks = resp.json()
        # Создаём тестовую задачу
        headers = {**TODOIST_HEADERS, "Content-Type": "application/json"}
        add_resp = httpx.post(
            f"{TODOIST_BASE}/tasks",
            headers=headers,
            json={"content": "🧪 Тест бота — удали меня", "priority": 1},
            timeout=10
        )
        if add_resp.status_code in (200, 204):
            task_id = add_resp.json().get("id", "?")
            # Сразу удаляем тестовую задачу
            httpx.delete(f"{TODOIST_BASE}/tasks/{task_id}", headers=TODOIST_HEADERS, timeout=10)
            await update.message.reply_text(
                f"✅ Todoist работает\n"
                f"Задач сейчас: {len(tasks)}\n"
                f"Тестовая задача создана и удалена (id={task_id})"
            )
        else:
            await update.message.reply_text(
                f"❌ POST /tasks — {add_resp.status_code}:\n{add_resp.text[:300]}"
            )
    except Exception as e:
        await update.message.reply_text(f"Ошибка диагностики: {e}")

async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_histories[update.effective_user.id] = []
    await update.message.reply_text("История очищена.")

async def review(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        reply = await process_with_claude(update.effective_user.id, "Проведи со мной еженедельный обзор GTD. Задавай вопросы по одному.")
        await update.message.reply_text(reply)
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("today", today))
    app.add_handler(CommandHandler("tomorrow", tomorrow))
    app.add_handler(CommandHandler("week", week))
    app.add_handler(CommandHandler("tasks", tasks))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(CommandHandler("todoist_check", todoist_check))
    app.add_handler(CommandHandler("review", review))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Бот запущен...")
    app.run_polling()

if __name__ == "__main__":
    main()
