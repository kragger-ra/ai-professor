"""Read txt / md / pdf / docx / code files into HTML + plain text.

The HTML output is what the DocumentWindow displays in its QWebEngineView
(so the existing JS bridge picks up selection + RMB context menu actions).
The plain-text output is what the tutor sees as additional LLM context.
"""
from __future__ import annotations

import html as html_mod
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

# Extension → kind. Anything not listed falls back to "text".
_CODE_EXTS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".cpp", ".cc", ".h",
    ".hpp", ".cs", ".go", ".rs", ".rb", ".php", ".sh", ".bash", ".ps1",
    ".sql", ".yml", ".yaml", ".toml", ".json", ".xml", ".html", ".css",
    ".kt", ".swift", ".scala",
}
_MD_EXTS = {".md", ".markdown"}
_PDF_EXTS = {".pdf"}
_DOCX_EXTS = {".docx"}
_TEXT_EXTS = {".txt", ".log", ".csv", ".tsv", ".ini", ".cfg", ".conf"}


@dataclass
class Document:
    name: str          # file name only (display)
    path: str          # absolute source path
    kind: str          # "text" | "md" | "pdf" | "docx" | "code"
    text: str          # plain text — for LLM context
    html_body: str     # body HTML — for the doc window webview
    # When set, the doc window loads this URL directly (Chromium's built-in
    # PDF viewer for native rendering). html_body is ignored in that case.
    native_url: str | None = None


# ---------------------------------------------------------------------------

def detect_kind(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in _MD_EXTS:    return "md"
    if ext in _PDF_EXTS:   return "pdf"
    if ext in _DOCX_EXTS:  return "docx"
    if ext in _CODE_EXTS:  return "code"
    return "text"


def load(path: Path) -> Document:
    """Load one file. Never raises on a recognised extension."""
    path = Path(path).resolve()
    kind = detect_kind(path)
    native_url = None
    try:
        if kind == "pdf":
            # The viewer loads the PDF natively (Chromium plugin); we still
            # extract text for LLM context.
            text = _read_pdf(path)
            html_body = ""    # not used when native_url is set
            native_url = path.as_uri()
        elif kind == "docx":
            text, html_body = _read_docx(path)
        elif kind == "md":
            text = _read_text(path)
            html_body = _render_md(text)
        elif kind == "code":
            text = _read_text(path)
            html_body = _wrap_code(text, lang=path.suffix.lstrip("."))
        else:
            text = _read_text(path)
            html_body = _wrap_text(text)
    except Exception as exc:
        text = f"[Не удалось открыть {path.name}: {type(exc).__name__}: {exc}]"
        html_body = (
            f'<p style="color:#d4c266">Не удалось открыть файл.<br>'
            f'<code>{html_mod.escape(str(exc))}</code></p>'
        )
    return Document(name=path.name, path=str(path), kind=kind,
                    text=text, html_body=html_body, native_url=native_url)


# ---------------------------------------------------------------------------
# Format-specific extractors
# ---------------------------------------------------------------------------

def _read_text(path: Path) -> str:
    for enc in ("utf-8", "utf-8-sig", "cp1251", "latin-1"):
        try:
            return path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def _read_pdf(path: Path) -> str:
    import fitz   # PyMuPDF
    out: list[str] = []
    with fitz.open(str(path)) as doc:
        for page in doc:
            t = page.get_text("text")
            if t:
                out.append(t)
    return "\n\n".join(out).strip()


def _read_docx(path: Path) -> tuple[str, str]:
    """Return (plain_text, html_body). HTML keeps bold/italics/lists/tables.

    plain_text is what the tutor sees; html_body is what the doc window
    renders. Mammoth's HTML keeps formatting; raw_text extracts strings.
    """
    import mammoth
    with open(str(path), "rb") as f:
        html_result = mammoth.convert_to_html(f)
    html_body = html_result.value or ""
    # Wrap with a class so the doc_window CSS can scope rules.
    html_body = f'<div class="doc-docx">{html_body}</div>'
    # Plain text for LLM context.
    try:
        with open(str(path), "rb") as f:
            text_result = mammoth.extract_raw_text(f)
        plain_text = (text_result.value or "").strip()
    except Exception:
        plain_text = ""
    return plain_text, html_body


# ---------------------------------------------------------------------------
# HTML renderers
# ---------------------------------------------------------------------------

def _wrap_text(text: str) -> str:
    """Plain text → escaped pre-wrap block, paragraphs preserved."""
    if not text:
        return '<p style="color:#666"><i>пусто</i></p>'
    escaped = html_mod.escape(text)
    return f'<div class="doc-text">{escaped}</div>'


def _wrap_code(text: str, lang: str = "") -> str:
    escaped = html_mod.escape(text)
    lang_attr = f' data-lang="{html_mod.escape(lang)}"' if lang else ""
    return f'<pre class="doc-code"{lang_attr}><code>{escaped}</code></pre>'


def _render_md(text: str) -> str:
    import markdown
    return markdown.markdown(
        text,
        extensions=["extra", "sane_lists", "tables", "fenced_code"],
    )
