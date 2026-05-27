"""Read an exported session back into board events.

Mirror of ``board.export``. Supported formats: HTML and Markdown. PDF is
intentionally not supported — exported PDFs are rasterised / flattened
output, not a structured carrier.

The parsed events are lightweight dicts with the same ``type`` keys the
rest of the board expects (``user_said``, ``professor_said``,
``board_item`` with kinds term/formula/fact/code/mermaid, plus
``session_start`` / ``session_end``). They land in
``MainWindow._dispatch`` and replay onto the live panes.
"""
from __future__ import annotations

import html as html_mod
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import List


_SEQ = 0


def _next_seq() -> int:
    global _SEQ
    _SEQ += 1
    return _SEQ


def _reset_seq() -> None:
    global _SEQ
    _SEQ = 0


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------

def parse_markdown(path: Path) -> List[dict]:
    """Parse a session exported via ``export_md_*``. Supports the three
    layouts the exporter writes (board-only, chat-only, combined)."""
    _reset_seq()
    text = path.read_text(encoding="utf-8", errors="replace")
    events: List[dict] = []
    # Detect section roles. The exporter writes either '# Доска',
    # '# Диалог' or both. Default to "board" if no header is found.
    sections = _split_md_sections(text)
    ref_seq_counter = 0
    saw_session_start = False
    for header, body in sections:
        role = "chat" if "диалог" in header.lower() else "board"
        if role == "chat":
            events.extend(_parse_md_chat(body))
        else:
            evs = _parse_md_board(body, ref_seq_counter)
            events.extend(evs)
            # Bump ref_seq for each topic separator we saw, so the live UI
            # renders a fresh separator between distinct answers on replay.
            ref_seq_counter += sum(1 for e in evs
                                   if e.get("type") == "board_item")
    # Ensure there's a session_start so the UI renders a header line.
    if not any(e.get("type") == "session_start" for e in events):
        events.insert(0, {"type": "session_start",
                          "seq": _next_seq(),
                          "session": path.stem,
                          "course": ""})
    return events


_MD_HEADER_RE = re.compile(r"^# (.+)$", re.MULTILINE)


def _split_md_sections(text: str) -> List[tuple[str, str]]:
    matches = list(_MD_HEADER_RE.finditer(text))
    if not matches:
        return [("", text)]
    out = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        out.append((m.group(1).strip(),
                    text[m.end():end].strip()))
    return out


_MD_SESSION_LABEL_RE = re.compile(r"^— сессия ([^,—]+)(?:, курс ([^—]+))?\s*—\s*$")
_MD_USER_RE = re.compile(r"^\*\*Студент:\*\*\s*(.+)$", re.DOTALL)
_MD_PROF_RE = re.compile(r"^\*\*Профессор:\*\*\s*(.+)$", re.DOTALL)
_MD_TERM_RE = re.compile(r"^\*\*([^*]+)\*\*\s*(?:—\s*(.+))?$", re.DOTALL)
_MD_FORMULA_RE = re.compile(r"^\$\$([\s\S]+)\$\$$")


def _md_paragraphs(text: str) -> List[str]:
    """Split a markdown block into paragraphs / fenced blocks. Fenced
    code blocks (``` ... ```) are kept as single chunks even if they
    contain blank lines inside."""
    paras: List[str] = []
    buf: List[str] = []
    in_fence = False
    fence_lang = ""

    def _flush():
        if buf:
            paras.append("\n".join(buf).strip("\n"))
            buf.clear()

    for line in text.splitlines():
        stripped = line.strip()
        if not in_fence and stripped.startswith("```"):
            _flush()
            in_fence = True
            fence_lang = stripped[3:].strip()
            buf.append(line)
            continue
        if in_fence and stripped.startswith("```"):
            buf.append(line)
            paras.append("\n".join(buf))
            buf.clear()
            in_fence = False
            fence_lang = ""
            continue
        if in_fence:
            buf.append(line)
            continue
        if not stripped:
            _flush()
        else:
            buf.append(line)
    _flush()
    return [p for p in paras if p.strip()]


def _parse_md_chat(body: str) -> List[dict]:
    out: List[dict] = []
    for para in _md_paragraphs(body):
        first = para.lstrip()
        m = _MD_SESSION_LABEL_RE.match(first.splitlines()[0]) if first else None
        if m:
            out.append({"type": "session_start", "seq": _next_seq(),
                        "session": m.group(1).strip(),
                        "course": (m.group(2) or "").strip()})
            continue
        m = _MD_USER_RE.match(para.strip())
        if m:
            out.append({"type": "user_said", "seq": _next_seq(),
                        "text": m.group(1).strip()})
            continue
        m = _MD_PROF_RE.match(para.strip())
        if m:
            out.append({"type": "professor_said", "seq": _next_seq(),
                        "text": m.group(1).strip()})
            continue
    return out


