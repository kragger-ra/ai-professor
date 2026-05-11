"""Step definitions for voice_commands.feature."""

from pathlib import Path
from types import SimpleNamespace

from pytest_bdd import given, parsers, scenarios, then, when

FEATURE = str(Path(__file__).resolve().parents[1] / "features" / "voice_commands.feature")
scenarios(FEATURE)


# --- Helpers / stubs --------------------------------------------------------

def _patterns():
    """Lazy-import CoreAgent only for its class-level regex attributes."""
    from agent.core_agent import CoreAgent
    return CoreAgent


def _make_fake_agent(*, current_student=None, profile=None):
    """Return a SimpleNamespace shaped enough for _handle_profile_query."""
    spoken = []
    history = []

    fake = SimpleNamespace(
        _lecture_phase="idle",
        _current_student=current_student,
        _profile_mgr=_FakeProfileMgr(profile),
        _send_to_tts=lambda phrase: spoken.append(phrase),
        _save_to_history=lambda phrase: history.append(phrase),
        _TOPIC_LEVEL_LABELS={
            1: "начинающий", 2: "базовый", 3: "средний",
            4: "продвинутый", 5: "эксперт",
        },
        _WEAK_TOPIC_LEVEL_MAX=2,
        _PROFILE_QUERY_RE=_patterns()._PROFILE_QUERY_RE,
    )
    fake.spoken = spoken
    fake.history = history
    return fake


class _FakeProfileMgr:
    def __init__(self, profile):
        self.profile = profile

    def get_or_create_student(self, name):
        return self.profile


# --- Given ------------------------------------------------------------------

@given("агент без current_student")
def given_no_student(context):
    context["agent"] = _make_fake_agent(current_student=None, profile=None)


@given(parsers.parse('агент с current_student "{name}" и одной интеракцией в БД'))
def given_student_one_interaction(context, name):
    profile = {
        "total_interactions": 1, "known_issues": "[]", "topic_levels": "{}",
        "tech_level": 3, "topics_of_interest": "[]",
    }
    context["agent"] = _make_fake_agent(current_student=name, profile=profile)


@given(parsers.parse(
    'агент с current_student "{name}", {n:d} интеракций, '
    'known_issues {issues}, topic_levels {levels}'
))
def given_student_with_data(context, name, n, issues, levels):
    profile = {
        "total_interactions": n,
        "known_issues": issues,
        "topic_levels": levels,
        "tech_level": 3,
        "topics_of_interest": "[]",
    }
    context["agent"] = _make_fake_agent(current_student=name, profile=profile)


@given(parsers.parse(
    'агент с current_student "{name}", {n:d} интеракций, '
    'без known_issues и слабых тем'
))
def given_student_clean(context, name, n):
    profile = {
        "total_interactions": n,
        "known_issues": "[]",
        "topic_levels": "{}",
        "tech_level": 3,
        "topics_of_interest": "[]",
    }
    context["agent"] = _make_fake_agent(current_student=name, profile=profile)


# --- When -------------------------------------------------------------------

@when(parsers.parse('я разбираю фразу "{msg}"'))
def when_parse(context, msg):
    pats = _patterns()
    result = {"command": None}
    m = pats._LOAD_SUBJECT_RE.search(msg.strip())
    if m:
        result.update({
            "command": "load_subject",
            "name": m.group("name").strip().rstrip(".!?,"),
            "path": m.group("path").strip().rstrip(".!?,"),
            "mode": "append" if m.group("verb").lower() == "добавь" else "replace",
        })
        context["parsed"] = result
        return
    m = pats._TOPIC_LECTURE_RE.search(msg.strip())
    if m:
        result.update({
            "command": "topic_lecture",
            "topic": m.group("topic").strip().rstrip(".!?,"),
        })
        context["parsed"] = result
        return
    if pats._PROFILE_QUERY_RE.search(msg.strip()):
        result["command"] = "profile_query"
    context["parsed"] = result


@when(parsers.parse('я проверяю фразу "{msg}" на end-lecture'))
def when_check_end(context, msg):
    pats = _patterns()
    norm = msg.strip().lower().rstrip(".!?,")
    context["end_hit"] = any(p in norm for p in pats._END_LECTURE_PHRASES)


@when(parsers.parse('агент обрабатывает фразу "{msg}"'))
def when_agent_processes(context, msg):
    from agent.core_agent import CoreAgent
    # Bind unbound method to the fake namespace.
    CoreAgent._handle_profile_query(context["agent"], msg)


# --- Then -------------------------------------------------------------------

@then(parsers.parse('команда распознана как {cmd}'))
def then_command(context, cmd):
    assert context["parsed"]["command"] == cmd, context["parsed"]


@then(parsers.parse('поле name равно "{value}"'))
def then_name(context, value):
    assert context["parsed"]["name"] == value, context["parsed"]


@then(parsers.parse('поле path равно "{value}"'))
def then_path(context, value):
    assert context["parsed"]["path"] == value, context["parsed"]


@then(parsers.parse('режим равен "{value}"'))
def then_mode(context, value):
    assert context["parsed"]["mode"] == value, context["parsed"]


@then(parsers.parse('тема равна "{value}"'))
def then_topic(context, value):
    assert context["parsed"]["topic"] == value, context["parsed"]


@then(parsers.parse('фраза {marker} распознаётся как завершение'))
def then_end_match(context, marker):
    expected = (marker.strip() == "должна")
    assert context["end_hit"] is expected, f"end_hit={context['end_hit']}, expected={expected}"


@then("озвучивается фраза с приглашением назвать имя")
def then_phrase_invite_name(context):
    spoken = " ".join(context["agent"].spoken).lower()
    assert "имя" in spoken or "назови" in spoken, context["agent"].spoken


@then("озвучивается фраза про недостаточно данных")
def then_phrase_insufficient(context):
    spoken = " ".join(context["agent"].spoken).lower()
    assert "недостаточно" in spoken or "данных" in spoken, context["agent"].spoken


@then(parsers.parse('озвучивается фраза с упоминанием "{token}"'))
def then_phrase_mentions(context, token):
    spoken = " ".join(context["agent"].spoken)
    assert token in spoken, f"missing {token!r} in {context['agent'].spoken}"


@then("не озвучивается communication_style")
def then_no_style(context):
    spoken = " ".join(context["agent"].spoken).lower()
    forbidden = ["communication", "style", "стиль общения", "манера речи"]
    for f in forbidden:
        assert f not in spoken, f"leaked: {f!r} in {context['agent'].spoken}"
