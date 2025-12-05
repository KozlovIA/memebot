import os
import logging
import base64
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()  # Загружаем .env

logger = logging.getLogger(__name__)

# DB_NAME = "memebot_db"


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
                mongo_db_name = os.getenv("MONGO_DB_NAME", "memebot_db")
                
                if mongo_user and mongo_pass:
                    uri = f"mongodb://{mongo_user}:{mongo_pass}@{mongo_host}:{mongo_port}"
                else:
                    uri = f"mongodb://{mongo_host}:{mongo_port}"
                
                logger.info(f"Using MongoDB connection: {mongo_host}:{mongo_port}")
            
            self.client = MongoClient(uri)
            self.db = self.client[mongo_db_name]
            # Коллекции
            self.bot_state = self.db["bot_state"]
            self.memes = self.db["memes"]
            self.user_memes = self.db["user_memes"]
            
            # Создаем индексы для оптимизации
            self.memes.create_index("_id")
            self.user_memes.create_index("_id")
            
            logger.info(f"Connected to MongoDB: {mongo_db_name}")
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

    def update_bot_state(self, state: dict) -> None:
            """Обновляет документ состояния бота (upsert)."""
            # пример реализации:
            self.bot_state.update_one({}, {"$set": state}, upsert=True)

    def get_meme_order(self):
        """Получить MEME_ORDER из bot_state"""
        state = self.get_bot_state()
        return state.get("MEME_ORDER", [])

    def set_meme_order(self, meme_order):
        """Установить MEME_ORDER в bot_state"""
        self.update_bot_state({'MEME_ORDER': meme_order})

  # -------------------- memes (NEW VERSION) --------------------
    def get_all_memes(self):
        """Получить все мемы с Base64, отсортированные по _id"""
        return list(self.memes.find({}, sort=[("_id", 1)]))

    def get_meme_by_id(self, meme_id):
        """Получить мем по _id"""
        return self.memes.find_one({"_id": meme_id})

    def count_memes(self):
        return self.memes.count_documents({})

    def add_meme_base64(self, base64_str):
        """Добавляет мем, переданный как base64 строка"""
        max_id_doc = self.memes.find_one(sort=[("_id", -1)])
        new_id = (max_id_doc["_id"] + 1) if max_id_doc else 0

        self.memes.insert_one({
            "_id": new_id,
            "image": base64_str
        })

        logger.info(f"Added meme (base64) with _id={new_id}")
        return new_id

    def add_meme_from_file(self, file_path):
        """Прочитать файл -> сохранить как base64"""
        with open(file_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("utf-8")

        return self.add_meme_base64(encoded)

    def sync_memes_from_folder(self, folder):
        """
        СИНХРОНИЗАЦИЯ НОВАЯ:
        - все файлы читаются
        - каждый файл грузится в виде base64
        - старые документы НЕ УДАЛЯЮТСЯ (можно включить)
        """
        files = [
            f for f in os.listdir(folder)
            if f.lower().endswith((".jpg", ".jpeg", ".png", ".gif"))
        ]

        added = 0
        for filename in files:
            full_path = os.path.join(folder, filename)
            new_id = self.add_meme_from_file(full_path)
            added += 1

        logger.info(f"Sync completed: added {added} memes from folder")
        return added

    def delete_meme(self, meme_id):
        result = self.memes.delete_one({"_id": meme_id})
        return result.deleted_count > 0

    # -------------------- user_memes (UPDATED) --------------------
    def get_user_meme(self, user_id):
            """Получить мем дня по user_id"""
            return self.user_memes.find_one({"_id": user_id})

    def set_user_meme(self, user_id, meme_id, date):
        """
        Теперь храним ссылку на ID мема (int), а не файл или base64.
        """
        self.user_memes.update_one(
            {"_id": user_id},
            {"$set": {"meme_id": meme_id, "date": date}},
            upsert=True
        )

    def delete_user_meme(self, user_id):
        self.user_memes.delete_one({"_id": user_id})

    def cleanup_old_user_memes(self, today_date):
        result = self.user_memes.delete_many({"date": {"$ne": today_date}})
        return result.deleted_count

    def get_memes_cursor(self):
            """
            Возвращает курсор для всех мемов, отсортированных по _id.
            Используется для потоковой обработки без загрузки всех документов в память.
            """
            return self.memes.find({}, sort=[("_id", 1)])