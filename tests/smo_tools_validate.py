import os, sys

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "src"
    ),
)


from agent.smo.agent_factory import setup_tools


setup_tools()