#!/usr/bin/env python3
"""seed_hunter.py - preview 3D de varias seeds de Minecraft Java.

Paper + Chunky + BlueMap CLI. So biblioteca padrao do Python 3.10+.
Fluxo por seed: sobe o Paper -> filtra com /locate (medido do spawn) ->
pre-gera com Chunky -> renderiza no BlueMap com marcadores nativos.
O resultados.csv e a fonte da verdade para retomar de onde parou.
"""
import argparse, csv, json, os, queue, random, re, shutil, subprocess, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import terrain                      # mede o relevo do mundo (funil antes do BlueMap)
import triagem                      # etapa 0 (cubiomes); a DLL so e carregada quando a triagem roda

# ============================ CONFIGURACAO ============================
BASE = Path(__file__).resolve().parent
SERVER_DIR = BASE / "server"        # paper.jar, eula.txt, plugins/Chunky-*.jar
BLUEMAP_DIR = BASE / "bluemap"      # bluemap-cli.jar + config/ gerada por ele
WORLDS_DIR = BASE / "worlds"        # um mundo por seed
DATA_DIR = BASE / "resultados"      # um JSON por seed (spawn e achados), para a interface
SEEDS_FILE = BASE / "seeds.txt"     # uma seed por linha (# comenta)
RESULTS = BASE / "resultados.csv"

PAPER_JAR = "paper.jar"
BLUEMAP_JAR = "bluemap-cli.jar"
SERVER_RAM = "4G"
BLUEMAP_RAM = "4G"

RADIUS = 480                        # blocos em volta do spawn: 30 chunks
# Regras do filtro: (alvo do /locate, distancia maxima do SPAWN em blocos).
# Alvo = "structure <id>" ou "biome <id>". Lista vazia = sem filtro.
# Por padrao NAO ha regra: o funil de relevo (abaixo) decide, e a vila fica so como informacao. Uma regra de vila
# eliminava bons candidatos (por exemplo mundos nevados). Reative com --rule "structure #minecraft:village=480".
LOCATE_RULES = []

# Funil de relevo: depois do Chunky, terrain.py mede se ha um anel de montanhas em volta de uma area mais baixa.
# Abaixo de ANEL_MIN o mundo e apagado ("sem relevo"); acima vira "candidata" e espera o juiz de imagem.
ANEL_MIN = 0.5
JUIZ_NOTA_MIN = 7                   # nota minima (0-10) do juiz para renderizar no BlueMap
JUIZ_LOTE = 12                      # imagens por lote de juiz (lotes menores erram menos)
# Achados informativos: rodam so depois que a seed passa no filtro e NUNCA reprovam.
# Alimentam a lista de estruturas/biomas, as tags e os marcadores da interface.
INFO_TARGETS = [
    "structure #minecraft:village",
    "structure minecraft:trial_chambers",
    "structure #minecraft:ruined_portal",
    "structure minecraft:pillager_outpost",
    "structure minecraft:ancient_city",
    "structure minecraft:mansion",
    "biome minecraft:cherry_grove",
    "biome minecraft:dappled_forest",
    "biome minecraft:meadow",
    "biome minecraft:jagged_peaks",
    "biome minecraft:mushroom_fields",
    "biome minecraft:ice_spikes",
]
UI_DIR = BASE / "ui"                # fonte da interface (copiada para bluemap/web/ui/)
WEB_UI = BLUEMAP_DIR / "web" / "ui"
CAVE_SUFFIX = "_cav"                # mapa extra com cavernas abertas, gerado sob demanda

# Ajustes do site do BlueMap (config/webapp.conf). O padrao do BlueMap e hires 100;
# 300 cobre boa parte do mapa sem pesar tanto na GPU. Resolucao 0.8 alivia mais.
# O slider continua livre no menu (max 1000 deixa ver os 480 blocos inteiros).
WEBAPP_TWEAKS = {"hires-slider-max": 1000, "hires-slider-default": 300, "resolution-default": 0.8}

# Config do nucleo do BlueMap (config/core.conf). O padrao e 1 thread de render, que deixa a CPU quase
# parada: a renderizacao e a fase mais lenta do pipeline. 8 deixa folga em uma CPU de 12 threads.
CORE_TWEAKS = {"render-thread-count": 8}

MAP_TEMPLATE = """world: "{world}"
dimension: "minecraft:overworld"
name: "Seed {seed}"
sorting: {sorting}
ambient-light: 0.1
remove-caves-below-y: 55
storage: "file"
marker-sets: {{
  pontos: {{
    label: "Pontos"
    toggleable: true
    default-hidden: false
    markers: {{
{markers}
    }}
  }}
}}
"""
# =====================================================================

ANSI = re.compile(r"\x1b\[[0-9;]*m")
LOCATE_OK = re.compile(r"is at \[(-?\d+), (~|-?\d+), (-?\d+)\] \((\d+) blocks away\)")
LOCATE_FAIL = re.compile(r"Could not find|Unknown or incomplete|Invalid|Unknown (structure|biome)")
SPAWN_RE = re.compile(r"world spawn point to (-?\d+), (-?\d+), (-?\d+)")
# Estados que nao se reprocessam; falhas sao tentadas de novo. "candidata" espera o juiz (mundo guardado em worlds/).
STATUS_FINAL = {"ok", "reprovada", "sem relevo", "candidata", "descartada"}


