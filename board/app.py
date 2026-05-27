"""Entry point for the board sidecar — ``python -m board``."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    cli = argparse.ArgumentParser(
        prog="board",
        description="AI Professor — interactive board + chat sidecar",
    )
    cli.add_argument(
        "--replay", action="store_true",
        help="Read the JSONL file from the beginning (default: tail from end)",
    )
    cli.add_argument(
        "--log", type=Path, default=None,
        help="Path to the JSONL event log (default: data/board_events.jsonl)",
    )
    cli.add_argument(
        "--export-board-html", type=Path, default=None,
        help="Replay the log to a self-contained board HTML and exit",
    )
    cli.add_argument(
        "--export-chat-html", type=Path, default=None,
        help="Replay the log to a self-contained chat HTML and exit",
    )
    args = cli.parse_args()

    try:
        from PySide6.QtWidgets import QApplication  # noqa: F401
    except ImportError:
        print(
            "PySide6 is not installed. Install the board dep group:\n"
            "    uv sync --group board\n"
            "or:\n"
            "    pip install \"PySide6~=6.7\"",
            file=sys.stderr,
        )
        return 1

    jsonl_path = args.log or (
        Path(__file__).resolve().parent.parent / "data" / "board_events.jsonl"
    )

    # Headless HTML export: skip Qt UI entirely.
    if args.export_board_html or args.export_chat_html:
        from board import export as exporter
        if args.export_board_html:
            n = exporter.export_html_board(jsonl_path, args.export_board_html)
            print(f"board HTML saved: {args.export_board_html} ({n} items)")
        if args.export_chat_html:
            n = exporter.export_html_chat(jsonl_path, args.export_chat_html)
            print(f"chat HTML saved: {args.export_chat_html} ({n} items)")
        return 0

    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication, QMessageBox
    from board.ui import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    # Bump the app-wide font one notch — Windows default 9pt looks tiny
    # on the high-res displays the testers use. Affects menubar, dialog
    # labels, table cells, and any widget that doesn't set its own font.
    base_font = QFont("Segoe UI", 11)
    app.setFont(base_font)
    win = MainWindow(jsonl_path, from_start=args.replay)
    win.show()

    # Alpha disclaimer — fires once per board launch, on top of the now-
    # visible main window. Cosmetic / informational only; OK closes it.
    QMessageBox.information(
        win,
        "AI Professor — альфа-тестирование",
        "Этот интерфейс сейчас находится в стадии альфа-тестирования.\n\n"
        "Большая часть функций уже работает, но возможны нестабильности, "
        "странное поведение и неполные сценарии. Если что-то выглядит "
        "сломанным — это нормально для текущего этапа.\n\n"
        "Сообщайте о найденных проблемах в обратной связи."
    )
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
