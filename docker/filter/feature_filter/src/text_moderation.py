import logging
import os
import re
import string
from functools import lru_cache
from typing import List, Set, Tuple

import Levenshtein
import pymorphy2
from transliterate import translit

from .transliteration_map import transliteration_map
from .utils import (
    load_banned_words_with_ratings_from_csv,
    load_categories_from_csv,
    load_test_samples,
    load_words_from_csv_file,
    load_words_from_directory,
)

# Настройка логирования
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger()
logger.setLevel(logging.INFO)


class TextModeration:
    def __init__(
        self,
        banned_words: List[str],
        hard_banned_words: List[str],
        levenshtein_distance_threshold: int = 2,
    ):
        """
        Инициализирует объект класса TextModeration.

        Args:
            banned_words (List[str]): Список слов, использование которых нежелательно.
            hard_banned_words (List[str]): Список слов, использование которых строго запрещено.
            levenshtein_distance_threshold (int): Порог расстояния Левенштейна для проверки опечаток.
        """
        self.banned_words: Set[str] = set(banned_words)
        self.hard_banned_words: Set[str] = set(hard_banned_words)
        self.morph = pymorphy2.MorphAnalyzer()
        self.transliteration_map = transliteration_map
        self.levenshtein_distance_threshold = levenshtein_distance_threshold

    def clean_text(self, text: str) -> str:
        """Удаляет знаки пунктуации между словами и лишние пробелы."""
        # Удаляем знаки препинания, которые находятся между словами (не внутри слов)
        text = re.sub(r"(?<=\s)[^\w\s]+(?=\s)", " ", text)
        text = re.sub(r"^\W+|\W+$", "", text)  # Убираем знаки в начале и в конце текста
        text = re.sub(r"\s+", " ", text).strip()  # Убираем лишние пробелы между словами
        return text.lower()

    # @lru_cache(maxsize=10000)  # Кэшируем до 10,000 слов # Пока не будем
    def lemmatize_word(self, word: str) -> str:
        """
        Лемматизирует слово.

        Args:
            word (str): Слово для лемматизации.

        Returns:
            str: Лемма слова.
        """
        return self.morph.parse(word)[0].normal_form

    def extract_and_lemmatize_words(self, text: str) -> List[str]:
        """
        Извлекает слова из текста и лемматизирует их.

        Этот метод удаляет пунктуацию и пробелы, выделяет отдельные слова,
        приводит их к единой форме (лемматизирует), чтобы облегчить последующий анализ текста.

        Args:
            text (str): Исходный текст для обработки.

        Returns:
            List[str]: Список лемм, представляющих слова текста.
        """
        # Используем регулярное выражение для извлечения слов (буквы, цифры, символы подчеркивания)
        words = re.findall(r"\w+", text.lower())
        return [self.lemmatize_word(word) for word in words]

    def transliterate_word_base(self, word: str) -> str:
        """
        Транслитерирует слово с кириллицы на латиницу.

        Args:
            word (str): Слово для транслитерации.

        Returns:
            str: Транслитерированное слово.
        """
        return translit(word, "ru")

    def transliterate_word(self, word: str) -> List[str]:
        """
        Генерирует все возможные варианты транслитерации слова.

        Args:
            word (str): Слово для транслитерации.

        Returns:
            List[str]: Список всех возможных транслитераций.
        """

        def generate_combinations(current: str, remaining: str) -> List[str]:
            if not remaining:
                return [current]

            char = remaining[0]
            rest = remaining[1:]

            if char in self.transliteration_map:
                options = self.transliteration_map[char]
                combinations = []
                for option in options if isinstance(options, list) else [options]:
                    combinations.extend(generate_combinations(current + option, rest))
                return combinations
            else:
                return generate_combinations(current + char, rest)

        return generate_combinations("", word.lower())

    def transliterate_sentence(self, sentence: str) -> List[str]:
        """
        Транслитерирует слова в предложении, содержащие латиницу или специальные символы.

        Args:
            sentence (str): Исходное предложение.

        Returns:
            List[str]: Список всех вариантов транслитерации предложения.
        """
        words = sentence.split()
        results = []

        for word in words:
            if re.search(
                r"[a-zA-Z*@(-01]", word
            ):  # Проверка на латиницу или специальные символы
                transliterated_words = self.transliterate_word(word)
                base_translit = self.transliterate_word_base(word)

                # print("base_translit ",  base_translit)

                transliterated_words.append(base_translit.lower())
                results.extend(transliterated_words)
            else:
                results.append(word)

        return results

    def process_text(self, text: str) -> Set[str]:
        """
        Обрабатывает текст: приводит к нижнему регистру, очищает от пунктуации,
        транслитерирует и лемматизирует.

        Args:
            text (str): Исходный текст.

        Returns:
            Set[str]: Множество всех лемматизированных и транслитерированных слов.
        """
        text_lower = text.lower()  # Приведение к нижнему регистру
        text_lower = self.clean_text(text_lower)  # Очистка текста

        # Транслитерация текста
        transliterated_texts = set(
            self.transliterate_sentence(text_lower)
        )  # Убираем дубликаты

        # Вариант оптимизации
        # # Объединяем все строки в одну, разделённую пробелами
        # combined_text = ' '.join(transliterated_texts)
        # # Заменяем множество на эту объединённую строку
        # transliterated_texts = {combined_text}

        transliterated_texts.add(text_lower)  # Добавляем оригинальный текст

        # print(transliterated_texts)

        # Лемматизация только оригинального текста
        lemmatized_texts = set(self.extract_and_lemmatize_words(text_lower))

        # print("\n lemmatized_texts   ", lemmatized_texts)

        # Возвращаем объединённое множество лемматизированных и транслитерированных слов
        return lemmatized_texts.union(transliterated_texts)

    def is_near_match(self, word: str, banned_word: str) -> bool:
        """
        Проверяет, является ли слово похожим на запрещенное слово на основе расстояния Левенштейна.

        Args:
            word (str): Слово для сравнения.
            banned_word (str): Запрещенное слово для сравнения.

        Returns:
            bool: True, если слова похожи (расстояние меньше или равно порогу), иначе False.
        """
        return (
            Levenshtein.distance(word, banned_word)
            <= self.levenshtein_distance_threshold
        )

    def _check_word_list(self, text_words: List[str], banned_words: Set[str]) -> bool:
        """
        Проверяет текст на наличие слов из заданного списка с учётом расстояния Левенштейна.

        Args:
            text_words (List[str]): Список лемматизированных слов из текста.
            banned_words (Set[str]): Набор запрещённых слов.

        Returns:
            bool: True, если найдены запрещённые слова, иначе False.
        """
        for banned_word in banned_words:
            if banned_word in text_words:
                return True

            for word in text_words:
                if self.is_near_match(word, banned_word):
                    return True

        return False

    def has_banned_words(
        self, text: str, check_hard_banned: bool = False, check_banned: bool = True
    ) -> Tuple[float, bool]:
        """
        Проверяет текст на наличие запрещённых слов.

        Args:
            text (str): Текст для проверки.
            check_hard_banned (bool): Проверять ли строго запрещённые слова.
            check_banned (bool): Проверять ли нежелательные слова.

        Returns:
            Tuple[float, bool]: Кортеж, где первое значение - вероятность нахождения запрещённых слов,
                                второе - факт их наличия (True/False).
        """
        # Получаем объединённый набор лемматизированных и транслитерированных слов
        all_texts = self.process_text(text)

        # Проверка на наличие запрещённых слов
        if check_banned and self._check_word_list(all_texts, self.banned_words):
            return 0.8, True
        if check_hard_banned and self._check_word_list(
            all_texts, self.hard_banned_words
        ):
            return 1.0, True

        return 0.0, False

    def check_banned_words_with_weights(
        self, text: str, filename: str
    ) -> Tuple[float, bool]:
        """
        Проверяет текст на наличие запрещённых слов из CSV-файла с учётом их весов.

        Args:
            text (str): Текст для проверки.
            filename (str): Путь к CSV-файлу со словами.

        Returns:
            Tuple[float, bool]: Кортеж, где первое значение - общая вероятность нахождения запрещённых слов,
                                второе - факт их наличия (True/False).
        """
        # Загружаем слова и их веса из файла
        banned_words_with_weights = load_banned_words_with_ratings_from_csv(filename)

        # print(banned_words_with_weights)

        # Получаем объединённый набор лемматизированных и транслитерированных слов
        all_texts = self.process_text(text)

        total_weight = 0.0
        found_banned = False

        # Создаём словарь для быстрого доступа к весам и категориям
        banned_dict = {
            item["word"]: (item["category"], item["weight"])
            for item in banned_words_with_weights
        }

        found_words = []

        # Проверяем каждое слово в тексте на наличие в списке запрещённых слов
        for word in all_texts:
            # Проверяем точное совпадение
            if word in banned_dict:
                found_banned = True
                category, weight = banned_dict[word]
                total_weight += weight  # Суммируем вес найденных слов
                found_words.append(word)
                continue  # Переходим к следующему слову

            # Проверяем близость по написанию с учетом расстояния Левенштейна
            for banned_word, (category, weight) in banned_dict.items():
                if self.is_near_match(word, banned_word):
                    found_banned = True
                    total_weight += weight  # Суммируем вес найденных слов
                    found_words.append(banned_word)
                    break  # Выходим из цикла для данного слова

        # Определяем вероятность блокировки текста на основе общего веса
        probability = total_weight  # Примерное преобразование веса в вероятность

        # Проверка: если вероятность больше 1, устанавливаем её равной 1
        if probability > 1:
            probability = 1.0

        # print(found_worlds)

        return probability, found_banned

    def check_banned_words_with_categories(
        self, text: str, banned_words_file: str, categories_file: str
    ) -> Tuple[float, bool]:
        """
        Проверяет текст на наличие запрещённых слов из CSV-файла и вычисляет общую вероятность на основе коэффициентов категорий.
        """
        # Загружаем запрещённые слова и их категории из файла
        banned_words_with_weights = load_banned_words_with_ratings_from_csv(
            banned_words_file
        )
        # print("Banned words loaded:", banned_words_with_weights)

        # Загружаем категории и их коэффициенты
        categories_list = load_categories_from_csv(categories_file)
        # print("Categories loaded:", categories_list)

        # Преобразуем список категорий в словарь для быстрого доступа
        categories = {item["category"]: item["coefficient"] for item in categories_list}
        # print("Categories dictionary:", categories)

        # Получаем обработанный текст как список слов
        all_texts = self.process_text(text)
        # print("Processed text:", all_texts)

        total_probability = 0.0
        found_banned = False

        # Создаём словарь для быстрого доступа к категориям запрещённых слов
        banned_dict = {
            item["word"]: item["category"] for item in banned_words_with_weights
        }
        # print("Banned words dictionary:", banned_dict)

        # Проверяем каждое слово в тексте на наличие в списке запрещённых слов
        for word in all_texts:
            # print(f"Checking word: {word}")
            # Проверяем точное совпадение
            if word in banned_dict:
                found_banned = True
                category = banned_dict[word]
                coefficient = categories.get(
                    category
                )  # Получаем коэффициент для категории

                # print(f"Found exact match: {word} (Category: {category}, Coefficient: {coefficient})")

                if coefficient is not None:
                    total_probability += (
                        coefficient  # Суммируем вероятности на основе коэффициентов
                    )

                continue  # Переходим к следующему слову

            # Проверяем близость по написанию с учётом расстояния Левенштейна
            for banned_word in banned_dict.keys():
                if self.is_near_match(word, banned_word):
                    found_banned = True
                    category = banned_dict[banned_word]
                    coefficient = categories.get(
                        category
                    )  # Получаем коэффициент для категории

                    # print(f"Found close match: {banned_word} (Category: {category}, Coefficient: {coefficient})")

                    if coefficient is not None:
                        total_probability += (
                            coefficient  # Суммируем вероятности на основе коэффициентов
                        )

                    break  # Выходим из цикла для данного слова

        # Ограничиваем вероятность до 1.0
        if total_probability > 1:
            total_probability = 1.0

        # print(f"Final Total Probability: {total_probability}, Found Banned Words: {found_banned}")

        return total_probability, found_banned


