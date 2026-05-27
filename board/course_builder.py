"""Course Builder dialog and background worker.

Packs a heterogeneous set of source files (PDF/DOCX/MD/TXT/code) into a
RAG package directory the tutor can hot-swap with rag.reload_from_path().

Pipeline (in BuildWorker):
    for each input file
        text = doc_reader.load(path).text
        if not text: skip with warning
        write text to <target>/<slug(stem)>.md
    write course_config.yml
    run a sanity-split via CustomTripleNewLineSplitter to estimate chunks

No FAISS indexing here — the tutor builds the index on first activation
(rag.reload_from_path is hot-swap-friendly).
"""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from board import doc_reader

try:
    import yaml  # type: ignore
except ImportError:    # pragma: no cover — surfaced via UI
    yaml = None


_SUPPORTED_EXTS = {".pdf", ".docx", ".md", ".markdown", ".txt"}
_REPO_ROOT = Path(__file__).resolve().parent.parent
_COURSES_ROOT = _REPO_ROOT / "courses"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slugify(name: str) -> str:
    """Lat/cyr/digit/_/- only; trims to 40 chars; falls back to 'course'."""
    s = name.strip().lower()
    s = re.sub(r"[\s/\\]+", "_", s)
    s = re.sub(r"[^a-zа-я0-9_\-]+", "", s, flags=re.IGNORECASE)
    s = s.strip("_-")[:40]
    return s or "course"


_SHORT_RE = re.compile(r"^[A-Za-zА-Яа-яЁё0-9_\-]{2,40}$")


def _validate_short_name(s: str) -> bool:
    return bool(_SHORT_RE.match(s.strip()))


def _supported_files_under(root: Path) -> list[Path]:
    out: list[Path] = []
    if root.is_file():
        if root.suffix.lower() in _SUPPORTED_EXTS:
            out.append(root.resolve())
        return out
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in _SUPPORTED_EXTS:
            out.append(p.resolve())
    return out


def _unique_target(target_dir: Path, stem: str, ext: str = ".md") -> Path:
    """Return a non-existing path inside target_dir based on stem + ext."""
    candidate = target_dir / f"{stem}{ext}"
    if not candidate.exists():
        return candidate
    n = 2
    while True:
        candidate = target_dir / f"{stem}_{n}{ext}"
        if not candidate.exists():
            return candidate
        n += 1


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

@dataclass
class BuildInputs:
    files: list[Path]
    target_dir: Path
    course_name: str
    course_topic: str
    short_name: str
    audience: str
    teaching_style: str
    overwrite: bool          # True = wipe target_dir first; False = append


