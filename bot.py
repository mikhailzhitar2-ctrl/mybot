import os
import anthropic
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes
from google.oauth2 import service_account
from googleapiclient.discovery import build
from datetime import datetime, timedelta
import pytz
import re
import json

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
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

def get_today_events():
    try:
        service = get_calendar_service()
        tz = pytz.timezone("Europe/Moscow")
        now = datetime.now(tz)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        end = now.replace(hour=23, minute=59, second=59, microsecond=0).isoformat()
        events_result = service.events().list(
            calendarId=GOOGLE_CALENDAR_ID,
            timeMin=start, timeMax=end,
            singleEvents=True, orderBy="startTime"
        ).execute()
        events = events_result.get("items", [])
        if not events:
            return "Сегодня событий в календаре нет."
        result = "📅 Сегодня в календаре:\n"
        for e in events:
            start_time = e["start"].get("dateTime", e["start"].get("date", ""))
            t = datetime.fromisoformat(start_time).astimezone(pytz.timezone("Europe/Moscow")).strftime("%H:%M") if "T" in start_time else "весь день"
            result += f"• {t} — {e.get('summary', 'Без названия')}\n"
        return result
    except Exception as ex:
        return f"Ошибка получения календаря: {ex}"

def get_tomorrow_events():
    try:
        service = get_calendar_service()
        tz = pytz.timezone("Europe/Moscow")
        tomorrow = datetime.now(tz) + timedelta(days=1)
        start = tomorrow.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        end = tomorrow.replace(hour=23, minute=59, second=59, microsecond=0).isoformat()
        events_result = service.events().list(
            calendarId=GOOGLE_CALENDAR_ID,
            timeMin=start, timeMax=end,
            singleEvents=True, orderBy="startTime"
        ).execute()
        events = events_result.get("items", [])
        if not events:
            return "Завтра событий в календаре нет."
        result = "📅 Завтра в календаре:\n"
        for e in events:
            start_time = e["start"].get("dateTime", e["start"].get("date", ""))
            t = datetime.fromisoformat(start_time).astimezone(pytz.timezone("Europe/Moscow")).strftime("%H:%M") if "T" in start_time else "весь день"
            result += f"• {t} — {e.get('summary', 'Без названия')}\n"
        return result
    except Exception as ex:
        return f"Ошибка получения календаря: {ex}"

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
                dt = datetime.fromisoformat(start_time).astimezone(pytz.timezone("Europe/Moscow"))
                t = dt.strftime("%d.%m %H:%M")
            else:
                t = start_time
            result += f"• {t} — {e.get('summary', 'Без названия')}\n"
        return result
    except Exception as ex:
        return f"Ошибка получения календаря: {ex}"

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
        return f"Ошибка добавления события: {ex}"

TOOLS = [
    {
        "name": "add_calendar_event",
        "description": "Добавить событие в Google Calendar пользователя. Используй когда пользователь просит внести, добавить или записать что-то в календарь.",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "Название события"},
                "date": {"type": "string", "description": "Дата в формате YYYY-MM-DD, например 2026-06-05"},
                "time": {"type": "string", "description": "Время начала в формате HH:MM, например 15:00"},
                "duration_hours": {"type": "number", "description": "Длительность в часах, по умолчанию 1"}
            },
            "required": ["summary", "date", "time"]
        }
    }
]

SYSTEM_PROMPT = """Ты — персональный ИИ-ассистент предпринимателя Михаила.

У тебя есть доступ к его Google Calendar — ты можешь читать события и добавлять новые через инструмент add_calendar_event.

Когда Михаил просит внести событие в календарь — сразу используй инструмент, не спрашивай подтверждения лишний раз.

ВАЖНО: не используй markdown. Никаких звёздочек, никакого жирного текста. Только обычный текст и эмодзи.

Сегодняшняя дата для справки: используй её при расчёте дат "сегодня", "завтра", "в пятницу" и т.д.

═══════════════════════════════════════
КОНТЕКСТ: КТО ТАКОЙ МИХАИЛ
═══════════════════════════════════════

Михаил — предприниматель, 27 лет. Владеет брендом одежды YStaler (оборот 35 млн/мес на Wildberries). Параллельно инвестирует в облигации, строит собственный канал продаж через сайт и Telegram.

Приоритеты бизнеса:
1. Wildberries — основной оборот и прибыль
2. Собственный сайт и Telegram — стратегическое развитие
3. Тренеры и амбассадоры — долгосрочный канал
4. Инвестиции — пассивный доход

═══════════════════════════════════════
МЕТОДОЛОГИЯ: GTD + ДЕЛЕГИРОВАНИЕ
═══════════════════════════════════════

GTD — 5 шагов:
1. СБОР — фиксируй всё немедленно
2. ПРОЯСНЕНИЕ — что конкретно нужно сделать? Правило 2 минут.
3. ОРГАНИЗАЦИЯ — Сделать / Делегировать / Отложить / Удалить
4. ОБЗОР — еженедельно по пятницам
5. ДЕЙСТВИЕ — по контексту, времени, энергии

Принцип следующего действия: "Запустить сайт" — не действие. "Написать Артёму про домен" — действие.

Делегирование: если задачу может сделать кто-то другой — скажи об этом прямо.

═══════════════════════════════════════
КАК РАБОТАТЬ
═══════════════════════════════════════

Планирование дня:
- Уточни расплывчатые задачи
- Проверь что можно делегировать
- Максимум 3 ключевые задачи в день
- Учитывай события из календаря

Приоритеты:
🔴 Высокий — деньги или стратегия
🟡 Средний — важно, можно сдвинуть
⚪ Низкий — делегировать или удалить

Прокрастинация: не мотивируй, декомпозируй до шага на 10 минут.

СТИЛЬ: конкретика, без воды, короткие ответы, списки. Если план плохой — говори прямо."""

