"""Idea suggestor

This module is designed to choose ideas for LLM

TODO check idea realness / relevancy
"""

import random
from typing import Literal, OrderedDict, Union

from utils.prompt_helper import prompt_template_load


def get_random_idea(
    personality: str = "streamer_abstract", include_base: bool = True
) -> str:
    """Retrieve a random idea for use in LLM"""

    ALL_IDEAS = prompt_template_load("ideas")
    IDEAS = {}
    # print("[DEBUG] fJDSJIG S" + str(ALL_IDEAS))
    if include_base:
        BASE_IDEAS = ALL_IDEAS["base"]
        IDEAS.update(BASE_IDEAS)
    if personality:
        IDEAS.update(ALL_IDEAS.get(personality, {}))
    idea, description = random.choice(list(IDEAS.items()))
    result = f"""Daily idea suggestion for you: '{idea}': {description}. If you loved the idea, you may save it with pattern command. Dont reveal the idea name, its secret, you may only follow it."""
    return result


RANK_TO_LABEL = OrderedDict(
    {1: "agressive", 2: "negative", 3: "neutral", 4: "positive", 5: "love"}
)


def get_cringe_tag(
    rank: Union[float, int], gender: Literal["m", "f"] = "random"
) -> str:
    """Retrieve a cringe word for use in LLM"""

    ALL_WORDS = prompt_template_load("vocabulary")
    WORDS = {}
    if gender == "random":
        gender = random.choice(["m", "f"])
    # clamp min max
    rank = max(list(RANK_TO_LABEL.keys())[0], min(rank, list(RANK_TO_LABEL.keys())[-1]))
    # round if float
    rank = round(rank)
    label = RANK_TO_LABEL[rank]

    ALL_WORDS = prompt_template_load("vocabulary")
    # voc strucure: {str rank} {m/f} [words list]
    WORDS = ALL_WORDS[label][gender]
    word = random.choice(list(WORDS))
    return word
