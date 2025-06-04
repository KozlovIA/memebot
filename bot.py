import logging
import os
import yaml
import datetime
from telegram import Update, InputFile
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, ChatMemberHandler

import numpy as np
import zipfile
import tempfile
import asyncio
import nest_asyncio

BOT_VERSION = "v1.0.2: disable_notification"

# --- Логирование ---
LOG_FILE = os.getcwd() + "/log.log"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# --- Глобальные переменные ---
CONFIG = {}
MEMES_FOLDER = ""
ADMINS = set()
ALLOW_USER_ADD = True
MEMES_DAY = {}
MEMES_LIST = []
MEME_INDEX = 0
MEME_ORDER = []

# --- Чтение конфига ---
def load_config(path=os.getcwd() + "/config.yaml"):
    global CONFIG, MEMES_FOLDER, ADMINS
    with open(path, 'r', encoding='utf-8') as f:
        CONFIG = yaml.safe_load(f)
    MEMES_FOLDER = os.getcwd() + CONFIG.get('memes_folder', '/memes')
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

# --- Подготовка и выбор случайного мема ---
def prepare_meme_order():
    global MEME_ORDER, MEME_INDEX
    MEME_ORDER = np.random.permutation(len(MEMES_LIST)).tolist()
    MEME_INDEX = 0

def get_random_meme():
    global MEME_INDEX, MEME_ORDER
    if not MEMES_LIST:
        return None
    if not MEME_ORDER or MEME_INDEX >= len(MEME_ORDER):
        prepare_meme_order()
    meme_idx = MEME_ORDER[MEME_INDEX]
    MEME_INDEX += 1
    return MEMES_LIST[meme_idx]

# --- Экспорт мемов в zip ---
def create_memes_zip():
    temp_zip = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    with zipfile.ZipFile(temp_zip.name, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for filename in os.listdir(MEMES_FOLDER):
            filepath = MEMES_FOLDER + "/" + filename
            if os.path.isfile(filepath):
                zipf.write(filepath, arcname=filename)
    return temp_zip.name

# --- Команды ---
async def export_memes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    username = f"{user.username}" if user.username else user.name
    if username in list(ADMINS):
        zip_path = create_memes_zip()
        try:
            await update.message.reply_document(document=open(zip_path, 'rb'), filename="memes.zip", disable_notification=True)
        finally:
            os.remove(zip_path)
    else:
        await update.message.reply_text("⛔ Эта команда доступна только администраторам.", disable_notification=True)

async def meme_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    count = len(MEMES_LIST)
    await update.message.reply_text(f"Сейчас доступно {count} мемов.", disable_notification=True)

def is_admin(username: str):
    return username in ADMINS

def reset_memes_day_if_needed():
    today = datetime.date.today()
    to_delete = [user_id for user_id, (fname, dt) in MEMES_DAY.items() if dt != today]
    for user_id in to_delete:
        del MEMES_DAY[user_id]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я бот для мемов.\n"
        "Команды:\n"
        "/random_meme - случайный мем\n"
        "/meme_of_the_day - мем дня\n"
        "В личке можно прислать мем, чтобы добавить в библиотеку.",
        disable_notification=True
    )

async def help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Команды:\n"
        "/random_meme - случайный мем\n"
        "/meme_of_the_day - мем дня\n"
        "/meme_count - количество мемов\n"
        "/export_memes - экспортировать все мемы (только для админов)",
        disable_notification=True
    )

async def random_meme(update: Update, context: ContextTypes.DEFAULT_TYPE):
    meme_file = get_random_meme()
    if not meme_file:
        await update.message.reply_text("Мемы не найдены :(", disable_notification=True)
        return
    path = MEMES_FOLDER + "/" + meme_file
    await update.message.reply_photo(photo=open(path, 'rb'), disable_notification=True)

async def meme_of_the_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_memes_day_if_needed()
    user_id = update.effective_user.id
    today = datetime.date.today()
    if user_id in MEMES_DAY:
        fname, dt = MEMES_DAY[user_id]
        if dt == today:
            path = MEMES_FOLDER + "/" + fname
            await update.message.reply_photo(photo=open(path, 'rb'), disable_notification=True)
            return
    meme_file = get_random_meme()
    if not meme_file:
        await update.message.reply_text("Мемы не найдены :(", disable_notification=True)
        return
    MEMES_DAY[user_id] = (meme_file, today)
    path = MEMES_FOLDER + "/" + meme_file
    await update.message.reply_photo(photo=open(path, 'rb'), disable_notification=True)

