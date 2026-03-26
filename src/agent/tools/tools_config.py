import os
from typing import Any, Dict, List

from config_schema.general import get_secret
from data_flow.ctx_handler import CtxHandler
from data_flow.database import StreamerDatabase
from data_schema.ctx_structures import CtxSwarmType
from data_schema.structure_templates import CTX_SWARM_EMPTY, REPO_RESOURCE_PATH
from data_schema.tool_structures import ToolRecord, VotesBank
from utils.prompt_helper import yaml_load

ctx_swarm: CtxSwarmType = CTX_SWARM_EMPTY  # .copy()
ctx_handler: CtxHandler = None
llm_model = None
db: StreamerDatabase = None

# Global storage for active votes
active_votes: VotesBank = {}

# GLOBAL TOOL BANK (!!!)
tool_bank: Dict[str, ToolRecord] = {}
# openai-like inner dialogue history
inner_dialogue_history: List[dict] = []

TOOLS_RUN_CTX_ADD: bool = True
TOOLS_RESULT_CTX_ADD: bool = True
TOOLS_ERRORS_CTX_ADD: bool = False
TOOLS_FX_PLAY: bool = True


def queue_send(queue_name: str, message_list: Any, ignore_queue=False) -> bool:
    ctx_queue = ctx_swarm[queue_name]
    # print(f"[DEBUG] Queue {queue_name} before send:", list(ctx_queue))
    # print(f"[DEBUG] Sending messages:", message_list)
    # check if it's list proxy
    # for k, v in ctx_swarm.items():
    #     print("CTX SWARM KEY:", k, "VAL:", v, "TYPE:",type(v))
    if not message_list or len(message_list) <= 0:
        raise Exception("You don't add messages to send!")
        return False
    if (not ignore_queue and len(ctx_queue) > 3) or (
        ignore_queue and len(ctx_queue) > 10
    ):
        raise Exception(
            f"YOU ARE SENDING MESSAGES TOO FAST!!!\nThere are {str(len(ctx_queue))} messages pending in {queue_name}!"
        )
        return False
    # if queue_name in ["chat_queue"]:
    #     if filter_client.check_message("\n".join(message_list)).get("acceptable", True) == False:
    #         raise Exception("Sent message is RUDE, BAD, RACIST and not acceptable!")
    #         return False
    # if queue_name in ["tts_queue"]:
    #     if filter_client.check_message("\n".join([msg.get("text", "") for msg in message_list])).get("acceptable", True) == False:
    #         raise Exception("Speak message is RUDE, BAD, RACIST and not acceptable!")
    #         return False
    #        pass # TODO filter here!!!
    ctx_queue.extend(message_list)
    return True


def init_tools_module(
    ctx_swarm_new,
    ctx_handler_new,
    new_db=None,
    new_llm=None,
    tools_format="langchain",
) -> dict:
    global ctx_swarm, ctx_handler, db, llm_model, tool_bank

    # Clear existing tool bank
    # tool_bank.clear()

    if new_db is None:
        db = StreamerDatabase()
    else:
        db = new_db
    if new_llm is None:
        # from agent.llm_clients.lc_chatopenai_patch import ChatOpenAI
        from agent.llm_clients.lc_clients import get_llm_chain

        llm_model = get_llm_chain()
    else:
        llm_model = new_llm
    # ctx_swarm.clear()
    ctx_swarm.update(ctx_swarm_new)
    ctx_handler = ctx_handler_new

    # Register tools from tools.py
    from agent.tools.status_tools import register_tool, register_tool_status
    from agent.tools.tools import ALL_TOOLS, DEFAULT_DISABLED_TOOLS, TOOL_STATUSES

    tool_bank_config = yaml_load(
        os.path.join(REPO_RESOURCE_PATH, "Customization", "tool_bank_config.yml")
    )

    for tool in ALL_TOOLS:
        tool_name = tool.__name__
        should_disable = tool in DEFAULT_DISABLED_TOOLS
        if not should_disable and tool_name == "screenshot":
            vlm_name = get_secret("VISION_LLM_MODEL_NAME")
            if vlm_name:
                if vlm_name == "NONE":
                    should_disable = True
            else:
                should_disable = True

        register_tool(
            name=tool_name,
            func=tool,
            disable=should_disable,
            config=tool_bank_config.get(tool_name, {}),
        )
    for tool_status in TOOL_STATUSES:
        # minecraft_command_tool_status
        status_name = tool_status.__name__.replace("_tool_status", "")
        register_tool_status(name=status_name, get_status=tool_status)
    return tool_bank
