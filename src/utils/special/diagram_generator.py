"""
Утилита для создания диаграммы классов и модулей проекта.

Эта утилита использует pyreverse для генерации диаграмм UML
в формате .dot, которые затем можно преобразовать в изображения
с помощью Graphviz.
"""

import os
import subprocess
import sys
import traceback

"""
Утилита для создания диаграммы классов и модулей проекта.

Эта утилита использует pyreverse для генерации диаграмм UML 
в формате .dot, которые затем можно преобразовать в изображения 
с помощью Graphviz.
"""

import os
import subprocess
import sys

REPO_CODE_PATH = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

"""
Утилита для создания диаграммы классов и модулей проекта.

Эта утилита использует pyreverse для генерации диаграмм UML 
в формате .dot, которые затем можно преобразовать в изображения 
с помощью Graphviz.
"""

import argparse
import os
import shutil
import subprocess
import sys
import traceback


def check_tool_exists(tool_name):
    """Проверяет, установлен ли инструмент в системе."""
    return shutil.which(tool_name) is not None


def generate_pyreverse_diagram():
    """Генерирует диаграмму классов и модулей проекта с помощью pyreverse."""

    # Получаем путь к корню проекта
    src_dir = REPO_CODE_PATH

    print(f"Генерация диаграммы классов для директории: {src_dir}")

    # Создаем директорию для диаграмм, если она не существует
    diagrams_dir = os.path.join(os.path.dirname(src_dir), "docs", "diagrams")
    os.makedirs(diagrams_dir, exist_ok=True)

    # Команда для генерации диаграмм (классов и модулей)
    cmd = [
        "pyreverse",
        "-o",
        "png",  # Формат вывода
        "-p",
        "NetTyan",  # Имя проекта
        "-d",
        diagrams_dir,  # Директория для вывода
        "--ignore",
        "tests,__pycache__",  # Игнорировать эти директории
        "-A",  # Показывать все атрибуты
        "-s",
        "1",  # Размер шрифта
        "-m",
        "y",  # Показывать модули
        src_dir,  # Директория с кодом
    ]

    try:
        if not check_tool_exists("pyreverse"):
            print("Pyreverse не найден. Устанавливаем pylint...")
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "pylint"], check=True
            )

        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        print(f"Диаграммы успешно созданы в директории: {diagrams_dir}")
        print(
            "Файлы: classes_NetTyan.png (диаграмма классов) и packages_NetTyan.png (диаграмма модулей)"
        )

        # Вывести дополнительную информацию из процесса
        if result.stdout:
            print("Вывод процесса:")
            print(result.stdout)

        return True
    except subprocess.CalledProcessError as e:
        print(f"Ошибка при генерации диаграммы с pyreverse: {e}")
        if e.stdout:
            print("Стандартный вывод:")
            print(e.stdout)
        if e.stderr:
            print("Стандартная ошибка:")
            print(e.stderr)
        traceback.print_exc()
        return False
    except Exception as e:
        print(f"Произошла ошибка при использовании pyreverse: {e}")
        traceback.print_exc()
        return False


