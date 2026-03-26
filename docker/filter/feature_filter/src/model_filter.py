import json
import logging
import os
from typing import Dict, List, Tuple

import numpy as np
import torch
from transformers import BertForSequenceClassification, BertTokenizer

logger = logging.getLogger(__name__)


# TODO utils func move to filter/utils
def adjust_multilabel(y, target_vaiables_id2topic_dict, is_pred=False):
    y_adjusted = []
    for y_c in y:
        y_test_curr = [0] * 19
        index = str(int(np.argmax(y_c)))
        # value = y_c[index]
        y_c = target_vaiables_id2topic_dict[index]
    return y_c


def get_elements_of_nested_list(element):
    count = 0
    if isinstance(element, list):
        for each_element in element:
            count += get_elements_of_nested_list(each_element)
    else:
        count += 1
    return count


class ModelFilter:
    def __init__(self):
        self.device = "cpu"
        self.models_loaded = False
        self.tokenizer = None
        self.judge_model = None
        self.topic_model = None
        self.target_variables_dict = None

        self.model_paths = {
            "judge": {
                "id": "apanc/russian-inappropriate-messages",
                "path": "/models/apancJudge",
            },
            "topics": {
                "id": "apanc/russian-sensitive-topics",
                "path": "/models/apancTopics",
            },
            "topics_new": {
                "id": "Den4ikAI/russian_sensitive_topics",
                "path": "/models/denchikTopics",
            },
        }
        self.this_dir = ""
        self.this_data_dir = "/app/data"
        with open(self.this_data_dir + "/id2topic.json") as f:
            self.target_vaiables_id2topic_dict = json.load(f)

    def debug_new_topics_model(self):
        for model_name_, model_data in self.model_paths.items():
            os.makedirs(model_data["path"], exist_ok=True)
        self.large_topic_model: BertForSequenceClassification = (
            BertForSequenceClassification.from_pretrained(
                self.model_paths["topics_new"]["id"],
                cache_dir=self.model_paths["topics_new"]["path"],
            ).to(self.device)
        )

        self.large_topic_tokenizer: BertTokenizer = BertTokenizer.from_pretrained(
            self.model_paths["topics_new"]["id"],
            cache_dir=self.model_paths["topics_new"]["path"],
        )
        text = "мда"
        inputs = self.large_topic_tokenizer(
            text, max_length=512, add_special_tokens=False, return_tensors="pt"
        ).to(self.device)
        with torch.no_grad():
            topics_pred = self.large_topic_model(**inputs).logits
        topics = []
        preds = adjust_multilabel(
            topics_pred, self.target_vaiables_id2topic_dict, is_pred=True
        )
        if preds != "none":
            topics = list(set(topics + preds.split(",")))
        logger.info("Models den4ik loaded " + str(topics))

    def load_models(self):
        if self.models_loaded:
            return

        try:
            self.tokenizer = BertTokenizer.from_pretrained(
                self.model_paths["judge"]["id"],
                cache_dir=self.model_paths["judge"]["path"],
            )

            self.judge_model = BertForSequenceClassification.from_pretrained(
                self.model_paths["judge"]["id"],
                cache_dir=self.model_paths["judge"]["path"],
            ).to(self.device)

            self.topic_model = BertForSequenceClassification.from_pretrained(
                self.model_paths["topics"]["id"],
                cache_dir=self.model_paths["topics"]["path"],
            ).to(self.device)

            self.debug_new_topics_model()
            self.models_loaded = True
            logger.info("Models loaded successfully")
        except Exception as e:
            logger.error(f"Error loading models: {e}")
            raise

    def analyze_text(self, text: str) -> Tuple[bool, List[str], float]:
        self.load_models()

        input_cnt = 0
        with torch.no_grad():

            tokenized = self.tokenizer.batch_encode_plus(
                [text],
                max_length=256,
                padding=True,
                truncation=True,
                return_token_type_ids=False,
            )  # было max length 512
            tokens_ids, mask = torch.tensor(tokenized["input_ids"]), torch.tensor(
                tokenized["attention_mask"]
            )

            input_cnt += get_elements_of_nested_list(tokens_ids.tolist())

            with torch.no_grad():
                topics_pred = self.topic_model(tokens_ids, mask)
                judgement_out = self.judge_model(tokens_ids, mask)

            judgement_label = judgement_out["logits"].argmax().item()
            allow = not bool(judgement_label)
            topics = []
            preds = adjust_multilabel(
                topics_pred["logits"], self.target_vaiables_id2topic_dict, is_pred=True
            )
            if preds != "none":
                topics = list(set(topics + preds.split(",")))
            model_score = judgement_label

        return allow, topics, model_score
