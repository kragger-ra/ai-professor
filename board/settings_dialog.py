"""Connections settings dialog — pick the active LLM provider and edit
the API keys / model names that the tutor reads from ``.env`` at boot.

Five providers are supported:

  local      — LM Studio (or any OpenAI-compatible local server)
  openai     — OpenAI hosted (gpt-4o, gpt-4o-mini, gpt-5.x …)
  anthropic  — Anthropic (claude-3-5-sonnet, claude-3-5-haiku, opus-4-7)
  deepseek   — DeepSeek (deepseek-chat, deepseek-reasoner)
  yandex     — Yandex GPT (yandexgpt-pro/latest, yandexgpt/latest)

All API keys live in the same ``.env`` and stay there across switches —
selecting a different active provider only flips ``USE_LOCAL_LLM`` and
``CORE_LLM_MODEL_NAME``. Restart the tutor to apply.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QToolButton, QVBoxLayout, QWidget,
)

try:
    from dotenv import dotenv_values, set_key
except ImportError:
    dotenv_values = None  # type: ignore[assignment]
    set_key = None  # type: ignore[assignment]


_REPO_ROOT = Path(__file__).resolve().parent.parent
_ENV_PATH = _REPO_ROOT / ".env"

# (provider_key, label, default_model, env_var_for_api_key, litellm_prefix)
PROVIDERS: list[tuple[str, str, str, str, str]] = [
    ("local",     "Локально (LM Studio / OpenAI-совместимый сервер)",
                  "",                              "",                 ""),
    ("openai",    "OpenAI",
                  "gpt-4o-mini",                   "OPENAI_API_KEY",   "openai/"),
    ("anthropic", "Anthropic Claude",
                  "claude-3-5-sonnet-20241022",    "ANTHROPIC_API_KEY","anthropic/"),
    ("deepseek",  "DeepSeek",
                  "deepseek-chat",                 "DEEPSEEK_API_KEY", "deepseek/"),
    ("yandex",    "Yandex GPT",
                  "yandexgpt-pro/latest",          "YANDEX_API_KEY",   "yandex/"),
]


def _provider_by_key(key: str) -> tuple[str, str, str, str, str] | None:
    for p in PROVIDERS:
        if p[0] == key:
            return p
    return None


class ConnectionsDialog(QDialog):
    """Modal dialog to edit provider + keys; persists to .env via dotenv."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Настройки подключений")
        self.setMinimumWidth(640)
        self.setModal(True)

        if dotenv_values is None or set_key is None:
            self._env: dict[str, str] = {}
        else:
            self._env = {k: (v or "") for k, v in
                         dotenv_values(_ENV_PATH).items()} \
                         if _ENV_PATH.exists() else {}

        layout = QVBoxLayout(self)

        # --- Active provider + model ---------------------------------
        provider_box = QGroupBox("Активный провайдер")
        prov_form = QFormLayout(provider_box)
        self.combo_provider = QComboBox()
        for key, label, *_ in PROVIDERS:
            self.combo_provider.addItem(label, key)
        current = self._detect_current_provider()
        idx = next((i for i, p in enumerate(PROVIDERS) if p[0] == current), 1)
        self.combo_provider.setCurrentIndex(idx)
        self.combo_provider.currentIndexChanged.connect(self._on_provider_changed)
        prov_form.addRow("Провайдер:", self.combo_provider)

        self.input_model = QLineEdit()
        prov_form.addRow("Модель:", self.input_model)
        layout.addWidget(provider_box)

        # --- API keys ------------------------------------------------
        keys_box = QGroupBox(
            "API-ключи (хранятся одновременно; используется ключ активного "
            "провайдера)")
        keys_form = QFormLayout(keys_box)
        self.key_inputs: dict[str, QLineEdit] = {}
        for key, label, _, env_var, _ in PROVIDERS:
            if not env_var:
                continue
            line = QLineEdit()
            line.setEchoMode(QLineEdit.Password)
            line.setText(self._env.get(env_var, ""))
            line.setPlaceholderText("(не задан)")
            self.key_inputs[key] = line

            toggle = QToolButton()
            toggle.setText("show")
            toggle.setCheckable(True)
            toggle.setToolTip("Показать / скрыть ключ")
            toggle.toggled.connect(
                lambda checked, l=line, b=toggle: (
                    l.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password),
                    b.setText("hide" if checked else "show"),
                ))

            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(4)
            row.addWidget(line)
            row.addWidget(toggle)
            wrap = QWidget()
            wrap.setLayout(row)
            keys_form.addRow(label + ":", wrap)

        # Yandex needs an extra field (folder id) — not a secret but
        # required by the API endpoint.
        self.input_yandex_folder = QLineEdit()
        self.input_yandex_folder.setText(self._env.get("YANDEX_FOLDER_ID", ""))
        self.input_yandex_folder.setPlaceholderText("обязательно для Yandex")
        keys_form.addRow("Yandex Folder ID:", self.input_yandex_folder)
        layout.addWidget(keys_box)

        # --- Local server --------------------------------------------
        local_box = QGroupBox(
            "Локальный сервер (используется когда активен провайдер «Локально»)")
        local_form = QFormLayout(local_box)
        self.input_local_url = QLineEdit()
        self.input_local_url.setText(
            self._env.get("LM_STUDIO_API_BASE", "http://localhost:1234/v1"))
        local_form.addRow("URL:", self.input_local_url)
        self.input_local_model = QLineEdit()
        self.input_local_model.setText(
            self._env.get("LM_STUDIO_MODEL_NAME", "gpt-4o-mini"))
        local_form.addRow("Имя модели:", self.input_local_model)
        layout.addWidget(local_box)

        # --- Info ----------------------------------------------------
        info = QLabel(
            "Изменения сохраняются в файл .env. Перезапусти тьютор, "
            "чтобы новые настройки подхватились."
        )
        info.setStyleSheet("color:#888; font-style:italic; padding:4px 0;")
        info.setWordWrap(True)
        layout.addWidget(info)

        if dotenv_values is None or set_key is None:
            warn = QLabel(
                "⚠ python-dotenv не установлен — сохранение отключено. "
                "Установи: pip install python-dotenv")
            warn.setStyleSheet("color:#a05858; font-weight:bold; padding:4px 0;")
            layout.addWidget(warn)

        # --- Buttons -------------------------------------------------
        btn_row = QHBoxLayout()
        btn_open_env = QPushButton("Открыть .env вручную…")
        btn_open_env.clicked.connect(self._open_env_in_editor)
        btn_row.addWidget(btn_open_env)
        btn_row.addStretch()
        btn_cancel = QPushButton("Отмена")
        btn_cancel.clicked.connect(self.reject)
        btn_save = QPushButton("Сохранить")
        btn_save.setDefault(True)
        if set_key is None or not _ENV_PATH.exists():
            btn_save.setEnabled(False)
        btn_save.clicked.connect(self._save)
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_save)
        layout.addLayout(btn_row)

        self._on_provider_changed()

    # ------------------------------------------------------------------

    def _detect_current_provider(self) -> str:
        use_local = self._env.get("USE_LOCAL_LLM", "").strip().lower()
        if use_local in ("true", "1", "yes", "on"):
            return "local"
        core = self._env.get("CORE_LLM_MODEL_NAME", "").strip().lower()
        for key, _, _, _, prefix in PROVIDERS:
            if prefix and core.startswith(prefix):
                return key
        return "openai"

    def _on_provider_changed(self) -> None:
        provider = self.combo_provider.currentData()
        entry = _provider_by_key(provider)
        if entry is None:
            return
        _, _, default_model, _, prefix = entry

        if provider == "local":
            self.input_model.setText(self.input_local_model.text())
            self.input_model.setEnabled(False)
            self.input_model.setPlaceholderText(
                "берётся из «Локальный сервер → Имя модели» ниже")
            return

        self.input_model.setEnabled(True)
        # If the current CORE_LLM_MODEL_NAME matches this provider, restore
        # the part after the prefix; otherwise fall back to the default.
        current = self._env.get("CORE_LLM_MODEL_NAME", "").strip()
        if current.lower().startswith(prefix.lower()) and prefix:
            self.input_model.setText(current[len(prefix):])
        else:
            self.input_model.setText(default_model)
        self.input_model.setPlaceholderText(f"например: {default_model}")

    def _open_env_in_editor(self) -> None:
        if _ENV_PATH.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(_ENV_PATH)))
        else:
            QMessageBox.warning(
                self, ".env не найден",
                f"Файл не существует: {_ENV_PATH}\n\n"
                "Скопируй .env.example в .env и заполни значения вручную.")

    # ------------------------------------------------------------------

    def _save(self) -> None:
        if set_key is None:
            QMessageBox.warning(self, "Нет python-dotenv",
                                "Установи: pip install python-dotenv")
            return
        if not _ENV_PATH.exists():
            QMessageBox.warning(
                self, ".env не найден",
                f"Файл не существует: {_ENV_PATH}\n\n"
                "Скопируй .env.example в .env, потом сохраняй настройки.")
            return

        provider = self.combo_provider.currentData()
        env_path_s = str(_ENV_PATH)

        # 1. All cloud API keys — write even unchanged values so a fresh
        #    .env after .env.example copy still gets populated. Empty
        #    string is allowed (means "not set").
        try:
            for key, _, _, env_var, _ in PROVIDERS:
                if not env_var:
                    continue
                val = self.key_inputs[key].text().strip()
                set_key(env_path_s, env_var, val, quote_mode="always")

            # 2. Yandex folder id.
            set_key(env_path_s, "YANDEX_FOLDER_ID",
                    self.input_yandex_folder.text().strip(),
                    quote_mode="always")

            # 3. Local server URL + model name.
            set_key(env_path_s, "LM_STUDIO_API_BASE",
                    self.input_local_url.text().strip(),
                    quote_mode="always")
            set_key(env_path_s, "LM_STUDIO_MODEL_NAME",
                    self.input_local_model.text().strip(),
                    quote_mode="always")

            # 4. Active provider switch.
            if provider == "local":
                set_key(env_path_s, "USE_LOCAL_LLM", "true",
                        quote_mode="always")
            else:
                set_key(env_path_s, "USE_LOCAL_LLM", "false",
                        quote_mode="always")
                entry = _provider_by_key(provider)
                if entry is not None:
                    _, _, _, _, prefix = entry
                    model = self.input_model.text().strip()
                    if model:
                        set_key(env_path_s, "CORE_LLM_MODEL_NAME",
                                f"{prefix}{model}", quote_mode="always")
                    set_key(env_path_s, "CORE_LLM_API_BASE", "NONE",
                            quote_mode="always")
        except Exception as exc:
            QMessageBox.warning(
                self, "Не удалось сохранить",
                f"{type(exc).__name__}: {exc}\n\nПопробуй открыть .env "
                "вручную (кнопка внизу) и проверить права доступа.")
            return

        QMessageBox.information(
            self, "Сохранено",
            "Настройки записаны в .env.\n\n"
            "Перезапусти тьютор (stop_tutor_v2.bat → start_tutor_v2.bat), "
            "чтобы новые настройки подхватились.")
        self.accept()
