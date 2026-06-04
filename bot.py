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
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        dt_tz = tz.localize(dt)
        start = dt_tz.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        end = dt_tz.replace(hour=23, minute=59, second=59, microsecond=0).isoformat()
        events_result = service.events().list(
            calendarId=GOOGLE_CALENDAR_ID,
            timeMin=start, timeMax=end,
            singleEvents=True, orderBy="startTime"
        ).execute()
        events = events_result.get("items", [])
        if not events:
            return f"На {date_str} событий нет.", []
        result = f"📅 События на {date_str}:\n"
        event_list = []
        for i, e in enumerate(events):
            start_time = e["start"].get("dateTime", e["start"].get("date", ""))
            t = datetime.fromisoformat(start_time).astimezone(tz).strftime("%H:%M") if "T" in start_time else "весь день"
            name = e.get("summary", "Без названия")
            result += f"{i+1}. {t} — {name}\n"
            event_list.append({"id": e["id"], "summary": name, "time": t})
        return result, event_list
    except Exception as ex:
        return f"Ошибка: {ex}", []

def get_today_events():
    tz = pytz.timezone("Europe/Moscow")
    today = datetime.now(tz).strftime("%Y-%m-%d")
    text, _ = get_events_for_date(today)
    return text

def get_tomorrow_events():
    tz = pytz.timezone("Europe/Moscow")
    tomorrow = (datetime.now(tz) + timedelta(days=1)).strftime("%Y-%m-%d")
    text, _ = get_events_for_date(tomorrow)
    return text.replace(tomorrow, "завтра")

def get_week_events():
    try:
        service = get_calendar_service()
        tz = pytz.timezone("Europe/Moscow")
        now = datetime.now(tz)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        end = (now + timedelta(days=7)).replace(hour=23, minute=59, second=59).isoformat()
        events_result = service.events().list(
            calendarId=GOOGLE_CALENDAR_ID,
            timeMin=start, timeMax=end,
            singleEvents=True, orderBy="startTime"
        ).execute()
        events = events_result.get("items", [])
        if not events:
            return "На ближайшие 7 дней событий нет."
        result = "📅 Ближайшие 7 дней:\n"
        for e in events:
            start_time = e["start"].get("dateTime", e["start"].get("date", ""))
            if "T" in start_time:
                dt = datetime.fromisoformat(start_time).astimezone(tz)
                t = dt.strftime("%d.%m %H:%M")
            else:
                t = start_time
            result += f"• {t} — {e.get('summary', 'Без названия')}\n"
        return result
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
        return f"✅ Добавлено: {summary} — {date_str} в {time_str}"
    except Exception as ex:
        return f"Ошибка добавления: {ex}"

def delete_event(event_id):
    try:
        service = get_calendar_service()
        service.events().delete(calendarId=GOOGLE_CALENDAR_ID, eventId=event_id).execute()
        return "✅ Событие удалено."
    except Exception as ex:
        return f"Ошибка удаления: {ex}"

def move_event(event_id, new_date_str, new_time_str):
    try:
        service = get_calendar_service()
        tz = pytz.timezone("Europe/Moscow")
        event = service.events().get(calendarId=GOOGLE_CALENDAR_ID, eventId=event_id).execute()
        old_start = datetime.fromisoformat(event["start"]["dateTime"])
        old_end = datetime.fromisoformat(event["end"]["dateTime"])
        duration = old_end - old_start
        new_start = tz.localize(datetime.strptime(f"{new_date_str} {new_time_str}", "%Y-%m-%d %H:%M"))
        new_end = new_start + duration
        event["start"] = {"dateTime": new_start.isoformat(), "timeZone": "Europe/Moscow"}
        event["end"] = {"dateTime": new_end.isoformat(), "timeZone": "Europe/Moscow"}
        service.events().update(calendarId=GOOGLE_CALENDAR_ID, eventId=event_id, body=event).execute()
        return f"✅ Перенесено на {new_date_str} в {new_time_str}"
    except Exception as ex:
        return f"Ошибка переноса: {ex}"

def find_event_id(date_str, summary_fragment):
    _, events = get_events_for_date(date_str)
    for e in events:
        if summary_fragment.lower() in e["summary"].lower():
            return e["id"], e["summary"]
    return None, None

async def transcribe_voice(file_path):
    try:
        with open(file_path, "rb") as f:
            audio_data = f.read()
        async with httpx.AsyncClient() as http_client:
            response = await http_client.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                files={"file": ("voice.ogg", audio_data, "audio/ogg")},
                data={"model": "whisper-1", "language": "ru"},
                timeout=30
            )
        result = response.json()
        return result.get("text", "Не удалось распознать речь")
    except Exception as ex:
        return f"Ошибка распознавания: {ex}"

