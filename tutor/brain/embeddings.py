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

    Reads EMBEDDINGS_MODEL / _API_BASE / _API_KEY from env. Falls back to
    OPENAI_API_KEY when EMBEDDINGS_API_KEY is empty and to the standard
    OpenAI endpoint when EMBEDDINGS_API_BASE is empty — that pair keeps
    the embeddings working out of the box for a tester who only set their
    OpenAI key, no LM Studio required. Local bge-m3 via LM Studio is
    still supported when both vars are filled explicitly.
    """
    model = _get_env("EMBEDDINGS_MODEL") or "text-embedding-3-small"
    api_base = _get_env("EMBEDDINGS_API_BASE") or None
    api_key = _get_env("EMBEDDINGS_API_KEY") or _get_env("OPENAI_API_KEY")
    if not api_key:
        log(_COMPONENT, "no embeddings/OpenAI api key set — RAG will be unavailable")

    log(_COMPONENT,
        f"model={model!r}  api_base={api_base or '<openai default>'!r}  "
        f"key={'set' if api_key else 'MISSING'}")

    return OpenAIEmbeddings(
        check_embedding_ctx_length=False,
        model=model,
        openai_api_base=api_base,
        api_key=api_key,
    )
