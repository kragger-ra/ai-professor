import asyncio
import json
import os
import traceback
from threading import Thread
from typing import Any, Optional

import websockets
from websockets.exceptions import WebSocketException

from live2d.vtube_settings import Live2DConfig

from .eye_rotater import start_eye_rotater

# from utils.exceptions import Live2DConnectionError


# Constants
WS_CONNECT_TIMEOUT = 5  # seconds
WS_OPERATION_TIMEOUT = 3  # seconds


def get_vtube_eye_params(x, y):
    value_map = {"EyeLeftX": x, "EyeRightX": x, "EyeLeftY": y, "EyeRightY": y}
    # value_map = {"MousePositionX": x, "MousePositionY": y}
    return [{"id": k, "value": v} for k, v in value_map.items()]


def get_vtube_face_params(x, y):
    value_map = {"FaceAngleX": x * 30, "FaceAngleY": y * 30}
    return [{"id": k, "value": v} for k, v in value_map.items()]


class VTubeStudioIntegration:
    def __init__(self, config: Live2DConfig = None, ctx_swarm=None):
        self.config = config or Live2DConfig()
        self.websocket: Optional[websockets.ClientProtocol] = None
        self.auth_token = None
        self.connected = False
        self.enabled = True
        self.repeating_dict = {}
        self.ctx_swarm = ctx_swarm
        self.eye_rotater_thread: Thread = None
        self.game_listening_cycle_task = None
        # asyncio.run(self.connect())
        if ctx_swarm is not None:
            print("[VTUBE] VTubeStudioIntegration initilizing (ctx_swarm)")
            self.eye_rotater_thread = start_eye_rotater(ctx_swarm, self)
            print("[VTUBE] VTubeStudioIntegration initilized (ctx_swarm)")
            # self.game_listening_cycle_task = Thread(
            #     target=self.game_listening_thread, daemon=True,
            #     args=(self,)
            # )
            # self.game_listening_cycle_task = asyncio.create_task(self.gameListeningCycle())
            # self.game_listening_cycle_task.start()
        else:
            print("[VTUBE] VTubeStudioIntegration initialized (no ctx_swarm)")

    async def setXY(self):
        # print("[Vtube] game listening cycle started")
        vtube_ctx = self.ctx_swarm["vtube"]
        try:
            # print("[Vtube] NeedX:", vtube_ctx["NeedX"])
            # print("[Vtube] NeedY:", vtube_ctx["NeedY"])
            # print("[Vtube] eyeX:", vtube_ctx["eyeX"])
            # print("[Vtube] eyeY:", vtube_ctx["eyeY"])
            await self.setEyeNeedXY(vtube_ctx["eyeX"], vtube_ctx["eyeY"])
            await self.setFaceXY(vtube_ctx["NeedX"], vtube_ctx["NeedY"])
        except Exception as e:
            print(f"[Vtube] error in game listening cycle: {e}")
            traceback.print_exc()

    async def setFaceXY(self, x, y):
        return await self.set_parameter(parameters=get_vtube_face_params(x, y))

    async def setEyeNeedXY(self, x, y):
        return await self.set_parameter(parameters=get_vtube_eye_params(x, y))

    def load_token(self) -> bool:
        if os.path.exists(self.config.token_file):
            try:
                with open(self.config.token_file, "r") as json_file:
                    data = json.load(json_file)
                    self.auth_token = data.get("authenticationkey", "")
                    if self.auth_token == "":
                        return False
                    return True
            except (json.JSONDecodeError, FileNotFoundError) as e:
                print(f"[VTUBE] Error reading token file: {e}")
                self.auth_token = None
        return False

    async def connect(self) -> bool:
        if not self.enabled:
            # print("[VTUBE] Integration is disabled due to previous errors")
            return False

        try:
            self.websocket = await websockets.connect(
                self.config.websocket_url, open_timeout=WS_CONNECT_TIMEOUT
            )
            print("[VTUBE] Connected to VTube Studio. Getting token...")
            if not self.load_token():  # get token from file
                print(
                    "[VTUBE] Doesn't have token. Creating new one... (open vtube and click yes)"
                )
                await self._get_token()
                print("[VTUBE] Got new token. Auth...")
            else:
                print("[VTUBE] Got existing token. Auth...")
            await self._authenticate()
            print("[VTUBE] Connection ready to work!")
            self.connected = True
            return True
        except asyncio.TimeoutError:
            print("[VTUBE] Connection timed out")
            self.enabled = False
        except (WebSocketException, ConnectionRefusedError) as e:
            print(f"[VTUBE] WebSocket connection error: {e}")
            self.enabled = False
        except Exception as e:
            print(f"[VTUBE] Unexpected error during connection: {e}")
            traceback.print_exc()
            self.enabled = False

        self.connected = False
        return False

    async def _get_token(self) -> str:
        payload = {
            "apiName": self.config.api_name,
            "apiVersion": self.config.api_version,
            "requestID": self.config.request_id,
            "messageType": "AuthenticationTokenRequest",
            "data": {
                "pluginName": self.config.plugin_name,
                "pluginDeveloper": self.config.plugin_developer,
            },
        }

        await self.websocket.send(json.dumps(payload))
        response = await self.websocket.recv()
        token = json.loads(response)["data"]["authenticationToken"]
        os.makedirs(str(self.config.token_file.parent), exist_ok=True)
        with open(self.config.token_file, "w") as json_file:
            json.dump({"authenticationkey": token}, json_file)
        self.load_token()
        return token

    async def _authenticate(self) -> bool:
        payload = {
            "apiName": self.config.api_name,
            "apiVersion": self.config.api_version,
            "requestID": self.config.request_id,
            "messageType": "AuthenticationRequest",
            "data": {
                "pluginName": self.config.plugin_name,
                "pluginDeveloper": self.config.plugin_developer,
                "authenticationToken": self.auth_token,
            },
        }

        await self.websocket.send(json.dumps(payload))
        response = json.loads(await self.websocket.recv())
        return response["data"]["authenticated"]

    async def _ensure_connection(self) -> bool:
        if (
            not self.connected
            or not self.websocket
            or self.websocket.state
            not in (websockets.client.State.CONNECTING, websockets.client.State.OPEN)
        ):  # or self.websocket:
            # print("[VTUBE] Connection lost, why? Reconnecting.", self.connected, not self.websocket, self.websocket.closed)
            await self.connect()
        return self.connected

    async def set_parameter(
        self, param_name: str = None, value: float = None, parameters: list = None
    ) -> Optional[Any]:
        try:
            retry_count = 3
            while retry_count > 0:
                if not await self._ensure_connection():
                    retry_count -= 1
                    continue
                if parameters is None:
                    parameters = [{"id": param_name, "value": value}]
                # print("STUPID MOUTH SMILE VALUE",param_name, value, parameters)
                payload = {
                    "apiName": self.config.api_name,
                    "apiVersion": self.config.api_version,
                    "requestID": self.config.request_id,
                    "messageType": "InjectParameterDataRequest",
                    "data": {
                        "faceFound": False,  # NEW EXPERIMENT! IF ERRORS SET TO FALSE!! # TODO test idk whats this
                        # https://github.com/DenchiSoft/VTubeStudio?tab=readme-ov-file#feeding-in-data-for-default-or-custom-parameters
                        "mode": "set",
                        "parameterValues": parameters,
                    },
                }
                # print("[VTUBE] DEBUG RESULT WS SEND", payload)
                await self.websocket.send(json.dumps(payload))
                output_data = await self.websocket.recv()
                # print("[VTUBE] DEBUG RESULT WS RECV", output_data)
                return output_data

        except Exception as e:
            print(f"[VTUBE ERR] Failed to set parameter after retries: {e}")
            traceback.print_exc()
            self.connected = False

    async def execute_hotkey(self, hotkey_name: str, itemInstanceID: str = None):
        """
        Post-processing effects (VtubeStudio VFX)

        Effect list:
        https://github.com/DenchiSoft/VTubeStudio/blob/master/Files/EffectConfigs.cs

        Payload structure:
        https://github.com/DenchiSoft/VTubeStudio?tab=readme-ov-file#the-postprocessingeffects-array
        """
        try:
            retry_count = 3
            while retry_count > 0:
                if not await self._ensure_connection():
                    retry_count -= 1
                    continue
                hotkey_data = {
                    "hotkeyID": hotkey_name,
                }
                if itemInstanceID:
                    hotkey_data["itemInstanceID"] = itemInstanceID
                payload = {
                    "apiName": self.config.api_name,
                    "apiVersion": self.config.api_version,
                    "requestID": self.config.request_id,
                    "messageType": "HotkeyTriggerRequest",
                    "data": hotkey_data,
                    #                                     {
                    # 	"apiName": "VTubeStudioPublicAPI",
                    # 	"apiVersion": "1.0",
                    # 	"requestID": "SomeID",
                    # 	"messageType": "HotkeyTriggerRequest",
                    # 	"data": {
                    # 		"hotkeyID": "HotkeyNameOrUniqueIdOfHotkeyToExecute",
                    # 		"itemInstanceID": "Optional_ItemInstanceIdOfLive2DItemToTriggerThisHotkeyFor"
                    # 	}
                    # }
                }
                # print("[VTUBE] DEBUG RESULT WS SEND", payload)
                await self.websocket.send(json.dumps(payload))
                output_data = await self.websocket.recv()
                # print("[VTUBE] DEBUG RESULT WS RECV", output_data)
                return output_data

        except Exception as e:
            print(f"[VTUBE ERR] Failed to set parameter after retries: {e}")
            traceback.print_exc()
            self.connected = False

    # TODO UNTESTED
    async def set_glich_effect(self, value: float = 0.0) -> Optional[Any]:
        """
        Set glitch effect
        """
        pass
        # await self.post_processing_update("ModelGlitch_StrengthWiggle", str(value))

    async def post_processing_update(
        self, config_id: str, config_value: str
    ) -> Optional[Any]:
        """
        Post-processing effects (VtubeStudio VFX)

        Effect list:
        https://github.com/DenchiSoft/VTubeStudio/blob/master/Files/EffectConfigs.cs

        Payload structure:
        https://github.com/DenchiSoft/VTubeStudio?tab=readme-ov-file#the-postprocessingeffects-array
        """
        try:
            retry_count = 3
            while retry_count > 0:
                if not await self._ensure_connection():
                    retry_count -= 1
                    continue
                payload = {
                    "apiName": self.config.api_name,
                    "apiVersion": self.config.api_version,
                    "requestID": self.config.request_id,
                    "messageType": "PostProcessingUpdateRequest",
                    "data": {
                        "postProcessingOn": True,
                        "setPostProcessingValues": True,
                        "presetToSet": "",
                        "postProcessingFadeTime": 1.3,
                        "setAllOtherValuesToDefault": True,
                        "usingRestrictedEffects": True,
                        "randomizeAll": False,
                        "randomizeAllChaosLevel": 0.0,
                        "postProcessingValues": [
                            {"configID": config_id, "configValue": str(config_value)}
                            # {
                            #     "configID": "Backlight_Strength",
                            #     "configValue": "0.8"
                            # },
                            # {
                            #     "configID": "Bloom_Strength",
                            #     "configValue": "1.0"
                            # },
                            # {
                            #     "configID": "Bloom_StreakVertical",
                            #     "configValue": "false"
                            # },
                            # {
                            #     "configID": "Bloom_StreakColorTint",
                            #     "configValue": "220308FF"
                            # }
                        ],
                    },
                }
                # print("[VTUBE] DEBUG RESULT WS SEND", payload)
                await self.websocket.send(json.dumps(payload))
                output_data = await self.websocket.recv()
                # print("[VTUBE] DEBUG RESULT WS RECV", output_data)
                return output_data

        except Exception as e:
            print(f"[VTUBE ERR] Failed to set parameter after retries: {e}")
            traceback.print_exc()
            self.connected = False

    async def cleanup(self) -> None:
        if self.websocket and not self.websocket.closed:
            await self.websocket.close()
        # if self.eye_rotater_thread is not None:
        #     self.eye_rotater_thread.join()
        # if self.game_listening_cycle_task is not None:
        #     self.game_listening_cycle_task.join()
