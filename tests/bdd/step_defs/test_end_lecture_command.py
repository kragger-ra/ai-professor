"""Step definitions for end_lecture_command.feature."""

from pathlib import Path

from pytest_bdd import parsers, scenarios, then, when

FEATURE = str(Path(__file__).resolve().parents[1] / "features" / "end_lecture_command.feature")
scenarios(FEATURE)


def _phrases():
    from agent.core_agent import CoreAgent
    return CoreAgent._END_LECTURE_PHRASES


@when(parsers.parse('я проверяю фразу "{msg}" на end-lecture'))
def when_check(context, msg):
    norm = msg.strip().lower().rstrip(".!?,")
    context["end_hit"] = any(p in norm for p in _phrases())


@when("я читаю константу LECTURE_FAREWELL_PHRASE")
def when_read_farewell(context):
    from agent.core_agent import LECTURE_FAREWELL_PHRASE
    context["farewell"] = LECTURE_FAREWELL_PHRASE


@then(parsers.parse('фраза {marker} распознаётся как завершение'))
def then_end(context, marker):
    expected = (marker.strip() == "должна")
    assert context["end_hit"] is expected


@then("фраза не распознаётся как завершение")
def then_not_end(context):
    assert context["end_hit"] is False


@then(parsers.parse('фраза начинается с "{prefix}"'))
def then_starts(context, prefix):
    assert context["farewell"].startswith(prefix), context["farewell"]


@then(parsers.parse('фраза содержит "{substr}"'))
def then_contains(context, substr):
    assert substr in context["farewell"], context["farewell"]
