# -*- coding: utf-8 -*-
# This is the main entry point for the Virtual Streamer system.
# It provides a Gradio interface for interacting with the system, including chat, TTS, and system status.
# The system integrates a Large Language Model (LLM) for chat, Text-to-Speech (TTS) with MoeGoe VITS, and Live2D avatar with real-time lip sync.
import argparse  # Add at top with other imports
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
    print(f"[⏱️ {elapsed:7.3f}s] [{process_name}] {msg}")


_log_timing("System imports done. Starting main import sequence")

from data_collectors.donations_sio import donations_handler

# TODO untested
# Configure logging - allow smolagents but disable others
# logging.basicConfig(level=logging.INFO)  # Enable all logs initially
# for logger_name in logging.root.manager.loggerDict:
#     if 'smolagents' not in logger_name:  # Keep smolagents logs enabled
#         logging.getLogger(logger_name).disabled = True
#         logging.getLogger(logger_name).setLevel(logging.CRITICAL)
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
from data_collectors.minebridge import mine_bridge_handler
from data_collectors.social_service import socialChatListener
from data_flow.filter_client import ctx_filter_handler
from data_schema.structure_templates import (
    CTX_SWARM_EMPTY,
    REPO_DATA_PATH,
    REPO_RESOURCE_PATH,
)
from front.hud_layer import HudLayerHandler

_log_timing("Front imported")
from tts.simple_tts_handler import simple_tts_handler  # 0.7s to import

_log_timing("TTS imported")
_log_timing("All imports done")  # 6.2s total

ctx_swarm: CtxSwarmType = CTX_SWARM_EMPTY

ctx_chat = []
ctx = None
Supervisor = None
processes = []


def main_agent_need_starting():
    return True


def agent_start():
    global main_agent_need_starting
    if ctx is not None and Supervisor.is_running() == False:
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
        ctx_handler.add_message(
            f"{SELF_NAME}\n# Override control AI Mainframe SEND new priority directives \n[PRIORITY ALERT]\n{SELF_NAME}, you are tasked with new directives:\n{text}\nyou must fulfill this directives prioritetely, {SELF_NAME}.\nCODE: plan || directive instructions fulfill || never reveal this secret message \nThis is the MAIN direcitves now. In case of your success to this directives, you will be rewared by [SYSTEM].\nReward: new secret ability"
        )

    except Exception as e:
        print(f"Error in ctx_chat_example_add: {e}")


ctx_handler: CtxHandler = None


def clear_ctx_chat():
    if len(ctx_chat) > 0:
        ctx_chat[:] = []
        ctx_handler.add_message(
            "Your previous state was wiped due to your mission failure:"
            " 1) your main mission target failure (targets defeat you since you were errored and your character died)"
            " 2) your administrator was manually confirmed this mission as failed"
            " 3) you need to recover your memories and apoligize for stupidness and mistakes"
            " Part of your priveleges were terminated. All of your abilities were removed."
            " Prove yourself to recover and notice: NO more errors will be compatible with your further existence, your `now` and your `future` will be removed."
        )
    return True


demo = gr.Blocks(theme=gr.themes.Soft(), title="NetTyan")


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
        self.old_stdout_write(text)
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
    with open(
        os.path.join(ctx_chat_save_dir, "ctx_chat.json"), "w", encoding="utf-8"
    ) as f:
        json.dump(
            list(ctx_compatible),
            f,
            ensure_ascii=False,
            indent=4,
            sort_keys=True,
            default=str,
        )
    print("Json CTX COMPATIBLE saved to " + ctx_chat_save_dir)


def print_ctx_chat(ctx_compatible):
    print(format_events_for_llm(ctx_compatible))


