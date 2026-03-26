# Функция для конвертации слова в кодовые точки
def word_to_codepoints(word):
    return [ord(char) for char in word]


# Функция для конвертации кодовых точек обратно в слово
def codepoints_to_word(codepoints):
    return "".join(chr(n) for n in codepoints)


# Пример слова
word = "сложное слово"

# Конвертация слова в кодовые точки
codepoints = word_to_codepoints(word)
print("Кодовые точки:", codepoints)

# Конвертация кодовых точек обратно в слово
reconstructed_word = codepoints_to_word(codepoints)
print("Восстановленное слово:", reconstructed_word)
