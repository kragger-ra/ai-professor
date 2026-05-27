"""Export board and chat panes to PDF, self-contained HTML, and Markdown.

PDF goes through Qt (``QWebEnginePage.printToPdf``) and needs an
instantiated view to print from. For combined exports (board+chat in one
file) a hidden view loads a temporary HTML document and prints it. HTML
and Markdown exports are pure replays of the JSONL through
``board.parser.render``; they work even when called from the CLI on a
yesterday's session.

Exported HTML is self-contained: KaTeX CSS/JS are inlined from the
vendored ``board/assets/katex/`` directory, so the file renders formulas
without internet access. Font files (``.woff2``) are NOT inlined; the
HTML keeps relative ``katex/fonts/...`` URLs and the exporter copies the
katex/ directory next to the output file when needed.

Markdown export is plain prose — no KaTeX wrappers, no HTML, just the
structure (term-name + definition, formula block in $$...$$, mermaid
fenced code, etc.) so it round-trips through any reader.
"""
from __future__ import annotations

import html as html_mod
import json
import re
import shutil
from pathlib import Path
from typing import Iterable, List

from board import parser as event_parser

_ASSETS = Path(__file__).resolve().parent / "assets"
_KATEX_DIR = _ASSETS / "katex"


# ---------------------------------------------------------------------------
# PDF — via Qt WebEngine. Caller is responsible for ensuring the view has
# finished loading and rendering before calling.
# ---------------------------------------------------------------------------

def export_pdf(view, out_path: Path, on_done=None) -> None:
    """Schedule a PDF write of the given QWebEngineView.

    ``printToPdf`` is asynchronous — the file is not on disk when this
    returns. Pass ``on_done`` as a callback(path, ok) for completion.
    """
    from PySide6.QtCore import QMarginsF
    from PySide6.QtGui import QPageLayout, QPageSize

    layout = QPageLayout(
        QPageSize(QPageSize.A4),
        QPageLayout.Portrait,
        QMarginsF(10, 10, 10, 10),
    )
    page = view.page()
    if on_done is not None:
        def _slot(path: str, ok: bool):
            try:
                page.pdfPrintingFinished.disconnect(_slot)
            except (TypeError, RuntimeError):
                pass
            on_done(Path(path), bool(ok))
        page.pdfPrintingFinished.connect(_slot)
    page.printToPdf(str(out_path), layout)


# ---------------------------------------------------------------------------
# HTML — pure JSONL replay. CSS inlined; KaTeX CSS+JS inlined from vendored
# assets so the file works fully offline (fonts loaded via relative URL).
# ---------------------------------------------------------------------------

_BOARD_CSS = """
  html, body { height:100%; }
  body { background:#0d1110; color:#ebebeb;
    font-family:-apple-system,"Segoe UI",Roboto,sans-serif;
    margin:0; padding:32px 44px; font-size:22px; line-height:1.6; }
  h1 { color:#888; font-size:11px; text-transform:uppercase;
    letter-spacing:2px; margin:0 0 24px; font-weight:500; }
  .term  { margin:16px 0; }
  .term strong { color:#fff; font-weight:700; letter-spacing:.3px; }
  .fact  { margin:16px 0; }
  .formula { margin:22px 0; text-align:left; overflow-x:auto; }
  .warn  { margin:14px 0; color:#d4c266; font-style:italic; }
  .code  { background:transparent; color:#ebebeb; margin:14px 0; padding:0;
    font-family:Consolas,"Cascadia Code",monospace; font-size:14px;
    white-space:pre; overflow-x:auto; }
  .sep { color:#5a5a5a; text-align:center; font-size:11px;
    margin:34px 0 22px; border-top:1px dashed #2a3a2a; padding-top:8px;
    letter-spacing:1px; }
  hr.topic-sep { border:0; height:0; border-top:1px dashed #3a4a3a;
    margin:36px auto 28px; width:80%; }
  .katex, .katex * { color:#ebebeb !important; }
  .katex { font-size:1.18em; }
  .formula .katex-display { margin:.4em 0; text-align:left; }
"""

