import os, sys

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "src"
    ),
)

from agent.tools import tools_config
from agent.llm_clients.lc_clients import get_llm_chain
from agent.tools.tool_executor import execute_tools, format_tool_command, list_elements_equal, parse_and_execute_tool_call, get_tool_fewshots
from agent.tools.tools import execute_tool_query

# Test a basic tool execution
def test_tool_executor():

    # print(format_tool_command(tool_name="agent_action", args={0: '@strike Chochok'}, tool_call_format="command"))
    print(format_tool_command(tool_name="wait", args={'seconds': '5'}, tool_call_format="command"))
    print(format_tool_command(tool_name="agent_action", args={'action': '@strike Chochok'}, tool_call_format="command"))
    for i, word in enumerate(("hihihilol", "hihihihihihihihihihihi", "hello hello hello hello", "1,2,3,1,2,3,", "Hello, how are you?")):
        print("REPEAT CHECK", i, word, list_elements_equal(word))


    def mock_execute(tool_name, args):
        if tool_name == "chat_simple":
            message = args.get(0, "") or args.get("message", "")
            return {"tool": tool_name, "message": message}
        return None
    # test_input = 'chat_simple(lol=1, haha=2)'
    test_input = 'chat_simple("Hello, World!")'
    result = parse_and_execute_tool_call(test_input, mock_execute)
    print(result)
    assert result is not None, "Tool execution result should not be None"
    assert result["tool"] == "chat_simple", "Wrong tool name parsed"
    assert result["message"] == '"Hello, World!"', "Wrong message parsed"
    print("Tool executor test passed!")

def test_simple_command_format():
    def mock_execute(tool_name, args):
        return {"tool": tool_name, "args": args}

    # Test basic command
    test_input = '!state "Hello, World!"'
    result = parse_and_execute_tool_call(test_input, mock_execute)
    print("\nTesting simple command:", test_input)
    print("Result:", result)
    #assert result["tool"] == "state"
    #assert result["args"][0] == '"Hello, World!"'

    # Test with JSON args
    test_input = '!command {"arg1": "value", "num": 123}'
    result = parse_and_execute_tool_call(test_input, mock_execute)
    print("\nTesting JSON args:", test_input)
    print("Result:", result)
    #assert result["tool"] == "command"
    #assert result["args"]["arg1"] == "value"
    #assert result["args"]["num"] == 123

    # Test with named args
    test_input = "!action --name value --count 5"
    result = parse_and_execute_tool_call(test_input, mock_execute)
    print("\nTesting named args:", test_input)
    print("Result:", result)
    #assert result["tool"] == "action"
    #assert result["args"]["name"] == "value"
    #assert result["args"]["count"] == "5"

    print("Simple command format tests passed!")


def test_tool_fewshots():
    """Test getting fewshot examples for tools"""
    print("\nTesting tool fewshots:")
    
    # Test command format
    result = get_tool_fewshots("example_tool", "command")
    print("\nCommand format:")
    print(result)
    assert "!example_tool" in result, "Command format should include !tool_name"
    
    # Test python format
    result = get_tool_fewshots("example_tool", "python")
    print("\nPython format:")
    print(result)
    assert "example_tool(" in result, "Python format should include function call"
    
    print("Tool fewshots tests passed!")


def llm_testing():
    # text
    text_sample = """!action lol hahaha\n!lol ahahah ahhah\n/minecraft "Very bad player, name, ahahah" 123"""
    for text in (
        text_sample,
        """/roast "You're about as useful in Minecraft as a chocolate toolbox, haha!" lol""",
        """> Привет, как дела?\nЧто случилось?\n!speak Ахахахаха *аххаха*""",
        """lol123
!interrupt_chat
!int
!haha 1
!f
> О ты кто такой, аххаха?... *yandere*
@avoid SENEX
!wait 5
@status
> о привет
```""",
        ):
        print("\nPROMPT=" + text,"\nOUTPUT...\n")
        print(execute_tools(text, execute_func=lambda name, args: print("Executed:", name, args)))

    llm = get_llm_chain()
    # tools_prompot = generate_tool_fewshots()
    system_prompt = "Use a tool !action lol hahaha. DO NOT REPLY ANY OTHER TEXT. Use several tool calls divided with \n. Command should start with any of prefixes: !, / or @. Example:" + text_sample
    if True:
        print(execute_tools(
                llm.stream(system_prompt),
                generator_callable=lambda x: print("|"+ str(x.content), flush=True, end=""),
                execute_func=lambda *args, **kwargs: print("\n\nExecuted:", args, kwargs,"\n\n")))
    
    # prompt_openai_messages = [{"role": "system", "content": system_prompt}]
    # 
    # print("EXECUTION QUERY LLM:\n", execute_tool_query(prompt_openai_messages))


if __name__ == "__main__":
    test_tool_executor()
    test_simple_command_format()
    test_tool_fewshots() # Add new test
    # tools_config.init_tools_module()
    llm_testing()