import os
import sys
import time
from contextlib import contextmanager
from collections import Counter
from typing import Dict, List

from langchain_core.documents.base import Document


sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "src"
    ),
)

from agent.rag import (
    RAG_DOCS_DIR,
    CustomDirectoryLoader,
    CustomTripleNewLineSplitter,
    RagModel,
    timing_context,
)
from utils.string_helper import dict_to_str


class RagTest:
    def __init__(self):
        self.dataloader = CustomDirectoryLoader(RAG_DOCS_DIR, ["tests"])
        self.text_splitter = CustomTripleNewLineSplitter(
            chunk_size=1000, chunk_overlap=0, separator="\n\n"
        )
        self.docs = self.dataloader.load(self.text_splitter)
        self.wordkeys = self.dataloader.get_docs_wordkeys(self.docs)
        self.prepare_docs()
        self.test_results = []

    def prepare_docs(self):
        new_docs = []
        for i, wordkey in enumerate(self.wordkeys):
            text = self.docs[i].page_content
            text_lines = text.split("\n")
            if len(text_lines) > 1:
                text_lines.pop(0)
                text_to_add = "\n".join(text_lines)
            else:
                text_to_add = text
                print("[RAG TEST] FOUND BAD WORDKEY: ", wordkey)
            new_docs.append(text_to_add)
        self.queries = new_docs

    def test(self, rag_model):
        passed_tests = []
        failed_tests = []
        all_tests = []
        for i, wordkey in enumerate(self.wordkeys):
            query = self.queries[i]
            results = rag_model.retrieve_full(query)
            # print("Processing query '" + query + "'")
            k = 0
            test_result = False

            for result, score in results:
                k += 1
                result_text = result.page_content
                passed = wordkey.lower().strip() in result_text.lower().strip()
                test_result_dict = {"wordkey": wordkey, "pass": passed, "try": k, "score": float(score), "query": query, "answer": result_text}
                if k == 1:
                    test_result = passed
                    if not passed:
                        print(dict_to_str(test_result_dict))
                # print(f"{k}. [{score:2f}] {result}")
                all_tests.append(test_result_dict)
            if test_result:
                passed_tests.append(wordkey)
            else:
                failed_tests.append(wordkey)

            print(f"Test result: {test_result}")
        self.tests = all_tests
        self.print_summary(passed_tests, failed_tests)
        
    def print_summary(self, passed_tests, failed_tests):
        total_tests = len(self.wordkeys)
        passed_tests_num = len(passed_tests)
        success_rate = (passed_tests_num / total_tests) * 100
        
        print("\n=== Test Summary ===")
        print(f"Total tests: {total_tests}")
        print(f"Passed: {passed_tests_num}")
        print(f"Failed: {len(failed_tests)}")
        print(f"Success rate: {success_rate:.2f}%")
        cnt = Counter()
        for test in self.tests:
            if test["try"] <= 3 and test["pass"]:
                cnt["t"] += 1
        print(F"Top-3 k success rate: {cnt['t'] / total_tests * 100:.2f}%")
        if passed_tests_num:
            print("\nPassed keywords:")
            print(", ".join(passed_tests))

        if failed_tests:
            print("\nFailed keywords:")
            print(", ".join(failed_tests))
        print("==================")


def rag_test():
    os.environ["KMP_DUPLICATE_LIB_OK"] = "True"
    init_start = time.time()
    rag = RagModel()

    print("------------------------- retriever -------------------")
    ret = RagTest()
    ret.test(rag)


if __name__ == "__main__":
    rag_test()
