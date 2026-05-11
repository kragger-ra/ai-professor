"""Step definitions for course_config.feature."""

from pathlib import Path

from pytest_bdd import given, parsers, scenarios, then, when

FEATURE = str(Path(__file__).resolve().parents[1] / "features" / "course_config.feature")
scenarios(FEATURE)


# --- helpers ----------------------------------------------------------------

def _write_yaml(tmp: Path, fields: dict) -> Path:
    import yaml
    p = tmp / "course_config.yml"
    p.write_text(yaml.safe_dump({"course": fields}, allow_unicode=True), encoding="utf-8")
    return p


# --- Given ------------------------------------------------------------------

@given(parsers.parse('YAML-файл course_config.yml со следующими полями:'))
def given_yaml_table(context, tmp_cwd, datatable):
    # pytest-bdd 8.x datatable: list[list[str]], first row = headers
    headers = datatable[0]
    fields = {}
    for row in datatable[1:]:
        d = dict(zip(headers, row))
        fields[d["поле"]] = d["значение"]
    context["yaml"] = _write_yaml(tmp_cwd, fields)
    context["fields"] = fields


@given('YAML-файл с полем name "Физика"')
def given_yaml_physics(context, tmp_cwd):
    context["yaml"] = _write_yaml(tmp_cwd, {"name": "Физика"})


@given("чистый рабочий каталог без current_course.json")
def given_clean_cwd(tmp_cwd):
    assert not (tmp_cwd / "data" / "current_course.json").exists()


@given(parsers.parse('загруженный курс "{name}"'))
def given_loaded_course(context, tmp_cwd, name):
    from lecture import course_config
    cfg = course_config.CourseConfig(name=name)
    course_config.set_current(cfg)


# --- When -------------------------------------------------------------------

@when("я вызываю apply_from_yaml для этого файла")
@when("я вызываю apply_from_yaml")
def when_apply_yaml(context):
    from lecture import course_config
    context["cfg"] = course_config.apply_from_yaml(str(context["yaml"]))


@when("я вызываю get_current")
def when_get_current(context):
    from lecture import course_config
    context["cfg"] = course_config.get_current()


@when("затем я создаю новую сессию чтения через get_current")
def when_new_session_get_current(context):
    from lecture import course_config
    course_config._cached_cfg = None  # simulate cross-process read
    course_config._cached_at = 0.0
    context["cfg"] = course_config.get_current()


@when(parsers.parse('я рендерю шаблон "{template}"'))
def when_render(context, template):
    from lecture import course_config
    context["rendered"] = course_config.get_current().render(template)


# --- Then -------------------------------------------------------------------

@then(parsers.parse('поле name становится равно "{value}"'))
@then(parsers.parse('поле name равно "{value}"'))
@then(parsers.parse('поле name по-прежнему равно "{value}"'))
def then_name(context, value):
    assert context["cfg"].fields["name"] == value, context["cfg"].fields


@then(parsers.parse('поле topic становится равно "{value}"'))
@then(parsers.parse('поле topic равно "{value}"'))
def then_topic(context, value):
    assert context["cfg"].fields["topic"] == value, context["cfg"].fields


@then(parsers.parse('render шаблона "{template}" выдаёт "{expected}"'))
def then_render_output(context, template, expected):
    out = context["cfg"].render(template)
    assert out == expected, f"got: {out!r}"


@then(parsers.parse('результат содержит "{substr}"'))
def then_result_contains(context, substr):
    assert substr in context["rendered"], f"missing {substr!r} in {context['rendered']!r}"


@then(parsers.parse('результат всё ещё содержит "{substr}"'))
def then_result_still_contains(context, substr):
    assert substr in context["rendered"], f"placeholder stripped: {context['rendered']!r}"
