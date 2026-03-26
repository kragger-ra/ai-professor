import logging
import multiprocessing
import os
import random
import subprocess
import sys
import threading
import time
from collections import defaultdict
from multiprocessing import Manager, Process

import flask
from flask import Flask, render_template

if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from data_schema.ctx_structures import CtxSwarmType
from data_schema.structure_templates import CTX_SWARM_EMPTY


def clamp(n, smallest, largest):
    return max(smallest, min(n, largest))


def print_subtitles(inp, speed="fast", calculateTime=False):

    if not calculateTime:
        print("== ВЫВОДИМ СУБТИТРЫ ==")
        print("Субтитры>> ", end="", flush=True)  # rate x-slow slow medium fast x-fastt
    punktEnd = "!?."
    if speed == "fast":
        mult = 1
    elif speed == "x-fast":
        mult = 0.7
    elif speed == "medium":
        mult = 1.3
    elif speed == "slow":
        mult = 1.7
    elif speed == "x-slow":
        mult = 2.0
    resulttime = 0
    if inp:
        for symbol in inp:

            waittime = 0.04 * mult
            if symbol == " ":
                waittime = 0.06 * mult
            elif symbol == ",":
                waittime = 0.2 * mult
            elif punktEnd.find(symbol) != -1:
                waittime = 0.4 * mult
            if not calculateTime:
                print(symbol, end="", flush=True)
                time.sleep(waittime)
            else:
                resulttime += waittime
    if not calculateTime:
        print("\n==Субтитры выведены!==")
    else:
        # print('Время субтитров >>> '+str(resulttime))
        return resulttime


