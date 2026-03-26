"""Tools for managing agent state updates.

Based on the state structure defined in templates/structures.py and
state update patterns from agent/agent.py.

TODO add state wipe tool
TODO add state save tool
"""

from typing import Optional

from agent.tools import tools_config
from data_schema.structure_templates import THOUGHTS_FORMAT


def _validate_thought_field(key: str, value: str) -> tuple[bool, Optional[str]]:
    """Validate a thought field value against defined limits."""
    MAX_LENGTH = 300  # Characters limit for thought fields

    if not isinstance(value, str):
        return False, f"Value for {key} must be string"

    if len(value) > MAX_LENGTH:
        return False, f"Value for {key} exceeds {MAX_LENGTH} character limit"

    if key not in THOUGHTS_FORMAT:
        return False, f"Invalid thought field: {key}"

    return True, None


def plan(plan: str) -> str:
    """Updates agent plan field if it differs from current state.

    Args:
        plan: new plan
    """
    return state_update({"plan": plan})


def pattern(pattern: str):
    """Updates current agent pattern field if it differs from current state.

    Args:
        pattern: string, one of avaiable values

    Available values:
        `llm_answer` - answer seriously, truthfully, dryly, honestly and directly, as the LLM, NO jokes, only straight answer
        `greeting`
        `joking` - answer in a joking manner, with humor, sarcasm, irony, or a joke
        `commenting` - comment on the situation, ask questions, make remarks, or provide feedback
        `crazy` - act crazy, insane, or unpredictable, with no regard for consequences
    """
    return state_update({"pattern": pattern})


def focus(object: str) -> str:
    """Changes focus topic

    Args:
        object: string, focus object / topics
        Can be game / chat / person / yourself
    """
    return state_update({"focus_topic": object})


def summary(summary: str) -> str:
    """Updates current situation overall summary

    Args:
        summary: situation overall summary
    """
    return state_update({"summary": summary})


# TODO test investigate and check: maybe not work
# seems like agent runs don't take effect =(
def state_update(kwargs: dict[str, str]) -> str:  #  dict[str, str]
    """Update agent state fields if they differ from current state.

    Args:
        kwargs: Key-value pairs of state fields to update

    Available values:
        "summary": "short summary of current situation"
        "focus_topic"
        "restricted_topics"
        "plan"
        "criticism"

    Returns:
        str: Summary of state changes made
    """
    ctx_swarm = tools_config.ctx_swarm
    if not ctx_swarm:
        return "Error: Context not initialized"

    ctx_states = ctx_swarm["states"]
    print(
        "[DEBUG RUNNED STATE CHANGE]",
        kwargs,
        "\n[STATE TOOL DEBUG] TYPE CTX STATES=",
        type(ctx_states),
    )
    thoughts_state = ctx_states["thoughts"]
    print("[DEBUG RUNNED STATE CHANGE] OLD STATE", thoughts_state)
    changes = []

    for key, new_value in kwargs.items():
        # Validate the field
        valid, error = _validate_thought_field(key, new_value)
        if not valid:
            changes.append(f"Error for {key}: {error}")
            continue

        # Check if value actually changed
        old_value = thoughts_state.get(key)
        if old_value != new_value:
            # actually it may all works because i tested only in smolagent additional args, it may rewrite them and spoil...
            # maybe doesnt change
            # ctx_swarm["states"]["thoughts"][key] = new_value
            # explicit update
            old_thoughts = ctx_swarm["states"]["thoughts"]
            old_thoughts[key] = new_value
            # ctx_swarm["states"]["thoughts"] = old_thoughts

            # right inplace way

            ctx_swarm["states"].update({"thoughts": old_thoughts})

            changes.append(f"{key}")

    if not changes:
        return "No state changes needed"
    print("[DEBUG RUNNED STATE CHANGE] CHANGES", changes)
    print("[DEBUG RUNNED STATE CHANGE] NEW STATE", ctx_swarm["states"]["thoughts"])
    return "; ".join(changes)


# Define tool for smolagents format
state_tool = {
    "name": "update_state",
    "description": "Update agent state fields (summary, focus, plan, criticism)",
    "function": state_update,
    "args": {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "Brief summary of current situation",
            },
            "focus": {"type": "string", "description": "What to focus on"},
            "plan": {"type": "string", "description": "Action plan"},
            "criticism": {"type": "string", "description": "Self-criticism"},
        },
    },
}
