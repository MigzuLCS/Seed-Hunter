#!/usr/bin/env python3
"""Compara a altura aproximada do cubiomes (mapApproxHeight) com a altura REAL dos mundos gerados.
Calibra por regressao linear (a altura do cubiomes e relativa) e mostra correlacao e erro."""
import csv, math, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import terrain, shcubiomes
from seed_hunter import safe_id

by_level = {}
with (ROOT / "resultados.csv").open(encoding="utf-8-sig", newline="") as f:
    for r in csv.DictReader(f, delimiter=";"):
        by_level[safe_id(r["seed"])] = r["seed"]

wanted = {safe_id(s) for s in sys.argv[1:]}
allx, ally = [], []
for d in sorted((ROOT / "worlds").iterdir()):
    if wanted and d.name not in wanted:
        continue
    seed = by_level.get(d.name)
    cells = terrain.sample_world(d)
    H, B, gx0, gz0 = terrain.to_grid(cells)
    w = shcubiomes.World(seed)
    t0 = time.time()
    ys, _ = w.surface(gx0, gz0, len(H[0]), len(H))
    t = time.time() - t0
    xs, rs = [], []
    for z in range(len(H)):
        for x in range(len(H[0])):
            if H[z][x] is not None:
                xs.append(ys[z][x]); rs.append(H[z][x])
    n = len(xs); mx = sum(xs) / n; mr = sum(rs) / n
    sxx = sum((a - mx) ** 2 for a in xs); srr = sum((b - mr) ** 2 for b in rs)
    sxr = sum((a - mx) * (b - mr) for a, b in zip(xs, rs))
    corr = sxr / math.sqrt(sxx * srr)
    slope = sxr / sxx; icpt = mr - slope * mx
    err = sum(abs(slope * a + icpt - b) for a, b in zip(xs, rs)) / n
    # no terreno elevado (>= 90) o erro importa mais para o anel
    hi = [(slope * a + icpt, b) for a, b in zip(xs, rs) if b >= 90]
    err_hi = sum(abs(a - b) for a, b in hi) / len(hi) if hi else float("nan")
    print(f"{d.name.replace('seed_', '')[:16]:18} r={corr:.3f}  y_real ~ {slope:.2f}*x + {icpt:.1f}  erro medio {err:.1f} blocos"
          f"  (terreno >=90: {err_hi:.1f})  [{t:.2f}s para {n} celulas]", flush=True)
    allx += xs; ally += rs

n = len(allx); mx = sum(allx) / n; mr = sum(ally) / n
sxr = sum((a - mx) * (b - mr) for a, b in zip(allx, ally)); sxx = sum((a - mx) ** 2 for a in allx); srr = sum((b - mr) ** 2 for b in ally)
print(f"\nGERAL: r={sxr / math.sqrt(sxx * srr):.3f}  y_real ~ {sxr / sxx:.2f}*x + {mr - sxr / sxx * mx:.1f}  ({n} celulas)")