_CHAT_CSS = """
  html, body { height:100%; }
  body { background:#0e0e0e; color:#d6d6d6;
    font-family:-apple-system,"Segoe UI",Roboto,sans-serif;
    margin:0; padding:18px; font-size:17px; line-height:1.55;
    max-width:760px; margin-left:auto; margin-right:auto; }
  h1 { color:#777; font-size:11px; text-transform:uppercase;
    letter-spacing:1.4px; margin:0 0 12px; font-weight:500; }
  #chat { display:flex; flex-direction:column; gap:6px; }
  .msg { padding:8px 12px; border-radius:14px; width:fit-content;
    max-width:min(440px, 90%); word-wrap:break-word; overflow-wrap:break-word;
    white-space:pre-wrap; box-sizing:border-box; }
  .msg.user { background:#2c5282; align-self:flex-end;
    border-bottom-right-radius:4px; }
  .msg.prof { background:#232323; align-self:flex-start;
    border-bottom-left-radius:4px; }
  .sep { color:#555; text-align:center; font-size:10px;
    margin:14px 0 8px; border-top:1px dashed #2a2a2a; padding-top:6px;
    letter-spacing:.5px; align-self:stretch; }
"""

_KATEX_RENDER_JS = """
<script>
  window.addEventListener('load', () => {
    if (window.renderMathInElement) {
      try {
        renderMathInElement(document.body, {
          delimiters: [
            { left: "$$", right: "$$", display: true },
            { left: "\\\\[", right: "\\\\]", display: true },
            { left: "$",  right: "$",  display: false },
            { left: "\\\\(", right: "\\\\)", display: false }
          ],
          throwOnError: false,
          errorColor: "#e25555"
        });
      } catch(e) {}
    }
  });
</script>
"""


def export_html_board(jsonl_path: Path, out_path: Path) -> int:
    fragments = _collect_pane(jsonl_path, "board")
    body = "\n".join(fragments) or '<div class="sep">— пусто —</div>'
    _ensure_katex_next_to(out_path)
    out_path.write_text(_render_page(
        title="AI Professor — доска",
        css=_BOARD_CSS,
        body=f'<h1>Доска</h1>\n<div id="board">{body}</div>',
        include_katex=True,
    ), encoding="utf-8")
    return len(fragments)


def export_html_chat(jsonl_path: Path, out_path: Path) -> int:
    fragments = _collect_pane(jsonl_path, "chat")
    body = "\n".join(fragments) or '<div class="sep">— пусто —</div>'
    out_path.write_text(_render_page(
        title="AI Professor — чат",
        css=_CHAT_CSS,
        body=f'<h1>Диалог</h1>\n<div id="chat">{body}</div>',
        include_katex=False,
    ), encoding="utf-8")
    return len(fragments)


def export_html_combined(jsonl_path: Path, out_path: Path) -> int:
    """Board + chat in a single HTML, two-column layout when wide enough,
    stacked on narrow viewports. Uses board's KaTeX setup so formulas render."""
    board_frags = _collect_pane(jsonl_path, "board")
    chat_frags = _collect_pane(jsonl_path, "chat")
    _ensure_katex_next_to(out_path)
    body = (
        f'<div class="cols">'
        f'<section><h1>Доска</h1><div id="board">'
        f'{chr(10).join(board_frags) or "— пусто —"}</div></section>'
        f'<section><h1>Диалог</h1><div id="chat">'
        f'{chr(10).join(chat_frags) or "— пусто —"}</div></section>'
        f'</div>'
    )
    css = _BOARD_CSS + _CHAT_CSS + """
      body { padding: 24px; }
      .cols { display:flex; gap:32px; align-items:flex-start; }
      .cols > section { flex:1; min-width:0; }
      .cols > section + section { border-left:1px solid #2a3a2a; padding-left:24px; }
      @media (max-width: 900px) { .cols { flex-direction:column; } }
    """
    out_path.write_text(_render_page(
        title="AI Professor — сессия",
        css=css, body=body, include_katex=True,
    ), encoding="utf-8")
    return len(board_frags) + len(chat_frags)


