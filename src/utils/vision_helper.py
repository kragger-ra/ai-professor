import base64
import io
from os import getenv

from PIL import Image

client = None
using_obs = True


def get_obs_frame() -> str:
    """
    Capture a screenshot from OBS.
    """
    global using_obs, client
    try:
        # Load obs websocket client
        if client is None:
            from obsws_python import ReqClient

            host = "localhost"
            port = str(getenv("OBS_WEBSOCKET_PORT", "4455"))
            password = getenv("OBS_WEBSOCKET_PASSWORD")
            client = ReqClient(host=host, port=port, password=password)

        current_scene = client.get_current_program_scene()
        scene_name = current_scene.current_program_scene_name

        # Get screenshot of the current program scene
        response = client.get_source_screenshot(
            name=scene_name,  # Or get current scene first
            img_format="jpg",
            width=1920,
            height=1080,
            quality=60,
        )

        # Extract base64 image data (response is dict with 'image_data' key)
        img_data = response.image_data

        # data:image/jpg;base64,/9j/4AA

        # client.disconnect()

        # # For saving
        # img_data_only = response.image_data.split(',')[1]
        # img_bytes = base64.b64decode(img_data_only)
        # img = Image.open(io.BytesIO(img_bytes))
        # img.save(path)
    except Exception as e:
        print(f"[VISION HELPER] Error capturing OBS frame: {e}")
        img_data = ""
        using_obs = False
    return img_data


def img_to_str(image: Image.Image) -> str:
    img_byte_arr = io.BytesIO()
    image = image.convert("RGB")  # if rgba
    image.save(img_byte_arr, format="JPEG")  # Save image to bytes buffer
    img_byte_arr = img_byte_arr.getvalue()  # Get bytes value
    cypher = base64.b64encode(img_byte_arr).decode("utf-8")
    return "data:image/jpeg;base64," + cypher


def get_actual_frame() -> str:
    return get_obs_frame()


def load_sample_image() -> str:
    img = Image.open(
        r"C:\Pets\NetTyan\Python\NetTyanRepo\NetTyan\resources\Pictures\app.png"
    )
    img_str = img_to_str(img)
    return img_str


if __name__ == "__main__":
    print(
        "sample img =", get_obs_frame()[:30], "..."
    )  # Print first 30 chars of base64 string
