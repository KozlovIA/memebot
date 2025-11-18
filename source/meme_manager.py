import os
import datetime
import numpy as np
import logging
import base64
from io import BytesIO
import zipfile
from source.mongo_manager import MongoManager

logger = logging.getLogger(__name__)

mongo = MongoManager()

# Глобальная переменная для папки с мемами (будет установлена из bot.py)
MEMES_FOLDER = None


def set_memes_folder(folder_path):
    """Установить путь к папке с мемами"""
    global MEMES_FOLDER
    MEMES_FOLDER = folder_path


# -------------------- MEMES_LIST (синхронизация с папкой) --------------------
def load_memes_list():
    """Возвращает список файлов мемов в папке memes"""
    if not MEMES_FOLDER or not os.path.exists(MEMES_FOLDER):
        return []
    return [
        f for f in os.listdir(MEMES_FOLDER)
        if os.path.isfile(os.path.join(MEMES_FOLDER, f)) 
        and f.lower().endswith(('.jpg', '.jpeg', '.png', '.gif'))
    ]


def sync_memes_with_db():
    """Синхронизировать файлы из папки с БД"""
    if not MEMES_FOLDER:
        return 0
    return mongo.sync_memes_from_folder(MEMES_FOLDER)


# -------------------- MEME_ORDER (перемешивание) --------------------
def shuffle_meme_order(admin_shuffle=False):
    """
    Перемешивание MEME_ORDER с учётом логики:
    1) Удаление несуществующих индексов
    2) Коррекция MEME_INDEX при удалениях
    3) Частичное перемешивание хвоста после MEME_INDEX
    4) Полное перемешивание при admin_shuffle=True
    """

    state = mongo.get_bot_state()
    memes = mongo.get_all_memes()

    if not memes:
        logger.warning("No memes in database")
        return []

    # Все существующие _id
    all_meme_ids = sorted(m["_id"] for m in memes)

    # MEME_ORDER и MEME_INDEX
    current_order = state.get("MEME_ORDER", [])
    meme_index = state.get("MEME_INDEX", 0)  # Важно: это позиция, а не ID!

    # --- 1. Фильтрация MEME_ORDER от отсутствующих ID ---
    cleaned_order = []
    removed_count_left = 0

    for pos, meme_id in enumerate(current_order):
        if meme_id in all_meme_ids:
            cleaned_order.append(meme_id)
        else:
            if pos <= meme_index:
                removed_count_left += 1

    # Если список пуст — создаём полный порядок по БД
    if not cleaned_order:
        cleaned_order = all_meme_ids.copy()
        meme_index = 0
    else:
        # --- 2. Корректируем MEME_INDEX после удаления слева ---
        meme_index = max(0, meme_index - removed_count_left)
        # MEME_INDEX не должен выходить за пределы списка
        if meme_index >= len(cleaned_order):
            meme_index = max(0, len(cleaned_order) - 1)

    # Список актуален
    current_order = cleaned_order

    # --- 4. Admin shuffle = полный пересорт ---
    if admin_shuffle:
        new_order = [int(x) for x in np.random.permutation(all_meme_ids)]
        meme_index = 0
        logger.info("Admin shuffle: full reshuffle")
    else:
        # --- 3. Частичное перемешивание правой части ---
        if meme_index < len(current_order) - 1:
            left = current_order[:meme_index + 1]
            right = current_order[meme_index + 1:]

            right_shuffled = [int(x) for x in np.random.permutation(right)]
            new_order = left + right_shuffled

            logger.info(
                f"Partial shuffle after MEME_INDEX={meme_index}, "
                f"left size={len(left)}, right size={len(right)}"
            )
        else:
            # Нечего перемешивать
            new_order = current_order.copy()
            logger.info("Nothing to shuffle (pointer at end)")

    # --- Сохраняем в БД ---
    mongo.update_bot_state({
        "MEME_ORDER": new_order,
        "MEME_INDEX": int(meme_index),
        "LAST_MEMES_COUNT": len(all_meme_ids)
    })

    return new_order


def prepare_meme_order_if_needed():
    """
    Подготовить MEME_ORDER, если нужно (когда количество мемов изменилось)
    Возвращает True, если было выполнено перемешивание
    """
    state = mongo.get_bot_state()
    current_count = mongo.count_memes()
    last_count = state.get("LAST_MEMES_COUNT", 0)
    
    if current_count != last_count or not state.get("MEME_ORDER"):
        shuffle_meme_order(admin_shuffle=False)
        return True
    return False

