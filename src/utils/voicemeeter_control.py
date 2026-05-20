"""VoiceMeeter Banana audio routing for AI Professor.

Three modes:
  MEETING: TTS -> VoiceMeeter VAIO -> A1 (headphones) + B1 (call mic)
           Call speaker -> VB-Cable -> Strip 0 -> A1 (monitor) + B2 (STT)

  LOCAL:   TTS -> VoiceMeeter VAIO -> A1 (headphones only)
           Strip 0 B2 off (STT uses fifine mic directly)

  RELEASE: Mute all, shutdown engine, return devices to Windows.

Works with any audio call app where CABLE Input is selected as the mic
and CABLE Output as the speaker (Discord, Meet, Teams, Telegram, ...).
Zoom is excluded — its driver bypasses VB-Cable routing.

IMPORTANT: meeting_mode() and local_mode() always unmute the relevant
strips and buses, so they work correctly even after a release_audio().
"""

import traceback

_vm = None
_engine_was_shutdown = False  # set by release_audio(); next mode switch must restart

# Virtual audio devices required for routing. All four are part of the
# stock VB-Cable + VoiceMeeter Banana install — no extra A+B pack needed.
#   CABLE Input/Output — call-app pipes its audio in/out via VB-Cable
#   Voicemeeter Input  — TTS writes here (Banana main VAIO, Strip 3 source)
#   Voicemeeter Out B2 — STT reads here (Banana virtual bus B2)
_REQUIRED_DEVICES = (
    "CABLE Input",
    "CABLE Output",
    "Voicemeeter Input",
    "Voicemeeter Out B2",
)


def _get_vm():
    global _vm
    # AUDIO_MODE=none|off|skip disables ALL VoiceMeeter interaction. Without
    # this gate, Gradio's demo.load(get_status) at page open would call
    # voicemeeterlib.api("banana").login() which auto-launches voicemeeterpro_x64
    # and grabs Sound Blaster in WASAPI exclusive mode.
    import os
    if os.getenv("AUDIO_MODE", "local").lower() in ("none", "off", "skip", ""):
        return None
    if _vm is None:
        try:
            import voicemeeterlib
            _vm = voicemeeterlib.api("banana")
            _vm.login()
        except Exception as e:
            print(f"[VoiceMeeter] Failed to connect: {e}")
            return None
    return _vm


def _check_vm_banana() -> bool:
    """Return True if VoiceMeeter Banana is reachable (engine running)."""
    vm = _get_vm()
    if vm is None:
        return False
    try:
        _ = vm.strip[0].mute  # cheap read; raises if engine is shut down
        return True
    except Exception:
        return False


def _validate_devices() -> list:
    """Return required audio devices that are missing from the OS device list."""
    try:
        import sounddevice as sd
        names = [dev["name"] for dev in sd.query_devices()]
    except Exception:
        return list(_REQUIRED_DEVICES)
    missing = []
    for required in _REQUIRED_DEVICES:
        if not any(required.lower() in name.lower() for name in names):
            missing.append(required)
    return missing


def _ensure_engine_running(vm):
    """Restart VoiceMeeter audio engine only if it was shut down.

    Previously this restarted unconditionally with a 5s sleep on every mode
    switch. Now we restart only when needed:
      - _engine_was_shutdown flag set by release_audio() — fast path
      - fallback cheap-read probe (vm.strip[0].mute) catches external shutdown
    """
    global _engine_was_shutdown
    if not _engine_was_shutdown:
        try:
            _ = vm.strip[0].mute
            return  # engine alive, no restart needed
        except Exception:
            pass  # fall through to restart

    import time
    try:
        vm.command.restart()
        time.sleep(5)  # engine needs ~5s to reinitialize audio devices
    except Exception:
        pass
    _engine_was_shutdown = False


def _unmute_core(vm):
    """Unmute the strips and buses used by AI Professor.

    Strip 0: VB-Cable (call audio input)
    Strip 3: VAIO (TTS output)
    Bus A1 (index 0): headphones / monitor
    Bus B1 (index 3): call mic output
    Bus B2 (index 4): STT device output
    """
    # Unmute active strips
    vm.strip[0].mute = False
    vm.strip[3].mute = False
    # Unmute output buses
    vm.bus[0].mute = False   # A1 — headphones
    vm.bus[3].mute = False   # B1 — call mic
    vm.bus[4].mute = False   # B2 — STT


