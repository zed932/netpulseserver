import mysql.connector
from mysql.connector import Error
import os
from dotenv import load_dotenv

load_dotenv()


def test_connection():
    try:
        connection = mysql.connector.connect(
            host=os.getenv('DB_HOST', 'localhost'),
            database=os.getenv('DB_NAME', 'netpulse'),
            user=os.getenv('DB_USER', 'root'),
            password=os.getenv('DB_PASSWORD', ''),
            port=os.getenv('DB_PORT', 3306)
        )

        if connection.is_connected():
            print("✅ Успешное подключение к MySQL!")

            cursor = connection.cursor()
            cursor.execute("SELECT DATABASE();")
            db_name = cursor.fetchone()
            print(f"📊 Подключена база: {db_name[0]}")

            cursor.close()
            connection.close()

    except Error as e:
        print(f"❌ Ошибка подключения: {e}")


if __name__ == "__main__":
    test_connection()