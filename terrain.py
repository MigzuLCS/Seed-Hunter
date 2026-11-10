#!/usr/bin/env python3
"""terrain.py - le o relevo e os biomas de um mundo (arquivos de regiao .mca) sem abrir o jogo
e mede se o terreno tem a forma de um anel de montanhas em volta de uma area mais baixa.

So biblioteca padrao. Serve para filtrar seeds ANTES de gastar tempo e disco no BlueMap.

  python terrain.py seed_12345 seed_777      # mede e grava resultados/relevo/<id>.png + .json
"""
import json, math, struct, sys, zlib
from pathlib import Path

BASE = Path(__file__).resolve().parent
MINY = -64                       # altura minima do mundo: os mapas de altura contam a partir dela
HEIGHTMAP = "MOTION_BLOCKING_NO_LEAVES"   # superficie sem copas de arvore
STRIDE = 4                       # 1 amostra a cada 4 blocos (a resolucao dos biomas)
SKIP_KEYS = ("block_states", "structures", "block_entities", "block_ticks", "fluid_ticks",
             "PostProcessing", "entities")   # nao precisamos disso: pular acelera muito
_FIXED = {1: 1, 2: 2, 3: 4, 4: 8, 5: 4, 6: 8}


def parse_nbt(b, skip=()):
    """NBT -> dict/list/int/str. Arrays de long/int viram listas; chaves em `skip` viram None sem ler o conteudo."""
    pos = 0

    def rd(fmt):
        nonlocal pos
        v = struct.unpack_from(">" + fmt, b, pos)[0]
        pos += struct.calcsize(fmt)
        return v

    def rstr():
        nonlocal pos
        n = rd("H")
        s = b[pos:pos + n].decode("utf-8", "replace")
        pos += n
        return s

    def skip_payload(t):
        nonlocal pos
        if t in _FIXED:
            pos += _FIXED[t]
        elif t == 7:
            n = rd("i"); pos += n          # (nao usar `pos += rd(..)`: o lado esquerdo e lido antes de rd avancar)
        elif t == 8:
            n = rd("H"); pos += n
        elif t == 9:
            it = rd("b"); n = rd("i")
            if it in _FIXED:
                pos += n * _FIXED[it]
            else:
                for _ in range(n):
                    skip_payload(it)
        elif t == 10:
            while True:
                tt = rd("b")
                if tt == 0:
                    return
                n = rd("H"); pos += n
                skip_payload(tt)
        elif t == 11:
            n = rd("i"); pos += 4 * n
        elif t == 12:
            n = rd("i"); pos += 8 * n
        else:
            raise ValueError(f"tag NBT desconhecida: {t}")

    def payload(t):
        nonlocal pos
        if t == 1: return rd("b")
        if t == 2: return rd("h")
        if t == 3: return rd("i")
        if t == 4: return rd("q")
        if t == 5: return rd("f")
        if t == 6: return rd("d")
        if t == 7:
            n = rd("i"); v = b[pos:pos + n]; pos += n; return v
        if t == 8: return rstr()
        if t == 9:
            it = rd("b"); n = rd("i")
            return [payload(it) for _ in range(n)]
        if t == 10:
            d = {}
            while True:
                tt = rd("b")
                if tt == 0:
                    return d
                k = rstr()
                if k in skip:
                    skip_payload(tt); d[k] = None
                else:
                    d[k] = payload(tt)
        if t == 11:
            n = rd("i"); v = list(struct.unpack_from(">%di" % n, b, pos)); pos += 4 * n; return v
        if t == 12:
            n = rd("i"); v = list(struct.unpack_from(">%dq" % n, b, pos)); pos += 8 * n; return v
        raise ValueError(f"tag NBT desconhecida: {t}")

    t = rd("b")
    rstr()
    return payload(t)