def clean(line):
    return ANSI.sub("", line)


def parse_locate(line):
    """Retorna dict(x, y, z, dist) ou None. y e None quando o jogo imprime '~'."""
    m = LOCATE_OK.search(clean(line))
    if not m:
        return None
    x, y, z, dist = m.groups()
    return {"x": int(x), "y": None if y == "~" else int(y), "z": int(z), "dist": int(dist)}


def parse_spawn(line):
    m = SPAWN_RE.search(clean(line))
    return {"x": int(m[1]), "y": int(m[2]), "z": int(m[3])} if m else None


def safe_id(seed):
    return "seed_" + re.sub(r"[^A-Za-z0-9]", lambda m: "n" if m.group() == "-" else "_", str(seed))


def find_java():
    found = sorted((BASE / "tools").glob("jdk-25*/bin/java.exe")) + sorted((BASE / "tools").glob("jdk-25*/bin/java"))
    return str(found[0]) if found else "java"


JAVA = find_java()


class Server:
    """Servidor Paper sem interface, controlado pelo console."""

    def __init__(self, verbose):
        self.verbose = verbose
        self.lines = queue.Queue()
        self.proc = subprocess.Popen(
            [JAVA, f"-Xms{SERVER_RAM}", f"-Xmx{SERVER_RAM}", "-jar", PAPER_JAR, "--nogui"],
            cwd=SERVER_DIR, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1)
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.proc.stdout:
            self.lines.put(clean(line.rstrip()))

    def send(self, cmd):
        while not self.lines.empty():       # descarta resto de comandos anteriores
            try:
                self.lines.get_nowait()
            except queue.Empty:
                break
        self.proc.stdin.write(cmd + "\n")
        self.proc.stdin.flush()

    def wait_for(self, pattern, timeout):
        rx, end = re.compile(pattern), time.time() + timeout
        while time.time() < end:
            try:
                line = self.lines.get(timeout=1)
            except queue.Empty:
                if self.proc.poll() is not None:
                    return None
                continue
            if self.verbose:
                print("   |", line)
            m = rx.search(line)
            if m:
                return line
        return None

    def stop(self):
        try:
            self.send("stop")
            self.proc.wait(timeout=180)
        except Exception:
            self.proc.kill()
            self.proc.wait()


def set_props(values):
    path = SERVER_DIR / "server.properties"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    found = set()
    for i, line in enumerate(lines):
        key = line.split("=", 1)[0].strip()
        if key in values:
            lines[i] = f"{key}={values[key]}"
            found.add(key)
    lines += [f"{k}={v}" for k, v in values.items() if k not in found]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def patch_conf(text, values):
    """Troca 'chave: valor' nas linhas ativas de um .conf, sem tocar nos comentarios."""
    for key, val in values.items():
        text = re.sub(rf"^(\s*{re.escape(key)}:\s*)\S+", rf"\g<1>{val}", text, flags=re.M)
    return text


def check_setup():
    problems = []
    if not (SERVER_DIR / PAPER_JAR).exists():
        problems.append(f"Falta {SERVER_DIR / PAPER_JAR}")
    if not list((SERVER_DIR / "plugins").glob("[Cc]hunky*.jar")):
        problems.append("Falta o Chunky em server/plugins/")
    eula = SERVER_DIR / "eula.txt"
    if not eula.exists() or "eula=true" not in eula.read_text(encoding="utf-8"):
        problems.append("Rode o servidor uma vez e aceite a EULA em server/eula.txt")
    if not (BLUEMAP_DIR / BLUEMAP_JAR).exists():
        problems.append(f"Falta {BLUEMAP_DIR / BLUEMAP_JAR}")
    core = BLUEMAP_DIR / "config" / "core.conf"
    if not core.exists():
        problems.append("Rode 'java -jar bluemap-cli.jar' uma vez dentro de bluemap/")
    elif not re.search(r"^\s*accept-download:\s*true", core.read_text(encoding="utf-8"), re.M):
        problems.append("Mude accept-download para true em bluemap/config/core.conf")
    if problems:
        for p in problems:
            print("ERRO:", p)
        sys.exit(1)
    core_text = core.read_text(encoding="utf-8")
    patched = patch_conf(core_text, CORE_TWEAKS)
    if patched != core_text:
        core.write_text(patched, encoding="utf-8")
    webapp = BLUEMAP_DIR / "config" / "webapp.conf"
    if webapp.exists():
        old = webapp.read_text(encoding="utf-8")
        new = patch_conf(old, WEBAPP_TWEAKS)
        if new != old:
            webapp.write_text(new, encoding="utf-8")
    maps = BLUEMAP_DIR / "config" / "maps"
    maps.mkdir(parents=True, exist_ok=True)
    for conf in maps.glob("*.conf"):
        if not conf.stem.startswith("seed_"):
            off = BLUEMAP_DIR / "config" / "maps_desativados"
            off.mkdir(exist_ok=True)
            shutil.move(str(conf), str(off / conf.name))
    WORLDS_DIR.mkdir(exist_ok=True)
    DATA_DIR.mkdir(exist_ok=True)


