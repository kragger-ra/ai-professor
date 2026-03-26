import os
from dataclasses import dataclass
from pathlib import Path

from data_schema.structure_templates import REPO_DATA_PATH


@dataclass
class Live2DConfig:
    api_name: str = "VTubeStudioPublicAPI"
    api_version: str = "1.0"
    websocket_url: str = "ws://127.0.0.1:22232"
    plugin_name: str = "TTS Integration"
    plugin_developer: str = "nettyan"
    request_id: str = "test"
    token_file: Path = Path(
        os.path.join(REPO_DATA_PATH, "vtube_studio_plugin", "token.json")
    )