# ---------------------------------------------------------------------------
# Markdown — plain prose replay. No HTML, no inlined assets, round-trips
# through any reader. Mermaid stays as a fenced ```mermaid block, formulas
# as $$...$$ display math.
# ---------------------------------------------------------------------------

def export_md_board(jsonl_path: Path, out_path: Path) -> int:
    parts: List[str] = ["# Доска", ""]
    n = _md_board(jsonl_path, parts)
    out_path.write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")
    return n


def export_md_chat(jsonl_path: Path, out_path: Path) -> int:
    parts: List[str] = ["# Диалог", ""]
    n = _md_chat(jsonl_path, parts)
    out_path.write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")
    return n


def export_md_combined(jsonl_path: Path, out_path: Path) -> int:
    parts: List[str] = []
    parts.append("# Диалог")
    parts.append("")
    n_chat = _md_chat(jsonl_path, parts)
    parts.append("")
    parts.append("# Доска")
    parts.append("")
    n_board = _md_board(jsonl_path, parts)
    out_path.write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")
    return n_chat + n_board


def _md_chat(jsonl_path: Path, parts: List[str]) -> int:
    n = 0
    for event in _iter_events(jsonl_path):
        et = event.get("type")
        if et == "session_start":
            sid = (event.get("session") or "").strip()
            course = (event.get("course") or "").strip()
            label = f"сессия {sid}" + (f", курс {course}" if course else "")
            parts.append(f"— {label} —")
            parts.append("")
        elif et == "session_end":
            parts.append("— конец сессии —")
            parts.append("")
        elif et == "user_said":
            txt = (event.get("text") or "").strip()
            if txt:
                parts.append(f"**Студент:** {txt}")
                parts.append("")
                n += 1
        elif et == "professor_said":
            txt = (event.get("text") or "").strip()
            if txt:
                parts.append(f"**Профессор:** {txt}")
                parts.append("")
                n += 1
    return n


def _md_board(jsonl_path: Path, parts: List[str]) -> int:
    n = 0
    last_ref_seq = None
    for event in _iter_events(jsonl_path):
        et = event.get("type")
        if et == "session_start":
            sid = (event.get("session") or "").strip()
            course = (event.get("course") or "").strip()
            label = f"сессия {sid}" + (f", курс {course}" if course else "")
            parts.append(f"— {label} —")
            parts.append("")
            last_ref_seq = None
            continue
        if et != "board_item":
            continue
        ref = event.get("ref_seq")
        if last_ref_seq is not None and ref != last_ref_seq:
            parts.append("---")
            parts.append("")
        last_ref_seq = ref
        kind = (event.get("kind") or "").lower()
        body = event.get("body") or ""
        if kind == "term":
            head, _, rest = body.partition(":")
            if rest:
                parts.append(f"**{head.strip()}** — {rest.strip()}")
            else:
                parts.append(f"**{body.strip()}**")
        elif kind == "fact":
            parts.append(body.strip())
        elif kind == "formula":
            parts.append("$$" + body.strip() + "$$")
        elif kind == "code":
            parts.append("```")
            parts.append(body.rstrip())
            parts.append("```")
        elif kind == "mermaid":
            parts.append("```mermaid")
            parts.append(body.rstrip())
            parts.append("```")
        else:
            parts.append(body.strip())
        parts.append("")
        n += 1
    return n


# ---------------------------------------------------------------------------
# Combined PDF — render combined HTML in a hidden QWebEngineView, then
# printToPdf. The view is kept alive until the async pdfPrintingFinished
# callback fires, then released.
# ---------------------------------------------------------------------------

