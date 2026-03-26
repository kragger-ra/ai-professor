import csv
import os
import re

import pymorphy2


def is_cyrillic(word):
    """Checks if the word consists only of Cyrillic characters."""
    return bool(re.match(r"^[а-яА-ЯёЁ]+$", word))


def normalize_word(word):
    """Normalizes the word to its base form (lemmatization)."""
    morph = pymorphy2.MorphAnalyzer()
    parsed_word = morph.parse(word)[0]
    return parsed_word.normal_form


def process_csv(filename):
    """Reads the CSV file and processes the words."""
    words_set = set()  # Use a set to remove duplicates

    with open(filename, newline="", encoding="utf-8") as csvfile:
        reader = csv.reader(csvfile)
        for row in reader:
            for word in row:
                word = word.strip()  # Remove whitespace
                if is_cyrillic(word):  # Check for Cyrillic characters
                    normalized_word = normalize_word(
                        word.lower()
                    )  # Normalize and convert to lowercase
                    words_set.add(normalized_word)  # Add to the set

    return words_set


def save_to_csv(words_set, original_filename):
    """Saves unique words to a new CSV file with 'processed_' prefix."""
    base_name, ext = os.path.splitext(original_filename)
    new_filename = f"{base_name}_processed{ext}"  # Create new filename with prefix

    with open(new_filename, mode="w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        for word in sorted(words_set):  # Sort words before writing
            writer.writerow([word])  # Write each word to a new row

    print(f"Processed words saved to file: {new_filename}")


def process_directory(directory):
    """Processes all CSV files in the specified directory."""
    for filename in os.listdir(directory):
        if filename.endswith(".csv"):
            full_path = os.path.join(directory, filename)
            print(f"Processing file: {full_path}")
            unique_words = process_csv(full_path)
            save_to_csv(unique_words, full_path)


if __name__ == "__main__":
    input_directory = (
        "words_list_dir"  # Specify the path to your directory containing CSV files
    )
    process_directory(input_directory)  # Process all CSV files in the directory
