# pip install py_audio2face[streaming]
import time

import py_audio2face as pya2f

a2f = pya2f.Audio2Face()

# audio = AudioFile().from_file("path/to/audio/file.wav")
# audio_stream = audio.to_stream()  # note: this can be any python generator that yields numpy arrays/bytes of audio data
# a2f.stream_audio(audio_data, output_path="path/to/output/animation.usd", fps=60)
# Generate animation for a single audio file
AUDIO_SAMPLE = (
    r"D:\Pets\NetTyan\Python\NetTyanRepo\NetTyan\resources\Audio\refs\cursing.wav"
)
OUTPUT_SAMPLE = r"D:\Pets\NetTyan\Python\NetTyanRepo\NetTyan\data\live2d_test\anim.usd"
a2f.audio2face_single(
    audio_file_path=AUDIO_SAMPLE,  #  path of the audio file you want to animate
    output_path=OUTPUT_SAMPLE,  # path where the animation file will be saved
    fps=60,  # frames per second for the animation. Higher fps will result in smoother animations and longer processing time
    emotion_auto_detect=True,  # automatically detect emotions in the audio file. If false the set emotion will be used
)

# Generate animation for an entire folder of audio files
# a2f.audio2face_folder(input_folder="path/to/my/folder", output_folder='/output', fps=60)
time.sleep(20)
print("EXITING...")
