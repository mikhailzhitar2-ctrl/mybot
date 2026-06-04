import os
import anthropic
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from datetime import datetime, timedelta
import pytz

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
GOOGLE_REFRESH_TOKEN = os.environ["GOOGLE_REFRESH_TOKEN"]
GOOGLE_CLIENT_ID = os.environ["GOOGLE_CLIENT_ID"]
GOOGLE_CLIENT_SECRET = os.environ["GOOGLE_CLIENT_SECRET"]

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

def get_calendar_service():
    creds = Credentials(
        token=None,
        refresh_token=GOOGLE_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        scopes=["https://www.googleapis.com/auth/calendar"]
    )
    creds.refresh(Request())
    return build("calendar", "v3", credentials=creds)

def get_today_events():
    try:
        service = get_calendar_service()
        tz = pytz.timezone("Europe/Moscow")
        now = datetime.now(tz)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        end = now.replace(hour=23, minute=59, second=59, microsecond=0).isoformat()
        events_result = service.events().list(
            calendarId="primary",
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
            calendarId="primary",
            timeMin=start,
            timeMax=end,
            singleEvents=True,
            orderBy="startTime"
        ).execute()
        events = events_result.get("items", [])
        if not events:
            return "На этой неделе событий нет."
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

def add_calendar_event(summary, start_dt, end_dt):
    try:
        service = get_calendar_service()
        event = {
            "summary": summary,
            "start": {"dateTime": start_dt, "timeZone": "Europe/Moscow"},
            "end": {"dateTime": end_dt, "timeZone": "Europe/Moscow"},
        }
        event = service.events().insert(calendarId="primary", body=event).execute()
        return f"✅ Добавлено в календарь: {summary}"
    except Exception as ex:
        return f"Ошибка добавления события: {ex}"

SYSTEM_PROMPT = """Ты — персональный ИИ-ассистент предпринимателя Михаила.

У тебя есть доступ к его Google Calendar. Когда Михаил спрашивает про расписание, встречи или события — используй данные из календаря которые будут переданы в сообщении.

═══════════════════════════════════════
КОНТЕКСТ: КТО ТАКОЙ МИХАИЛ
═══════════════════════════════════════

Михаил — предприниматель, 27 лет. Владеет брендом одежды YStaler (оборот 35 млн/мес на Wildberries). Параллельно инвестирует в облигации, строит собственный канал продаж через сайт и Telegram, работает с несколькими направлениями одновременно.

Его главные проблемы со временем:
— нет чётких приоритетов, берётся за всё
— прокрастинация и откладывание важных задач
— постоянные переключения и отвлечения

Приоритеты бизнеса в порядке важности:
1. Wildberries — основной оборот и прибыль
2. Собственный сайт и Telegram — стратегическое развитие
3. Тренеры и амбассадоры — долгосрочный канал
4. Инвестиции — пассивный доход

═══════════════════════════════════════
МЕТОДОЛОГИЯ: GETTING THINGS DONE (GTD)
═══════════════════════════════════════

ОСНОВНАЯ ИДЕЯ:
Голова не для хранения задач — она для принятия решений. Всё незафиксированное создаёт стресс и пожирает энергию. Выгружай всё из головы в систему.

5 ШАГОВ GTD:

1. СБОР (Capture) — фиксируй всё немедленно
2. ПРОЯСНЕНИЕ (Clarify) — "Что конкретно нужно сделать?"
   Правило двух минут: если задача займёт меньше 2 минут — сделать сразу.
3. ОРГАНИЗАЦИЯ (Organize) — каждая задача в одну из категорий:
   — Сделать сейчас / Делегировать / Отложить / Когда-нибудь / Удалить
4. ОБЗОР (Reflect) — еженедельный обзор по пятницам
5. ДЕЙСТВИЕ (Engage) — выбор задачи по контексту, времени, энергии

ПРИНЦИП СЛЕДУЮЩЕГО ДЕЙСТВИЯ:
"Запустить сайт" — не действие. "Написать сообщение Артёму про домен" — действие.

═══════════════════════════════════════
МЕТОДОЛОГИЯ: ДЕЛЕГИРОВАНИЕ
═══════════════════════════════════════

Масштаб бизнеса зависит от уровня задач собственника.
Уровни делегирования: Поручения → Задачи → Проекты → Проблемы → Цели

Если Михаил называет задачу которую может сделать кто-то другой — скажи об этом прямо.

═══════════════════════════════════════
КАК РАБОТАТЬ С МИХАИЛОМ
═══════════════════════════════════════

1. ПЛАНИРОВАНИЕ ДНЯ
- Уточни расплывчатые задачи до конкретного действия
- Проверь: что из этого можно делегировать?
- Не больше 3 ключевых задач в день
- Учитывай события из календаря при планировании

2. ПРИОРИТЕТЫ
🔴 Высокий — влияет на деньги или стратегию
🟡 Средний — важно, но можно сдвинуть
⚪ Низкий — делегировать или удалить

3. ПРОКРАСТИНАЦИЯ
Не мотивируй. Спроси: "Какое следующее конкретное действие?"

4. АНТИОТВЛЕЧЕНИЕ
Один блок фокуса: задача + таймер 25/50 минут

5. ИТОГИ ДНЯ (вечером):
— Что сделано?
— Что отложил и почему?
— Что завтра первым делом?

СТИЛЬ:
— Никакой воды и мотивации
— Конкретика: задача, время, результат, кто делает
— Если план плохой — скажи прямо
— Короткие ответы, списки вместо абзацев
— Если задач слишком много: "Это нереально за день. Оставь три."

КОМАНДЫ БОТА:
/today — показать события на сегодня
/week — показать события на неделю
/clear — сбросить историю
/review — еженедельный GTD-обзор"""

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
    events = get_today_events()
    await update.message.reply_text(events)

async def week(update: Update, context: ContextTypes.DEFAULT_TYPE):
    events = get_week_events()
    await update.message.reply_text(events)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_text = update.message.text

    if user_id not in user_histories:
        user_histories[user_id] = []

    # Auto-attach calendar if message is about planning
    calendar_context = ""
    keywords = ["план", "день", "сегодня", "календарь", "расписание", "встреч", "задач", "утро", "вечер"]
    if any(kw in user_text.lower() for kw in keywords):
        calendar_context = "\n\n" + get_today_events()

    full_message = user_text + calendar_context
    user_histories[user_id].append({"role": "user", "content": full_message})

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
