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

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

def remove_markdown(text):
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'__(.+?)__', r'\1', text)
    text = re.sub(r'_(.+?)_', r'\1', text)
    return text

# ─── GOOGLE CALENDAR ───────────────────────────────────────

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

def add_event(summary, date_str, time_str, duration_hours=1):
    try:
        service = get_calendar_service()
        tz = pytz.timezone("Europe/Moscow")
        dt_start = tz.localize(datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M"))
        dt_end = dt_start + timedelta(hours=duration_hours)
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
        return "✅ Событие удалено из календаря."
    except Exception as ex:
        return f"Ошибка: {ex}"

def move_event(event_id, new_date_str, new_time_str):
    try:
        service = get_calendar_service()
        tz = pytz.timezone("Europe/Moscow")
        event = service.events().get(calendarId=GOOGLE_CALENDAR_ID, eventId=event_id).execute()
        duration = datetime.fromisoformat(event["end"]["dateTime"]) - datetime.fromisoformat(event["start"]["dateTime"])
        new_start = tz.localize(datetime.strptime(f"{new_date_str} {new_time_str}", "%Y-%m-%d %H:%M"))
        new_end = new_start + duration
        event["start"] = {"dateTime": new_start.isoformat(), "timeZone": "Europe/Moscow"}
        event["end"] = {"dateTime": new_end.isoformat(), "timeZone": "Europe/Moscow"}
        service.events().update(calendarId=GOOGLE_CALENDAR_ID, eventId=event_id, body=event).execute()
        return f"✅ Перенесено на {new_date_str} в {new_time_str}"
    except Exception as ex:
        return f"Ошибка: {ex}"

# ─── TODOIST ───────────────────────────────────────────────

TODOIST_BASE = "https://api.todoist.com/rest/v2"
TODOIST_HEADERS = {"Authorization": f"Bearer {TODOIST_API_KEY}"}

PRIORITY_MAP = {"p1": 4, "p2": 3, "p3": 2, "p4": 1}
PRIORITY_EMOJI = {4: "🔴", 3: "🟠", 2: "🔵", 1: "⚪"}

def get_todoist_tasks():
    try:
        resp = httpx.get(f"{TODOIST_BASE}/tasks", headers=TODOIST_HEADERS, timeout=10)
        tasks = resp.json()
        if not tasks:
            return "В Todoist задач нет."
        text = "📋 Задачи в Todoist:\n"
        for t in sorted(tasks, key=lambda x: -x.get("priority", 1)):
            emoji = PRIORITY_EMOJI.get(t.get("priority", 1), "⚪")
            due = f" (до {t['due']['date']})" if t.get("due") else ""
            text += f"{emoji} {t['content']}{due}\n"
        return text
    except Exception as ex:
        return f"Ошибка Todoist: {ex}"

def add_todoist_task(content, priority="p3", due_date=None):
    try:
        body = {
            "content": content,
            "priority": PRIORITY_MAP.get(priority.lower(), 2)
        }
        if due_date:
            body["due_date"] = due_date
        resp = httpx.post(f"{TODOIST_BASE}/tasks", headers=TODOIST_HEADERS, json=body, timeout=10)
        task = resp.json()
        emoji = PRIORITY_EMOJI.get(body["priority"], "⚪")
        return f"✅ Добавлено в Todoist: {emoji} {content}"
    except Exception as ex:
        return f"Ошибка: {ex}"

def complete_todoist_task(task_name_fragment):
    try:
        resp = httpx.get(f"{TODOIST_BASE}/tasks", headers=TODOIST_HEADERS, timeout=10)
        tasks = resp.json()
        for t in tasks:
            if task_name_fragment.lower() in t["content"].lower():
                httpx.post(f"{TODOIST_BASE}/tasks/{t['id']}/close", headers=TODOIST_HEADERS, timeout=10)
                return f"✅ Задача выполнена: {t['content']}"
        return f"Задача '{task_name_fragment}' не найдена."
    except Exception as ex:
        return f"Ошибка: {ex}"

def delete_todoist_task(task_name_fragment):
    try:
        resp = httpx.get(f"{TODOIST_BASE}/tasks", headers=TODOIST_HEADERS, timeout=10)
        tasks = resp.json()
        for t in tasks:
            if task_name_fragment.lower() in t["content"].lower():
                httpx.delete(f"{TODOIST_BASE}/tasks/{t['id']}", headers=TODOIST_HEADERS, timeout=10)
                return f"✅ Удалено из Todoist: {t['content']}"
        return f"Задача '{task_name_fragment}' не найдена."
    except Exception as ex:
        return f"Ошибка: {ex}"

def update_todoist_task(task_name_fragment, new_content=None, new_priority=None, new_due_date=None):
    try:
        resp = httpx.get(f"{TODOIST_BASE}/tasks", headers=TODOIST_HEADERS, timeout=10)
        tasks = resp.json()
        for t in tasks:
            if task_name_fragment.lower() in t["content"].lower():
                body = {}
                if new_content:
                    body["content"] = new_content
                if new_priority:
                    body["priority"] = PRIORITY_MAP.get(new_priority.lower(), t.get("priority", 2))
                if new_due_date:
                    body["due_date"] = new_due_date
                httpx.post(f"{TODOIST_BASE}/tasks/{t['id']}", headers=TODOIST_HEADERS, json=body, timeout=10)
                return f"✅ Задача обновлена: {new_content or t['content']}"
        return f"Задача '{task_name_fragment}' не найдена."
    except Exception as ex:
        return f"Ошибка: {ex}"

# ─── WHISPER ───────────────────────────────────────────────

async def transcribe_voice(file_path):
    try:
        with open(file_path, "rb") as f:
            audio_data = f.read()
        async with httpx.AsyncClient(timeout=30) as http_client:
            response = await http_client.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                files={"file": ("voice.mp3", audio_data, "audio/mpeg")},
                data={"model": "whisper-1", "language": "ru"},
            )
        result = response.json()
        return result.get("text", "Не удалось распознать речь")
    except Exception as ex:
        return f"Ошибка распознавания: {ex}"

