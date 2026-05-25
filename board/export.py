"""Export board and chat panes to PDF and self-contained HTML.

PDF goes through Qt (``QWebEnginePage.printToPdf``) and needs an
instantiated view to print from. HTML export is a pure replay of the
JSONL through ``board.parser.render``; it works even when called from
the CLI on a yesterday's session.

The exported HTML is self-contained: KaTeX CSS/JS are inlined from the
vendored ``board/assets/katex/`` directory, so the file renders formulas
without internet access. Font files (``.woff2``) are NOT inlined; the
HTML keeps relative ``katex/fonts/...`` URLs and the exporter copies the
katex/ directory next to the output file when needed.
"""
from __future__ import annotations

import json
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