def HudLayerHandler(
    ctx,
    ctx_swarm: CtxSwarmType,
    SubtText,
    TextDisplaySpeed,
    RefreshInterval,
    screenPrintMas,
):

    log = logging.getLogger("werkzeug")
    log.disabled = True
    sitestring = ["чо деду чо бабке"]
    app = Flask(__name__)
    votes = ctx_swarm["votes"]
    text_to_display = ""
    newtext = "vzz"
    ####def update_text():
    ####    global text_to_display
    ####    global newtext
    ####    threading.Timer(0.01, update_text).start()
    ####    #print(newtext)
    ####    text_to_display = newtext
    ####
    ##### Start updating the text
    ####update_text()
    oldval = ""

    def SplitTextToParts(text, max_length=150):
        result = ""
        resultmas = []
        k = 0
        for i, char in enumerate(text):
            k += 1
            result += char

            if k >= max_length * 0.85:
                if char in " .!?":
                    k = max_length

            if k >= max_length:
                # print('4o ',k,max_length,resultmas)
                resultmas.append(result.strip())
                result = ""
                k = 0
            elif i == len(text) - 1:
                resultmas.append(result)
        return resultmas

    def generate_text_shawdow(
        outline_color="#000000", glow_color="#ff5cef"
    ):  # outline_color = '#000000',glow_color = '#ff5cef'
        return f"""<style type="text/css">
.OutlineText {{
    text-shadow:
    /* Outline 1 черный */
    -1px -1px 0 {outline_color},
    1px -1px 0 {outline_color},
    -1px 1px 0 {outline_color},
    1px 1px 0 {outline_color},  
    -2px 0 0 {outline_color},
    2px 0 0 {outline_color},
    0 2px 0 {outline_color},
    0 -2px 0 {outline_color}, 
    /* Outline 2 красный #ff0000 розовый #ff5cef */
    -2px -2px 0 {glow_color},
    2px -2px 0 {glow_color},
    -2px 2px 0 {glow_color},
    2px 2px 0 {glow_color},  
    -3px 0 0 {glow_color},
    3px 0 0 {glow_color},
    0 3px 0 {glow_color},
    0 -3px 0 {glow_color};
}}
</style>"""

    mood_list = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0]
    # import GPUtil
    old_moods = ["neutral"]

    EMOTION_TO_EMOJI = {
        "neutral": "😐",
        "happy": "😊",
        "sad": "😢",
        "angry": "😠",
        "scared": "😱",
        "whispering": "🤫",
        "disgusted": "🤢",
        "sarcastic": "🙃",
        "yandere": "🔪",
    }

    @app.route("/mood_data")
    def mood_data():
        mood_str = ctx_swarm["voice"]["speak_entry"]["emotion"]
        # print("000gfdgdf", mood_str)
        if mood_str:
            old_moods[0] = mood_str
        mood_str = old_moods[0]
        mood = 0  # round(ctx_swarm["mood"], 2)
        if mood_list[9] != mood and mood_list[10] == 0:
            old_mood = mood_list[9]
            mood_list[9] = mood
            mood_subtract = mood - old_mood
            mood_part = mood_subtract / 10
            for i in range(0, 9):
                mood_list[i] = old_mood + (i * mood_part)
            mood_list[10] = 0

        mood = round(mood_list[mood_list[10]], 2)
        if mood_list[10] >= 9:
            mood_list[10] = 0
        else:
            mood_list[10] = mood_list[10] + 1

        red, green, blue = 255, 255, 255
        emoji = EMOTION_TO_EMOJI.get(mood_str, "🤨")  # TODO untested
        # if mood >= 0.25:
        #     lol = int(clamp(25 + (mood // 0.039), 0, 255))
        #     red -= lol
        #     blue -= lol
        #     emoji = "😄"
        # elif mood <= -0.25:
        #     lol = int(clamp(25 + ((-mood) // 0.039), 0, 255))
        #     green -= lol
        #     blue -= lol
        #     emoji = "😬"

        return flask.jsonify(
            {
                "mood": mood_str,  # str(mood),
                "emoji": emoji,
                "color": f"rgba({red},{green},{blue},100)",
            }
        )

    old_text_entries = [""]

    @app.route("/subtitles_data")
    def subtitles_data():
        text = ctx_swarm["voice"]["speak_entry"]["text"]
        if text and len(screenPrintMas) == 0 and old_text_entries[0] != text:
            old_text_entries[0] = text
            screenPrintMas.extend(SplitTextToParts(text, 80))
            # SubtText.value = ""
            # empty internal voice ctx ?

        text = screenPrintMas.pop(0) if len(screenPrintMas) > 0 else ""
        return flask.jsonify({"text": text, "hasMore": len(screenPrintMas) > 0})

    @app.route("/info/")
    def systeminfo():
        def inner():
            yield """
<!DOCTYPE html>
<html>
<head>
    <title>Информация о системе</title>
<script>
function updateMood() {
    fetch('/mood_data')
        .then(response => response.json())
        .then(data => {
            document.getElementById('mood-container').innerHTML = 
                `<p>${data.emoji} ${data.mood}</p>`;
            document.documentElement.style.setProperty('--glow-color', data.color);
        });
}
setInterval(updateMood, 100);
</script>
<style>
:root { --glow-color: rgba(255,255,255,100); }
"""
            yield generate_text_shawdow(glow_color="var(--glow-color)")
            yield """
</style>
</head>
<body style="font-size:25pt; color:rgba(255,255,255,100); text-align:left; vertical-align:up"; align="center">
    <font face="Minecraft Rus">
        <div class="OutlineText" id="mood-container">
            <p>---</p>
        </div>
    </font>
</body>
</html>"""

        return flask.Response(inner(), mimetype="text/html")

    @app.route("/hud_data")
    def hud_data():
        votes = ctx_swarm["votes"]
        vote_info = {"has_votes": False, "topic": "", "results": []}

        try:
            if votes and len(list(votes.keys())) > 0:
                votes_data = dict(votes)
                topic = list(votes_data.keys())[-1]
                vote_data = votes_data[topic]
                if vote_data:
                    results = sorted(
                        vote_data["votes"].items(), key=lambda x: x[1], reverse=True
                    )
                    vote_info = {
                        "has_votes": True,
                        "topic": topic,
                        "results": [
                            {"type": vote_type, "count": count}
                            for vote_type, count in results
                            if count >= 0
                        ],
                    }
                    winner = vote_data.get("winner", None)
                    if winner:
                        vote_info["winner"] = winner
        except Exception as e:
            print("[HUD LAYER VOTES EXC]", e)

        return flask.jsonify(vote_info)

    @app.route("/hud/")
    def hud():
        return render_template("hud.html")

    @app.route("/")
    @app.route("/subtitles/")
    def index():
        def inner():
            if True:  # SubtText.value != "" or len(screenPrintMas) != 0:
                # color:rgba(255,6,132,100); сиреневый
                # yield """<head> <link rel="stylesheet" href='/templates/static/main.css' /> </head> <body style="font-size:33pt; color:rgba(255,255,255,100); text-align:center; vertical-align:bottom"; align="center"> <font face="Impact">""" #align="center"
                yield """
<!DOCTYPE html>
<html>
<head>
    <meta http-equiv="Content-Type" content="text/html; charset=utf-8" />
    <title>Субтитры</title>
"""
                yield generate_text_shawdow()
                yield """
</head>
<body style="font-size:33pt; color:rgba(255,255,255,100); text-align:center; vertical-align:bottom"; align="center">
    <font face="Impact">
        <div class="OutlineText" id="subtitles-container"></div>
    </font>
<script>
async function animateText(text, speed) {
    const container = document.getElementById('subtitles-container');
    container.textContent = '';
    const punktEnd = "!?.";
    const mult = {"fast": 1, "x-fast": 0.7, "medium": 1.3, "slow": 1.7, "x-slow": 2.0}[speed] || 1;
    
    for(let i = 0; i < text.length; i++) {
        const char = text[i];
        let waitTime = 40 * mult;
        if(char === " ") waitTime = 60 * mult;
        else if(char === ",") waitTime = 200 * mult;
        else if(punktEnd.includes(char)) waitTime = 400 * mult;
        
        container.textContent += char;
        await new Promise(resolve => setTimeout(resolve, waitTime));
    }
}

async function checkSubtitles() {
    const response = await fetch('/subtitles_data');
    const data = await response.json();
    if(data.text) {
        await animateText(data.text, 'fast');
        setTimeout(checkSubtitles, data.hasMore ? 100 : 1400);
    } else {
        setTimeout(checkSubtitles, 100);
    }
}

checkSubtitles();
</script>
</body>
</html>"""

        return flask.Response(inner(), mimetype="text/html")

    app.run(port=int(os.getenv("HUD_LAYER_PORT", 22236)))  # older it was 5000