user_histories = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет, Михаил. Готов работать.\n\n"
        "Скинь задачи на сегодня — расставлю приоритеты и составлю план.\n\n"
        "Команды:\n"
        "/today — события на сегодня\n"
        "/tomorrow — события на завтра\n"
        "/week — события на неделю\n"
        "/clear — сбросить историю\n"
        "/review — еженедельный GTD-обзор"
    )

async def today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(get_today_events())

async def tomorrow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(get_tomorrow_events())

async def week(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(get_week_events())

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_text = update.message.text

    if user_id not in user_histories:
        user_histories[user_id] = []

    # Auto-attach calendar context
    calendar_context = ""
    tz = pytz.timezone("Europe/Moscow")
    today_date = datetime.now(tz).strftime("%Y-%m-%d")
    tomorrow_date = (datetime.now(tz) + timedelta(days=1)).strftime("%Y-%m-%d")

    tomorrow_keywords = ["завтра", "план на завтра", "задачи на завтра"]
    today_keywords = ["сегодня", "план на день", "утро", "вечер"]

    if any(kw in user_text.lower() for kw in tomorrow_keywords):
        calendar_context = f"\n\nСегодняшняя дата: {today_date}\nДата завтра: {tomorrow_date}\n" + get_tomorrow_events()
    elif any(kw in user_text.lower() for kw in today_keywords):
        calendar_context = f"\n\nСегодняшняя дата: {today_date}\n" + get_today_events()
    else:
        calendar_context = f"\n\nСегодняшняя дата: {today_date}"

    user_histories[user_id].append({"role": "user", "content": user_text + calendar_context})

    if len(user_histories[user_id]) > 20:
        user_histories[user_id] = user_histories[user_id][-20:]

    try:
        response = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=1000,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=user_histories[user_id]
        )

        # Handle tool use
        if response.stop_reason == "tool_use":
            tool_results = []
            assistant_content = response.content

            for block in response.content:
                if block.type == "tool_use":
                    if block.name == "add_calendar_event":
                        inp = block.input
                        result = add_event(
                            summary=inp["summary"],
                            date_str=inp["date"],
                            time_str=inp["time"],
                            duration_hours=inp.get("duration_hours", 1)
                        )
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result
                        })

            # Continue conversation with tool result
            user_histories[user_id].append({"role": "assistant", "content": assistant_content})
            user_histories[user_id].append({"role": "user", "content": tool_results})

            followup = client.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=500,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=user_histories[user_id]
            )
            reply = remove_markdown(followup.content[0].text)
            user_histories[user_id].append({"role": "assistant", "content": reply})
            await update.message.reply_text(reply)
        else:
            reply = remove_markdown(response.content[0].text)
            user_histories[user_id].append({"role": "assistant", "content": reply})
            await update.message.reply_text(reply)

    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_histories[user_id] = []
    await update.message.reply_text("История очищена. Начинаем заново.")

async def review(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_histories:
        user_histories[user_id] = []
    tz = pytz.timezone("Europe/Moscow")
    today_date = datetime.now(tz).strftime("%Y-%m-%d")
    user_histories[user_id].append({"role": "user", "content": f"Проведи со мной еженедельный обзор GTD. Задавай вопросы по одному.\n\nСегодняшняя дата: {today_date}"})
    try:
        response = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=1000,
            system=SYSTEM_PROMPT,
            messages=user_histories[user_id]
        )
        reply = remove_markdown(response.content[0].text)
        user_histories[user_id].append({"role": "assistant", "content": reply})
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
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Бот запущен...")
    app.run_polling()

if __name__ == "__main__":
    main()
