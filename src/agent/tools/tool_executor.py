"""Special tool executor separate module

Separate from tools, may be moved somewhere

TODO implement

TODO use in autogpt agent

Python-like tool parsing, executing system

Features:
- streaming llm support
- execute right now after part is parsed
- preserving strict order of tool calling

How data should be driving:
1. We got messages list and llm supports streaming by passing llm.invoke(BaseMessage list)
2. We are listening `for event in llm.stream(BaseMessage list)`
every event should be parsed and checked for starters and enders
every tool should have

CURRENT IMPLEMENTATION (BAD, NOT WILL USED):

Parsing this calls:
- tool_name(arg)
- tool_name(args, divided, with, commads)
- tool_name(arg1=argvalue)
- tool_name(arg1=argvalue, arg2=argvalue)

Maybe we have to use simplier command syntax like !commandName arg1 arg2 arg3


FOR Future (DELAYED, DO NOT IMPLEMENT):
with named args like !commandName --argName argValue --argName2 argValue2
or simplified with first letter of arg / part of word !commandName -a argValue -b argValue2
also simplified needs to work with full: !commandName -argName argValue -argName2 argValue2 -c argValue3

And command prefixes:
`/command args` for minecraft default commands
`@action args` for baritone agent actions

State updating: (TODO into state tools)
!state <new state>
for example:
!plan <new plan>

TODO s:
1. implement <prefix><tool name> <args> syntax, like \n!state "Hello, world!"
2. implement JSON args (if found {} then parse with json.loads, and if not parsed add VERY precize error handling with very exact error positioning)
3. implement tool fewshot formatting in chosen format, like, if passed tool name and args -> convert it into tool call string, for example for {"name": "state", "state": "lol"}, @state lol


For multiline python:
```py
# some python code
```

"""

import time
import traceback
from typing import Any, Callable, Iterable, List, Optional, TypedDict, Union

from data_schema.tool_structures import TOOL_COMMAND_FORMATS, ToolCommandFormats
from utils.prompt_helper import prompt_template_load

# TODO implement this dict into all tool command formatting things
TOOL_COMMAND_PREFIX = {
    "minecraft_command": "/",
    "agent_action": "@",
    "speak": ">",
    "general": "!",
}

# TODO 2 implement this DICTS into TOOL BANK
# TODO 2.1 standartize the tool bank (tool bank typing)
# TODO 2.2 define tool args type
SINGLE_ARG_TOOLS = {
    "plan",
    "state",
    "summary",
    "focus",
    "criticism",
    "screenshot",
    "directive",
    "agent_action",  # UNTESTED!
    "minecraft_command",
}
TOOL_PREFIX_COMMAND = {v: k for k, v in TOOL_COMMAND_PREFIX.items()}
TOOL_PREFIXES = tuple(TOOL_COMMAND_PREFIX.values())


