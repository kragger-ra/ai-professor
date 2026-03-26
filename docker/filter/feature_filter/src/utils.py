import csv
import os


def load_words_from_directory(directory):
    """Загружает слова из всех CSV-файлов в указанной директории."""

    words_list = []  # Список для хранения загруженных слов
    for file_name in os.listdir(directory):
        if file_name.endswith(".csv"):
            file_path = os.path.join(directory, file_name)
            with open(file_path, newline="", encoding="utf-8") as csvfile:
                reader = csv.reader(csvfile)  #
                for row in reader:
                    if row:  # Проверяем, что строка не пустая
                        words_list.append(row[0])  # Добавляем первое значение в строке
    return words_list  # Возвращаем список загруженных слов


def load_words_from_csv_file(filename):
    """Загружает слова из указанного CSV-файла."""
    words_list = []  # Список для хранения загруженных слов
    with open(filename, newline="", encoding="utf-8") as csvfile:
        reader = csv.reader(csvfile)  # Используем csv.reader для файлов без заголовков
        for row in reader:
            if row:  # Проверяем, что строка не пустая
                words_list.append(row[0])  # Добавляем первое значение в строке
    return words_list  # Возвращаем список загруженных слов


def load_test_samples(filename):
    """Загружает тестовые образцы из CSV-файла."""
    with open(filename, newline="", encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile)
        return [(row["text"], row["expected"] == "True") for row in reader]


def load_banned_words_with_ratings_from_csv(filename):
    """Загружает слова из указанного CSV-файла с категориями, весами и метками.

    Проверяет наличие заголовка и его корректность.
    """
    words_list = []  # Список для хранения загруженных слов
    expected_header = ["word", "category", "weight", "label"]  # Ожидаемый заголовок

    with open(filename, newline="", encoding="utf-8") as csvfile:
        reader = csv.reader(csvfile)  # Используем csv.reader для файлов без заголовков
        header = next(reader)  # Читаем первую строку как заголовок

        # Проверяем, соответствует ли заголовок ожидаемому
        if header != expected_header:
            raise ValueError(
                f"Некорректный заголовок в файле {filename}. Ожидается: {expected_header}, получено: {header}"
            )

        # Загружаем данные из файла, начиная со второй строки
        for row in reader:
            if (
                row and len(row) >= 4
            ):  # Проверяем, что строка не пустая и содержит минимум 4 колонки
                word_data = {
                    "word": row[0],  # Первое значение - слово
                    "category": row[1],  # Второе значение - категория
                    "weight": float(
                        row[2]
                    ),  # Третье значение - вес (преобразуем в float)
                    "label": row[3],  # Четвертое значение - метка
                }
                words_list.append(word_data)  # Добавляем словарь в список

    return words_list  # Возвращаем список загруженных словарей


def load_categories_from_csv(filename):
    """Loads data from a CSV file with the specified headers: category, coefficient, label."""
    data = []  # List to store the loaded data

    with open(filename, newline="", encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile)  # Use DictReader to read rows as dictionaries
        for row in reader:
            # Append each row to the data list
            data.append(
                {
                    "category": row["category"],  # Correct key for English header
                    "coefficient": float(
                        row["coefficient"]
                    ),  # Convert coefficient to float
                    "label": row["label"],  # Correct key for English header
                }
            )

    return data


if __name__ == "__main__":

    #     # Пример использования функции
    # filename = 'words.csv'  # Имя вашего CSV-файла

    # try:
    #     banned_words = load_banned_words_with_ratings_from_csv(filename)
    #     print("Запрещённые слова успешно загружены: \n", banned_words)
    # except ValueError as e:
    #     print(e)

    # # Загружаем слова из CSV-файла
    # words = load_banned_words_with_ratings_from_csv(filename)

    # # Вывод загруженных данных
    # for word in words:
    #     print(word)

    # # пример вывода
    # {'word': 'apple', 'category': 'fruit', 'weight': 0.5, 'label': 'healthy'}
    # {'word': 'banana', 'category': 'fruit', 'weight': 0.3, 'label': 'healthy'}
    # {'word': 'carrot', 'category': 'vegetable', 'weight': 0.5, 'label': 'healthy'}
    # {'word': 'donut', 'category': 'dessert', 'weight': 0.2, 'label': 'unhealthy'}
    # {'word': 'eggplant', 'category': 'vegetable', 'weight': 0.8, 'label': 'healthy'}
    # {'word': 'fig', 'category': 'dessert', 'weight': 0.1, 'label': 'healthy'}
    # {'word': 'grape', 'category': 'fruit', 'weight': 0.3, 'label': 'healthy'}

    input_file = "_categories.csv"  # Specify the path to your CSV file
    loaded_data = load_categories_from_csv(input_file)

    print("Loaded data:")
    for item in loaded_data:
        print(item)
