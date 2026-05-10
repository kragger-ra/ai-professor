import time
from typing import Dict, Union

from data_schema.chat_structures import CtxEventBase
from utils.time_helper import eztime


def convert_to_chat_message(data: Union[Dict, str]) -> CtxEventBase:
    """Convert a dict or plain string into a CtxEventBase.

    A plain string is wrapped as a system directive. Dicts pass through their
    known fields and drop anything else into ``additional_fields``.
    """
    if isinstance(data, str):
        return CtxEventBase(
            msg=data,
            env="system",
            user="system",
            date=eztime(),
            processing_timestamp=time.time_ns(),
            type="directive",
            additional_fields={"filter_results": {"acceptable": True}},
        )

    known_fields = {"msg", "user", "date", "processing_timestamp", "type", "env"}
    base_fields = {
        "msg": data.get("msg", ""),
        "env": data.get("env", ""),
        "user": data.get("user", ""),
        "date": data.get("date", eztime()),
        "processing_timestamp": data.get("processing_timestamp", time.time_ns()),
        "type": data.get("type", "chat"),
    }
    additional_fields = {k: v for k, v in data.items() if k not in known_fields}
    return CtxEventBase(**base_fields, additional_fields=additional_fields)
