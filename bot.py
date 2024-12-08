from telegram.ext import Updater, CommandHandler, CallbackContext, MessageHandler, Filters
from telegram import Update
import sqlite3
import requests
import time
from ton import tl
from ton.utils import Address

# Конфигурация
TOKEN = "8085122191:AAEaej7Ara5GU6spLPVaNrUTQ7itN9ImK_c"  # Замените на ваш токен бота
TON_API_KEY = "0e10f6af497956d661e37858bd6a3c11f022ab3387e3cad0f30a99200e6e4732" # Замените на ваш Toncenter API key
JETTON_ROOT_ADDRESS = "EQDtDojKIWgJZvK7MpIx2nv6Q6EUJ5wUldvcwlRuGFOhG2F6"
MIN_TOKEN_AMOUNT = 10000000
GROUP_CHAT_ID = -4631633778  # Замените на ваш реальный ID группы
INVITE_LINK = "https://t.me/+gsHU_oQ-JhNhYmMy" # Замените на вашу ссылку для вступления

# Подключение к SQLite
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
    username TEXT
)
""")
conn.commit()

def is_admin_in_group(context: CallbackContext, user_id: int, group_id: int) -> bool:
    admins = context.bot.get_chat_administrators(group_id)
    for a in admins:
        if a.user.id == user_id:
            return True
    return False

def start(update: Update, context: CallbackContext):
    update.message.reply_text(
        f"Здравствуйте! Я ваш персональный VIP-консьерж, готовый помочь вам проверить наличие достаточного количества токенов для вступления в нашу приватную группу.\n\n"
        f"На данный момент для вступления требуется иметь не менее {MIN_TOKEN_AMOUNT} токенов.\n\n"
        f"Вы можете приобрести необходимое количество на DEX-биржах или через Blum.\n\n"
        f"Для начала, пожалуйста, привяжите свой TON-кошелёк, отправив мне в личных сообщениях команду:\n"
        f"/addwallet <TON_wallet>\n\n"
        f"После этого вы сможете использовать команду /check, чтобы узнать, достигли ли вы необходимого баланса. "
        f"Если всё в порядке, я сразу же предоставлю вам ссылку для вступления в группу!"
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

    cursor.execute("""
    INSERT OR REPLACE INTO users (user_id, group_id, ton_address, warning_time, last_balance, username)
    VALUES (?,?,?,?,?,?)
    """, (user_id, GROUP_CHAT_ID, wallet, None, None, username))
    conn.commit()

    # Добавляем пользователя в known_users, чтобы он был виден при /status
    cursor.execute("SELECT 1 FROM known_users WHERE user_id=? AND group_id=?", (user_id, GROUP_CHAT_ID))
    if not cursor.fetchone():
        cursor.execute("INSERT INTO known_users (user_id, group_id, username) VALUES (?,?,?)", (user_id, GROUP_CHAT_ID, username))
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
            "Отлично! Ваш баланс теперь соответствует минимальному количеству токенов.\n"
            f"Вот ваша ссылка для вступления: {INVITE_LINK}"
        )
    else:
        update.message.reply_text("Баланс по-прежнему ниже минимального. Пополните и попробуйте ещё раз.")

def decode_wallet_address_from_cell(cell_b64: str) -> str:
    # Декодируем base64 cell в Bytes, затем распаковываем BOC
    cell_data = tl.deserialize_boc(bytes.fromhex(tl.b64str_to_hex(cell_b64)))
    root_cell = cell_data[0]

    # Адрес хранится в первом рефе root_cell
    if len(root_cell.refs) == 0:
        return None

    addr_cell = root_cell.refs[0]
    slice_ = addr_cell.begin_parse()

    # anycast (1 бит)
    slice_.skip_bits(1)
    # type (2 бита)
    t = slice_.load_uint(2)
    if t != 2:
        return None
    is_bounceable = slice_.load_bit()
    is_test_only = slice_.load_bit()
    wc = slice_.load_int(8)
    addr_hash = slice_.load_bytes(32)

    address = Address(None, wc, addr_hash, is_bounceable=is_bounceable, is_test_only=is_test_only)
    return address.to_string(True, True, True)

def get_jetton_wallet_address(owner_address: str) -> str:
    params = {
        "address": JETTON_ROOT_ADDRESS,
        "method": "get_wallet_address",
        "stack": f'["{owner_address}"]',
        "api_key": TON_API_KEY
    }
    r = requests.get("https://toncenter.com/api/v2/runGetMethod", params=params, timeout=10)
    data = r.json()
    if not data.get("ok"):
        return None
    stack = data.get("result", {}).get("stack", [])
    if not stack:
        return None
    entry = stack[0]
    if entry[0] == "tvm_cell" and entry[1]:
        return decode_wallet_address_from_cell(entry[1])
    return None

def get_jetton_wallet_balance(wallet_address: str) -> float:
    params = {
        "address": wallet_address,
        "method": "get_wallet_data",
        "api_key": TON_API_KEY
    }
    r = requests.get("https://toncenter.com/api/v2/runGetMethod", params=params, timeout=10)
    data = r.json()
    if not data.get("ok"):
        return 0.0
    stack = data.get("result", {}).get("stack", [])
    # get_wallet_data обычно возвращает:
    # 0: balance (num)
    # 1: owner (slice)
    # 2: jetton (slice)
    if len(stack) > 0 and stack[0][0] == "num":
        raw_balance_str = stack[0][1]
        raw_balance = int(raw_balance_str)
        decimals = 9
        balance = raw_balance / (10**decimals)
        return balance
    return 0.0

def check_balance_for_user(ton_address: str) -> bool:
    try:
        jetton_wallet_addr = get_jetton_wallet_address(ton_address)
        if not jetton_wallet_addr:
            return False
        balance = get_jetton_wallet_balance(jetton_wallet_addr)
        return balance >= MIN_TOKEN_AMOUNT
    except:
        return False

def status_command(update: Update, context: CallbackContext):
    if not is_admin_in_group(context, update.effective_user.id, GROUP_CHAT_ID):
        update.message.reply_text("У вас нет прав для этой команды.")
        return

    total_count = context.bot.get_chat_member_count(GROUP_CHAT_ID)
    cursor.execute("SELECT COUNT(*) FROM users WHERE group_id = ? AND ton_address IS NOT NULL", (GROUP_CHAT_ID,))
    verified_count = cursor.fetchone()[0]
    not_verified_count = total_count - verified_count

    cursor.execute("SELECT user_id, username FROM known_users WHERE group_id = ?", (GROUP_CHAT_ID,))
    known = cursor.fetchall()
    known_ids = [k[0] for k in known]

    cursor.execute("SELECT user_id FROM users WHERE group_id = ? AND ton_address IS NOT NULL", (GROUP_CHAT_ID,))
    verified_users = [v[0] for v in cursor.fetchall()]

    not_verified_users = [k for k in known_ids if k not in verified_users]

    msg = f"Всего участников: {total_count}\n" \
          f"Верифицировано: {verified_count}\n" \
          f"Не верифицировано: {not_verified_count}\n\n"

    mentions = []
    for user_id in not_verified_users:
        cursor.execute("SELECT username FROM known_users WHERE user_id=? AND group_id=?", (user_id, GROUP_CHAT_ID))
        row = cursor.fetchone()
        if row and row[0]:
            mentions.append(f"@{row[0]}")

    if mentions:
        msg += "Не верифицированы:\n" + " ".join(mentions)
    else:
        msg += "Все известные пользователи верифицированы или нет данных."

    update.message.reply_text(msg)

def debug_command(update: Update, context: CallbackContext):
    if not is_admin_in_group(context, update.effective_user.id, GROUP_CHAT_ID):
        update.message.reply_text("У вас нет прав для этой команды.")
        return

    report = []
    if TOKEN:
        report.append("Токен бота: OK")
    else:
        report.append("Токен бота: ОШИБКА")

    if TON_API_KEY:
        report.append("TON API ключ: OK")
    else:
        report.append("TON API ключ: ОШИБКА")

    try:
        r = requests.get("https://toncenter.com/api/v2/getMasterchainInfo", params={"api_key": TON_API_KEY}, timeout=5)
        if r.status_code == 200:
            report.append("Toncenter API доступ: OK")
        else:
            report.append(f"Toncenter API доступ: ОШИБКА код {r.status_code}")
    except Exception as e:
        report.append(f"Toncenter API доступ: ОШИБКА {e}")

    if all("OK" in x for x in report):
        report.append("Работа стабильна и все хорошо!")
    else:
        report.append("Есть проблемы! См. выше.")

    update.message.reply_text("\n".join(report))

def new_member_handler(update: Update, context: CallbackContext):
    if update.effective_user:
        user_id = update.effective_user.id
        username = update.effective_user.username or update.effective_user.first_name
        cursor.execute("SELECT 1 FROM known_users WHERE user_id=? AND group_id=?", (user_id, GROUP_CHAT_ID))
        if not cursor.fetchone():
            cursor.execute("INSERT INTO known_users (user_id, group_id, username) VALUES (?,?,?)", (user_id, GROUP_CHAT_ID, username))
            conn.commit()

def faq_handler(update: Update, context: CallbackContext):
    if update.effective_chat.type == 'private':
        text = update.message.text.strip().lower()
        answers = {
            "привет": "Привет! Я ваш VIP-консьерж. Чем могу помочь?",
            "как дела": "У меня всё замечательно! Готов помочь вам с любыми вопросами.",
            "а что дальше": "Как ваш VIP-консьерж, рекомендую пополнить баланс токенов или использовать /check для проверки!",
            "а что делать": "Вы можете добавить свой кошелёк командой /addwallet, а затем использовать /check, чтобы получить доступ.",
            "что делать": "Вы можете добавить свой кошелёк командой /addwallet, а затем использовать /check, чтобы получить доступ."
        }

        for key, val in answers.items():
            if key in text:
                update.message.reply_text(val)
                return

        update.message.reply_text(
            "Я ваш VIP-консьерж и готов помочь. Спросите, что вас интересует, "
            "или используйте команду /addwallet для привязки кошелька и /check для проверки баланса."
        )

def check_balances(context: CallbackContext):
    # Можно реализовать логику периодической проверки баланса, если нужно
    pass

def delete_webhook_before_polling(updater):
    updater.bot.delete_webhook()

def main():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    delete_webhook_before_polling(updater)

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("addwallet", addwallet))
    dp.add_handler(CommandHandler("check", check_command))
    dp.add_handler(CommandHandler("status", status_command))
    dp.add_handler(CommandHandler("debug", debug_command))

    dp.add_handler(MessageHandler(Filters.chat(GROUP_CHAT_ID) & Filters.all, new_member_handler))
    dp.add_handler(MessageHandler(Filters.private & Filters.text & ~Filters.command, faq_handler))

    job_queue = updater.job_queue
    job_queue.run_repeating(check_balances, interval=1800, first=10)

    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
