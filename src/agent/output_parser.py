from typing import Dict

from langchain.schema import BaseOutputParser


def cut_spaces(text: str) -> str:
    result = []
    prev_was_space = False
    for char in text:
        if char == " ":
            if not prev_was_space:
                result.append(char)
            prev_was_space = True
        else:
            result.append(char)
            prev_was_space = False
    return "".join(result).strip()


class FredOutputParser(BaseOutputParser):
    def get_format_instructions(self) -> str:
        return """Output should contain:
- Main response text
- Optional emotion in square brackets [эмоция=X]
- Optional command in angle brackets <команда=X>
"""

    def parse(self, text: str) -> Dict:
        def extract_tag(text: str, tag_type: str = "emo") -> Dict[str, str]:
            brackets = ["[", "]"] if tag_type == "emo" else ["<", ">"]
            cmdlist = (
                "агрессия, скука, усталость, интерес, смущение, счастье, веселье, страх".split(
                    ", "
                )
                if tag_type == "emo"
                else "бан, издевайся, попрыгай, смейся, кричи, убегай".split(", ")
            )

            start_idx = text.find(brackets[0]) + 1
            end_idx = text.rfind(brackets[1])

            result = ""
            if start_idx > 0 and end_idx > 0:
                content = text[start_idx:end_idx]
                for cmd in cmdlist:
                    if cmd in content:
                        result = cmd
                        break
                text = text[: start_idx - 1] + text[end_idx + 1 :]
            return {"cmd": result, "text": text}

        text = cut_spaces(text.replace("<extra_id_0>", "").replace("A:", "").strip())

        emotion_result = extract_tag(text, "emo")
        text = emotion_result["text"]
        command_result = extract_tag(text, "cmd")

        return {
            "reply": command_result["text"],
            "emotion": emotion_result["cmd"] or "нет",
            "command": command_result["cmd"] or "нет",
        }
