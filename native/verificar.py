#!/usr/bin/env python3
"""Verifica se os biomas do cubiomes (26.3) batem com os mundos REAIS gerados pelo Paper.

Para cada mundo em worlds/ le o bioma de cada celula 4x4 na superficie (terrain.sample_world) e pergunta ao
cubiomes o bioma da mesma celula e altura. Imprime a concordancia por mundo e os pares que mais divergem.

  python native/verificar.py            # todos os mundos
  python native/verificar.py 12345 777  # so essas seeds
"""
import csv, sys, time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import terrain
import shcubiomes
from seed_hunter import safe_id

by_level = {}
with (ROOT / "resultados.csv").open(encoding="utf-8-sig", newline="") as f:
    for r in csv.DictReader(f, delimiter=";"):
        by_level[safe_id(r["seed"])] = r["seed"]

wanted = {safe_id(s) for s in sys.argv[1:]}
tot = ok = 0
confusion = Counter()
rows = []
for d in sorted((ROOT / "worlds").iterdir()):
    if wanted and d.name not in wanted:
        continue
    seed = by_level.get(d.name)
    if seed is None:
        continue
    t0 = time.time()
    cells = terrain.sample_world(d)                       # {(gx, gz): (altura, bioma)}
    t_read = time.time() - t0
    w = shcubiomes.World(seed)
    t1 = time.time()
    n = m = 0
    for (gx, gz), (y, real) in cells.items():
        got = w.name(w.biome_at(gx, y >> 2, gz, scale=4)) if True else None
        real = real.replace("minecraft:", "")
        n += 1
        if got == real:
            m += 1
        else:
            confusion[(real, got)] += 1
    t_cub = time.time() - t1
    rows.append((d.name.replace("seed_", "")[:16], n, m, 100 * m / n, t_read, t_cub))
    tot += n; ok += m
    print(f"{rows[-1][0]:18} {n:6d} celulas  {rows[-1][3]:6.2f}% iguais  (ler mundo {t_read:.1f}s, cubiomes {t_cub:.2f}s)", flush=True)

print(f"\nTOTAL: {ok}/{tot} = {100 * ok / tot:.2f}% das celulas iguais")
print("divergencias mais comuns (real -> cubiomes):")
for (real, got), c in confusion.most_common(12):
    print(f"  {c:6d}  {real}  ->  {got}")
