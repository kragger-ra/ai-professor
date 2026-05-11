# language: ru

Функционал: Course config с PersonaLab-дефолтами (Lecture-сборка)
  Lecture-сборка по умолчанию подставляет PersonaLab Workshop,
  чтобы существующий курс работал без course_config.yml.
  Любой загруженный YAML может это переопределить.

  Сценарий: Дефолты Lecture сохраняют PersonaLab
    Дано чистый рабочий каталог без current_course.json
    Когда я вызываю get_current
    Тогда поле name равно "PersonaLab Workshop"
    И поле topic равно "цифровых персонажей"
    И поле short_name равно "PersonaLab"

  Сценарий: Render с дефолтами подставляет PersonaLab
    Дано чистый рабочий каталог без current_course.json
    Когда я рендерю шаблон "Курс {COURSE_NAME} — про {COURSE_TOPIC}"
    Тогда результат равен "Курс PersonaLab Workshop — про цифровых персонажей"

  Сценарий: YAML может перебить PersonaLab-дефолты
    Дано YAML-файл с полем name "Веб-разработка"
    Когда я вызываю apply_from_yaml
    Тогда поле name равно "Веб-разработка"
    И поле name не равно "PersonaLab Workshop"

  Сценарий: Шаблон без COURSE_* placeholder возвращается как есть
    Дано чистый рабочий каталог без current_course.json
    Когда я рендерю шаблон "Простая строка без замен"
    Тогда результат равен "Простая строка без замен"
