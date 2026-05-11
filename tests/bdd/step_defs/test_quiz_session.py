"""Step definitions for quiz_session.feature."""

from pathlib import Path

from pytest_bdd import given, parsers, scenarios, then, when

FEATURE = str(Path(__file__).resolve().parents[1] / "features" / "quiz_session.feature")
scenarios(FEATURE)


# --- Given ------------------------------------------------------------------

@given(parsers.parse('доставленные блоки лекции:'))
def given_blocks(context, datatable):
    headers = datatable[0]
    blocks = []
    for row in datatable[1:]:
        d = dict(zip(headers, row))
        blocks.append({
            "id": int(d["id"]),
            "key_points": [p.strip() for p in d["key_points"].split(";")],
        })
    context["blocks"] = blocks


@given("LLM временно недоступен (для проверки fallback-веток)")
def given_llm_unavailable(context, monkeypatch):
    from lecture import quiz_loop as ql

    def fail(*_a, **_kw):
        raise RuntimeError("LLM disabled for this scenario")
    monkeypatch.setattr(ql, "_smart_call", fail)


@given(parsers.parse("новая сессия теста на {n:d} вопроса"))
def given_new_session(context, n):
    from lecture.quiz_loop import QuizSession
    context["session"] = QuizSession(context["blocks"], topic="Тест")
    context["n"] = n


@given("сессия с готовым fallback-набором вопросов")
def given_session_with_fallback(context):
    from lecture.quiz_loop import QuizSession
    s = QuizSession(context["blocks"], topic="Тест")
    s.questions = s._fallback_questions(3)
    context["session"] = s


# --- When -------------------------------------------------------------------

@when("сессия пробует сгенерировать вопросы")
def when_generate(context):
    s = context["session"]
    s.generate_questions(n=context["n"])


@when(parsers.parse('студент отвечает на вопрос {idx:d} "{reply}"'))
def when_answer(context, idx, reply):
    s = context["session"]
    s.grade_answer(idx, reply)


@when(parsers.parse("блок {bid:d} помечен как resolved"))
def when_mark_resolved(context, bid):
    context["session"].mark_block_resolved(bid)


@when("сессия инкрементирует iteration")
def when_bump_iteration(context):
    context["session"].bump_iteration()


@when(parsers.parse("сессия инкрементирует iteration {n:d} раза"))
@when(parsers.parse("сессия инкрементирует iteration {n:d} раз"))
def when_bump_iteration_n(context, n):
    for _ in range(n):
        context["session"].bump_iteration()


# --- Then -------------------------------------------------------------------

@then(parsers.parse("сгенерировано ровно {n:d} вопроса"))
@then(parsers.parse("сгенерировано ровно {n:d} вопросов"))
def then_count(context, n):
    assert len(context["session"].questions) == n, context["session"].questions


@then("каждый вопрос ссылается на источник-блок")
def then_each_has_source(context):
    for q in context["session"].questions:
        assert q.get("source_block_id") is not None, q


@then(parsers.parse("оценка ответа равна {grade:d}"))
def then_grade(context, grade):
    last = context["session"].answers[-1]
    assert last["grade"] == grade, last


@then("слабые блоки остаются пусты")
def then_no_weak(context):
    assert context["session"].weak_blocks == {}, context["session"].weak_blocks


@then(parsers.parse("слабый блок {bid:d} имеет {n:d} ошибку"))
@then(parsers.parse("слабый блок {bid:d} имеет {n:d} ошибки"))
def then_weak_count(context, bid, n):
    assert context["session"].weak_blocks.get(bid) == n, context["session"].weak_blocks


@then(parsers.parse("самый слабый блок имеет id {bid:d}"))
def then_pick_weakest(context, bid):
    assert context["session"].pick_weakest_block() == bid


@then("is_done возвращает True")
def then_is_done_true(context):
    assert context["session"].is_done() is True, (
        f"weak_blocks={context['session'].weak_blocks}, "
        f"iteration={context['session'].iteration}"
    )
