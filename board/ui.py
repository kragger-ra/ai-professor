"""Main window for the board sidecar.

Board (chalk-style HTML, KaTeX) on the left, detachable chat dock on the
right. The chat pane has three voice modes:

  open       — VAD always listens, every utterance goes to the LLM
  transcribe — STT writes the recognised text into the chat input field for
               the user to edit/send manually (closes the noise problem)
  ptt        — VAD is paused on the tutor side; the user clicks record,
               can preview/delete/re-record, and sends a single voice
               message at a time

The voice modes are switched by sending an ``stt_mode`` command to the
tutor; the tutor flips ``CaptureThread.stt_mode`` and pauses/resumes the
mic capture accordingly.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from PySide6.QtCore import Qt, QSettings, QTimer, QUrl
from PySide6.QtGui import QAction, QActionGroup, QKeySequence, QShortcut
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QDockWidget, QFileDialog, QHBoxLayout, QInputDialog, QLineEdit,
    QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox,
    QPushButton, QToolBar, QVBoxLayout, QWidget,
)

from board import doc_reader
from board import export as exporter
from board import parser as event_parser
from board.bridge import BoardBridge
from board.commands import BoardCommander
from board.course_builder import CourseBuilderDialog
from board.course_manager import CourseManagerDock
from board.course_switcher import CourseQuickSwitcher
from board.doc_window import DocumentWindow
from board.documents import DocumentStore
from board.settings_dialog import ConnectionsDialog
from board.tail import JsonlTail

_ASSETS = Path(__file__).resolve().parent / "assets"


class _LoggingPage(QWebEnginePage):
    """QWebEnginePage that mirrors JS console messages to Python stdout
    so 'console.error(...)' from board.html actually shows up in the
    board process bat log. Mermaid render failures used to silently
    disappear into the WebEngine console — this surfaces them."""

    _LEVEL = {
        QWebEnginePage.JavaScriptConsoleMessageLevel.InfoMessageLevel: "INFO",
        QWebEnginePage.JavaScriptConsoleMessageLevel.WarningMessageLevel: "WARN",
        QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel: "ERR ",
    }

    def javaScriptConsoleMessage(self, level, message, line, source):
        tag = self._LEVEL.get(level, "?   ")
        print(f"[board-js {tag}] {message}  ({source}:{line})", flush=True)
_DATA = Path(__file__).resolve().parent.parent / "data"
_SESSIONS_DIR = _DATA / "sessions"


# ---------------------------------------------------------------------------
# Chat pane: webview + voice-mode bar + (text input | PTT recorder)
# ---------------------------------------------------------------------------

class ChatPane(QWidget):
    """Chat history + text input + voice-mode toggle.

    Two voice modes:
      * ``open``       — VAD-mic always on; every utterance auto-sent to LLM
      * ``transcribe`` — STT writes into the input field; user edits and
                         sends manually. A record/stop toggle inside this
                         mode pauses/resumes the mic via stt_paused.
    """

    def __init__(self, commander: BoardCommander, parent=None) -> None:
        super().__init__(parent)
        self._commander = commander

        # --- webview ----------------------------------------------------
        self.view = QWebEngineView()
        self.view.load(QUrl.fromLocalFile(str(_ASSETS / "chat.html")))

        # --- voice-mode toggle bar -------------------------------------
        self._mode_buttons: dict[str, QPushButton] = {}
        mode_bar_widget = QWidget()
        mode_bar_widget.setStyleSheet(
            "QWidget { background:#15191a; border-bottom:1px solid #2a3a2a; }")
        mode_bar = QHBoxLayout(mode_bar_widget)
        mode_bar.setContentsMargins(8, 6, 8, 6)
        mode_bar.setSpacing(6)
        for key, label, tip in [
            ("open",       "Открытый микрофон",
             "Микрофон всегда слушает, реплики уходят сразу в LLM"),
            ("transcribe", "Запись с правкой",
             "Запись с правкой: STT пишет в поле, ты редактируешь и сам отправляешь"),
        ]:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setToolTip(tip)
            btn.setStyleSheet(
                "QPushButton { background:#1f2422; color:#bbb; "
                "border:1px solid #2c3530; border-radius:6px; "
                "padding:7px 14px; font-size:15px; }"
                "QPushButton:hover { background:#2a3530; color:#fff; }"
                "QPushButton:checked { background:#3a5a3a; color:#fff; "
                "border-color:#5a7a5a; }"
            )
            btn.clicked.connect(lambda _checked, k=key: self.set_voice_mode(k))
            mode_bar.addWidget(btn)
            self._mode_buttons[key] = btn
        mode_bar.addStretch(1)
        self._mode_buttons["open"].setChecked(True)

        # --- input row: [rec toggle] [text input] [send] ---------------
        # `rec_btn` is only visible in "transcribe" mode. It toggles the
        # tutor-side capture pause: pressed = mic active, released = paused.
        self.rec_btn = QPushButton("Старт")
        self.rec_btn.setCheckable(True)
        self.rec_btn.setFixedWidth(64)
        self.rec_btn.setToolTip("Старт/стоп распознавания речи")
        self.rec_btn.setStyleSheet(self._rec_btn_css())
        self.rec_btn.toggled.connect(self._on_rec_toggled)
        self.rec_btn.setVisible(False)

        self.attach_btn = QPushButton("Файл")
        self.attach_btn.setFixedWidth(56)
        self.attach_btn.setToolTip("Прикрепить документ (PDF, DOCX, MD, TXT, код)")
        self.attach_btn.setStyleSheet(self._rec_btn_css())
        # MainWindow connects this to its own upload handler.

        self.input = QLineEdit()
        self.input.setPlaceholderText("Введите вопрос и нажмите Enter…")
        self.input.setStyleSheet(
            "QLineEdit { background:#1a1a1a; color:#e0e0e0; "
            "border:1px solid #2c2c2c; border-radius:6px; "
            "padding:8px 12px; font-size:15px; }"
            "QLineEdit:focus { border-color:#3a82c8; }"
        )
        self.input.returnPressed.connect(self._on_send)

        self.send_btn = QPushButton("→")
        self.send_btn.setFixedWidth(36)
        self.send_btn.setStyleSheet(
            "QPushButton { background:#2c5282; color:#fff; "
            "border:none; border-radius:6px; padding:6px; font-weight:600; }"
            "QPushButton:hover { background:#3a6cad; }"
        )
        self.send_btn.clicked.connect(self._on_send)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(self.rec_btn)
        row.addWidget(self.attach_btn)
        row.addWidget(self.input, 1)
        row.addWidget(self.send_btn)

        # --- assemble ---------------------------------------------------
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        col.addWidget(mode_bar_widget)
        col.addWidget(self.view, 1)
        # Input row gets its own padded container so it doesn't crowd the
        # webview edge and inherits the chat background.
        input_container = QWidget()
        input_container.setStyleSheet(
            "QWidget { background:#0e0e0e; border-top:1px solid #2a2a2a; }")
        ic_layout = QVBoxLayout(input_container)
        ic_layout.setContentsMargins(8, 8, 8, 8)
        ic_layout.addLayout(row)
        col.addWidget(input_container)
        self.setStyleSheet("ChatPane { background:#0e0e0e; }")

        self._voice_mode = "open"

    # ------------------------------------------------------------------
    # Voice mode
    # ------------------------------------------------------------------

    def set_voice_mode(self, mode: str) -> None:
        if mode not in ("open", "transcribe"):
            return
        if mode == self._voice_mode:
            self._mode_buttons[mode].setChecked(True)
            return
        self._voice_mode = mode
        for k, btn in self._mode_buttons.items():
            btn.setChecked(k == mode)
        self._commander.stt_mode(mode)
        if mode == "transcribe":
            self.rec_btn.setVisible(True)
            # Enter transcribe paused — student decides when to start dictating.
            self.rec_btn.blockSignals(True)
            self.rec_btn.setChecked(False)
            self.rec_btn.setStyleSheet(self._rec_btn_css(active=False))
            self.rec_btn.setText("Старт")
            self.rec_btn.blockSignals(False)
            self._commander.stt_paused(True)
            self.input.setPlaceholderText(
                "Жми «Старт», говори — текст появится здесь. Можно править и отправлять.")
        else:   # open
            self.rec_btn.setVisible(False)
            # Open mode: capture is always live.
            self._commander.stt_paused(False)
            self.input.setPlaceholderText(
                "Введите вопрос и нажмите Enter…")

    def voice_mode(self) -> str:
        return self._voice_mode

    def _on_rec_toggled(self, checked: bool) -> None:
        """Inside transcribe mode: pause/resume STT on user demand."""
        # checked=True  → recording (capture unpaused)
        # checked=False → stopped   (capture paused)
        self._commander.stt_paused(not checked)
        if checked:
            self.rec_btn.setText("Стоп")
            self.rec_btn.setStyleSheet(self._rec_btn_css(active=True))
        else:
            self.rec_btn.setText("Старт")
            self.rec_btn.setStyleSheet(self._rec_btn_css(active=False))

    # ------------------------------------------------------------------
    # Text input path
    # ------------------------------------------------------------------

    def _on_send(self) -> None:
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        # If recording was on, stop it after send — same flow as Telegram:
        # send finalises the message, mic goes quiet until next start.
        if self._voice_mode == "transcribe" and self.rec_btn.isChecked():
            self.rec_btn.setChecked(False)   # triggers _on_rec_toggled(False)
        self._commander.chat_input(text)

    def fill_input(self, text: str) -> None:
        """Append a clicked term/formula to whatever the user already typed."""
        cur = self.input.text()
        sep = " " if cur and not cur.endswith(" ") else ""
        self.input.setText(cur + sep + text)
        self.input.setFocus()

    def set_input_text(self, text: str) -> None:
        """Append STT result to the input field (transcribe mode).

        Append, not replace — so the student can dictate multiple phrases
        into one message. Existing typed text is preserved.
        """
        cur = self.input.text()
        sep = " " if cur and not cur.endswith(" ") else ""
        self.input.setText(cur + sep + text)
        self.input.setFocus()

    @staticmethod
    def _rec_btn_css(active: bool = False) -> str:
        if active:
            return (
                "QPushButton { background:#5a2c2c; color:#fff; border:none; "
                "border-radius:6px; padding:6px; font-weight:600; }"
                "QPushButton:hover { background:#6a3a3a; }"
            )
        return (
            "QPushButton { background:#1a1a1a; color:#cfcfcf; "
            "border:1px solid #2c2c2c; border-radius:6px; padding:6px; }"
            "QPushButton:hover { background:#2a3a2a; }"
        )


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self, jsonl_path: Path, *, from_start: bool = False) -> None:
        super().__init__()
        self.setWindowTitle("AI Professor — доска")
        self.resize(1500, 880)
        self.setStyleSheet("QMainWindow { background:#0d1110; }")
        # AllowNestedDocks lets the user split one dock area into multiple
        # sub-zones (e.g. Documents stacked next to Chat on the right),
        # not just along the main window edges.
        self.setDockOptions(
            QMainWindow.AnimatedDocks
            | QMainWindow.AllowTabbedDocks
            | QMainWindow.AllowNestedDocks
        )

        self._jsonl_path = Path(jsonl_path)

        self._commander = BoardCommander()
        self._bridge = BoardBridge(self._commander, parent=self)
        self._docs = DocumentStore()
        self._doc_windows: dict[str, DocumentWindow] = {}

        # Accept files dropped anywhere on the main window.
        self.setAcceptDrops(True)

        # --- board (central) -------------------------------------------
        self.board_view = QWebEngineView()
        self.board_view.setPage(_LoggingPage(self.board_view))
        self._wire_channel(self.board_view)
        self.board_view.load(QUrl.fromLocalFile(str(_ASSETS / "board.html")))
        self.setCentralWidget(self.board_view)

        # --- chat dock (detachable) ------------------------------------
        self.chat_pane = ChatPane(self._commander)
        self._wire_channel(self.chat_pane.view)
        self._bridge.insert_into_chat_requested.connect(self.chat_pane.fill_input)
        self._bridge.intent_emitted.connect(self._on_intent)
        self._bridge.comment_requested.connect(self._on_comment_requested)
        # Wire the paperclip button to the upload handler.
        self.chat_pane.attach_btn.clicked.connect(self._on_attach_clicked)

        self.chat_dock = QDockWidget("Чат", self)
        self.chat_dock.setObjectName("chat_dock")
        self.chat_dock.setAllowedAreas(Qt.AllDockWidgetAreas)
        self.chat_dock.setFeatures(
            QDockWidget.DockWidgetMovable
            | QDockWidget.DockWidgetFloatable
            | QDockWidget.DockWidgetClosable
        )
        self.chat_dock.setWidget(self.chat_pane)
        self.chat_dock.setStyleSheet(
            "QDockWidget { color:#e0e0e0; font-size:14px; }"
            "QDockWidget::title { background:#1c2120; padding:7px 14px; "
            "border:1px solid #3a4a3a; border-bottom:2px solid #3a4a3a; "
            "text-align:left; font-weight:600; letter-spacing:.5px; }"
            "QDockWidget::close-button, QDockWidget::float-button { "
            "background:transparent; border:0; padding:2px; }"
            "QDockWidget::close-button:hover { background:#5a2c2c; }"
            "QDockWidget::float-button:hover { background:#3a4a3a; }"
        )
        self.addDockWidget(Qt.RightDockWidgetArea, self.chat_dock)
        self.resizeDocks([self.chat_dock], [340], Qt.Horizontal)

        # --- artifacts dock (left) -------------------------------------
        self.artifacts_list = QListWidget()
        self.artifacts_list.setStyleSheet(
            "QListWidget { background:#0e0e0e; color:#cfcfcf; "
            "border:0; padding:6px; }"
            "QListWidget::item { padding:6px 8px; border-radius:4px; }"
            "QListWidget::item:selected { background:#2a3a2a; color:#fff; }"
            "QListWidget::item:hover { background:#1a1f1c; }"
        )
        self.artifacts_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.artifacts_list.customContextMenuRequested.connect(
            self._on_artifact_menu)
        self.artifacts_list.itemDoubleClicked.connect(
            lambda it: self._open_artifact_window(it.data(Qt.UserRole)))

        self.artifacts_dock = QDockWidget("Документы", self)
        self.artifacts_dock.setObjectName("artifacts_dock")
        self.artifacts_dock.setAllowedAreas(Qt.AllDockWidgetAreas)
        self.artifacts_dock.setFeatures(
            QDockWidget.DockWidgetMovable
            | QDockWidget.DockWidgetFloatable
            | QDockWidget.DockWidgetClosable
        )
        self.artifacts_dock.setWidget(self.artifacts_list)
        self.artifacts_dock.setStyleSheet(
            "QDockWidget { color:#e0e0e0; font-size:14px; }"
            "QDockWidget::title { background:#1c2120; padding:7px 14px; "
            "border:1px solid #3a4a3a; border-bottom:2px solid #3a4a3a; "
            "text-align:left; font-weight:600; letter-spacing:.5px; }"
            "QDockWidget::close-button, QDockWidget::float-button { "
            "background:transparent; border:0; padding:2px; }"
            "QDockWidget::close-button:hover { background:#5a2c2c; }"
            "QDockWidget::float-button:hover { background:#3a4a3a; }"
        )
        self.addDockWidget(Qt.LeftDockWidgetArea, self.artifacts_dock)
        self.resizeDocks([self.artifacts_dock], [240], Qt.Horizontal)

        # --- course manager dock (left, under artifacts) ---------------
        self.course_manager_dock = CourseManagerDock(self)
        self.course_manager_dock.setStyleSheet(self.artifacts_dock.styleSheet())
        self.addDockWidget(Qt.LeftDockWidgetArea, self.course_manager_dock)
        self.splitDockWidget(self.artifacts_dock, self.course_manager_dock,
                             Qt.Vertical)
        self.course_manager_dock.activate_requested.connect(
            self._on_course_activate)
        self.course_manager_dock.build_requested.connect(
            self._open_course_builder)

        # Active course path — kept in sync via the course_loaded event.
        self._current_course_path: str = ""

        # --- menu + toolbar --------------------------------------------
        self._build_menubar()
        self._build_toolbar()

        # --- buffer events until both webviews are ready ---------------
        self._pending: list[dict] = []
        self._board_ready = False
        self._chat_ready = False
        self.board_view.loadFinished.connect(self._on_board_loaded)
        self.chat_pane.view.loadFinished.connect(self._on_chat_loaded)

        # Last seen ref_seq on the board — when it changes between board_items
        # we insert a thin pencil-line separator: visually delimits one
        # professor answer from the next.
        self._last_board_ref_seq: int | None = None

        self.tail: JsonlTail | None = None
        self._start_tail(self._jsonl_path, from_start=from_start)
        # Initial scroll: for a fresh empty session start at the top, for a
        # replay or for a session that already had content we honour the
        # auto-scroll which lands at the bottom.
        if from_start:
            QTimer.singleShot(1200, self._scroll_panes_bottom)

        # Export shortcuts (kept from the previous window).
        QShortcut(QKeySequence("Ctrl+E"), self,
                  activated=lambda: self._export("board", "pdf"))
        QShortcut(QKeySequence("Ctrl+Shift+E"), self,
                  activated=lambda: self._export("chat", "pdf"))
        QShortcut(QKeySequence("Ctrl+H"), self,
                  activated=lambda: self._export("board", "html"))
        QShortcut(QKeySequence("Ctrl+Shift+H"), self,
                  activated=lambda: self._export("chat", "html"))

    # ------------------------------------------------------------------
    # Menu / toolbar
    # ------------------------------------------------------------------

    def _build_menubar(self) -> None:
        mb = self.menuBar()
        mb.setStyleSheet(
            "QMenuBar { background:#22272a; color:#e0e0e0; padding:4px 6px; "
            "border-bottom:1px solid #3a4a3a; font-size:15px; }"
            "QMenuBar::item { padding:6px 14px; border-radius:4px; }"
            "QMenuBar::item:selected { background:#3a4a3a; color:#fff; }"
            "QMenu { background:#1c2120; color:#e0e0e0; "
            "border:1px solid #3a4a3a; padding:4px; font-size:15px; }"
            "QMenu::item { padding:7px 20px; border-radius:3px; }"
            "QMenu::item:selected { background:#3a4a3a; color:#fff; }"
            "QMenu::separator { height:1px; background:#2a3a2a; margin:4px 6px; }"
        )

        # Файл
        file_menu = mb.addMenu("Файл")
        a_open = QAction("Открыть сессию…", self,
                         shortcut=QKeySequence("Ctrl+O"))
        a_open.triggered.connect(self._open_session)
        file_menu.addAction(a_open)
        a_live = QAction("Вернуться к текущей сессии", self)
        a_live.triggered.connect(self._open_live)
        file_menu.addAction(a_live)
        a_save_session = QAction("Сохранить сессию как… (доска+чат)", self,
                                 shortcut=QKeySequence("Ctrl+S"))
        a_save_session.triggered.connect(self._save_session_as)
        file_menu.addAction(a_save_session)
        file_menu.addSeparator()
        # Экспорт — две оси: что (доска / чат / доска+чат) × формат (PDF / HTML / MD).
        export_menu = file_menu.addMenu("Экспорт")
        for scope_key, scope_label, shortcut_hint in (
            ("board", "Только доска", "Ctrl+E"),
            ("chat", "Только чат", "Ctrl+Shift+E"),
            ("combined", "Доска + чат", ""),
        ):
            sub = export_menu.addMenu(scope_label)
            for fmt, fmt_label in (
                ("pdf", "→ PDF"),
                ("html", "→ HTML"),
                ("md", "→ Markdown"),
            ):
                act = QAction(fmt_label, self)
                # Defaults: Ctrl+E exports board→PDF, Ctrl+Shift+E exports chat→PDF
                # (matches the previous shortcut for the most common case).
                if fmt == "pdf" and shortcut_hint:
                    act.setShortcut(QKeySequence(shortcut_hint))
                act.triggered.connect(
                    lambda _checked=False, s=scope_key, f=fmt: self._export(s, f))
                sub.addAction(act)
        # Импорт — обратная операция. PDF read-only, не парсится.
        import_menu = file_menu.addMenu("Импорт")
        a_import_html = QAction("Сессию из HTML…", self)
        a_import_html.triggered.connect(lambda: self._import_session("html"))
        import_menu.addAction(a_import_html)
        a_import_md = QAction("Сессию из Markdown…", self)
        a_import_md.triggered.connect(lambda: self._import_session("md"))
        import_menu.addAction(a_import_md)
        file_menu.addSeparator()
        a_settings = QAction("Настройки подключений…", self)
        a_settings.triggered.connect(self._open_connections_settings)
        file_menu.addAction(a_settings)
        file_menu.addSeparator()
        a_quit = QAction("Выход", self, shortcut=QKeySequence("Ctrl+Q"))
        a_quit.triggered.connect(self.close)
        file_menu.addAction(a_quit)

        # Вид — мелочи отображения
        view_menu = mb.addMenu("Вид")
        self.act_detach = QAction("Отделить чат в отдельное окно",
                                  self, checkable=True)
        self.act_detach.toggled.connect(self._on_detach_toggled)
        view_menu.addAction(self.act_detach)
        a_redock = QAction("Прикрепить чат обратно", self)
        a_redock.triggered.connect(self._on_chat_redock)
        view_menu.addAction(a_redock)

        # Окна — единый список панелей с показ/спрятать (+ сброс раскладки)
        windows_menu = mb.addMenu("Окна")
        self._windows_menu = windows_menu
        windows_menu.aboutToShow.connect(self._rebuild_windows_menu)

        # Документы
        docs_menu = mb.addMenu("Документы")
        a_attach = QAction("Прикрепить файл…", self,
                           shortcut=QKeySequence("Ctrl+L"))
        a_attach.triggered.connect(self._on_attach_clicked)
        docs_menu.addAction(a_attach)
        a_clear_docs = QAction("Удалить все из контекста", self)
        a_clear_docs.triggered.connect(self._on_clear_documents)
        docs_menu.addAction(a_clear_docs)

        # Звук
        audio_menu = mb.addMenu("Звук")
        self.act_mute = QAction("Заглушить TTS", self, checkable=True)
        self.act_mute.setShortcut(QKeySequence("Ctrl+M"))
        self.act_mute.toggled.connect(self._on_mute_toggled)
        audio_menu.addAction(self.act_mute)
        audio_menu.addSeparator()
        # Аудио-режим — radio choice. The board persists the pick in QSettings;
        # the tutor reads data/audio_mode.txt on startup, so the change applies
        # only after a tutor restart (the audio threads hold their devices open
        # for the lifetime of the process).
        mode_menu = audio_menu.addMenu("Аудио-режим")
        self._mode_group = QActionGroup(self)
        self._mode_group.setExclusive(True)
        self.act_mode_local = QAction(
            "Локальный (микрофон / динамики)", self, checkable=True,
        )
        self.act_mode_meeting = QAction(
            "Режим созвона (виртуальный кабель)", self, checkable=True,
        )
        self._mode_group.addAction(self.act_mode_local)
        self._mode_group.addAction(self.act_mode_meeting)
        mode_menu.addAction(self.act_mode_local)
        mode_menu.addAction(self.act_mode_meeting)
        # Initial state from QSettings; default to local on first launch.
        settings = QSettings("AI-Professor", "Board")
        saved_mode = str(settings.value("audio/mode", "local")).strip().lower()
        if saved_mode not in ("local", "meeting"):
            saved_mode = "local"
        self._audio_mode = saved_mode
        (self.act_mode_meeting if saved_mode == "meeting"
         else self.act_mode_local).setChecked(True)
        self.act_mode_local.triggered.connect(
            lambda: self._on_audio_mode_picked("local"))
        self.act_mode_meeting.triggered.connect(
            lambda: self._on_audio_mode_picked("meeting"))

        # Курсы
        courses_menu = mb.addMenu("Курсы")
        a_courses_browse = QAction("Менеджер курсов…", self)
        a_courses_browse.triggered.connect(self._show_course_manager)
        courses_menu.addAction(a_courses_browse)
        a_courses_prep = QAction("Подготовить RAG-пакет…", self)
        a_courses_prep.triggered.connect(self._open_course_builder)
        courses_menu.addAction(a_courses_prep)
        courses_menu.addSeparator()
        a_courses_export = QAction("Экспортировать выбранный курс…", self)
        a_courses_export.triggered.connect(
            lambda: self.course_manager_dock.export_selected())
        courses_menu.addAction(a_courses_export)
        a_courses_import = QAction("Импортировать курс из .zip…", self)
        a_courses_import.triggered.connect(
            lambda: self.course_manager_dock.import_zip())
        courses_menu.addAction(a_courses_import)

        # Видеоматериалы (заглушка)
        video_menu = mb.addMenu("Видеоматериалы")
        a_video_load = QAction("Загрузить лекцию…", self)
        a_video_load.triggered.connect(
            lambda: self._stub("Видеолекция",
                               "Плеер + транскрипция + чат с ИИ по содержанию"))
        video_menu.addAction(a_video_load)
        a_video_url = QAction("По ссылке…", self)
        a_video_url.triggered.connect(
            lambda: self._stub("Видео по ссылке",
                               "YouTube/прямые ссылки на видео"))
        video_menu.addAction(a_video_url)
        a_video_notes = QAction("Конспект из видео…", self)
        a_video_notes.triggered.connect(
            lambda: self._stub("Конспект",
                               "Автогенерация конспекта по транскрипции"))
        video_menu.addAction(a_video_notes)

    def _build_toolbar(self) -> None:
        tb = QToolBar()
        tb.setMovable(False)
        tb.setStyleSheet(
            "QToolBar { background:#15191a; border:0; "
            "border-bottom:1px solid #2a3a2a; padding:5px 10px; spacing:8px; }"
            "QToolButton { color:#cfcfcf; background:transparent; "
            "border:1px solid transparent; padding:6px 14px; "
            "border-radius:4px; font-size:14px; }"
            "QToolButton:hover { background:#2a3a2a; color:#fff; }"
            "QToolButton:checked { background:#3a5a3a; color:#fff; "
            "border-color:#4a6a4a; }"
        )
        self.addToolBar(Qt.TopToolBarArea, tb)
        # Quick course switcher — leftmost so a new user can spot the active
        # RAG corpus and change it without diving into menus.
        self.course_switcher = CourseQuickSwitcher(self)
        self.course_switcher.course_chosen.connect(self._on_course_activate)
        self.course_switcher.build_requested.connect(self._open_course_builder)
        self.course_switcher.manager_requested.connect(self._show_course_manager)
        tb.addWidget(self.course_switcher)
        tb.addSeparator()
        tb.addAction(self.act_mute)
        tb.addAction(self.act_detach)
        self.act_comments = QAction("Примечания", self, checkable=True)
        self.act_comments.setToolTip(
            "Показать/спрятать боковую панель комментариев на доске")
        self.act_comments.toggled.connect(self._on_comments_toggled)
        tb.addAction(self.act_comments)
        # Best-effort: seed the switcher from the persisted active course
        # so the label is correct on launch (before the first event arrives).
        self._init_current_course_label()

    # ------------------------------------------------------------------
    # WebChannel
    # ------------------------------------------------------------------

    def _wire_channel(self, view: QWebEngineView) -> None:
        channel = QWebChannel(view.page())
        channel.registerObject("bridge", self._bridge)
        view.page().setWebChannel(channel)

    # ------------------------------------------------------------------
    # Tail + dispatch
    # ------------------------------------------------------------------

    def _start_tail(self, path: Path, *, from_start: bool) -> None:
        if self.tail is not None:
            try:
                self.tail.stop_tail()
                self.tail.wait(2000)
            except Exception:
                pass
        self.tail = JsonlTail(path, from_start=from_start, parent=self)
        self.tail.new_event.connect(self._on_event)
        self.tail.error.connect(self._on_tail_error)
        self.tail.start()

    def _on_board_loaded(self, ok: bool) -> None:
        self._board_ready = bool(ok)
        print(f"[board-py] board loadFinished ok={ok} "
              f"pending={len(self._pending)}", flush=True)
        self._flush_pending()

    def _on_chat_loaded(self, ok: bool) -> None:
        self._chat_ready = bool(ok)
        print(f"[board-py] chat loadFinished ok={ok} "
              f"pending={len(self._pending)}", flush=True)
        self._flush_pending()

    def _flush_pending(self) -> None:
        if not (self._board_ready and self._chat_ready):
            print(f"[board-py] flush_pending blocked: "
                  f"board_ready={self._board_ready} chat_ready={self._chat_ready}",
                  flush=True)
            return
        if self._pending:
            print(f"[board-py] flush_pending dispatching {len(self._pending)} queued events",
                  flush=True)
        for event in self._pending:
            self._dispatch(event)
        self._pending.clear()

    def _on_event(self, event: dict) -> None:
        et = event.get("type", "?")
        # stt_transcript bypasses the webview — drop it into the chat input.
        if et == "stt_transcript":
            self.chat_pane.set_input_text(event.get("text", ""))
            return
        if not (self._board_ready and self._chat_ready):
            self._pending.append(event)
            print(f"[board-py] queue {et} (board_ready={self._board_ready} "
                  f"chat_ready={self._chat_ready} pending={len(self._pending)})",
                  flush=True)
            return
        print(f"[board-py] dispatch {et}", flush=True)
        self._dispatch(event)

    def _dispatch(self, event: dict) -> None:
        et = event.get("type")
        if et == "course_loaded":
            short = (event.get("short_name") or "").strip()
            name = (event.get("name") or "").strip()
            path = (event.get("path") or "").strip()
            chunks = event.get("chunks") or 0
            self._current_course_path = path
            self.course_switcher.set_current(short, path)
            self.course_manager_dock.set_current(path)
            self.statusBar().showMessage(
                f"Курс загружен: {name or short} ({chunks} фрагмент(ов))", 5000)
            return
        if et == "course_load_failed":
            error = (event.get("error") or "").strip() or "неизвестная ошибка"
            path = (event.get("path") or "").strip()
            QMessageBox.warning(self, "Курс не загружен",
                                f"{error}\n\n{path}")
            return
        if et == "comment_added":
            arg = json.dumps({
                "id": event.get("comment_id", ""),
                "anchor": event.get("anchor", ""),
                "note": event.get("note", ""),
            })
            self.board_view.page().runJavaScript(f"applyComment({arg});")
            return
        if et == "comment_removed":
            arg = json.dumps(event.get("comment_id", ""))
            self.board_view.page().runJavaScript(f"removeComment({arg});")
            return
        if et == "session_start":
            self._last_board_ref_seq = None
        # Before rendering a board_item belonging to a NEW professor answer
        # (different ref_seq), insert a pencil-line topic separator so the
        # chalkboard does not blur multiple answers into one wall of text.
        if et == "board_item":
            ref = event.get("ref_seq")
            if (self._last_board_ref_seq is not None
                    and ref != self._last_board_ref_seq):
                sep = json.dumps('<hr class="topic-sep">')
                self.board_view.page().runJavaScript(f"appendItem({sep});")
            self._last_board_ref_seq = ref
        for pane, fragment in event_parser.render(event):
            if not fragment:
                continue
            arg = json.dumps(fragment)
            if pane == "board":
                self.board_view.page().runJavaScript(f"appendItem({arg});")
            elif pane == "chat":
                self.chat_pane.view.page().runJavaScript(f"appendMsg({arg});")

    def _on_tail_error(self, msg: str) -> None:
        self._dispatch({"type": "warning", "text": f"tail: {msg}"})

    def _on_intent(self, label: str, text: str) -> None:
        """Render a small system chip in the chat for a JS-triggered action."""
        snippet = text if len(text) <= 70 else text[:67] + "…"
        arg_lbl = json.dumps(label)
        arg_txt = json.dumps(snippet)
        self.chat_pane.view.page().runJavaScript(
            f"appendIntent({arg_lbl}, {arg_txt});"
        )

    def _on_comments_toggled(self, checked: bool) -> None:
        js = "showComments();" if checked else "hideComments();"
        self.board_view.page().runJavaScript(js)

    def _on_comment_requested(self, anchor: str) -> None:
        """Show a Qt dialog so the student can type the note in dark mode."""
        preview = anchor if len(anchor) <= 90 else anchor[:87] + "…"
        note, ok = QInputDialog.getMultiLineText(
            self, "Новый комментарий",
            f'К фрагменту:\n«{preview}»', "")
        if not ok:
            return
        note = note.strip()
        if not note:
            return
        cid = "c_" + uuid.uuid4().hex[:10]
        self._commander.add_comment(cid, anchor, note)
        # Make sure the side panel is visible so the user sees the new card.
        if not self.act_comments.isChecked():
            self.act_comments.setChecked(True)

    # ------------------------------------------------------------------
    # Menu actions
    # ------------------------------------------------------------------

    def _open_session(self) -> None:
        start_dir = str(_SESSIONS_DIR if _SESSIONS_DIR.exists() else _DATA)
        path_str, _ = QFileDialog.getOpenFileName(
            self, "Открыть архив сессии", start_dir,
            "Session log (board_*.jsonl);;All files (*)"
        )
        if not path_str:
            return
        self.board_view.page().runJavaScript("clearBoard();")
        self.chat_pane.view.page().runJavaScript("clearChat();")
        self._start_tail(Path(path_str), from_start=True)
        # Wait for replay + KaTeX to settle, then pin both panes to the
        # last message — what the user expects when reopening a session.
        QTimer.singleShot(1200, self._scroll_panes_bottom)
        self.statusBar().showMessage(f"Открыто: {path_str}", 5000)

    def _open_live(self) -> None:
        self.board_view.page().runJavaScript("clearBoard();")
        self.chat_pane.view.page().runJavaScript("clearChat();")
        self._start_tail(self._jsonl_path, from_start=False)
        # Fresh live tail = no historical content; show the top.
        self.board_view.page().runJavaScript("scrollTop();")
        self.chat_pane.view.page().runJavaScript("scrollTop();")
        self.statusBar().showMessage("Снова слушаем текущую сессию", 5000)

    def _scroll_panes_bottom(self) -> None:
        self.board_view.page().runJavaScript("scrollBottom();")
        self.chat_pane.view.page().runJavaScript("scrollBottom();")

    def _on_mute_toggled(self, checked: bool) -> None:
        self._commander.tts_mute(checked)
        self.statusBar().showMessage(
            "TTS заглушён" if checked else "TTS включён", 3000)

    def _on_audio_mode_picked(self, mode: str) -> None:
        """User toggled an audio-mode radio. Persist + tell the tutor.

        The tutor hot-swaps both mic and TTS-output devices live — the
        current sentence finishes on the old output, the new mic comes
        online within ~100ms. No restart needed.
        """
        if mode not in ("local", "meeting"):
            return
        self._audio_mode = mode
        try:
            settings = QSettings("AI-Professor", "Board")
            settings.setValue("audio/mode", mode)
        except Exception:
            pass
        self._commander.audio_mode(mode)
        label = ("Локальный режим (микрофон / динамики)" if mode == "local"
                 else "Режим созвона (виртуальный кабель)")
        self.statusBar().showMessage(f"Аудио-режим: {label}", 4000)

    def _on_detach_toggled(self, checked: bool) -> None:
        if checked:
            self.chat_dock.setFloating(True)
            # Position the floating window next to the main window.
            geo = self.geometry()
            self.chat_dock.move(geo.right() + 12, geo.top() + 60)
        else:
            self.chat_dock.setFloating(False)

    def _on_chat_redock(self) -> None:
        """Forcibly re-dock the chat into its standard area + show it."""
        self.chat_dock.setFloating(False)
        self.chat_dock.setVisible(True)
        if self.dockWidgetArea(self.chat_dock) == Qt.NoDockWidgetArea:
            self.addDockWidget(Qt.RightDockWidgetArea, self.chat_dock)
        self.act_detach.blockSignals(True)
        self.act_detach.setChecked(False)
        self.act_detach.blockSignals(False)
        self.chat_dock.raise_()

    # ------------------------------------------------------------------
    # Windows menu — auto-rebuilt on aboutToShow
    # ------------------------------------------------------------------

    def _rebuild_windows_menu(self) -> None:
        menu = self._windows_menu
        menu.clear()
        for dock in self._all_docks():
            act = QAction(dock.windowTitle(), self, checkable=True)
            act.setChecked(dock.isVisible())
            act.toggled.connect(
                lambda checked, d=dock: self._set_dock_visible(d, checked))
            menu.addAction(act)
        menu.addSeparator()
        a_show_all = QAction("Показать все панели", self)
        a_show_all.triggered.connect(self._show_all_docks)
        menu.addAction(a_show_all)
        a_reset = QAction("Сбросить раскладку", self)
        a_reset.triggered.connect(self._reset_layout)
        menu.addAction(a_reset)

    def _all_docks(self) -> list:
        # Iteration is stable: chat, artifacts, courses (+ future docks).
        # Floating docks are still listed so they can be re-toggled.
        out = []
        for d in (self.chat_dock, self.artifacts_dock,
                  getattr(self, "course_manager_dock", None)):
            if d is not None:
                out.append(d)
        return out

    def _set_dock_visible(self, dock, visible: bool) -> None:
        # When un-hidden, make sure it's attached if it has no area at all
        # (closed floats lose their docking site).
        if visible and self.dockWidgetArea(dock) == Qt.NoDockWidgetArea \
                and not dock.isFloating():
            self.addDockWidget(Qt.RightDockWidgetArea, dock)
        dock.setVisible(visible)
        if visible:
            dock.raise_()

    def _show_all_docks(self) -> None:
        for d in self._all_docks():
            self._set_dock_visible(d, True)

    def _reset_layout(self) -> None:
        """Bring every dock back into its canonical area, not floating."""
        for d in self._all_docks():
            d.setFloating(False)
            d.setVisible(True)
        # Re-pin to canonical sides.
        self.addDockWidget(Qt.LeftDockWidgetArea, self.artifacts_dock)
        self.addDockWidget(Qt.RightDockWidgetArea, self.chat_dock)
        if getattr(self, "course_manager_dock", None) is not None:
            self.addDockWidget(Qt.LeftDockWidgetArea, self.course_manager_dock)
            self.splitDockWidget(self.artifacts_dock, self.course_manager_dock,
                                 Qt.Vertical)
        self.act_detach.blockSignals(True)
        self.act_detach.setChecked(False)
        self.act_detach.blockSignals(False)

    def _save_session_as(self) -> None:
        """Copy the current rolling JSONL to a user-chosen path.

        That single file is the canonical board+chat archive: re-opening
        it through Файл → Открыть сессию replays both panes faithfully.
        """
        if not self._jsonl_path.exists():
            self.statusBar().showMessage("Сессия ещё пуста — нечего сохранять", 4000)
            return
        default = f"session-{Path(self._jsonl_path).stem}.jsonl"
        path_str, _ = QFileDialog.getSaveFileName(
            self, "Сохранить сессию (доска + чат)",
            default, "Session archive (*.jsonl)"
        )
        if not path_str:
            return
        try:
            import shutil
            shutil.copy2(self._jsonl_path, path_str)
            self.statusBar().showMessage(
                f"Сессия сохранена: {path_str}", 5000)
        except Exception as exc:
            QMessageBox.warning(self, "Сохранение",
                                f"Не удалось сохранить: {exc}")

    # ------------------------------------------------------------------
    # Document uploads
    # ------------------------------------------------------------------

    def _on_attach_clicked(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Прикрепить документ", "",
            "Поддерживаемые (*.txt *.md *.pdf *.docx *.py *.js *.ts *.java "
            "*.c *.cpp *.h *.cs *.go *.rs *.rb *.php *.sh *.ps1 *.sql *.yml "
            "*.yaml *.toml *.json *.xml *.html *.css);;All files (*)"
        )
        for p in paths:
            self._load_document(Path(p))

    def _on_clear_documents(self) -> None:
        if not self._docs.list():
            return
        for art in list(self._docs.list()):
            self._remove_artifact(art.id)

    def _load_document(self, path: Path) -> None:
        try:
            doc = doc_reader.load(path)
        except Exception as exc:
            QMessageBox.warning(self, "Документ",
                                f"Не удалось прочитать {path.name}: {exc}")
            return
        art = self._docs.add(doc)
        # Refresh / add list item.
        for i in range(self.artifacts_list.count()):
            it = self.artifacts_list.item(i)
            if it.data(Qt.UserRole) == art.id:
                it.setText(self._artifact_label(art))
                break
        else:
            it = QListWidgetItem(self._artifact_label(art))
            it.setData(Qt.UserRole, art.id)
            it.setToolTip(art.doc.path)
            self.artifacts_list.addItem(it)
        # Push to tutor as LLM context.
        self._commander.document_added(art.id, art.doc.name, art.doc.kind,
                                       art.doc.text)
        # Open the document window immediately.
        self._open_artifact_window(art.id)
        self.statusBar().showMessage(
            f"Прикреплён: {art.doc.name} ({len(art.doc.text)} симв.)", 5000)

    @staticmethod
    def _artifact_label(art) -> str:
        return f"{art.doc.name}    [{art.doc.kind}]"

    def _open_artifact_window(self, doc_id: str) -> None:
        art = self._docs.get(doc_id)
        if art is None:
            return
        win = self._doc_windows.get(doc_id)
        if win is None or not win.isVisible():
            win = DocumentWindow(art.doc, self._bridge, parent=self)
            self._doc_windows[doc_id] = win
        win.show()
        win.raise_()
        win.activateWindow()

    def _remove_artifact(self, doc_id: str) -> None:
        # Close any open window for this doc.
        win = self._doc_windows.pop(doc_id, None)
        if win is not None:
            try:
                win.close()
            except Exception:
                pass
        self._docs.remove(doc_id)
        for i in range(self.artifacts_list.count()):
            if self.artifacts_list.item(i).data(Qt.UserRole) == doc_id:
                self.artifacts_list.takeItem(i)
                break
        self._commander.document_removed(doc_id)

    def _on_artifact_menu(self, pos) -> None:
        item = self.artifacts_list.itemAt(pos)
        if item is None:
            return
        doc_id = item.data(Qt.UserRole)
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background:#181b1a; color:#cfcfcf; "
            "border:1px solid #2a3a2a; }"
            "QMenu::item:selected { background:#2a3a2a; }"
        )
        a_open = menu.addAction("Открыть в окне")
        a_remove = menu.addAction("Удалить из контекста")
        chosen = menu.exec(self.artifacts_list.mapToGlobal(pos))
        if chosen is a_open:
            self._open_artifact_window(doc_id)
        elif chosen is a_remove:
            self._remove_artifact(doc_id)

    # ------------------------------------------------------------------
    # Courses
    # ------------------------------------------------------------------

    def _open_course_builder(self) -> None:
        dlg = CourseBuilderDialog(self)
        dlg.exec()
        # After the dialog closes, refresh the manager + switcher so the
        # new (or untouched) package list is up to date.
        self.course_manager_dock.refresh()

    def _show_course_manager(self) -> None:
        self._set_dock_visible(self.course_manager_dock, True)
        self.course_manager_dock.refresh()

    def _open_connections_settings(self) -> None:
        """Open the LLM provider / API keys dialog. Saving persists to .env;
        the user has to restart the tutor for the new credentials to be
        picked up — the LLM client reads env at process boot."""
        dlg = ConnectionsDialog(self)
        dlg.exec()

    def _on_course_activate(self, path: str) -> None:
        if not path:
            return
        self._commander.load_course(path)
        self.statusBar().showMessage(
            f"Запрошена загрузка курса: {Path(path).name}…", 3000)

    def _init_current_course_label(self) -> None:
        """Read data/current_course.json and seed the switcher label."""
        try:
            cc = _DATA / "current_course.json"
            if not cc.exists():
                return
            data = json.loads(cc.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return
            short = str(data.get("short_name") or data.get("name") or "").strip()
            path = str(data.get("path") or "").strip()
            if short or path:
                self._current_course_path = path
                self.course_switcher.set_current(short, path)
                if path:
                    self.course_manager_dock.set_current(path)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Drag-drop on the whole window
    # ------------------------------------------------------------------

    def dragEnterEvent(self, ev) -> None:
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dragMoveEvent(self, ev) -> None:
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev) -> None:
        if not ev.mimeData().hasUrls():
            return
        for url in ev.mimeData().urls():
            local = url.toLocalFile()
            if local:
                self._load_document(Path(local))
        ev.acceptProposedAction()

    def _stub(self, title: str, body: str) -> None:
        msg = QMessageBox(self)
        msg.setWindowTitle(title)
        msg.setText(f"<b>{title}</b><br><br>{body}<br><br>"
                    "<i>Раздел в разработке — реализуем следующими этапами.</i>")
        msg.setStandardButtons(QMessageBox.Ok)
        msg.setStyleSheet(
            "QMessageBox { background:#181b1a; color:#cfcfcf; }"
            "QPushButton { background:#2a3a2a; color:#fff; border:none; "
            "padding:6px 14px; border-radius:4px; }"
            "QPushButton:hover { background:#3a5a3a; }"
        )
        msg.exec()

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def _export(self, scope: str, fmt: str) -> None:
        """Export the session in one of nine (scope × format) combinations.

        scope: 'board' | 'chat' | 'combined'
        fmt:   'pdf'   | 'html' | 'md'
        """
        scope_name = {"board": "доска", "chat": "чат",
                      "combined": "сессия"}.get(scope, scope)
        default_name = f"{scope}-export.{fmt}"
        filter_ = {
            "pdf":  "PDF (*.pdf)",
            "html": "HTML (*.html *.htm)",
            "md":   "Markdown (*.md)",
        }.get(fmt, "")
        path_str, _ = QFileDialog.getSaveFileName(
            self, f"Сохранить {scope_name} в {fmt.upper()}",
            default_name, filter_)
        if not path_str:
            return
        out_path = Path(path_str)
        try:
            if fmt == "md":
                if scope == "board":
                    n = exporter.export_md_board(self._jsonl_path, out_path)
                elif scope == "chat":
                    n = exporter.export_md_chat(self._jsonl_path, out_path)
                else:
                    n = exporter.export_md_combined(self._jsonl_path, out_path)
                self.statusBar().showMessage(
                    f"Markdown сохранён: {out_path} ({n} элемент(ов))", 5000)
            elif fmt == "html":
                if scope == "board":
                    n = exporter.export_html_board(self._jsonl_path, out_path)
                elif scope == "chat":
                    n = exporter.export_html_chat(self._jsonl_path, out_path)
                else:
                    n = exporter.export_html_combined(self._jsonl_path, out_path)
                self.statusBar().showMessage(
                    f"HTML сохранён: {out_path} ({n} элемент(ов))", 5000)
            elif fmt == "pdf":
                if scope == "combined":
                    self.statusBar().showMessage(
                        "Готовлю PDF (доска + чат)…", 3000)
                    exporter.export_pdf_combined(
                        self._jsonl_path, out_path,
                        on_done=self._on_export_done)
                else:
                    view = (self.board_view if scope == "board"
                            else self.chat_pane.view)
                    exporter.export_pdf(view, out_path,
                                        on_done=self._on_export_done)
        except Exception as exc:
            self.statusBar().showMessage(f"экспорт упал: {exc}", 5000)

    def _on_export_done(self, path: Path, ok: bool) -> None:
        msg = f"PDF сохранён: {path}" if ok else f"PDF НЕ сохранён: {path}"
        self.statusBar().showMessage(msg, 5000)

    def _import_session(self, fmt: str) -> None:
        """Import a previously-exported HTML / Markdown session and replay
        it onto the live board + chat panes. PDF is not supported (read-only
        rasterised content). The imported events overwrite the live view
        but DO NOT touch the underlying JSONL — close & reopen the live
        session to return."""
        filter_ = {"html": "HTML (*.html *.htm)",
                   "md":   "Markdown (*.md)"}.get(fmt, "")
        path_str, _ = QFileDialog.getOpenFileName(
            self, f"Открыть сессию из {fmt.upper()}", "", filter_)
        if not path_str:
            return
        path = Path(path_str)
        try:
            from board import importer as _importer
            events = (_importer.parse_html(path) if fmt == "html"
                      else _importer.parse_markdown(path))
        except Exception as exc:
            QMessageBox.warning(
                self, "Импорт не удался",
                f"{type(exc).__name__}: {exc}\n\nФайл: {path}")
            return
        if not events:
            self.statusBar().showMessage(
                f"В файле ничего не найдено: {path}", 4000)
            return
        # Clear panes and replay.
        self.board_view.page().runJavaScript("clearBoard();")
        self.chat_pane.view.page().runJavaScript("clearChat();")
        self._last_board_ref_seq = None
        # Stop the live tail so further runtime events don't mix with the
        # imported snapshot. The user can return via "Вернуться к текущей".
        if self.tail is not None:
            try:
                self.tail.stop_tail()
            except Exception:
                pass
        for ev in events:
            self._dispatch(ev)
        self.statusBar().showMessage(
            f"Импортировано: {len(events)} событий из {path.name}", 6000)

    # ------------------------------------------------------------------

    def closeEvent(self, ev) -> None:
        if self.tail is not None:
            self.tail.stop_tail()
            self.tail.wait(2000)
        super().closeEvent(ev)