def export_pdf_combined(jsonl_path: Path, out_path: Path, on_done=None) -> None:
    """Pack board+chat into a temporary HTML and print it to PDF.

    Caller must keep a reference to the returned view (we attach the view
    to ``on_done.__self__`` via the closure) — Qt would otherwise GC it
    before printing finishes. The temp HTML is removed after the print.
    """
    from PySide6.QtCore import QUrl
    from PySide6.QtWebEngineWidgets import QWebEngineView

    tmp_html = out_path.with_suffix(".tmp.html")
    n_items = export_html_combined(jsonl_path, tmp_html)

    view = QWebEngineView()
    view.resize(1024, 1400)
    # Keep view alive by attaching to a module-level set; remove on done.
    _PDF_VIEWS.add(view)

    def _after_load(ok: bool):
        if not ok:
            _cleanup()
            if on_done is not None:
                on_done(out_path, False)
            return
        # Wait one tick for KaTeX/mermaid to settle before printing.
        from PySide6.QtCore import QTimer
        QTimer.singleShot(800, _do_print)

    def _do_print():
        export_pdf(view, out_path, on_done=lambda p, ok: (_cleanup(),
                                                         on_done and on_done(p, ok)))

    def _cleanup():
        _PDF_VIEWS.discard(view)
        view.deleteLater()
        try:
            tmp_html.unlink()
        except Exception:
            pass

    view.loadFinished.connect(_after_load)
    view.load(QUrl.fromLocalFile(str(tmp_html.resolve())))
    return  # noqa — implicit, just documenting


# Strong references — Qt would GC the off-screen views before print finished.
_PDF_VIEWS: set = set()


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _collect_pane(jsonl_path: Path, pane: str) -> List[str]:
    out: List[str] = []
    last_ref_seq = None
    for event in _iter_events(jsonl_path):
        et = event.get("type")
        if et == "session_start":
            last_ref_seq = None
        # Mirror the live UI's per-answer separator on the board pane.
        if pane == "board" and et == "board_item":
            ref = event.get("ref_seq")
            if last_ref_seq is not None and ref != last_ref_seq:
                out.append('<hr class="topic-sep">')
            last_ref_seq = ref
        for p, html in event_parser.render(event):
            if p == pane and html:
                out.append(html)
    return out


def _iter_events(jsonl_path: Path) -> Iterable[dict]:
    if not jsonl_path.exists():
        return
    with open(jsonl_path, "rb") as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            try:
                yield json.loads(raw.decode("utf-8"))
            except Exception:
                continue


def _ensure_katex_next_to(out_path: Path) -> None:
    """Copy the vendored katex/ directory next to the HTML output so the
    file renders offline. No-op if already present."""
    if not _KATEX_DIR.exists():
        return
    target = out_path.parent / "katex"
    if target.exists():
        return
    try:
        shutil.copytree(_KATEX_DIR, target)
    except Exception:
        pass   # exports degrade to no-math; never crash the UI on copy error


def _render_page(*, title: str, css: str, body: str,
                 include_katex: bool) -> str:
    head_parts = [
        '<meta charset="utf-8">',
        f'<title>{title}</title>',
        f'<style>{css}</style>',
    ]
    if include_katex:
        head_parts += [
            '<link rel="stylesheet" href="katex/katex.min.css">',
            '<script defer src="katex/katex.min.js"></script>',
            '<script defer src="katex/contrib/auto-render.min.js"></script>',
        ]
    scripts = _KATEX_RENDER_JS if include_katex else ""
    return (
        '<!DOCTYPE html>\n<html lang="ru">\n<head>\n'
        + "\n".join(head_parts)
        + '\n</head>\n<body>\n'
        + body
        + '\n' + scripts
        + '\n</body>\n</html>\n'
    )
