"""Optional sidecar UI for the AI Professor tutor.

The board process tails ``data/board_events.jsonl`` (written by the tutor's
``BoardLog``) and renders two panes — an interactive board (formulas / terms
/ key facts) and a chat history — in a single PySide6 window.

This package has NO audio dependencies by construction: it is purely a
read-only viewer over the event log.
"""
