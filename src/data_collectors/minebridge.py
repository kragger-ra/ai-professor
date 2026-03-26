# TODO refactor this
import copy
import logging
import multiprocessing
import os
import queue
import sys
import threading
import time
import traceback
from datetime import datetime

from py4j.java_gateway import CallbackServerParameters, JavaGateway

if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
    from data_schema.structure_templates import create_ctx_swarm

from config_schema.general import get_name, get_secret
from data_flow.ctx_handler import CtxHandler
from data_schema.ctx_structures import CtxSwarmType, FilterRequest
from utils.minecraft_helper import parse_nearby_players, primitivize_nearby_players
from utils.time_helper import eztime, tm

# Disable unused py4j logging (but may need for debug)
logger = logging.getLogger("py4j")
logger.setLevel(logging.FATAL)


SELF_NAME = get_name()  # in future should be SELF_MINECRAFT_NICKNAME env,
# but for now SELF_MINECRAFT_NICKNAME should be equal to SELF_NAME


def chat_queue_handler(
    mc: JavaGateway, ctx_swarm: CtxSwarmType, main_thread_actived={"actived": True}
):

    while ctx_swarm["env"]["actived"] and main_thread_actived["actived"]:
        if ctx_swarm["game"]["ingame"]:
            chat_queue_handle(mc, ctx_swarm)
        time.sleep(0.1)


def chat_queue_handle(mc, ctx_swarm):
    ctx_chat_queue = ctx_swarm["chat_queue"]
    ctx_game = ctx_swarm["game"]
    delta = (
        datetime.now()
        - tm(ctx_game.get("mc_last_chat_interact", "2024-01-01 00:00:00"))
    ).total_seconds()
    # print("DELTA KGSDJGKL " + str(round(delta, 2)), "LEN CHAT Q", len(ctx_chat_queue))
    if (len(ctx_chat_queue) > 0) and (
        datetime.now()
        - tm(ctx_game.get("mc_last_chat_interact", "2024-01-01 00:00:00"))
    ).total_seconds() >= 0.5:
        try:

            chat_msg = ctx_chat_queue[0].strip()

            is_command = False
            special_symbol = "@"
            try:
                if chat_msg[0] in ["$", "@", "/"]:
                    special_symbol = chat_msg[0]
                    is_command = True
                    # chat_msg = chat_msg[1:]
            except Exception:
                is_command = False

            if (
                is_command
                or (
                    datetime.now()
                    - tm(
                        ctx_game.get(
                            "mc_last_chat_interact",
                            "2024-01-01 00:00:00",
                        )
                    )
                ).total_seconds()
                >= 6
            ):
                try:
                    ctx_chat_queue.pop(0)

                    print(
                        "[MC DEBUG] chat_queue msg, queue",
                        chat_msg,
                        ctx_chat_queue,
                    )
                    if chat_msg:
                        if is_command:

                            CMD_SIGN_TO_TO_OPERATOR = {"$": "@"}
                            if special_symbol == "@":
                                cmd = (
                                    CMD_SIGN_TO_TO_OPERATOR.get(
                                        special_symbol,
                                        special_symbol,
                                    )
                                    + chat_msg[1:]
                                )
                                print("[MC] RUN EXECUTOR: '" + cmd + "'")
                                mc.RunInnerCommand(cmd)
                                ctx_game["mc_last_chat_interact"] = eztime()
                            else:
                                cmd = (
                                    CMD_SIGN_TO_TO_OPERATOR.get(
                                        special_symbol,
                                        special_symbol,
                                    )
                                    + chat_msg[1:]
                                )
                                print("[MC] RUN CMD: '" + cmd + "'")
                                mc.ChatMessage(chat_msg)
                                ctx_game["mc_last_chat_interact"] = eztime()
                        else:
                            # TODO NEW UNTESTED
                            # FILTER THE PRINTING MESSAGE AND CHECK
                            # IF IT IS ACCEPTABLE
                            filter_enabled = ctx_swarm.get("filter", {}).get(
                                "chat_filter_enabled", True
                            )
                            is_nonmoderatable_server = any(
                                [
                                    srv in ctx_game.get("server", "")
                                    for srv in ["musteryworld"]
                                ]
                            )
                            if is_nonmoderatable_server:
                                filter_enabled = False
                            acceptable = False
                            if filter_enabled:
                                print(
                                    "putting to filter queue",
                                    ctx_game.get("server", ""),
                                )
                                try:
                                    ctx_swarm["filter_input_queue"].put(
                                        FilterRequest(
                                            text=chat_msg,
                                            filter_type="basic",
                                        ),
                                        timeout=5,
                                    )
                                    acceptable = ctx_swarm["filter_output_queue"].get(
                                        timeout=5
                                    )["acceptable"]
                                except queue.Empty:
                                    print(
                                        "[MC] CHAT MSG "
                                        + chat_msg
                                        + " NOT SENT: FILTER TIMEOUT"
                                    )
                                except Exception as e:
                                    print(
                                        "[MC] CHAT MSG "
                                        + str(chat_msg)
                                        + " NOT SENT: FILTER ERROR",
                                        e,
                                    )
                                    traceback.print_exc()
                            else:
                                acceptable = True
                            print(
                                "[DEBUG SRV CHAT MSG] ",
                                ctx_game.get("server", ""),
                                "<---",
                            )
                            if acceptable:
                                need_global_chat = any(
                                    [
                                        srv in ctx_game.get("server", "")
                                        for srv in ["musteryworld"]
                                    ]
                                )
                                # ctx_game.get("server", "") in [
                                #    "mc.musteryworld.net"
                                # ]  # for bedwars / other team modes
                                if need_global_chat:
                                    chat_msg = "!" + chat_msg
                                # TODO find another workaround for global chat
                                # potentially DANGEROUS if SYMBOL LIMIT exceeds
                                # not precize, need precize options for another modes
                                mc.ChatMessage(chat_msg)
                                # print("FJSKG SDJG JFK GHJKFD JHFDJKH")
                                ctx_game["mc_last_chat_interact"] = eztime()
                    else:
                        print("[MC] CHAT MSG EMPTY:" + chat_msg)
                except Exception as err:
                    print(
                        "[mineBridge] error sending msg in MC chat",
                        err,
                    )
                    traceback.print_exc()
                    raise err
                    # in case of restarting minebridge
                # finally:
                # try:
                #    ctx_chat_queue.pop(0)

            # ctx_chat_queue.pop(0)
        except Exception as err:
            print("VERY BAD CHAT PRINT ERR", err)
            traceback.print_exc()
        except KeyboardInterrupt:
            print("[ Mine Bridge ] MAIN KEYBOARD INTERRUPT")
            raise KeyboardInterrupt


