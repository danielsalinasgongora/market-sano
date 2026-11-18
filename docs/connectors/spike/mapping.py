"""Regla ingenua de mapeo: entre los 10 primeros por relevancia, en stock, cuyo nombre
contenga todas las palabras de la query (sin tildes, prefijo de 5 letras), el de menor PPUM."""

import json
import statistics
import sys
import unicodedata
from collections import defaultdict

d = json.load(open(sys.argv[1], encoding="utf-8"))


def norm(s):
    return unicodedata.normalize("NFKD", s.lower()).encode("ascii", "ignore").decode()


lat = defaultdict(list)
rows = []
for r in d:
    lat[r["store"]].append(r["ms"])
    ps = r["data"].get("products", [])
    toks = [t[:5] for t in norm(r["query"]).split()]
    cands = [
        p
        for p in ps
        if p.get("inStock", True) and p.get("unitPrice") and all(t in norm(p["name"]) for t in toks)
    ]
    best = min(cands, key=lambda p: p["unitPrice"]) if cands else None
    rows.append((r["store"], r["canonical"], len(ps), len(cands), best))

for s, v in lat.items():
    print(
        f"{s}: n={len(v)} mediana={statistics.median(v):.0f} ms p95~{sorted(v)[int(len(v) * 0.95) - 1]} ms max={max(v)} ms"  # noqa: E501
    )
print()
for s, c, n, k, b in rows:
    desc = (
        f"{b['name'][:48]} | ${b['price']} | PPUM {b['unitPrice']}/{b['unit']} | {b.get('sku')}"
        if b
        else "SIN MATCH"
    )
    print(f"{s[:5]} | {c[:22]:22} | {n:2} res, {k:2} cand | {desc}")
