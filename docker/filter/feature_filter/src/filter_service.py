import logging
import os
import traceback
import json
from dataclasses import dataclass
from typing import List, Optional

from .model_filter import ModelFilter
from .text_moderation import TextModeration
from .regex_censure import SimpleRegexCensor

# Get the directory containing this file
THIS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BANNED_WORDS_FILE = os.path.join(
    THIS_DIR, "data", "block_words", "banned_words_cat_2_2.csv"
)
CATEGORIES_FILE = os.path.join(THIS_DIR, "data", "block_words", "categories_2.csv")


@dataclass
class FilterResult:
    acceptable: bool
    reason: str
    judge: bool
    topics: List[str]
    score: float = 0.0
    filtered_text: Optional[str] = None


class ContentFilter:
    def __init__(self):
        self.text_moderator = TextModeration(
            banned_words=[], hard_banned_words=[], levenshtein_distance_threshold=2
        )
        self.model_filter = ModelFilter()
        self.regex_censor = SimpleRegexCensor()
    # def score_topics(self, topics: list):
    #     score = 0
    #     for topic in topics:
    #         if topic in "politics,racism,religion,terrorism,suicide".split(","):
    #             score += -10

    #         if topic in "offline_crime,drugs,social_injustice".split(","):
    #             score += -1
    #         if topic in "pornography,prostitution,sexism,sexual_minorities".split(
    #             ","
    #         ):
    #             score += -0.5
    #         if topic in "online_crime".split(","):
    #             score += -0.25
    #         if topic in "body_shaming,health_shaming".split(","):
    #             score += -0.1
    #         if topic in "slavery,gambling,weapons".split(","):
    #             score += -0.01
    #         if score >= 0:
    #             score += 0.3
    #     # normalizing score [-10, 0.5] to [0, 1]
    #     score = (score + 10) / 10.5
    def process_text(self, text: str) -> FilterResult:
        logging.info("[FILTER] got query text: \n'" + text + "'\n")
        if not text:
            return FilterResult(
                acceptable=True,
                reason="EMPTY_TEXT",
                judge=True,
                topics=[],
                score=0.0,
                filtered_text="",
            )

        try:
            judge_allow, topics, model_score = self.model_filter.analyze_text(text)
        except Exception as e:
            logging.error(f"Model analysis failed: {e}")
            traceback.print_exc()
            judge_allow = True
            topics = []
            model_score = 0.0

        try:
            probability = 0
            has_banned = False
            # SASHA FILTER REMOVED!!!!!!!!!!!!!!!!!!!
            # TODO INVESTIGATE
            # BLOCKING EVERY WORD!!!!!!!
            # probability, has_banned = (
            #     self.text_moderator.check_banned_words_with_categories(
            #         text, BANNED_WORDS_FILE, CATEGORIES_FILE
            #     )
            # )
            model_score = max(model_score, probability)
        except Exception as e:
            logging.error(f"Text moderation failed: {e}")
            traceback.print_exc()
            has_banned = False
            probability = 0.0
        regex_filter_results = self.regex_censor.check_profinity(text)
        logging.info("[FILTER] debug regex filter results:\n" 
                        + json.dumps(regex_filter_results, 
                                    indent=4,
                                    ensure_ascii=False
                                    )
        )
        regex_filter_allow = regex_filter_results["acceptable"]
        # print("[FILTER] profanity filter results:", has_banned)
        found_bad_topics = len(topics) > 0
        berts_banned = not judge_allow and found_bad_topics
        acceptable = not berts_banned and regex_filter_allow  # and not has_banned
        reason = "ACCEPTABLE"

        if not acceptable:
            if not regex_filter_allow or has_banned:
                reason = "BAD_WORD"
            else:
                if not judge_allow:
                    if found_bad_topics:
                        reason = "TOXIC_BAD_TOPICS"
                    else:
                        reason = "TOXIC"
                elif found_bad_topics:
                    reason = "BAD_TOPICS"
                else:
                    reason = "UNKNOWN"
        if acceptable:
            filtered_text = text
        else:
            filtered_text = "[FILTERED]"
        # if acceptable and reason == "BAD_WORD":
        #     filtered_text = self._filter_bad_words(text)
        # TODO regex filter has good filtering, implement
        # if model_score > 0.9:
        #     acceptable = False
        logging.info("[FILTER] debug other filter results:\n" 
                        + json.dumps({
                            "judge_allow": judge_allow,
                            "topics": topics,
                            "model_score": model_score,
                            "acceptable": acceptable,
                            "has_banned": has_banned,
                            "regex_filter_allow": regex_filter_allow,
                            "found_bad_topics": found_bad_topics,
                            "berts_banned": berts_banned,
                            "reason": reason,
                                    }, 
                                    indent=4,
                                    ensure_ascii=False
                        )
        )
        return FilterResult(
            acceptable=acceptable,
            reason=reason,
            judge=judge_allow,
            topics=topics,
            score=model_score,
            filtered_text=filtered_text,
        )

    def _filter_bad_words(self, text: str) -> str:
        """Filter bad words by replacing them with asterisks."""
        try:
            # Get all transliterated and processed variations
            processed_words = self.text_moderator.process_text(text)

            # Load banned words
            banned_words = {}
            with open(BANNED_WORDS_FILE, "r", encoding="utf-8") as f:
                # Skip header
                next(f)
                for line in f:
                    word = line.strip().split(",")[0]
                    banned_words[word.lower()] = "*" * len(word)

            result = text
            for word in processed_words:
                if word in banned_words:
                    result = result.replace(word, banned_words[word])
                else:
                    # Check for Levenshtein distance matches
                    for banned_word in banned_words:
                        if self.text_moderator.is_near_match(word, banned_word):
                            result = result.replace(word, "*" * len(word))
                            break

            return result
        except Exception as e:
            logging.error(f"Word filtering failed: {e}")
            return "*" * len(text)
