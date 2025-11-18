import logging
import os
import yaml
import datetime
from telegram import Update, InputFile
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, ChatMemberHandler

import zipfile
import tempfile
import asyncio
import nest_asyncio
import socket
import requests
import base64
from io import BytesIO

# Импорт модулей для работы с мемами и MongoDB
from source import meme_manager
from source.mongo_manager import MongoManager

BOT_VERSION = "v4.2: MongoDB integration. Stream export ZIP_STORED"

# --- Логирование ---
LOG_FILE = os.getcwd() + "/log/log.log"

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
CONFIG_PATH = os.path.join(os.getcwd(), "config.yaml")
EDITORS = set()
CONTROL_PANEL_URL = None
CONTROL_PANEL_PORT = 8501
CONFIG = {}
MEMES_FOLDER = ""
ADMINS = set()
ALLOW_USER_ADD = True
# Глобальные переменные MEMES_DAY, MEMES_LIST, MEME_INDEX, MEME_ORDER, LAST_MEMES_COUNT
# теперь хранятся в MongoDB через meme_manager и mongo_manager

async def ensure_memes_count_async():
    """Асинхронная оболочка над ensure_memes_count_is_actual()."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, meme_manager.ensure_memes_count_is_actual)

def get_server_ip():
    try:
        # Пробуем получить внешний IP (если есть интернет)
        return requests.get("https://api.ipify.org").text
    except Exception:
        # fallback — локальный IP
        return socket.gethostbyname(socket.gethostname())

SERVER_IP = get_server_ip()

# --- Чтение конфига ---
def save_config(path=CONFIG_PATH):
    """Сохраняет CONFIG обратно в файл (используется при добавлении editors)."""
    try:
        with open(path, 'w', encoding='utf-8') as f:
            yaml.safe_dump(CONFIG, f, allow_unicode=True)
        logger.info("Config saved.")
    except Exception as e:
        logger.error(f"Failed to save config: {e}")

# --- Обновление конфига ---
def load_config(path=CONFIG_PATH):
    global CONFIG, MEMES_FOLDER, ADMINS, EDITORS, CONTROL_PANEL_URL, CONTROL_PANEL_PORT
    with open(path, 'r', encoding='utf-8') as f:
        CONFIG = yaml.safe_load(f) or {}
    MEMES_FOLDER = os.getcwd() + CONFIG.get('memes_folder', '/memes')
    ADMINS.update(CONFIG.get('admins', []))
    EDITORS.update(CONFIG.get('editors', []))
    CONTROL_PANEL_URL = CONFIG.get('control_panel_url', "") or None
    CONTROL_PANEL_PORT = int(CONFIG.get('control_panel_port', 8501))
    if not os.path.exists(MEMES_FOLDER):
        os.makedirs(MEMES_FOLDER)
    # Устанавливаем папку с мемами в meme_manager
    meme_manager.set_memes_folder(MEMES_FOLDER)
    # Синхронизируем файлы из папки с БД при загрузке конфига
    # meme_manager.sync_memes_with_db()
    logger.info(f"Config loaded. Memes folder: {MEMES_FOLDER}. Admins: {ADMINS}. Editors: {EDITORS}")

# --- Проверки прав ---
def is_admin(username: str) -> bool:
    return username in ADMINS

def is_editor(username: str) -> bool:
    return username in EDITORS

def is_admin_or_editor(username: str) -> bool:
    return is_admin(username) or is_editor(username)

# Функции load_memes_list, prepare_meme_order, get_random_meme
# теперь находятся в source/meme_manager.py


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
        zip_path = meme_manager.create_memes_zip_from_db_stream()
        try:
            with open(zip_path, 'rb') as f:
                await update.message.reply_document(
                    document=f,
                    filename="memes.zip",
                    disable_notification=True
                )
        finally:
            os.remove(zip_path)
    else:
        await update.message.reply_text("⛔ Эта команда доступна только администраторам.", disable_notification=True)

async def meme_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure_memes_count_async()   # NEW
    count = meme_manager.get_meme_count()
    await update.message.reply_text(f"Сейчас доступно {count} мемов.", disable_notification=True)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я бот для мемов.\n"
        "Команды:\n"
        "/random_meme - случайный мем\n"
        "/meme_of_the_day - мем дня\n"
        "В личке можно прислать мем, чтобы добавить в библиотеку.",
        disable_notification=True
    )

# --- Справка для обычных пользователей ---
async def help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Команды:\n"
        "/random_meme - случайный мем\n"
        "/meme_of_the_day - мем дня\n"
        "/meme_count - количество мемов\n"
        "/help_admins - "
        "В личке можно прислать мем, чтобы добавить в библиотеку.",
        disable_notification=True
    )


# --- Справка для админов и редакторов ---
async def help_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Админские и редакторские команды:\n"
        "/export_memes - экспортировать все мемы\n"
        "/add_editor <username> - добавить редактора\n"
        "/remove_editor <username> - удалить редактора\n"
        "/control_panel - ссылка на панель мемов\n"
        "/lock_mem_add - запретить добавление мемов пользователям\n"
        "/unlock_mem_add - разрешить добавление мемов пользователям\n"
        "/shuffle_memes - перемешать все мемы\n"
        "/version - версия бота",
        disable_notification=True
    )

async def random_meme(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # meme_manager.ensure_memes_count_is_actual()
    await ensure_memes_count_async()   # NEW
    image, meme_id = meme_manager.get_random_meme()
    await update.message.reply_photo(
        photo=image,
        disable_notification=True
    )


async def meme_of_the_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure_memes_count_async()   # NEW

    user_id = update.effective_user.id
    image = meme_manager.get_user_meme_of_the_day(user_id)
    if not image:
        await update.message.reply_text("Мемы не найдены :(", disable_notification=True)
        return
    await update.message.reply_photo(photo=image, disable_notification=True)


async def add_meme(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global ALLOW_USER_ADD
    user = update.effective_user
    chat = update.effective_chat

    if chat.type != 'private':
        return

    if not is_admin(user.username) and not ALLOW_USER_ADD:
        await update.message.reply_text("Добавление мемов отключено для обычных пользователей.", 
                                        disable_notification=True)
        return

    if not update.message.photo:
        await update.message.reply_text("Пожалуйста, отправьте мем в виде картинки.", 
                                        disable_notification=True)
        return

    media_group_id = update.message.media_group_id

    # ---------------- Альбом ----------------
    if media_group_id:
        if "pending_photos" not in context.chat_data:
            context.chat_data["pending_photos"] = {}
        if media_group_id not in context.chat_data["pending_photos"]:
            context.chat_data["pending_photos"][media_group_id] = []

        context.chat_data["pending_photos"][media_group_id].append(update.message)

        await asyncio.sleep(1.5)

        photo_msgs = context.chat_data["pending_photos"].pop(media_group_id, [])
        saved_count = 0

        for msg in photo_msgs:
            try:
                photo = msg.photo[-1]
                file = await photo.get_file()   

                # --- загрузка в память ---
                data: bytearray = await file.download_as_bytearray()
                image_base64 = base64.b64encode(data).decode("utf-8")

                # --- запись в БД ---
                meme_manager.mongo.add_meme_base64(image_base64)

                saved_count += 1
            except Exception as e:
                logger.error(f"Failed to save meme from album: {e}")

        await update.message.reply_text(f"✅ Добавлено {saved_count} мемов из альбома. Спасибо 😊",
                                        disable_notification=True)

    else:
        # ---------------- Одиночное изображение ----------------
        try:
            photo = update.message.photo[-1]
            file = await photo.get_file()

            # --- загрузка в память ---
            data: bytearray = await file.download_as_bytearray()
            image_base64 = base64.b64encode(data).decode("utf-8")

            # --- запись в БД ---
            meme_manager.mongo.add_meme_base64(image_base64)

            logger.info("Saved meme to DB (base64)")

        except Exception as e:
            logger.error(f"Failed to save meme: {e}")
            await update.message.reply_text("❌ Ошибка при сохранении мема.", 
                                            disable_notification=True)
            return

        await update.message.reply_text("✅ Мем успешно добавлен! Спасибо 😊", 
                                        disable_notification=True)

    # Проверяем количество мемов
    await ensure_memes_count_async()


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


# --- Перемешивание мемов (для админов) ---
async def shuffle_memes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для перемешивания всех мемов (доступна только админам)"""
    await ensure_memes_count_async()
    user = update.effective_user
    username = user.username if user.username else user.name
    if not is_admin(username):
        await update.message.reply_text("⛔ Команда доступна только администраторам.", disable_notification=True)
        return
    
    try:
        meme_manager.shuffle_meme_order(admin_shuffle=True)
        await update.message.reply_text("✅ Все мемы перемешаны!", disable_notification=True)
    except Exception as e:
        logger.error(f"Failed to shuffle memes: {e}")
        await update.message.reply_text("❌ Ошибка при перемешивании мемов.", disable_notification=True)