def load_seeds(random_n):
    if random_n > 0:
        return [str(random.randint(-2**63, 2**63 - 1)) for _ in range(random_n)]
    if not SEEDS_FILE.exists():
        print(f"ERRO: crie {SEEDS_FILE.name} (uma seed por linha) ou use --random N")
        sys.exit(1)
    seeds = []
    for line in SEEDS_FILE.read_text(encoding="utf-8-sig").splitlines():   # -sig: editores do Windows gravam BOM
        line = line.split("#")[0].strip()
        if line:
            seeds.append(line)
    return seeds


def done_seeds():
    if not RESULTS.exists():
        return set()
    with RESULTS.open(encoding="utf-8-sig", newline="") as f:
        return {r["seed"] for r in csv.DictReader(f, delimiter=";") if r.get("status") in STATUS_FINAL}


def locate_cmd(spawn, target):
    """/locate medido a partir do spawn (o centro da area que o Chunky gera)."""
    return f"execute in minecraft:overworld positioned {spawn['x']} {spawn['y']} {spawn['z']} run locate {target}"


def locate_one(srv, spawn, target, timeout=180):
    """Roda um /locate e devolve dict(x,y,z,dist), None (nao achou) ou levanta ValueError (saida inesperada)."""
    srv.send(locate_cmd(spawn, target))
    line = srv.wait_for(r"blocks away\)|Could not find|Unknown|Invalid", timeout)
    hit = parse_locate(line) if line else None
    if line and not hit and not LOCATE_FAIL.search(line):
        raise ValueError(line[:80])
    return hit


def chunky_commands(level, center, radius):
    """Comandos do Chunky para gerar um quadrado de `radius` blocos em volta de `center` ({"x":..,"z":..}).
    O centro e o spawn, ou o centro do anel quando a triagem do cubiomes achou um."""
    return (f"chunky world {level}", f"chunky center {center['x']} {center['z']}", "chunky shape square",
            f"chunky radius {radius}", "chunky start")


def generate(seed, level, rules, radius, verbose, info=True, center=None):
    """Retorna (status, achados, spawn). O mundo fica em server/<level>."""
    set_props({"level-seed": seed, "level-name": level, "sync-chunk-writes": "false"})
    srv = Server(verbose)
    try:
        if not srv.wait_for(r"Done \(.*\)! For help", 300):
            return "falha ao iniciar", {}, None
        hits = {}
        # O console roda no spawn real; setworldspawn ~ ~ ~ o repete (sem mudar nada) e imprime as coordenadas.
        srv.send("execute in minecraft:overworld run setworldspawn ~ ~ ~")
        spawn = parse_spawn(srv.wait_for(r"world spawn point", 30) or "")
        if spawn is None:
            return "falha ao ler o spawn", hits, None
        for target, max_dist in rules:
            try:
                hit = locate_one(srv, spawn, target)
            except ValueError as e:
                return f"locate inesperado: {e}", hits, spawn
            hits[target] = hit
            if hit is None or hit["dist"] > max_dist:
                return "reprovada", hits, spawn
        if info:
            for target in INFO_TARGETS:
                if target in hits:
                    continue
                try:
                    hits[target] = locate_one(srv, spawn, target, 60)
                except ValueError:
                    hits[target] = None      # id desconhecido nesta versao: ignora
        for cmd in chunky_commands(level, center or spawn, radius):
            srv.send(cmd)
            time.sleep(1)
        if not srv.wait_for(r"Task finished", 3600):
            return "falha no chunky", hits, spawn
        return "ok", hits, spawn
    finally:
        srv.stop()


def markers_hocon(spawn, hits):
    rows = []
    if spawn:
        rows.append(f'      spawn: {{ type: "poi", position: {{ x: {spawn["x"]}, y: {spawn["y"]}, z: {spawn["z"]} }}, label: "Spawn" }}')
    for i, (target, h) in enumerate(hits.items()):
        if h:
            label = target.split()[-1].replace("#", "").split(":")[-1]
            y = h["y"] if h["y"] is not None else 100
            rows.append(f'      m{i}: {{ type: "poi", position: {{ x: {h["x"]}, y: {y}, z: {h["z"]} }}, label: "{label} ({h["dist"]} blocos)" }}')
    return "\n".join(rows)


def render(seed, level, sorting, spawn, hits):
    world = (WORLDS_DIR / level).resolve().as_posix()
    conf = BLUEMAP_DIR / "config" / "maps" / f"{level}.conf"
    name = str(seed).replace('"', "")
    conf.write_text(MAP_TEMPLATE.format(world=world, seed=name, sorting=sorting,
                                        markers=markers_hocon(spawn, hits)), encoding="utf-8")
    r = subprocess.run([JAVA, f"-Xmx{BLUEMAP_RAM}", "-jar", BLUEMAP_JAR, "-r", "-m", level], cwd=BLUEMAP_DIR)
    return r.returncode == 0


