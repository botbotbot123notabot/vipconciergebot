import logging
import os
import threading
from telegram.ext import Updater, CommandHandler, CallbackContext, MessageHandler, Filters
from telegram import Update
import sqlite3
import requests
from flask import Flask

# Включаем логирование
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG  # Установлен на DEBUG для подробного логирования
)
logger = logging.getLogger(__name__)

# Конфигурация
TOKEN = "8085122191:AAEaej7Ara5GU6spLPVaNrUTQ7itN9ImK_c"  # Ваш Telegram Bot Token
TON_API_KEY = "0e10f6af497956d661e37858bd6a3c11f022ab3387e3cad0f30a99200e6e4732"  # Ваш TonAPI Key
JETTON_ROOT_ADDRESS = "0:ed0e88ca21680966f2bb329231da7bfa43a114279c1495dbdcc2546e1853a11b"  # Ваш Jetton Root Address в raw формате
MIN_TOKEN_AMOUNT = 600  # Минимальное количество токенов
GROUP_CHAT_ID = -4631633778  # Замените на ваш реальный ID группы
INVITE_LINK = "https://t.me/+gsHU_oQ-JhNhYmMy"  # Ваша ссылка для вступления
ADMIN_CHAT_ID = 687198654  # Замените на ваш Telegram ID для получения уведомлений об ошибках

# Подключение к SQLite (на Koyeb данные сохраняются только временно, рекомендуется использовать PostgreSQL для постоянного хранения)
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

cursor.execute("""
CREATE TABLE IF NOT EXISTS known_users (
    user_id INTEGER,
    group_id INTEGER,
    username TEXT,
    PRIMARY KEY (user_id, group_id)
)
""")
conn.commit()

# Инициализация Flask приложения
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def is_admin_in_group(context: CallbackContext, user_id: int, group_id: int) -> bool:
    try:
        admins = context.bot.get_chat_administrators(group_id)
        for a in admins:
            if a.user.id == user_id:
                return True
    except Exception as e:
        logger.error(f"Error checking admin status: {e}")
    return False

def start(update: Update, context: CallbackContext):
    update.message.reply_text(
        f"Здравствуйте! Я ваш персональный VIP-консьерж, готовый помочь проверить наличие достаточного количества токенов для вступления в нашу приватную группу.\n\n"
        f"На данный момент для вступления требуется иметь не менее {MIN_TOKEN_AMOUNT} токенов.\n\n"
        f"Вы можете приобрести необходимые токены на DEX-биржах или через Blum.\n\n"
        f"Сначала привяжите свой TON-кошелёк, отправив в ЛС боту команду:\n"
        f"/addwallet <TON_wallet>\n\n"
        f"После этого используйте /check для повторной проверки баланса. Если всё в порядке, я предоставлю ссылку для вступления!"
    )