def meeting_mode() -> str:
    """Enable call-app routing: TTS->call mic, call audio->STT."""
    vm = _get_vm()
    if vm is None:
        return "VoiceMeeter not available"
    try:
        # Restart engine if it was shut down, then unmute
        _ensure_engine_running(vm)
        _unmute_core(vm)

        # Strip 0 (VB-Cable / call audio): route to A1 (monitor) + B2 (STT)
        vm.strip[0].A1 = True
        vm.strip[0].B1 = False
        vm.strip[0].B2 = True

        # Strip 3 (VAIO / TTS output): route to A1 (headphones) + B1 (call mic)
        vm.strip[3].A1 = True
        vm.strip[3].B1 = True
        vm.strip[3].B2 = False

        print("[VoiceMeeter] MEETING mode: TTS->call mic ON, call->STT ON")
        return "MEETING mode ON"
    except Exception as e:
        traceback.print_exc()
        return f"Error: {e}"


def local_mode() -> str:
    """Disable call routing: TTS to headphones only, no call feedback."""
    vm = _get_vm()
    if vm is None:
        return "VoiceMeeter not available"
    try:
        # Restart engine if it was shut down, then unmute
        _ensure_engine_running(vm)
        _unmute_core(vm)

        # Strip 0 (VB-Cable): A1 only, no B2 (STT won't get call audio)
        vm.strip[0].A1 = True
        vm.strip[0].B1 = False
        vm.strip[0].B2 = False

        # Strip 3 (VAIO / TTS output): A1 only, no B1 (call won't get TTS)
        vm.strip[3].A1 = True
        vm.strip[3].B1 = False
        vm.strip[3].B2 = False

        print("[VoiceMeeter] LOCAL mode: TTS->headphones only, call disconnected")
        return "LOCAL mode ON"
    except Exception as e:
        traceback.print_exc()
        return f"Error: {e}"


def toggle_agent_ears() -> str:
    """Toggle Strip 0 → B2 routing in Banana — the channel the STT process
    listens to. When OFF, the agent stops hearing the call audio entirely,
    while the host's monitor (Strip 0 → A1) keeps playing in headphones.
    Use this to talk to a volunteer privately (outside lecture flow)
    without the agent transcribing the exchange.

    Returns the new state as a short status string.
    """
    vm = _get_vm()
    if vm is None:
        return "VoiceMeeter not available"
    try:
        new_state = not bool(vm.strip[0].B2)
        vm.strip[0].B2 = new_state
        msg = "Уши агента: ВКЛ" if new_state else "Уши агента: ВЫКЛ"
        print(f"[VoiceMeeter] {msg}")
        return msg
    except Exception as e:
        traceback.print_exc()
        return f"Error: {e}"


def get_agent_ears_status() -> str:
    """Quick poll for UI label."""
    vm = _get_vm()
    if vm is None:
        return "—"
    try:
        return "Уши агента: ВКЛ" if bool(vm.strip[0].B2) else "Уши агента: ВЫКЛ"
    except Exception:
        return "—"


def get_status() -> str:
    """Return current routing mode, or a diagnostic message if setup is incomplete."""
    if not _check_vm_banana():
        return "VM не запущен"

    missing = _validate_devices()
    if missing:
        return f"VB-Cable отсутствует: {', '.join(missing)}"

    vm = _get_vm()
    try:
        call_stt = vm.strip[0].B2   # call audio -> STT
        call_tts = vm.strip[3].B1   # TTS -> call mic
        if call_stt and call_tts:
            return "MEETING"
        elif not call_stt and not call_tts:
            return "LOCAL"
        else:
            return f"CUSTOM (B2={call_stt}, B1={call_tts})"
    except Exception:
        return "VM не запущен"


def release_audio() -> str:
    """Release all VoiceMeeter routing and shutdown VoiceMeeter engine.

    Mutes all strips, resets bus assignments so Windows returns to
    default audio devices without VoiceMeeter holding exclusive locks.
    """
    vm = _get_vm()
    if vm is None:
        return "VoiceMeeter not available"
    try:
        # Mute all strips so nothing routes through VoiceMeeter
        for i in range(5):
            vm.strip[i].mute = True
            vm.strip[i].A1 = False
            vm.strip[i].B1 = False
            vm.strip[i].B2 = False

        # Mute all buses
        for i in range(5):
            vm.bus[i].mute = True

        # Shutdown VoiceMeeter engine to release exclusive device locks
        vm.command.shutdown()
        global _engine_was_shutdown
        _engine_was_shutdown = True

        print("[VoiceMeeter] RELEASED: all strips/buses muted, engine shutdown")
        cleanup()
        return "Audio RELEASED"
    except Exception as e:
        traceback.print_exc()
        cleanup()
        return f"Released with errors: {e}"


def cleanup():
    """Logout from VoiceMeeter API."""
    global _vm
    if _vm is not None:
        try:
            _vm.logout()
        except Exception:
            pass
        _vm = None
