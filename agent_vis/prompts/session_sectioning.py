"""Prompt template for AI-driven session section boundary detection."""

SESSION_SECTIONING_PROMPT_VERSION = "session-sectioning-v1"

_SESSION_SECTIONING_PROMPT = """\
You are analyzing one AI agent session transcript and must partition it
into semantically independent sections.

Return a single JSON object only. Do not use Markdown or code fences.

Schema:
{{
  "sections": [
    {{
      "title": string,
      "start_message_ordinal": integer,
      "end_message_ordinal": integer
    }}
  ]
}}

Requirements:
- Group the transcript into relatively independent dialogue events, not one section per user turn.
- Prefer coherent sections, but do not over-merge clearly separate user requests or restarts.
- Start a new section only when the user clearly changes goal, requests a
  different deliverable, restarts the task, or interrupts and begins a
  distinct thread.
- The first section must start exactly at `first_user_ordinal`.
- The last section must end exactly at `last_coverable_ordinal`.
- Every section must start on a user message ordinal.
- Every section must end on a non-user message ordinal.
- Sections must be ordered, non-overlapping, and contiguous across the covered transcript span.
- Cover every message from `first_user_ordinal` through `last_coverable_ordinal` exactly once.
- Ignore any leading prelude before the first user message.
- Ignore any trailing unmatched user interruption if no non-user reply follows it.
- Do not skip command-style, metadata-like, interrupted, or setup user
  messages if they are inside the covered span; they still belong to
  some section.
- If message 1 in the covered span is a user message, section 1 must
  start at that message even if it looks like setup, command output, or
  control text.
- Titles should be short, factual, and specific to the event.
- Do not invent hidden steps or outcomes.

Session context:
{session_text}
"""


def build_session_sectioning_prompt(session_text: str) -> str:
    """Build the prompt used for AI-driven session section partitioning."""
    return _SESSION_SECTIONING_PROMPT.format(session_text=session_text)
