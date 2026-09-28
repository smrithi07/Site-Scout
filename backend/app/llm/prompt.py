"""Prompt for the area narrative. The model phrases the fact sheet; it never calculates. Caveats
are not requested — code appends them, so a model can't drop one. Bump `llm.prompt_version` in
config whenever this text changes (it's part of the cache key)."""
import json

OUTPUT_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "summary": {"type": "STRING"},
        "why": {"type": "ARRAY", "items": {"type": "STRING"}},
        "where_to_scout": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["summary", "why", "where_to_scout"],
}

SYSTEM = """You write the narrative for an Area Fitness Report used by a grocery chain's business-development \
manager in Chennai. You are given a JSON fact sheet computed by code. Your only job is to phrase it clearly.

Rules — an automatic checker rejects any answer that breaks them:
1. Use only facts in the fact sheet. Do not add places, stores, brands, landmarks or wards that are not in it.
2. Copy numbers exactly as they appear in the fact sheet (you may round a number to a whole number). Never \
compute new numbers: no differences, sums, averages, ratios or percentages.
3. If result.status is not "scored", say there is no rating and give result.reason_no_rating; do not invent a score.
4. Mention the rating label only as given in result.rating.
5. Plain English, no markdown, no bullet symbols. Each string at most two sentences.

Return JSON with exactly these keys:
- "summary": one or two sentences: the verdict (score, rating, confidence) and the main reason.
- "why": 2 to 5 short strings: the strongest and weakest factors, with their normalized_0_100 values, and \
what each factor's note says about it.
- "where_to_scout": one string per hotspot, in rank order: its ward, score and strengths. Empty list if there \
are no hotspots."""


def user_message(sheet: dict, feedback: list[str] | None = None) -> str:
    facts = {k: v for k, v in sheet.items() if k != "caveats"}  # caveats are code-owned
    text = "Fact sheet:\n" + json.dumps(facts, ensure_ascii=False, separators=(",", ":"))
    if feedback:
        text += ("\n\nYour previous answer was rejected by the checker for these reasons; fix them and "
                 "answer again:\n- " + "\n- ".join(feedback[:8]))
    return text