def iter_chunks(region_file, skip=()):
    """Gera (chunk_x, chunk_z, nbt) de um .mca (coordenadas de chunk absolutas)."""
    data = Path(region_file).read_bytes()
    parts = Path(region_file).stem.split(".")          # r.<x>.<z>
    rx, rz = int(parts[1]), int(parts[2])
    for i in range(1024):
        entry = struct.unpack_from(">I", data, i * 4)[0]
        off, cnt = entry >> 8, entry & 0xFF
        if not off or not cnt:
            continue
        length, comp = struct.unpack_from(">IB", data, off * 4096)
        raw = data[off * 4096 + 5: off * 4096 + 4 + length]
        if comp == 2:
            raw = zlib.decompress(raw)
        elif comp == 1:
            import gzip
            raw = gzip.decompress(raw)
        else:
            raise ValueError(f"compressao de regiao nao suportada: {comp}")
        yield rx * 32 + (i % 32), rz * 32 + (i // 32), parse_nbt(raw, skip)


def _biome_at(sections, y, lx, lz):
    sec = sections.get(y >> 4)
    if sec is None:
        return "minecraft:plains"
    pal, data = sec["biomes"]["palette"], sec["biomes"].get("data")
    if len(pal) == 1 or not data:
        return pal[0]
    bits = max(1, (len(pal) - 1).bit_length())
    per = 64 // bits
    idx = ((y & 15) >> 2) * 16 + (lz // 4) * 4 + (lx // 4)
    return pal[(data[idx // per] >> ((idx % per) * bits)) & ((1 << bits) - 1)]


def sample_world(world_dir):
    """Le so os chunks `full`. Devolve {(gx, gz): (altura, bioma)} com 1 celula a cada STRIDE blocos
    (gx = x // STRIDE). A altura e o topo da superficie, sem copas de arvore."""
    region_dir = Path(world_dir) / "dimensions" / "minecraft" / "overworld" / "region"
    cells = {}
    per_chunk = 16 // STRIDE
    for mca in sorted(region_dir.glob("r.*.mca")):
        for cx, cz, nbt in iter_chunks(mca, SKIP_KEYS):
            if nbt.get("Status") != "minecraft:full":
                continue
            hms = nbt["Heightmaps"]
            hm = hms.get(HEIGHTMAP) or hms["WORLD_SURFACE"]
            secs = {s["Y"]: s for s in nbt["sections"]}
            for lz in range(0, 16, STRIDE):
                for lx in range(0, 16, STRIDE):
                    i = (lz + 2) * 16 + (lx + 2)
                    v = (hm[i // 7] >> ((i % 7) * 9)) & 511
                    y = v + MINY - 1
                    cells[(cx * per_chunk + lx // STRIDE, cz * per_chunk + lz // STRIDE)] = (y, _biome_at(secs, y, lx, lz))
    return cells


def to_grid(cells):
    """Matriz H[z][x] (None onde nao ha chunk full), B[z][x] biomas e o deslocamento (gx0, gz0)."""
    gx0 = min(k[0] for k in cells); gx1 = max(k[0] for k in cells)
    gz0 = min(k[1] for k in cells); gz1 = max(k[1] for k in cells)
    W, Hh = gx1 - gx0 + 1, gz1 - gz0 + 1
    H = [[None] * W for _ in range(Hh)]
    B = [[None] * W for _ in range(Hh)]
    for (gx, gz), (y, b) in cells.items():
        H[gz - gz0][gx - gx0] = y
        B[gz - gz0][gx - gx0] = b
    return H, B, gx0, gz0


SNOWY = ("frozen_peaks", "jagged_peaks", "snowy_slopes", "grove", "snowy_taiga", "snowy_plains", "ice_spikes",
         "snowy_beach", "frozen_river", "frozen_ocean")


# Tipos de alvo: "anel" = interior em terra (>= 64) e desnivel de ~60 blocos ja pontua cheio; "bacia" = aceita interior
# abaixo do nivel do mar (lago de cratera). A altura estimada do cubiomes ignora a agua que enche a bacia: ao prever
# uma bacia, triagem.py limita o interior ao nivel do mar (SEA_LEVEL) para o desnivel bater com o mundo real.
TIPOS = {"anel": {"interior_min": 64, "desnivel_ref": 60}, "bacia": {"interior_min": None, "desnivel_ref": 60},
         "cratera": {"interior_min": 64, "desnivel_ref": 80}}


def is_snowy(biome):
    """Bioma de neve? ("grove" tambem casaria com cherry_grove, que nao e neve.)"""
    b = biome or ""
    return "cherry" not in b and any(s in b for s in SNOWY)


def _cherry_near_rim(H, B, cx, cz, rays, rmin):
    """Fracao dos raios em que ha cerejeiral perto da crista (a ate 12 blocos de altura abaixo do ponto mais alto)."""
    hit = 0
    for ray in rays:
        cells = [(H[cz + dz][cx + dx], B[cz + dz][cx + dx]) for dx, dz in ray[rmin:]]
        top = max(h for h, _ in cells)
        hit += any(h >= top - 12 and "cherry" in (b or "") for h, b in cells)
    return hit / len(rays)


def ring_score(H, B, angles=24, rmin=10, rmax=45, step=3, interior_min=64, desnivel_ref=60, raio_min=0):
    """Procura o melhor centro para um anel: area interna mais baixa e uma crista alta em volta, em todas as direcoes.
    Raios em celulas (STRIDE blocos). `raio_min`: raio medio minimo do anel em blocos (descarta aneis pequenos). `interior_min`: altura media minima do interior (64 = so terra; None aceita
    bacias abaixo do nivel do mar, como um lago de cratera). Devolve o dict da melhor hipotese (ou None)."""
    rows, cols = len(H), len(H[0])
    rays = []
    for k in range(angles):
        a = 2 * math.pi * k / angles
        rays.append([(round(r * math.cos(a)), round(r * math.sin(a))) for r in range(rmax + 1)])
    best = None
    for cz in range(rmax, rows - rmax, step):
        for cx in range(rmax, cols - rmax, step):
            inner, rims, dists, rimb, ok = [], [], [], [], True
            for ray in rays:
                top, topr, topb = -999, 0, None
                for r, (dx, dz) in enumerate(ray):
                    h = H[cz + dz][cx + dx]
                    if h is None:
                        ok = False
                        break
                    if r < rmin:
                        inner.append(h)
                    elif h > top:
                        top, topr, topb = h, r, B[cz + dz][cx + dx]
                if not ok:
                    break
                rims.append(top); dists.append(topr); rimb.append(topb)
            if not ok:
                continue
            inside = sum(inner) / len(inner)
            if interior_min is not None and inside < interior_min:   # padrao: interior precisa ser terra, nao mar
                continue
            deltas = [t - inside for t in rims]
            dmean = sum(deltas) / len(deltas)
            frac = sum(d >= 20 for d in deltas) / len(deltas)
            mr = sum(dists) / len(dists)
            if mr * STRIDE < raio_min:
                continue
            round_ = max(0.0, 1 - (math.sqrt(sum((d - mr) ** 2 for d in dists) / len(dists)) / mr))
            score = frac * min(1.0, dmean / desnivel_ref) * round_
            if best is None or score > best["score"]:
                snow = sum(is_snowy(b) for b in rimb) / len(rimb)
                cherry = _cherry_near_rim(H, B, cx, cz, rays, rmin)
                best = {"score": round(score, 3), "cx": cx, "cz": cz, "anel": round(frac, 2), "desnivel": round(dmean),
                        "minimo": round(min(deltas)), "redondeza": round(round_, 2), "raio": round(mr * STRIDE),
                        "interior_y": round(inside), "neve": round(snow, 2), "cereja": round(cherry, 2)}
    return best


MOUNTAIN_BIOMES = ("frozen_peaks", "jagged_peaks", "stony_peaks", "snowy_slopes", "grove")


def biome_ring_score(B, angles=24, rmin=6, rmax=45, step=3, mountains=MOUNTAIN_BIOMES):
    """Anel decidido SO pelo mapa de biomas (sem alturas): um centro que nao e montanha, cercado em quase
    todas as direcoes por biomas de montanha a uma distancia parecida. Como o terreno da 1.18+ e gerado pelos
    mesmos ruidos que escolhem o bioma, picos nevados indicam terreno alto. Da para calcular sem gerar chunks."""
    rows, cols = len(B), len(B[0])
    is_m = [[bool(b) and any(m in b for m in mountains) for b in row] for row in B]
    rays = []
    for k in range(angles):
        a = 2 * math.pi * k / angles
        rays.append([(round(r * math.cos(a)), round(r * math.sin(a))) for r in range(rmax + 1)])
    best = None
    for cz in range(rmax, rows - rmax, step):
        for cx in range(rmax, cols - rmax, step):
            if is_m[cz][cx]:
                continue
            dists, ok = [], True
            for ray in rays:
                hit = None
                for r, (dx, dz) in enumerate(ray):
                    if B[cz + dz][cx + dx] is None:
                        ok = False
                        break
                    if is_m[cz + dz][cx + dx]:
                        hit = r
                        break
                if not ok:
                    break
                if hit is not None and hit >= rmin:
                    dists.append(hit)
                elif hit is not None:        # montanha colada no centro: nao e um interior
                    dists.append(None)
            if not ok:
                continue
            valid = [d for d in dists if d is not None]
            frac = len(valid) / angles
            if len(valid) < 3:
                continue
            mr = sum(valid) / len(valid)
            round_ = max(0.0, 1 - math.sqrt(sum((d - mr) ** 2 for d in valid) / len(valid)) / mr)
            score = frac * round_
            if best is None or score > best["score"]:
                best = {"score": round(score, 3), "cx": cx, "cz": cz, "anel": round(frac, 2),
                        "redondeza": round(round_, 2), "raio": round(mr * STRIDE)}
    return best


def _biome_color(b, h):
    n = (b or "").replace("minecraft:", "")
    if h < 63 or "ocean" in n or n in ("river", "frozen_river"):
        d = max(0.35, 1 - (63 - h) / 60) if h < 63 else 0.9
        return (int(35 * d), int(90 * d), int(170 * d))
    if any(s in n for s in ("peaks", "slopes", "ice_spikes", "frozen", "snowy_plains", "snowy_taiga")):
        return (240, 244, 250)
    if n == "grove": return (205, 225, 235)
    if "cherry" in n: return (232, 160, 200)
    if "badlands" in n: return (200, 110, 60)
    if "desert" in n or "beach" in n: return (225, 205, 140)
    if "savanna" in n: return (190, 170, 80)
    if any(s in n for s in ("stony", "windswept", "gravelly")): return (130, 135, 140)
    if any(s in n for s in ("jungle", "bamboo")): return (30, 120, 40)
    if any(s in n for s in ("swamp", "mangrove")): return (90, 110, 50)
    if "dark_forest" in n: return (40, 80, 35)
    if "taiga" in n: return (60, 110, 80)
    if "meadow" in n: return (130, 190, 90)
    if "mushroom" in n: return (150, 110, 150)
    return (80, 150, 60)


def relief_png(H, B, path, mark=None, scale=3):
    """PNG vista de cima: cor por bioma + sombreamento do relevo (luz noroeste). `mark` = (gx, gz) da celula a marcar."""
    rows, cols = len(H), len(H[0])
    px = []
    for z in range(rows):
        row = []
        for x in range(cols):
            h = H[z][x]
            if h is None:
                row.append((18, 22, 28)); continue
            r, g, b = _biome_color(B[z][x], h)
            hn = H[z - 1][x - 1] if z > 0 and x > 0 and H[z - 1][x - 1] is not None else h
            shade = 1 + max(-0.45, min(0.45, (h - hn) / 14))
            k = shade * (0.8 + min(0.35, max(0, (h - 63)) / 400))
            row.append((min(255, int(r * k)), min(255, int(g * k)), min(255, int(b * k))))
        px.append(row)
    if mark:
        mx, mz = mark
        for dz in range(-2, 3):
            for dx in range(-2, 3):
                if 0 <= mz + dz < rows and 0 <= mx + dx < cols and max(abs(dx), abs(dz)) >= 1:
                    px[mz + dz][mx + dx] = (255, 40, 40)
    raw = bytearray()
    for row in px:
        line = bytearray()
        for p in row:
            line += bytes(p) * scale
        raw += (b"\x00" + bytes(line)) * scale
    w, h = cols * scale, rows * scale
    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) \
        + chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + chunk(b"IEND", b"")
    Path(path).write_bytes(png)


def analyze_world(level, out_dir=None, rmax=45, tipo="anel", raio_min=0):
    """Mede um mundo de worlds/<level>. Grava resultados/relevo/<level>.png e .json e devolve as metricas.
    rmax = maior anel procurado, em celulas de 4 blocos. O padrao (45 = 180 blocos) varre a area toda; um mundo
    gerado em volta do centro de um anel grande pede um rmax maior (a busca fica perto do meio da area)."""
    out = Path(out_dir) if out_dir else BASE / "resultados" / "relevo"
    out.mkdir(parents=True, exist_ok=True)
    cells = sample_world(BASE / "worlds" / level)
    H, B, gx0, gz0 = to_grid(cells)
    best = ring_score(H, B, rmax=rmax, raio_min=raio_min, **TIPOS[tipo]) or {"score": 0.0}
    mark = (best["cx"], best["cz"]) if "cx" in best else None
    if mark:
        best["centro"] = {"x": (gx0 + best["cx"]) * STRIDE, "z": (gz0 + best["cz"]) * STRIDE}
        counts = {}
        for z in range(best["cz"] - 8, best["cz"] + 9):
            for x in range(best["cx"] - 8, best["cx"] + 9):
                bb = (B[z][x] or "").replace("minecraft:", "")
                counts[bb] = counts.get(bb, 0) + 1
        best["interior_biomas"] = [k for k, _ in sorted(counts.items(), key=lambda kv: -kv[1])[:3]]
    relief_png(H, B, out / f"{level}.png", mark)
    (out / f"{level}.json").write_text(json.dumps(best, indent=1, ensure_ascii=False), encoding="utf-8")
    return best


if __name__ == "__main__":
    for lvl in sys.argv[1:]:
        print(lvl, json.dumps(analyze_world(lvl), ensure_ascii=False), flush=True)