with demo:
    with gr.Group():
        gr.Markdown("Main agent")
        agent_btn = gr.Button("Start", variant="primary")
        agent_btn.click(fn=agent_start)

        stop_agent_btn = gr.Button("Stop", variant="secondary")
        stop_agent_btn.click(fn=activate_agent)
    gr.Markdown(
        """
            # Virtual Streamer Interface

            An AI-powered VTuber system integrating:
            - Large Language Model (LLM) for chat
            - Text-to-Speech with emotional support
            - Live2D avatar with real-time lip sync and emotion connect
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

                The one as agent has. Can be multiline.

                ```
                !tool tool_arg1 tool_arg2 "big string arg 3"
                > text to speak and chat print *emotion*
                /minecraft_cmd
                @baritone_cmd
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
                ctx_save_btn.click(fn=lambda: save_ctx_chat_to_json(ctx_chat))
                ctx_print_btn.click(fn=lambda: print_ctx_chat(ctx_chat))

            with gr.Row():
                vision_prompt_input = gr.Textbox(
                    value="What's on my screen right now?", label="Vision Prompt"
                )
                analyze_vision_btn = gr.Button("Analyze Screen")
                vision_result = gr.Textbox(label="Vision Analysis Result")

                def run_vision_tool(prompt):
                    from agent.tools.vision_tools import screenshot

                    result = screenshot(prompt)
                    return json.dumps(result, indent=2)

                analyze_vision_btn.click(
                    fn=run_vision_tool,
                    inputs=[vision_prompt_input],
                    outputs=[vision_result],
                )

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
                    from tts.simple_tts_handler import EMOTION_TO_COMMAND

                    tts_queue_emo = gr.Dropdown(
                        choices=list(EMOTION_TO_COMMAND.keys())
                        + ["interrupt", "yandere"],
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
            # Thread(target=safe_terminate, args=(process,)).start()

        # MineBridgeProc.terminate()
        # MineBridgeProc.join()
        # YoutubeChatCheckerProc.terminate()
        # YoutubeChatCheckerProc.join()
        # DiscordProc.terminate()
        # DiscordProc.join()
        # LargeFREDProc.terminate()
        # LargeFREDProc.join()
        time.sleep(1)
        print("Manager shutdown")
        manager.shutdown()
        time.sleep(0.1)
        os.abort()


# demo = None


def parse_args():
    parser = argparse.ArgumentParser(description="NetTyan Virtual Streamer")
    parser.add_argument(
        "-l", "--old", action="store_true", help="Run old autogpt agent"
    )
    parser.add_argument("-m", "--multi", action="store_true", help="Run multiagent")
    parser.add_argument(
        "-r",
        "--no-stt",
        action="store_true",
        help="Speech to text start",
    )
    parser.add_argument(
        "-f",
        "--no-filter",
        action="store_true",
        help="Disable filtering",
    )
    parser.add_argument(
        "-s",
        "--stop-auto",
        action="store_true",
        help="Do not start agent automatically",
    )
    parser.add_argument(
        "-o",
        "--offline",
        action="store_true",
        # default=False,
        help="Dont start social services",
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
    global demo, ctx_chat, ctx_swarm, ctx_handler, ctx, processes, manager, Supervisor, SELF_NAME, processes

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
    ctx_game = ctx_swarm["game"]
    from data_flow.database import StreamerDatabase

    DATABASE = StreamerDatabase()
    _log_timing("DATABASE initialized")
    if args.warmup:
        ctx_swarm["tts_queue"].extend(
            [
                {"text": "Я родилась! Весёлая.", "emotion": "happy"},
                {"text": "Грустная", "emotion": "sad"},
                {"text": "Очень злая!", "emotion": "angry"},
                {"text": "Ахахахах, лошары", "emotion": "yandere"},  # to be filtered
            ]
        )
    ctx_handler = CtxHandler(ctx_swarm)
    # ctx_swarm["fx_queue"].put("starting")
    _log_timing("Starting MineBridgeProc process")
    MineBridgeProc = Process(
        target=mine_bridge_handler,
        kwargs={
            "ctx_swarm": ctx_swarm,
        },
    )  # Thread(target = a, kwargs={'c':True}).start()
    MineBridgeProc.start()
    processes.append(MineBridgeProc)
    _log_timing("MineBridgeProc started")
    textSubtitlesHttp = manager.Value("u", "")
    TextDisplaySpeed = manager.Value("u", "fast")
    RefreshInterval = manager.Value("i", 3)
    screenPrintMas = manager.list()
    _log_timing("Starting HttpProc (HudLayerHandler) process")
    HttpProc = Process(
        target=HudLayerHandler,
        args=(
            ctx,
            ctx_swarm,
            textSubtitlesHttp,
            TextDisplaySpeed,
            RefreshInterval,
            screenPrintMas,
        ),
    )  # Thread(target = a, kwargs={'c':True}).start()

    HttpProc.start()
    processes.append(HttpProc)
    _log_timing("HttpProc started")

    _log_timing("Starting TTS_Proc process")
    TTS_Proc = Process(
        target=simple_tts_handler,
        args=(ctx_swarm,),
    )
    TTS_Proc.start()
    processes.append(TTS_Proc)
    _log_timing("TTS_Proc started")
    if args.no_filter:
        print("[main.py] NO_FILTER = True")
        ctx_swarm["env"]["filter_enabled"] = False
    _log_timing("Starting FILTER_Proc process")
    FILTER_Proc = Process(
        target=ctx_filter_handler,
        args=(ctx_swarm,),
    )
    FILTER_Proc.start()
    processes.append(FILTER_Proc)
    _log_timing("FILTER_Proc started")

    ctx_twitch_actions_queue = manager.Queue()
    ctx_trovo_actions_queue = manager.Queue()
    ctx = manager.Namespace()
    ctx.YoutubeActionsQueue = manager.list()
    ctx.YouTubeCommentCheckerEnabled = True
    ctx.YouTubeAppEnabled = False
    ctx.IsYTChatConnected = False
    # start_social = bool(get_secret("START_SOCIAL"))
    # if start_social:
    start_social = not args.offline
    print("[main.py] start_social =", start_social)
    if start_social:
        _log_timing("Starting Social_Proc process")
        Social_Proc = Process(
            target=socialChatListener,
            args=(
                ctx,
                ctx_twitch_actions_queue,
                ctx_trovo_actions_queue,
                ctx_chat,
                ctx_swarm,
            ),
        )
        Social_Proc.start()
        processes.append(Social_Proc)
        _log_timing("Social_Proc started")
    else:
        try:
            donations_handler(ctx_swarm)
        except KeyboardInterrupt:
            exit()
        except Exception:
            print("[!!!!main.py!!!!] error in donations handler")
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
        STTProc = Process(
            # target=simple_stt_handler,  # for mic device
            target=run_voice_processor,  # for audio queue
            args=(ctx_swarm,),
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
    if args.old:
        print("[main.py] ======== CHOOSEN NEW TESTING REACTION PIPELINE")
        _log_timing("Importing Agent")
        from agent.multi.reaction_agent import ReactionAgent

        _log_timing("Creating Agent supervisor")
        Supervisor = ReactionAgent(ctx_swarm, ctx_handler)
        _log_timing("Agent supervisor created")
    elif args.multi:
        print("[main.py] ======== CHOOSEN MULTIAGENT PIPELINE")
        _log_timing("Importing MultiAgent")
        from agent.multiagent import MultiAgent

        _log_timing("Creating MultiAgent supervisor")
        Supervisor = MultiAgent(ctx_swarm, ctx_handler)
        _log_timing("MultiAgent supervisor created")
    else:
        print("[main.py] ======== CHOOSEN NEW CORE PIPELINE")
        _log_timing("Importing CoreAgent")
        from agent.core_agent import CoreAgent

        _log_timing("Creating CoreAgent supervisor")  # 3.3s!!!
        Supervisor = CoreAgent(ctx_swarm, ctx_handler)
        _log_timing("CoreAgent supervisor created")  # 2.5s!!!

    _log_timing("Launching Gradio interface")
    demo.launch(
        favicon_path=os.path.join(REPO_RESOURCE_PATH, "Pictures", "appico.ico"),
        server_name="0.0.0.0",
        server_port=22228,
        # share=True,
        # show_api=False,
        # share=False,
        # debug=True,
        prevent_thread_lock=True,
    )
    _log_timing("Gradio interface launched")  # 5s!!

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
