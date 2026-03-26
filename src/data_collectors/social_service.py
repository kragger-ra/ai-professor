# Standard library imports
import asyncio
import json
import logging
import os
import sys
import threading
import time
import traceback
from datetime import datetime

# Third-party imports
import requests
from dotenv import load_dotenv

# from google_auth_oauthlib.flow import InstalledAppFlow
# from googleapiclient.discovery import build
from twitchAPI.chat import Chat, ChatCommand, ChatEvent, ChatMessage, ChatSub, EventData
from twitchAPI.oauth import UserAuthenticator
from twitchAPI.twitch import Twitch
from twitchAPI.type import AuthScope

# Local imports
if __name__ == "__main__":
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config_schema.general import get_secret
from data_collectors.sheepchat_sio import SheepChatClient
from data_schema.structure_templates import REPO_DATA_PATH, create_ctx_swarm
from utils.time_helper import eztime

CREDENTIALS_DIR = os.path.join(REPO_DATA_PATH, "credentials")
YOUTUBE_CLIENT_SECRET_FILE = os.path.join(
    CREDENTIALS_DIR, "youtube", "client_secret.json"
)
TWITCH_TOKEN_FILE = os.path.join(CREDENTIALS_DIR, "twitch", "token.json")
YT_STREAM_API_KEY = get_secret("YOUTUBE_STREAM_API_KEY")
YT_CHANNEL_ID = get_secret("YOUTUBE_CHANNEL_ID")
proxy = get_secret("proxy")

# print("[debug social service] imported")


