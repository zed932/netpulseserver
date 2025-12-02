import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
HOST = "0.0.0.0"
PORT = 5000

USER_STATUSES = ["online", "offline", "busy", "away"]

ACHIEVEMENT_TYPES = {
    "first_session": {
        "name": "Первая сессия",
        "description": "Завершите вашу первую совместную сессию",
        "threshold": 1
    },
    "sessions_5": {
        "name": "Начинающий",
        "description": "Завершите 5 совместных сессий",
        "threshold": 5
    },
    "sessions_10": {
        "name": "Активный участник",
        "description": "Завершите 10 совместных сессий",
        "threshold": 10
    },
    "sessions_25": {
        "name": "Эксперт",
        "description": "Завершите 25 совместных сессий",
        "threshold": 25
    },
    "sessions_50": {
        "name": "Мастер",
        "description": "Завершите 50 совместных сессий",
        "threshold": 50
    },
    "total_time_1h": {
        "name": "Час вместе",
        "description": "Проведите 1 час в совместных сессиях",
        "threshold": 3600
    },
    "total_time_5h": {
        "name": "Пять часов",
        "description": "Проведите 5 часов в совместных сессиях",
        "threshold": 18000
    },
    "friends_5": {
        "name": "Социальный",
        "description": "Добавьте 5 друзей",
        "threshold": 5
    }
}
