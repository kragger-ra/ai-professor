"""Course Manager dock: list of prepared RAG packages.

Lists every directory under courses/ (and a couple of fallback roots) that
contains a course_config.yml. Lets the user activate / delete / open the
package or kick off the Builder for a new one.

Activation does not happen here directly — it emits ``activate_requested``
so the main window can send ``BoardCommander.load_course(path)``.
"""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QFont, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView, QDockWidget, QHeaderView, QMessageBox, QTableView,
    QToolBar, QVBoxLayout, QWidget,
)

from board.courses_scan import CourseEntry, scan_courses

_REPO_ROOT = Path(__file__).resolve().parent.parent
_COURSES_DIR = _REPO_ROOT / "courses"


class CourseTableModel(QStandardItemModel):
    """5-column model: ● / short_name / name / файлов / дата."""

    HEADERS = ("●", "Краткое имя", "Название", "Файлов", "Собран")

    def __init__(self, parent=None) -> None:
        super().__init__(0, len(self.HEADERS), parent)
        self.setHorizontalHeaderLabels(self.HEADERS)
        self._current_path: str = ""

    def set_entries(self, entries: list[CourseEntry]) -> None:
        self.removeRows(0, self.rowCount())
        bold = QFont()
        bold.setBold(True)
        for e in entries:
            is_active = (e.path == self._current_path)
            cells = [
                "●" if is_active else "",
                e.short_name,
                e.name,
                str(e.files_count),
                self._fmt_mtime(e.mtime),
            ]
            row = []
            for text in cells:
                it = QStandardItem(text)
                it.setEditable(False)
                if is_active:
                    it.setFont(bold)
                row.append(it)
            # Stash the package path on column 0 for retrieval.
            row[0].setData(e.path, Qt.UserRole)
            self.appendRow(row)

    def path_at(self, row: int) -> str:
        if row < 0 or row >= self.rowCount():
            return ""
        item = self.item(row, 0)
        return item.data(Qt.UserRole) if item else ""

    def short_at(self, row: int) -> str:
        if row < 0 or row >= self.rowCount():
            return ""
        item = self.item(row, 1)
        return item.text() if item else ""

    def set_current(self, path: str) -> None:
        self._current_path = path or ""

    @staticmethod
    def _fmt_mtime(mtime: float) -> str:
        if not mtime:
            return ""
        try:
            return datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return ""


class CourseManagerDock(QDockWidget):

    activate_requested = Signal(str)     # absolute package path
    build_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Курсы", parent)
        self.setObjectName("course_manager_dock")
        self.setAllowedAreas(Qt.AllDockWidgetAreas)

        body = QWidget(self)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Toolbar
        tb = QToolBar()
        tb.setIconSize(QSize(16, 16))
        tb.setStyleSheet(
            "QToolBar { background:#15191a; border:0; "
            "border-bottom:1px solid #2a3a2a; padding:4px 6px; spacing:4px; }"
            "QToolButton { color:#cfcfcf; background:transparent; "
            "border:1px solid transparent; padding:4px 10px; "
            "border-radius:4px; font-size:12px; }"
            "QToolButton:hover { background:#2a3a2a; color:#fff; }"
        )
        a_new = QAction("Подготовить новый…", self)
        a_new.triggered.connect(self.build_requested)
        a_activate = QAction("Активировать", self)
        a_activate.triggered.connect(self._on_activate)
        a_delete = QAction("Удалить", self)
        a_delete.triggered.connect(self._on_delete)
        a_open = QAction("Открыть в проводнике", self)
        a_open.triggered.connect(self._on_open_folder)
        a_refresh = QAction("Обновить", self)
        a_refresh.triggered.connect(self.refresh)
        for a in (a_new, a_activate, a_delete, a_open, a_refresh):
            tb.addAction(a)
        layout.addWidget(tb)

        # Table
        self._model = CourseTableModel(self)
        self._view = QTableView()
        self._view.setModel(self._model)
        self._view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._view.setSelectionMode(QAbstractItemView.SingleSelection)
        self._view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._view.verticalHeader().setVisible(False)
        self._view.setAlternatingRowColors(True)
        self._view.setStyleSheet(
            "QTableView { background:#0d1110; color:#ebebeb; "
            "gridline-color:#1f2422; alternate-background-color:#11161a; "
            "selection-background-color:#264026; }"
            "QHeaderView::section { background:#15191a; color:#cfcfcf; "
            "padding:4px; border:0; border-bottom:1px solid #2a3a2a; }"
        )
        header = self._view.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self._view.doubleClicked.connect(lambda _idx: self._on_activate())
        layout.addWidget(self._view)

        self.setWidget(body)

        # Initial scan
        self.refresh()

    # ------------------------------------------------------------------

    def refresh(self) -> None:
        entries = scan_courses()
        self._model.set_entries(entries)

    def set_current(self, path: str) -> None:
        self._model.set_current(path or "")
        self.refresh()

    # ------------------------------------------------------------------

    def _selected_row(self) -> int:
        idx = self._view.currentIndex()
        return idx.row() if idx.isValid() else -1

    def _on_activate(self) -> None:
        row = self._selected_row()
        path = self._model.path_at(row)
        if path:
            self.activate_requested.emit(path)

    def _on_open_folder(self) -> None:
        row = self._selected_row()
        path = self._model.path_at(row)
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _on_delete(self) -> None:
        row = self._selected_row()
        path = self._model.path_at(row)
        short = self._model.short_at(row)
        if not path:
            return
        target = Path(path).resolve()
        try:
            target.relative_to(_COURSES_DIR.resolve())
        except ValueError:
            QMessageBox.warning(
                self, "Удаление запрещено",
                "Можно удалять только курсы из папки courses/. "
                f"Этот пакет лежит снаружи: {target}",
            )
            return
        ans = QMessageBox.question(
            self, "Удалить курс",
            f"Удалить курс «{short}» и все его файлы?\n\n{target}",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if ans != QMessageBox.Yes:
            return
        try:
            shutil.rmtree(target)
        except Exception as exc:
            QMessageBox.warning(self, "Не удалось удалить",
                                f"{type(exc).__name__}: {exc}")
            return
        self.refresh()
