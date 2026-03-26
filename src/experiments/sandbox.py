import asyncio
from typing import TypedDict


def foo(arg1, arg2=None, arg3=None):
    print(f"foo called with {arg1}, {arg2}, {arg3}")


# foo_args = {1: "hi", 2: 3, 3: "lol"}
#
# foo(**foo_args)


class Movie(TypedDict):
    name: str
    year: int


lol = Movie()


lol["ahahah"] = "123"

print(lol["name"])


async def long_task():
    await asyncio.sleep(5)
    print("Long task finished")
    return "Done"


async def main():
    # Create background task
    task = asyncio.create_task(long_task())

    print("This runs immediately")
    # Do other work here...

    # Optional: wait for task to complete at the end
    await task


# Run the main function
if __name__ == "__main__":
    asyncio.run(main())
