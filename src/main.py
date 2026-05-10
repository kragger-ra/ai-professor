# -*- coding: utf-8 -*-
# Entry point for the AI Professor system.
# Provides a Gradio interface, spawns STT/TTS/agent processes, manages shared ctx_swarm state.
import argparse
import asyncio
import json
import logging
import multiprocessing as mp
import os
import signal
import sys
import time
import traceback
from datetime import datetime
from io import StringIO
from multiprocessing import Manager, Process
from threading import Thread

if __name__ == "__main__":
    mp.set_start_method("spawn")

_MAIN_START_TIME = time.time()


def _log_timing(msg: str):
    """Log message with elapsed time since program start"""
    elapsed = time.time() - _MAIN_START_TIME
    process_name = "main.py"
    if __name__ != "__main__":
        process_name += "/" + str(os.getpid())
    print(f"[T {elapsed:7.3f}s] [{process_name}] {msg}")


_log_timing("System imports done. Starting main import sequence")


from data_collectors.stt.speech_processor import run_voice_processor
from data_flow.ctx_handler import CtxHandler
from data_schema.ctx_structures import CtxSwarmType
from data_schema.structure_templates import create_ctx_swarm
from utils.format_helper import format_events_for_llm

logging.disable(logging.CRITICAL)
logging.getLogger("smolagents").setLevel(logging.DEBUG)

_log_timing("base modules imported")  # 1.6s total
import gradio as gr  # 3s to import!

_log_timing("gradio imported")
import pandas as pd  # 0.5s to import

_log_timing("pandas imported")
from config_schema.general import get_name, get_secret
from data_schema.structure_templates import (
    CTX_SWARM_EMPTY,
    REPO_DATA_PATH,
    REPO_RESOURCE_PATH,
)

_log_timing("Front imported")
from tts.simple_tts_handler import simple_tts_handler  # 0.7s to import

_log_timing("TTS imported")
from lecture.integration import LectureManager

_log_timing("Lecture module imported")
_log_timing("All imports done")  # 6.2s total

ctx_swarm: CtxSwarmType = CTX_SWARM_EMPTY

ctx_chat = []
ctx = None
Supervisor = None
processes = []
lecture_manager: LectureManager = None


def main_agent_need_starting():
    return True


def agent_start():
    global main_agent_need_starting
    if Supervisor is not None and Supervisor.is_running() == False:
        print("Agent activated")
        main_agent_need_starting = lambda: True
        Supervisor.run()


def activate_agent(checked=False):
    global main_agent_need_starting
    if checked:
        main_agent_need_starting = lambda: True
        return True
    else:
        if Supervisor is not None:
            print("Agent deactivated")
            main_agent_need_starting = lambda: False
            Supervisor.stop()
        return False


state = {
    "ai": None,
    "initialized": False,
    "start_time": None,
    "context": [],
    "running": False,
}


def init_system():
    if state["initialized"]:
        return "🟡 System already initialized"
    try:
        state["initialized"] = True
        state["running"] = True
        state["start_time"] = time.time()
        return "🟢 System initialized and ready"
    except Exception as e:
        return f"🔴 Initialization failed: {str(e)}"


def stop_system():
    CompleteShutDown()
    return "🔴 STOPPING ALL SYSTEM..."
    # if not state["initialized"]:
    #     return "🔴 System not initialized"
    # try:
    #     asyncio.run(state["ai"].cleanup())
    #     state["running"] = False
    #
    #     return "🟡 System stopped"
    # except Exception as e:
    #     return f"🔴 Stop failed: {str(e)}"


def process_message(message):
    if not state["initialized"] or not state["running"]:
        return "System not ready. Please initialize first."

    try:
        response = asyncio.run(
            state["ai"].process_input(text=message, context=state["context"])
        )

        state["context"].extend(
            [
                {
                    "role": "user",
                    "content": message,
                },
                {
                    "role": "assistant",
                    "content": response["reply"],
                },
            ]
        )

        return response["reply"]
    except Exception as e:
        return f"Error: {str(e)}"


def clear_chat():
    state["context"] = []
    return "", ""


