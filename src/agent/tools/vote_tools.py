from collections import defaultdict
from typing import Dict, List

from agent.tools import tools_config

# from agent.tools.tools_config import active_votes, ctx_swarm


active_votes = tools_config.active_votes
ctx_swarm = tools_config.ctx_swarm


def isVotingStarted(ctx_swarm) -> str:
    votes = ctx_swarm["votes"]
    try:
        if votes and len(list(votes.keys())) > 0:
            votes_data = dict(votes)
            topic = list(votes_data.keys())[-1]
            vote_data = votes_data[topic]
            if vote_data:
                return True
    except Exception as e:
        print(e)
    return False


def format_votes(ctx_swarm) -> str:

    votes = ctx_swarm["votes"]
    success = False
    result = ""
    try:
        if votes and len(list(votes.keys())) > 0:
            votes_data = dict(votes)
            topic = list(votes_data.keys())[-1]
            vote_data = votes_data[topic]
            if vote_data:

                results = sorted(
                    vote_data["votes"].items(), key=lambda x: x[1], reverse=True
                )

                # Get winner
                winner, winning_votes = results[0] if results else ("No votes", 0)
                for vote_type, count in results:
                    if count >= 0:
                        if not success:
                            result += "Голосование на тему '"
                            result += f"{topic}':\n"
                            success = True
                        result += f"{vote_type}: {str(count)}\n"
    except Exception as e:
        print(e)
    if not success:  # TODO потом убрать когда заработает
        result = "Голосований нет."
    return result


def _get_last_vote_topic():
    ctx_votes = ctx_swarm["votes"]
    votes_topics = list(ctx_votes.keys())
    if len(votes_topics) > 0:
        last_vote_topic = votes_topics[-1]
        return last_vote_topic
    else:
        raise Exception("There are no any active votes!")


def start_vote(topic: str, options: list[str]) -> str:
    """Start a new vote with topic and options

    Args:
        topic: What are we voting for
        options: List of voting options
    """
    ctx_votes = ctx_swarm["votes"]
    votes_topics = list(ctx_votes.keys())
    if topic in votes_topics:
        return f"Vote for the topic {topic} already exists"
    elif len(votes_topics) > 0 and not ctx_votes[votes_topics[-1]]["winner"]:
        previous_vote = votes_topics[-1]
        raise Exception(
            f"You have UNFINISHED previous vote '{previous_vote}'! Finish it first using finish_vote tool if you want to!"
        )
    vote_data = {
        "options": options,
        "votes": defaultdict(int),
        "voters": dict(),
        "winner": dict(),
    }
    for option in options:
        vote_data["votes"][option] = 0
    active_votes[topic] = vote_data
    ctx_swarm["votes"][topic] = vote_data
    # Announce vote creation
    vote_msg = f"New vote: {topic}\nOptions: " + ", ".join(options)
    return vote_msg


def _add_votes(votes: List[Dict[str, str]]) -> str:
    if isinstance(votes, dict):
        votes = [votes]
    for vote in votes:
        topic = vote["topic"]
        option = vote["option"]
        voter_name = vote["voter"]
        if topic not in active_votes:
            return f"Topic {str(option)} not exists"

        vote_data = active_votes[topic]
        if option not in vote_data["options"]:
            return f"Option {str(option)} not exists"

        # Prevent double voting
        if voter_name in vote_data["voters"].keys():
            return f"Voter {voter_name} is already voted. Cannot vote twice or change the vote!"

        vote_data["votes"][option] += 1
        vote_data["voters"][voter_name] = option
        ctx_swarm["votes"][topic] = vote_data
    # Announce vote
    return f"Votes registered for votes: {str(votes)}"


def add_votes_topic(votes: List[Dict[str, str]]) -> str:
    """Add a votes and voters for given topic.

    Args:
        list[dict]
        votes is a list of dicts, each dict with next keys:
            topic: Active vote topic
            option: Selected option
            voter: Name of voter
        Example: [{"topic": "str", "option": "str", "voter": "str"}, ...]
    """
    return _add_votes(votes)


def vote_register(voter: str, option: str) -> str:
    """Register a vote for last vote topic.

    Args:
        voter: Name (nickname) of voter
        option: Selected option by this voter
    """

    if not voter or not option:
        raise Exception("Vote topic or option is empty!")

    last_topic = _get_last_vote_topic()

    votes = {
        "topic": last_topic,
        "option": option,
        "voter": voter,
    }
    return _add_votes(votes)


def add_votes(votes: object) -> str:  # List[Dict[str, str]]
    """Add a votes and voters for last vote topic.

    Args:
        votes: List[Dict[str, str]], is a list of dicts, each dict with next keys:
            voter: Name (nickname) of voter
            option: Selected option by this voter

    Votes example structure: [{"voter": "str", "option": "str"}, ...]
    """
    last_topic = _get_last_vote_topic()
    if isinstance(votes, dict):
        votes = [votes]
    votes_with_topic = []
    for vote in votes:
        votes_with_topic.append(vote)
        vote["topic"] = last_topic
    return _add_votes(votes_with_topic)


def finish_vote_topic(topic: str) -> str:
    """End voting and show results.
    Args:
        topic: Topic to end voting for
    """
    if topic not in active_votes:
        return False

    vote_data = active_votes[topic]
    results = sorted(vote_data["votes"].items(), key=lambda x: x[1], reverse=True)

    if results:
        winner, winning_votes = results[0]
        result_msg = f"Voting results for topic {topic}:\n"
        for option, count in results:
            result_msg += f"{option}: {count} votes\n"
        result_msg += f"Winner: {winner} with {winning_votes} votes!"
    else:
        result_msg = f"Nobody voted for topic {topic}"
        winner, winning_votes = ("No votes", 0)
        active_votes.pop(topic, None)
        ctx_swarm["votes"].pop(topic, None)
        return result_msg
    vote_data["winner"] = {
        "winner": winner,
        "votes": winning_votes,
    }
    ctx_swarm["votes"][topic] = vote_data
    return result_msg


def finish_vote() -> str:
    """End voting and show results for last vote topic.
    NO ARGS
    """
    return finish_vote_topic(_get_last_vote_topic())