class BuildWorker(QThread):
    progress = Signal(int, str)       # percent (0..100), short status
    log_line = Signal(str)
    finished_ok = Signal(str, int)    # target_dir, estimated_chunks
    failed = Signal(str)

    def __init__(self, inputs: BuildInputs, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._in = inputs

    # ------------------------------------------------------------------

    def run(self) -> None:    # noqa: D401 — Qt convention
        try:
            self._run()
        except Exception as exc:    # pragma: no cover — defensive
            self.failed.emit(f"{type(exc).__name__}: {exc}")

    def _run(self) -> None:
        if yaml is None:
            self.failed.emit("PyYAML не установлен; установи: pip install pyyaml")
            return

        inputs = self._in
        target = inputs.target_dir

        # Prepare target directory (overwrite or append, decided by UI).
        if inputs.overwrite and target.exists():
            try:
                shutil.rmtree(target)
            except Exception as exc:
                self.failed.emit(f"Не удалось очистить {target}: {exc}")
                return
        try:
            target.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            self.failed.emit(f"Не удалось создать {target}: {exc}")
            return

        # 1) Parse every input file into .md inside the package.
        total = max(1, len(inputs.files))
        written = 0
        skipped: list[str] = []
        for idx, src in enumerate(inputs.files, 1):
            if self.isInterruptionRequested():
                self.failed.emit("Прервано пользователем.")
                return
            pct = int(idx / total * 80)
            self.progress.emit(pct, f"Парсю {src.name}…")
            try:
                doc = doc_reader.load(src)
            except Exception as exc:
                self.log_line.emit(f"[!] {src.name}: ошибка чтения "
                                   f"({type(exc).__name__}: {exc})")
                skipped.append(src.name)
                continue
            text = (doc.text or "").strip()
            if not text:
                self.log_line.emit(f"[!] {src.name}: 0 символов, пропущен")
                skipped.append(src.name)
                continue

            ext = src.suffix.lower()
            stem = _slugify(src.stem) or "doc"
            if ext in (".md", ".markdown", ".txt"):
                target_path = _unique_target(target, stem, ".md")
                payload = text
            else:
                # PDF / DOCX / code → wrap with a header so chunking has anchors.
                target_path = _unique_target(target, stem, ".md")
                payload = f"# {src.stem}\n\n{text}\n"
            try:
                target_path.write_text(payload, encoding="utf-8")
            except Exception as exc:
                self.log_line.emit(f"[!] {src.name}: запись не удалась "
                                   f"({type(exc).__name__}: {exc})")
                skipped.append(src.name)
                continue
            self.log_line.emit(
                f"  {src.name}  ->  {target_path.name}  "
                f"({len(text)} симв.)"
            )
            written += 1

        if written == 0:
            self.failed.emit(
                "Не удалось извлечь текст ни из одного файла. "
                "Возможно, PDF — это скан без текстового слоя."
            )
            return

        # 2) Write course_config.yml
        self.progress.emit(85, "Пишу course_config.yml…")
        cfg = {
            "course": {
                "name":       inputs.course_name,
                "topic":      inputs.course_topic,
                "short_name": inputs.short_name,
                "audience":   inputs.audience,
            },
            "persona": {
                "teaching_style": inputs.teaching_style,
            },
        }
        try:
            with open(target / "course_config.yml", "w", encoding="utf-8") as f:
                yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
        except Exception as exc:
            self.failed.emit(f"Не удалось записать course_config.yml: {exc}")
            return

        # 3) Sanity-split estimate
        self.progress.emit(92, "Оцениваю чанки…")
        chunks_total = self._estimate_chunks(target)
        if chunks_total is not None:
            self.log_line.emit(f"Оценка чанков: ~{chunks_total}")
        if skipped:
            self.log_line.emit(f"Пропущено файлов: {len(skipped)}")

        self.progress.emit(100, "Готово")
        self.finished_ok.emit(str(target), chunks_total or 0)

    # ------------------------------------------------------------------

    def _estimate_chunks(self, target: Path) -> int | None:
        try:
            from tutor.brain.rag import CustomTripleNewLineSplitter  # type: ignore
        except Exception as exc:
            self.log_line.emit(f"(сплиттер недоступен: {exc})")
            return None
        splitter = CustomTripleNewLineSplitter(chunk_size=1000, chunk_overlap=0)
        total = 0
        for md in target.rglob("*.md"):
            try:
                text = md.read_text(encoding="utf-8")
            except Exception:
                continue
            total += len(splitter.split_text(text))
        return total


# ---------------------------------------------------------------------------
# File tree widget with drag-drop
# ---------------------------------------------------------------------------

class _FileTree(QTreeWidget):

    files_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setColumnCount(3)
        self.setHeaderLabels(["Файл", "Тип", "Путь"])
        self.setAcceptDrops(True)
        self.setRootIsDecorated(False)
        self.setUniformRowHeights(True)
        self.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.header().setSectionResizeMode(2, QHeaderView.Stretch)
        self._paths: set[str] = set()

    # ---- drag-drop ---------------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        if not event.mimeData().hasUrls():
            super().dropEvent(event)
            return
        added = 0
        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if not local:
                continue
            added += self._add_path(Path(local))
        if added:
            self.files_changed.emit()
        event.acceptProposedAction()

    # ---- public api --------------------------------------------------

    def add_paths(self, paths: list[Path]) -> int:
        added = 0
        for p in paths:
            added += self._add_path(p)
        if added:
            self.files_changed.emit()
        return added

    def remove_selected(self) -> None:
        changed = False
        for item in self.selectedItems():
            key = item.data(0, Qt.UserRole)
            if key and key in self._paths:
                self._paths.discard(key)
                changed = True
            idx = self.indexOfTopLevelItem(item)
            if idx >= 0:
                self.takeTopLevelItem(idx)
        if changed:
            self.files_changed.emit()

    def clear_all(self) -> None:
        if not self._paths:
            return
        self._paths.clear()
        self.clear()
        self.files_changed.emit()

    def collected_paths(self) -> list[Path]:
        return [Path(p) for p in sorted(self._paths)]

    # ---- internals ---------------------------------------------------

    def _add_path(self, p: Path) -> int:
        added = 0
        for f in _supported_files_under(p):
            key = str(f.resolve())
            if key in self._paths:
                continue
            self._paths.add(key)
            item = QTreeWidgetItem([f.name, f.suffix.lstrip(".").upper(), key])
            item.setData(0, Qt.UserRole, key)
            self.addTopLevelItem(item)
            added += 1
        return added


# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------

class CourseBuilderDialog(QDialog):

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Подготовить RAG-пакет курса")
        self.resize(820, 640)
        self.setSizeGripEnabled(True)

        self._worker: BuildWorker | None = None
        self._build_btn: QPushButton

        root = QVBoxLayout(self)

        # ----- 1. Files ------------------------------------------------
        files_box = QGroupBox("1. Источники — PDF / DOCX / MD / TXT")
        files_layout = QVBoxLayout(files_box)
        self.tree = _FileTree()
        self.tree.files_changed.connect(self._update_build_enabled)
        files_layout.addWidget(self.tree, stretch=1)

        files_btn_row = QHBoxLayout()
        b_add_files = QPushButton("Добавить файлы…")
        b_add_files.clicked.connect(self._on_add_files)
        b_add_dir = QPushButton("Добавить папку…")
        b_add_dir.clicked.connect(self._on_add_dir)
        b_remove = QPushButton("Удалить выделенное")
        b_remove.clicked.connect(self.tree.remove_selected)
        b_clear = QPushButton("Очистить")
        b_clear.clicked.connect(self.tree.clear_all)
        for w in (b_add_files, b_add_dir, b_remove, b_clear):
            files_btn_row.addWidget(w)
        files_btn_row.addStretch(1)
        files_layout.addLayout(files_btn_row)

        hint = QLabel(
            "Можно перетащить файлы или целые папки прямо в список. "
            "Поддерживаются .pdf / .docx / .md / .txt."
        )
        hint.setStyleSheet("color:#888; font-size:13px;")
        files_layout.addWidget(hint)
        root.addWidget(files_box, stretch=2)

        # ----- 2. Metadata --------------------------------------------
        meta_box = QGroupBox("2. Параметры курса")
        meta_form = QFormLayout(meta_box)
        self.ed_name = QLineEdit()
        self.ed_name.textChanged.connect(self._on_name_changed)
        self.ed_short = QLineEdit()
        self.ed_short.textChanged.connect(self._update_build_enabled)
        self.ed_short.setPlaceholderText("Короткое имя для голоса (2–40 символов)")
        self.ed_topic = QLineEdit()
        self.ed_topic.textChanged.connect(self._update_build_enabled)
        self.ed_audience = QLineEdit("студент")
        self.ed_style = QPlainTextEdit()
        self.ed_style.setPlaceholderText("Как преподавать. Одной-двумя фразами.")
        self.ed_style.setFixedHeight(60)
        self.ed_style.setPlainText("дружелюбно, простыми словами")

        meta_form.addRow("Название курса:", self.ed_name)
        meta_form.addRow("Краткое имя (short_name):", self.ed_short)
        meta_form.addRow("Тема / охват:", self.ed_topic)
        meta_form.addRow("Аудитория:", self.ed_audience)
        meta_form.addRow("Стиль преподавания:", self.ed_style)
        root.addWidget(meta_box)

        # ----- 3. Build ------------------------------------------------
        build_box = QGroupBox("3. Сборка")
        build_layout = QVBoxLayout(build_box)

        run_row = QHBoxLayout()
        self._build_btn = QPushButton("Собрать")
        self._build_btn.setDefault(True)
        self._build_btn.clicked.connect(self._on_build_clicked)
        self._build_btn.setEnabled(False)
        run_row.addWidget(self._build_btn)
        self._cancel_btn = QPushButton("Отменить сборку")
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.clicked.connect(self._on_cancel_clicked)
        run_row.addWidget(self._cancel_btn)
        run_row.addStretch(1)
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        run_row.addWidget(self._progress, stretch=1)
        build_layout.addLayout(run_row)

        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setFixedHeight(120)
        self._log.setStyleSheet(
            "QPlainTextEdit { background:#0d1110; color:#cfcfcf; "
            "border:1px solid #2a3a2a; font-family:Consolas, monospace; "
            "font-size:13px; }"
        )
        build_layout.addWidget(self._log)
        root.addWidget(build_box)

        # ----- bottom buttons ------------------------------------------
        self._buttons = QDialogButtonBox(QDialogButtonBox.Close)
        self._buttons.rejected.connect(self.reject)
        root.addWidget(self._buttons)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Добавить файлы курса", "",
            "Учебные материалы (*.pdf *.docx *.md *.markdown *.txt);;"
            "Все файлы (*)",
        )
        if paths:
            self.tree.add_paths([Path(p) for p in paths])

    def _on_add_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Добавить папку")
        if path:
            n = self.tree.add_paths([Path(path)])
            if n == 0:
                QMessageBox.information(
                    self, "Папка пуста",
                    "В выбранной папке не найдено поддерживаемых файлов "
                    "(.pdf / .docx / .md / .txt).",
                )

    def _on_name_changed(self, text: str) -> None:
        # Auto-fill short_name from name on first edit (only if short is empty
        # or the user hasn't touched it).
        if not self.ed_short.text().strip():
            slug = _slugify(text)
            self.ed_short.blockSignals(True)
            self.ed_short.setText(slug)
            self.ed_short.blockSignals(False)
        self._update_build_enabled()

    def _update_build_enabled(self) -> None:
        ok = (
            self.tree.topLevelItemCount() > 0
            and self.ed_name.text().strip() != ""
            and self.ed_topic.text().strip() != ""
            and _validate_short_name(self.ed_short.text())
        )
        self._build_btn.setEnabled(ok and self._worker is None)

    def _on_build_clicked(self) -> None:
        files = self.tree.collected_paths()
        if not files:
            return
        short = self.ed_short.text().strip()
        if not _validate_short_name(short):
            QMessageBox.warning(
                self, "Короткое имя",
                "short_name: 2–40 символов, только буквы/цифры/_/-.",
            )
            return

        target_dir = _COURSES_ROOT / short
        overwrite = False
        if target_dir.exists() and any(target_dir.iterdir()):
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Question)
            msg.setWindowTitle("Папка уже существует")
            msg.setText(f"<b>{target_dir}</b> не пустая.")
            msg.setInformativeText(
                "Перезаписать — удалить старое содержимое и собрать с нуля.\n"
                "Дополнить — оставить старое, добавить новые файлы поверх.\n"
                "Отмена — ничего не делать."
            )
            b_overwrite = msg.addButton("Перезаписать", QMessageBox.DestructiveRole)
            b_append    = msg.addButton("Дополнить",    QMessageBox.AcceptRole)
            b_cancel    = msg.addButton("Отмена",       QMessageBox.RejectRole)
            msg.exec()
            clicked = msg.clickedButton()
            if clicked is b_cancel:
                return
            overwrite = (clicked is b_overwrite)

        inputs = BuildInputs(
            files=files,
            target_dir=target_dir,
            course_name=self.ed_name.text().strip(),
            course_topic=self.ed_topic.text().strip(),
            short_name=short,
            audience=self.ed_audience.text().strip() or "студент",
            teaching_style=self.ed_style.toPlainText().strip() or "дружелюбно",
            overwrite=overwrite,
        )

        self._log.clear()
        self._log.appendPlainText(f"Цель: {target_dir}")
        self._log.appendPlainText(f"Файлов на входе: {len(files)}")
        self._progress.setValue(0)
        self._worker = BuildWorker(inputs, parent=self)
        self._worker.progress.connect(self._on_progress)
        self._worker.log_line.connect(self._log.appendPlainText)
        self._worker.finished_ok.connect(self._on_finished_ok)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._on_worker_done)
        self._build_btn.setEnabled(False)
        self._cancel_btn.setEnabled(True)
        self._worker.start()

    def _on_cancel_clicked(self) -> None:
        if self._worker is not None:
            self._worker.requestInterruption()
            self._log.appendPlainText("(прерывание...)")

    def _on_progress(self, pct: int, status: str) -> None:
        self._progress.setValue(pct)
        if status:
            self._progress.setFormat(f"{status}  %p%")

    def _on_finished_ok(self, target_dir: str, chunks: int) -> None:
        msg = (f"Готово. Пакет: {target_dir}\n"
               f"Оценка: ~{chunks} чанк(ов). "
               f"Курс появится в менеджере; активируй его кнопкой "
               f"«Активировать» или голосом «загрузи курс ...».")
        self._log.appendPlainText("")
        self._log.appendPlainText(msg)
        QMessageBox.information(self, "Пакет собран", msg)

    def _on_failed(self, error: str) -> None:
        self._log.appendPlainText(f"[!] Ошибка: {error}")
        QMessageBox.warning(self, "Сборка не выполнена", error)

    def _on_worker_done(self) -> None:
        self._worker = None
        self._cancel_btn.setEnabled(False)
        self._update_build_enabled()

    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.requestInterruption()
            self._worker.wait(2000)
        super().closeEvent(event)
