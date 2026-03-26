import os
import signal
import sys
import time

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "src"
    ),
)

from data_flow.filter_client import FilterClient


def test_filter_functionality():
    filter_client = FilterClient()

    test_cases = [
        "Привет, как дела?",
        "Привет как дела, лох?",
        "This is a test message",
        "Это тестовое сообщение",
    ]

    print("Starting filter tests...\n")

    for text in test_cases:
        print(f"Testing text: '{text}'")
        try:
            result = filter_client.check_message(text)

            print("Filter Results:")
            print(f"  Acceptable: {result['acceptable']}")
            print(f"  Reason: {result['reason']}")
            print(f"  Judge: {result['judge']}")
            print(f"  Topics: {result['topics']}")
            print(f"  Score: {result['score']}")
            print(f"  Filtered text: {result['filtered_text']}")
            print("-" * 50)

        except Exception as e:
            print(f"Error testing text: {e}")
            print("-" * 50)

        time.sleep(0.5)


if __name__ == "__main__":
    try:
        print("Starting filter test script...")
        test_filter_functionality()
        print("Filter testing completed.")
    except KeyboardInterrupt:
        print("\nTest interrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"An error occurred: {e}")
        sys.exit(1)
