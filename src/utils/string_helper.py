import json
import random
import re
from dataclasses import dataclass, field
from typing import Dict, List, Union

import cyrtranslit


def fix_line_splitters(text: str) -> str:
    return "\n".join(text.splitlines())


def dict_to_str(dict: dict) -> str:
    return json.dumps(dict, ensure_ascii=False, indent=2)


@dataclass
class RepeatingDict:
    data: Dict[str, List[str]] = field(default_factory=dict)
    max_size: int = 1000

    def add(self, value: str, key: str = "default") -> None:
        if key not in self.data:
            self.data[key] = []

        repeated_list = self.data[key]

        if value in repeated_list:
            repeated_list.remove(value)

        repeated_list.append(value)
        if len(repeated_list) > self.max_size:
            repeated_list.pop(0)

    def get_list(self, key: str = "default") -> List[str]:
        return self.data.get(key, [])


class NonRepeatRandom:
    def __init__(self, max_history: int = 1000):
        self.repeating_dict = RepeatingDict(max_size=max_history)
        self.symbol_map = {"#": "[!РЕШЕТКА]", "@": "[!СОБАКА]"}
        self.reverse_symbol_map = {v: k for k, v in self.symbol_map.items()}

    def _encode_special_symbols(self, text: str) -> str:
        for symbol, encoded in self.symbol_map.items():
            text = text.replace(symbol, encoded)
        return text

    def _decode_special_symbols(self, text: str) -> str:
        for encoded, symbol in self.reverse_symbol_map.items():
            text = text.replace(encoded, symbol)
        return text

    def apply_shuffle(self, text: str) -> str:
        text = self._encode_special_symbols(text)

        sections = text.split("#")
        for i in range(1, len(sections), 2):
            if sections[i].strip():
                words = sections[i].split()
                random.shuffle(words)
                sections[i] = " ".join(words)

        text = "".join(sections)
        text = text.replace("@", " ")
        text = self._decode_special_symbols(text)
        return text.strip()

    def choice(self, values: Union[str, List[str]], key: str = "default") -> str:
        items = values.split(",") if isinstance(values, str) else values

        if not items:
            raise ValueError("No values provided for selection")

        repeated_list = self.repeating_dict.get_list(key)

        available_items = [item for item in items if item not in repeated_list]

        if not available_items:

            repeated_matches = [item for item in repeated_list if item in items]
            if len(repeated_matches) > 1:
                available_items = repeated_matches[: len(repeated_matches) // 2]
            else:
                available_items = items

        result = random.choice(available_items)
        self.repeating_dict.add(result, key)
        return result

    def r(self, values: Union[str, List[str]], key: str = "default") -> str:
        return self.choice(values, key)

    def s(self, text: str) -> str:
        return self.apply_shuffle(text)


def cut_spaces(inp: str) -> str:
    """
    Removes extra spaces from the input string, ensuring no more than one consecutive space.

    Args:
        inp (str): The input string to process.

    Returns:
        str: The processed string with extra spaces removed.
    """
    result = ""
    cnt = 0
    for letter in inp:
        if letter == " ":
            cnt += 1
            if cnt > 1:
                pass
                # cnt=0
            else:
                result += letter
        else:
            result += letter
            cnt = 0
    return result.strip()


def translit(x: str) -> str:
    """
    Transliterates the given string from Latin to Cyrillic script.

    Args:
        x (str): The input string to be transliterated.

    Returns:
        str: The transliterated string in Cyrillic script.
    """
    try:
        result = x
        defaultCyrReplaceMap = {"x": "Кс", "h": "Х"}
        for symbol in defaultCyrReplaceMap:
            result = result.replace(symbol, defaultCyrReplaceMap[symbol].lower())
            result = result.replace(symbol.upper(), defaultCyrReplaceMap[symbol])
        partCyrReplaceMap = {
            "sh": "щ",
            "Sh": "Щ",
            "sH": "щ",
            "SH": "Щ",
            "ch": "ч",
            "ch": "ч",
            "CH": "Ч",
            "cH": "ч",
        }
        for part in partCyrReplaceMap:
            result = result.replace(part, partCyrReplaceMap[part])
        result = cyrtranslit.to_cyrillic(result, "ru")
    except BaseException as err:
        print("ошибка ", err, " при транслитерации =(")
        result = x
    return result


def mc_chat_fix_old_translit(inp: str) -> str:
    """
    Prepares the input string for chat printing by removing restricted characters,
    transliterating, and ensuring a minimum length.

    Args:
        inp (str): The input string to be prepared.

    Returns:
        str: The prepared string ready for chat printing.
    """
    restrictedChars = """\n\r|!'=#".,-/\\&^%$#@{}[]()*"""
    for char in restrictedChars:
        inp = inp.replace(char, " ")
    inp = translit(cut_spaces(inp))
    if len(inp) < 2:
        inp = inp + "лол"
    return inp


def mc_chat_fix(text: str) -> str:
    """
    Clean text to only allow Russian and English characters.

    Args:
        text (str): Input text to clean

    Returns:
        str: Cleaned text with only Russian and English characters
    """
    # Russian: А-Я, а-я (Unicode: 0410-042F, 0430-044F)
    # English: A-Z, a-z
    pattern = r"[^а-яА-Яa-zA-Z0-9ё ]"
    text = re.sub(pattern, " ", text)
    english_chars = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")
    digits = set("1234567890")
    char_num = 0
    digit_num = 0
    text_before = ""
    text_after = ""
    for char in text:
        if char in english_chars:
            char_num += 1
        if char in digits:
            digit_num += 1
            if digit_num > 5:
                continue  # TODO add logic digits transliterate
        if char_num <= 5:
            text_before += char
        else:
            text_after += char

    return cut_spaces(text_before + translit(text_after))


def prepare_mc_chat_send(message: str, max_length=80) -> list[str]:
    if len(message) > 0:
        if message[0] in ["@", "/", "#"]:  # minecraft commands processing
            return [message]
        return [  # temporal fix TODO make workaround for bedwars detecting
            str(mc_chat_fix(msg))  # str("!" + mc_chat_fix(msg))
            for msg in smart_sentence_split(message, max_length=max_length)
        ]
    else:
        return []


def smart_sentence_split(
    text: str, max_length: int = 60, min_divide_length: int = 8
) -> list[str]:
    """
    Split text into chunks respecting sentence boundaries and length limits.

    Args:
        text (str): Input text to split.
        max_length (int, optional): Maximum chunk length. Defaults to 40.
        min_divide_length (int, optional): Minimum chunk length to divide. Defaults to 8.

    Returns:
        list[str]: List of text chunks.

    Note:
        - Tries to keep sentences together if their combined length is within limits.
        - Splits long words if they exceed max_length.
    """
    # Split by punctuation marks while preserving them
    sentences = []
    current = ""

    i = 0
    while i < len(text):
        current += text[i]
        if text[i] in ".!?":
            # Check for multiple punctuation marks
            while i + 1 < len(text) and text[i + 1] in ".!?":
                i += 1
                current += text[i]
            sentences.append(current.strip())
            current = ""
        i += 1

    if current:
        sentences.append(current.strip())

    # Обрабатываем каждое предложение
    result = []
    current_chunk = ""

    for sentence in sentences:
        if len(sentence) > max_length:
            words = sentence.split()
            temp = ""
            for word in words:
                potential_chunk = (temp + " " + word).strip()
                if len(potential_chunk) <= max_length:
                    temp = potential_chunk
                else:
                    if temp:
                        result.append(temp)
                        temp = ""
                    if len(word) > max_length:
                        while word:
                            result.append(word[:max_length])
                            word = word[max_length:]
                    else:
                        temp = word
            if temp:
                result.append(temp)
        else:
            potential_chunk = (current_chunk + " " + sentence).strip()
            if len(potential_chunk) <= max_length:
                current_chunk = potential_chunk
            else:
                if current_chunk:
                    result.append(current_chunk)
                current_chunk = sentence

    if current_chunk:
        result.append(current_chunk)

    # Ensure chunks meet the minimum length requirement
    final_result = []
    temp_chunk = ""
    for chunk in result:
        if len(temp_chunk) + len(chunk) + 1 <= max_length:
            temp_chunk = (temp_chunk + " " + chunk).strip()
        else:
            if temp_chunk:
                final_result.append(temp_chunk)
            temp_chunk = chunk
    if temp_chunk:
        final_result.append(temp_chunk)
    return final_result


def check(condition, message):
    if not condition:
        print(f"Error: {message}")


if __name__ == "__main__":

    print(
        mc_chat_fix("Hilло Мир 1235646457 ! dfsdkjg чем-нибудь!Лёха!")
    )  # Returns "HelloМир"
    print(mc_chat_fix("Test@#$%^&"))  # Returns "Test"
    print(mc_chat_fix("ПРИВЕТ123ABC"))  # Returns "ПРИВЕТABC"

    nrr = NonRepeatRandom()

    print("Random selection test:")
    for _ in range(5):
        print(nrr.r("1,2,3,4,5"))

    print("\nShuffle test:")
    test_text = "#word1 word2 word3# normal text #word4 word5#"
    print(f"Original: {test_text}")
    print(f"Shuffled: {nrr.s(test_text)}")

    # Test 1: Long word splitting
    long_word = "a" * 150
    max_len = 40
    chunks = smart_sentence_split(long_word)
    print("Test 1 - Long word splitting:")
    print(chunks)
    check(len(max(chunks, key=len)) <= max_len, "Test 1 failed")

    # Test 2: Short sentences combining
    # NEED TO BE IN 1 CHUNK
    short_sentences = "Hello. Good. Guy."
    chunks = smart_sentence_split(short_sentences)
    print("\nTest 2 - Short sentences:")
    print(chunks)
    check(len(chunks) == 1, "Test 2 failed: Incorrect number of chunks")

    short_sentences = "Hello. Good. Guy. Hello. Good. Guy. Hello. Good. Guy. Hello. Good. Guy. Hello. Good. Guy. Hello. Good. Guy."
    chunks = smart_sentence_split(short_sentences)
    print("\nTest 2.1 - Short sentences many:")
    print(chunks)
    check(len(chunks) == 2, "Test 2.1 failed: Incorrect number of chunks")
    # Test 3: Regular sentence splitting
    # NEED TO BE IN 2 CHUNKS
    regular_text = "How are you? Are you good?"
    chunks = smart_sentence_split(regular_text)
    print("\nTest 3 - Regular sentences:")
    print(chunks)
    check(len(chunks) == 2, "Test 3 failed: Incorrect number of chunks")
    # Test 4: Sentence length control
    long_sentence = "This is a longer sentence that should divide to several chunks even it has no punctuation marks, however, it should not exceed the maximum length of 100 characters"
    chunks = smart_sentence_split(long_sentence)
    print("\nTest 4 - Long sentence control:")
    print(chunks)
    check(
        all(len(chunk) <= max_len for chunk in chunks),
        "Test 4 failed: Chunk length exceeds max_length",
    )

    print("\nAll tests completed!")
    print(
        prepare_mc_chat_send(
            "Hello, my name is Alex! Как дела хахахХАХАХхах ты хто такой я тя не звал заХВАХХА, авлоыпро чо по чом ыы -а-выа выца"
        )
    )
