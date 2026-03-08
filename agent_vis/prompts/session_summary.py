"""Prompt template for bounded plain-text session summaries."""

SESSION_SUMMARY_PROMPT_VERSION = "session-summary-v1"
SESSION_SUMMARY_MAX_CHARS = 480
DEFAULT_SESSION_SUMMARY_WORKERS = 4
DEFAULT_SESSION_SUMMARY_TIMEOUT_SECONDS = 180

_SESSION_SUMMARY_PROMPT = """\
You are summarizing one AI agent session for downstream embeddings and clustering.

Return plain text only. Do not use Markdown, JSON, bullets, or code fences.
Hard limit: {max_chars} characters total.
Prefer dense factual wording over narrative prose.
Include only the most important facts:
- user goal or task
- key tools/actions
- result or current status
- blockers/errors if any
- notable subagent or coordination behavior if relevant
Do not quote large logs. Do not invent details. If something is uncertain, say so briefly.

Session synopsis:
{synopsis_text}
"""


def build_session_summary_prompt(synopsis_text: str, *, max_chars: int) -> str:
    """Build the bounded prompt used for plain-text session summaries."""
    return _SESSION_SUMMARY_PROMPT.format(synopsis_text=synopsis_text, max_chars=max_chars)
