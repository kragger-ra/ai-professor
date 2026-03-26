"""
Game agent

For complex minecraft tasks
Agent with embedded reaction pipeline, like
initial prompt and situation + minecraft tools -> llm run ->
tool for found something in game -> llm run - see result and decide what to run next
-> new tool call
etc.

LLM tool run / tool output parsing format: langchain

Example run:
=System=
You are nettyan
there are 5 players around you
The overall situation is: (from plan agent)
players are arguing about some non-interesting stuff

tools:
minecraft_command
agent_command
=User=
History of events
=User= x N
Some player action / ... (like in other agent)
=Agent=
inner tool call log
tool call result, etc
=User=
Some user activity
=Agent=
tool calls, etc
...
=User=
Reminder what should we do as for plan

"""
