# uv pip install markdownify duckduckgo-search smolagents

import os
import re
import sys
from typing import Optional

import gradio as gr
import requests
from markdownify import markdownify
from requests.exceptions import RequestException
from smolagents import (
    CodeAgent,
    DuckDuckGoSearchTool,
    GradioUI,
    HfApiModel,
    LiteLLMModel,
    ManagedAgent,
    Tool,
    ToolCallingAgent,
    tool,
)

if __name__ == "__main__":
    sys.path.insert(
        0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
    )

import agent.tools.tools as tools_class

tools_class.tool = tool

toolss = tools_class.AGENT_SUPERVISOR_TOOLS_RAW
tools = []
for raw_tool in toolss:
    tool_item = tool(raw_tool)
    print(tool_item.name + " converted successfully")
    tools.append(tool_item)


# tools = [Tool.from_langchain(tool_item) for tool_item in AGENT_SUPERVISOR_TOOLS]
# for tool_item in AGENT_SUPERVISOR_TOOLS:
#     tooll = Tool.from_langchain(tool_item)
#     print(tooll.name +  "converted successfully")
#     # tools.append(tool)
# STUPID ERRORS


@tool
def visit_webpage(url: str) -> str:
    """Visits a webpage at the given URL and returns its content as a markdown string.

    Args:
        url: The URL of the webpage to visit.

    Returns:
        The content of the webpage converted to Markdown, or an error message if the request fails.
    """
    try:
        # Send a GET request to the URL
        response = requests.get(url)
        response.raise_for_status()  # Raise an exception for bad status codes

        # Convert the HTML content to Markdown
        markdown_content = markdownify(response.text).strip()

        # Remove multiple line breaks
        markdown_content = re.sub(r"\n{3,}", "\n\n", markdown_content)

        return markdown_content

    except RequestException as e:
        return f"Error fetching the webpage: {str(e)}"
    except Exception as e:
        return f"An unexpected error occurred: {str(e)}"


# model_id = "Qwen/Qwen2.5-Coder-32B-Instruct"
# model = HfApiModel(model_id)

model = LiteLLMModel(
    model_id="lm_studio/saiga_nemo_12b_gguf",
    api_base="http://localhost:22227/v1",  # replace with remote open-ai compatible server if necessary
    api_key="sk-1241",  # replace with API key if necessary
)

web_agent = ToolCallingAgent(
    tools=[DuckDuckGoSearchTool(), visit_webpage] + tools,
    model=model,
    # max_iterations=10,
)

managed_web_agent = ManagedAgent(
    agent=web_agent,
    name="search",
    description="""Runs web searches for you. Give it your request as an argument. It should use like:
    ```python
    search(request='Your request')
    ```
    """,
)


superagent = ToolCallingAgent(
    tools=tools,
    model=model,
    # max_iterations=10,
)

managed_superagent = ManagedAgent(
    agent=superagent,
    name="speakagent",
    description="""Using speak tools
    ```python
    speakagent(request='Your request to speak agent')
    ```
    """,
)


manager_agent = CodeAgent(
    tools=[],
    model=model,
    managed_agents=[managed_web_agent, managed_superagent],
    additional_authorized_imports=["time", "numpy", "pandas"],
)


# demo = gr.Blocks(theme=gr.themes.Soft(), title="Smolagents x NetTyan")
# with demo:
#     with gr.Row():
#         GradioUI(manager_agent)
#     #with gr.Row():
#     #    gr.Markdown("Привет =)")
if __name__ == "__main__":
    # test
    # print(visit_webpage("https://en.wikipedia.org/wiki/Hugging_Face")[:500])
    # exit()
    # answer = manager_agent.run("Сколько время")
    answer = superagent.run("Скажи ааа")
    GradioUI(manager_agent).launch()
    # demo.launch(
    #     server_name="0.0.0.0",
    #     server_port=22228,
    # )
    # print(answer)
