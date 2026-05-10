import os
import time
import traceback

import httpx
from mistralai import Mistral
from mistralai.client import MistralClient

from data_schema.chat_structures import MistralFilterResults

if __name__ == "__main__":
    import sys

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from config_schema.general import get_secret

client = Mistral(api_key=get_secret("MistralApiKey"))


class MistralFilter:
    def __init__(self, api_key=None):
        self.client = client
        self.errored = False

    def check_message(self, text: str) -> MistralFilterResults:
        try:
            response = self.client.classifiers.moderate(
                model="mistral-moderation-latest", inputs=[text]
            )

            result = response.results[0]
            categories = result.categories
            scores = result.category_scores

            is_harmful = any(categories.values())
            self.errored = False
            return {
                "acceptable": not is_harmful,
                "categories": categories,
                "category_scores": scores,
                "filtered_text": text if not is_harmful else "[FILTERED]",
            }
        except Exception as e:
            self.errored = True
            print(f"Mistral filter error: {e}")
            print(
                "ALARM!!! Mistral FILTER NOT CONNECTED!!! !!!!!!!!!!!!!!! FALLBACK TO ACCEPTABLE!!!"
            )
            traceback.print_exc()
            return {
                "acceptable": True,
                "categories": {},
                "category_scores": {},
                "filtered_text": text,
            }


if __name__ == "__main__":

    filter = MistralFilter()
    time.sleep(1)
    print("we're ready! Start!")
    start_time = time.time()

    print(filter.check_message("Привет, как дела!"))

    print("--- %s seconds ---" % (time.time() - start_time))

    # print(filter.check_message("жиды тупорылые"))
#
# print("--- %s seconds ---" % (time.time() - start_time))
#
# print(filter.check_message("Опять ты dawg!"))
#
# print("--- %s seconds ---" % (time.time() - start_time))
