import logging
import os
from telegram import Update, Sticker
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters, CommandHandler

# Конфигурация логирования
LOG_FILE = "bot.log"
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG,  # Уровень логирования установлен на DEBUG для подробных сообщений
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()  # Логирование также будет выводиться в консоль
    ]
)

logger = logging.getLogger(__name__)

# Константы
STICKER_EMOJI = "🫥"  # Эмодзи, привязанный к стикеру
RECORD_FILE = "record.txt"

# Глобальные переменные для текущей серии и рекорда
current_streak = 0
record = 0

def get_record():
    """Чтение текущего рекорда из файла."""
    if not os.path.exists(RECORD_FILE):
        logger.debug(f"Файл рекорда {RECORD_FILE} не существует. Устанавливаем рекорд в 0.")
        return 0
    try:
        with open(RECORD_FILE, "r", encoding='utf-8') as file:
            value = int(file.read())
            logger.debug(f"Текущий мировой рекорд загружен: {value}")
            return value
    except (ValueError, IOError) as e:
        logger.error(f"Ошибка при чтении рекорда из файла: {e}")
        return 0

def update_record(new_record):
    """Обновление рекорда в файле."""
    try:
        with open(RECORD_FILE, "w", encoding='utf-8') as file:
            file.write(str(new_record))
        logger.info(f"Мировой рекорд обновлен: {new_record}")
    except IOError as e:
        logger.error(f"Ошибка при записи рекорда в файл: {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global current_streak, record

    message = update.effective_message
    user = message.from_user.username or message.from_user.id
    logger.debug(f"Получено сообщение от пользователя @{user}: {message.text or 'Стикер'}")

    # Проверяем, является ли сообщение стикером
    if message.sticker:
        sticker: Sticker = message.sticker
        logger.debug(f"Сообщение содержит стикер с эмодзи: {sticker.emoji}")

        # Проверяем, соответствует ли эмодзи стикера нужному
        if STICKER_EMOJI in sticker.emoji:
            current_streak += 1
            logger.info(f"Найдена целевая серия стикеров. Текущая серия: {current_streak}")

            if current_streak > record:
                record = current_streak
                update_record(record)
                logger.info(f"Новый мировой рекорд установлен: {record}")
        else:
            logger.debug("Стикер не соответствует целевому эмодзи. Сбрасываем серию.")
            if current_streak > 0:
                await announce_streak(update, current_streak, record)
                current_streak = 0
    else:
        logger.debug("Сообщение не является стикером. Проверяем серию.")
        # Если сообщение не стикер, сбрасываем счетчик
        if current_streak > 0:
            await announce_streak(update, current_streak, record)
            current_streak = 0

async def announce_streak(update: Update, streak: int, record: int):
    """Отправка сообщения о завершении серии стикеров."""
    logger.info(f"Серия завершена. Всего стикеров: {streak}. Рекорд: {record}.")
    try:
        await update.message.reply_text(
            f"Серия стикеров закончилась!\nВсего было {streak}.\nТекущий мировой рекорд {record}."
        )
        logger.debug("Сообщение о серии успешно отправлено.")
    except Exception as e:
        logger.error(f"Ошибка при отправке сообщения о серии: {e}")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка ошибок."""
    logger.error(msg="Произошла ошибка при обработке обновления:", exc_info=context.error)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(f"Привет, {user.first_name}! Я готов считать стикеры.")

def main():
    global current_streak, record
    current_streak = 0
    record = get_record()

    # Вставка вашего токена бота
    BOT_TOKEN = '7794929885:AAHDiG47EN6wA250uWkvi0J1_JTWgCw-23g'

    try:
        application = ApplicationBuilder().token(BOT_TOKEN).build()
        logger.info("Бот успешно инициализирован.")
    except Exception as e:
        logger.critical(f"Не удалось инициализировать бота: {e}")
        return

    # Обработчик команды /start
    application.add_handler(CommandHandler("start", start))
    logger.debug("Обработчик команды /start добавлен.")

    # Обработчик всех сообщений
    application.add_handler(MessageHandler(filters.ALL, handle_message))
    logger.debug("Обработчик сообщений добавлен.")

    # Обработчик ошибок
    application.add_error_handler(error_handler)
    logger.debug("Обработчик ошибок добавлен.")

    # Запуск бота
    try:
        logger.info("Бот запущен и ожидает сообщений...")
        application.run_polling()
    except Exception as e:
        logger.critical(f"Произошла ошибка при запуске бота: {e}")

if __name__ == '__main__':
    main()