def mine_bridge_handler(ctx_swarm: CtxSwarmType, debug: bool = False):
    internal_chat_msgs = []
    internal_command_queue = []
    internal_audio_queue = []
    internal_events = []
    own_chat_list = []
    ctx_chat_queue = ctx_swarm.get("chat_queue", [])
    java_gateway = None
    ctx_env = ctx_swarm["env"]
    ctx_game = ctx_swarm["game"]
    debug = debug
    Razrabs = get_secret("RAZRABS")
    Nicknames = get_secret("BOT_NICKNAMES").split(",")
    handler = CtxHandler(ctx_swarm)
    main_thread_actived = {"actived": True}
    while ctx_env["actived"]:
        try:
            # ctx.lastmsg = "hz"
            print("запуск python callback")

            class PythonCallback(object):
                def isStarted(self):
                    return True

                def onVoiceFeed(self, playerName, voiceBytes):
                    internal_audio_queue.append(
                        (
                            playerName,
                            voiceBytes,
                        )
                    )
                    # print("[MC] GOT AUDIOFEED BYTES FOR "+ str(playerName) + " bytes " + str(voiceBytes))

                def onCaptchaSolveRequest(self, image_bytes):
                    print("GOT CAPTCHA REQUEST!")
                    # requestCaptchaResolve(image_bytes)

                def onUpdateServerInfo(self, infoMas=None):
                    for cho in infoMas:
                        ctx_game[cho] = copy.deepcopy(infoMas[cho])
                        print("GameInfoUpdated", infoMas[cho])

                def onVerifedChat(self, msgMas=None):
                    if msgMas is None:
                        pass
                        # msgMas = {}
                    else:
                        # print("RECIEVED BIG MSG:",msgMas.get("user",""),'>',msgMas.get("msg",""),' CLAN=',msgMas.get("clan","")," NONEXIST=",msgMas.get("gdfjkgdf",""))
                        msgDict = {
                            "user": msgMas.get("user", ""),
                            "msg": msgMas.get("msg", ""),
                        }
                        # pre, rank, user, msg, clan, team, server, serverMode, chat_type, precision
                        fields = [
                            "pre",
                            "rank",
                            "clan",
                            "team",
                            "server",
                            "serverMode",
                            "chat_type",
                            "precision",
                        ]
                        for field in fields:
                            if msgMas.get(field, "") is not None:
                                if msgMas.get(field, "").strip() != "":
                                    msgDict[field] = msgMas.get(field, "")
                        internal_chat_msgs.append(msgDict)
                    return msgMas

                def onChatMessage(self, msg=""):
                    # print(string)
                    # ctx.lastmsg = msg
                    # print('recieved msg >>',msg)
                    return msg

                def onDeath(self, killer="unknown"):
                    if (
                        killer is not None
                        and killer.strip() != ""
                        and killer != "unknown"
                        and killer != "неизвестный"
                    ):
                        event_data = {
                            "type": "death",
                            "user": killer,
                            "happiness_score": -3,
                        }
                        event_data["isEvent"] = True
                        event_data["description"] = " killed you!!! =("
                        internal_events.append(event_data)

                def onKill(self, killed="unknown"):
                    if (
                        killed is not None
                        and killed.strip() != ""
                        and killed != "unknown"
                    ):
                        event_data = {
                            "type": "kill",
                            "user": killed,
                            "happiness_score": 1,
                            "filter_results": {"acceptable": True},
                        }
                        event_data["isEvent"] = True
                        event_data["description"] = " was killed by you =)"
                        internal_events.append(event_data)

                def agentCommandRequest(self, command):
                    if command is not None:
                        internal_command_queue.append(command)
                        return "command sent"
                    return "command is None"

                def onAutoclefEvent(self, event_type, description):
                    try:
                        if (
                            description is not None
                            and description.strip() != ""
                            and description != "unknown"
                            and event_type is not None
                            and event_type.strip() != ""
                            and event_type != "unknown"
                        ):
                            event_data = {
                                "type": event_type,
                                "user": next(
                                    iter(Nicknames), SELF_NAME
                                ),  # Nicknames.get(0, "NetTyan"),
                                "happiness_score": 0,
                                "filter_results": {"acceptable": True},
                            }
                            event_data["isEvent"] = True
                            event_data["description"] = " " + description  # oh...
                            internal_events.append(event_data)
                    except:
                        pass

                def onDamage(self, amount=0):
                    pass
                    # print('MINECRAFT DAMAGE =',str(amount))

                def onDamageConfirmed(
                    self, damaged="unknown", attacker="unknown", amount=0
                ):
                    try:
                        description = "damaged by " + attacker + " for " + str(amount)
                        # print("MINECRAFT DAMAGE =", damaged, attacker, amount)
                        if (
                            description is not None
                            and description.strip() != ""
                            and description != "unknown"
                        ):
                            event_data = {
                                "type": "mc_damaged",
                                "user": damaged,
                                "happiness_score": 1,
                                "filter_results": {"acceptable": True},
                            }
                            event_data["isEvent"] = True
                            event_data["description"] = " " + description  # oh...
                            internal_events.append(event_data)
                    except:
                        pass

                class Java:
                    implements = ["adris.altoclef.PythonCallback"]

            cb = PythonCallback()
            java_gateway = JavaGateway(
                callback_server_parameters=CallbackServerParameters(),
                python_server_entry_point=cb,
                start_callback_server=True,
                # python_proxy_port=25333
            )

            mc = java_gateway.entry_point

            def ingame(loop=True):
                if loop:
                    needLog = False
                    fail = True
                    while fail and ctx_env["actived"]:
                        try:
                            ez = mc.inGame()
                            fail = False
                            if not ctx_game["mc_started"]:
                                ctx_game["mc_started"] = True
                            if needLog:
                                print("BRIDGE CONNECTION SUCCESSFUL")
                            ctx_game["ingame"] = ez
                            return ez
                        except KeyboardInterrupt:
                            print("[ Mine Bridge ] MAIN KEYBOARD INTERRUPT")
                            raise KeyboardInterrupt
                        except BaseException as err:
                            # print('INGAME ERROR', err)
                            if needLog:
                                print("BRIDGE CONNECTION FAILED", err)
                            ctx_game["mc_started"] = False
                            ctx_game["ingame"] = False
                            time.sleep(5)
                            # return False
                        finally:
                            needLog = False  # False
                else:
                    try:
                        ez = mc.inGame()
                        if not ctx_game["mc_started"]:
                            ctx_game["mc_started"] = True
                        # print('CONNECTION SUCCESSFUL')
                        return ez
                    except KeyboardInterrupt:
                        print("[ Mine Bridge ] MAIN KEYBOARD INTERRUPT")
                        raise KeyboardInterrupt
                    except BaseException as err:
                        print(
                            f"ERROR BRIDGE когда чекал запущенный майн. Его видимо нет в списке процессов или ещё че похуже {err}"
                        )
                        ctx_game["mc_started"] = False
                        return False

            print("[minebridge] waiting 1 sec, then ingame check")
            time.sleep(1)
            print("[minebridge] ingame =", ingame())
            ctx_swarm["vtube"]["game_yawspeed"] = 0.0
            ctx_swarm["vtube"]["game_pitchspeed"] = 0.0
            AngSpeedTableP = [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]
            AngSpeedTableY = [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]
            print("[minebridge] getting initial info dict")

            initial_info_dict = mc.getServerInfoDict()
            for key in initial_info_dict:
                ctx_game[key] = initial_info_dict[key]
                print(
                    "[minebrige] [infoDict] [initial]",
                    key,
                    "->",
                    initial_info_dict[key],
                )

            def updater():
                ii = 0
                while ctx_env["actived"]:
                    time.sleep(0.01)
                    # print('DEBUG ACTIVED')
                    if len(internal_audio_queue) > 0:
                        for user, audio in internal_audio_queue:
                            # print(
                            #     "[minebridge] Agent command, processing audio",
                            #     audio,
                            # )
                            ctx_swarm["audio_feed_queue"].put(
                                {"user": user, "audio": audio, "env": "minecraft"}
                            )
                        internal_audio_queue[:] = []
                    if len(internal_command_queue) > 0:
                        for command in internal_command_queue:
                            print(
                                "[minebridge] Agent command, processing command",
                                command,
                            )
                            ctx_swarm["internal_command_queue"].put(
                                {"command": command, "env": "minecraft"}
                            )
                        internal_command_queue[:] = []
                    if len(internal_events) > 0:
                        for event in internal_events:
                            event["date"] = eztime()
                            event["processing_timestamp"] = time.time_ns()
                            event["env"] = "minecraft"
                            # TODO lock
                            # TODO check duplicates

                            # TODO UNTESTED!!!! WARN #1
                            if handler.add_message(event):
                                pass
                                # print(
                                #     f"[{datetime.now().strftime('%H:%M:%S')}] [MC EVENT]",
                                #     str(event),
                                # )
                            else:
                                pass
                                # print(
                                #     f"[{datetime.now().strftime('%H:%M:%S')}] [MC EV DUPE] ",
                                #     str(event.get("type", "none_type")),
                                #     str(event.get("description", "")),
                                # )
                            # ctx_chat.append(event)
                        internal_events[:] = []
                    if len(internal_chat_msgs) > 0:
                        for msg in internal_chat_msgs:
                            # print('Processing msgsmas', msg)
                            msg["date"] = eztime()
                            msg["processing_timestamp"] = time.time_ns()
                            msg["env"] = "minecraft"
                            # pre, rank, user, msg, clan, team, server, serverMode, chat_type, precision
                            username = msg.get("user", "")
                            if not username:
                                username = ""
                            if username in Nicknames:
                                print(
                                    "Встречено собственное сообщение (тоже вносится)",
                                    username,
                                    "вносим в базу",
                                    msg["msg"],
                                )
                                own_chat_list.append(msg)
                                msg["self"] = True
                                ### ctx_chatOwn = ctx_chatOwn + [msg]
                                # ctx_game["mc_last_chat_interact"] = eztime()
                            if True:
                                # else:

                                message_l = msg["msg"].lower()
                                player = username

                                if player in Razrabs:
                                    if ingame(loop=False):
                                        try:
                                            if message_l.find("за мной") != -1:
                                                mc.RunInnerCommand(
                                                    f"""@follow {player}"""
                                                )
                                            elif message_l.find("вперед") != -1:
                                                mc.RunInnerCommand("@test killall")
                                            elif message_l.find("мочи") != -1:
                                                mc.RunInnerCommand(
                                                    f"""@punk {msg["msg"].split(' ')[1]}"""
                                                )
                                            elif message_l.find("стоп") != -1:
                                                mc.RunInnerCommand("@stop")
                                        except KeyboardInterrupt:
                                            print(
                                                "[ Mine Bridge ] MAIN KEYBOARD INTERRUPT"
                                            )
                                            raise KeyboardInterrupt
                                        except BaseException as err:
                                            print(
                                                "ERROR WHILE EXEC RAZRAB COMMAND", err
                                            )
                                # TODO UNTESTED!!!! WARN #2
                                if handler.add_message(msg):
                                    print(
                                        f"[{datetime.now().strftime('%H:%M:%S')}] [MC CHAT]",
                                        username,
                                        ">",
                                        msg["msg"],
                                    )
                                else:
                                    print(
                                        f"[{datetime.now().strftime('%H:%M:%S')}] [MC CHAT DUPE] ",
                                        str(msg.get("type", "none_type")),
                                        str(msg.get("description", "")),
                                    )
                                # ctx_chat.append(msg)
                        internal_chat_msgs[:] = []
                    if ingame():
                        # try:
                        #     captchaSolved = captchaQueueOutput.get(block=False)
                        #     if captchaSolved is not None:
                        #         print(
                        #             "[BRIDGE CAPTCHA] GET CAPTCHA OUTPUT ! Entering in chat >>",
                        #             captchaSolved,
                        #             "<<",
                        #         )
                        #         e.CaptchaSolvedSend(
                        #             captchaSolved["result"],
                        #             float(captchaSolved["predict"]),
                        #         )
                        # except queue.Empty:
                        #     pass
                        ii += 1
                        if ii > 30:
                            try:

                                state = mc.getState()
                                # print("Old get state", state)
                                # ctx_swarm["voice"]["is_speaking"]
                                # TODO untested
                                if ctx_swarm["voice"].get("speak_entry"):
                                    emotion = ctx_swarm["voice"]["speak_entry"].get(
                                        "emotion", "neutral"
                                    )
                                    mc.setEmotionalState(emotion)
                                g_block = mc.getGroundBlock()
                                g_item = mc.getHeldItem()
                                g_tasks = mc.getTaskChainString()
                                g_players = list(mc.getPlayersInfo(10))
                                # TEST save bytes to png
                                # screen_buffer = mc.getScreenshot()
                                # this works only after 14 april 2025 autoclef release
                                # with open('test_screenshot.png', 'wb') as f:
                                #     f.write(screen_buffer)
                                #     print("screen saved to " + str(f.name))
                                # time.sleep(50)
                                # if screen_buffer is not None:
                                #     screen_buffer
                                g_players_pythonic = primitivize_nearby_players(
                                    g_players
                                )
                                ctx_game.update(
                                    {
                                        "task_chain": str(g_tasks),
                                        "ground_block": str(g_block),
                                        "held_item": str(g_item),
                                        "nearby_players": list(
                                            parse_nearby_players(g_players_pythonic)
                                        ),
                                        # ready string version
                                        "near_threats": list(
                                            mc.nearestPlayersInfo(3)
                                        ).copy(),
                                        "last_talking_player": str(
                                            mc.getLastTalkingPlayer()
                                        ),
                                        "hasActiveTask": bool(mc.hasActiveTask()),
                                    }
                                )
                                # print("Last talking player:", str(mc.getLastTalkingPlayer()))
                                # print(json.dumps([v["distance"] for v in parse_nearby_players(g_players)], indent=2, ensure_ascii=False))
                                # print(json.dumps(parse_nearby_players_dict(g_players), indent=2, ensure_ascii=False))
                                # print(json.dumps([v["distance"] for k, v in parse_nearby_players_dict(g_players).items()], indent=2, ensure_ascii=False))
                            except KeyboardInterrupt:
                                print("[ Mine Bridge ] MAIN KEYBOARD INTERRUPT")
                                raise KeyboardInterrupt
                            except Exception as e:
                                print("EXCEPTION WHEN GETTING MC INFO", e)
                                traceback.print_exc()
                            ii = 0
                        if len(own_chat_list) > 80:
                            own_chat_list.pop(0)
                        goalRotation = mc.getGoalRotation()
                        if goalRotation is None:
                            AngSpeedTableP.append(mc.getPitch())
                            AngSpeedTableY.append(mc.getYaw())
                            if len(AngSpeedTableP) > 10:
                                AngSpeedTableP.pop(0)
                            if len(AngSpeedTableY) > 10:
                                AngSpeedTableY.pop(0)

                            ctx_swarm["vtube"]["game_yawspeed"] = (
                                -AngSpeedTableY[5] + AngSpeedTableY[0]
                            )
                            ctx_swarm["vtube"]["game_pitchspeed"] = (
                                -AngSpeedTableP[5] + AngSpeedTableP[0]
                            )
                        else:
                            # print('ыы',e.ChatMessage("ПриветМир"))
                            ctx_swarm["vtube"]["game_yawspeed"] = -goalRotation.getYaw()
                            ctx_swarm["vtube"][
                                "game_pitchspeed"
                            ] = goalRotation.getPitch()

                    else:
                        # print('НЕ В ИГРЕ!!!')
                        time.sleep(2)

            debug_additional_data = {"bow_spotted": 0}
            server_info_kwargs = {"mode": "skywars"}  # {"mode": "survival"}
            player_collecting = "kilbro"

            def debug_listener():
                from data_collectors.experiments.predictorcompetition.collect_mc_data import (
                    create_collector,
                )

                collector = create_collector(
                    r"D:\Pets\NetTyan\Python\NetTyanRepo\NetTyan\data\predictors"
                )
                print("Collecting started.")
                try:
                    ent = mc.getEntity(player_collecting)
                    collector.init_entity(ent)
                except KeyboardInterrupt:
                    print("[ Mine Bridge ] MAIN KEYBOARD INTERRUPT")
                    raise KeyboardInterrupt
                except Exception as e:
                    print("[debug bgridge err],", e)
                    traceback.print_exc()
                while ctx_env["actived"]:
                    time.sleep(0.01)
                    if ingame():
                        # time.sleep(5)

                        # print("debug run")
                        try:
                            ent = mc.getEntity(player_collecting)
                            collector.on_tick(ent, **debug_additional_data)
                            # print("DEBUG GETTING ENTITY", ent)
                            # print(ent.getPos())
                            # print(ent.getHealth())
                        except KeyboardInterrupt:
                            print("[ Mine Bridge ] MAIN KEYBOARD INTERRUPT")
                            raise KeyboardInterrupt
                        except Exception as e:
                            print("[debug bgridge err],", e)
                            traceback.print_exc()
                        # print(e.getPlayersInfo())
                        # print("@test killall")
                        # e.ExecuteCommand("@test killall")
                        # time.sleep(3)
                        # print("стоп")
                        # e.ExecuteCommand("@stop")
                        # time.sleep(1)
                print("Finishing run...")

            print("UPDATER STARTING...")
            updaterThread = threading.Thread(target=updater)
            updaterThread.start()
            chat_queue_thread = threading.Thread(
                target=chat_queue_handler,
                kwargs={
                    "mc": mc,
                    "ctx_swarm": ctx_swarm,
                    "main_thread_actived": main_thread_actived,
                },
            )
            chat_queue_thread.start()
            if debug:
                for i in range(10):
                    print("DEBUG LISTENER STARTING...")
                    ctx_env["actived"] = True
                    listner_thread = threading.Thread(target=debug_listener)
                    listner_thread.start()
                    time.sleep(10)
                    ctx_env["actived"] = False
                    listner_thread.join()
                    print(f"Phase {str(i)} ended. Running next")
            updaterThread.join()
        except Exception as err:
            print("Mine Bridge Произошла большая ошибка >", err)
            print("ТЕКСТ ОШИБКИ", traceback.format_exc())
            time.sleep(5)
        except KeyboardInterrupt:
            print("[ Mine Bridge ] MAIN KEYBOARD INTERRUPT")
            raise KeyboardInterrupt
        finally:
            print(
                "[ Mine Bridge ] Достигнут конец процесса Mine Bridge, перезапускаем его..."
            )
            try:
                main_thread_actived["actived"] = False
                if java_gateway is not None:
                    java_gateway.shutdown_callback_server()
                    java_gateway.shutdown()
                    time.sleep(1)
                    java_gateway = None
            except KeyboardInterrupt:
                print("[ Mine Bridge ] MAIN KEYBOARD INTERRUPT>>")
                raise KeyboardInterrupt
            except BaseException as err:
                print(f"MineBridge: не удалось завершить gateway {err}")
                time.sleep(1)


if __name__ == "__main__":
    logger.setLevel(logging.DEBUG)
    manager = multiprocessing.Manager()
    ctx_swarm = create_ctx_swarm(manager=manager)

    ctx_swarm["chat_queue"].extend(
        ["/randomcommand123", "привет", "пвалопрова дловалор"]
    )
    print(ctx_swarm)
    mine_bridge_handler(ctx_swarm)
    # mine_bridge_handler(ctx_swarm, True)  # for collecting data now
