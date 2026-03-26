import os

import pandas as pd


def remove_duplicates(input_file):
    # Читаем CSV файл
    df = pd.read_csv(input_file)

    # Проверяем, есть ли столбец 'word'
    if "word" not in df.columns:
        print("Столбец 'word' не найден в файле.")
        return

    # Удаляем дубликаты
    df_unique = df.drop_duplicates(subset="word")

    # Создаем новый файл с индексом
    base_name, ext = os.path.splitext(input_file)
    index = 1
    new_file = f"{base_name}_{index}{ext}"

    while os.path.exists(new_file):
        index += 1
        new_file = f"{base_name}_{index}{ext}"

    # Сохраняем уникальные слова в новый файл
    df_unique.to_csv(new_file, index=False)

    print(f"Уникальные слова сохранены в файл: {new_file}")


def remove_duplicates_and_sort(input_file):
    # Читаем CSV файл
    df = pd.read_csv(input_file)

    # Проверяем наличие необходимых столбцов
    if "word" not in df.columns or "category" not in df.columns:
        print("Необходимые столбцы 'word' и 'category' не найдены в файле.")
        return

    # Удаляем дубликаты по столбцу 'word'
    df_unique = df.drop_duplicates(subset="word")

    # Сортируем по столбцу 'category'
    df_sorted = df_unique.sort_values(by="category")

    # Создаем новый файл с индексом
    base_name, ext = os.path.splitext(input_file)
    index = 1
    new_file = f"{base_name}_{index}{ext}"

    while os.path.exists(new_file):
        index += 1
        new_file = f"{base_name}_{index}{ext}"

    # Сохраняем уникальные слова, отсортированные по категориям, в новый файл
    df_sorted.to_csv(new_file, index=False)

    print(
        f"Уникальные слова, отсортированные по категориям, сохранены в файл: {new_file}"
    )


# Пример использования
if __name__ == "__main__":
    # input_file = input("Введите имя CSV файла: ")
    input_file = "banned_words_cat_2.csv"
    # remove_duplicates(input_file)

    remove_duplicates_and_sort(input_file)
