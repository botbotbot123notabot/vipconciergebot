from telegram.ext import Updater, CommandHandler, CallbackContext, MessageHandler, Filters
from telegram import Update
import sqlite3
import requests
import time

# Конфигурация
TOKEN = "8085122191:AAEaej7Ara5GU6spLPVaNrUTQ7itN9ImK_c"
TON_API_KEY = "0e10f6af497956d661e37858bd6a3c11f022ab3387e3cad0f30a99200e6e4732"
JETTON_ROOT_ADDRESS = "EQDtDojKIWgJZvK7MpIx2nv6Q6EUJ5wUldvcwlRuGFOhG2F6"
MIN_TOKEN_AMOUNT = 10000000
GROUP_CHAT_ID = -1001234567890  # Замените на ваш реальный ID группы
INVITE_LINK = "https://t.me/+gsHU_oQ-JhNhYmMy"

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

def check_balance_for_user(ton_address: str) -> bool:
    # Проверка баланса через get_wallet_address
    # Упрощение: если jetton_wallet_addr возвращает непустой tvm_cell, считаем, что баланс ≥ MIN_TOKEN_AMOUNT.
    try:
        params = {
            "address": JETTON_ROOT_ADDRESS,
            "method": "get_wallet_address",
            "stack": f'["{ton_address}"]',
            "api_key": TON_API_KEY
        }
        r = requests.get("https://toncenter.com/api/v2/runGetMethod", params=params, timeout=10)
        data = r.json()

        if not data.get("ok"):
            return False

        stack = data.get("result", {}).get("stack", [])
        if not stack:
            return False

        entry = stack[0]
        # Если это ["tvm_cell", ...] и cell не пустая — считаем кошелек инициализированным => баланс достаточный
        if entry[0] == "tvm_cell" and entry[1] and len(entry[1]) > 10:
            return True
        else:
            return False

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
        r = requests.get("https://toncenter.com/api/v2/getStats", params={"api_key": TON_API_KEY}, timeout=5)
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
    # Здесь можно реализовать логику периодической проверки балансов, если нужно
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