def ensure_memes_count_is_actual():
    """Проверяет, совпадает ли количество мемов с сохранённым LAST_MEMES_COUNT.
    Если нет — перемешивает MEME_ORDER и обновляет LAST_MEMES_COUNT.
    """
    current_count = get_meme_count()
    state = mongo.get_bot_state()

    last_count = state.get("LAST_MEMES_COUNT", None)

    print('last_count', last_count, 'current_count', current_count)

    # Если кол-во другое → надо пересоздать и перемешать порядок
    if last_count is None or last_count != current_count:
        new_order = shuffle_meme_order(admin_shuffle=False)
        print(new_order)
        return True

    return False


# -------------------- get_random_meme (ОСНОВНОЕ ИЗМЕНЕНИЕ) --------------------
def get_random_meme():
    """
    Возвращает BASE64 строки мема с учётом MEME_ORDER и MEME_INDEX.
    Больше НЕ использует папку с мемами.
    """
    # Никакой sync с файлов нет
    # prepare_meme_order_if_needed()
    
    state = mongo.get_bot_state()
    meme_order = state.get("MEME_ORDER", [])
    current_meme_id = state.get("MEME_INDEX", 0)
    total_memes = mongo.count_memes()
    
    if not meme_order or total_memes == 0:
        logger.warning("No memes available in DB")
        return None, None
    
    # Если текущего ID нет в порядке — пересобираем порядок
    if current_meme_id not in meme_order or len(meme_order) != total_memes:
        shuffle_meme_order(admin_shuffle=False)
        state = mongo.get_bot_state()
        meme_order = state.get("MEME_ORDER", [])
        current_meme_id = state.get("MEME_INDEX", 0)
    
    # Определяем позицию
    try:
        position = meme_order.index(current_meme_id)
    except ValueError:
        position = 0
        current_meme_id = meme_order[0]
    
    # Если дошли до конца — полное перемешивание
    if position >= len(meme_order) - 1:
        shuffle_meme_order(admin_shuffle=True)
        state = mongo.get_bot_state()
        meme_order = state.get("MEME_ORDER", [])
        position = 0
        current_meme_id = meme_order[0]
    else:
        position += 1
        current_meme_id = meme_order[position]
    
    # Получаем документ мема
    meme_doc = mongo.get_meme_by_id(current_meme_id)
    if not meme_doc:
        logger.error(f"Meme with _id={current_meme_id} not found in DB")
        return None, None
    
    base64_image = meme_doc["image"]

    # Обновляем индекс
    mongo.update_bot_state({'MEME_INDEX': current_meme_id})

    # Возвращаем base64 изображение
    data = base64.b64decode(base64_image)
    bio = BytesIO(data)
    bio.name = f"image.jpg"  # важно указать имя файла!

    return bio, current_meme_id


# -------------------- MEMES_DAY --------------------
def get_user_meme_of_the_day(user_id):
    """
    Возвращает base64 мема дня.
    """
    today = datetime.date.today().isoformat()
    
    user_doc = mongo.get_user_meme(user_id)

    # Если мем уже есть и сегодняшний
    if user_doc and user_doc.get("date") == today:
        meme_id = user_doc.get("meme_id")
        meme_doc = mongo.get_meme_by_id(meme_id)
        if meme_doc:
            base64_img = meme_doc["image"]
            data = base64.b64decode(base64_img)
            base64_img = BytesIO(data)
            base64_img.name = f"image.jpg"
            return base64_img
        else:
            mongo.delete_user_meme(user_id)
            # Выбираем новый мем
            base64_img, meme_id = get_random_meme()
    else:
        # Выбираем новый мем
        base64_img, meme_id = get_random_meme()

    if base64_img is None:
        return 'None', 'None'
    
    mongo.set_user_meme(user_id, meme_id, today)

    return base64_img


# -------------------- get_meme_count --------------------
def get_meme_count():
    """Получить количество мемов из MongoDB."""
    return mongo.count_memes()


# -------------------- create_memes_zip_from_db --------------------
def create_memes_zip_from_db_stream():
    """
    Создает ZIP архив мемов из MongoDB без загрузки всех мемов в память.
    """
    cursor = mongo.get_memes_cursor()  # <- новый потоковый метод
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    temp_folder = 'temp'
    os.makedirs(temp_folder, exist_ok=True)
    zip_path = f"{temp_folder}/memes_export_{timestamp}.zip"

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as zipf:
        for meme in cursor:
            meme_id = meme["_id"]
            base64_str = meme["image"]
            try:
                binary = base64.b64decode(base64_str)
            except Exception as e:
                logger.error(f"Ошибка декодирования base64 для ID={meme_id}: {e}")
                continue

            filename = f"{meme_id:04d}.jpg"
            zipf.writestr(filename, binary)  # записываем сразу в ZIP

    return zip_path