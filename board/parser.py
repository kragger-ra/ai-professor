"""Event-dict -> HTML fragment, fan-out by pane.

The board pane is styled as a chalkboard: white text on dark, no badges, no
coloured boxes. Items flow as prose. KaTeX renders inline ``$...$`` and
display ``$$...$$`` math.
"""
from __future__ import annotations

import html as html_mod
from typing import List, Tuple


def render(event: dict) -> List[Tuple[str, str]]:
    """Return a list of (pane, html_fragment) — pane is 'board' or 'chat'."""
    et = event.get("type")
    if et == "user_said":
        return [("chat", _bubble("user", event.get("text", "")))]
    if et == "professor_said":
        return [("chat", _bubble("prof", event.get("text", "")))]
    if et == "board_item":
        return [("board", _board_html(event))]
    if et == "session_start":
        sid = html_mod.escape(event.get("session", ""))
        course = html_mod.escape(event.get("course", ""))
        label = f"сессия {sid}" + (f", курс {course}" if course else "")
        sep = f'<div class="sep">— {label} —</div>'
        return [("board", sep), ("chat", sep)]
    if et == "session_end":
        sep = '<div class="sep">— конец сессии —</div>'
        return [("board", sep), ("chat", sep)]
    if et == "warning":
        return [("board",
                 f'<p class="warn">{html_mod.escape(event.get("text", ""))}</p>')]
    return []


# ---------------------------------------------------------------------------

def _bubble(css_class: str, text: str) -> str:
    return f'<div class="msg {css_class}">{html_mod.escape(text)}</div>'


def _board_html(event: dict) -> str:
    kind = (event.get("kind") or "").lower()
    body = event.get("body", "")

    if kind == "formula":
        # Block math — body is raw LaTeX, NOT html-escaped (KaTeX wants it raw).
        return f'<div class="formula">$${body}$$</div>'

    if kind == "code":
        return f'<pre class="code">{html_mod.escape(body)}</pre>'

    if kind == "term":
        # "name: definition" — split on the first colon. Allow inline math
        # in the definition (escape HTML special chars but leave $ for KaTeX).
        if ":" in body:
            name, defn = body.split(":", 1)
            name_h = html_mod.escape(name.strip())
            defn_h = html_mod.escape(defn.strip())
            return f'<p class="term"><strong>{name_h}</strong> — {defn_h}</p>'
        return f'<p class="term"><strong>{html_mod.escape(body.strip())}</strong></p>'

    if kind == "fact":
        return f'<p class="fact">{html_mod.escape(body)}</p>'

    if kind == "mermaid":
        # Mermaid library reads the diagram source from the element's text
        # content. We escape so user-provided Mermaid never injects HTML
        # (mermaid still receives the original text via textContent — no
        # double-escaping issue because it parses `&lt;` as the source
        # character `<`). Wrap in a chalkboard-friendly container; the
        # board's appendItem() calls mermaid.run() to render after insert.
        return f'<div class="mermaid">{html_mod.escape(body)}</div>'

    # unknown / malformed kind — surface without crashing
    return f'<p class="warn">{html_mod.escape(body)}</p>'