def update_status():
    if state is None or not state.get("running", False):
        return "🔴 System Stopped", 0, 0, 0, 0
    uptime = time.time() - state["start_time"] if state["start_time"] else 0
    status = "🟢 Running" if state["running"] else "🔴 Stopped"
    return (status, round(uptime, 1), 0, 0, 0)


last_tts_audio = None
last_tts_converted = None
tts_generating = False

SELF_NAME = get_name()


def ctx_chat_example_add(text: str):
    try:
        ctx_handler.add_message(text)
    except Exception as e:
        print(f"Error in ctx_chat_example_add: {e}")


ctx_handler: CtxHandler = None


def clear_ctx_chat():
    if len(ctx_chat) > 0:
        ctx_chat[:] = []
        ctx_handler.add_message(
            "Контекст чата был очищен администратором. Начните диалог заново."
        )
    return True


demo = gr.Blocks(theme=gr.themes.Soft(), title="AI Professor")


class StreamToTextbox:
    def __init__(self, enable=True):
        self.log_content = StringIO()
        if enable:
            self.log_handler = logging.StreamHandler(self.log_content)
            self.log_handler.setFormatter(
                logging.Formatter("%(asctime)s - %(message)s")
            )
            logging.getLogger().addHandler(self.log_handler)
            self.old_stdout_write = sys.stdout.write
            sys.stdout.write = self._write

    def _write(self, text):
        try:
            self.old_stdout_write(text)
        except UnicodeEncodeError:
            safe = text.encode(sys.stdout.encoding or "ascii", errors="replace").decode(sys.stdout.encoding or "ascii")
            self.old_stdout_write(safe)
        self.log_content.write(text)
        return len(text)

    def get_logs(self):
        return self.log_content.getvalue()


stream_handler = StreamToTextbox(enable=True)


def get_logs():
    return stream_handler.get_logs()


def format_ctx_chat(ctx_compatible, isCtxChat=True):
    if not ctx_compatible or len(ctx_compatible) <= 0:
        if isCtxChat:
            return pd.DataFrame(
                [
                    {
                        "env": "system",
                        "user": "None",
                        "msg": "CTX CHAT EMPTY",
                        "date": datetime.now(),
                        "server": "None",
                        "serverMode": "None",
                        "filter_results": "N/A",
                    }
                ]
            )
        else:
            return pd.DataFrame([])

    ctx_to_out = list(ctx_compatible)

    if isinstance(ctx_to_out[0], str) and isCtxChat:
        ctx_to_out_new = [{"msg": x, "filter_results": "pending"} for x in ctx_to_out]
    else:
        ctx_to_out_new = ctx_to_out.copy()

    df = pd.DataFrame(ctx_to_out_new)
    # limit df by 50
    if len(df) > 50:
        df = df[-50:]
    if isCtxChat:
        required_columns = [
            "env",
            "user",
            "msg",
            "date",
            "server",
            "serverMode",
            "filter_results",
        ]
        for col in required_columns:
            if col == "filter_results":
                # covert obj to str
                df[col] = df[col].apply(lambda x: str(x))
            if col not in df.columns:
                df[col] = "N/A"
    return df


def save_ctx_chat_to_json(ctx_compatible):
    ctx_chat_save_dir = os.path.join(REPO_DATA_PATH, "debug")
    os.makedirs(ctx_chat_save_dir, exist_ok=True)
    save_path = os.path.join(ctx_chat_save_dir, "ctx_chat.json")
    try:
        data = list(ctx_compatible)
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4, sort_keys=True, default=str)
        msg = f"Saved {len(data)} events to {save_path}"
        print(msg)
        return msg
    except Exception as e:
        msg = f"Save error: {e}"
        print(msg)
        return msg


def print_ctx_chat(ctx_compatible):
    print(format_events_for_llm(ctx_compatible))