def addwallet(update: Update, context: CallbackContext):
    if update.effective_chat.type != 'private':
        update.message.reply_text("Пожалуйста, отправьте команду /addwallet в ЛС боту.")
        return

    if len(context.args) == 0:
        update.message.reply_text("Использование: /addwallet <TON_wallet_address>")
        return

    wallet = context.args[0]
    user_id = update.message.from_user.id
    username = update.message.from_user.username or update.message.from_user.first_name

    # Проверка формата адреса (должен начинаться с '0:')
    if not wallet.startswith("0:"):
        update.message.reply_text("Неверный формат адреса кошелька. Пожалуйста, используйте raw формат: 0:<HEX>...")
        return

    logger.info(f"Adding/updating wallet for user_id={user_id}: {wallet}")

    cursor.execute("""
    INSERT OR REPLACE INTO users (user_id, group_id, ton_address, warning_time, last_balance, username)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (user_id, GROUP_CHAT_ID, wallet, None, None, username))
    conn.commit()

    # Добавим пользователя в known_users
    cursor.execute("SELECT 1 FROM known_users WHERE user_id=? AND group_id=?", (user_id, GROUP_CHAT_ID))
    if not cursor.fetchone():
        cursor.execute("INSERT INTO known_users (user_id, group_id, username) VALUES (?, ?, ?)",
                       (user_id, GROUP_CHAT_ID, username))
        conn.commit()

    balance_ok = check_balance_for_user(wallet)
    if balance_ok:
        update.message.reply_text(
            "Поздравляю! Ваш баланс токенов достаточен для вступления в группу.\n"
            f"Вот ваша ссылка для вступления: {INVITE_LINK}"
        )
    else:
        update.message.reply_text(
            "Ваш баланс токенов пока ниже необходимого.\n"
            "Пополните баланс и используйте команду /check, чтобы проверить снова."
        )

def check_command(update: Update, context: CallbackContext):
    if update.effective_chat.type != 'private':
        return
    user_id = update.message.from_user.id
    cursor.execute("SELECT ton_address FROM users WHERE user_id=? AND group_id=?", (user_id, GROUP_CHAT_ID))
    row = cursor.fetchone()
    if row is None:
        update.message.reply_text("Сначала добавьте кошелёк командой /addwallet <TON_wallet>")
        return

    wallet = row[0]
    balance_ok = check_balance_for_user(wallet)
    if balance_ok:
        update.message.reply_text(
            "Отлично! Ваш баланс соответствует минимальному количеству токенов.\n"
            f"Вот ваша ссылка для вступления: {INVITE_LINK}"
        )
    else:
        update.message.reply_text("Баланс ниже минимального. Пополните и попробуйте ещё раз.")

def check_balance_for_user(owner_address: str) -> bool:
    url = "https://toncenter.com/api/v3/jetton/wallets"
    params = {
        "jetton": JETTON_ROOT_ADDRESS,
        "owner": owner_address,
        "limit": 1,
        "api_key": TON_API_KEY
    }
    logger.info(f"Fetching balance for owner_address={owner_address} and jetton={JETTON_ROOT_ADDRESS}")
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        logger.debug(f"Received response from Toncenter: {data}")
    except requests.RequestException as e:
        logger.error(f"Error fetching balance for {owner_address}: {e}")
        return False

    jetton_wallets = data.get("jetton_wallets", [])
    if not jetton_wallets:
        logger.info(f"No jetton wallets found for owner {owner_address}")
        return False

    raw_balance_str = jetton_wallets[0].get("balance", "0")
    logger.debug(f"Raw balance string: {raw_balance_str}")

    try:
        raw_balance = int(raw_balance_str)
    except ValueError:
        logger.error(f"Invalid balance format: {raw_balance_str}")
        return False

    decimals = 9  # Проверьте, что это правильное значение для вашего jetton
    balance = raw_balance / (10**decimals)
    logger.info(f"Owner {owner_address} has balance: {balance} tokens")

    return balance >= MIN_TOKEN_AMOUNT

def status_command(update: Update, context: CallbackContext):
    if not is_admin_in_group(context, update.effective_user.id, GROUP_CHAT_ID):
        update.message.reply_text("У вас нет прав для этой команды.")
        return

    try:
        total_count = context.bot.get_chat_member_count(GROUP_CHAT_ID)
        logger.info(f"Total members in group {GROUP_CHAT_ID}: {total_count}")
    except Exception as e:
        logger.error(f"Error getting chat member count: {e}")
        total_count = "Unknown"

    cursor.execute("SELECT COUNT(*) FROM users WHERE group_id = ? AND ton_address IS NOT NULL", (GROUP_CHAT_ID,))
    verified_count = cursor.fetchone()[0]
    not_verified_count = total_count - verified_count if isinstance(total_count, int) else "Unknown"

    cursor.execute("SELECT user_id, username FROM known_users WHERE group_id = ?", (GROUP_CHAT_ID,))
    known = cursor