async def add_meme(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ALLOW_USER_ADD
    user = update.effective_user
    chat = update.effective_chat

    if chat.type != 'private':
        return

    if not is_admin(user.username) and not ALLOW_USER_ADD:
        await update.message.reply_text("Добавление мемов отключено для обычных пользователей.", disable_notification=True)
        return

    if not update.message.photo:
        await update.message.reply_text("Пожалуйста, отправьте мем в виде картинки.", disable_notification=True)
        return

    media_group_id = update.message.media_group_id

    if media_group_id:
        # Инициализация списка для хранения всех фото из альбома
        if "pending_photos" not in context.chat_data:
            context.chat_data["pending_photos"] = {}
        if media_group_id not in context.chat_data["pending_photos"]:
            context.chat_data["pending_photos"][media_group_id] = []

        # Сохраняем фото во временный список
        context.chat_data["pending_photos"][media_group_id].append(update.message)

        # Подождём, пока придут все фото (альбом отправляется не сразу)
        await asyncio.sleep(1.5)

        # Если это последнее сообщение из группы, сохраняем все фото
        photo_msgs = context.chat_data["pending_photos"].pop(media_group_id, [])
        saved_count = 0

        for msg in photo_msgs:
            photo = msg.photo[-1]
            file = await photo.get_file()
            ext = ".jpg"
            filename = f"{user.id}_{int(datetime.datetime.now().timestamp())}_{saved_count}{ext}"
            save_path = os.path.join(MEMES_FOLDER, filename)
            try:
                await file.download_to_drive(save_path)
                logger.info(f"Saved meme from album to {save_path}")
                saved_count += 1
            except Exception as e:
                logger.error(f"Failed to save meme from album: {e}")

        load_memes_list()
        await update.message.reply_text(f"✅ Добавлено {saved_count} мемов из альбома. Спасибо 😊", disable_notification=True)
    else:
        # Одиночное изображение
        photo = update.message.photo[-1]
        file = await photo.get_file()
        ext = ".jpg"
        filename = f"{user.id}_{int(datetime.datetime.now().timestamp())}{ext}"
        save_path = os.path.join(MEMES_FOLDER, filename)
        try:
            await file.download_to_drive(save_path)
            logger.info(f"Saved meme to {save_path}")
        except Exception as e:
            logger.error(f"Failed to save meme: {e}")
            await update.message.reply_text("❌ Ошибка при сохранении мема.", disable_notification=True)
            return
        load_memes_list()
        await update.message.reply_text("✅ Мем успешно добавлен! Спасибо 😊", disable_notification=True)

async def lock_mem_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ALLOW_USER_ADD
    user = update.effective_user
    if not is_admin(user.username):
        await update.message.reply_text("Команда доступна только администраторам.", disable_notification=True)
        return
    ALLOW_USER_ADD = False
    await update.message.reply_text("Добавление мемов отключено для обычных пользователей.", disable_notification=True)

async def unlock_mem_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ALLOW_USER_ADD
    user = update.effective_user
    if not is_admin(user.username):
        await update.message.reply_text("Команда доступна только администраторам.", disable_notification=True)
        return
    ALLOW_USER_ADD = True
    await update.message.reply_text("Добавление мемов разрешено для всех.", disable_notification=True)

async def version(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Версия бота: {BOT_VERSION}", disable_notification=True)

async def main():
    load_config()
    load_memes_list()
    application = ApplicationBuilder().token(CONFIG['token']).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help))
    application.add_handler(CommandHandler("meme_count", meme_count))
    application.add_handler(CommandHandler("random_meme", random_meme))
    application.add_handler(CommandHandler("meme_of_the_day", meme_of_the_day))
    application.add_handler(CommandHandler("lock_mem_add", lock_mem_add))
    application.add_handler(CommandHandler("unlock_mem_add", unlock_mem_add))
    application.add_handler(CommandHandler("export_memes", export_memes))
    application.add_handler(CommandHandler("version", version))
    application.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE, add_meme))
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    print("Bot is running")
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
