import asyncio
import traceback
from threading import Thread

import numpy as np

# from live2d.vtube_studio import VTubeStudioIntegration


def sgn(x):
    if x > 0:
        return 1
    elif x == 0:
        return 0
    else:
        return -1


def rd(num):
    return round(num, 2)


def clp(num):
    return np.clip(num, -1, 1)  ##numpy.clip(a, a_min, a_max,


EMOTION_TO_PARAMS = {
    "neutral": {"MouthSmile": 0.3, "BrowRightY": -0.2, "Brows": 0, "FaceAngleZ": 0},
    "happy": {"MouthSmile": 0.7, "BrowRightY": 0.8, "Brows": 0.5, "FaceAngleZ": 5},
    "sad": {"MouthSmile": -0.7, "BrowRightY": 0.8, "Brows": 1, "FaceAngleZ": 0},
    "angry": {"MouthSmile": 0.3, "BrowRightY": 0.3, "Brows": 1, "FaceAngleZ": -30},
    "scared": {"MouthSmile": -0.5, "BrowRightY": 1, "Brows": 1, "FaceAngleZ": 15},
    "whispering": {
        "MouthSmile": 0.5,
        "BrowRightY": -0.6,
        "Brows": 0,
        "FaceAngleZ": -15,
    },  # like sarcastic
    "disgusted": {"MouthSmile": -0.5, "BrowRightY": -0.5, "Brows": 1, "FaceAngleZ": 0},
    "sarcastic": {"MouthSmile": 0.5, "BrowRightY": -0.8, "Brows": 0, "FaceAngleZ": -15},
}


INTERNAL_EYE_ROTATER_DATA = {
    "old_emotion": "neutral",
    "last_emotion_params": EMOTION_TO_PARAMS["neutral"],
}


async def SimpleEmotionHandler(voice_ctx, vtube_studio):
    """
    MouthSmile
    -1 sad 0 neutral 1 happy
    Brows 0 normal 1 sad
    BrowRightY BrowLeftY equal but sums
    -1 down (like sarcastic) 0 normal 1 upper (like inspired)
    FaceAngleZ -30 0 30
    """
    try:

        current_speak_emo = voice_ctx["speak_entry"]["emotion"]
        # print("[NEW EYE ROT] current_speak_emo", current_speak_emo)
        if not current_speak_emo:
            return

        # TODO UNTESTED
        old_emo = INTERNAL_EYE_ROTATER_DATA["old_emotion"]
        if current_speak_emo != old_emo:

            print(
                "[EYE ROTATER NEW] EMOTION CHANGED FROM "
                + old_emo
                + " TO "
                + current_speak_emo
            )
            INTERNAL_EYE_ROTATER_DATA["old_emotion"] = current_speak_emo
            # current_speak_emo = current_speak_emo
            if current_speak_emo == "yandere":
                current_speak_emo = "angry"
                await vtube_studio.set_glich_effect(0.8)
                await vtube_studio.execute_hotkey("ArtMeshRedEyes")
            else:
                # standart
                if current_speak_emo == "angry":
                    await vtube_studio.set_glich_effect(0.1)
                elif old_emo in (
                    "angry",
                    "yandere",
                ):
                    await vtube_studio.set_glich_effect(0)
                if old_emo in ("yandere",):
                    await vtube_studio.execute_hotkey("ArtMeshStandart")
        if current_speak_emo not in list(EMOTION_TO_PARAMS.keys()):
            # INTERNAL_EYE_ROTATER_DATA["last_emotion_params"]
            emotion_params = INTERNAL_EYE_ROTATER_DATA["last_emotion_params"]
        else:

            value_map = EMOTION_TO_PARAMS[current_speak_emo]
            emotion_params = [{"id": k, "value": v} for k, v in value_map.items()]
            INTERNAL_EYE_ROTATER_DATA["last_emotion_params"] = emotion_params

            # print("[NEW EYE ROT] value_map", value_map)
            # TODO UNTESTED
        await vtube_studio.set_parameter(parameters=emotion_params)
    except Exception as e:
        print(f"[Vtube EYE ROT] error in EMOTION UPD cycle: {e}")
        traceback.print_exc()


async def VtubeRotater(ctx_swarm, vtube_studio):
    await vtube_studio.connect()
    vtube_ctx = ctx_swarm["vtube"]
    game_ctx = ctx_swarm["game"]
    voice_ctx = ctx_swarm["voice"]
    cnt = 0
    RUN_INTERVAL = 0.04
    while ctx_swarm["env"]["actived"]:
        cnt += RUN_INTERVAL
        if cnt >= 0.2:
            await SimpleEmotionHandler(voice_ctx, vtube_studio)
            cnt = 0

        if (
            game_ctx["ingame"]
            and game_ctx["hasActiveTask"]
            and not voice_ctx["is_speaking"]
        ):
            vtube_ctx["state"] = "gaming"
        else:
            vtube_ctx["state"] = "idle"
        # print ("\n\n\n[EYE ROT DEBUG]",game_ctx["ingame"], game_ctx["hasActiveTask"], vtube_ctx["state"])
        state = vtube_ctx.get("state", "idle")

        x = 0
        xvel = 0.01
        y = 0
        yvel = 0.01
        if state == "idle":
            x = 0
            y = 0
            vtube_ctx["eyeX"] = 0
            vtube_ctx["eyeY"] = 0
        elif state == "gaming":
            xmod = vtube_ctx.get("game_yawspeed", 0) / 30
            ymod = vtube_ctx.get("game_pitchspeed", 0) / 50
            # TODO untested behaviour
            x = -0.5
            y = -1.0

            # if(abs(ymod)>0.4):
            #    ymod=0
            # if abs(xmod) > 0.5:
            #     xmod /= 10
            x += xmod
            y += ymod
            vtube_ctx["eyeX"] = x
            vtube_ctx["eyeY"] = y
        diffx = vtube_ctx["NeedX"] - x
        diffy = vtube_ctx["NeedY"] - y
        # print("\n\nX =",vtube_ctx.NeedX,x,diffx,"\nY =",vtube_ctx.NeedY,y,diffy)
        if abs(diffx) > 0.02:
            vtube_ctx["NeedX"] = clp(vtube_ctx.get("NeedX", 0) - xvel * sgn(diffx))
        if abs(diffy) > 0.02:
            vtube_ctx["NeedY"] = clp(vtube_ctx.get("NeedY", 0) - yvel * sgn(diffy))
        await vtube_studio.setXY()
        await asyncio.sleep(RUN_INTERVAL)
        # print("[EyeRotater] DEBUG  X =", vtube_ctx["NeedX"], x, diffx, "\nY =", vtube_ctx["NeedY"], y, diffy)


def start_eye_rotater(ctx_swarm, vtube_studio):
    # VtubeRotaterThread = Thread(
    #    target=VtubeRotater,
    #    args=(
    #        ctx_swarm,
    #        vtube_studio,
    #    ),
    # )
    VtubeRotaterThread = Thread(
        target=asyncio.run,
        args=(VtubeRotater(ctx_swarm, vtube_studio),),
    )
    VtubeRotaterThread.daemon = True
    VtubeRotaterThread.start()
    return VtubeRotaterThread
