import telebot
from telebot import types
import requests
import sqlite3
import time
import datetime

# ================== НАСТРОЙКИ ==================
BOT_TOKEN = "8544083372:AAF3cZ4jEtafdG2l6GBh7y2WkwTvkFflAmk"
WEBHOOK_URL = "https://n8n.devart.kz/webhook/telegram-ai"
ADMIN_ID = 1577850433

bot = telebot.TeleBot(BOT_TOKEN)

# ================== ТАРИФЫ (НЕ ТРОГАЮ) ==================
TARIFFS = {
    "Физ-Мат-Гео": {"price": 400, "subjects": ["Физика", "Математика", "География"]},
    "Хим-Био": {"price": 300, "subjects": ["Химия", "Биология"]},
    "Лит-Языки-История": {"price": 350, "subjects": ["Литература", "Языки", "История"]},
    "Остальные": {"price": 200, "subjects": ["Остальные"]},
    "Все вместе": {"price": 1100, "subjects": ["Все"]}
}

pending_checks = {}

# ================== SQLITE ==================
db = sqlite3.connect("bot.db", check_same_thread=False)
sql = db.cursor()

sql.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    subjects TEXT,
    sub_until INTEGER
)
""")

sql.execute("""
CREATE TABLE IF NOT EXISTS usage (
    user_id INTEGER,
    date TEXT,
    count INTEGER,
    PRIMARY KEY (user_id, date)
)
""")

sql.execute("""
CREATE TABLE IF NOT EXISTS cooldown (
    user_id INTEGER PRIMARY KEY,
    last_request INTEGER
)
""")

db.commit()

# ================== ВСПОМОГАТЕЛЬНЫЕ ==================
def is_subscribed(user_id):
    row = sql.execute(
        "SELECT subjects, sub_until FROM users WHERE user_id=?",
        (user_id,)
    ).fetchone()

    if not row:
        return False, None

    subjects, sub_until = row
    if int(time.time()) > sub_until:
        sql.execute("DELETE FROM users WHERE user_id=?", (user_id,))
        db.commit()
        return False, None

    return True, subjects.split(",")

MAX_FREE_REQUESTS = 3

def check_limits(user_id):
    today = datetime.date.today().isoformat()

    subscribed, _ = is_subscribed(user_id)

    if subscribed:
        row = sql.execute(
            "SELECT last_request FROM cooldown WHERE user_id=?",
            (user_id,)
        ).fetchone()

        if row and time.time() - row[0] < 60:
            return False, "⏳ Подожди 2 минуты между запросами"

        sql.execute(
            "REPLACE INTO cooldown (user_id, last_request) VALUES (?, ?)",
            (user_id, int(time.time()))
        )
        db.commit()
        return True, None

    row = sql.execute(
        "SELECT count FROM usage WHERE user_id=? AND date=?",
        (user_id, today)
    ).fetchone()

    used = row[0] if row else 0
    if used >= MAX_FREE_REQUESTS:
        return False, "⛔ Лимит 3 запроса в день без подписки"

    sql.execute(
        "REPLACE INTO usage (user_id, date, count) VALUES (?, ?, ?)",
        (user_id, today, used + 1)
    )
    db.commit()
    return True, None

# ================== START ==================
@bot.message_handler(commands=["start"])
def start(msg):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("⭐ Купить подписку", callback_data="subscribe"))
    kb.add(types.InlineKeyboardButton("📦 Моя подписка", callback_data="my_sub"))
    kb.add(types.InlineKeyboardButton("📊 Осталось запросов", callback_data="limits"))
    bot.send_message(msg.chat.id, "Привет! Я помогу с домашкой 📚", reply_markup=kb)

# ================== ТАРИФЫ ==================
@bot.callback_query_handler(func=lambda c: c.data == "subscribe")
def subscribe(call):
    kb = types.InlineKeyboardMarkup()
    for tariff in TARIFFS:
        kb.add(types.InlineKeyboardButton(
            f"{tariff} - {TARIFFS[tariff]['price']}₸",
            callback_data=f"tariff_{tariff}"
        ))
    bot.send_message(call.message.chat.id, "Выбери тариф:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("tariff_"))
def tariff_selected(call):
    tariff = call.data.replace("tariff_", "")
    pending_checks[call.message.chat.id] = tariff
    bot.send_message(
        call.message.chat.id,
        f"Ты выбрал «{tariff}» ({TARIFFS[tariff]['price']}₸)\nОтправь чек или скрин оплаты"
    )

# ================== ЧЕК ==================
@bot.message_handler(content_types=["photo", "document"])
def receive_check(msg):
    uid = msg.chat.id
    if uid not in pending_checks:
        return

    tariff = pending_checks[uid]

    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("✅ Одобрить", callback_data=f"approve_{uid}_{tariff}"),
        types.InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{uid}_{tariff}")
    )

    bot.copy_message(ADMIN_ID, uid, msg.message_id, reply_markup=kb)
    bot.send_message(uid, "✅ Чек отправлен на проверку")
    del pending_checks[uid]

# ================== АДМИН ==================
@bot.callback_query_handler(func=lambda c: c.data.startswith("approve_"))
def approve(call):
    if call.message.chat.id != ADMIN_ID:
        return

    _, uid, tariff = call.data.split("_", 2)
    uid = int(uid)

    subjects = TARIFFS[tariff]["subjects"]
    sub_until = int(time.time()) + 30 * 24 * 60 * 60

    if "Все" in subjects:
        subjects = ["Все"]

    sql.execute(
        "REPLACE INTO users (user_id, subjects, sub_until) VALUES (?, ?, ?)",
        (uid, ",".join(subjects), sub_until)
    )
    db.commit()

    bot.send_message(uid, f"🎉 Подписка «{tariff}» активна на 30 дней")
    bot.answer_callback_query(call.id, "Готово")
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("reject_"))
def reject(call):
    if call.message.chat.id != ADMIN_ID:
        return

    _, uid, tariff = call.data.split("_", 2)
    bot.send_message(int(uid), f"❌ Оплата «{tariff}» не подтверждена")
    bot.answer_callback_query(call.id, "Отклонено")
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id)

# ================== КНОПКИ ==================
@bot.callback_query_handler(func=lambda c: c.data == "my_sub")
def my_sub(call):
    ok, subjects = is_subscribed(call.message.chat.id)
    if not ok:
        bot.send_message(call.message.chat.id, "❌ Подписки нет")
        return

    row = sql.execute(
        "SELECT sub_until FROM users WHERE user_id=?",
        (call.message.chat.id,)
    ).fetchone()

    date = datetime.datetime.fromtimestamp(row[0]).strftime("%d.%m.%Y")
    bot.send_message(
        call.message.chat.id,
        f"✅ Подписка активна\n📚 Предметы: {', '.join(subjects)}\n⏳ До: {date}"
    )

@bot.callback_query_handler(func=lambda c: c.data == "limits")
def limits(call):
    today = datetime.date.today().isoformat()
    row = sql.execute(
        "SELECT count FROM usage WHERE user_id=? AND date=?",
        (call.message.chat.id, today)
    ).fetchone()

    used = row[0] if row else 0
    bot.send_message(call.message.chat.id, f"📊 Использовано сегодня: {used}/{MAX_FREE_REQUESTS}")

# ================== AI ==================
# ================== AI ==================
@bot.message_handler(func=lambda m: True)
def ai(msg):
    uid = msg.chat.id

    ok, reason = check_limits(uid)
    if not ok:
        bot.send_message(uid, reason)
        return

    wait = bot.send_message(uid, "🤖 ИИ думает…")

    try:
        # Получаем подписки пользователя
        subscribed, subjects = is_subscribed(uid)
        subscriptions = subjects if subscribed else []

        # Отправляем на n8n: текст и подписки
        payload = {
            "user_id": uid,
            "text": msg.text,
            "subscriptions": subscriptions
        }

        r = requests.post(WEBHOOK_URL, json=payload, timeout=20)
        data = r.json()

        bot.delete_message(uid, wait.message_id)

        # Если n8n вернул пустой ответ или отказ
        answer = data.get("answer", "")
        if not data.get("ok", True):
            bot.send_message(uid, data.get("reason", "⛔ Нет доступа по подписке"))
            return

        if not answer:
            bot.send_message(uid, "⚠️ Пустой ответ от ИИ")
            return

        # Отправляем ответ частями по 4000 символов
        for i in range(0, len(answer), 4000):
            bot.send_message(uid, answer[i:i+4000])

    except Exception as e:
        bot.delete_message(uid, wait.message_id)
        bot.send_message(uid, "⚠️ ИИ временно недоступен")
        bot.send_message(ADMIN_ID, f"AI error: {e}")


# ================== ЗАПУСК ==================
bot.infinity_polling()