with demo:
    with gr.Group():
        gr.Markdown("Main agent")
        agent_btn = gr.Button("Start", variant="primary")
        agent_btn.click(fn=agent_start)

        stop_agent_btn = gr.Button("Stop", variant="secondary")
        stop_agent_btn.click(fn=activate_agent)

    with gr.Group():
        gr.Markdown("### Audio Routing (VoiceMeeter)")
        audio_status = gr.Textbox(value="—", label="Current mode", interactive=False)
        with gr.Row():
            meeting_btn = gr.Button("Созвон", variant="primary")
            local_btn = gr.Button("Локально", variant="secondary")
            release_btn = gr.Button("Отпустить", variant="stop")

        from utils.voicemeeter_control import (
            meeting_mode, local_mode, release_audio, get_status as vm_status,
        )

        meeting_btn.click(fn=meeting_mode, outputs=[audio_status])
        local_btn.click(fn=local_mode, outputs=[audio_status])
        release_btn.click(fn=release_audio, outputs=[audio_status])
        demo.load(fn=vm_status, outputs=[audio_status])

    with gr.Group():
        def _exit_all():
            release_audio()
            stop_system()
            return "Exiting..."

        exit_btn = gr.Button("EXIT (Release Audio + Shutdown)", variant="stop")
        exit_btn.click(fn=_exit_all)
    # Lecture mode controls
    with gr.Group():
        gr.Markdown("### Lecture Mode")
        with gr.Row():
            lecture_topic_input = gr.Textbox(
                value="RAG-системы: архитектура и применение",
                label="Тема лекции",
                scale=3,
            )
            lecture_duration = gr.Number(value=30, label="Минут", minimum=10, maximum=60, scale=1)
        with gr.Row():
            lecture_start_btn = gr.Button("Start Lecture", variant="primary")
            lecture_stop_btn = gr.Button("Stop Lecture", variant="stop")
            lecture_status = gr.Textbox(value="—", label="Status", interactive=False, scale=2)

        def _start_lecture(topic, duration):
            if Supervisor and hasattr(Supervisor, 'start_lecture'):
                from threading import Thread
                Thread(target=Supervisor.start_lecture, args=(topic, int(duration)), daemon=True).start()
                return f"Preparing: {topic} ({int(duration)} min)"
            return "Agent not running"

        def _stop_lecture():
            if Supervisor and hasattr(Supervisor, 'stop_lecture'):
                Supervisor.stop_lecture()
                return "Stopped"
            return "Agent not running"

        lecture_start_btn.click(fn=_start_lecture, inputs=[lecture_topic_input, lecture_duration], outputs=[lecture_status])
        lecture_stop_btn.click(fn=_stop_lecture, outputs=[lecture_status])

    gr.Markdown(
        """
            # AI Professor Interface

            Voice-based AI teaching assistant:
            - LLM backbone (Mistral API or local LM Studio)
            - RAG over course materials
            - Vosk TTS with emotional tags
            """
    )
    with gr.Tab(label="Control"):
        with gr.Row():
            control_queue_input = gr.Textbox(
                value="!interrupt_voice\n> Привет всем! *angry*",
                label="Control Command Input",
                submit_btn=True,
            )

            def control_queue_add(text: str):
                ctx_swarm["internal_command_queue"].put(
                    {"command": text, "env": "system"}
                )

            control_queue_input.submit(
                fn=control_queue_add, inputs=[control_queue_input]
            )
            gr.Markdown(
                """# Command line interface

                Direct input to the agent. Can be multiline.

                ```
                > text to speak and chat print *emotion*
                ```
                """,
                container=True,
            )
        with gr.Row():

            ctx_chat_output = gr.Dataframe(
                label="Chat context",
                headers=[
                    "env",
                    "user",
                    "msg",
                    "date",
                    "server",
                    "serverMode",
                    "filter_results",
                ],
            )
        with gr.Row():
            ctx_chat_input = gr.Textbox(
                value="Привет! Как дела?", label="Add new directive"
            )
            ctx_chat_input.submit(fn=ctx_chat_example_add, inputs=[ctx_chat_input])

            def selected_chat_callback(evt: gr.SelectData):
                print(
                    f"You selected {evt.value} at {evt.index} from {evt.target}; selected= {evt.selected}"
                )

            ctx_chat_output.select(selected_chat_callback)
            with gr.Row():
                ctx_submit_btn = gr.Button("Force check")
                ctx_answer_btn = gr.Button("Force answer")
                ctx_clear_btn = gr.Button("Clear")
                ctx_save_btn = gr.Button("Save json")
                ctx_print_btn = gr.Button("Print")
                ctx_answer_btn.click(
                    fn=lambda: (
                        None
                        if not (len(ctx_chat) > 0)
                        else process_message(ctx_chat[-1]["msg"])
                    ),
                )
                ctx_clear_btn.click(fn=clear_ctx_chat)
                ctx_submit_btn.click(
                    fn=lambda: format_ctx_chat(ctx_chat), outputs=[ctx_chat_output]
                )
                save_status = gr.Textbox(visible=False)
                ctx_save_btn.click(fn=lambda: save_ctx_chat_to_json(ctx_chat), outputs=[save_status])
                ctx_print_btn.click(fn=lambda: print_ctx_chat(ctx_chat))

        with gr.Accordion("Automatic TTS info", open=True) as accordion:
            with gr.Row():
                with gr.Column(scale=1):
                    ctx_audio_status = gr.Textbox(value="Offline", label="TTS status")
                with gr.Column(scale=1):
                    ctx_audio_initial = gr.Audio(value=None, label="Initial TTS")
                with gr.Column(scale=1):
                    ctx_audio_converted = gr.Audio(value=None, label="Converted")
            with gr.Row():
                tts_queue_output = gr.Dataframe(
                    label="TTS queue",
                )
                accordion.expand(
                    fn=lambda: format_ctx_chat(
                        list(ctx_swarm["tts_queue"]).copy(), False
                    ),
                    outputs=[tts_queue_output],
                )
                with gr.Row():
                    tts_queue_input = gr.Textbox(
                        value="Привет всем!", label="tts queue input"
                    )
                    _EMOTIONS = [
                        "neutral", "happy", "sad", "angry",
                        "scared", "whispering", "disgusted", "sarcastic",
                    ]
                    tts_queue_emo = gr.Dropdown(
                        choices=_EMOTIONS + ["interrupt"],
                        label="tts queue emotion",
                        allow_custom_value=True,
                    )

                    def tts_queue_add(text: str, emo: str):
                        ctx_swarm["tts_queue"].append({"text": text, "emotion": emo})

                    tts_queue_input.submit(
                        fn=tts_queue_add, inputs=[tts_queue_input, tts_queue_emo]
                    )
            # with gr.Accordion("Chat queue", open=False) as accordion:
            chat_queue_output = gr.Dataframe(
                label="Chat queue",
            )
            accordion.expand(
                fn=lambda: format_ctx_chat(
                    [{"msg": m} for m in list(ctx_swarm["chat_queue"]).copy()], False
                ),
                outputs=[chat_queue_output],
            )
            with gr.Row():
                chat_queue_input = gr.Textbox(
                    value="@test mm", label="chat queue input"
                )

                def chat_queue_add(text: str):
                    ctx_swarm["chat_queue"].append(text)

                chat_queue_input.submit(fn=chat_queue_add, inputs=[chat_queue_input])

    with gr.Tab(label="Lecture"):
        with gr.Row():
            lecture_start_btn = gr.Button("Start Lecture", variant="primary")
            lecture_stop_btn = gr.Button("Stop & Summarize", variant="stop")
        lecture_status = gr.Textbox(label="Status", value="Not recording", interactive=False)
        lecture_segments = gr.Number(label="Segments recorded", value=0, interactive=False)
        lecture_summary_box = gr.Textbox(
            label="Last summary", lines=12, interactive=False
        )

        def _lecture_start():
            if lecture_manager is None:
                return "LectureManager not initialized"
            return lecture_manager.start_lecture()

        def _lecture_stop():
            if lecture_manager is None:
                return "LectureManager not initialized"
            return lecture_manager.stop_lecture()

        def _lecture_tick():
            if lecture_manager is None:
                return "Not initialized", 0, ""
            status = "Recording..." if lecture_manager.is_recording else "Stopped"
            return status, lecture_manager.segment_count, lecture_manager.last_summary

        lecture_start_btn.click(fn=_lecture_start, outputs=[lecture_status])
        lecture_stop_btn.click(fn=_lecture_stop, outputs=[lecture_summary_box])

        timer_lecture = gr.Timer(value=5)
        timer_lecture.tick(
            fn=_lecture_tick,
            outputs=[lecture_status, lecture_segments, lecture_summary_box],
            queue=False,
        )

    with gr.Tab(label="Metrics"):
        metrics_weekly = gr.Dataframe(label="Weekly stats")
        metrics_recent = gr.Dataframe(label="Recent interactions (last 10)")

        def _metrics_refresh():
            if lecture_manager is None:
                return pd.DataFrame(), pd.DataFrame()
            weekly = lecture_manager.metrics.get_weekly_stats()
            recent = lecture_manager.metrics.get_recent_interactions(limit=10)
            return pd.DataFrame(weekly), pd.DataFrame(recent)

        metrics_refresh_btn = gr.Button("Refresh metrics")
        metrics_refresh_btn.click(fn=_metrics_refresh, outputs=[metrics_weekly, metrics_recent])

        timer_metrics = gr.Timer(value=15)
        timer_metrics.tick(
            fn=_metrics_refresh,
            outputs=[metrics_weekly, metrics_recent],
            queue=False,
        )

    with gr.Accordion("System Stats", open=False):
        with gr.Row():
            llm_time = gr.Number(
                label="LLM Response Time (s)", value=0, interactive=False
            )
            tts_time = gr.Number(
                label="TTS Generation Time (s)", value=0, interactive=False
            )
            play_time = gr.Number(
                label="Audio Playback Time (s)", value=0, interactive=False
            )
            filter_result = gr.Textbox(
                label="Filter Status", value="🟢 Active", interactive=False
            )

    debug_logs = None
    # with gr.Group():
    #     with gr.Row():
    #         debug_logs = gr.Textbox(
    #             label="Console logs (stdout)",
    #             interactive=True,
    #             lines=10,
    #             value=get_logs,
    #             every=1,
    #             autoscroll=True,
    #         )
    #     with gr.Row():
    #         logs_btn = gr.Button("Update logs", variant="primary")
    #         logs_btn.click(fn=get_logs, outputs=[debug_logs])

    # Connect to any button that should trigger log updates
    # init_btn.click(
    #    fn=lambda: stdout_wrapper.get_logs(),
    #    outputs=[debug_logs]
    # )
    timer_tick_kwargs = {"queue": False}
    timer_ctx = gr.Timer(value=3)

    def upd_ctx_queues():
        return format_ctx_chat(
            [{"msg": m} for m in list(ctx_swarm["chat_queue"]).copy()].copy(), False
        ), format_ctx_chat(list(ctx_swarm["tts_queue"]).copy(), False)

    timer_ctx.tick(
        fn=upd_ctx_queues,
        outputs=[chat_queue_output, tts_queue_output],
        **timer_tick_kwargs,
        max_batch_size=1,
        concurrency_limit=1,
    )

    # timer_logs = gr.Timer(value=2)
    # timer_logs.tick(
    #    fn=get_logs,
    #    outputs=[debug_logs]
    # )