def generate_deps_diagram():
    """Генерирует диаграмму зависимостей проекта с помощью pydeps."""

    # Получаем путь к корню проекта
    src_dir = REPO_CODE_PATH

    print(f"Генерация диаграммы зависимостей для директории: {src_dir}")

    # Создаем директорию для диаграмм, если она не существует
    diagrams_dir = os.path.join(os.path.dirname(src_dir), "docs", "diagrams")
    os.makedirs(diagrams_dir, exist_ok=True)

    output_file = os.path.join(diagrams_dir, "dependencies.svg")

    # Команда для генерации диаграммы зависимостей
    cmd = [
        "pydeps",
        src_dir,  # Директория с кодом
        "--only",
        "src",  # Только модули из src
        "--cluster",  # Группировать по пакетам
        "--max-bacon",
        "10",  # Максимальная глубина зависимостей
        "--no-config",  # Не использовать конфигурационный файл
        "--reverse",  # Обратные зависимости (что использует этот модуль)
        "--exclude",
        "__pycache__,tests",  # Исключить эти директории
        "-o",
        output_file,  # Файл для сохранения диаграммы
    ]

    try:
        if not check_tool_exists("pydeps"):
            print("Pydeps не найден. Устанавливаем pydeps...")
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "pydeps"], check=True
            )

        if not check_tool_exists("dot"):
            print("Внимание: Graphviz (команда dot) не найдена в системе.")
            print(
                "Установите Graphviz с сайта https://graphviz.org/download/ или через менеджер пакетов."
            )

        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        print(f"Диаграмма зависимостей успешно создана в: {output_file}")

        # Вывести дополнительную информацию из процесса
        if result.stdout:
            print("Вывод процесса:")
            print(result.stdout)

        return True
    except subprocess.CalledProcessError as e:
        print(f"Ошибка при генерации диаграммы с pydeps: {e}")
        if e.stdout:
            print("Стандартный вывод:")
            print(e.stdout)
        if e.stderr:
            print("Стандартная ошибка:")
            print(e.stderr)
        traceback.print_exc()
        print(
            "Убедитесь, что pydeps установлен (pip install pydeps) и graphviz установлен в системе"
        )
        return False
    except Exception as e:
        print(f"Произошла ошибка при использовании pydeps: {e}")
        traceback.print_exc()
        return False


def generate_simple_diagram():
    """Генерирует простую текстовую диаграмму структуры проекта."""
    src_dir = REPO_CODE_PATH
    diagrams_dir = os.path.join(os.path.dirname(src_dir), "docs", "diagrams")
    os.makedirs(diagrams_dir, exist_ok=True)

    output_file = os.path.join(diagrams_dir, "structure.txt")

    print(f"Генерация простой структуры проекта в файл: {output_file}")

    try:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("Структура проекта NetTyan:\n\n")

            for root, dirs, files in os.walk(src_dir):
                # Пропускаем __pycache__ и другие технические директории
                dirs[:] = [
                    d
                    for d in dirs
                    if d not in ["__pycache__", ".git", ".venv", ".vscode"]
                ]

                # Считаем отступ от корневой директории
                level = root.replace(src_dir, "").count(os.sep)
                indent = "    " * level

                # Добавляем имя директории
                subdir = os.path.basename(root)
                if level > 0:
                    f.write(f"{indent}└── {subdir}/\n")
                else:
                    f.write(f"{subdir}/\n")

                # Добавляем файлы
                sub_indent = "    " * (level + 1)
                py_files = [file for file in files if file.endswith(".py")]
                for i, file in enumerate(py_files):
                    if i == len(py_files) - 1:
                        f.write(f"{sub_indent}└── {file}\n")
                    else:
                        f.write(f"{sub_indent}├── {file}\n")

        print(f"Простая структура проекта успешно создана в: {output_file}")
        return True
    except Exception as e:
        print(f"Произошла ошибка при создании простой диаграммы: {e}")
        traceback.print_exc()
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Генерация диаграмм для проекта NetTyan"
    )
    parser.add_argument(
        "--mode",
        choices=["pydeps", "pyreverse", "simple", "all"],
        default="all",
        help="Выбор инструмента для генерации диаграммы",
    )

    args = parser.parse_args()

    success = False

    if args.mode == "pydeps" or args.mode == "all":
        print("\n=== Генерация диаграммы с помощью pydeps ===")
        pydeps_success = generate_deps_diagram()
        success = success or pydeps_success

    if args.mode == "pyreverse" or args.mode == "all":
        print("\n=== Генерация диаграммы с помощью pyreverse ===")
        pyreverse_success = generate_pyreverse_diagram()
        success = success or pyreverse_success

    if args.mode == "simple" or (args.mode == "all" and not success):
        print("\n=== Генерация простой текстовой диаграммы ===")
        simple_success = generate_simple_diagram()
        success = success or simple_success

    if success:
        print("\nГотово! Диаграмма(ы) успешно созданы.")
    else:
        print(
            "\nВНИМАНИЕ: Не удалось создать ни одну диаграмму. Проверьте требуемые зависимости:"
        )
        print("1. pip install pylint pydeps")
        print("2. Установите Graphviz: https://graphviz.org/download/")
        print("3. Убедитесь, что Graphviz добавлен в PATH")
