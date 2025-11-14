import os
import logging
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()  # Загружаем .env

logger = logging.getLogger(__name__)

DB_NAME = "memebot_db"


class MongoManager:
    def __init__(self):
        """Инициализация подключения к MongoDB"""
        try:
            # Приоритет 1: Используем MONGO_URI если он задан (из docker-compose)
            mongo_uri = os.getenv("MONGO_URI")
            if mongo_uri:
                uri = mongo_uri
                logger.info("Using MONGO_URI from environment")
            else:
                # Приоритет 2: Собираем URI из отдельных переменных
                mongo_user = os.getenv("MONGO_USER", "")
                mongo_pass = os.getenv("MONGO_PASS", "")
                mongo_port = os.getenv("MONGO_PORT", "27017")
                # MONGO_HOST может быть задан в .env или docker-compose, иначе localhost
                mongo_host = os.getenv("MONGO_HOST", "localhost")
                
                if mongo_user and mongo_pass:
                    uri = f"mongodb://{mongo_user}:{mongo_pass}@{mongo_host}:{mongo_port}"
                else:
                    uri = f"mongodb://{mongo_host}:{mongo_port}"
                
                logger.info(f"Using MongoDB connection: {mongo_host}:{mongo_port}")
            
            self.client = MongoClient(uri)
            self.db = self.client[DB_NAME]
            # Коллекции
            self.bot_state = self.db["bot_state"]
            self.memes = self.db["memes"]
            self.user_memes = self.db["user_memes"]
            
            # Создаем индексы для оптимизации
            self.memes.create_index("_id")
            self.user_memes.create_index("_id")
            
            logger.info(f"Connected to MongoDB: {DB_NAME}")
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            raise

    # -------------------- bot_state --------------------
    def get_bot_state(self):
        """Получить состояние бота (MEME_INDEX, LAST_MEMES_COUNT, MEME_ORDER)"""
        doc = self.bot_state.find_one({"_id": 0})
        if doc is None:
            doc = {"_id": 0, "MEME_INDEX": 0, "LAST_MEMES_COUNT": 0, "MEME_ORDER": []}
            self.bot_state.insert_one(doc)
        return doc

    def update_bot_state(self, **kwargs):
        """Обновить состояние бота"""
        self.bot_state.update_one({"_id": 0}, {"$set": kwargs}, upsert=True)

    def get_meme_order(self):
        """Получить MEME_ORDER из bot_state"""
        state = self.get_bot_state()
        return state.get("MEME_ORDER", [])

    def set_meme_order(self, meme_order):
        """Установить MEME_ORDER в bot_state"""
        self.update_bot_state(MEME_ORDER=meme_order)

    # -------------------- memes --------------------
    def get_all_memes(self):
        """Получить все мемы, отсортированные по _id"""
        return list(self.memes.find({}, sort=[("_id", 1)]))

    def get_meme_by_id(self, meme_id):
        """Получить мем по _id"""
        return self.memes.find_one({"_id": meme_id})

    def get_meme_by_file(self, file_name):
        """Получить мем по имени файла"""
        return self.memes.find_one({"file": file_name})

    def count_memes(self):
        """Подсчитать количество мемов в БД"""
        return self.memes.count_documents({})

    def add_meme(self, file_name):
        """Добавить новый мем в БД. Возвращает _id"""
        # Проверяем, не существует ли уже такой файл
        existing = self.get_meme_by_file(file_name)
        if existing:
            return existing["_id"]
        
        # Находим максимальный _id и добавляем новый
        max_id_doc = self.memes.find_one(sort=[("_id", -1)])
        new_id = (max_id_doc["_id"] + 1) if max_id_doc else 0
        
        self.memes.insert_one({"_id": new_id, "file": file_name})
        logger.info(f"Added meme to DB: {file_name} with _id={new_id}")
        return new_id

    def sync_memes_from_folder(self, memes_folder):
        """Синхронизировать список файлов из папки с БД"""
        import os
        
        # Получаем список файлов из папки
        files_in_folder = [
            f for f in os.listdir(memes_folder)
            if os.path.isfile(os.path.join(memes_folder, f)) 
            and f.lower().endswith(('.jpg', '.jpeg', '.png', '.gif'))
        ]
        
        # Получаем список файлов из БД
        memes_in_db = {m["file"] for m in self.get_all_memes()}
        
        # Добавляем новые файлы
        added_count = 0
        for file_name in files_in_folder:
            if file_name not in memes_in_db:
                self.add_meme(file_name)
                added_count += 1
        
        # Удаляем файлы, которых нет в папке (опционально, можно закомментировать)
        # files_in_folder_set = set(files_in_folder)
        # for meme in self.get_all_memes():
        #     if meme["file"] not in files_in_folder_set:
        #         self.memes.delete_one({"_id": meme["_id"]})
        
        if added_count > 0:
            logger.info(f"Synced {added_count} new memes from folder to DB")
        
        return len(files_in_folder)

    def delete_meme(self, meme_id):
        """Удалить мем по _id"""
        result = self.memes.delete_one({"_id": meme_id})
        return result.deleted_count > 0

    # -------------------- user_memes --------------------
    def get_user_meme(self, user_id):
        """Получить мем дня для пользователя"""
        return self.user_memes.find_one({"_id": user_id})

    def set_user_meme(self, user_id, meme_file, date):
        """Установить мем дня для пользователя"""
        self.user_memes.update_one(
            {"_id": user_id},
            {"$set": {"meme_file": meme_file, "date": date}},
            upsert=True
        )

    def delete_user_meme(self, user_id):
        """Удалить мем дня для пользователя"""
        self.user_memes.delete_one({"_id": user_id})

    def cleanup_old_user_memes(self, today_date):
        """Удалить устаревшие записи мемов дня (не сегодняшние)"""
        result = self.user_memes.delete_many({"date": {"$ne": today_date}})
        if result.deleted_count > 0:
            logger.info(f"Cleaned up {result.deleted_count} old user memes")
        return result.deleted_count
