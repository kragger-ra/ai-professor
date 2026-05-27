"""Audio mode — local (mic/speakers) vs meeting (virtual cable).

Persisted in ``data/audio_mode.txt`` (one word: ``local`` or ``meeting``).
The board UI writes this file via the ``audio_mode`` IPC command; the tutor
reads it at startup to choose input/output device names.

Hot-swap during a session is intentionally NOT supported in this iteration —
the audio threads grab their devices once at boot and hold them open. To
change modes, the user toggles in the menu and restarts the tutor.

Defaults are biased to ``local`` because that is the natural first-launch
state. ``.env`` ``AUDIO_MODE`` is still honoured as a fallback for users
who haven't touched the UI toggle yet.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Tuple

# Sidecar lives in the same data/ dir as session_memory.json / current_course.json
_MODE_FILE = (
    Path(__file__).resolve().parent.parent.parent / "data" / "audio_mode.txt"
)

VALID_MODES = ("local", "meeting")


def current_mode() -> str:
    """Read the persisted mode; fall back to AUDIO_MODE env, then 'local'."""
    if _MODE_FILE.exists():
        try:
            stored = _MODE_FILE.read_text(encoding="utf-8").strip().lower()
            if stored in VALID_MODES:
                return stored
        except Exception:
            pass
    env_mode = os.getenv("AUDIO_MODE", "local").strip().lower()
    return env_mode if env_mode in VALID_MODES else "local"


def set_mode(mode: str) -> None:
    """Persist mode to disk. Applies on next tutor process restart."""
    mode = mode.strip().lower()
    if mode not in VALID_MODES:
        raise ValueError(f"unknown audio mode {mode!r}; expected one of {VALID_MODES}")
    _MODE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _MODE_FILE.write_text(mode, encoding="utf-8")


def devices_for_mode(mode: str) -> Tuple[str, str]:
    """Return ``(input_device_name, output_device_name)`` for the mode.

    Empty strings mean "use the system default". Names are substring
    matches against sounddevice / PortAudio's device listing.

    Meeting-mode devices match the documented VoiceMeeter Banana setup
    (see project_audio_routing_meeting_2026_05_17). Users with a different
    routing override via the env vars below.
    """
    if mode == "meeting":
        return (
            os.getenv("SOUND_DEVICE_IN_MEETING", "Voicemeeter Out B2"),
            os.getenv("SOUND_DEVICE_OUT_MEETING", "Voicemeeter Input"),
        )
    # local
    return (
        os.getenv("SOUND_DEVICE_IN_LOCAL", os.getenv("SOUND_DEVICE_IN", "")),
        os.getenv("SOUND_DEVICE_OUT_LOCAL", os.getenv("SOUND_DEVICE_OUT", "")),
    )
