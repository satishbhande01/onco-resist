"""
app/agent/agent.py

The OncoDB AI agent.
Handles the Groq tool calling loop — sends messages to the LLM,
executes tool calls, feeds results back, gets final response.
"""

import json
import os
from dotenv import load_dotenv
from groq import Groq

from app.agent.prompt  import SYSTEM_PROMPT
from app.agent.schemas import TOOL_SCHEMAS, TOOL_REGISTRY
from app.agent import tools as tool_module

load_dotenv()

# ─────────────────────────────────────────────────────────────
# Groq client
# ─────────────────────────────────────────────────────────────

client = Groq(api_key=os.getenv("GROQ_API_KEY"))
MODEL  = "llama-3.3-70b-versatile"

MAX_TOOL_ROUNDS = 5   # prevent infinite tool calling loops


# ─────────────────────────────────────────────────────────────
# Tool execution
# ─────────────────────────────────────────────────────────────

def execute_tool(tool_name: str, tool_args: dict) -> str:
    """
    Look up the tool function by name and call it with the given args.
    Returns the result as a JSON string for the LLM to read.
    """
    func = getattr(tool_module, tool_name, None)

    if func is None:
        return json.dumps({"error": f"Tool '{tool_name}' not found."})

    try:
        result = func(**tool_args)
        return json.dumps(result, ensure_ascii=False)
    except TypeError as e:
        return json.dumps({"error": f"Invalid arguments for {tool_name}: {str(e)}"})
    except Exception as e:
        return json.dumps({"error": f"Tool execution failed: {str(e)}"})


# ─────────────────────────────────────────────────────────────
# Main agent function
# ─────────────────────────────────────────────────────────────

def run_agent(
    message:     str,
    history:     list[dict] = None,
    page_context: str       = "",
) -> dict:
    """
    Run the agent for a single user turn.

    Args:
        message:      The user's message
        history:      Previous conversation turns
                      [{"role": "user"|"assistant", "content": "..."}]
        page_context: Optional string describing what page the user is on
                      e.g. "Viewing drug: Imatinib (BCR-ABL Inhibitor)"

    Returns:
        {
            "answer":  str,   final response text
            "history": list,  updated conversation history
            "tools_used": list  names of tools that were called
        }
    """
    history     = history or []
    tools_used  = []

    # Build system message
    # Inject page context if available so agent knows what user is viewing
    system_content = SYSTEM_PROMPT
    if page_context:
        system_content += f"\n\n## Current Page Context\n{page_context}\n"

    # Build message list for Groq
    # System + history + new user message
    messages = [
        {"role": "system", "content": system_content}
    ]

    # Add conversation history
    for turn in history:
        if turn.get("role") in ("user", "assistant", "tool"):
            messages.append(turn)

    # Add the new user message
    messages.append({"role": "user", "content": message})

    # ── Tool calling loop ──────────────────────────────────
    # The LLM may call multiple tools in sequence before
    # producing a final answer. We loop until it stops
    # calling tools or we hit MAX_TOOL_ROUNDS.

    for round_num in range(MAX_TOOL_ROUNDS):

        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=TOOL_SCHEMAS,
            tool_choice="auto",
            max_tokens=2048,
            temperature=0.1,   # low temperature for factual accuracy
        )

        choice  = response.choices[0]
        message_obj = choice.message

        # Add assistant's response to message list
        messages.append({
            "role":       "assistant",
            "content":    message_obj.content or "",
            "tool_calls": [
                {
                    "id":       tc.id,
                    "type":     "function",
                    "function": {
                        "name":      tc.function.name,
                        "arguments": tc.function.arguments,
                    }
                }
                for tc in (message_obj.tool_calls or [])
            ] or None
        })

        # If no tool calls — LLM is done, return the answer
        if not message_obj.tool_calls:
            answer = message_obj.content or ""
            break

        # Execute each tool call
        for tool_call in message_obj.tool_calls:
            tool_name = tool_call.function.name
            tools_used.append(tool_name)

            try:
                tool_args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                tool_args = {}

            print(f"[Agent] Tool call: {tool_name}({tool_args})")

            tool_result = execute_tool(tool_name, tool_args)

            print(f"[Agent] Tool result length: {len(tool_result)} chars")

            # Feed tool result back to the LLM
            messages.append({
                "role":         "tool",
                "tool_call_id": tool_call.id,
                "content":      tool_result,
            })

    else:
        # Hit MAX_TOOL_ROUNDS without a final answer
        answer = (
            "I was unable to complete this query — "
            "too many tool calls required. Please try a more specific question."
        )

    # ── Build updated history for next turn ───────────────
    # Store only user/assistant turns (not tool results)
    # to keep history manageable
    updated_history = []
    for msg in messages[1:]:   # skip system message
        if msg.get("role") in ("user", "assistant"):
            updated_history.append({
                "role":    msg["role"],
                "content": msg.get("content") or "",
            })

    return {
        "answer":     answer,
        "history":    updated_history,
        "tools_used": tools_used,
    }