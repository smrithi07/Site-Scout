"""Narrative for a v1 → v2 evaluation diff (docs/DESIGN.md §7). The diff is computed by code
(`services/diff.py`); the model only phrases it. Same chain as the area narrative (cache → Gemini
→ Groq → template, validator on every answer), its own prompt, schema, checks and template.
Bump `llm.diff_prompt_version` whenever SYSTEM changes (it is part of the cache key)."""
import json
import re
from decimal import Decimal

from app.llm.validator import _numbers_in, _sheet_numbers, _traces

SCHEMA = {
    "type": "OBJECT",
    "properties": {"summary": {"type": "STRING"}, "changes": {"type": "ARRAY", "items": {"type": "STRING"}}},
    "required": ["summary", "changes"],
}

SYSTEM = """You explain to a grocery chain's business-development manager in Chennai why a site's evaluation \
changed between two versions. You are given a JSON fact sheet computed by code: the before/after score and \
rating, and each factor change with its cause (data change, config change, factor newly included, \
factor dropped, renormalization), plus new facts and risks from a field survey. Only phrase it.

Rules — an automatic checker rejects any answer that breaks them:
1. Use only facts in the fact sheet. Do not add places, stores, brands or landmarks.
2. Copy numbers exactly as they appear (you may round to a whole number or drop a minus sign when you say \
"down"). Never compute new numbers: no differences, sums, ratios or percentages.
3. Name each change's cause with the words given in the sheet; never assign a cause the sheet doesn't give.
4. Mention ratings only as given in before.rating and after.rating.
5. Plain English, no markdown, no bullet symbols. Each string at most two sentences.

Return JSON with exactly these keys:
- "summary": one or two sentences: the score and rating before and after, and the main reason.
- "changes": 1 to 6 short strings, biggest change first: the factor, its cause, and its points_change; \
then any new risks."""

LABELS = ("strong fit", "weak fit", "needs info")            # "consider" is also a plain English word
CAUSES = {"config change": "config change", "newly included": "factor newly included", "dropped": "factor dropped",
          "renormali": "renormalization"}


def user_message(sheet: dict, feedback: list[str] | None = None) -> str:
    facts = {k: v for k, v in sheet.items() if k != "caveats"}
    text = "Fact sheet:\n" + json.dumps(facts, ensure_ascii=False, separators=(",", ":"))
    if feedback:
        text += ("\n\nYour previous answer was rejected by the checker for these reasons; fix them and answer again:\n- "
                 + "\n- ".join(feedback[:8]))
    return text


def validate(narrative: object, sheet: dict, known_entities: list[str] | None = None) -> list[str]:
    if not isinstance(narrative, dict):
        return ["answer is not a JSON object"]
    errors = []
    if not isinstance(narrative.get("summary"), str) or not narrative["summary"].strip():
        errors.append('"summary" must be a non-empty string')
    ch = narrative.get("changes")
    if not isinstance(ch, list) or not all(isinstance(x, str) for x in ch) or not 1 <= len(ch) <= 6:
        errors.append('"changes" must be a list of 1–6 strings')
    if errors:
        return errors
    strings = [narrative["summary"], *ch]
    if any(len(x) > 500 for x in strings):
        errors.append("a string is longer than 500 characters")
    text = " ".join(strings)
    lowered = text.lower()
    allowed = _sheet_numbers(sheet)
    allowed |= {abs(n) for n in allowed} | {Decimal(0), Decimal(100)}
    bad = sorted({str(n) for n in _numbers_in(text) if not _traces(abs(n), allowed)})
    if bad:
        errors.append(f"numbers not in the fact sheet: {', '.join(bad[:10])}")
    ratings = {(sheet["before"]["rating"] or "").lower(), (sheet["after"]["rating"] or "").lower()}
    wrong = [label for label in LABELS if label in lowered and label not in ratings]
    if wrong:
        errors.append(f"rating label(s) {wrong} are not the before/after ratings")
    given = {c["cause"] for c in sheet["changes"]}
    invented = [phrase for phrase, cause in CAUSES.items() if phrase in lowered and cause not in given]
    if invented:
        errors.append(f"cause(s) not in the fact sheet: {', '.join(invented)}")
    sheet_text = json.dumps(sheet, ensure_ascii=False).lower()
    strays = sorted({e for e in (known_entities or []) if re.search(rf"\b{re.escape(e.lower())}\b", lowered)
                     and e.lower() not in sheet_text})
    if strays:
        errors.append(f"mentions places/stores not in the fact sheet: {', '.join(strays[:10])}")
    return errors


def _f(v) -> str:
    return "n/a" if v is None else (f"{v:.0f}" if float(v).is_integer() else f"{v}")


def template(sheet: dict) -> dict:
    b, a = sheet["before"], sheet["after"]
    why = f" after catchment study #{sheet['study']['study_id']} ({sheet['study']['confidence']} confidence)" if sheet["study"] else ""
    summary = (f"{sheet['property']}: {_f(b['score'])} ({b['rating']}) in v{b['version']} → {_f(a['score'])} "
               f"({a['rating']}) in v{a['version']}{why}.")
    changes = [f"{c['factor']} — {c['cause']}: {c['explanation']} ({'+' if c['points_change'] >= 0 else ''}{_f(c['points_change'])} points)"
               for c in sheet["changes"][:5]]
    changes += [f"New risk: {r}" for r in sheet["new_risks"][:2]]
    caveats = list(sheet["caveats"])
    if sheet["study"] and sheet["study"]["facts_only"]:
        caveats.append("The study's coverage was too low to score; its facts are shown but the estimates were kept.")
    return {"summary": summary, "changes": changes[:6] or ["No factor changed."], "caveats": caveats}


def finish(parsed: dict, fallback: dict) -> dict:
    return {"summary": parsed["summary"], "changes": parsed["changes"], "caveats": fallback["caveats"]}


def spec():
    from app.llm.adapter import NarrativeSpec  # local: adapter imports providers; keep this module light
    return NarrativeSpec(purpose="evaluation_diff", prompt_version_key="diff_prompt_version", system=SYSTEM, schema=SCHEMA,
                         user_message=user_message, validate=validate, template=template, finish=finish)
