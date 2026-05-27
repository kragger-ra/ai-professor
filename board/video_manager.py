"""Video Manager dock + background transcription worker.

The dock lists every video registered in ``data/videos/registry.json``
(see :mod:`tutor.video_store`) and provides toolbar actions for removing
entries, opening the storage folder, and refreshing the list. Loading a
new video is initiated from the menu (``Видеоматериалы → Загрузить
видео…``) — the worker runs Faster-Whisper off the UI thread and a
progress dialog mirrors its updates.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QFont, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView, QDockWidget, QHeaderView, QMessageBox, QTableView,
    QToolBar, QVBoxLayout, QWidget,
)

from tutor.video_store import VideoStore


def _fmt_duration(seconds: float) -> str:
    if not seconds or seconds <= 0:
        return "—"
    m, s = divmod(int(seconds), 60)
    if m < 60:
        return f"{m}:{s:02d}"
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}"


class TranscribeWorker(QThread):
    """Run :func:`transcribe_video` on a background thread and emit
    progress + completion signals to the Qt main thread. The worker
    owns its own VideoStore reference so it can register the result
    before signalling done."""

    progress = Signal(float, str)
    done = Signal(object)            # VideoEntry on success, Exception on failure

    def __init__(self, video_path: Path, language: str = "ru",
                 device: str | None = None, parent=None) -> None:
        super().__init__(parent)
        self.video_path = video_path
        self.language = language
        self.device = device

    def run(self) -> None:
        try:
            from tutor.audio.video_transcribe import transcribe_video
            segments = transcribe_video(
                self.video_path,
                language=self.language,
                device=self.device,
                on_progress=lambda f, t: self.progress.emit(f, t),
            )
            entry = VideoStore().register_transcribed(self.video_path, segments)
            self.done.emit(entry)
        except Exception as exc:
            self.done.emit(exc)


class _Model(QStandardItemModel):
    HEADERS = ("Файл", "Длительность", "Сегментов", "Добавлен")

    def __init__(self, parent=None) -> None:
        super().__init__(0, len(self.HEADERS), parent)
        self.setHorizontalHeaderLabels(self.HEADERS)

    def set_entries(self, entries) -> None:
        self.removeRows(0, self.rowCount())
        for e in entries:
            mtime = self._fmt_mtime(Path(e.transcript_path)
                                    if e.transcript_path else None)
            cells = [e.name, _fmt_duration(e.duration_s),
                     str(e.segments_count), mtime]
            row = []
            for text in cells:
                it = QStandardItem(text)
                it.setEditable(False)
                row.append(it)
            row[0].setData(e.video_id, Qt.UserRole)
            self.appendRow(row)

    def video_id_at(self, row: int) -> str:
        if row < 0 or row >= self.rowCount():
            return ""
        it = self.item(row, 0)
        return (it.data(Qt.UserRole) if it else "") or ""

    @staticmethod
    def _fmt_mtime(path) -> str:
        if not path:
            return ""
        try:
            return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return ""


class VideoManagerDock(QDockWidget):
    """Right-side dock listing transcribed videos."""

    open_folder_requested = Signal(str)   # storage path

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Видеоматериалы", parent)
        self.setObjectName("video_manager_dock")
        self.setAllowedAreas(Qt.AllDockWidgetAreas)

        body = QWidget(self)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        tb = QToolBar()
        tb.setIconSize(QSize(16, 16))
        tb.setStyleSheet(
            "QToolBar { background:#15191a; border:0; "
            "border-bottom:1px solid #2a3a2a; padding:4px 6px; spacing:4px; }"
            "QToolButton { color:#cfcfcf; background:transparent; "
            "border:1px solid transparent; padding:4px 10px; "
            "border-radius:4px; font-size:13px; }"
            "QToolButton:hover { background:#2a3a2a; color:#fff; }"
        )
        a_refresh = QAction("Обновить", self)
        a_refresh.triggered.connect(self.refresh)
        a_open = QAction("В проводнике", self)
        a_open.triggered.connect(self._on_open_folder)
        a_delete = QAction("Удалить", self)
        a_delete.triggered.connect(self._on_delete)
        for a in (a_refresh, a_open, a_delete):
            tb.addAction(a)
        layout.addWidget(tb)

        self._model = _Model(self)
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
            "selection-background-color:#264026; font-size:13px; }"
            "QHeaderView::section { background:#15191a; color:#cfcfcf; "
            "padding:4px; border:0; border-bottom:1px solid #2a3a2a; }"
        )
        header = self._view.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self._view.doubleClicked.connect(lambda _i: self._on_open_folder())
        layout.addWidget(self._view)

        self.setWidget(body)
        self.refresh()

    # ------------------------------------------------------------------

    def refresh(self) -> None:
        entries = VideoStore().list()
        self._model.set_entries(entries)

    def _selected_video_id(self) -> str:
        idx = self._view.currentIndex()
        return self._model.video_id_at(idx.row()) if idx.isValid() else ""

    def _on_open_folder(self) -> None:
        vid = self._selected_video_id()
        if not vid:
            return
        entry = VideoStore().get(vid)
        if entry is None:
            return
        folder = Path(entry.stored_path).parent
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _on_delete(self) -> None:
        vid = self._selected_video_id()
        if not vid:
            return
        entry = VideoStore().get(vid)
        if entry is None:
            return
        ans = QMessageBox.question(
            self, "Удалить видео",
            f"Удалить запись «{entry.name}» из реестра и стереть файлы "
            f"({entry.stored_path}, {entry.transcript_path})?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if ans != QMessageBox.Yes:
            return
        VideoStore().remove(vid, delete_files=True)
        self.refresh()
