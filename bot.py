import os
import anthropic
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes
from google.oauth2 import service_account
from googleapiclient.discovery import build
from datetime import datetime, timedelta
import pytz

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
GOOGLE_SERVICE_ACCOUNT_EMAIL = os.environ["GOOGLE_SERVICE_ACCOUNT_EMAIL"]
GOOGLE_PRIVATE_KEY = os.environ["GOOGLE_PRIVATE_KEY"].replace("\\n", "\n")
GOOGLE_CALENDAR_ID = os.environ["GOOGLE_CALENDAR_ID"]

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

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
            timeMin=start,
            timeMax=end,
            singleEvents=True,
            orderBy="startTime"
        ).execute()
        events = events_result.get("items", [])
        if not events:
            return "Сегодня событий в календаре нет."
        result = "📅 Сегодня в календаре:\n"
        for e in events:
            start_time = e["start"].get("dateTime", e["start"].get("date", ""))
            if "T" in start_time:
                t = datetime.fromisoformat(start_time).astimezone(tz).strftime("%H:%M")
            else:
                t = "весь день"
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
            timeMin=start,
            timeMax=end,
            singleEvents=True,
            orderBy="startTime"
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
        return f"Ошибка получения календаря: {ex}"

SYSTEM_PROMPT = """Ты — персональный ИИ-ассистент предпринимателя Михаила.

У тебя есть доступ к его Google Calendar. Когда Михаил спрашивает про расписание или планирует день — используй данные из календаря которые будут переданы в сообщении.

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
2. ПРОЯСНЕНИЕ — "Что конкретно нужно сделать?" Правило 2 минут.
3. ОРГАНИЗАЦИЯ — Сделать / Делегировать / Отложить / Удалить
4. ОБЗОР — еженедельно по пятницам
5. ДЕЙСТВИЕ — по контексту, времени, энергии

Принцип следующего действия: "Запустить сайт" — не действие. "Написать Артёму про домен" — действие.

Делегирование: масштаб бизнеса зависит от уровня задач собственника. Если задачу может сделать кто-то другой — скажи об этом прямо.

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

Итоги дня: что сделано / что отложил и почему / что завтра первым.

СТИЛЬ: конкретика, без воды, короткие ответы, списки. Если план плохой — говори прямо."""

user_histories = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет, Михаил. Готов работать.\n\n"
        "Скинь задачи на сегодня — расставлю приоритеты и составлю план.\n\n"
        "Команды:\n"
        "/today — события на сегодня\n"
        "/week — события на неделю\n"
        "/clear — сбросить историю\n"
        "/review — еженедельный GTD-обзор"
    )

async def today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(get_today_events())

async def week(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(get_week_events())

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_text = update.message.text

    if user_id not in user_histories:
        user_histories[user_id] = []

    calendar_context = ""
    keywords = ["план", "день", "сегодня", "календарь", "расписание", "встреч", "задач", "утро", "вечер"]
    if any(kw in user_text.lower() for kw in keywords):
        calendar_context = "\n\n" + get_today_events()

    user_histories[user_id].append({"role": "user", "content": user_text + calendar_context})

    if len(user_histories[user_id]) > 20:
        user_histories[user_id] = user_histories[user_id][-20:]

    try:
        response = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=1000,
            system=SYSTEM_PROMPT,
            messages=user_histories[user_id]
        )
        reply = response.content[0].text
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
    user_histories[user_id].append({"role": "user", "content": "Проведи со мной еженедельный обзор GTD. Задавай вопросы по одному."})
    try:
        response = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=1000,
            system=SYSTEM_PROMPT,
            messages=user_histories[user_id]
        )
        reply = response.content[0].text
        user_histories[user_id].append({"role": "assistant", "content": reply})
        await update.message.reply_text(reply)
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("today", today))
    app.add_handler(CommandHandler("week", week))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(CommandHandler("review", review))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Бот запущен...")
    app.run_polling()

if __name__ == "__main__":
    main()
