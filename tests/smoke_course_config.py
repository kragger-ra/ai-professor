"""Smoke test: course_config + CLI round trip."""
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from lecture import course_config


def main():
    with tempfile.TemporaryDirectory() as tmp:
        # Manually create a course_config.yml as the CLI would
        yml = Path(tmp) / "course_config.yml"
        yml.write_text(
            "course:\n"
            "  name: Линейная алгебра\n"
            "  topic: векторы и матрицы\n"
            "  short_name: LinAlg\n"
            "  audience: студент\n"
            "persona:\n"
            "  teaching_style: строго\n",
            encoding="utf-8",
        )

        cfg = course_config.apply_from_yaml(str(yml))
        print(f"Loaded: {cfg.fields}")
        assert cfg.fields["name"] == "Линейная алгебра"
        assert cfg.fields["topic"] == "векторы и матрицы"
        assert cfg.fields["teaching_style"] == "строго"

        # Render a template
        template = "Курс «{COURSE_NAME}» — про {COURSE_TOPIC}."
        rendered = cfg.render(template)
        print(f"Rendered: {rendered}")
        assert rendered == "Курс «Линейная алгебра» — про векторы и матрицы."

        # Persistence: get_current should pick it up
        current = course_config.get_current()
        print(f"get_current: {current.fields['name']}")
        assert current.fields["name"] == "Линейная алгебра"

    print("[OK] course_config smoke passed")


if __name__ == "__main__":
    # Run inside a tmp cwd so data/current_course.json doesn't pollute the repo.
    # Chdir back to home before TemporaryDirectory cleans up to avoid Win32 lock.
    orig_cwd = os.getcwd()
    cwd = tempfile.mkdtemp()
    try:
        os.chdir(cwd)
        main()
    finally:
        os.chdir(orig_cwd)
        try:
            import shutil
            shutil.rmtree(cwd, ignore_errors=True)
        except Exception:
            pass