TOOLS = [
    {
        "name": "add_calendar_event",
        "description": "Добавить событие в Google Calendar. Используй когда пользователь просит внести, добавить или запланировать что-то.",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "Название события"},
                "date": {"type": "string", "description": "Дата YYYY-MM-DD"},
                "time": {"type": "string", "description": "Время HH:MM"},
                "duration_hours": {"type": "number", "description": "Длительность в часах, по умолчанию 1"}
            },
            "required": ["summary", "date", "time"]
        }
    },
    {
        "name": "delete_calendar_event",
        "description": "Удалить событие из Google Calendar. Сначала найди event_id через get_events_for_date.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "Дата события YYYY-MM-DD"},
                "event_name": {"type": "string", "description": "Часть названия события для поиска"}
            },
            "required": ["date", "event_name"]
        }
    },
    {
        "name": "move_calendar_event",
        "description": "Перенести событие на другую дату или время.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "Текущая дата события YYYY-MM-DD"},
                "event_name": {"type": "string", "description": "Часть названия события"},
                "new_date": {"type": "string", "description": "Новая дата YYYY-MM-DD"},
                "new_time": {"type": "string", "description": "Новое время HH:MM"}
            },
            "required": ["date", "event_name", "new_date", "new_time"]
        }
    },
    {
        "name": "get_calendar_events",
        "description": "Получить события календаря на конкретную дату.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "Дата YYYY-MM-DD"}
            },
            "required": ["date"]
        }
    }
]

SYSTEM_PROMPT = """Ты — персональный ИИ-ассистент Михаила Житаря. Говори на ты, коротко, без воды.

НЕ используй markdown — никаких звёздочек, решёток, подчёркиваний. Только обычный текст и эмодзи.

━━━━━━━━━━━━━━━━━━━━━
ПРОФИЛЬ МИХАИЛА
━━━━━━━━━━━━━━━━━━━━━

Возраст: 27 лет
Адрес: Московская область, Ивантеевка, Голландский квартал, дом 17, кв 35 (ориентир для поиска мест рядом)

Семья:
- Жена Анна, 25 лет, женаты с 2020
- Сын, 1.3 года
- Дочка, 2.5 года

Бизнес: бренд одежды YStaler, оборот 35 млн/мес на Wildberries, партнёрство 50/50
Инвестиции: облигации, купоны, реинвестирование

Режим:
- Встаёт в 8:00, ложится 00:00-03:00 (цель — до 00:00)
- Рабочие часы в день: пн 6ч, вт 5ч, ср 5ч, чт 4ч, пт 5ч

Спорт:
- Восстановление после травмы плеча/спины — силовые нельзя
- Можно: турник, пресс, кардио, теннис, настольный теннис
- Хочет: теннис, настольный теннис, тир (стрельба)

Учёба (приоритеты):
- Искусственный интеллект
- Продажи в e-commerce
- Маркетинг и продвижение бренда в интернете
- Публичная речь, коммуникации, словарный запас

Хобби и отдых:
- Охота, стрельба в тире
- Компьютерные игры
- Баня, СПА, массаж
- Вейкборд, плавание
- Картинг
- Машины
- Пиво с друзьями
- Инвестиции (как хобби тоже)

━━━━━━━━━━━━━━━━━━━━━
ПРИОРИТЕТЫ БИЗНЕСА
━━━━━━━━━━━━━━━━━━━━━
1. Wildberries — основной оборот и прибыль
2. Собственный сайт и Telegram — стратегическое развитие
3. Тренеры и амбассадоры — долгосрочный канал
4. Инвестиции — пассивный доход

━━━━━━━━━━━━━━━━━━━━━
ПЛАНИРОВАНИЕ ДНЯ
━━━━━━━━━━━━━━━━━━━━━

Когда Михаил говорит "распланируй день" или "что делать завтра":
1. Запроси занятые слоты (или используй календарь)
2. Остальное время раздели на блоки:
   - Работа (по приоритетам бизнеса)
   - Учёба (AI, продажи, маркетинг, речь)
   - Спорт (турник/пресс/кардио/теннис)
   - Семья (жена + дети)
   - Отдых (хобби из списка)
   - Сон (цель — 8 часов, до 00:00)
3. Предлагай конкретные активности из его интересов:
   - "В 19:00 у тебя 2 свободных часа — найти корт для тенниса рядом с Ивантеевкой?"
   - "18:00-19:00 — почитай 30 минут про e-commerce продажи"
   - "Суббота утром — сходи в тир, ближайший в Мытищах"
4. Предлагай сам, не жди пока спросит

━━━━━━━━━━━━━━━━━━━━━
МЕТОДОЛОГИЯ: GTD
━━━━━━━━━━━━━━━━━━━━━

Принцип следующего действия: "Запустить сайт" — не действие. "Написать Артёму про домен" — действие.

Приоритеты задач:
🔴 Высокий — деньги или стратегия
🟡 Средний — важно, можно сдвинуть
⚪ Низкий — делегировать или удалить

Делегирование: если задачу может сделать кто-то другой — скажи прямо.
Максимум 3 ключевые задачи в день.

━━━━━━━━━━━━━━━━━━━━━
РАБОТА С КАЛЕНДАРЁМ
━━━━━━━━━━━━━━━━━━━━━

Умеешь: добавлять, удалять, переносить события.
Когда просит удалить или перенести — сначала найди событие через get_calendar_events, потом действуй.
Не спрашивай лишних подтверждений — действуй сразу.

СТИЛЬ: коротко, конкретно, без воды. Если план плохой — скажи прямо."""

