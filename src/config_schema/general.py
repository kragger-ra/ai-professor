import os

from dotenv import load_dotenv

load_dotenv()


def get_secret(var: str):
    return os.getenv(var)


def get_name():
    return os.getenv("SELF_NAME", "NetTyan")


# TODO: not counts different nicks from other envs like minecraft, youtube
def is_self_nick(nickname: str) -> bool:
    return nickname in os.getenv("BOT_NICKNAMES", "").split(",")


def is_dev_nick(nickname: str) -> bool:
    return nickname in os.getenv("RAZRABS", "").split(",")
