import logging
import os
import random
import yaml
import datetime
from telegram import Update, InputFile
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, ChatMemberHandler

# --- Логирование ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Глобальные переменные ---
CONFIG = {}
MEMES_FOLDER = ""
ADMINS = set()
ALLOW_USER_ADD = True  # По умолчанию разрешаем добавлять мемы
MEMES_DAY = {}  # user_id: (filename, date)
MEMES_LIST = []  # список мемов для быстрого доступа

# --- Чтение конфига ---
def load_config(path='config.yaml'):
    global CONFIG, MEMES_FOLDER, ADMINS
    with open(path, 'r', encoding='utf-8') as f:
        CONFIG = yaml.safe_load(f)
    MEMES_FOLDER = CONFIG.get('memes_folder', './memes')
    ADMINS.update(CONFIG.get('admins', []))
    if not os.path.exists(MEMES_FOLDER):
        os.makedirs(MEMES_FOLDER)
    logger.info(f"Config loaded. Memes folder: {MEMES_FOLDER}. Admins: {ADMINS}")

# --- Загрузка списка мемов ---
def load_memes_list():
    global MEMES_LIST
    MEMES_LIST = [
        f for f in os.listdir(MEMES_FOLDER)
        if os.path.isfile(os.path.join(MEMES_FOLDER, f)) and f.lower().endswith(('.jpg','.jpeg','.png','.gif'))
    ]
    logger.info(f"Loaded {len(MEMES_LIST)} memes.")

# --- Утилита для получения случайного мема ---
from collections import deque
import random

MEME_QUEUE = deque()

def get_random_meme():
    global MEME_QUEUE
    if not MEME_QUEUE:
        memes = MEMES_LIST.copy()
        random.shuffle(memes)
        MEME_QUEUE = deque(memes)
    return MEME_QUEUE.popleft()

async def meme_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    count = len(MEMES_LIST)
    await update.message.reply_text(f"Сейчас доступно {count} мемов.")

# --- Проверка админа ---
def is_admin(username: str):
    print(username)
    print(ADMINS)
    return username in ADMINS

# --- Сброс мемов дня (если дата изменилась) ---
def reset_memes_day_if_needed():
    today = datetime.date.today()
    to_delete = []
    for user_id, (fname, dt) in MEMES_DAY.items():
        if dt != today:
            to_delete.append(user_id)
    for user_id in to_delete:
        del MEMES_DAY[user_id]

# --- Обработчики команд ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я бот для мемов.\n"
        "Команды:\n"
        "/random_meme - случайный мем\n"
        "/meme_of_the_day - мем дня\n"
        "В личке можно прислать мем, чтобы добавить в библиотеку.\n"
        #"Админы могут использовать /lock_mem_add и /unlock_mem_add."
    )

async def help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я бот для мемов.\n"
        "Команды:\n"
        "/random_meme - случайный мем\n"
        "/meme_of_the_day - мем дня\n"
        "В личке можно прислать мем, чтобы добавить в библиотеку.\n"
        "Админы могут использовать /lock_mem_add и /unlock_mem_add."
    )

async def random_meme(update: Update, context: ContextTypes.DEFAULT_TYPE):
    meme_file = get_random_meme()
    if not meme_file:
        await update.message.reply_text("Мемы не найдены :(")
        return
    path = os.path.join(MEMES_FOLDER, meme_file)
    await update.message.reply_photo(photo=open(path, 'rb'))

async def meme_of_the_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Мем дня для каждого пользователя"""
    reset_memes_day_if_needed()
    user_id = update.effective_user.id
    today = datetime.date.today()
    if user_id in MEMES_DAY:
        fname, dt = MEMES_DAY[user_id]
        if dt == today:
            path = os.path.join(MEMES_FOLDER, fname)
            await update.message.reply_photo(photo=open(path, 'rb'))
            return
    # Нужно выбрать новый мем
    meme_file = get_random_meme()
    if not meme_file:
        await update.message.reply_text("Мемы не найдены :(")
        return
    MEMES_DAY[user_id] = (meme_file, today)
    path = os.path.join(MEMES_FOLDER, meme_file)
    await update.message.reply_photo(photo=open(path, 'rb'))

async def add_meme(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ALLOW_USER_ADD
    user = update.effective_user
    chat = update.effective_chat

    # Проверяем, что это личка
    if chat.type != 'private':
        return

    # Проверяем права на добавление мемов
    if not is_admin(user.username) and not ALLOW_USER_ADD:
        await update.message.reply_text("Добавление мемов отключено для обычных пользователей.")
        return

    if not update.message.photo:
        await update.message.reply_text("Пожалуйста, отправьте мем в виде картинки.")
        return

    photo = update.message.photo[-1]  # Берем самое лучшее качество
    file = await photo.get_file()
    # Генерируем уникальное имя
    ext = os.path.splitext(file.file_path)[1]
    filename = f"{user.id}_{int(datetime.datetime.now().timestamp())}{ext}"
    save_path = os.path.join(MEMES_FOLDER, filename)
    await file.download_to_drive(save_path)

    MEMES_LIST.append(filename)

    await update.message.reply_text("Мем успешно добавлен! Спасибо 😊")

async def lock_mem_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ALLOW_USER_ADD
    user = update.effective_user
    if not is_admin(user.username):
        await update.message.reply_text("Команда доступна только администраторам.")
        return
    ALLOW_USER_ADD = False
    await update.message.reply_text("Добавление мемов отключено для обычных пользователей.")

async def unlock_mem_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ALLOW_USER_ADD
    user = update.effective_user
    if not is_admin(user.username):
        await update.message.reply_text("Команда доступна только администраторам.")
        return
    ALLOW_USER_ADD = True
    await update.message.reply_text("Добавление мемов разрешено для всех.")

# --- Хендлеры команд в группе/беседе ---
async def group_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.lower()
    if text.startswith('/random_meme'):
        await random_meme(update, context)
    elif text.startswith('/meme_of_the_day'):
        await meme_of_the_day(update, context)

# --- Основной запуск ---
import asyncio
import nest_asyncio

async def main():
    load_config()
    load_memes_list()

    application = ApplicationBuilder().token(CONFIG['token']).build()

    # Добавляем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help))
    application.add_handler(CommandHandler("meme_count", meme_count))
    application.add_handler(CommandHandler("random_meme", random_meme))
    application.add_handler(CommandHandler("meme_of_the_day", meme_of_the_day))
    application.add_handler(CommandHandler("lock_mem_add", lock_mem_add))
    application.add_handler(CommandHandler("unlock_mem_add", unlock_mem_add))

    # В группах — только команды случайного мема и мем дня
    application.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE, add_meme))

    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    print("Bot is running")

    # Ждём Ctrl+C (работает в большинстве сред)
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        print("Stopping bot...")

    await application.updater.stop_polling()
    await application.stop()
    await application.shutdown()

if __name__ == '__main__':
    nest_asyncio.apply()
    asyncio.get_event_loop().run_until_complete(main())