if __name__ == "__main__":
    from config.settings import LEVENSHTEIN_DISTANCE

    # Пример использования (старый код)
    # directory_path = 'hard_banned_worlds_dir'  # Путь к папке с файлами
    # hard_banned_words = load_words_from_directory(directory_path)
    # banned_words = load_words_from_csv_file('banned_words.csv')
    # test_samples = load_test_samples('test_samples.csv')
    # # test_samples = load_test_samples('test_samples_small.csv')
    # moderator = TextModeration(banned_words, hard_banned_words, LEVENSHTEIN_DISTANCE)
    # for sample_text, expected in test_samples:
    #     result = moderator.has_banned_words(sample_text, check_hard_banned=True, check_banned=True)
    #     logging.info(f"Текст: \"{sample_text}\" - Ожидаемый: {expected}, Фактический: {result}")
    # #####################################################################################
    # banned_words_file = 'words.csv'  # Укажите путь к вашему CSV-файлу с запрещёнными словами
    # text_moderation = TextModeration(banned_words=[], hard_banned_words=[], levenshtein_distance_threshold=LEVENSHTEIN_DISTANCE)
    # # Тестовые случаи с ожидаемыми результатами
    # test_cases = [
    #     ("Текст с запрещённым словом apple и другим fruit.", (0.5, True)),  # apple (0.5)
    #     ("В этом предложении есть банан и морковь.", (0.0, True)),  #
    #     ("Я люблю есть donut и fig.", (0.3, True)),  # donut (0.2) + fig (0.1)
    #     ("Здесь нет запрещённых слов.", (0.0, False)),  # Нет запрещённых слов
    #     ("Какой замечательный grape у нас сегодня!", (0.3, True)),  # grape (0.3)
    #     ("Съел много carrot и eggplant.", (1.3, True)),  # carrot (0.5) + eggplant (0.8)
    #     ("Мой любимый десерт - donut.", (0.2, True)),  # donut (0.2)
    #     ("Эти фрукты: apple, banana и grape.", (1.1, True)),  # apple (0.5) + banana (0.3) + grape (0.3)
    #     ("Слово 'appl' слишком близко к 'apple'.", (0.5, True)),  # appl близко к apple
    #     ("Фрукты: banana, fig и unhealthy food.", (0.4, True)),  # banana (0.3) + fig (0.1)
    #     ("На завтрак я предпочитаю carrot и eggplant.", (1.3, True)),  # carrot (0.5) + eggplant (0.8)
    #     ("Я не ем unhealthy food, как donut.", (0.2, True)),  # donut (0.2)
    #     ("Это просто текст без запрещённых слов.", (0.0, False)),  # Нет запрещённых слов
    #     ("Сравните apple и appl, это близкие слова.", (0.5, True)),  # apple
    #     ("Я купил fruit и vegetable на рынке.", (0., False)),  # Нет запрещённых слов
    # ]
    # print("Результаты тестов:")
    # for text_to_check, expected in test_cases:
    #     probability, has_banned = text_moderation.check_banned_words_with_weights(text_to_check, banned_words_file)
    #     print(f"Текст: \"{text_to_check}\" - "
    #           f"Вероятность бл.: {probability:.2f}, "
    #           f"Наличие запрещ. слов: {has_banned} - "
    #           f"Ожидаемый результат: Вероятность {expected[0]:.2f}, Наличие {expected[1]}")
    # input_text = "I like apple and banana."
    # banned_words_file = 'banned_words_cat.csv'
    # categories_file = 'categories.csv'
    # # Create an instance of TextModeration
    # text_moderation = TextModeration(banned_words=[], hard_banned_words=[], levenshtein_distance_threshold=LEVENSHTEIN_DISTANCE)
    # # Call the method on the instance
    # probability, has_banned = text_moderation.check_banned_words_with_categories(input_text, banned_words_file, categories_file)
    # print(f"Total Probability: {probability}, Found Banned Words: {has_banned}")
    # -----------------------------------------------------------------------------------------
    # banned_words_file = 'banned_words_cat.csv'
    # categories_file = 'categories.csv'
    # text_moderation = TextModeration(banned_words=[], hard_banned_words=[], levenshtein_distance_threshold=LEVENSHTEIN_DISTANCE)
    # test_cases = [
    #     ("I like apple and banana.", 0.8, True),  # apple (0.5) + banana (0.3)
    #     ("I like grapes and oranges.", 0.3, True),  # grape (0.3)
    #     ("I like appl and banan.", 0.6, True),  # close matches: apple (0.5) + banana (0.3)
    #     ("I enjoy rice and chicken meat.", 1.0, True),  # rice (0.4) + chicken meat (0.6)
    #     ("I love chips and cookies.", 0.5, True)   # chips (0.3) + cookies (0.2)
    # ]
    # for input_text, expected_probability, expected_found in test_cases:
    #     probability, has_banned = text_moderation.check_banned_words_with_categories(input_text, banned_words_file, categories_file)
    #     print(f"Input: {input_text}\nTotal Probability: {probability}, Expected: {expected_probability}, Found Banned Words: {has_banned}, Expected Found: {expected_found}\n")
    # -----------------------------------------------------------------------------------------
    # banned_words_file = 'banned_words_cat_2.csv'
    # НОВЫЙ ФАИЛ
    banned_words_file = r"D:\Pets\NetTyan\Python\NetTyanRepo\NetTyan\docker\filter\feature_filter\data\block_words\banned_words_cat_2_2.csv" # "banned_words_cat_2_2.csv"

    categories_file = r"D:\Pets\NetTyan\Python\NetTyanRepo\NetTyan\docker\filter\feature_filter\data\block_words\categories_2.csv" # "categories_2.csv"

    text_moderation = TextModeration(
        banned_words=[],
        hard_banned_words=[],
        levenshtein_distance_threshold=0.5  # LEVENSHTEIN_DISTANCE,
    )

    test_cases = [
        ("I like jfdkhwemvsddsfd kfdjfkjdsfasssaqng.", 0.6, True),
        ("I like  президент  пробный текст эксперимент слово.", 0.35, True),
        ("Привет, как дела?", 0.35, False),
        ("Друзья, что случилось?", 0.35, False),
        ("CJlaDКа9л БеПа Давай поговорим о чем то интересном в игре без этих глупостей", 0.9, False),
        ("хуем тя кто подтянул отвечай с члена?", 0.9, False),
        ("Mat_Eby_Tvoy", 0.9, False),
        # ("I like grapes and oranges.", 0.3, True),  #
    ]

    for input_text, expected_probability, expected_found in test_cases:
        probability, has_banned = text_moderation.check_banned_words_with_categories(
            input_text, banned_words_file, categories_file
        )
        print(
            f"Input: {input_text}\nTotal Probability: {probability}, Expected: {expected_probability}, Found Banned Words: {has_banned}, Expected Found: {expected_found}\n"
        )
    # приветпокакакдела
    # пр ив ет
    # привет