"""AI Professor — Tutor v2 entry point (Phase 2: QA base).

Single process. Worker threads wired by two queues and one interrupt event:

    capture/STT  --input_q-->  agent  --tts_q-->  playback
         |                                            ^
         +------------------ interrupt ---------------+

External servers used: OpenAI API (or local LM Studio) for the LLM,
LM Studio for RAG embeddings, the Vosk TTS server for synthesis.

Run (from the repo root):
    python -m tutor.app
"""
from __future__ import annotations

import os
import queue
import threading
import time

from tutor.audio.ambient import AmbientPlayer
from tutor.audio.capture import CaptureThread
from tutor.audio.fillers import FillerLibrary
from tutor.audio.mode import current_mode, devices_for_mode, set_mode
from tutor.audio.playback import PlaybackThread
from tutor.brain.agent import AgentThread
from tutor.brain.answer import Answer
from tutor.brain.rag import RagModel
from tutor.commands_tail import CommandsTail
from tutor.document_store import DocumentStore
from tutor.util import log


def main() -> None:
    # Resolve the active audio mode (UI sidecar overrides AUDIO_MODE env) and
    # pick the matching input/output device names. The board UI's audio-mode
    # menu writes the sidecar file; changes take effect on this restart.
    mode = current_mode()
    capture_dev, playback_dev = devices_for_mode(mode)
    log("app", f"audio mode: {mode} (in={capture_dev or '<system default>'}, "
               f"out={playback_dev or '<system default>'})")
    # --- shared channels -------------------------------------------------
    input_q: queue.Queue = queue.Queue()   # student utterances -> agent
    tts_q: queue.Queue = queue.Queue()     # answer sentences   -> playback
    interrupt = threading.Event()          # set the instant the student talks

    # --- RAG model (embeddings + FAISS index) ----------------------------
    log("app", "loading RAG model (embeddings + FAISS index)...")
    try:
        rag = RagModel()
    except Exception as exc:
        log("app", f"RAG unavailable ({type(exc).__name__}: {exc}) — "
                   f"is LM Studio running? continuing without course retrieval")
        rag = None

    # Document store (board uploads docs; agent injects their text into the
    # system prompt). Lives outside any thread so handlers + agent share it.
    documents = DocumentStore()

    # Filler library — short pre-rendered cues to cover the wait gap when
    # the agent starts answering. Off by default (env FILLERS=on enables
    # warm-up + use). User feedback 2026-05-27: cues felt distracting at
    # the current cadence; the agent skips them silently when fillers=None.
    if os.getenv("FILLERS", "off").strip().lower() in ("on", "1", "true", "yes"):
        fillers = FillerLibrary()
        threading.Thread(
            target=fillers.warm_up, daemon=True, name="filler-warmup",
        ).start()
        log("app", "fillers ENABLED (FILLERS=on)")
    else:
        fillers = None
        log("app", "fillers disabled (set FILLERS=on to enable)")

    # --- worker threads --------------------------------------------------
    # Playback must exist before the agent so the agent can hook into
    # playback.speaking for its filler-gate. PlaybackThread itself is
    # cheap to construct — the AudioProcessor is built later in run().
    playback = PlaybackThread(tts_q, interrupt, output_device=playback_dev)
    agent = AgentThread(
        input_q, tts_q, interrupt, rag,
        documents=documents, fillers=fillers,
        playback_speaking=playback.speaking,
    )
    capture = CaptureThread(
        input_q,
        interrupt,
        tts_active=playback.speaking,           # anti-echo: raise VAD gate while voicing
        rag_vocab=(rag.get_vocabulary() if rag else set()),
        device_name=capture_dev,
    )

    agent.start()
    playback.start()
    capture.start()

    # Plumb the transcript sink for STT_MODE=transcribe — sends captured
    # text to the board's chat input field instead of the LLM.
    capture.transcript_sink = lambda text: agent._board.stt_transcript(text)

    # Optional sidecar IPC: the board UI writes commands here. No-throw.
    def _on_chat_input(cmd: dict) -> None:
        text = (cmd.get("text") or "").strip()
        if text:
            log("app", f"chat_input from board: {text[:60]!r}")
            input_q.put((text, False))

    def _on_explain(cmd: dict) -> None:
        text = (cmd.get("text") or "").strip()
        if text:
            wrapped = (
                f"Объясни простыми словами этот фрагмент: «{text}». "
                "Отвечай голосом, 2–4 предложения. "
                "На доску ничего выносить не нужно — не добавляй ни "
                "маркера «---BOARD---», ни тегов [BOARD-*]."
            )
            log("app", f"explain from board: {text[:60]!r}")
            # SYNTHETIC marker — agent strips it and skips the user_said
            # board event (intent chip is already shown by the board UI).
            input_q.put((f"__INTENT__{wrapped}", False))

    def _on_read_aloud(cmd: dict) -> None:
        text = (cmd.get("text") or "").strip()
        if not text:
            return
        log("app", f"read_aloud from board: {text[:60]!r}")
        cue = Answer(question="", sentences=[text])
        cue.finish_generation()
        interrupt.clear()
        tts_q.put(cue)

    def _on_read_formula(cmd: dict) -> None:
        latex = (cmd.get("latex") or "").strip()
        if not latex:
            return
        log("app", f"read_formula from board: {latex[:60]!r}")
        wrapped = ("Произнеси эту формулу ЕСТЕСТВЕННОЙ русской речью, "
                   "одним коротким предложением, без объяснений и без "
                   "повторения LaTeX-символов: " + latex)
        input_q.put((f"__INTENT__{wrapped}", False))

    def _on_tts_mute(cmd: dict) -> None:
        muted = bool(cmd.get("muted"))
        if muted:
            playback.muted.set()
            log("app", "TTS muted from board")
        else:
            playback.muted.clear()
            log("app", "TTS unmuted from board")

    def _on_stt_mode(cmd: dict) -> None:
        mode = (cmd.get("mode") or "open").lower()
        if mode not in ("open", "transcribe"):
            log("app", f"unknown stt mode {mode!r} — ignored")
            return
        capture.stt_mode = mode
        # Entering open mode always resumes capture; entering transcribe mode
        # leaves the paused state untouched (board UI sets it explicitly).
        if mode == "open":
            capture.paused.clear()
        log("app", f"STT mode -> {mode}")

    def _on_stt_paused(cmd: dict) -> None:
        paused = bool(cmd.get("paused"))
        if paused:
            capture.paused.set()
        else:
            capture.paused.clear()
        log("app", f"STT paused -> {paused}")

    def _on_document_added(cmd: dict) -> None:
        doc_id = (cmd.get("id") or "").strip()
        name = (cmd.get("name") or "").strip() or "(без названия)"
        kind = (cmd.get("kind") or "text").strip()
        text = cmd.get("text") or ""
        if not doc_id or not text:
            return
        documents.add(doc_id, name, kind, text)
        log("app", f"document added: {name} ({kind}, "
                   f"{len(text)} chars) — total {len(documents.list())}")

    def _on_document_removed(cmd: dict) -> None:
        doc_id = (cmd.get("id") or "").strip()
        if not doc_id:
            return
        removed = documents.remove(doc_id)
        if removed:
            log("app", f"document removed: {removed.name}")

    def _on_add_comment(cmd: dict) -> None:
        cid = (cmd.get("comment_id") or "").strip()
        anchor = (cmd.get("anchor") or "").strip()
        note = (cmd.get("note") or "").strip()
        if cid and anchor and note:
            agent._board.comment_added(cid, anchor, note)
            log("app", f"comment {cid}: {note[:60]!r}")

    def _on_remove_comment(cmd: dict) -> None:
        cid = (cmd.get("comment_id") or "").strip()
        if cid:
            agent._board.comment_removed(cid)
            log("app", f"comment removed: {cid}")

    # Mutable holder so the IPC handler can update the active mode after a swap.
    _active_mode = [mode]

    def _on_tts_pause(cmd: dict) -> None:
        """Pause the currently-voicing answer. Setting interrupt makes
        PlaybackThread's watcher break the chunk loop on the next ~30ms
        tick; the cut sentence is NOT marked voiced, so a resume re-voices
        it for context. The interrupt flag stays set — capture clears it
        on the next real utterance or on resume below."""
        log("app", "TTS paused from board")
        interrupt.set()

    def _on_tts_resume(cmd: dict) -> None:
        """Resume the paused answer. We push an empty-utterance interruption
        record into the agent's input queue; the agent already treats this
        as a 'no-transcript interruption' and calls _handle_continue —
        which is exactly the path that re-voices the cut sentence from
        memory without an LLM round-trip."""
        log("app", "TTS resume from board")
        input_q.put(("", True))

    def _on_audio_mode(cmd: dict) -> None:
        """Hot-swap the audio devices and persist the new mode.

        The capture loop has an outer re-entry layer that reopens its mic
        sd.InputStream on the next ~100ms block; playback re-resolves its
        output index on the next ``_play_safe`` call. The current TTS
        sentence finishes on the old device — interruption-free swap."""
        new_mode = (cmd.get("mode") or "").strip().lower()
        if new_mode not in ("local", "meeting"):
            log("app", f"audio_mode: unknown mode {new_mode!r} - ignored")
            return
        if new_mode == _active_mode[0]:
            log("app", f"audio_mode: already {new_mode!r} — no-op")
            return
        new_in, new_out = devices_for_mode(new_mode)
        log("app", f"audio_mode hot-swap -> {new_mode!r} "
                   f"(in='{new_in}', out='{new_out}')")
        try:
            capture.swap_device(new_in)
            playback.swap_output(new_out)
            set_mode(new_mode)
            _active_mode[0] = new_mode
        except Exception as exc:
            log("app", f"audio_mode swap failed: "
                       f"{type(exc).__name__}: {exc}")

    def _on_load_course(cmd: dict) -> None:
        from pathlib import Path as _Path
        path = (cmd.get("path") or "").strip()
        if not path:
            return
        if rag is None:
            agent._board.course_load_failed(
                "RAG model unavailable (LM Studio embeddings down?)", path)
            return
        short = _Path(path).name
        mode = (cmd.get("mode") or "replace").strip()
        try:
            n = rag.reload_from_path(short, path, mode=mode)
            from tutor.brain import course as _course
            _course.set_current_path(path)
            cfg = _course.get_current()
            agent._board.course_loaded(
                str(cfg.fields.get("name") or short),
                str(cfg.fields.get("short_name") or short),
                path, n)
            log("app", f"course loaded: {short!r} ({n} chunks)")
        except Exception as exc:
            agent._board.course_load_failed(
                f"{type(exc).__name__}: {exc}", path)
            log("app", f"load_course failed: {type(exc).__name__}: {exc}")

    cmd_tail = CommandsTail(handlers={
        "chat_input":       _on_chat_input,
        "explain":          _on_explain,
        "read_aloud":       _on_read_aloud,
        "read_formula":     _on_read_formula,
        "tts_mute":         _on_tts_mute,
        "stt_mode":         _on_stt_mode,
        "stt_paused":       _on_stt_paused,
        "document_added":   _on_document_added,
        "document_removed": _on_document_removed,
        "add_comment":      _on_add_comment,
        "remove_comment":   _on_remove_comment,
        "load_course":      _on_load_course,
        "audio_mode":       _on_audio_mode,
        "tts_pause":        _on_tts_pause,
        "tts_resume":       _on_tts_resume,
    })
    cmd_tail.start()

    # Quiet ambient background — optional and fail-safe (AMBIENT_SOUND=off
    # mutes it; any decode or device failure silently disables it).
    ambient = AmbientPlayer(device_name=os.getenv("SOUND_DEVICE_OUT", ""))
    ambient.start_room_loop()

    # Audible "ready" cue once the mic stream is open — also a live
    # end-to-end check that the TTS chain works.
    if capture.ready.wait(timeout=120):
        cue = Answer(question="", sentences=["Профессор готов. Спрашивай."])
        cue.finish_generation()
        tts_q.put(cue)
        ambient.play_cat_purr()    # a short calming purr as the tutor comes online
    log("app", "pipeline up — speak to the professor (Ctrl+C to quit)")

    try:
        while capture.is_alive():
            time.sleep(0.2)
    except KeyboardInterrupt:
        log("app", "shutting down")
    finally:
        capture.stop()
        ambient.stop()
        cmd_tail.stop()
        # Capture this final session into cross-session memory before exit.
        log("app", "persisting session memory...")
        agent.persist_memory()
        agent.stop()
        playback.stop()


if __name__ == "__main__":
    main()