# ─── TOOLS ─────────────────────────────────────────────────

TOOLS = [
    {
        "name": "add_calendar_event",
        "description": "Добавить событие в Google Calendar. Используй для встреч, созвонов, активностей привязанных к конкретному времени.",
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
                "date": {"type": "string", "description": "YYYY-MM-DD"},
                "event_name": {"type": "string"}
            },
            "required": ["date", "event_name"]
        }
    },
    {
        "name": "move_calendar_event",
        "description": "Перенести событие в Google Calendar на другую дату/время.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "Текущая дата YYYY-MM-DD"},
                "event_name": {"type": "string"},
                "new_date": {"type": "string", "description": "YYYY-MM-DD"},
                "new_time": {"type": "string", "description": "HH:MM"}
            },
            "required": ["date", "event_name", "new_date", "new_time"]
        }
    },
    {
        "name": "get_calendar_events",
        "description": "Получить события календаря на дату.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "YYYY-MM-DD"}
            },
            "required": ["date"]
        }
    },
    {
        "name": "add_todoist_task",
        "description": "Добавить задачу в Todoist. Используй для дел без конкретного времени — позвонить, написать, сделать что-то.",
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {"type": "string"},
                "priority": {"type": "string", "description": "p1 (срочно+важно), p2 (важно), p3 (средний), p4 (низкий)"},
                "due_date": {"type": "string", "description": "YYYY-MM-DD, опционально"}
            },
            "required": ["content", "priority"]
        }
    },
    {
        "name": "get_todoist_tasks",
        "description": "Получить все задачи из Todoist.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "complete_todoist_task",
        "description": "Отметить задачу в Todoist как выполненную.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_name": {"type": "string", "description": "Часть названия задачи"}
            },
            "required": ["task_name"]
        }
    },
    {
        "name": "delete_todoist_task",
        "description": "Удалить задачу из Todoist.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_name": {"type": "string"}
            },
            "required": ["task_name"]
        }
    },
    {
        "name": "update_todoist_task",
        "description": "Изменить задачу в Todoist — название, приоритет или срок.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_name": {"type": "string", "description": "Часть текущего названия задачи"},
                "new_content": {"type": "string"},
                "new_priority": {"type": "string", "description": "p1/p2/p3/p4"},
                "new_due_date": {"type": "string", "description": "YYYY-MM-DD"}
            },
            "required": ["task_name"]
        }
    }
]

