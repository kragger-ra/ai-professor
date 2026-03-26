# TODO add

import json
import time
import traceback

import socketio

from data_schema.chat_structures import EventBase
from data_schema.ctx_structures import CtxSwarmType

if __name__ == "__main__":
    import os
    import sys

    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config_schema.general import get_secret
from utils.time_helper import eztime

DEFAULT_DONATE_DESCRIPTION = " DONATED TO YOU!!! CONGRATULATIONS! NOW You must: change topic now to THIS donater || answer his question MAXIMUM fullfilly || save info about him || acknowledge he has given you a REAL money you can further spend on your new abilities and permissions"


def donations_handler(ctx_swarm: CtxSwarmType, reconnect: bool = False):
    sio = socketio.Client()
    # https://www.donationalerts.com/widget/alerts?group_id=1&token=your_token

    @sio.on("connect")
    def on_connect():
        sio.emit(
            "add-user",
            {"token": get_secret("DONATIONALERTS_TOKEN"), "type": "alert_widget"},
        )  #

    @sio.on("donation")
    def on_message(data):
        donate: dict = json.loads(data)
        if donate:
            # if ((y['message'].find('IMG:') != -1)):
            # url = y['message'].split('IMG:')[1]
            print("!!! ВНИМАНИЕ !!! УРААА ПОЛУЧЕН ДОНАТ!!! Вот словарь:", donate)
            name = donate.get("username", "")
            if name:
                name = name.strip()
            else:
                name = "Anonymous_fanat"
            msg = donate.get("message", "").strip()
            if msg:
                msg = msg.strip()
            else:
                msg = "донат без сообщения"
            try:
                summ = float(donate.get("amount", 0))

                if summ > 0:
                    ctx_record: EventBase = {
                        # "isEvent": True,
                        "summ": summ,
                        "env": "twitch",
                        "type": "chat",
                        "msg": DEFAULT_DONATE_DESCRIPTION
                        + ". Message came with donation: '"
                        + msg
                        + "'",
                        "date": eztime(),
                        "processing_timestamp": time.time_ns(),
                        # "description": ,
                    }
                    ctx_record.update(
                        {
                            "user": name,
                            "isEvent": True,
                            "summ": summ,
                            "env": "donation",
                            "type": "chat",
                            "msg": msg,
                            "date": eztime(),
                            "processing_timestamp": time.time_ns(),
                        }
                    )
                    print(" ДОНАТ ПРОЦЕССЕР АКТИВИРОВАН ! ВЫВОДИМ ДОНАТ", donate)
                    ctx_swarm["ctx_chat"].append(ctx_record)
            except Exception as e:
                print(
                    "[DONATE PROCESSOR] !!! ОШИБКА ПРИ ПОПЫТКЕ ПОЛУЧИТЬ СУММУ ДОНАТА", e
                )
                traceback.print_exc()

        # donationQueue.append(y)
        # print#(y['username'])
        # print(y['message'])
        # print_img(y['message'].split('IMG:')[1])

    if reconnect:
        while True:  # TODO while threads actived...
            if sio.connected:
                time.sleep(10)
            else:
                try:
                    sio.connect(
                        "wss://socket.donationalerts.ru:443", transports="websocket"
                    )
                    time.sleep(10)
                except Exception as e:
                    print("[DONATIONS] connect failed, exiting.", e)
                    traceback.print_exc()
                    time.sleep(15)
    else:
        try:
            sio.connect(
                "wss://socket.donationalerts.ru:443",
                transports="websocket",
                wait_timeout=10,
            )
        except Exception as e:
            print("[DONATIONS] connect failed, exiting.", e)
            traceback.print_exc()


if __name__ == "__main__":  # testing
    ctx_swarm = {"ctx_chat": [], "env": {"actived": True}}
    donations_handler(ctx_swarm)
    while True:
        time.sleep(5)
        print(str(ctx_swarm["ctx_chat"]))
