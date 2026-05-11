"""Step definitions for cli_prepare_rag.feature."""

from pathlib import Path

import yaml
from pytest_bdd import given, parsers, scenarios, then, when

FEATURE = str(Path(__file__).resolve().parents[1] / "features" / "cli_prepare_rag.feature")
scenarios(FEATURE)


CLI_MODULE = "tools.prepare_rag_package"


# --- Given ------------------------------------------------------------------

@given("исходная директория с двумя .md и одним .txt")
def given_src_three(context, tmp_cwd):
    src = tmp_cwd / "raw_kb"
    src.mkdir()
    (src / "lecture1.md").write_text("# L1\n\n\nA про векторы.", encoding="utf-8")
    (src / "lecture2.md").write_text("# L2\n\n\nA про матрицы.", encoding="utf-8")
    (src / "notes.txt").write_text("plain notes\n\n\nstuff", encoding="utf-8")
    context["src"] = str(src)
    context["out"] = str(tmp_cwd / "out")


@given("исходная директория с одним .md")
def given_src_one(context, tmp_cwd):
    src = tmp_cwd / "raw_kb"
    src.mkdir()
    (src / "lecture.md").write_text("# L\n\n\nstuff", encoding="utf-8")
    context["src"] = str(src)
    context["out"] = str(tmp_cwd / "out")


@given("пустая исходная директория")
def given_src_empty(context, tmp_cwd):
    src = tmp_cwd / "empty"
    src.mkdir()
    context["src"] = str(src)
    context["out"] = str(tmp_cwd / "out")


@given("путь источника, которого нет на диске")
def given_src_missing(context, tmp_cwd):
    context["src"] = str(tmp_cwd / "does_not_exist")
    context["out"] = str(tmp_cwd / "out")


@given("--out указывает на уже непустую папку")
def given_out_nonempty(context):
    out = Path(context["out"])
    out.mkdir(parents=True, exist_ok=True)
    (out / "stray.txt").write_text("stray", encoding="utf-8")


# --- When -------------------------------------------------------------------

def _run_cli(argv) -> int:
    import importlib
    mod = importlib.import_module(CLI_MODULE)
    return mod.main(argv)


@when(parsers.parse('я запускаю CLI с --course-name "{name}" --course-topic "{topic}"'))
def when_cli_basic(context, name, topic):
    context["rc"] = _run_cli([
        "--source", context["src"],
        "--out", context["out"],
        "--course-name", name,
        "--course-topic", topic,
    ])


@when(parsers.parse(
    'я запускаю CLI с --course-name "{name}" --course-topic "{topic}" без --overwrite'
))
def when_cli_no_overwrite(context, name, topic):
    context["rc"] = _run_cli([
        "--source", context["src"],
        "--out", context["out"],
        "--course-name", name,
        "--course-topic", topic,
    ])


@when(parsers.parse(
    'я запускаю CLI с --course-name "{name}" --course-topic "{topic}" и --overwrite'
))
def when_cli_overwrite(context, name, topic):
    context["rc"] = _run_cli([
        "--source", context["src"],
        "--out", context["out"],
        "--course-name", name,
        "--course-topic", topic,
        "--overwrite",
    ])


@when("загружаю получившийся course_config.yml через apply_from_yaml")
def when_apply_yaml(context):
    from lecture import course_config
    yml = Path(context["out"]) / "course_config.yml"
    context["cfg"] = course_config.apply_from_yaml(str(yml))


# --- Then -------------------------------------------------------------------

@then(parsers.parse("CLI завершается с кодом {rc:d}"))
def then_rc(context, rc):
    assert context["rc"] == rc, f"got {context['rc']}"


@then("в выходной папке есть скопированные .md/.txt файлы")
def then_copied(context):
    out = Path(context["out"])
    md = list(out.glob("*.md"))
    txt = list(out.glob("*.txt"))
    assert md and txt, f"md={md}, txt={txt}"


@then(parsers.parse('в выходной папке есть course_config.yml с полем {field} "{value}"'))
def then_config_field(context, field, value):
    yml = Path(context["out"]) / "course_config.yml"
    data = yaml.safe_load(yml.read_text(encoding="utf-8"))
    # Layout: {course: {name, topic, ...}, persona: {...}}
    actual = (data.get("course") or {}).get(field) or data.get(field)
    assert actual == value, f"field {field}: got {actual!r}, want {value!r}"


@then(parsers.parse('поле name равно "{value}"'))
def then_name(context, value):
    assert context["cfg"].fields["name"] == value, context["cfg"].fields


@then(parsers.parse('поле topic равно "{value}"'))
def then_topic(context, value):
    assert context["cfg"].fields["topic"] == value, context["cfg"].fields