def socialChatListener(
    ctx, twitch_actions_queue, trovo_actions_queue, ctx_chat, ctx_swarm=None
):
    from data_collectors.donations_sio import donations_handler

    ctx_env = ctx_swarm["env"]
    donations_handler_thread = threading.Thread(
        target=donations_handler,
        args=(
            ctx_swarm,
            True,
        ),
        daemon=True,
    )
    donations_handler_thread.start()
    print("Donations handler started!")
    if proxy:
        os.environ["http_proxy"] = proxy
        os.environ["HTTP_PROXY"] = proxy
        os.environ["https_proxy"] = proxy
        os.environ["HTTPS_PROXY"] = proxy
    load_dotenv()
    print("[PRE PRE PRE INIT YT + TWITCH] yt listener start.... (loaded dotenv)")

    youtube = None
    liveChatId = None

    # import time

    # pip install pytchat
    # Set API key and YouTube video ID
    # добывается в гугл клауде https://console.cloud.google.com/apis/

    # Set YouTube channel ID КАНАЛ ОТКУДА БЕРЕМ СТРИМ. ID канала узнать можно через код элемента поиск channel id
    # [TEST] The Good Life Radio x Sensual Musique https://www.youtube.com/channel/UChs0pSaEoNLV4mevBFGaoKA

    # Get channel information
    # чисто url самого канала и его описания иконки и т д
    # url = f"https://www.googleapis.com/youtube/v3/channels?part=snippet%2CcontentDetails%2Cstatistics&id={CHANNEL_ID}&key={API_KEY}"

    # юрл стрима текущего

    YoutubeStreamURL = f"https://www.googleapis.com/youtube/v3/search?part=snippet&channelId={YT_CHANNEL_ID}&eventType=live&type=video&key={YT_STREAM_API_KEY}"

    # YoutubeStreamURL = "https://www.googleapis.com/youtube/v3/search?part=snippet&channelId=UChs0pSaEoNLV4mevBFGaoKA&eventType=live&type=video&key=AIzaSyB6KA5SaWUgmGk5FQ-qZBUmCyF1001P0ZM"
    # print("****\n" + YoutubeStreamURL1 + "\n" + YoutubeStreamURL + "\n****")

    TWITCH_APP_ID = get_secret("TWITCH_APP_ID")
    TWITCH_APP_SECRET = get_secret("TWITCH_APP_SECRET")
    TWITCH_TARGET_CHANNEL = get_secret("TWITCH_TARGET_CHANNEL")

    TWITCH_USER_SCOPE = [AuthScope.CHAT_READ, AuthScope.CHAT_EDIT]

    twitch_chat = None
    twitch_ready = False

    async def twitch_chat_reply(ninp: str):
        nonlocal twitch_chat
        try:
            await twitch_chat.send_message(TWITCH_TARGET_CHANNEL, ninp)
        except BaseException as err:
            print(
                "[TWITCH LIVECHAT ERR] не удалось отправить сообщение",
                ninp,
                "в twitch chat потому что",
                err,
            )

    async def on_ready(ready_event: EventData):
        nonlocal twitch_ready
        print("[TWTICH BOT LOAD] Bot is ready for work, joining channels")

        await ready_event.chat.join_room(TWITCH_TARGET_CHANNEL)
        await twitch_chat_reply(
            f"[AI] [CONNECTED->{datetime.now().strftime('%M:%S')}] Подключен twitch! Всем привет, система работает =)"
        )
        twitch_ready = True

    async def on_message(msg: ChatMessage):
        twitch_username = msg.user.name
        # print(f'[TWITCH CHAT {msg.room.name}] {msg.user.name}: {msg.text}')
        msg = {
            "env": "twitch",
            "msg": msg.text,
            "user": twitch_username,
            "processing_timestamp": time.time_ns(),
            "date": eztime(),
        }
        # pre, rank, user, msg, clan, team, server, serverMode, chat_type, precision
        if twitch_username in get_secret("SELF_TWITCH_USERNAME"):
            print(
                "[YT] Встречено собственное сообщение",
                msg["user"],
                "вносим в базу",
                msg["msg"],
            )
            # ctx_chatOwn.append(msg)
            ###ctx_chatOwn = ctx_chatOwn + [msg]
            # ctx.LastMineChatInteract = datetime.now()
        else:
            print(
                f"[{datetime.now().strftime('%H:%M:%S')}] [TWITCH CHAT]",
                msg["user"],
                ">",
                msg["msg"],
            )
            ctx_chat.append(msg)

    # this will be called whenever someone subscribes to a channel ПЛАТНАЯ ПОДПИСКА
    async def on_sub(sub: ChatSub):
        print(
            f"[TWITCH +SUB] New subscription in {sub.room.name}, type: {sub.sub_plan}, msg: {sub.sub_message}"
        )

    # this will be called whenever the !reply command is issued
    async def test_command(cmd: ChatCommand):
        if len(cmd.parameter) == 0:
            await cmd.reply("you did not tell me what to reply with")
        else:
            await cmd.reply(f"{cmd.user.name}: {cmd.parameter}")

    def load_twitch_token():
        """Load saved Twitch tokens from file"""
        try:
            if os.path.exists(TWITCH_TOKEN_FILE):
                with open(TWITCH_TOKEN_FILE, "r") as f:
                    data = json.load(f)
                    return data.get("token"), data.get("refresh_token")
        except Exception as e:
            print(f"[TWITCH] Error loading token: {e}")
        return None, None

    def save_twitch_token(token, refresh_token):
        """Save Twitch tokens to file"""
        try:
            os.makedirs(os.path.dirname(TWITCH_TOKEN_FILE), exist_ok=True)
            with open(TWITCH_TOKEN_FILE, "w") as f:
                json.dump({"token": token, "refresh_token": refresh_token}, f)
            return True
        except Exception as e:
            print(f"[TWITCH] Error saving token: {e}")
            return False

    async def run_twitch_bot():
        nonlocal twitch_chat
        twitch = await Twitch(TWITCH_APP_ID, TWITCH_APP_SECRET)

        # Try to load existing tokens
        token, refresh_token = load_twitch_token()

        if token and refresh_token:
            try:
                # Try to use existing tokens
                await twitch.set_user_authentication(
                    token, TWITCH_USER_SCOPE, refresh_token
                )
                print("[TWITCH] Successfully authenticated with saved tokens")
            except:
                # If tokens are invalid, get new ones
                token = refresh_token = None
                print("[TWITCH] Saved tokens invalid, getting new ones...")

        if not token or not refresh_token:
            # Get new tokens if needed
            auth = UserAuthenticator(twitch, TWITCH_USER_SCOPE)
            token, refresh_token = await auth.authenticate()
            save_twitch_token(token, refresh_token)
            await twitch.set_user_authentication(
                token, TWITCH_USER_SCOPE, refresh_token
            )

        twitch_chat = await Chat(twitch)
        twitch_chat.register_event(ChatEvent.READY, on_ready)
        twitch_chat.register_event(ChatEvent.MESSAGE, on_message)
        twitch_chat.register_event(ChatEvent.SUB, on_sub)
        twitch_chat.register_command("reply", test_command)
        twitch_chat.start()

    # lets run our setup
    # asyncio.run(run_twitch_bot())
    print("НАЧИНАЕМ ЧЕКАТЬ ЮТУБ...")

    def twitch_actions_executor_func():
        while True:
            if twitch_chat is not None and twitch_ready:
                t_act_inp = twitch_actions_queue.get()
                t_act = t_act_inp.get("action", "")
                try:
                    if t_act == "reply":
                        asyncio.run(
                            twitch_chat_reply("[AI] " + t_act_inp.get("msg", "пустота"))
                        )
                        time.sleep(1)
                    # elif t_act == "ban":
                    #    if channel_id:
                    #        print('user', channel_id)
                    #        tempban(liveChatId, channel_id=channel_id,
                    #                timee=t_act_inp.get("bantime", 20))
                    #        time.sleep(1)
                    #    else:
                    #        print("БАН НЕ ВЫДАН ТАК КАК НЕ СООБЩЕНО ID")
                except BaseException as err:
                    print("TWICH action print queue err, q=", t_act)
                    print("ОШИБКА ВЫВОДА В ЧАТ TWITCH! ", err)
                    print("ТЕКСТ ОБ***Й ОШИБКИ", traceback.format_exc())
            time.sleep(1)

    def run_twitch_bot_func():
        asyncio.run(run_twitch_bot())
        tt = threading.Thread(target=twitch_actions_executor_func, daemon=True)
        tt.start()

    # print('LELL')
    t = threading.Thread(target=run_twitch_bot_func, daemon=True)
    # loop = asyncio.get_event_loop()
    # loop.run_until_complete(run_twitch_bot())

    #
    twitch_started = False
    # выше так было
    # а теперь стало тк тест надо же сделать

    # t.start()
    # twitch_started = True
    # from TrovoClient import trovo_client_thread
    # print('STARTING YT CHECKER! 00')
    trovo_started = False
    # trovo_thread = trovo_client_thread(ctx_chat, trovo_actions_queue)
    print("STARTING YT CHECKER! 01")
    youtubeMessagesList = []
    youtubeUnreadList = []

    def onSheepChatMsg(msg):
        sheep_type = msg.get("type", "")
        if sheep_type == "youtube":
            msg["username"] = msg["nick"]
            msg["message"] = msg["text"]
            onYoutubeChatMessage(msg)

    def onYoutubeChatMessage(msg):
        # print("DEBUG", msg)
        try:
            ytname = msg["username"]
            message = msg["message"]
            msg = {
                "env": "youtube",
                "msg": message,
                "user": ytname,
                # "youtube_user_channel_id": msg["userId"],
                # "youtube_moderator": c.author.isChatModerator,
                "processing_timestamp": time.time_ns(),
                "date": eztime(),
            }

            print(
                f"[{datetime.now().strftime('%H:%M:%S')}] [YOUTUBE CHAT] {ytname}: {message}"
            )
            ctx_chat.append(msg)

            ctx.IsYTChatConnected = True
            time.sleep(2)
        except BaseException as err:
            print("2ОШИБКА ПОДКЛЮЧЕНИЯ! ПОХОЖЕ СТРИМ ЗАКОНЧИЛСЯ2! ", err)
            print("ТЕКСТ ОБ***Й ОШИБКИ", traceback.format_exc())
            print("\n=== КОНЕЦ ОШИБКИ ====")
            ctx.IsYTChatConnected = False
            time.sleep(10)

    sc_client = SheepChatClient(callback=onSheepChatMsg)

    while ctx_env["actived"]:
        if ctx_env["youtube_social_enabled"]:
            print(
                "[PRE INIT YT] включил коммент чекер? вход в ветку ютуба и твича для запуска непосредственно"
            )
            # if not trovo_started:
            #     try:
            #         trovo_thread.start()
            #     except BaseException as err:
            #         print('[TROVO]ОШИБКА ПОДКЛЮЧЕНИЯ! TROVO BOT! ', err)
            #         print('[TROVO]ТЕКСТ ОБ***Й ОШИБКИ', traceback.format_exc())
            #         print("\n[TROVO]=== КОНЕЦ ОШИБКИ ====")
            #     trovo_started = True

            if not twitch_started:
                try:
                    t.start()

                except BaseException as err:
                    print("[TWITCH]ОШИБКА ПОДКЛЮЧЕНИЯ! TWITCH BOT! ", err)
                    print("[TWITCH]ТЕКСТ ОБ***Й ОШИБКИ", traceback.format_exc())
                    print("\n[TWITCH]=== КОНЕЦ ОШИБКИ ====")
                    twitch_error = True
                twitch_started = True
            try:
                print("[PRE INIT YT] COMMENT CHECKING ENABLED!!! RUNNING TWITCH BOT...")

                print("[PRE INIT YT] TWITCH INIT ENDED! RUNNING YT BOT...")
                if not sc_client.running:
                    sc_client.start()
                YOUTUBE_START_ACTIONS_LISTENER = False
                if not YOUTUBE_START_ACTIONS_LISTENER:
                    while ctx_env["actived"]:
                        time.sleep(5)
                response = requests.get(YoutubeStreamURL)
                # print("YT>> pre init responce debug =" + str(response))

                streams = json.loads(response.text).get("items", [])
                # print("YT>> pre init streams debug =" + str(streams))
                VIDEO_ID = None
                liveChatId = None

            except BaseException as err:
                print("1ОШИБКА ПОДКЛЮЧЕНИЯ! ПОХОЖЕ СТРИМ ЗАКОНЧИЛСЯ111! ", err)
                print("ТЕКСТ ОБ***Й ОШИБКИ", traceback.format_exc())
                print("\n=== КОНЕЦ ОШИБКИ ====")
                ctx.IsYTChatConnected = False
                time.sleep(10)
        else:
            if sc_client.running:
                sc_client.stop()
        time.sleep(0.1)


if __name__ == "__main__":
    import multiprocessing

    logging.disable(logging.CRITICAL)
    manager = multiprocessing.Manager()
    ctx = manager.Namespace()
    ctx.IsYTChatConnected = False
    ctx_chat = manager.list()
    ctx_twitch_actions_queue = manager.Queue()
    ctx_trovo_actions_queue = manager.Queue()
    ctx.YoutubeActionsQueue = manager.list()
    ctx_env = manager.dict()
    ctx_env["youtube_social_enabled"] = True
    ctx.botNicknames = ["Net Tyan", "NetTyan", "neurodeva", "NeuroDeva"]
    ctx_env["actived"] = True
    ctx.YouTubeAppEnabled = True
    ctx.IsYTChatConnected = False
    ctx_twitch_actions_queue.put({"action": "reply", "msg": f"""Как дела? Тест =)"""})
    ctx_swarm = create_ctx_swarm(manager=manager)
    ctx_swarm["env"] = ctx_env
    socialChatListener(
        ctx, ctx_twitch_actions_queue, ctx_trovo_actions_queue, ctx_chat, ctx_swarm
    )
