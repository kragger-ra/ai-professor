"""Per-document viewer window.

A QMainWindow with a single QWebEngineView showing the rendered HTML for
the loaded document. The same ``BoardBridge`` is registered as in the main
window, so selection + RMB triggers the existing context menu (read aloud
/ explain / insert into chat) without any extra wiring.
"""
from __future__ import annotations

import html as html_mod
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QMainWindow, QMenu

from board.bridge import BoardBridge
from board.doc_reader import Document


_ASSETS = Path(__file__).resolve().parent / "assets"


_BASE_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>__TITLE__</title>
<script src="qrc:///qtwebchannel/qwebchannel.js"></script>
<style>
  html, body { height:100%; }
  body {
    background:#0d1110; color:#dcdcdc;
    font-family:-apple-system,"Segoe UI",Roboto,sans-serif;
    margin:0; padding:28px 40px 80px;
    font-size:19px; line-height:1.65;
    max-width:1000px; margin-left:auto; margin-right:auto;
  }
  h1, h2, h3, h4 { color:#fff; }
  h1.doc-title { font-size:15px; color:#888; text-transform:uppercase;
    letter-spacing:1.5px; margin:0 0 22px; font-weight:500; }
  .doc-text { white-space:pre-wrap; word-wrap:break-word; }
  .doc-code { background:#0a0d0a; padding:14px 16px; border-radius:6px;
    overflow-x:auto; font-family:Consolas,"Cascadia Code",monospace;
    font-size:17px; color:#e6e6e6; }
  code { background:#181b1a; padding:1px 6px; border-radius:3px;
    font-family:Consolas,"Cascadia Code",monospace; font-size:17px; }
  pre code { background:transparent; padding:0; }
  blockquote { border-left:3px solid #2a3a2a; margin:10px 0;
    padding:4px 14px; color:#bdbdbd; font-style:italic; }
  table { border-collapse:collapse; margin:14px 0; }
  th, td { border:1px solid #2a3a2a; padding:6px 10px; text-align:left; }
  th { background:#181b1a; color:#fff; }
  a { color:#7ab0e0; }
  img { max-width:100%; }
  /* DOCX bodies (from mammoth) — light-on-dark, readable typography. */
  .doc-docx p { margin:10px 0; }
  .doc-docx strong { color:#fff; }
  .doc-docx em { color:#ddd; font-style:italic; }
  .doc-docx h1, .doc-docx h2, .doc-docx h3 { color:#fff; margin:18px 0 8px; }
  .doc-docx ul, .doc-docx ol { padding-left:24px; margin:8px 0; }
  .doc-docx li { margin:4px 0; }
  /* Context menu — identical to the chalkboard side */
  #ctx {
    position:fixed; display:none; z-index:9999;
    background:#1e2422; border:1px solid #3a4a3a; border-radius:6px;
    box-shadow:0 6px 20px rgba(0,0,0,.6); padding:4px; min-width:200px;
    font-size:13px;
  }
  #ctx .ctx-item { padding:7px 12px; border-radius:4px; cursor:pointer; color:#dcdcdc; }
  #ctx .ctx-item:hover { background:#2c5282; color:#fff; }
  #ctx .ctx-sep { height:1px; background:#3a4a3a; margin:4px 0; }
  ::-webkit-scrollbar { width:10px; }
  ::-webkit-scrollbar-track { background:#0d1110; }
  ::-webkit-scrollbar-thumb { background:#2a3a2a; border-radius:5px; }
  ::-webkit-scrollbar-thumb:hover { background:#3a4a3a; }
</style>
</head>
<body>
<h1 class="doc-title">__TITLE_LINE__</h1>
__BODY__

<div id="ctx"></div>
<script>
  let bridge = null;
  new QWebChannel(qt.webChannelTransport, function(ch) {
    bridge = ch.objects.bridge;
  });

  document.addEventListener('contextmenu', (ev) => {
    if (ev.target.closest('#ctx')) { ev.preventDefault(); return; }
    const sel = window.getSelection().toString().trim();
    if (!sel) return;
    ev.preventDefault();
    _showCtx(ev.clientX, ev.clientY, sel);
  });
  document.addEventListener('click', (ev) => {
    if (!ev.target.closest('#ctx')) _hideCtx();
  });

  function _showCtx(x, y, text) {
    const ctx = document.getElementById('ctx');
    ctx.innerHTML =
      '<div class="ctx-item" data-act="read">Прочитать вслух</div>' +
      '<div class="ctx-item" data-act="explain">Объяснить смысл</div>' +
      '<div class="ctx-sep"></div>' +
      '<div class="ctx-item" data-act="insert">Вставить в чат</div>';
    ctx.style.left = x + 'px';
    ctx.style.top  = y + 'px';
    ctx.style.display = 'block';
    ctx.querySelectorAll('.ctx-item').forEach(el => {
      el.addEventListener('click', () => {
        if (!bridge) return _hideCtx();
        const act = el.getAttribute('data-act');
        if (act === 'read')         bridge.read_aloud(text);
        else if (act === 'explain') bridge.explain(text);
        else if (act === 'insert')  bridge.insert_into_chat(text);
        _hideCtx();
      });
    });
  }
  function _hideCtx() { document.getElementById('ctx').style.display = 'none'; }
</script>
</body>
</html>
"""


class _DocWebView(QWebEngineView):
    """QWebEngineView with our context menu — works even on PDFs.

    Inside the native PDF viewer the in-page JS contextmenu listener
    never fires (the plugin handles RMB itself), so we hijack the Qt
    contextMenuEvent and read ``page().selectedText()`` directly.
    """

    def __init__(self, doc: Document, bridge: BoardBridge, parent=None):
        super().__init__(parent)
        self._doc = doc
        self._bridge = bridge

    def contextMenuEvent(self, ev) -> None:
        text = (self.page().selectedText() or "").strip()
        if not text:
            super().contextMenuEvent(ev)
            return
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background:#1e2422; color:#dcdcdc; "
            "border:1px solid #3a4a3a; padding:4px; font-size:14px; }"
            "QMenu::item { padding:7px 18px; border-radius:3px; }"
            "QMenu::item:selected { background:#2c5282; color:#fff; }"
            "QMenu::separator { height:1px; background:#3a4a3a; margin:4px 6px; }"
        )
        a_read    = menu.addAction("Прочитать вслух")
        a_explain = menu.addAction("Объяснить смысл")
        menu.addSeparator()
        a_comment = menu.addAction("Комментарий…")
        a_insert  = menu.addAction("Вставить в чат")
        chosen = menu.exec(ev.globalPos())
        if chosen is None:
            return
        ctx_payload = (
            f"Контекст: документ «{self._doc.name}». Выделено: «{text}»."
        )
        if chosen is a_read:
            # Direct TTS — voice only the selection (no doc context wrapper,
            # otherwise the TTS would say "контекст" out loud).
            self._bridge.read_aloud(text)
        elif chosen is a_explain:
            self._bridge.explain(ctx_payload)
        elif chosen is a_insert:
            self._bridge.insert_into_chat(text)
        elif chosen is a_comment:
            self._bridge.request_comment(text)


class DocumentWindow(QMainWindow):
    def __init__(self, doc: Document, bridge: BoardBridge,
                 parent=None) -> None:
        super().__init__(parent)
        self._doc = doc
        self._bridge = bridge
        self.setWindowTitle(f"AI Professor — {doc.name}")
        self.resize(960, 780)
        self.setStyleSheet("QMainWindow { background:#0d1110; }")

        view = _DocWebView(doc, bridge)
        settings = view.settings()
        # PDFs render via the built-in Chromium PDF viewer when both flags
        # are on — otherwise the page tries to download the file.
        settings.setAttribute(QWebEngineSettings.PdfViewerEnabled, True)
        settings.setAttribute(QWebEngineSettings.PluginsEnabled, True)

        channel = QWebChannel(view.page())
        channel.registerObject("bridge", bridge)
        view.page().setWebChannel(channel)

        if doc.kind == "pdf" and doc.native_url:
            # Render via vendored PDF.js — gives a proper DOM text layer,
            # so our contextmenu listener, comments highlighting, and
            # selection all work the same as on the chalkboard.
            template = (_ASSETS / "pdf_view.html").read_text(encoding="utf-8")
            page_html = (
                template
                .replace("__TITLE__", html_mod.escape(doc.name))
                .replace("__DOC_NAME__",
                         html_mod.escape(doc.name).replace('"', '\\"'))
                .replace("__PDF_URL__", doc.native_url)
            )
            view.setHtml(page_html, QUrl.fromLocalFile(str(_ASSETS) + "/"))
        elif doc.native_url:
            # Other native-rendered formats (none yet) — fall back to direct load.
            view.load(QUrl(doc.native_url))
        else:
            title = html_mod.escape(doc.name)
            title_line = (
                f"{html_mod.escape(doc.name)} &nbsp;·&nbsp; "
                f"{html_mod.escape(doc.kind.upper())}"
            )
            page_html = (
                _BASE_HTML
                .replace("__TITLE__", title)
                .replace("__TITLE_LINE__", title_line)
                .replace("__BODY__", doc.html_body)
            )
            view.setHtml(page_html, QUrl.fromLocalFile(str(_ASSETS) + "/"))
        self.setCentralWidget(view)
        self._view = view
