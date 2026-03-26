import sqlite3

# Укажите путь к вашей базе данных
db_path = "scripts/example_database.db"

# Подключение к базе данных
conn = sqlite3.connect(db_path)
cursor = conn.cursor()


# 2. Получение списка таблиц
def list_tables():
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()
    print("Таблицы в базе данных:")
    for table in tables:
        print(table[0])  # выводим имя таблицы


# 3. Получение данных из таблицы
def fetch_data_from_table(table_name):
    cursor.execute(f"SELECT * FROM {table_name};")
    rows = cursor.fetchall()
    print(f"\nДанные из таблицы '{table_name}':")
    for row in rows:
        print(row)


# Основная логика
if __name__ == "__main__":
    list_tables()  # Выводим список таблиц

    # Запрашиваем у пользователя имя таблицы для вывода данных
    table_name = input("\nВведите имя таблицы, чтобы увидеть данные: ")
    fetch_data_from_table(table_name)

# Закрытие соединения с базой данных
conn.close()
