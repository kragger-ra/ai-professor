import csv


def validate_csv(file_path):
    with open(file_path, mode="r", newline="", encoding="utf-8") as file:
        reader = csv.reader(file)
        header = next(reader)  # Считываем заголовок
        expected_columns = len(header)

        for line_number, row in enumerate(
            reader, start=2
        ):  # Начинаем с 2 для учета заголовка
            if len(row) != expected_columns:
                print(
                    f"Ошибка на строке {line_number}: ожидалось {expected_columns} столбцов, но найдено {len(row)}"
                )
            for col_number, value in enumerate(row):
                if value.strip() == "":  # Проверка на пустые значения
                    print(
                        f"Пустое значение на строке {line_number}, столбец {col_number + 1}"
                    )


# Пример использования
# validate_csv('your_file.csv')


# Пример использования
validate_csv("banned_words_cat_2.csv")
