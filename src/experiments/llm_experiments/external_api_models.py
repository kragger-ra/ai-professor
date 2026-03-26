import base64
import os
import sys
from typing import TypedDict

from google import genai
from google.genai import types
from smolagents import LiteLLMModel
from torch import ge
from urllib3 import proxy_from_url

if __name__ == "__main__":
    sys.path.insert(
        0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
    )


from config_schema.general import get_secret


class LiteLLMConnection(TypedDict):
    model_id: str
    api_base: str
    api_key: str
    max_tokens: int


# LM_STUDIO =

os.environ["USE_LITELLM_PROXY"] = "True"
os.environ["LITELLM_PROXY_API_BASE"] = "http://127.0.0.1:2080"


def get_litellm_creds() -> LiteLLMConnection:
    return LiteLLMConnection(
        model_id=f"gemini/gemini-2.5-flash-lite",
        # api_base=get_secret("lm_studio_api"),
        api_key=get_secret("GEMINI_API_KEY"),
        max_tokens=12000,
        # proxy=get_secret("proxy"),
        # proxy_from_url=get_secret("proxy")
    )


def get_smo_llm() -> LiteLLMModel:
    return LiteLLMModel(**get_litellm_creds())


print(
    "ОТВЕТ = ",
    get_smo_llm().__call__(
        [
            {
                "role": "user",
                "content": "здарова как дела йоу расскажи о самых модных словах зумеров 2025 бро",
            }
        ],
    ),
)

# To run this code you need to install the following dependencies:
# pip install google-genai


# def generate():
#     client = genai.Client(
#         api_key=os.environ.get("GEMINI_API_KEY"),
#     )
#
#     model = "gemini-2.5-flash-lite"
#     contents = [
#         types.Content(
#             role="user",
#             parts=[
#                 types.Part.from_text(text="""INSERT_INPUT_HERE"""),
#             ],
#         ),
#     ]
#     tools = [
#         types.Tool(googleSearch=types.GoogleSearch(
#         )),
#     ]
#     generate_content_config = types.GenerateContentConfig(
#         thinking_config = types.ThinkingConfig(
#             thinking_budget=0,
#         ),
#         tools=tools,
#     )
#
#     for chunk in client.models.generate_content_stream(
#         model=model,
#         contents=contents,
#         config=generate_content_config,
#     ):
#         print(chunk.text, end="")
#
# if __name__ == "__main__":
#     generate()