# demo.queue()
#    return demo


def timeout_handler():
    time.sleep(10)
    raise KeyboardInterrupt


def create_timeout():
    Thread(target=timeout_handler).start()


def safe_terminate(process: Process):
    if process and process.is_alive():
        try:
            create_timeout()
            process.join()
        except KeyboardInterrupt:
            print("Process join timeout")
        except Exception as e:
            print(f"[{process.name}] Error while joining process: {e}")
            traceback.print_exc()
        finally:
            if process.is_alive():
                process.terminate()


def CompleteShutDown(signal=None, frame=None):
    print("ИНИЦИАЛИЗИРУЕМ ВЫХОД!!!")
    if ctx is not None:
        ctx.ThreadsActived = False
        ctx_swarm["env"]["actived"] = False
        process: Process
        for process in processes:
            process.terminate()
        time.sleep(1)
        print("Manager shutdown")
        manager.shutdown()
        time.sleep(0.1)
        os.abort()


# demo = None


def parse_args():
    parser = argparse.ArgumentParser(description="AI Professor")
    parser.add_argument(
        "-r",
        "--no-stt",
        action="store_true",
        help="Disable speech-to-text",
    )
    parser.add_argument(
        "-s",
        "--stop-auto",
        action="store_true",
        help="Do not start agent automatically",
    )
    parser.add_argument(
        "-w",
        "--warmup",
        action="store_true",
        default=False,
        help="Do TTS warmup after start",
    )
    return parser.parse_args()


