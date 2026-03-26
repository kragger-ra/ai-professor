import pytest

from src.text_moderation import TextModeration


@pytest.fixture
def moderation():
    banned_words = ["спам", "мошенничество", "фейк"]
    hard_banned_words = ["оскорбление", "ругательство"]
    levenshtein_distance_threshold = 2
    return TextModeration(
        banned_words, hard_banned_words, levenshtein_distance_threshold
    )


def test_lemmatize_word(moderation):
    word = "играю"
    expected = "играть"
    assert moderation.lemmatize_word(word) == expected


def test_extract_and_lemmatize_words(moderation):
    text = "Я люблю играть в игры."
    expected = ["я", "любить", "играть", "в", "игра"]
    assert sorted(moderation.extract_and_lemmatize_words(text)) == sorted(expected)


def test_transliterate_word_base(moderation):
    word = "privet"
    expected = "привет"
    assert moderation.transliterate_word_base(word) == expected


def test_transliterate_word(moderation):
    word = "privet"
    transliterations = moderation.transliterate_word(word)
    assert "привет" in transliterations


def test_has_banned_words_exact_match(moderation):
    text = "Это спам"
    probability, found = moderation.has_banned_words(text, check_banned=True)
    assert probability == 0.8
    assert found is True


def test_has_banned_words_hard_banned(moderation):
    text = "Это оскорбление"
    probability, found = moderation.has_banned_words(text, check_hard_banned=True)
    assert probability == 1.0
    assert found is True


def test_has_banned_words_with_typos(moderation):
    text = "Это спмм"  # Опечатка в слове "спам"
    probability, found = moderation.has_banned_words(text, check_banned=True)
    assert probability == 0.8
    assert found is True


def test_check_word_list_with_close_matches(moderation):
    text_words = ["игра", "спмм"]  # Опечатка в слове "спам"
    banned_words = {"спам"}
    result = moderation._check_word_list(text_words, banned_words)
    assert result is True


def test_check_banned_words_with_weights(moderation):
    text = "Это фейк информация eggplant."

    # Предполагается, что файл со словами уже загружен
    probability, found = moderation.check_banned_words_with_weights(
        text, "banned_words_cat.csv"
    )

    expected_probability = 0.8
    expected_found = True

    assert pytest.approx(probability) == expected_probability
    assert found is True


def test_check_banned_words_with_categories(moderation):
    text = "I like grapes and oranges."

    # Проверяем наличие запрещенных слов с учетом категорий
    probability, found = moderation.check_banned_words_with_categories(
        text, "banned_words_cat.csv", "categories.csv"
    )

    expected_probability = 1.0  # 0.5 + 0.5
    expected_found = True

    assert probability == expected_probability
    assert found is True


def test_is_near_match(moderation):
    # Тестируем положительные случаи (похожие слова)
    assert moderation.is_near_match("спам", "спмм")  # Опечатка
    assert moderation.is_near_match(
        "мошенничество", "мошенничество"
    )  # Точное совпадение
    assert moderation.is_near_match("фейк", "фейк")
    assert moderation.is_near_match("фейк", "фек")

    # Тестируем отрицательные случаи (непохожие слова)
    assert not moderation.is_near_match("спам", "другие")
    assert not moderation.is_near_match("мошенничество", "честность")
    assert not moderation.is_near_match("фейк", "реальность")


if __name__ == "__main__":
    pytest.main()