# --- Панель управления мемами ---
async def control_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    username = user.username if user.username else user.name

    # разрешаем только в личке
    if chat.type != 'private':
        await update.message.reply_text(
            "ℹ️ Команда доступна только в личных сообщениях. Пожалуйста, напишите боту в ЛС.",
            disable_notification=True
        )
        return

    if not is_admin_or_editor(username):
        await update.message.reply_text(
            "⛔ Эта команда доступна только администраторам и редакторам.",
            disable_notification=True
        )
        return

    if CONTROL_PANEL_URL:
        url = f"http://{CONTROL_PANEL_URL}:{CONTROL_PANEL_PORT}"
    else:
        server_ip = SERVER_IP
        if server_ip:
            url = f"http://{server_ip}:{CONTROL_PANEL_PORT}"
        else:
            url = f"http://<SERVER_IP>:{CONTROL_PANEL_PORT}  (укажи SERVER_IP или control_panel_url в config.yaml)"

    await update.message.reply_text(
        f"[Панель управления мемами]({url})",
        disable_notification=True,
        parse_mode='Markdown'
    )


# --- Добавление редакторов ---
async def add_editor_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    username = user.username if user.username else user.name
    if not is_admin(username):
        await update.message.reply_text("⛔ Команда доступна только администраторам.", disable_notification=True)
        return

    args = context.args
    if not args:
        await update.message.reply_text("Использование: /add_editor <username> (без @).", disable_notification=True)
        return
    new_editor = args[0].lstrip("@")
    if new_editor in EDITORS:
        await update.message.reply_text(f"{new_editor} уже в списке editors.", disable_notification=True)
        return

    EDITORS.add(new_editor)
    CONFIG['editors'] = sorted(list(EDITORS))
    save_config()
    await update.message.reply_text(f"✅ Пользователь {new_editor} добавлен в editors.", disable_notification=True)