_log_timing("All pre-main functions defined")


def main():
    global demo, ctx_chat, ctx_swarm, ctx_handler, ctx, processes, manager, Supervisor, SELF_NAME, processes, lecture_manager

    _log_timing("=== MAIN FUNCTION STARTED ===")
    args = parse_args()
    _log_timing(f"[main.py] ENTERED __main__. PROGRAM ARGS: {str(args)}")

    for signal_type in (
        signal.SIGABRT,
        signal.SIGFPE,
        signal.SIGILL,
        signal.SIGINT,
        signal.SIGSEGV,
        signal.SIGTERM,
    ):
        signal.signal(signal_type, CompleteShutDown)

    _log_timing("Creating Manager and ctx_swarm")
    manager = Manager()
    ctx_swarm = create_ctx_swarm(manager)
    _log_timing("ctx_swarm created")  # 6s!!! (because of processes?)
    ctx_swarm["env"]["debug_print_prompt"] = True
    ctx_chat = ctx_swarm["ctx_chat"]
    if args.warmup:
        ctx_swarm["tts_queue"].extend(
            [
                {"text": "Добро пожаловать на лекцию.", "emotion": "happy"},
                {"text": "Это грустная тема.", "emotion": "sad"},
                {"text": "Внимание, это важно!", "emotion": "angry"},
            ]
        )
    ctx_handler = CtxHandler(ctx_swarm)

    lecture_manager = LectureManager(ctx_swarm)
    _log_timing("LectureManager initialized")

    # Initialize VoiceMeeter routing before TTS starts.
    # AUDIO_MODE=meeting for call apps (Discord/Meet/Teams/Telegram).
    # AUDIO_MODE=local for headphones-only mode through VoiceMeeter.
    # AUDIO_MODE=none (or off/skip) to bypass VM entirely — TTS plays direct
    # to the OS default device. Use this for laptop/local tests where VM
    # would grab Sound Blaster in WASAPI exclusive mode.
    _vm_mode = os.getenv("AUDIO_MODE", "local").lower()
    if _vm_mode in ("none", "off", "skip", ""):
        _log_timing("VoiceMeeter skipped (AUDIO_MODE=none)")
    else:
        try:
            from utils.voicemeeter_control import meeting_mode, local_mode
            if _vm_mode == "meeting":
                _vm_status = meeting_mode()
            else:
                _vm_status = local_mode()
            _log_timing(f"VoiceMeeter initialized ({_vm_mode}): {_vm_status}")
        except Exception as e:
            _log_timing(f"VoiceMeeter init failed (non-critical): {e}")

    _log_timing("Starting TTS_Proc process")
    TTS_Proc = Process(
        target=simple_tts_handler,
        args=(ctx_swarm,),
    )
    TTS_Proc.start()
    processes.append(TTS_Proc)
    _log_timing("TTS_Proc started")

    DO_BLOCK = True
    _log_timing(
        f"Core model config: {os.getenv('CORE_LLM_MODEL_NAME')} @ {os.getenv('CORE_LLM_API_BASE')}"
    )
    print(
        "[main.py] core model = ",
        os.getenv("CORE_LLM_MODEL_NAME"),
        "on adress",
        os.getenv("CORE_LLM_API_BASE"),
    )
    start_stt = not args.no_stt
    # bool(get_secret("SPEECH_TO_TEXT_START"))
    if start_stt:
        print("[main.py] Speech to Text feature is enabled.")
        _log_timing("Starting STTProc process")
        from data_collectors.stt.mic_stt_handler import mic_stt_handler
        # In meeting mode, STT listens to Voicemeeter Out B2 (call audio)
        if os.getenv("AUDIO_MODE", "local").lower() == "meeting":
            stt_device_name = "Voicemeeter Out B2"
            print(f"[main.py] MEETING mode: STT listening to {stt_device_name}")
        else:
            stt_device_name = os.getenv("SOUND_DEVICE_IN", "")
        STTProc = Process(
            target=mic_stt_handler,
            kwargs={"ctx_swarm": ctx_swarm, "audio_device_name": stt_device_name},
        )
        STTProc.start()
        processes.append(STTProc)
        _log_timing("STTProc started")
    else:
        print("[main.py] Speech to Text DISABLED!")
    # DO NOT RUN AGENT HERE, WAIT GRADIO
    _log_timing("All processes started, preparing agent selection")
    print("== RUNNING MAIN ENTRY POINT: main.py == \n ** BEFORE GRADIO LAUNCH ** \n")
    AGENT_AUTO_START = not args.stop_auto
    print("[main.py] ======== AGENT_AUTO_START = " + str(AGENT_AUTO_START))
    _log_timing(f"Agent auto-start: {AGENT_AUTO_START}")
    _log_timing("Importing CoreAgent")
    from agent.core_agent import CoreAgent

    _log_timing("Creating CoreAgent supervisor")
    Supervisor = CoreAgent(ctx_swarm, ctx_handler)
    _log_timing("CoreAgent supervisor created")

    # Inject RAG vocabulary into ctx_swarm for STT correction
    if Supervisor.rag_model:
        rag_vocab = Supervisor.rag_model.get_vocabulary()
        ctx_swarm["env"]["rag_vocabulary"] = list(rag_vocab)
        print(f"[main.py] RAG vocabulary injected: {len(rag_vocab)} terms")
    _log_timing("RAG vocabulary injected")

    _log_timing("Launching Gradio interface")
    demo.launch(
        favicon_path=os.path.join(REPO_RESOURCE_PATH, "Pictures", "appico.ico"),
        server_name="0.0.0.0",
        server_port=int(os.getenv("GRADIO_SERVER_PORT", "22228")),
        inbrowser=True,
        prevent_thread_lock=True,
    )
    _log_timing("Gradio interface launched")  # 5s!!

    # Polling thread: drains interaction logs and syncs lecture summary
    def _interaction_poller():
        while ctx_swarm["env"].get("actived", True):
            try:
                # Drain interaction log
                data = ctx_swarm["env"].get("last_interaction")
                if data is not None:
                    lecture_manager.log_interaction(
                        query=data.get("query", ""),
                        response=data.get("response", ""),
                        response_time_ms=data.get("response_time_ms", 0),
                        rag_sources=data.get("rag_sources"),
                        emotion=data.get("emotion", "neutral"),
                    )
                    ctx_swarm["env"]["last_interaction"] = None

                # Sync current lecture summary so CoreAgent can read it
                if lecture_manager.is_recording:
                    ctx_swarm["env"]["lecture_summary"] = (
                        lecture_manager.get_current_summary()
                    )
                else:
                    # Keep last summary available even after stop
                    if lecture_manager.last_summary:
                        ctx_swarm["env"]["lecture_summary"] = (
                            lecture_manager.last_summary
                        )
            except Exception as e:
                print(f"[interaction_poller] error: {e}")
            time.sleep(2)

    Thread(target=_interaction_poller, daemon=True).start()
    _log_timing("Interaction poller thread started")

    print("== main.py CODEBLOCK AFTER GRADIO LAUNCH ==")
    # starting agent NOW
    _log_timing("Entering agent control loop")

    while AGENT_AUTO_START:

        try:
            if not Supervisor.is_running():
                if main_agent_need_starting():
                    _log_timing("Starting main supervisor agent")
                    print("== main.py STARTING MAIN SUPERVISOR AGENT ==")
                    agent_start()
                    _log_timing("Main supervisor agent started")
        except Exception as e:
            print("== main.py AGENT MAIN LOOP ERROR ==", e)
            traceback.print_exc()
            time.sleep(15)
        _log_timing(f"Agent main loop stopping; manual={main_agent_need_starting()}")
        print(
            "== main.py AGENT MAIN LOOP STOPPING==; manual = "
            + str(main_agent_need_starting())
        )
        try:
            Supervisor.stop()
            _log_timing("Supervisor stopped")
        except Exception as e:
            print("== main.py AGENT STOP ERROR ==", e)
            traceback.print_exc()
        time.sleep(10)
        # Thread(target=lambda: agent_start, daemon=True).start()
    print("== main.py AGENT TERMINATED (THIS IS PROGRAM END) ==")
    while True:
        # for program not exit
        time.sleep(10)
    # agent_start()
    # asyncio.run(demo)
    # asyncio.run(gradio_launch())
    # if gr.NO_RELOAD:
    #    while DO_BLOCK:
    #        time.sleep(5)


if __name__ == "__main__":
    main()
