from typing import TypedDict

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_litellm import ChatLiteLLM
from langchain_openai import OpenAIEmbeddings

# from agent.llm_clients.lc_chatopenai_patch import ChatOpenAI
# for older langchain versions
from config_schema.general import get_secret

# for langchain-core=0.3.52, langchain-openai=0.3.13


class ChatLiteLLMCreds(TypedDict, total=False):
    model: str
    api_base: str
    api_key: str
    max_tokens: int


def get_llm_chain(model_name: str = None) -> BaseChatModel:
    """Get ChatLiteLLM instance with credentials from .env or defaults.
    Args:
        model_name:
            Str, model name to use. If None, get from .env CORE_LLM_MODEL_NAME.
    Returns:
        ChatLiteLLM instance.
    """

    if model_name is None:
        model_name = get_secret("CORE_LLM_MODEL_NAME")

    # proxies moved to .env, just configure this vars
    # proxy = get_secret("proxy")
    # if proxy and proxy != "NONE":
    #     environ["HTTP_PROXY"] = proxy
    #     environ["HTTPS_PROXY"] = proxy
    #     environ["NO_PROXY"] = "localhost,127.0.0.1,::1,0.0.0.0"
    core_llm_api_base = get_secret("CORE_LLM_API_BASE")
    creds = ChatLiteLLMCreds(
        model=model_name,
        # api_key=get_secret("CORE_LLM_API_KEY"),
        # stored in env, loaded by litellm
        # max_tokens=20000,  # >10k on start, 6k
    )
    max_tokens = get_secret("CORE_LLM_MAX_TOKENS")
    if max_tokens and core_llm_api_base != "NONE":
        creds["max_tokens"] = int(max_tokens)
    if core_llm_api_base and core_llm_api_base != "NONE":
        creds["api_base"] = core_llm_api_base
    # else chosen automatically from env / litellm defaults

    # print("[lc_clients.py DEBUG] LLM Model full creds =", creds)

    return ChatLiteLLM(**creds)


def get_embeddings_model() -> OpenAIEmbeddings:
    return OpenAIEmbeddings(
        check_embedding_ctx_length=False,
        model=get_secret("EMBEDDINGS_MODEL"),
        # deployment=get_secret("embeddings_model"),
        openai_api_base=get_secret("EMBEDDINGS_API_BASE"),
        api_key=get_secret("EMBEDDINGS_API_KEY"),
    )
