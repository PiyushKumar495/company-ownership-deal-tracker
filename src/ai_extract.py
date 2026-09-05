"""
Extract structured deal fields (company, investors, round type, amount,
valuation, date) from unstructured press-release text.

If ANTHROPIC_API_KEY is set, this calls Claude with a strict JSON-only
prompt. If not, it falls back to a small rule-based extractor so the
pipeline still runs end-to-end for anyone reviewing this on GitHub without
needing to configure an API key.
"""
import json
import os
import re
from typing import Optional

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")

EXTRACTION_SYSTEM_PROMPT = """You extract structured private-market deal data from press-release text.
Respond with ONLY a JSON object (no markdown fences, no commentary) with exactly these keys:
{
  "company": string,
  "lead_investor": string or null,
  "other_investors": array of strings,
  "round_type": string or null,
  "amount_usd": number or null,
  "valuation_usd": number or null,
  "round_date": string in YYYY-MM-DD format or null,
  "stakes": array of {"investor": string, "stake_pct": number}  // only if explicitly stated
}
If a field is not stated in the text, use null (or an empty array). Do not guess numbers that
are not present in the text. Do not invent investors."""


def extract_deal_fields(text: str, use_ai: bool = True) -> dict:
    """Return a dict of structured fields extracted from raw press-release text."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if use_ai and api_key:
        try:
            return _ai_extract(text, api_key)
        except Exception as exc:  # network issues, bad response, etc.
            print(f"[ai_extract] AI extraction failed ({exc}); falling back to rule-based extractor.")
            return _fallback_extract(text)
    return _fallback_extract(text)


def _ai_extract(text: str, api_key: str) -> dict:
    import anthropic  # imported lazily so the fallback path has no hard dependency

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=MODEL,
        max_tokens=500,
        system=EXTRACTION_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": text}],
    )
    raw = "".join(block.text for block in response.content if block.type == "text")
    raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(raw)


def _fallback_extract(text: str) -> dict:
    """Lightweight regex/heuristic extractor used when no API key is configured.

    This intentionally only pulls what it can find with confidence; it leaves
    fields as None rather than guessing, matching the same "don't invent
    numbers" principle as the AI prompt above.
    """
    result = {
        "company": None,
        "lead_investor": None,
        "other_investors": [],
        "round_type": None,
        "amount_usd": None,
        "valuation_usd": None,
        "round_date": None,
        "stakes": [],
    }

    amount_match = re.search(r"\$(\d+(?:\.\d+)?)\s*million", text, re.IGNORECASE)
    if amount_match:
        result["amount_usd"] = float(amount_match.group(1)) * 1_000_000

    valuation_match = re.search(
        r"valu\w*[^.$]*\$(\d+(?:\.\d+)?)\s*million", text, re.IGNORECASE
    )
    if valuation_match:
        result["valuation_usd"] = float(valuation_match.group(1)) * 1_000_000

    round_match = re.search(r"Series\s+[A-E]|Seed round|Seed", text)
    if round_match:
        result["round_type"] = round_match.group(0).strip()

    led_match = re.search(r"led by ([A-Z][A-Za-z&.,' ]+?)(?:,| with| and|\.|$)", text)
    if led_match:
        result["lead_investor"] = led_match.group(1).strip()

    # Company name heuristic: first capitalized multi-word phrase before a
    # common verb. This is intentionally crude -- it's a fallback, not a
    # replacement for the AI extractor.
    company_match = re.search(
        r"^([A-Z][A-Za-z]+(?: [A-Z][A-Za-z]+){0,3})\s+(?:today announced|has raised|has landed|has closed|raised|closed)",
        text.strip(),
    )
    if not company_match:
        company_match = re.search(r"(?:startup|firm|company) ([A-Z][A-Za-z]+)", text)
    if company_match:
        result["company"] = company_match.group(1).strip()

    return result
