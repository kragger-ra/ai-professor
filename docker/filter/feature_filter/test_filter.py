from src.text_moderation import TextModeration

if __name__ == "__main__":
    blocked_csv_dir = (
        r"C:\Users\Tseh\Documents\Files\NeuroDeva\NetTyan\docker\filter\block_words"
    )
    banned_words_file = blocked_csv_dir + "/banned_words_cat_2_2.csv"

    categories_file = blocked_csv_dir + "/categories_2.csv"

    text_moderation = TextModeration(
        banned_words=[],
        hard_banned_words=[],
        levenshtein_distance_threshold=0.5,
    )

    test_cases = [
        ("I like jfdkhwemvsddsfd kfdjfkjdsfasssaqng.", 0.6, True),
        ("I like  президент  пробный текст эксперимент слово.", 0.35, True),
        ("gривет", 0.35, True),
        # ("I like grapes and oranges.", 0.3, True),  #
    ]

    for input_text, expected_probability, expected_found in test_cases:
        probability, has_banned = text_moderation.check_banned_words_with_categories(
            input_text, banned_words_file, categories_file
        )
        print(
            f"Input: {input_text}\nTotal Probability: {probability}, Expected: {expected_probability}, Found Banned Words: {has_banned}, Expected Found: {expected_found}\n"
        )