def format_tool_command(
    tool_name: str, args: dict, tool_call_format: str = "command"
) -> str:
    """Format tool call string from tool name and args

    > format_tool_command(tool_name="tool_name", args={"hello": "123"}, tool_call_format="command")
    < !tool_name hello=123
    """

    if tool_call_format == "command":
        # Handle special tool prefixes
        if tool_name in TOOL_COMMAND_PREFIX.keys():
            try:
                if tool_name == "speak":
                    # if not args["comment"].startswith(TOOL_COMMAND_PREFIX[tool_name]):
                    #     args["comment"] = TOOL_COMMAND_PREFIX[tool_name] + args["comment"]
                    if not args["emotion"].startswith("*"):
                        args["emotion"] = "*" + args["emotion"] + "*"

            except (
                KeyError,
                IndexError,
                ValueError,
                TypeError,
            ):
                pass
            if len(list(args.keys())) == 1 and isinstance(args.get(0, None), int):
                tool_call = str(args.get(0, ""))
            else:
                args_str = " ".join(str(v) for v in args.values())
                tool_call = f"{args_str}"
            if not tool_call.startswith(TOOL_COMMAND_PREFIX[tool_name]):
                tool_call = f"{TOOL_COMMAND_PREFIX[tool_name]}{tool_call}"
                # tool_call = f"{TOOL_COMMAND_PREFIX[tool_name]}{tool_name} {args_str}"
        else:
            # For other tools use !tool arg1 arg2 format
            args_str = " ".join(str(v) for v in args.values())
            tool_call = f"""{TOOL_COMMAND_PREFIX["general"]}{tool_name} {args_str}"""
    elif tool_call_format == "python":
        args_str = ", ".join(f"{k}={v}" for k, v in args.items())
        tool_call = f"{tool_name}({args_str})"
    elif tool_call_format == "text":
        if tool_name in ["speak", "private_message", "message"]:
            try:
                if not args["emotion"].startswith("*"):
                    args["emotion"] = "*" + args["emotion"] + "*"
            except (
                KeyError,
                IndexError,
                ValueError,
                TypeError,
            ):
                pass
            args_str = " ".join(str(v) for v in args.values())
            tool_call = f"{args_str}"
        else:
            args_str = ", ".join(f"{k}={v}" for k, v in args.items())
            tool_call = f'tool "{tool_name}" with args "{args_str}"'
    return tool_call


def get_tool_fewshots(
    tool_name: str, tool_call_format: ToolCommandFormats = "command"
) -> str:
    """Get fewshot examples for a specific tool from YAML file."""
    try:
        fewshots = prompt_template_load("tool_fewshots")  # _" + tool_call_format)
        if not fewshots or tool_name not in fewshots:
            return ""

        examples = []
        for example in fewshots[tool_name]:
            context = example.get("context", "").strip()
            args = example.get("args", {})
            result = example.get("result", "").strip()

            tool_call = format_tool_command(tool_name, args, tool_call_format)

            example_str = (
                f"Situation: {context}\nResponse:"
                + f"\n{TOOL_COMMAND_FORMATS[tool_call_format]['single_start']}{tool_call}"
                + TOOL_COMMAND_FORMATS[tool_call_format]["single_end"]
                + f"\nResults: {result}\n"
            )
            examples.append(example_str)

        return "\n---\n".join(examples)

    except Exception as e:
        print(f"Error loading fewshots: {e}")
        return ""


def get_situation_fewshot(
    tool_names: List[str], tool_call_format: ToolCommandFormats = "command"
) -> str:
    """Multiple fewshot situations for multiple tool situations
    TODO implment

    Need to do like that (example only for command call format):
    Situation:
        situation about using several tools
    Response:
    ```
    !tool1 arg1 arg2 arg3
    !tool2 args
    > speak tool example *emotion*
    /another_prefix_tool
    ```
    Result:
        result of using several tools
    """
    pass


def _parse_python_style(tool_call_fragment: str) -> tuple[str, dict]:
    """Parse Python-style tool calls like: tool_name(arg1, arg2, name=value)"""
    main_fragment_split = tool_call_fragment.split("(", 1)
    tool_name = (
        main_fragment_split[0].replace("\n", "").replace("\r", "").strip().lower()
    )
    args_str = main_fragment_split[1]
    # remove last bracket
    args_str = args_str[:-1]

    # Handle quoted strings properly
    args = []
    current_arg = []
    in_quotes = False
    for char in args_str:
        if char == '"' and (not current_arg or current_arg[-1] != "\\"):
            in_quotes = not in_quotes
            current_arg.append(char)
        elif char == "," and not in_quotes:
            args.append("".join(current_arg).strip())
            current_arg = []
        else:
            current_arg.append(char)
    if current_arg:
        args.append("".join(current_arg).strip())

    tool_args = {}
    for arg_num, arg in enumerate(args):
        arg = arg.strip()
        if "=" in arg and not arg.startswith('"'):
            arg_split = arg.split("=", 1)
            arg_name = arg_split[0].strip()
            arg_value = arg_split[1].strip()
            tool_args[arg_name] = arg_value
        else:
            arg_name = arg_num
            arg_value = arg
            tool_args[arg_name] = arg_value

    return tool_name, tool_args


