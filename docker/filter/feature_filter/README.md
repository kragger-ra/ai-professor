
# content-moderator

## Overview

Версия питон  Python 3.10.15   
пакеты  в requirements.txt

## Features

Два варианта набора слов:   

banned_words и hard_banned_words     

hard_banned_words  - 100% блокировать (вероятность если находит выдает 1)        
положить списки слов в csv фаилах (в один столбец) в коде указать  куда    
в примеере папка hard_banned_words_dir   
смотреть пример  hard1.csv hard2.csv     

banned_words  - лучше блокировать (вероятность если находит выдает 0.8)   
для них  просто указать csv  фаил путь/название один фаил     


Сами списки слов будем хранить отдельно    
## Installation    

python310.15 -m pip install -r requirements.txt

## Usage   

```python 


```

# Text Moderation

Text Moderation – это модуль для проверки текста на наличие запрещённых слов. Поддерживает проверку слов с учётом опечаток (расстояние Левенштейна) и транслитерации.

## Установка

1. Клонируйте репозиторий:
    ```bash
    git clone <репозиторий>
    cd <папка>
    ```

2. Установите зависимости:
    ```bash
    pip install -r requirements.txt
    ```

## Использование

```python
from src.text_moderation import TextModeration

banned_words = ["спам", "мошенничество"]
hard_banned_words = ["оскорбление", "ругательство"]
moderation = TextModeration(banned_words, hard_banned_words, levenshtein_distance_threshold=2)

text = "Это сообщение содержит спам."
probability, found = moderation.has_banned_words(text)
print(probability, found)  # Вернёт: (0.8, True)
```

## Запустите тесты с помощью unittest:

python -m unittest discover tests

python310.15 -m unittest discover tests

Запуск с подробным выводом   
python310.15 -m unittest discover -s tests -v


project/
├── src/
│   ├── transliteration_map.py
│   ├── utils.py
│   ├── text_moderation.py
├── config/
│   ├── settings.py
├── tests/
│   ├── test_text_moderation.py
├── README.md




python310.15 -m pip install pytest


pytest py_test_text_moderation.py
pytest -v


python310.15 database_viewer.py

python310.15 -m  database_viewer.py

python310.15 -m  scripts.database_viewer

Категории

child.csv drugs.scv  nationalism.csv politix.csv seks.csv other bad words

Пока такие категории
child
sx
nation
politix
other
