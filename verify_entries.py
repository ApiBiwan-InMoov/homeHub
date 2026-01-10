import re
from typing import Any

def _extract_location_text(ev: dict[str, Any]) -> str:
    val = ev.get("location")
    if isinstance(val, str) and val.strip():
        return val
    if isinstance(val, dict):
        for key in ("displayName", "name", "address", "formatted", "query", "title", "description"):
            v = val.get(key)
            if isinstance(v, str) and v.strip():
                return v
    desc = ev.get("description")
    if isinstance(desc, str) and desc.strip():
        desc = re.sub(r"<[^>]+>", " ", desc)
        return desc
    return ""

def _normalize_addr(q: str) -> str:
    lines = [line.strip() for line in q.splitlines() if line.strip()]
    if len(lines) > 1:
        candidates = [l for l in lines if any(c.isdigit() for c in l)]
        if candidates:
            be_zip_candidates = [l for l in candidates if re.search(r"\b\d{4}\b", l)]
            if be_zip_candidates:
                q = be_zip_candidates[0]
            else:
                q = candidates[-1]
        else:
            q = " ".join(lines)
    q = re.sub(r"^[·\s\-\u2022]+", "", q)
    q = re.sub(r"\s+", " ", q.strip())
    return q

entries = [
    """01
10:00
2h
Sportlink - Parc M-1
Leopold M-1-Parc M-1
· Leopold Avenue Adolphe Dupuich 42 1180 UCCLE
🚗
—""",
    """01
15:00
2h
Sportlink - Rix H-1
Rix H-1-Zaid H-1
· Rixensart Rue du Tilleul 56 1332 GENVAL
🚗
—""",
    """08
10:00
2h
Sportlink - Parc M-1
Racing M-1-Parc M-1
· Racing Avenue des Chênes 125 1180 UCCLE
🚗
—""",
    """08
15:00
2h
Sportlink - Rix H-1
Roeselare H-1-Rix H-1
· Roeselare Hoogstraat 98 8800 ROESELARE
🚗
—""",
    """15
10:00
2h
Sportlink - Parc M-1
Waterloo Ducks M-1-Parc M-1
· Waterloo Ducks Drève d'Argenteuil 23 1410 WATERLOO
🚗
—"""
]

for i, raw in enumerate(entries):
    # Simulate extraction from description if location is empty
    extracted = _extract_location_text({"description": raw})
    normalized = _normalize_addr(extracted)
    print(f"Entry {i+1}:")
    # print(f"  Extracted: {extracted.replace('\n', '\\n')}")
    print(f"  Normalized: {normalized}")
