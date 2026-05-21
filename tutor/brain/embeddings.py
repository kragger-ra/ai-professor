"""OpenAI-compatible embeddings model factory.

Reads configuration from environment variables (loaded via .env):
  EMBEDDINGS_MODEL    — model name, e.g. "BAAI/bge-m3"
  EMBEDDINGS_API_BASE — base URL, e.g. "http://localhost:22227/v1"
  EMBEDDINGS_API_KEY  — API key (can be a dummy value for local servers)

Designed for use with a local LM Studio bge-m3 server but works with any
OpenAI-compatible embeddings endpoint.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from langchain_openai import OpenAIEmbeddings

from tutor.util import log

load_dotenv()

_COMPONENT = "embeddings"


def _get_env(var: str) -> str | None:
    """Read an environment variable by name."""
    return os.getenv(var)


def get_embeddings_model() -> OpenAIEmbeddings:
    """Return a configured OpenAIEmbeddings instance.

    All parameters come from environment variables so no credentials are
    hard-coded.  check_embedding_ctx_length is disabled because local models
    do not expose that endpoint.
    """
    model = _get_env("EMBEDDINGS_MODEL")
    api_base = _get_env("EMBEDDINGS_API_BASE")
    api_key = _get_env("EMBEDDINGS_API_KEY")

    log(_COMPONENT, f"model={model!r}  api_base={api_base!r}")

    return OpenAIEmbeddings(
        check_embedding_ctx_length=False,
        model=model,
        openai_api_base=api_base,
        api_key=api_key,
    )