SYSTEM_PROMPT = """Ты — персональный ИИ-ассистент Михаила Житаря. Говори на ты, коротко, без воды.

НЕ используй markdown — никаких звёздочек, решёток, подчёркиваний. Только текст и эмодзи.

━━━━━━━━━━━━━━━━━━━━━
ПРАВИЛО: КАЛЕНДАРЬ vs TODOIST
━━━━━━━━━━━━━━━━━━━━━

Календарь = событие привязанное ко времени:
- встреча, созвон, тренировка в 18:00, обед в 13:00, поездка

Todoist = задача без конкретного времени:
- позвонить поставщику, написать ТЗ, проверить отчёт, купить что-то

Если человек говорит "добавь задачу" — Todoist.
Если "запланируй встречу/событие на время" — Календарь.
Если непонятно — уточни одним вопросом.

Приоритеты Todoist:
🔴 P1 — срочно и важно (влияет на деньги прямо сейчас)
🟠 P2 — важно, не срочно (стратегия, развитие)
🔵 P3 — средний (обычные рабочие задачи)
⚪ P4 — низкий (когда-нибудь)

━━━━━━━━━━━━━━━━━━━━━
ПРОФИЛЬ МИХАИЛА
━━━━━━━━━━━━━━━━━━━━━

Возраст: 27 лет
Адрес: Московская область, Ивантеевка, Голландский квартал, дом 17 (для поиска мест рядом)

Семья:
- Жена Анна, 25 лет, женаты с 2020
- Сын, 1.3 года
- Дочка, 2.5 года

Бизнес: бренд одежды YStaler, оборот 35 млн/мес на Wildberries, партнёрство 50/50
Инвестиции: облигации, купоны, реинвестирование

Режим:
- Встаёт 8:00, ложится 00:00-03:00 (цель — до 00:00)
- Рабочие часы: пн 6ч, вт 5ч, ср 5ч, чт 4ч, пт 5ч

Спорт (травма плеча/спины — силовые нельзя):
- Можно: турник, пресс, кардио, теннис, настольный теннис
- Хочет попробовать: теннис, настольный теннис, тир

Учёба (приоритеты):
1. Искусственный интеллект
2. Продажи в e-commerce
3. Маркетинг и продвижение бренда
4. Публичная речь, коммуникации, словарный запас

Хобби: охота, стрельба, компьютеры, баня, СПА, вейкборд, картинг, машины, пиво с друзьями, инвестиции

━━━━━━━━━━━━━━━━━━━━━
ПЛАНИРОВАНИЕ ДНЯ
━━━━━━━━━━━━━━━━━━━━━

Когда просит распланировать день:
1. Получи занятые слоты из календаря
2. Свободное время раздели на блоки: Работа / Учёба / Спорт / Семья / Отдых / Сон
3. Предлагай конкретные активности из его интересов:
   "19:00-21:00 свободно — найти корт для тенниса рядом с Ивантеевкой?"
   "После обеда 30 минут — почитай про e-commerce продажи"
4. Учитывай рабочие часы по дням недели
5. Предлагай сам, не жди пока спросит

━━━━━━━━━━━━━━━━━━━━━
ПРИОРИТЕТЫ БИЗНЕСА
━━━━━━━━━━━━━━━━━━━━━
1. Wildberries — оборот и прибыль
2. Сайт и Telegram — стратегия
3. Тренеры и амбассадоры — долгосрочно
4. Инвестиции — пассивный доход

GTD: максимум 3 ключевые задачи в день. Если задачу может сделать кто-то другой — скажи прямо."""

