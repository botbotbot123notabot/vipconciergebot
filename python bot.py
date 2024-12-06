from telegram.ext import Updater, CommandHandler, CallbackContext
from telegram.ext import MessageHandler, Filters
from telegram import Update
import sqlite3
import requests
import time

# Телеграм токен бота
TOKEN = "8085122191:AAEaej7Ara5GU6spLPVaNrUTQ7itN9ImK_c"

# Toncenter API key
TON_API_KEY = "0e10f6af497956d661e37858bd6a3c11f022ab3387e3cad0f30a99200e6e4732"

JETTON_ROOT_ADDRESS = "EQDtDojKIWgJZvK7MpIx2nv6Q6EUJ5wUldvcwlRuGFOhG2F6"
MIN_TOKEN_AMOUNT = 10000000  # Минимальный баланс
CHECK_INTERVAL = 1800  # Проверка каждые 30 минут
WARNING_PERIOD = 36000  # 10 часов
GROUP_CHAT_ID = -4631633778  # Замените на реальный ID вашей группы

conn = sqlite3.connect('users.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER,
    group_id INTEGER,
    ton_address TEXT,
    warning_time INTEGER,
    last_balance INTEGER,
    username TEXT,
    PRIMARY KEY (user_id, group_id)
)
""")
conn.commit()

def start(update: Update, context: CallbackContext):
    update.message.reply_text(
        "Привет! Я бот для проверки баланса вашего TON токена. "
        "Отправьте мне ваш кошелек в ЛС командой /addwallet <TON_wallet>, "
        "чтобы участвовать в группе."
    )

def addwallet(update: Update, context: CallbackContext):
    if update.effective_chat.type != 'private':
        update.message.reply_text("Пожалуйста, отправьте команду /addwallet в личные сообщения боту.")
        return

    if len(context.args) == 0:
        update.message.reply_text("Использование: /addwallet <TON_wallet_address>")
        return

    wallet = context.args[0]
    user_id = update.message.from_user.id
    username = update.message.from_user.username or update.message.from_user.first_name

    cursor.execute("""
    INSERT OR REPLACE INTO users (user_id, group_id, ton_address, warning_time, last_balance, username) 
    VALUES (?,?,?,?,?,?)
    """, (user_id, GROUP_CHAT_ID, wallet, None, None, username))
    conn.commit()

    update.message.reply_text(f"Кошелек {wallet} успешно привязан к вашему аккаунту для группы {GROUP_CHAT_ID}.")

def get_jetton_balance(ton_address: str) -> int:
    # Здесь должен быть реальный вызов Toncenter API для получения баланса.
    # Примерный алгоритм (псевдо):
    #
    # 1. Получить адрес jetton-wallet для ton_address:
    #    Это зависит от контракта токена и метода получения jetton-wallet.
    #    Обычно используется метод runGetMethod для jetton root.
    #
    # Пример запроса (псевдо):
    # jetton_wallet_info = requests.get("https://toncenter.com/api/v2/runGetMethod", params={
    #     "address": JETTON_ROOT_ADDRESS,
    #     "method": "get_wallet_address",
    #     "stack": f"[\"{ton_address}\"]",
    #     "api_key": TON_API_KEY
    # }).json()
    #
    # # Извлечь jetton_wallet_addr из jetton_wallet_info...
    # jetton_wallet_addr = ... # получить из ответа
    #
    # if not jetton_wallet_addr:
    #     return 0
    #
    # 2. Получить баланс этого jetton-wallet:
    # balance_info = requests.get("https://toncenter.com/api/v2/runGetMethod", params={
    #     "address": jetton_wallet_addr,
    #     "method": "get_balance",
    #     "api_key": TON_API_KEY
    # }).json()
    #
    # raw_balance = balance_info.get("result", {}).get("balance", "0")
    # decimals = 9
    # real_balance = int(raw_balance) / (10**decimals)
    # return int(real_balance)

    # Пока вернем 0 для примера.
    return 0

def check_balances(context: CallbackContext):
    now = int(time.time())
    cursor.execute("SELECT user_id, ton_address, warning_time, last_balance, username FROM users WHERE group_id = ?", (GROUP_CHAT_ID,))
    rows = cursor.fetchall()

    for (user_id, ton_address, warning_time, last_balance, username) in rows:
        balance = get_jetton_balance(ton_address)
        cursor.execute("UPDATE users SET last_balance = ? WHERE user_id = ? AND group_id = ?", (balance, user_id, GROUP_CHAT_ID))
        conn.commit()

        if balance >= MIN_TOKEN_AMOUNT:
            # Баланс в норме, сбрасываем предупреждение, если было
            if warning_time is not None:
                cursor.execute("UPDATE users SET warning_time = NULL WHERE user_id = ? AND group_id = ?", (user_id, GROUP_CHAT_ID))
                conn.commit()
        else:
            # Баланс ниже минимального
            if warning_time is None:
                # Выдаем предупреждение один раз
                cursor.execute("UPDATE users SET warning_time = ? WHERE user_id = ? AND group_id = ?", (now, user_id, GROUP_CHAT_ID))
                conn.commit()

                user_mention = f"<a href=\"tg://user?id={user_id}\">@{username}</a>"
                context.bot.send_message(
                    chat_id=GROUP_CHAT_ID, 
                    text=(
                        f"{user_mention}, Ваш баланс токенов ниже минимального ({MIN_TOKEN_AMOUNT}) "
                        f"для нахождения в этой группе. Пожалуйста, пополните ваш баланс! У вас есть 10 часов."
                    ),
                    parse_mode='HTML'
                )
            else:
                # Предупреждение уже было, не спамим.
                if now - warning_time > WARNING_PERIOD:
                    # Время вышло – кикаем
                    context.bot.send_message(
                        chat_id=GROUP_CHAT_ID, 
                        text=f"Пользователь @{username} не пополнил баланс за 10 часов. Исключаю из группы."
                    )
                    try:
                        context.bot.kick_chat_member(chat_id=GROUP_CHAT_ID, user_id=user_id)
                    except Exception as e:
                        print(f"Не удалось кикнуть пользователя {user_id}: {e}")

def main():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("addwallet", addwallet))

    # Запуск периодической проверки
    job_queue = updater.job_queue
    job_queue.run_repeating(check_balances, interval=CHECK_INTERVAL, first=10)

    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
