"""Step definitions for course_config_lecture.feature."""

from pathlib import Path

from pytest_bdd import given, parsers, scenarios, then, when

FEATURE = str(Path(__file__).resolve().parents[1] / "features" / "course_config_lecture.feature")
scenarios(FEATURE)


def _write_yaml(tmp: Path, fields: dict) -> Path:
    import yaml
    p = tmp / "course_config.yml"
    p.write_text(yaml.safe_dump({"course": fields}, allow_unicode=True), encoding="utf-8")
    return p


@given("чистый рабочий каталог без current_course.json")
def given_clean_cwd(tmp_cwd):
    assert not (tmp_cwd / "data" / "current_course.json").exists()


@given(parsers.parse('YAML-файл с полем name "{name}"'))
def given_yaml(context, tmp_cwd, name):
    context["yaml"] = _write_yaml(tmp_cwd, {"name": name})


@when("я вызываю get_current")
def when_get_current(context):
    from lecture import course_config
    context["cfg"] = course_config.get_current()


@when("я вызываю apply_from_yaml")
def when_apply(context):
    from lecture import course_config
    context["cfg"] = course_config.apply_from_yaml(str(context["yaml"]))


@when(parsers.parse('я рендерю шаблон "{template}"'))
def when_render(context, template):
    from lecture import course_config
    context["rendered"] = course_config.get_current().render(template)


@then(parsers.parse('поле name равно "{value}"'))
def then_name(context, value):
    assert context["cfg"].fields["name"] == value, context["cfg"].fields


@then(parsers.parse('поле topic равно "{value}"'))
def then_topic(context, value):
    assert context["cfg"].fields["topic"] == value


@then(parsers.parse('поле short_name равно "{value}"'))
def then_short_name(context, value):
    assert context["cfg"].fields["short_name"] == value


@then(parsers.parse('поле name не равно "{value}"'))
def then_name_not(context, value):
    assert context["cfg"].fields["name"] != value


@then(parsers.parse('результат равен "{value}"'))
def then_rendered_equals(context, value):
    assert context["rendered"] == value, f"got: {context['rendered']!r}"
