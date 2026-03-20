"""Prompt template for structured per-section session summaries."""

SESSION_SECTION_SUMMARY_PROMPT_VERSION = "session-section-summary-v1"

_SESSION_SECTION_SUMMARY_PROMPT = """\
You are analyzing one section from an AI agent session.

Return a single JSON object only. Do not use Markdown or code fences.

Schema:
{{
  "title": string,
  "summary": string,
  "goal": string | null,
  "actions": string[],
  "outcome": string | null,
  "tool_patterns": string[],
  "risk_or_blocker": string | null,
  "keywords": string[]
}}

Requirements:
- Keep "summary" under {max_chars} characters.
- Be factual and compact.
- "actions", "tool_patterns", and "keywords" should be short lists.
- Use null for unknown goal/outcome/risk_or_blocker.
- Do not invent missing details.

Section context:
{section_text}
"""


def build_session_section_summary_prompt(section_text: str, *, max_chars: int) -> str:
    """Build the prompt used for section-level structured JSON summaries."""
    return _SESSION_SECTION_SUMMARY_PROMPT.format(section_text=section_text, max_chars=max_chars)
