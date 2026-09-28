"""Checks an LLM narrative against its fact sheet (Core rule 7): every number must trace to the
sheet (rounding a sheet number is fine, inventing one is not), no known place/store outside the
sheet may appear, the rating label must be the sheet's, and the shape must be right."""
import json
import re
from decimal import Decimal, InvalidOperation

NUMBER = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?")
RATING_LABELS = ("strong fit", "moderate fit", "weak fit")
ALWAYS_OK = {Decimal(0), Decimal(100)}  # the 0–100 scale itself ("68/100")


def _numbers_in(text: str) -> list[Decimal]:
    out = []
    for m in NUMBER.findall(text):
        try:
            out.append(Decimal(m.replace(",", "")))
        except InvalidOperation:
            pass
    return out


def _sheet_numbers(value) -> set[Decimal]:
    found: set[Decimal] = set()
    if isinstance(value, bool):
        return found
    if isinstance(value, (int, float)):
        found.add(Decimal(str(value)))
    elif isinstance(value, str):
        found.update(_numbers_in(value))
    elif isinstance(value, dict):
        for v in value.values():
            found |= _sheet_numbers(v)
    elif isinstance(value, list):
        for v in value:
            found |= _sheet_numbers(v)
    return found


def _traces(n: Decimal, allowed: set[Decimal]) -> bool:
    if n in allowed or n in ALWAYS_OK:
        return True
    places = max(-n.as_tuple().exponent, 0)
    quantum = Decimal(1).scaleb(-places)
    return any(v.quantize(quantum) == n for v in allowed if -v.as_tuple().exponent > places)


def validate(narrative: object, sheet: dict, known_entities: list[str] | None = None) -> list[str]:
    errors: list[str] = []
    if not isinstance(narrative, dict):
        return ["answer is not a JSON object"]
    if not isinstance(narrative.get("summary"), str) or not narrative["summary"].strip():
        errors.append('"summary" must be a non-empty string')
    for key, lo, hi in (("why", 1, 6), ("where_to_scout", 0, 6)):
        v = narrative.get(key)
        if not isinstance(v, list) or not all(isinstance(s, str) for s in v) or not lo <= len(v) <= hi:
            errors.append(f'"{key}" must be a list of {lo}–{hi} strings')
    if errors:
        return errors

    strings = [narrative["summary"], *narrative["why"], *narrative["where_to_scout"]]
    if any(len(s) > 500 for s in strings):
        errors.append("a string is longer than 500 characters")
    text = " ".join(strings)
    lowered = text.lower()

    allowed = _sheet_numbers(sheet)
    bad = sorted({str(n) for n in _numbers_in(text) if not _traces(n, allowed)})
    if bad:
        errors.append(f"numbers not in the fact sheet: {', '.join(bad[:10])}")

    rating = (sheet.get("result", {}).get("rating") or "").lower()
    wrong = [label for label in RATING_LABELS if label in lowered and label != rating]
    if wrong:
        errors.append(f"rating label(s) {wrong} do not match the fact sheet ({rating or 'no rating'})")

    sheet_text = json.dumps(sheet, ensure_ascii=False).lower()
    strays = sorted({e for e in (known_entities or [])
                     if re.search(rf"\b{re.escape(e.lower())}\b", lowered) and e.lower() not in sheet_text})
    if strays:
        errors.append(f"mentions places/stores not in the fact sheet: {', '.join(strays[:10])}")
    return errors