def _parse_md_board(body: str, ref_seq_start: int) -> List[dict]:
    out: List[dict] = []
    ref_seq = ref_seq_start
    saw_first = False
    for para in _md_paragraphs(body):
        line = para.strip()

        if _MD_SESSION_LABEL_RE.match(line.splitlines()[0] if line else ""):
            m = _MD_SESSION_LABEL_RE.match(line.splitlines()[0])
            out.append({"type": "session_start", "seq": _next_seq(),
                        "session": m.group(1).strip(),
                        "course": (m.group(2) or "").strip()})
            continue

        if line == "---":
            ref_seq += 1
            continue

        # Fenced block — mermaid or code.
        if line.startswith("```"):
            first_nl = line.find("\n")
            if first_nl < 0:
                continue
            head = line[3:first_nl].strip().lower()
            body_text = line[first_nl + 1:]
            if body_text.endswith("\n```"):
                body_text = body_text[:-4]
            elif body_text.endswith("```"):
                body_text = body_text[:-3]
            kind = "mermaid" if head == "mermaid" else "code"
            out.append({"type": "board_item", "seq": _next_seq(),
                        "kind": kind, "body": body_text.rstrip(),
                        "ref_seq": ref_seq, "caption": ""})
            saw_first = True
            continue

        # Display math.
        m = _MD_FORMULA_RE.match(line)
        if m:
            out.append({"type": "board_item", "seq": _next_seq(),
                        "kind": "formula", "body": m.group(1).strip(),
                        "ref_seq": ref_seq, "caption": ""})
            saw_first = True
            continue

        # Term: **Name** — definition  or **Name**
        m = _MD_TERM_RE.match(line)
        if m and "\n" not in line:
            name = m.group(1).strip()
            defn = (m.group(2) or "").strip()
            body_str = (name + ": " + defn) if defn else name
            out.append({"type": "board_item", "seq": _next_seq(),
                        "kind": "term", "body": body_str,
                        "ref_seq": ref_seq, "caption": ""})
            saw_first = True
            continue

        # Fallback — treat as fact.
        out.append({"type": "board_item", "seq": _next_seq(),
                    "kind": "fact", "body": line,
                    "ref_seq": ref_seq, "caption": ""})
        saw_first = True
    return out


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

class _BoardChatHTMLParser(HTMLParser):
    """Pulls structured chat bubbles and board items from our exported HTML.

    The exporter writes consistent classes (msg.user, msg.prof, term, fact,
    formula, code, mermaid, hr.topic-sep) — we key on those, ignoring page
    chrome (style, script, h1).
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.events: List[dict] = []
        self._stack: list[tuple[str, dict]] = []
        self._buf: list[str] = []
        self._cur_pane: str = ""   # "board" | "chat"
        self._ref_seq = 0
        self._skip_depth = 0
        self._capture_pane_from = None

    def _classes(self, attrs):
        for k, v in attrs:
            if k == "class":
                return (v or "").split()
        return []

    def handle_starttag(self, tag, attrs):
        if self._skip_depth:
            self._skip_depth += 1
            return
        if tag in ("style", "script"):
            self._skip_depth = 1
            return
        classes = self._classes(attrs)
        # Pane detection on <section> blocks of the combined export.
        if tag == "section":
            self._cur_pane = ""
            return
        if tag == "h1":
            self._buf = []
            self._stack.append(("h1", {}))
            return
        # hr separator on the board pane → bump ref_seq counter.
        if tag == "hr" and "topic-sep" in classes:
            self._ref_seq += 1
            return
        # Chat bubbles.
        if "msg" in classes and ("user" in classes or "prof" in classes):
            role = "user_said" if "user" in classes else "professor_said"
            self._buf = []
            self._stack.append((role, {}))
            self._cur_pane = "chat"
            return
        # Board items.
        for k in ("term", "fact", "formula", "code", "mermaid"):
            if k in classes:
                self._buf = []
                self._stack.append((f"board:{k}", {}))
                self._cur_pane = "board"
                return

    def handle_endtag(self, tag):
        if self._skip_depth:
            self._skip_depth -= 1
            return
        if not self._stack:
            return
        top_tag, _ctx = self._stack[-1]
        if top_tag == "h1" and tag == "h1":
            label = "".join(self._buf).strip().lower()
            # 'диалог' → chat pane, 'доска' → board pane
            if "диалог" in label:
                self._cur_pane = "chat"
            elif "доск" in label:
                self._cur_pane = "board"
            self._buf = []
            self._stack.pop()
            return
        # Bubbles / items close on </div> or </p>.
        if tag in ("div", "p", "pre"):
            text = "".join(self._buf).strip()
            if top_tag in ("user_said", "professor_said"):
                if text:
                    self.events.append({"type": top_tag,
                                        "seq": _next_seq(),
                                        "text": text})
            elif top_tag.startswith("board:"):
                kind = top_tag.split(":", 1)[1]
                if text:
                    body = _normalise_board_body(kind, text)
                    self.events.append({
                        "type": "board_item",
                        "seq": _next_seq(),
                        "kind": kind,
                        "body": body,
                        "ref_seq": self._ref_seq,
                        "caption": "",
                    })
            self._buf = []
            self._stack.pop()

    def handle_data(self, data):
        if self._skip_depth:
            return
        if self._stack:
            self._buf.append(data)


_FORMULA_WRAP_RE = re.compile(r"^\s*\$\$([\s\S]+?)\$\$\s*$")
_TERM_EMDASH_RE = re.compile(r"^([^\s][^—:]*?)\s+—\s+(.+)$", re.DOTALL)


def _normalise_board_body(kind: str, text: str) -> str:
    """HTML round-trip dropped the term ':' separator (replaced by em-dash
    at render time) and wrapped formula in $$ for KaTeX. Reverse both so
    the live UI's parser splits them again the way it expects."""
    if kind == "formula":
        m = _FORMULA_WRAP_RE.match(text)
        return m.group(1).strip() if m else text
    if kind == "term":
        m = _TERM_EMDASH_RE.match(text)
        if m and ":" not in m.group(1):
            return f"{m.group(1).strip()}: {m.group(2).strip()}"
    return text


def parse_html(path: Path) -> List[dict]:
    """Parse an HTML file produced by ``export_html_*`` back into events."""
    _reset_seq()
    raw = path.read_text(encoding="utf-8", errors="replace")
    parser = _BoardChatHTMLParser()
    try:
        parser.feed(raw)
    finally:
        parser.close()
    events = parser.events
    if not any(e.get("type") == "session_start" for e in events):
        events.insert(0, {"type": "session_start",
                          "seq": _next_seq(),
                          "session": path.stem,
                          "course": ""})
    return events
