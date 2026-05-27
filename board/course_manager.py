"""Course Manager dock: list of prepared RAG packages.

Lists every directory under courses/ (and a couple of fallback roots) that
contains a course_config.yml. Lets the user activate / delete / open the
package, export a course as a single .zip for sharing, import one back,
or kick off the Builder for a new one. A preview pane on the right shows
metadata + the first chunk of corpus text for the selected course.

Activation does not happen here directly — it emits ``activate_requested``
so the main window can send ``BoardCommander.load_course(path)``.
"""
from __future__ import annotations

import html as html_mod
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QFont, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView, QDockWidget, QFileDialog, QHeaderView, QMessageBox,
    QSplitter, QTableView, QTextBrowser, QToolBar, QVBoxLayout, QWidget,
)

from board.courses_scan import CourseEntry, read_course_yaml, scan_courses

_REPO_ROOT = Path(__file__).resolve().parent.parent
_COURSES_DIR = _REPO_ROOT / "courses"
_TEXT_EXTS = (".md", ".markdown", ".txt")


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
            "border-radius:4px; font-size:14px; }"
            "QToolButton:hover { background:#2a3a2a; color:#fff; }"
        )
        a_new = QAction("Подготовить новый…", self)
        a_new.triggered.connect(self.build_requested)
        a_activate = QAction("Активировать", self)
        a_activate.triggered.connect(self._on_activate)
        a_export = QAction("Экспорт…", self)
        a_export.triggered.connect(self.export_selected)
        a_import = QAction("Импорт из .zip…", self)
        a_import.triggered.connect(self.import_zip)
        a_delete = QAction("Удалить", self)
        a_delete.triggered.connect(self._on_delete)
        a_open = QAction("В проводнике", self)
        a_open.triggered.connect(self._on_open_folder)
        a_refresh = QAction("Обновить", self)
        a_refresh.triggered.connect(self.refresh)
        for a in (a_new, a_activate, a_export, a_import, a_delete, a_open, a_refresh):
            tb.addAction(a)
        layout.addWidget(tb)

        # Split: table | preview
        splitter = QSplitter(Qt.Horizontal)

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
        self._view.selectionModel().currentRowChanged.connect(
            lambda _cur, _prev: self._refresh_preview()
        )
        splitter.addWidget(self._view)

        # Preview
        self._preview = QTextBrowser()
        self._preview.setOpenExternalLinks(False)
        self._preview.setStyleSheet(
            "QTextBrowser { background:#0d1110; color:#cfcfcf; "
            "border:0; padding:8px 10px; font-size:14px; }"
        )
        self._preview.setHtml(self._empty_preview_html())
        splitter.addWidget(self._preview)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        layout.addWidget(splitter)
        self._splitter = splitter

        self.setWidget(body)

        # Width threshold: hide preview pane when the dock is narrow,
        # show it again once the user widens it. Picked from feedback —
        # below ~480 px the preview eats space that should go to the
        # course table's columns.
        self._preview_min_width = 480

        # Initial scan
        self.refresh()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_preview") and hasattr(self, "_preview_min_width"):
            wide_enough = self.width() >= self._preview_min_width
            if self._preview.isVisible() != wide_enough:
                self._preview.setVisible(wide_enough)

    # ------------------------------------------------------------------

    def refresh(self) -> None:
        entries = scan_courses()
        self._model.set_entries(entries)
        self._refresh_preview()

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

    # ------------------------------------------------------------------
    # Export / import
    # ------------------------------------------------------------------

    def export_selected(self) -> None:
        """Pack the selected course directory into a single .zip the user
        picks via a save dialog. Internal layout inside the archive uses
        the course's short_name as the top-level folder."""
        row = self._selected_row()
        path = self._model.path_at(row)
        short = self._model.short_at(row)
        if not path:
            QMessageBox.information(
                self, "Экспорт", "Сначала выбери курс в списке.")
            return
        src = Path(path)
        if not src.is_dir():
            QMessageBox.warning(self, "Экспорт",
                                f"Папка курса не найдена:\n{src}")
            return
        default_name = (short or src.name) + ".zip"
        default_path = str(Path.home() / "Desktop" / default_name)
        zip_path, _ = QFileDialog.getSaveFileName(
            self, "Куда сохранить курс", default_path, "ZIP (*.zip)")
        if not zip_path:
            return
        try:
            self._zip_directory(src, Path(zip_path),
                                top_folder=short or src.name)
        except Exception as exc:
            QMessageBox.warning(self, "Не удалось упаковать",
                                f"{type(exc).__name__}: {exc}")
            return
        QMessageBox.information(
            self, "Экспорт",
            f"Курс «{short}» сохранён в:\n{zip_path}")

    def import_zip(self) -> None:
        """Read a course .zip and unpack into courses/<short_name>/.

        The archive must contain exactly one course_config.yml — any path
        depth is fine (we use the directory of that yaml as the package
        root). short_name is read from the yaml; if absent, the archive's
        own folder name is used."""
        zip_path, _ = QFileDialog.getOpenFileName(
            self, "Импортировать курс", str(Path.home()), "ZIP (*.zip)")
        if not zip_path:
            return
        try:
            short, dest = self._unzip_course(Path(zip_path), _COURSES_DIR, self)
        except _ImportAborted:
            return
        except Exception as exc:
            QMessageBox.warning(self, "Не удалось импортировать",
                                f"{type(exc).__name__}: {exc}")
            return
        self.refresh()
        QMessageBox.information(
            self, "Импорт",
            f"Курс «{short}» распакован в:\n{dest}\n\n"
            "Активируй его двойным кликом или из меню «Курсы»."
        )

    # ------------------------------------------------------------------
    # Preview
    # ------------------------------------------------------------------

    @staticmethod
    def _empty_preview_html() -> str:
        return ('<div style="color:#666;font-style:italic;">'
                'Выбери курс в списке, чтобы увидеть описание и начало '
                'корпуса.</div>')

    def _refresh_preview(self) -> None:
        row = self._selected_row()
        path = self._model.path_at(row)
        if not path:
            self._preview.setHtml(self._empty_preview_html())
            return
        try:
            html = self._build_preview_html(Path(path))
        except Exception as exc:
            html = (f'<div style="color:#a05858;">Не удалось прочитать '
                    f'описание: {html_mod.escape(type(exc).__name__)}: '
                    f'{html_mod.escape(str(exc))}</div>')
        self._preview.setHtml(html)

    def _build_preview_html(self, course_dir: Path) -> str:
        yml = course_dir / "course_config.yml"
        cfg = read_course_yaml(yml) if yml.exists() else {}
        course = cfg.get("course") if isinstance(cfg.get("course"), dict) else {}
        persona = cfg.get("persona") if isinstance(cfg.get("persona"), dict) else {}

        def _esc(v) -> str:
            return html_mod.escape(str(v).strip()) if v else ""

        name = _esc(course.get("name") or cfg.get("name") or course_dir.name)
        short = _esc(course.get("short_name") or cfg.get("short_name") or "")
        topic = _esc(course.get("topic") or cfg.get("topic") or "")
        audience = _esc(course.get("audience") or "")
        style = _esc(persona.get("teaching_style") or
                     course.get("teaching_style") or "")
        keywords_raw = cfg.get("example_keywords") or course.get("example_keywords")
        if isinstance(keywords_raw, list):
            keywords = ", ".join(_esc(k) for k in keywords_raw if k)
        else:
            keywords = _esc(keywords_raw or "")

        # Find the first sizeable text file for a corpus preview.
        sample = ""
        sample_name = ""
        for ext in _TEXT_EXTS:
            for f in sorted(course_dir.rglob(f"*{ext}")):
                try:
                    text = f.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue
                if len(text.strip()) < 50:
                    continue
                sample = text.strip()[:500]
                sample_name = f.name
                break
            if sample:
                break

        parts = [f'<h3 style="color:#ebebeb;margin:0 0 8px 0;">{name}</h3>']
        if short:
            parts.append(f'<p><strong>Краткое имя:</strong> {short}</p>')
        if topic:
            parts.append(f'<p><strong>Тема:</strong> {topic}</p>')
        if audience:
            parts.append(f'<p><strong>Аудитория:</strong> {audience}</p>')
        if style:
            short_style = style if len(style) <= 280 else style[:280] + "…"
            parts.append(f'<p><strong>Стиль:</strong> {short_style}</p>')
        if keywords:
            parts.append(f'<p><strong>Ключевые слова:</strong> {keywords}</p>')
        if sample:
            parts.append(
                f'<hr style="border:0;border-top:1px solid #2a3a2a;'
                f'margin:10px 0;">'
                f'<p style="color:#888;font-size:13px;">Начало корпуса '
                f'({html_mod.escape(sample_name)}):</p>'
                f'<pre style="white-space:pre-wrap;color:#cfcfcf;'
                f'font-size:13px;">{html_mod.escape(sample)}</pre>'
            )
        return "".join(parts)

    # ------------------------------------------------------------------
    # Static archive helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _zip_directory(src: Path, zip_path: Path, top_folder: str) -> None:
        """Write every file under ``src`` into ``zip_path`` with arcnames
        rooted at ``top_folder/...``."""
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in src.rglob("*"):
                if f.is_dir():
                    continue
                arc = Path(top_folder) / f.relative_to(src)
                zf.write(f, arcname=str(arc).replace("\\", "/"))

    @staticmethod
    def _unzip_course(zip_path: Path, dest_root: Path,
                      parent: QWidget) -> tuple[str, Path]:
        """Unzip into ``dest_root/<short_name>/``.

        Returns ``(short_name, dest_path)``. Raises ``_ImportAborted`` if the
        user declines to overwrite an existing destination. Other errors
        propagate to the caller, which surfaces them via QMessageBox.
        """
        if not zipfile.is_zipfile(zip_path):
            raise ValueError("Файл не является ZIP-архивом.")
        with zipfile.ZipFile(zip_path, "r") as zf:
            members = zf.namelist()
            ymls = [m for m in members
                    if m.endswith("course_config.yml")
                    and not m.startswith("__MACOSX/")]
            if not ymls:
                raise ValueError(
                    "В архиве нет course_config.yml — это не пакет курса.")
            if len(ymls) > 1:
                # Use the shallowest one (least number of path components).
                ymls.sort(key=lambda p: p.count("/"))
            yml_member = ymls[0]
            # Root of the package inside the archive.
            root_in_zip = yml_member.rsplit("/", 1)[0] if "/" in yml_member else ""

            # Read short_name from the yaml in the archive.
            try:
                import yaml as _yaml
                with zf.open(yml_member) as f:
                    cfg = _yaml.safe_load(f.read().decode("utf-8")) or {}
            except Exception:
                cfg = {}
            course = cfg.get("course") if isinstance(cfg.get("course"), dict) else {}
            short = (course.get("short_name") or cfg.get("short_name")
                     or course.get("name") or cfg.get("name")
                     or (root_in_zip.split("/")[-1] if root_in_zip
                         else zip_path.stem)).strip() or zip_path.stem

            dest = (dest_root / short).resolve()
            try:
                dest.relative_to(dest_root.resolve())
            except ValueError:
                raise ValueError(
                    "Имя короткого курса делает путь выходящим за courses/.")

            if dest.exists():
                ans = QMessageBox.question(
                    parent, "Курс уже существует",
                    f"Курс «{short}» уже есть в:\n{dest}\n\n"
                    "Перезаписать содержимое? Старый контент будет удалён.",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
                )
                if ans != QMessageBox.Yes:
                    raise _ImportAborted
                shutil.rmtree(dest)
            dest.mkdir(parents=True, exist_ok=True)

            # Extract only files belonging to the detected root.
            for m in members:
                if m.endswith("/") or m.startswith("__MACOSX/"):
                    continue
                if root_in_zip and not m.startswith(root_in_zip + "/"):
                    if m != yml_member:
                        continue
                rel = (m[len(root_in_zip) + 1:] if root_in_zip
                       else m)
                if not rel:
                    continue
                # Resolve target safely (no .. escapes).
                target = (dest / rel).resolve()
                try:
                    target.relative_to(dest)
                except ValueError:
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(m) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)

        return short, dest


class _ImportAborted(Exception):
    """User declined to overwrite an existing destination."""