def prepare(seed, rules, radius, verbose, info=True, anel_min=None, center=None, tipo="anel", neve_min=None, cereja_min=None, raio_min=0):
    """Filtra e gera uma seed e deixa o mundo pronto em worlds/<level>. Nao renderiza.
    Devolve (status, achados, spawn, relevo). Sem funil (anel_min None): "ok" = pronta para o BlueMap.
    Com funil: mede o relevo; abaixo de anel_min o mundo e apagado ("sem relevo"), acima vira "candidata"
    (mundo guardado, esperando o juiz). Qualquer outro status nunca chega ao BlueMap."""
    level = safe_id(seed)
    shutil.rmtree(SERVER_DIR / level, ignore_errors=True)      # restos de uma rodada interrompida
    shutil.rmtree(WORLDS_DIR / level, ignore_errors=True)
    status, hits, spawn = generate(seed, level, rules, radius, verbose, info, center)
    src = SERVER_DIR / level
    if status == "ok" and not src.exists():
        status = "mundo nao encontrado"
    if status != "ok":
        shutil.rmtree(src, ignore_errors=True)
        return status, hits, spawn, None
    try:
        shutil.move(str(src), str(WORLDS_DIR / level))
    except OSError as e:
        return f"falha ao mover mundo: {e}", hits, spawn, None
    if anel_min is None:
        return "ok", hits, spawn, None
    # mundo gerado em volta do centro de um anel: procura aneis maiores (a busca fica perto do meio da area);
    # sem centro (spawn), mantem o padrao, que varre a area toda
    rmax = max(45, min(100, radius // terrain.STRIDE - 8)) if center else 45
    try:
        relevo = terrain.analyze_world(level, rmax=rmax, tipo=tipo, raio_min=raio_min)
    except Exception as e:                                     # mundo estranho: guarda para investigar
        return f"falha na analise: {e}", hits, spawn, None
    if relevo["score"] < anel_min or (neve_min and relevo.get("neve", 0) < neve_min)             or (cereja_min and relevo.get("cereja", 0) < cereja_min):
        shutil.rmtree(WORLDS_DIR / level, ignore_errors=True)
        return "sem relevo", hits, spawn, relevo
    return "candidata", hits, spawn, relevo


def save_seed(seed, status, hits, spawn, mins, radius, centro=None, triagem=None):
    """Um JSON por seed (inclusive reprovadas): a interface le tudo daqui via index.json.
    centro = centro da area gerada (o spawn, ou o centro do anel quando a triagem do cubiomes achou um);
    triagem = resultado da etapa 0 (score so-cubiomes, centro e raio do anel estimados)."""
    level = safe_id(seed)
    data = {"seed": seed, "id": level, "status": status, "spawn": spawn, "centro": centro or spawn, "achados": hits,
            "triagem": triagem, "minutos": round(mins, 1), "raio": radius, "quando": time.strftime("%Y-%m-%dT%H:%M:%S")}
    (DATA_DIR / f"{level}.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def load_juiz():
    """Notas do juiz de imagem: {seed: {"nota": 0-10, "neve": bool, "motivo": str}}."""
    p = DATA_DIR / "juiz.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def save_juiz(data):
    DATA_DIR.mkdir(exist_ok=True)
    (DATA_DIR / "juiz.json").write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")


def build_index():
    """Junta resultados.csv (fonte da verdade) com resultados/*.json em bluemap/web/ui/index.json."""
    rows = {}
    if RESULTS.exists():
        with RESULTS.open(encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f, delimiter=";"):
                rows[r["seed"]] = r                       # a ultima linha de cada seed vence
    juiz = load_juiz()
    seeds = []
    for seed, r in rows.items():
        level = safe_id(seed)
        extra = {}
        p = DATA_DIR / f"{level}.json"
        if p.exists():
            extra = json.loads(p.read_text(encoding="utf-8"))
        achados = extra.get("achados")
        if achados is None:                                # linhas antigas: so as distancias do CSV
            try:
                achados = {k: ({"dist": v} if v is not None else None) for k, v in json.loads(r["achados"]).items()}
            except (ValueError, KeyError):
                achados = {}
        has_map = (BLUEMAP_DIR / "web" / "maps" / level).exists() and r["status"] == "ok"
        relevo = None
        rp = DATA_DIR / "relevo" / f"{level}.json"
        if rp.exists():
            relevo = json.loads(rp.read_text(encoding="utf-8"))
        img = DATA_DIR / "relevo" / f"{level}.png"
        has_img = img.exists() and r["status"] in ("ok", "candidata")
        if has_img:                                        # a interface le a imagem de relevo da mesma origem do mapa
            (WEB_UI / "relevo").mkdir(parents=True, exist_ok=True)
            shutil.copy2(img, WEB_UI / "relevo" / f"{level}.png")
        seeds.append({
            "seed": seed, "id": level, "status": r["status"], "minutos": float(r["minutos"] or 0),
            "spawn": extra.get("spawn"), "centro": extra.get("centro"), "achados": achados, "raio": extra.get("raio", RADIUS),
            "quando": extra.get("quando"), "mapa": has_map,
            "cavernas": has_map and (BLUEMAP_DIR / "web" / "maps" / (level + CAVE_SUFFIX)).exists(),
            "relevo": relevo, "juiz": juiz.get(seed), "imagem": has_img, "triagem": extra.get("triagem"),
        })
    WEB_UI.mkdir(parents=True, exist_ok=True)
    (WEB_UI / "index.json").write_text(json.dumps(
        {"gerado": time.strftime("%Y-%m-%dT%H:%M:%S"), "seeds": seeds}, indent=1, ensure_ascii=False), encoding="utf-8")
    return len(seeds)


def copy_ui():
    """Copia ui/ para bluemap/web/ui/ (o BlueMap serve a interface na mesma origem do mapa)."""
    if UI_DIR.exists():
        shutil.copytree(UI_DIR, WEB_UI, dirs_exist_ok=True)


def make_caves(seeds):
    """Renderiza um segundo mapa por seed, com as cavernas abertas (caro: minutos e centenas de MB)."""
    for seed in seeds:
        level = safe_id(seed)
        if not (WORLDS_DIR / level).exists():
            print(f"{seed}: sem mundo em worlds/ (so seeds aprovadas tem mapa)")
            continue
        src = BLUEMAP_DIR / "config" / "maps" / f"{level}.conf"
        text = src.read_text(encoding="utf-8")
        text = re.sub(r'^(\s*name:\s*)"(.*)"', r'\1"\2 (cavernas)"', text, count=1, flags=re.M)
        text = re.sub(r"^(\s*sorting:\s*)\d+", r"\g<1>1000", text, count=1, flags=re.M)
        text = re.sub(r"^(\s*remove-caves-below-y:\s*)-?\d+", r"\g<1>-10000", text, count=1, flags=re.M)
        (BLUEMAP_DIR / "config" / "maps" / f"{level}{CAVE_SUFFIX}.conf").write_text(text, encoding="utf-8")
        print(f"{seed}: renderizando cavernas (uns 5 min)...", flush=True)
        t0 = time.time()
        r = subprocess.run([JAVA, f"-Xmx{BLUEMAP_RAM}", "-jar", BLUEMAP_JAR, "-r", "-m", level + CAVE_SUFFIX], cwd=BLUEMAP_DIR)
        print(f"   -> {'ok' if r.returncode == 0 else 'falha'} ({(time.time() - t0) / 60:.1f} min)")


def default_saves():
    """Pasta de mundos do Minecraft Java (launcher padrao)."""
    base = Path(os.environ["APPDATA"]) / ".minecraft" if os.environ.get("APPDATA") else Path.home() / ".minecraft"
    return base / "saves"


# O Paper 26.x guarda estes dados globais dentro da dimensao (dimensions/minecraft/overworld/data/minecraft/),
# mas o jogo os le da raiz do mundo (data/minecraft/). Sem eles o jogo falha com "Overworld settings missing".
PAPER_TO_ROOT = ("world_gen_settings.dat", "game_rules.dat", "weather.dat", "scheduled_events.dat")


def adapt_for_vanilla(world):
    """Leva os .dat globais do overworld para a raiz do mundo, so quando faltam (nunca sobrescreve).
    Devolve quantos arquivos foram adicionados."""
    ow = Path(world) / "dimensions" / "minecraft" / "overworld" / "data" / "minecraft"
    root = Path(world) / "data" / "minecraft"
    added = 0
    for name in PAPER_TO_ROOT:
        if (ow / name).exists() and not (root / name).exists():
            root.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ow / name, root / name)
            added += 1
    return added


def play_world(seed, saves, force=False):
    """Copia o mundo pre-gerado de uma seed para a pasta saves do Minecraft e devolve (destino, acao).
    acao: "copiado", "reparado" (ja existia e faltavam .dat do jogo) ou "existente".
    Fora da area gerada o jogo continua gerando o mesmo terreno."""
    level = safe_id(seed)
    src = WORLDS_DIR / level
    if not src.exists():
        raise FileNotFoundError(f"{seed}: sem mundo em worlds/ (so seeds aprovadas tem mundo)")
    dst = Path(saves) / ("SeedHunter_" + level[len("seed_"):])
    if dst.exists():
        if not force:
            # nao sobrescreve o progresso do jogador; so completa o que o jogo precisa e faltava
            return dst, ("reparado" if adapt_for_vanilla(dst) else "existente")
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("session.lock"))
    adapt_for_vanilla(dst)
    return dst, "copiado"


def read_rows():
    """Ultima linha de cada seed em resultados.csv."""
    rows = {}
    if RESULTS.exists():
        with RESULTS.open(encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f, delimiter=";"):
                rows[r["seed"]] = r
    return rows


def write_row(seed, status, hits, spawn, mins, radius, centro=None, triagem=None):
    """Registra o resultado de uma seed fora da rodada principal (aprovacao do juiz): JSON, CSV e index.json."""
    brief = {k.split()[-1]: (v["dist"] if v else None) for k, v in hits.items()}
    save_seed(seed, status, hits, spawn, mins, radius, centro, triagem)
    new = not RESULTS.exists()
    with RESULTS.open("a", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter=";")
        if new:
            w.writerow(["seed", "status", "achados", "minutos"])
        w.writerow([seed, status, json.dumps(brief), f"{mins:.1f}"])
    build_index()


def juiz_preparar(lote_size=JUIZ_LOTE):
    """Copia as imagens de relevo das candidatas sem nota para lotes com nomes embaralhados (img_01...).
    O juiz ve so a imagem: nunca o score nem a seed. Devolve as pastas dos lotes (cada uma com mapa.json)."""
    rows, juiz = read_rows(), load_juiz()
    pend = [s for s, r in rows.items()
            if r["status"] == "candidata" and s not in juiz and (DATA_DIR / "relevo" / f"{safe_id(s)}.png").exists()]
    random.shuffle(pend)
    stamp, lotes = time.strftime("%Y%m%d_%H%M%S"), []
    for n in range(0, len(pend), lote_size):
        d = DATA_DIR / "juiz" / f"lote_{stamp}_{n // lote_size + 1:02d}"
        d.mkdir(parents=True)
        mapa = {}
        for i, s in enumerate(pend[n:n + lote_size], 1):
            shutil.copy2(DATA_DIR / "relevo" / f"{safe_id(s)}.png", d / f"img_{i:02d}.png")
            mapa[f"img_{i:02d}"] = s
        (d / "mapa.json").write_text(json.dumps(mapa, indent=1), encoding="utf-8")
        lotes.append(d)
    return lotes


def juiz_aplicar(resposta, lote):
    """Le o JSON do juiz ({"notas": {"img_01": {"nota": 7, "neve": true, "motivo": "..."}}}) e grava em juiz.json."""
    mapa = json.loads((Path(lote) / "mapa.json").read_text(encoding="utf-8"))
    data = json.loads(Path(resposta).read_text(encoding="utf-8"))
    notas, juiz, n = data.get("notas", data), load_juiz(), 0
    for img, v in notas.items():
        seed = mapa.get(re.sub(r"\.png$", "", img))
        if seed is None:
            continue
        juiz[seed] = {"nota": float(v["nota"]), "neve": bool(v.get("neve", False)),
                      "motivo": str(v.get("motivo", "")), "quando": time.strftime("%Y-%m-%dT%H:%M:%S")}
        n += 1
    save_juiz(juiz)
    build_index()
    return n


def aprovar(nota_min=JUIZ_NOTA_MIN, radius=RADIUS, neve_min=None, cereja_min=None):
    """Fase final do funil: candidatas com nota >= nota_min vao para o BlueMap ("ok"); as demais
    "descartada" e o mundo e apagado. Candidatas ainda sem nota ficam esperando."""
    rows, juiz = read_rows(), load_juiz()
    feitos = {"ok": 0, "descartada": 0, "falha no bluemap": 0}
    for i, (seed, r) in enumerate(rows.items(), 1):
        if r["status"] != "candidata" or seed not in juiz:
            continue
        level = safe_id(seed)
        info = {}
        p = DATA_DIR / f"{level}.json"
        if p.exists():
            info = json.loads(p.read_text(encoding="utf-8"))
        hits, spawn, mins = info.get("achados", {}), info.get("spawn"), float(r["minutos"] or 0)
        rp = DATA_DIR / "relevo" / f"{level}.json"
        medido = json.loads(rp.read_text(encoding="utf-8")) if rp.exists() else {}   # neve/cereja medidas, nao as do juiz
        if juiz[seed]["nota"] >= nota_min and not (neve_min and medido.get("neve", 0) < neve_min)                 and not (cereja_min and medido.get("cereja", 0) < cereja_min):
            print(f"{seed}: nota {juiz[seed]['nota']:g}, renderizando 3D...", flush=True)
            ok = render(seed, level, i, spawn, hits)
            status = "ok" if ok else "falha no bluemap"
        else:
            shutil.rmtree(WORLDS_DIR / level, ignore_errors=True)
            status = "descartada"
        feitos[status] += 1
        write_row(seed, status, hits, spawn, mins, info.get("raio", radius), info.get("centro"), info.get("triagem"))
    return feitos


def run_seeds(seeds, rules, radius, verbose, info, limit, log, anel_min=None, centros=None, tipo="anel", neve_min=None, cereja_min=None, raio_min=0):
    """Pipeline com sobreposicao: enquanto o BlueMap renderiza a seed N, o Paper ja filtra/gera a N+1.
    Um render por vez (o proximo espera o anterior), e seeds reprovadas nunca vao para o BlueMap.
    centros: {seed: resultado da triagem} - o Chunky gera em volta do centro do anel em vez do spawn."""
    done = done_seeds()
    w = csv.writer(log, delimiter=";")
    pool = ThreadPoolExecutor(max_workers=1)
    pending = None                       # (future, seed, hits, spawn, t0, triagem, raio) da seed que esta renderizando
    ran, t_start = 0, time.time()
    centros = centros or {}

    def record(seed, status, hits, spawn, t0, tri=None, rad=radius):
        mins = (time.time() - t0) / 60   # com a sobreposicao, o tempo de uma seed inclui o que correu junto
        brief = {k.split()[-1]: (v["dist"] if v else None) for k, v in hits.items()}
        print(f"   -> {seed}: {status} {brief} ({mins:.1f} min)", flush=True)
        save_seed(seed, status, hits, spawn, mins, rad, {"x": tri["x"], "z": tri["z"]} if tri else None, tri)
        w.writerow([seed, status, json.dumps(brief), f"{mins:.1f}"])
        log.flush()
        build_index()

    def finish():
        nonlocal pending
        fut, seed, hits, spawn, t0, tri, rad = pending
        pending = None
        try:
            ok = fut.result()
        except Exception as e:           # um render quebrado nao derruba a rodada
            print(f"   render falhou: {e}")
            ok = False
        record(seed, "ok" if ok else "falha no bluemap", hits, spawn, t0, tri, rad)

    try:
        for i, seed in enumerate(seeds, 1):
            if pending and pending[0].done():
                finish()
            if seed in done:
                print(f"[{i}/{len(seeds)}] {seed}: ja processada, pulando")
                continue
            if limit and ran >= limit:
                break
            ran += 1
            t0 = time.time()
            print(f"[{i}/{len(seeds)}] {seed}: gerando...", flush=True)
            tri = centros.get(seed)
            rad = triagem.adaptive_radius(tri["raio"], radius) if tri else radius   # anel + margem, nao um raio fixo
            if tri:
                print(f"   raio de geracao: {rad} blocos (anel ~{tri['raio']})", flush=True)
            status, hits, spawn, relevo = prepare(seed, rules, rad, verbose, info, anel_min,
                                                  {"x": tri["x"], "z": tri["z"]} if tri else None, tipo, neve_min, cereja_min, raio_min)
            if relevo:
                est = f" (cubiomes previu {tri['score']})" if tri else ""
                print(f"   relevo: anel {relevo['score']} (neve {relevo.get('neve', '-')}){est}", flush=True)
            if status == "ok":
                if pending:
                    finish()             # so um render por vez: espera o anterior
                print(f"   {seed}: renderizando 3D em segundo plano...", flush=True)
                pending = (pool.submit(render, seed, safe_id(seed), i, spawn, hits), seed, hits, spawn, t0, tri, rad)
            else:
                record(seed, status, hits, spawn, t0, tri, rad)
    finally:
        if pending:
            finish()
        pool.shutdown()
    print(f"\nRodada: {ran} seeds em {(time.time() - t_start) / 60:.1f} min", flush=True)


def parse_rule(text):
    target, _, dist = text.rpartition("=")
    return target.strip(), int(dist)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--random", type=int, default=0, metavar="N", help="testa N seeds aleatorias em vez de seeds.txt")
    ap.add_argument("--limit", type=int, default=0, metavar="N", help="processa no maximo N seeds nesta rodada")
    ap.add_argument("--radius", type=int, default=RADIUS, help="raio em blocos (padrao %(default)s)")
    ap.add_argument("--rule", action="append", metavar="ALVO=DIST",
                    help='substitui LOCATE_RULES, ex.: "structure #minecraft:village=1500" (repetivel; "none=0" desliga)')
    ap.add_argument("--verbose", action="store_true", help="mostra o log do servidor")
    ap.add_argument("--sem-achados", action="store_true", help="pula os /locate informativos (mais rapido)")
    ap.add_argument("--cavernas", nargs="+", metavar="SEED", help="gera o mapa com cavernas abertas das seeds indicadas")
    ap.add_argument("--reindex", action="store_true", help="so atualiza a interface e o index.json")
    ap.add_argument("--anel-min", type=float, default=ANEL_MIN, metavar="F",
                    help="funil de relevo: score minimo (0-1) para virar candidata (padrao %(default)s)")
    ap.add_argument("--sem-anel", action="store_true", help="desliga o funil de relevo: toda seed gerada vai direto ao BlueMap")
    ap.add_argument("--garimpar", type=int, metavar="N",
                    help="etapa 0: avalia o anel de muitas seeds so com o cubiomes (sem gerar) e leva as N melhores ao servidor")
    ap.add_argument("--amostra", type=int, metavar="M", help="com --garimpar: quantas seeds aleatorias avaliar (padrao 60*N)")
    ap.add_argument("--triagem-min", type=float, default=None, metavar="F",
                    help="com --garimpar: score minimo so-cubiomes (padrao triagem.TRIAGEM_MIN = 0,4)")
    ap.add_argument("--tipo", choices=sorted(terrain.TIPOS), default="anel",
                    help="o que procurar: anel (interior em terra) ou bacia (aceita lago de cratera, exige paredes mais altas)")
    ap.add_argument("--neve-min", type=float, default=None, metavar="F",
                    help="exige que ao menos esta fracao (0-1) da crista seja bioma de neve, medida no terreno (triagem, funil e --aprovar)")
    ap.add_argument("--cereja-min", type=float, default=None, metavar="F",
                    help="exige que ao menos esta fracao (0-1) das cristas tenha cerejeiral por perto (use com --tipo cratera)")
    ap.add_argument("--raio-min", type=int, default=0, metavar="BLOCOS",
                    help="descarta aneis com raio menor que isto (triagem e analise do mundo)")
    ap.add_argument("--raio-max", type=int, default=None, metavar="BLOCOS",
                    help="maior anel procurado na triagem (padrao 300; janela de 720 blocos)")
    ap.add_argument("--peso-cereja", type=float, default=0.0, metavar="F",
                    help="bonus no ranking da triagem: score + F * cereja (sem filtrar; 0,2 sobe as cerejeiras)")
    ap.add_argument("--workers", type=int, default=8, help="com --garimpar: processos em paralelo (padrao %(default)s)")
    ap.add_argument("--juiz-preparar", action="store_true",
                    help="monta lotes de imagens (nomes embaralhados) das candidatas sem nota, para o juiz")
    ap.add_argument("--juiz-aplicar", nargs=2, metavar=("RESPOSTA.json", "LOTE"),
                    help="grava as notas do juiz de um lote em resultados/juiz.json")
    ap.add_argument("--aprovar", action="store_true",
                    help="candidatas com nota >= --nota-min vao ao BlueMap; as outras sao descartadas (mundo apagado)")
    ap.add_argument("--nota-min", type=float, default=JUIZ_NOTA_MIN, metavar="N",
                    help="nota minima do juiz (0-10) para aprovar (padrao %(default)s)")
    ap.add_argument("--jogar", nargs="+", metavar="SEED", help="copia o mundo das seeds para a pasta saves do Minecraft")
    ap.add_argument("--saves", metavar="PASTA", help="pasta saves do Minecraft (padrao: %%APPDATA%%\\.minecraft\\saves)")
    ap.add_argument("--forcar", action="store_true", help="com --jogar: recopia mesmo que o mundo ja exista nos saves (apaga o progresso)")
    args = ap.parse_args()

    if args.jogar:
        saves = Path(args.saves) if args.saves else default_saves()
        for s in args.jogar:
            try:
                dst, action = play_world(s, saves, args.forcar)
            except FileNotFoundError as e:
                print(e)
                continue
            msg = {"copiado": "copiado para", "reparado": "ja existia; completei os arquivos que o jogo precisa em",
                   "existente": "ja existe em"}[action]
            print(f"{s}: {msg} {dst}" + ("  (--forcar recopia e apaga o progresso)" if action == "existente" else ""))
            # o jogo lista o nome do level.dat ("seed_...") e, abaixo dele, o nome da pasta
            print(f"   No Minecraft 26.3: Um jogador > entrada com a pasta '{dst.name}' (o titulo mostrado e '{safe_id(s)}').")
        return

    rules = LOCATE_RULES if args.rule is None else [parse_rule(r) for r in args.rule if not r.startswith("none")]
    check_setup()
    copy_ui()
    if args.juiz_preparar:
        lotes = juiz_preparar()
        for d in lotes:
            print(d)
        print(f"{len(lotes)} lote(s) de ate {JUIZ_LOTE} imagens. O juiz abre img_NN.png e responde o JSON; depois: --juiz-aplicar RESPOSTA.json LOTE")
        return
    if args.juiz_aplicar:
        print(f"{juiz_aplicar(*args.juiz_aplicar)} notas gravadas em resultados/juiz.json")
        return
    if args.aprovar:
        print(aprovar(args.nota_min, args.radius, args.neve_min, args.cereja_min))
        return
    if args.cavernas or args.reindex:
        if args.cavernas:
            make_caves(args.cavernas)
        print(f"index.json: {build_index()} seeds")
        return
    centros = None
    if args.garimpar:
        picks = triagem.screen(args.amostra or 60 * args.garimpar, args.garimpar,
                               args.triagem_min if args.triagem_min is not None else triagem.TRIAGEM_MIN, args.workers,
                               tipo=args.tipo, neve_min=args.neve_min, cereja_min=args.cereja_min,
                               raio_min=args.raio_min, raio_max=args.raio_max, peso_cereja=args.peso_cereja)
        if not picks:
            print("Nenhuma seed passou na triagem: aumente --amostra ou baixe --triagem-min.")
            return
        seeds = [str(p["seed"]) for p in picks]
        centros = {str(p["seed"]): p for p in picks}
        for p in picks:
            print(f"   {p['seed']}: score {p['score']} (neve {p['neve']}), anel perto de ({p['x']}, {p['z']}), raio ~{p['raio']}")
    else:
        seeds = load_seeds(args.random)
    new_file = not RESULTS.exists()
    with RESULTS.open("a", encoding="utf-8", newline="") as log:
        if new_file:
            csv.writer(log, delimiter=";").writerow(["seed", "status", "achados", "minutos"])
        run_seeds(seeds, rules, args.radius, args.verbose, not args.sem_achados, args.limit, log,
                  None if args.sem_anel else args.anel_min, centros, args.tipo, args.neve_min, args.cereja_min, args.raio_min)
    print("Interface: http://localhost:8100/ui/  (servir: cd bluemap && java -jar bluemap-cli.jar -w; reinicie-o se ja estava ligado)")


if __name__ == "__main__":
    main()