# --- Удаление редакторов ---
async def remove_editor_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    username = user.username if user.username else user.name
    if not is_admin(username):
        await update.message.reply_text("⛔ Команда доступна только администраторам.", disable_notification=True)
        return

    args = context.args
    if not args:
        await update.message.reply_text("Использование: /remove_editor <username> (без @).", disable_notification=True)
        return
    editor_to_remove = args[0].lstrip("@")
    if editor_to_remove not in EDITORS:
        await update.message.reply_text(f"{editor_to_remove} не найден в списке editors.", disable_notification=True)
        return

    EDITORS.remove(editor_to_remove)
    CONFIG['editors'] = sorted(list(EDITORS))
    save_config()
    await update.message.reply_text(f"✅ Пользователь {editor_to_remove} удалён из editors.", disable_notification=True)


async def main():
    load_config()
    # load_memes_list() больше не нужна, синхронизация происходит в load_config()   // уже не происходит
    application = ApplicationBuilder().token(CONFIG['token']).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help))
    application.add_handler(CommandHandler("help_admins", help_admins))
    application.add_handler(CommandHandler("meme_count", meme_count))
    application.add_handler(CommandHandler("random_meme", random_meme))
    application.add_handler(CommandHandler("meme_of_the_day", meme_of_the_day))
    application.add_handler(CommandHandler("lock_mem_add", lock_mem_add))
    application.add_handler(CommandHandler("unlock_mem_add", unlock_mem_add))
    application.add_handler(CommandHandler("export_memes", export_memes))
    application.add_handler(CommandHandler("version", version))
    application.add_handler(CommandHandler("add_editor", add_editor_cmd))
    application.add_handler(CommandHandler("remove_editor", remove_editor_cmd))
    application.add_handler(CommandHandler("control_panel", control_panel))
    application.add_handler(CommandHandler("shuffle_memes", shuffle_memes))
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
