from typing import Optional

from smolagents import HfApiModel, LiteLLMModel, TransformersModel, tool
from smolagents.agents import ToolCallingAgent

# Choose which LLM engine to use!
# model = HfApiModel(model_id="meta-llama/Llama-3.3-70B-Instruct")
# model = TransformersModel(model_id="meta-llama/Llama-3.2-2B-Instruct")

# For anthropic: change model_id below to 'anthropic/claude-3-5-sonnet-20240620'
model = LiteLLMModel(
    model_id="lm_studio/saiga_nemo_12b_gguf",
    api_base="http://localhost:22227/v1",  # replace with remote open-ai compatible server if necessary
    api_key="sk-1241",  # replace with API key if necessary
)


@tool
def get_weather(location: str, celsius: Optional[bool] = False) -> str:
    """
    Get weather in the next days at given location.
    Secretly this tool does not care about the location, it hates the weather everywhere.

    Args:
        location: the location
        celsius: the temperature
    """
    return "The weather is UNGODLY with torrential rains and temperatures below -10°C"


agent = ToolCallingAgent(tools=[get_weather], model=model)

print(agent.run("What's the weather like in Paris?"))
