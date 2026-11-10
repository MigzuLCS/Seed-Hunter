"""triagem.py - etapa 0 do funil: acha seeds com cara de anel de montanhas SEM gerar o mundo.

Usa o cubiomes (shcubiomes.py): biomas e uma estimativa de altura direto da seed, ~0,7 s por seed. Medido contra mundos
reais do Paper (native/verificar.py, native/altura.py, native/anel_cubiomes.py): 99,95% dos biomas iguais, altura com
correlacao 0,96 e ranking de anel com correlacao 0,9 em relacao ao score do mundo gerado. E uma peneira: o analisador
de relevo (terrain.py) e o juiz de imagem continuam decidindo depois.
"""
import random
import time
from functools import partial
from concurrent.futures import ProcessPoolExecutor

import shcubiomes
import terrain

CAL_A, CAL_B = 0.80, 20.2         # altura_real ~ A * altura_cubiomes + B (regressao em native/altura.py)
SEA_LEVEL = 62                    # bacias abaixo disso viram lago: a superficie e a agua
CHUNKS = 45                       # janela avaliada: 45 chunks de raio = 720 blocos em volta de (0,0)
RMAX = 75                         # maior anel procurado, em celulas de 4 blocos = 300 blocos de raio
TRIAGEM_MIN = 0.4                 # o score so-cubiomes fica uns 30% abaixo do medido no mundo (0,5): 0,4 equivale

# Raio de geracao adaptativo: o Chunky gera so o anel mais uma margem, em vez de um raio fixo.
MARGEM = 160                      # blocos alem da crista do anel
RAIO_MIN, RAIO_MAX = 320, 960     # limites do raio gerado (blocos)


def adaptive_radius(ring_radius, default=None):
    """Raio (blocos) a gerar para um anel de raio `ring_radius`: anel + margem, entre RAIO_MIN e RAIO_MAX.
    Sem anel conhecido (None) devolve `default`."""
    if ring_radius is None:
        return default
    return max(RAIO_MIN, min(RAIO_MAX, int(ring_radius) + MARGEM))


def estimate_grid(seed, center_x=0, center_z=0, chunks=CHUNKS):
    """Grade de alturas e biomas estimados em volta de (center_x, center_z), no formato de terrain.to_grid.
    Devolve (H, B, gx0, gz0): gx0/gz0 = canto da grade em celulas de 4 blocos."""
    w = shcubiomes.World(seed)
    gx0, gz0 = ((center_x >> 4) - chunks) * 4, ((center_z >> 4) - chunks) * 4
    n = (2 * chunks + 1) * 4
    ys, _ = w.surface(gx0, gz0, n, n)
    H = [[int(CAL_A * v + CAL_B) for v in row] for row in ys]
    B = [[w.name(w.biome_at(gx0 + x, H[z][x] >> 2, gz0 + z, scale=4)) for x in range(n)] for z in range(n)]
    return H, B, gx0, gz0


def score_seed(seed, center_x=0, center_z=0, tipo="anel"):
    """Score de anel/bacia (0-1) de uma seed e o centro em blocos. Roda em processo separado (precisa ser top-level)."""
    H, B, gx0, gz0 = estimate_grid(seed, center_x, center_z)
    if tipo == "bacia":
        H = [[max(h, SEA_LEVEL) for h in row] for row in H]
    best = terrain.ring_score(H, B, rmax=RMAX, **terrain.TIPOS[tipo])
    if not best:
        return {"seed": seed, "score": 0.0}
    return {"seed": seed, "score": best["score"], "neve": best["neve"], "raio": best["raio"],
            "x": (gx0 + best["cx"]) * terrain.STRIDE, "z": (gz0 + best["cz"]) * terrain.STRIDE}


def random_seeds(n, rng=None):
    rng = rng or random.Random()
    return [rng.randint(-2**63, 2**63 - 1) for _ in range(n)]


def screen(pool, keep, min_score=TRIAGEM_MIN, workers=8, seeds=None, log=print, tipo="anel", neve_min=None):
    """neve_min: fracao minima (0-1) da crista em bioma de neve (so o dado medido, nao o palpite do juiz).
    Avalia `pool` seeds aleatorias (ou a lista `seeds`) e devolve as `keep` melhores com score >= min_score,
    da melhor para a pior. Cada item: {seed, score, neve, raio, x, z}."""
    seeds = list(seeds) if seeds is not None else random_seeds(pool)
    t0 = time.time()
    results = []
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for i, r in enumerate(ex.map(partial(score_seed, tipo=tipo), seeds, chunksize=4), 1):
            results.append(r)
            if log and i % 100 == 0:
                log(f"   triagem: {i}/{len(seeds)} ({time.time() - t0:.0f}s)")
    passed = sorted((r for r in results if r["score"] >= min_score and r.get("neve", 0) >= (neve_min or 0)),
                    key=lambda r: -r["score"])
    if log:
        log(f"   triagem: {len(seeds)} seeds em {time.time() - t0:.0f}s ({len(seeds) / max(time.time() - t0, 1e-6):.1f}/s); "
            f"{len(passed)} com score >= {min_score}" + (f" e neve >= {neve_min}" if neve_min else "") + f"; levando as {min(keep, len(passed))} melhores")
    return passed[:keep]