def _parse_command_style(command: str) -> tuple[str, dict]:
    """Parse command-style tool calls like: !command arg1 arg2 or direct commands /cmd or @cmd
    Examples:
        /m Bob hi -> minecraft_command, {0: "/m Bob hi"}
        @follow player -> agent_action, {0: "@follow player"}
        !speak "Hello" "happy" -> speak, {0: "Hello", 1: "happy"}
        > Hello *happy* -> speak, {0: "Hello *happy*"}
        !plan some long text -> plan, {0: "some long text"}
    """
    command = command.strip()
    if not command:
        return "", {}

    # Skip if doesn't start with a valid prefix
    if not command or command[0] not in TOOL_PREFIX_COMMAND:
        return "", {}

    if command[0] in TOOL_PREFIX_COMMAND:
        tool_name = TOOL_PREFIX_COMMAND[command[0]]
        if command[0] != ">":
            # and remove < and > (draft fix args like <name>)
            command = command.replace(">", "").replace("<", "")
        if tool_name != "general":
            return tool_name, {0: command}

    # Regular !command parsing
    parts = command[1:].split(maxsplit=1)
    if not parts:
        return "", {}

    tool_name = parts[0].lower()
    args_str = parts[1] if len(parts) > 1 else ""

    # Special case tools that should treat rest of line as single argument

    if tool_name in SINGLE_ARG_TOOLS:
        return tool_name, {0: args_str.strip()} if args_str else {0: ""}

    # Parse arguments with quote handling for other tools
    args = []
    current = []
    in_quotes = False

    for char in args_str:
        if char == '"' and (not current or current[-1] != "\\"):
            if in_quotes:
                args.append("".join(current))
                current = []
            in_quotes = not in_quotes
        elif char.isspace() and not in_quotes:
            if current:
                args.append("".join(current))
                current = []
        else:
            current.append(char)

    if current:
        args.append("".join(current))

    # Convert to args dict
    tool_args = {}
    for i, arg in enumerate(args):
        # QUESTIONABLE MOMENT
        if arg.strip():  # Only add non-empty args
            tool_args[i] = arg.strip()

    return tool_name, tool_args


class ToolCallResult(TypedDict):
    name: str
    args: dict
    returned: Any
    succesful: bool
    call_time: float
    execute_duration: float
    parsed_fragment: str

    def __init__(self):
        self["call_time"] = time.time()
        # self["execute_duration"] = 0.0


def parse_and_execute_tool_call(
    tool_call_fragment: str,
    execute_func: Callable[[str, str], Any],
    error_handler: Callable[[BaseException], Any] = None,
    tool_call_format: str = "command",
) -> Any:
    """Parse tool call string"""

    tool_call_fragment = tool_call_fragment.strip()

    # Skip empty calls
    if not tool_call_fragment:
        return None
    # tool_call_format
    # Detect format and parse accordingly
    if any(
        tool_call_fragment.startswith(x) for x in TOOL_PREFIXES
    ):  # tool_call_format="command"
        tool_name, tool_args = _parse_command_style(tool_call_fragment)
    elif (
        "(" in tool_call_fragment and ")" in tool_call_fragment
    ):  # tool_call_format="python"
        tool_name, tool_args = _parse_python_style(tool_call_fragment)
    else:
        return None

    if not tool_name:  # not tool_args or not tool_name:
        return None

    if not tool_args:
        tool_args = {}

    if execute_func is not None:
        try:
            return execute_func(tool_name, tool_args)
        except Exception as e:
            if error_handler is not None:
                return error_handler(e)
            else:
                print("[TOOL EXECUTOR DEBUG ERROR]", e)
                traceback.print_exc()
                return str(e)


def _get_function_args_from_dict(args: dict):
    call_args = []
    call_kwargs = {}
    for arg_key in args:
        if isinstance(arg_key, int):
            # positional
            call_args.append(args[arg_key])
        else:
            # keyword
            call_kwargs[arg_key] = args[arg_key]
    return call_args, call_kwargs