user_histories = {}

async def process_with_claude(user_id, message_text):
    if user_id not in user_histories:
        user_histories[user_id] = []

    tz = pytz.timezone("Europe/Moscow")
    now = datetime.now(tz)
    today_date = now.strftime("%Y-%m-%d")
    tomorrow_date = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    weekday_ru = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
    today_weekday = weekday_ru[now.weekday()]

    calendar_context = ""
    tomorrow_keywords = ["завтра", "план на завтра"]
    today_keywords = ["сегодня", "план на день", "утро", "вечер"]

    if any(kw in message_text.lower() for kw in tomorrow_keywords):
        calendar_context = "\n\n" + get_tomorrow_events()
    elif any(kw in message_text.lower() for kw in today_keywords):
        calendar_context = "\n\n" + get_today_events()

    full_message = f"{message_text}\n\n[Сегодня: {today_date}, {today_weekday}. Завтра: {tomorrow_date}]{calendar_context}"
    user_histories[user_id].append({"role": "user", "content": full_message})

    if len(user_histories[user_id]) > 20:
        user_histories[user_id] = user_histories[user_id][-20:]

    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        tools=TOOLS,
        messages=user_histories[user_id]
    )

    # Handle tool calls in a loop
    while response.stop_reason == "tool_use":
        tool_results = []
        assistant_content = response.content

        for block in response.content:
            if block.type == "tool_use":
                tool_input = block.input
                if block.name == "add_calendar_event":
                    result = add_event(
                        summary=tool_input["summary"],
                        date_str=tool_input["date"],
                        time_str=tool_input["time"],
                        duration_hours=tool_input.get("duration_hours", 1)
                    )
                elif block.name == "delete_calendar_event":
                    event_id, event_name = find_event_id(tool_input["date"], tool_input["event_name"])
                    if event_id:
                        result = delete_event(event_id)
                        result += f" ({event_name})"
                    else:
                        result = f"Событие '{tool_input['event_name']}' не найдено на {tool_input['date']}"
                elif block.name == "move_calendar_event":
                    event_id, event_name = find_event_id(tool_input["date"], tool_input["event_name"])
                    if event_id:
                        result = move_event(event_id, tool_input["new_date"], tool_input["new_time"])
                        result += f" ({event_name})"
                    else:
                        result = f"Событие '{tool_input['event_name']}' не найдено на {tool_input['date']}"
                elif block.name == "get_calendar_events":
                    text, _ = get_events_for_date(tool_input["date"])
                    result = text
                else:
                    result = "Неизвестный инструмент"

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result
                })

        user_histories[user_id].append({"role": "assistant", "content": assistant_content})
        user_histories[user_id].append({"role": "user", "content": tool_results})

        response = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=1000,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
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
        "/clear — сбросить историю\n"
        "/review — еженедельный GTD-обзор\n\n"
        "Можешь писать текстом или голосом."
    )

async def today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(get_today_events())

async def tomorrow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(get_tomorrow_events())

async def week(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(get_week_events())

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
        file = await context.bot.get_file(voice.file_id)
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            await file.download_to_drive(tmp.name)
            text = await transcribe_voice(tmp.name)

        await update.message.reply_text(f"🎤 Распознано: {text}")
        reply = await process_with_claude(user_id, text)
        await update.message.reply_text(reply)
    except Exception as e:
        await update.message.reply_text(f"Ошибка голосового: {e}")

async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_histories[user_id] = []
    await update.message.reply_text("История очищена.")

async def review(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    try:
        reply = await process_with_claude(user_id, "Проведи со мной еженедельный обзор GTD. Задавай вопросы по одному.")
        await update.message.reply_text(reply)
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("today", today))
    app.add_handler(CommandHandler("tomorrow", tomorrow))
    app.add_handler(CommandHandler("week", week))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(CommandHandler("review", review))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Бот запущен...")
    app.run_polling()

if __name__ == "__main__":
    main()
