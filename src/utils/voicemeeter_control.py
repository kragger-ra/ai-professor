"""VoiceMeeter Banana audio routing for AI Professor.

Three modes:
  ZOOM:    TTS -> VoiceMeeter VAIO -> A1 (headphones) + B1 (Zoom mic)
           Zoom speaker -> VB-Cable -> Strip 0 -> A1 (monitor) + B2 (STT)

  DIRECT:  TTS -> VoiceMeeter VAIO -> A1 (headphones only)
           Strip 0 B2 off (STT uses fifine mic directly)

  RELEASE: Mute all, shutdown engine, return devices to Windows.

IMPORTANT: zoom_mode() and direct_mode() always unmute the relevant
strips and buses, so they work correctly even after a release_audio().
"""

import traceback

_vm = None


def _get_vm():
    global _vm
    if _vm is None:
        try:
            import voicemeeterlib
            _vm = voicemeeterlib.api("banana")
            _vm.login()
        except Exception as e:
            print(f"[VoiceMeeter] Failed to connect: {e}")
            return None
    return _vm


def _ensure_engine_running(vm):
    """Restart VoiceMeeter audio engine if it was shut down.

    After release_audio() calls vm.command.shutdown(), the process stays
    alive but the engine is dead. We must restart it before changing routing.
    """
    import time
    try:
        vm.command.restart()
        time.sleep(5)  # engine needs ~5s to reinitialize audio devices
    except Exception:
        pass  # restart may fail if engine is already running — that's fine


def _unmute_core(vm):
    """Unmute the strips and buses used by AI Professor.

    Strip 0: VB-Cable (Zoom audio input)
    Strip 3: VAIO (TTS output)
    Bus A1 (index 0): headphones / monitor
    Bus B1 (index 3): Zoom mic output
    Bus B2 (index 4): STT device output
    """
    # Unmute active strips
    vm.strip[0].mute = False
    vm.strip[3].mute = False
    # Unmute output buses
    vm.bus[0].mute = False   # A1 — headphones
    vm.bus[3].mute = False   # B1 — Zoom mic
    vm.bus[4].mute = False   # B2 — STT


def zoom_mode() -> str:
    """Enable Zoom routing: TTS->Zoom, Zoom->STT."""
    vm = _get_vm()
    if vm is None:
        return "VoiceMeeter not available"
    try:
        # Restart engine if it was shut down, then unmute
        _ensure_engine_running(vm)
        _unmute_core(vm)

        # Strip 0 (VB-Cable / Zoom audio): route to A1 (monitor) + B2 (STT)
        vm.strip[0].A1 = True
        vm.strip[0].B1 = False
        vm.strip[0].B2 = True

        # Strip 3 (VAIO / TTS output): route to A1 (headphones) + B1 (Zoom mic)
        vm.strip[3].A1 = True
        vm.strip[3].B1 = True
        vm.strip[3].B2 = False

        print("[VoiceMeeter] ZOOM mode: TTS->Zoom ON, Zoom->STT ON")
        return "ZOOM mode ON"
    except Exception as e:
        traceback.print_exc()
        return f"Error: {e}"


def direct_mode() -> str:
    """Disable Zoom routing: TTS to headphones only, no Zoom feedback."""
    vm = _get_vm()
    if vm is None:
        return "VoiceMeeter not available"
    try:
        # Restart engine if it was shut down, then unmute
        _ensure_engine_running(vm)
        _unmute_core(vm)

        # Strip 0 (VB-Cable): A1 only, no B2 (STT won't get Zoom audio)
        vm.strip[0].A1 = True
        vm.strip[0].B1 = False
        vm.strip[0].B2 = False

        # Strip 3 (VAIO / TTS output): A1 only, no B1 (Zoom won't get TTS)
        vm.strip[3].A1 = True
        vm.strip[3].B1 = False
        vm.strip[3].B2 = False

        print("[VoiceMeeter] DIRECT mode: TTS->headphones only, Zoom disconnected")
        return "DIRECT mode ON"
    except Exception as e:
        traceback.print_exc()
        return f"Error: {e}"


def get_status() -> str:
    """Return current routing mode based on strip state."""
    vm = _get_vm()
    if vm is None:
        return "VoiceMeeter N/A"
    try:
        zoom_stt = vm.strip[0].B2   # Zoom audio -> STT
        zoom_tts = vm.strip[3].B1   # TTS -> Zoom mic
        if zoom_stt and zoom_tts:
            return "ZOOM"
        elif not zoom_stt and not zoom_tts:
            return "DIRECT"
        else:
            return f"CUSTOM (B2={zoom_stt}, B1={zoom_tts})"
    except Exception:
        return "ERROR"


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