def execute_tool(
    tool_bank: dict, tool_name: str, tool_args: dict, allow_disabled_tools: bool = False
) -> Any:
    """Execute a tool with given arguments"""
    if tool_name not in tool_bank:
        print(f"[TOOL EXEC WARNING] Tool '{tool_name}' not found in tool bank !!!")
        return None
    tool_record = tool_bank[tool_name]

    if not allow_disabled_tools and tool_record.get("disabled"):
        return None

    call_args, call_kwargs = _get_function_args_from_dict(tool_args)
    return tool_record["function"](*call_args, **call_kwargs)


def list_elements_equal(lst: Union[list[str], str]) -> bool:
    """Check if elements in a string or list form repetitive patterns

    Detects repeating sequences like:
    - Direct repetition: "22222222", "hello hello hello"
    - Simple patterns: "hihihihi", "abcabcabc"

    Args:
        lst: String or list to check for patterns

    Returns:
        bool: True if repetitive patterns found, False otherwise
    """
    # Convert string to list of characters if needed
    if isinstance(lst, str):
        lst = list(lst)

    if not lst or len(lst) <= 2:  # Too short to have meaningful patterns
        return False

    # Check for repeating n-grams of different lengths
    n = len(lst)
    for pattern_len in range(1, n // 2 + 1):
        if n % pattern_len == 0:  # Length must be divisible by pattern length
            pattern = lst[:pattern_len]
            repeating = True

            # Check if this pattern repeats throughout
            for i in range(0, n, pattern_len):
                if lst[i : i + pattern_len] != pattern:
                    repeating = False
                    break

            if repeating:
                return True

    return False


def execute_tools(
    generator: Union[Iterable, str],
    generator_callable: Callable[[str], Union[str, Any]] = None,
    tool_exec_callable: Callable[[ToolCallResult], Optional[bool]] = None,
    execute_func: Callable = None,
    tool_bank: dict = None,
    tool_call_format: str = "command",
    max_tool_run_cnt: int = -1,
    should_interrupt: Optional[Callable] = None,
    max_symbol_count: int = 2000,
    allow_disabled_tools: bool = False,
    response_starting: str = "",
    max_generator_iterations: str = None,
    stopping_word: Callable = None,
    stopping_word_repeat_count: int = 1,
) -> str:
    """Execute tools during streaming / text

    Args:
        generator: llm object SUPPORTS streaming for example, will used in for event in generator
        generator_callable: Callable[[str], Union[str, Any]] = None,
        tool_exec_callable: Callable[[ToolCallResult], Optional[bool]] = None,
        execute_func: Callable = None,
        tool_call_format: str = "command",
            tool_call_formats:
            - custom (for example, !commandName arg1 arg2 arg3)
            - python (UNIMPLEMENTED)
        max_tool_run_cnt: int = -1,
        should_interrupt: Optional[dict] = None
            Put anything in this dict during streaming / execution to interrupt the process
    """
    if not max_generator_iterations:
        max_generator_iterations = max_symbol_count
    if stopping_word is None:
        if tool_call_format == "command":
            stopping_word = "\n```"
    if stopping_word_repeat_count == -1:
        stopping_word = ""
    final_response = ""
    # TODO response starting is NOT executed
    tool_call_fragment = ""
    starter_cnt = 0
    ender_cnt = 0
    tool_runs_cnt = 0
    if execute_func is None:
        if tool_bank is None:
            print("[TOOL EXEC WARNING] NO EXECUTE FUNC PROVIDED")
        else:
            execute_func = lambda tool_name, tool_args: execute_tool(
                tool_bank,
                tool_name,
                tool_args,
                allow_disabled_tools=allow_disabled_tools,
            )
    if should_interrupt is None:
        should_interrupt = lambda: False

    in_command = False

    def execute_complete_fragment() -> bool:
        nonlocal tool_call_fragment, starter_cnt, ender_cnt, tool_runs_cnt
        if should_interrupt():
            return False
        if max_tool_run_cnt != -1 and tool_runs_cnt > max_tool_run_cnt:
            return False
        if not tool_call_fragment.strip():
            return True
        try:
            # print("DEBUG tool_call_fragment", tool_call_fragment)
            returned = parse_and_execute_tool_call(
                tool_call_fragment, execute_func, tool_call_format=tool_call_format
            )
            if tool_exec_callable is not None:
                tool_call_result = ToolCallResult(
                    name="UNIMPLEMENTED",
                    parsed_fragment=tool_call_fragment,
                    args={0: "UNIMPLEMENTED"},
                    returned=returned,
                )

                tool_callable_result = tool_exec_callable(tool_call_result)
                if tool_call_result is not None:
                    return tool_callable_result
        except Exception as e:
            print("[DEBUG TOOL EXECUTOR EXC] ", e)
            traceback.print_exc()
        tool_call_fragment = ""
        starter_cnt = 0
        ender_cnt = 0
        tool_runs_cnt += 1
        return True

    def tool_execute_step(symbol: str, is_last: bool = False) -> bool:
        """Execute tool step"""
        nonlocal tool_call_fragment, starter_cnt, ender_cnt, in_command

        tool_call_fragment += symbol

        # Only process lines that start with valid tool prefixes
        if symbol == "\n" or is_last:
            stripped = tool_call_fragment.strip()
            if stripped and stripped[0] in TOOL_PREFIXES:
                execute_complete_fragment()
            elif in_command:
                in_command = False
            tool_call_fragment = ""
        elif not in_command and any(
            tool_call_fragment.strip().startswith(x) for x in TOOL_PREFIXES
        ):
            in_command = True

        # Check for python-style tools
        if symbol == "(":
            starter_cnt += 1
        elif symbol == ")":
            ender_cnt += 1
            if starter_cnt != 0 and starter_cnt == ender_cnt:
                execute_complete_fragment()
        return True

    response_list = []
    generators = []
    iteration_count = 0
    if response_starting:
        iteration_count -= len(response_starting)
        generators.append(response_starting)
    generators.append(generator)
    for container in generators:
        for event in container:
            iteration_count += 1
            if iteration_count > max_generator_iterations:
                print(
                    "[TOOL EXECUTOR DEBUG] INTERRUPTED! (MAX GENERATOR ITERATIONS REACHED!)"
                )
                break
            got_text: str = None
            if generator_callable is not None:
                generator_callable(event)
            if event:
                if not isinstance(event, str):
                    t = event.content
                else:
                    t = event
                final_response += t
                length = len(t)
                if length > 0:
                    if length == 1:
                        got_text = t
                    else:
                        got_text = t
            if got_text is not None:
                for symbol in got_text:
                    response_list.append(symbol)

                    if not tool_execute_step(symbol):
                        print("[TOOL EXECUTOR DEBUG] INTERRUPTED!")
                        break
            else:
                response_list.append(" ")

        # Checking for repetition n-gram patterns in last 10 symbols

        if len(response_list) > 30:
            last_responses = response_list[-25:]
            if list_elements_equal(last_responses):
                print("[TOOL EXECUTOR DEBUG] INTERRUPTED! (REPEAT OUTPUT LAG!)")
                break
            else:
                response_list = last_responses
            if stopping_word:
                last_responses_str = "".join(last_responses)
                if last_responses_str.endswith(stopping_word):
                    stopping_word_repeat_count -= 1
                    if stopping_word_repeat_count <= 0:
                        print(
                            "[TOOL EXECUTOR DEBUG] INTERRUPTED! (STOPPING WORD FOUND!)"
                        )
                        break
        if len(final_response) > max_symbol_count:
            print("[TOOL EXECUTOR DEBUG] INTERRUPTED! (MAX SYMBOL COUNT REACHED!)")
            break
    # Handle case when last command has no newline
    if tool_call_fragment.strip():
        tool_execute_step("\n", is_last=True)

    return final_response
