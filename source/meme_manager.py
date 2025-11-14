import os
import datetime
import numpy as np
import logging
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
    Перемешивание MEME_ORDER
    
    Args:
        admin_shuffle: Если True, перемешивает все мемы. 
                      Если False, перемешивает только правую часть после текущего элемента MEME_INDEX.
    
    Returns:
        Новый MEME_ORDER (список _id мемов)
    """
    state = mongo.get_bot_state()
    memes = mongo.get_all_memes()
    
    if not memes:
        logger.warning("No memes in database")
        return []
    
    # Получаем список всех _id мемов
    all_meme_ids = [m["_id"] for m in memes]
    
    # Получаем текущий MEME_ORDER или создаем новый
    current_order = state.get("MEME_ORDER", [])
    current_meme_index_value = state.get("MEME_INDEX", 0)
    
    # Если админ вызвал перемешивание, перемешиваем все
    if admin_shuffle:
        new_order = [int(x) for x in np.random.permutation(all_meme_ids)]
        # Устанавливаем MEME_INDEX на первый элемент нового порядка
        current_meme_index_value = int(new_order[0]) if new_order else 0
        logger.info("Admin shuffle: all memes shuffled")
    else:
        # Перемешиваем только правую часть после текущего элемента
        # MEME_INDEX - это значение элемента в MEME_ORDER, а не индекс позиции
        if current_order and current_meme_index_value in current_order:
            # Находим позицию текущего элемента
            try:
                current_position = current_order.index(current_meme_index_value)
                # Левая часть (до текущего элемента включительно) остается без изменений
                left_part = current_order[:current_position + 1]
                # Правая часть (после текущего элемента) перемешивается
                right_part = [int(x) for x in np.random.permutation(current_order[current_position + 1:])]
                new_order = left_part + right_part
                # MEME_INDEX остается на том же элементе (current_meme_index_value не меняется)
                logger.info(f"Shuffled right part after element {current_meme_index_value} (position {current_position})")
            except ValueError:
                # Если текущий элемент не найден в порядке, перемешиваем все
                new_order = [int(x) for x in np.random.permutation(all_meme_ids)]
                current_meme_index_value = int(new_order[0]) if new_order else 0
                logger.warning(f"Current meme index {current_meme_index_value} not found in order, shuffling all")
        else:
            # Если MEME_ORDER пуст или текущий элемент не найден, перемешиваем все
            new_order = [int(x) for x in np.random.permutation(all_meme_ids)]
            current_meme_index_value = int(new_order[0]) if new_order else 0
            logger.info("Empty or invalid order, shuffling all memes")
    
    # Обновляем состояние в БД
    total_memes = len(all_meme_ids)
    mongo.update_bot_state(
        MEME_ORDER=new_order,
        MEME_INDEX=current_meme_index_value,
        LAST_MEMES_COUNT=total_memes
    )
    
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


# -------------------- get_random_meme --------------------
def get_random_meme():
    """
    Возвращает файл случайного мема с учётом MEME_ORDER и MEME_INDEX.
    Синхронизирует список файлов с БД перед использованием.
    """
    # Синхронизируем файлы из папки с БД
    sync_memes_with_db()
    
    # Проверяем, нужно ли обновить MEME_ORDER
    prepare_meme_order_if_needed()
    
    state = mongo.get_bot_state()
    meme_order = state.get("MEME_ORDER", [])
    current_meme_index_value = state.get("MEME_INDEX", 0)
    total_memes = mongo.count_memes()
    
    if not meme_order or total_memes == 0:
        logger.warning("No memes available")
        return None
    
    # Если индекс вышел за границы или текущий элемент не найден, перемешиваем заново
    if current_meme_index_value not in meme_order or len(meme_order) != total_memes:
        shuffle_meme_order(admin_shuffle=False)
        state = mongo.get_bot_state()
        meme_order = state.get("MEME_ORDER", [])
        current_meme_index_value = state.get("MEME_INDEX", 0)
    
    # Находим позицию текущего элемента в порядке
    try:
        current_position = meme_order.index(current_meme_index_value)
    except ValueError:
        # Если элемент не найден, берем первый
        current_position = 0
        current_meme_index_value = meme_order[0]
    
    # Если дошли до конца, перемешиваем все заново
    if current_position >= len(meme_order) - 1:
        shuffle_meme_order(admin_shuffle=True)
        state = mongo.get_bot_state()
        meme_order = state.get("MEME_ORDER", [])
        current_position = 0
        current_meme_index_value = meme_order[0] if meme_order else 0
    else:
        # Переходим к следующему элементу
        current_position += 1
        current_meme_index_value = meme_order[current_position]
    
    # Получаем мем по _id
    meme_doc = mongo.get_meme_by_id(current_meme_index_value)
    if not meme_doc:
        logger.error(f"Meme with _id={current_meme_index_value} not found in DB")
        return None
    
    meme_file = meme_doc["file"]
    
    # Обновляем MEME_INDEX в БД (сохраняем значение элемента, а не позицию)
    mongo.update_bot_state(MEME_INDEX=current_meme_index_value)
    
    return meme_file


# -------------------- MEMES_DAY --------------------
def reset_memes_day_if_needed():
    """Удаляем устаревшие мемы дня по дате"""
    today = datetime.date.today()
    today_str = today.isoformat()
    mongo.cleanup_old_user_memes(today_str)


def get_user_meme_of_the_day(user_id):
    """
    Получить мем дня для пользователя.
    Если мем дня уже есть и он сегодняшний - возвращает его.
    Иначе выбирает новый мем и сохраняет его.
    """
    reset_memes_day_if_needed()
    today = datetime.date.today()
    today_str = today.isoformat()
    
    user_meme = mongo.get_user_meme(user_id)
    
    # Если у пользователя уже есть мем дня на сегодня
    if user_meme and user_meme.get("date") == today_str:
        meme_file = user_meme.get("meme_file")
        # Проверяем, что файл существует
        if meme_file and os.path.exists(os.path.join(MEMES_FOLDER, meme_file)):
            return meme_file
        else:
            # Если файл не найден, удаляем запись и выбираем новый
            mongo.delete_user_meme(user_id)
    
    # Выбираем новый мем дня
    meme_file = get_random_meme()
    if meme_file:
        mongo.set_user_meme(user_id, meme_file, today_str)
    
    return meme_file


def get_meme_count():
    """Получить количество мемов (синхронизирует с папкой перед подсчетом)"""
    sync_memes_with_db()
    return mongo.count_memes()
