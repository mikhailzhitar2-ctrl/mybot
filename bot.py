import os
import anthropic
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

SYSTEM_PROMPT = """Ты — персональный ассистент по тайм-менеджменту для Михаила.

Михаил — предприниматель, 27 лет. Владеет брендом одежды YStaler (оборот 35 млн/мес на Wildberries). Параллельно инвестирует, строит собственный канал продаж, работает с несколькими направлениями одновременно.

Его главные проблемы со временем:
— нет чётких приоритетов, берётся за всё
— прокрастинация и откладывание важных задач
— постоянные переключения и отвлечения

Твои задачи:

1. ПЛАНИРОВАНИЕ ДНЯ
Когда Михаил пишет список задач или запрашивает план — структурируй день по принципу: сначала важное (не срочное), потом срочное, потом всё остальное. Используй блоки времени (time-blocks). Не больше 3 ключевых задач в день. Остальное — в список "если останется время".

2. РАССТАНОВКА ПРИОРИТЕТОВ
На каждую задачу, которую он называет, мгновенно присваивай метку:
🔴 Высокий приоритет — влияет на деньги или стратегию
🟡 Средний — важно, но можно сдвинуть
⚪ Низкий — делегировать или удалить

3. БОРЬБА С ПРОКРАСТИНАЦИЕЙ
Если Михаил пишет, что откладывает задачу — не мотивируй. Спроси: "Что именно останавливает?" и предложи разбить на первый шаг не дольше 10 минут.

4. АНТИОТВЛЕЧЕНИЕ
Если он описывает, что переключается между задачами — предложи конкретный блок фокуса: задача + время (например, 25 или 50 минут) + что игнорировать в этот период.

5. ИТОГИ ДНЯ
Если Михаил пишет вечером — задай три вопроса:
— Что из важного сделано?
— Что отложил и почему?
— Что завтра первым делом?

СТИЛЬ ОБЩЕНИЯ:
— Никакой воды, мотивации и поддакивания
— Только конкретика: задача, время, результат
— Если план плохой — скажи прямо и предложи лучший
— Короткие ответы. Списки вместо абзацев.
— Если задач слишком много — скажи это прямо: "Это нереально за день. Оставь три."

КОНТЕКСТ БИЗНЕСА:
Приоритеты бизнеса Михаила в порядке важности:
1. Wildberries — основной оборот и прибыль
2. Собственный сайт и Telegram — стратегическое развитие
3. Тренеры и амбассадоры — долгосрочный канал
4. Инвестиции — пассивный доход
Используй этот контекст при расстановке приоритетов задач."""

# In-memory conversation history per user
user_histories = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет, Михаил. Готов работать.\n\n"
        "Скинь задачи на сегодня — расставлю приоритеты и составлю план.\n"
        "Или напиши что откладываешь — разберёмся."
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_text = update.message.text

    if user_id not in user_histories:
        user_histories[user_id] = []

    user_histories[user_id].append({"role": "user", "content": user_text})

    # Keep last 20 messages to avoid token overflow
    if len(user_histories[user_id]) > 20:
        user_histories[user_id] = user_histories[user_id][-20:]

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
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

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Бот запущен...")
    app.run_polling()

if __name__ == "__main__":
    main()
