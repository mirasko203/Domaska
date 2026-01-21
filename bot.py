import telebot
import requests

BOT_TOKEN = "8544083372:AAF3cZ4jEtafdG2l6GBh7y2WkwTvkFflAmk"
N8N_WEBHOOK = "https://n8n.devart.kz/webhook/telegram-ai"

bot = telebot.TeleBot(BOT_TOKEN)

@bot.message_handler(func=lambda message: True)
def handle(message):
    user_id = message.chat.id
    text = message.text

    payload = {
        "user_id": user_id,
        "text": text
    }

    try:
        r = requests.post(N8N_WEBHOOK, json=payload, timeout=20)
        data = r.json()
        answer = data.get("answer", "Нет ответа от ИИ")
    except Exception as e:
        answer = "Ошибка при обработке запроса"

    bot.send_message(user_id, answer)

print("Бот запущен")
bot.infinity_polling()