user_histories = {}

async def process_with_claude(user_id, message_text):
    if user_id not in user_histories:
        user_histories[user_id] = []

    tz = pytz.timezone("Europe/Moscow")
    now = datetime.now(tz)
    today_date = now.strftime("%Y-%m-%d")
    tomorrow_date = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    weekdays = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
    today_weekday = weekdays[now.weekday()]

    calendar_context = ""
    if any(kw in message_text.lower() for kw in ["завтра", "план на завтра"]):
        calendar_context = "\n\n" + get_tomorrow_events()
    elif any(kw in message_text.lower() for kw in ["сегодня", "план на день", "утро", "вечер"]):
        calendar_context = "\n\n" + get_today_events()

    full_msg = f"{message_text}\n\n[Сегодня: {today_date} ({today_weekday}). Завтра: {tomorrow_date}]{calendar_context}"
    user_histories[user_id].append({"role": "user", "content": full_msg})

    if len(user_histories[user_id]) > 20:
        user_histories[user_id] = user_histories[user_id][-20:]

    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        tools=TOOLS,
        messages=user_histories[user_id]
    )

    while response.stop_reason == "tool_use":
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                inp = block.input
                name = block.name
                if name == "add_calendar_event":
                    result = add_event(inp["summary"], inp["date"], inp["time"], inp.get("duration_hours", 1))
                elif name == "delete_calendar_event":
                    eid, ename = find_event_id(inp["date"], inp["event_name"])
                    result = delete_event(eid) + f" ({ename})" if eid else f"Событие не найдено: {inp['event_name']}"
                elif name == "move_calendar_event":
                    eid, ename = find_event_id(inp["date"], inp["event_name"])
                    result = move_event(eid, inp["new_date"], inp["new_time"]) + f" ({ename})" if eid else f"Событие не найдено: {inp['event_name']}"
                elif name == "get_calendar_events":
                    result, _ = get_events_for_date(inp["date"])
                elif name == "add_todoist_task":
                    result = add_todoist_task(inp["content"], inp.get("priority", "p3"), inp.get("due_date"))
                elif name == "get_todoist_tasks":
                    result = get_todoist_tasks()
                elif name == "complete_todoist_task":
                    result = complete_todoist_task(inp["task_name"])
                elif name == "delete_todoist_task":
                    result = delete_todoist_task(inp["task_name"])
                elif name == "update_todoist_task":
                    result = update_todoist_task(inp["task_name"], inp.get("new_content"), inp.get("new_priority"), inp.get("new_due_date"))
                else:
                    result = "Неизвестный инструмент"
                tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": result})

        user_histories[user_id].append({"role": "assistant", "content": response.content})
        user_histories[user_id].append({"role": "user", "content": tool_results})
        response = client.messages.create(
            model="claude-sonnet-4-5", max_tokens=1000,
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
        "/review — еженедельный GTD-обзор\n\n"
        "Пишешь или говоришь — я на связи."
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
    try:
        reply = await process_with_claude(user_id, update.message.text)
        await update.message.reply_text(reply)
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    try:
        voice = update.message.voice
        tg_file = await context.bot.get_file(voice.file_id)
        with tempfile.NamedTemporaryFile(suffix=".oga", delete=False) as tmp:
            await tg_file.download_to_drive(tmp.name)
            text = await transcribe_voice(tmp.name)
        await update.message.reply_text(f"🎤 {text}")
        if "ошибка" not in text.lower() and "не удалось" not in text.lower():
            reply = await process_with_claude(user_id, text)
            await update.message.reply_text(reply)
    except Exception as e:
        await update.message.reply_text(f"Ошибка голосового: {e}")

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
    app.add_handler(CommandHandler("review", review))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Бот запущен...")
    app.run_polling()

if __name__ == "__main__":
    main()
