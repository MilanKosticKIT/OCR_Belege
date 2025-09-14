import re
from typing import Optional, Tuple, List

STORE_PATTERNS = [
    (re.compile(r"migros", re.I), ("Migros", "Migros")),
    (re.compile(r"coop", re.I), ("Coop", "Coop")),
    (re.compile(r"aldi", re.I), ("Aldi", "Aldi")),
    (re.compile(r"lidl", re.I), ("Lidl", "Lidl")),
]

# Enhanced patterns:
# - Accepts labels like TOTAL, SUMME, GESAMT(BETRAG), ZU ZAHLEN/BEZAHLEN, ZAHLBETRAG, TOTALBETRAG
# - Allows optional currency tokens CHF/Fr./SFr./EUR/€ before or after the amount
# - Supports thousands separators (apostrophe, space, dot) and comma/dot decimals
AMOUNT_GROUP = r"([0-9]{1,3}(?:[\'\s\.,][0-9]{3})*[.,][0-9]{2}|[0-9]+[.,][0-9]{2})"
CURRENCY = r"(?:CHF|Fr\.?|SFr\.?|EUR|€)"
LABEL = r"(?:TOTAL|SUMME|GESAMT(?:BETRAG)?|TOTALBETRAG|ZU\s*(?:ZAHLEN|BEZAHLEN)|ZAHLBETRAG)"

TOTAL_PATTERNS: List[re.Pattern] = [
    # Label then amount, maybe currency in between
    re.compile(rf"{LABEL}\s*[:=]?\s*(?:{CURRENCY}\s*)?{AMOUNT_GROUP}", re.I),
    # Label then amount then currency
    re.compile(rf"{LABEL}\s*[:=]?\s*{AMOUNT_GROUP}\s*(?:{CURRENCY})", re.I),
    # Standalone line with currency then amount (multiline)
    re.compile(rf"^(?:{CURRENCY})\s*{AMOUNT_GROUP}\s*$", re.I | re.M),
    # Standalone line with amount then currency (multiline)
    re.compile(rf"^{AMOUNT_GROUP}\s*(?:{CURRENCY})\s*$", re.I | re.M),
]


def _normalize_amount_to_float(s: str) -> Optional[float]:
    """
    Normalize strings like "1'234.56", "1 234,56", "1234,56", "1234.56" to float.
    """
    if not s:
        return None
    s = s.strip()
    # Remove spaces and apostrophes used as thousands separators
    s = s.replace(" ", "").replace("'", "")
    # If both '.' and ',' exist, assume '.' thousands, ',' decimal (common in DE/CH)
    if "." in s and "," in s:
        s = s.replace(".", "")
        s = s.replace(",", ".")
    else:
        # If only comma exists, treat as decimal separator
        if "," in s and "." not in s:
            s = s.replace(",", ".")
        # If only dot exists, keep as is
    try:
        return float(s)
    except ValueError:
        return None


def parse_store_and_total(text: str) -> Tuple[Optional[str], Optional[str], Optional[float]]:
    chain_name = None
    store_name = None
    for pat, (sname, cname) in STORE_PATTERNS:
        if pat.search(text):
            store_name, chain_name = sname, cname
            break

    # Find all candidate totals, take the last occurrence in the document
    candidates: List[Tuple[int, float]] = []
    for pat in TOTAL_PATTERNS:
        for m in pat.finditer(text):
            raw = m.group(1)  # always capture group for amount
            val = _normalize_amount_to_float(raw)
            if val is not None:
                candidates.append((m.start(), val))

    total: Optional[float] = None
    if candidates:
        # pick the last match (highest start position)
        candidates.sort(key=lambda x: x[0])
        total = candidates[-1][1]

    return store_name, chain_name, total