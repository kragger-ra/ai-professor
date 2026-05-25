"""Quick course switcher for the toolbar.

Compact pill-styled QToolButton with a dropdown menu listing every detected
course package. The currently active course is marked with a checkmark and
shown on the button label so a newcomer can see at a glance which corpus
the tutor is using.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QMenu, QSizePolicy, QToolButton, QWidget,
)

from board.courses_scan import scan_courses


_BTN_STYLE = (
    "QToolButton { color:#dbe7db; background:#1c2620; "
    "border:1px solid #3a5a3a; border-radius:11px; "
    "padding:3px 12px; font-size:12px; min-height:18px; }"
    "QToolButton:hover { background:#26362a; border-color:#5a7a5a; }"
    "QToolButton::menu-indicator { width:10px; }"
)


class CourseQuickSwitcher(QWidget):

    course_chosen = Signal(str)        # path
    build_requested = Signal()
    manager_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)

        row = QHBoxLayout(self)
        row.setContentsMargins(4, 0, 4, 0)
        row.setSpacing(6)

        self._label = QLabel("Курс:")
        self._label.setStyleSheet("color:#9ab59a; font-size:12px;")
        row.addWidget(self._label)

        self._button = QToolButton(self)
        self._button.setText("не выбран")
        self._button.setPopupMode(QToolButton.MenuButtonPopup)
        self._button.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self._button.setToolTip("Текущий курс RAG (клик — выбор из списка)")
        self._button.setStyleSheet(_BTN_STYLE)
        self._menu = QMenu(self._button)
        self._menu.aboutToShow.connect(self._rebuild_menu)
        self._button.setMenu(self._menu)
        # Clicking the button itself opens the menu too (no default action).
        self._button.clicked.connect(self._button.showMenu)
        row.addWidget(self._button)

        self._current_path: str = ""

    # ------------------------------------------------------------------

    def set_current(self, short_name: str, path: str) -> None:
        self._current_path = path or ""
        label = (short_name or "").strip() or "не выбран"
        self._button.setText(label)

    # ------------------------------------------------------------------

    def _rebuild_menu(self) -> None:
        self._menu.clear()
        entries = scan_courses()
        if entries:
            for e in entries:
                act = self._menu.addAction(e.short_name)
                act.setCheckable(True)
                if e.path == self._current_path:
                    act.setChecked(True)
                act.setToolTip(e.name or e.short_name)
                act.triggered.connect(
                    lambda _checked=False, path=e.path: self.course_chosen.emit(path)
                )
        else:
            empty = self._menu.addAction("(нет подготовленных курсов)")
            empty.setEnabled(False)
        self._menu.addSeparator()
        act_new = self._menu.addAction("Подготовить новый…")
        act_new.triggered.connect(self.build_requested)
        act_mgr = self._menu.addAction("Открыть менеджер курсов")
        act_mgr.triggered.connect(self.manager_requested)