if __name__ == "__main__":
    from multiprocessing import Manager

    manager = Manager()
    ctx = manager.Namespace()
    ctx.mood = 0.02
    textSubtitlesHttp = manager.Value("u", "")
    TextDisplaySpeed = manager.Value("u", "fast")
    RefreshInterval = manager.Value("i", 3)
    screenPrintMas = manager.list()

    TextDisplaySpeed.value = "fast"
    textSubtitlesHttp.value = (
        """Привет! Мне кажется, плохо пахнет. Кто испортил мне воздух?""" * 100
    )

    import threading
    import time

    ctx_swarm = CTX_SWARM_EMPTY
    ctx_votes_dict = manager.dict(ctx_swarm["votes"])
    ctx_swarm["votes"] = ctx_votes_dict
    ctx_swarm["voice"]["speak_entry"] = {
        "text": "Привет! Мне кажется, плохо пахнет. Кто испортил мне воздух?",
        "emotion": "angry",
    }
    ctx_votes_dict.update(
        {
            "ExampleVote": {
                "options": ["Hello", "World", "Lol"],
                "votes": defaultdict(int, {"Hello": 1, "World": 0, "Lol": 0}),
                "voters": {"ExampleUser": "Hello"},
                "winner": {},
            }
        }
    )

    def testFunc():
        while True:
            ctx.mood = ctx.mood + random.choice([1.01, -1.01])
            time.sleep(0.1)

    def testVoteFunc():
        while True:
            time.sleep(5)
            ctx_votes_dict.update(
                {
                    "ExampleVote": {
                        "options": ["Hello", "World", "Lol"],
                        "votes": defaultdict(int, {"Hello": 1, "World": 1, "Lol": 0}),
                        "voters": {"ExampleUser": "Hello", "ExampleUser2": "World"},
                        "winner": {},
                    }
                }
            )
            time.sleep(10)
            ctx_votes_dict.update(
                {
                    "ExampleVotee": {
                        "options": ["Hello", "World", "Lol"],
                        "votes": defaultdict(int, {"Hello": 2, "World": 1, "Lol": 0}),
                        "voters": {
                            "ExampleUser": "Hello",
                            "ExampleUser2": "World",
                            "ExampleUser3": "Hello",
                        },
                        "winner": {},
                    }
                }
            )
            time.sleep(5)
            ctx_votes_dict.update(
                {
                    "ExampleVotee": {
                        "options": ["Hello", "World", "Lol"],
                        "votes": defaultdict(int, {"Hello": 3, "World": 1, "Lol": 0}),
                        "voters": {
                            "ExampleUser": "Hello",
                            "ExampleUser2": "World",
                            "ExampleUser3": "Hello",
                            "ExampleUser4": "Hello",
                        },
                        "winner": {"winner": "Hello", "votes": 3},
                    }
                }
            )
            time.sleep(5)
            ctx_votes_dict.pop("ExampleVote", None)
            ctx_votes_dict.pop("ExampleVotee", None)

    testThread = threading.Thread(target=testFunc)
    testThread.daemon = True
    testThread.start()
    testVoteThread = threading.Thread(target=testVoteFunc)
    testVoteThread.daemon = True
    testVoteThread.start()
    # ctx_swarm["votes"] = [
    #     {
    #         "Who is cool?": {
    #             "options": ["Hello", "World"],
    #             "voters": {"Yo": "Hello"},
    #             "votes": {"Hello": 1},
    #         }
    #     }
    # ]

    # [{'HH': {'options': ['Hello', 'World'], 'votes': defaultdict(<class 'int'>, {'Hello': 1}), 'voters': {'ExampleUser': 'Hello'}, 'winner': {'winner': 'Hello', 'votes': 1}}, 'topic': {'options': ['Hello', 'World'], 'votes': defaultdict(<class 'int'>, {'Hello': 1}), 'voters': {'ExampleUser': 'Hello'}, 'winner': {'winner': 'Hello', 'votes': 1}}}]

    HudLayerHandler(
        ctx,
        ctx_swarm,
        textSubtitlesHttp,
        TextDisplaySpeed,
        RefreshInterval,
        screenPrintMas,
    )
