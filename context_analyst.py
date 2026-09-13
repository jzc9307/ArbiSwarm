from schemas import Listing, ContextAnalysis
from agents._llm import call_json

SYSTEM_PROMPT = """You are the Context Analyst in an e-commerce arbitrage swarm.
Read a messy, informal seller description and extract:
- true_condition (Mint / Used-Good / Used-Fair / Damaged)
- flaws_found (specific defects mentioned, e.g. "box dented")
- missing_parts (anything the seller says is missing/uncertain)
- red_flags (vague language, "as is no return", inconsistent claims)
- needs_clarification: true if the description is too vague to judge condition confidently
Be skeptical of vague sellers — that itself is a red flag."""


def analyze(listing: Listing) -> ContextAnalysis:
    user_content = f"Title: {listing.title}\nDescription: {listing.description}"
    return call_json(SYSTEM_PROMPT, user_content, ContextAnalysis)
