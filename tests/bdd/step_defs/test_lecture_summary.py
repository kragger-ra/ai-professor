"""Step definitions for lecture_summary.feature."""

from pathlib import Path

from pytest_bdd import given, parsers, scenarios, then, when

FEATURE = str(Path(__file__).resolve().parents[1] / "features" / "lecture_summary.feature")
scenarios(FEATURE)


# --- Given ------------------------------------------------------------------

@given(parsers.parse('подготовленная лекция "{topic}" с {n:d} блоками'))
def given_lecture(context, topic, n):
    from lecture.lecture_delivery import LectureDelivery
    blocks = []
    for i in range(1, n + 1):
        blocks.append({
            "id": i,
            "type": "concept",
            "key_points": [f"Тезис блока {i}, пункт A", f"Тезис блока {i}, пункт B"],
        })
    delivery = LectureDelivery({"topic": topic, "blocks": blocks})
    delivery.blocks_delivered = blocks  # simulate that all were delivered
    context["delivery"] = delivery
    context["topic"] = topic


@given("снимок ctx_chat с сообщениями для каждого блока")
def given_ctx_chat(context):
    blocks = context["delivery"].blocks_delivered
    ctx = []
    for i, _ in enumerate(blocks, 1):
        ctx.append({"self": True, "msg": f"Реальный текст блока {i}."})
    context["ctx_chat"] = ctx


@given(parsers.parse('список из {n:d} проверочных вопросов'))
def given_quiz(context, n):
    context["quiz"] = [
        "Что такое матрица?",
        "Чем отличается вектор от скаляра?",
    ][:n]


@given(parsers.parse('в ctx_chat есть запись с префиксом "{prefix}"'))
def given_ctx_chat_with_qa(context, prefix):
    context["ctx_chat"].append({
        "self": True,
        "msg": f"{prefix} A как с B?] Ответ профессора на этот вопрос.",
    })


@given("LLM возвращает заглушку для condense")
def given_llm_stub(context, monkeypatch):
    from lecture import lecture_delivery as ld
    monkeypatch.setattr(ld, "_condense_blocks", lambda _x: {})


@given("LLM возвращает condensed-результат для всех блоков")
def given_llm_condensed(context, monkeypatch):
    from lecture import lecture_delivery as ld
    fake = {b["id"]: f"Условный конспект блока {b['id']}."
            for b in context["delivery"].blocks_delivered}
    monkeypatch.setattr(ld, "_condense_blocks", lambda _x: fake)


@given("LLM падает при вызове condense")
def given_llm_crash(context, monkeypatch):
    from lecture import lecture_delivery as ld

    def boom(_x):
        return {}  # function itself catches and returns {} on failure
    monkeypatch.setattr(ld, "_condense_blocks", boom)


# --- When -------------------------------------------------------------------

@when("я вызываю export_lecture_summary")
def when_export(context, tmp_cwd):
    from lecture.lecture_delivery import export_lecture_summary
    out_dir = tmp_cwd / "lecture_summaries"
    path = export_lecture_summary(
        context["delivery"],
        context["ctx_chat"],
        context["quiz"],
        str(out_dir),
    )
    context["path"] = path
    context["body"] = Path(path).read_text(encoding="utf-8")


# --- Then -------------------------------------------------------------------

@then("возвращённый путь существует на диске")
def then_path_exists(context):
    assert Path(context["path"]).exists(), context["path"]


@then(parsers.parse('имя файла содержит "{substr}"'))
def then_filename_contains(context, substr):
    assert substr in Path(context["path"]).name, Path(context["path"]).name


@then(parsers.parse('имя файла начинается на "{prefix}"'))
def then_filename_starts(context, prefix):
    assert Path(context["path"]).name.startswith(prefix), Path(context["path"]).name


@then(parsers.parse('расширение файла "{ext}"'))
def then_filename_ext(context, ext):
    assert Path(context["path"]).suffix == ext, Path(context["path"]).suffix


@then(parsers.parse('содержимое файла содержит "{substr}"'))
def then_body_contains(context, substr):
    assert substr in context["body"], f"missing {substr!r} in summary"


@then(parsers.parse('содержимое файла не содержит "{substr}"'))
def then_body_not_contains(context, substr):
    assert substr not in context["body"], f"unexpected {substr!r} in summary"
