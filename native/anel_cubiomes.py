#!/usr/bin/env python3
"""Decide o anel SO com o cubiomes (sem gerar o mundo) e compara com o score medido nos mundos reais.

  python native/anel_cubiomes.py              # todos os mundos de worlds/
"""
import csv, json, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import terrain, shcubiomes
from seed_hunter import safe_id

import triagem


def estimate_grid(seed, center_x, center_z):
    H, B, _, _ = triagem.estimate_grid(seed, center_x, center_z)
    return H, B


def ranks(v):
    order = sorted(range(len(v)), key=lambda i: v[i])
    r = [0] * len(v)
    for pos, i in enumerate(order):
        r[i] = pos
    return r


by_level = {}
with (ROOT / "resultados.csv").open(encoding="utf-8-sig", newline="") as f:
    for r in csv.DictReader(f, delimiter=";"):
        by_level[safe_id(r["seed"])] = r["seed"]

rows = []
for d in sorted((ROOT / "worlds").iterdir()):
    seed = by_level.get(d.name)
    info = json.loads((ROOT / "resultados" / f"{d.name}.json").read_text(encoding="utf-8"))
    sp = info.get("spawn") or {"x": 0, "z": 0}
    real = json.loads((ROOT / "resultados" / "relevo" / f"{d.name}.json").read_text(encoding="utf-8"))
    t0 = time.time()
    H, B = estimate_grid(seed, sp["x"], sp["z"])
    t_est = time.time() - t0
    t1 = time.time()
    est = terrain.ring_score(H, B) or {"score": 0.0}
    t_ring = time.time() - t1
    rows.append((d.name.replace("seed_", "")[:14], real["score"], est["score"], est.get("neve"), real.get("neve"), t_est, t_ring))
    print(f"{rows[-1][0]:16} real={real['score']:.3f}  so-cubiomes={est['score']:.3f}  neve real/est={real.get('neve')}/{est.get('neve')}"
          f"  [estimar {t_est:.2f}s + anel {t_ring:.1f}s]", flush=True)

r1, r2 = ranks([r[1] for r in rows]), ranks([r[2] for r in rows])
n = len(rows)
d2 = sum((a - b) ** 2 for a, b in zip(r1, r2))
print(f"\ncorrelacao de ranking (Spearman) entre real e so-cubiomes: {1 - 6 * d2 / (n * (n * n - 1)):.3f}  ({n} mundos)")
print("top 5 real:      ", [r[0] for r in sorted(rows, key=lambda r: -r[1])[:5]])
print("top 5 cubiomes:  ", [r[0] for r in sorted(rows, key=lambda r: -r[2])[:5]])
