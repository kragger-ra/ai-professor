import os
import sys
from typing import Dict

import yaml

if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from config_schema.general import get_name
from data_schema.structure_templates import REPO_PROMPTS_PATH

SELF_NAME = get_name()


def prompt_load(
    name: str, role_description: str, mapping: Dict[str, str] = None
) -> str:
    # personalty/lexa.yaml
    path = os.path.join(
        REPO_PROMPTS_PATH, f"{name}.yml"
    )  # f"resources/Prompts/{name}.yml"
    prompt = yaml_load(path)[role_description]
    if SELF_NAME != "NetTyan":  # temp fix for using old prompts
        prompt = prompt.replace("NetTyan", SELF_NAME)
    if mapping:
        try:
            for key, value in mapping.items():
                prompt = prompt.replace("{" + key + "}", value)
            # prompt = prompt.format(**mapping)
        except KeyError as e:
            print(f"Missing key in mapping: {e}", mapping, role_description, name)
    return prompt


def prompt_template_load(name: str) -> dict:
    # personalty/lexa.yaml
    path = os.path.join(
        REPO_PROMPTS_PATH, f"{name}.yml"
    )  # f"resources/Prompts/{name}.yml"
    prompt_template = yaml_load(path)
    return prompt_template


def yaml_load(yaml_path: str) -> dict:
    with open(yaml_path, "r", encoding="utf8") as file:
        result_dict = yaml.safe_load(file)
    return result_dict


if __name__ == "__main__":
    # print(prompt_load("test_prompt", "role_description"))
    print("--------------")
    print(yaml_load("../../resources/Prompts/test_prompt.yml"))
