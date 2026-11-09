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
LOCATE_RULES = [
    ("structure #minecraft:village", 480),
    # ("biome minecraft:cherry_grove", 800),
    # ("biome minecraft:dappled_forest", 800),
]
# Achados informativos: rodam so depois que a seed passa no filtro e NUNCA reprovam.
# Alimentam a lista de estruturas/biomas, as tags e os marcadores da interface.
INFO_TARGETS = [
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
STATUS_FINAL = {"ok", "reprovada"}  # nao reprocessar; falhas sao tentadas de novo


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


def generate(seed, level, rules, radius, verbose, info=True):
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
        for cmd in (f"chunky world {level}", f"chunky center {spawn['x']} {spawn['z']}", "chunky shape square",
                    f"chunky radius {radius}", "chunky start"):
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


def prepare(seed, rules, radius, verbose, info=True):
    """Filtra e gera uma seed e deixa o mundo pronto em worlds/<level>. Nao renderiza.
    Status "ok" = pronta para o BlueMap; qualquer outro (reprovada, falha...) nunca chega nele."""
    level = safe_id(seed)
    shutil.rmtree(SERVER_DIR / level, ignore_errors=True)      # restos de uma rodada interrompida
    shutil.rmtree(WORLDS_DIR / level, ignore_errors=True)
    status, hits, spawn = generate(seed, level, rules, radius, verbose, info)
    src = SERVER_DIR / level
    if status == "ok" and not src.exists():
        status = "mundo nao encontrado"
    if status == "ok":
        try:
            shutil.move(str(src), str(WORLDS_DIR / level))
        except OSError as e:
            return f"falha ao mover mundo: {e}", hits, spawn
    else:
        shutil.rmtree(src, ignore_errors=True)
    return status, hits, spawn


def save_seed(seed, status, hits, spawn, mins, radius):
    """Um JSON por seed (inclusive reprovadas): a interface le tudo daqui via index.json."""
    level = safe_id(seed)
    data = {"seed": seed, "id": level, "status": status, "spawn": spawn, "centro": spawn, "achados": hits,
            "minutos": round(mins, 1), "raio": radius, "quando": time.strftime("%Y-%m-%dT%H:%M:%S")}
    (DATA_DIR / f"{level}.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def build_index():
    """Junta resultados.csv (fonte da verdade) com resultados/*.json em bluemap/web/ui/index.json."""
    rows = {}
    if RESULTS.exists():
        with RESULTS.open(encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f, delimiter=";"):
                rows[r["seed"]] = r                       # a ultima linha de cada seed vence
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
        seeds.append({
            "seed": seed, "id": level, "status": r["status"], "minutos": float(r["minutos"] or 0),
            "spawn": extra.get("spawn"), "centro": extra.get("centro"), "achados": achados, "raio": extra.get("raio", RADIUS),
            "quando": extra.get("quando"), "mapa": has_map,
            "cavernas": has_map and (BLUEMAP_DIR / "web" / "maps" / (level + CAVE_SUFFIX)).exists(),
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


def play_world(seed, saves, force=False):
    """Copia o mundo pre-gerado de uma seed para a pasta saves do Minecraft e devolve o destino.
    O formato do Paper 26.x e o mesmo do jogo; fora da area gerada o jogo continua gerando normalmente."""
    level = safe_id(seed)
    src = WORLDS_DIR / level
    if not src.exists():
        raise FileNotFoundError(f"{seed}: sem mundo em worlds/ (so seeds aprovadas tem mundo)")
    dst = Path(saves) / ("SeedHunter_" + level[len("seed_"):])
    if dst.exists():
        if not force:
            return dst, False                      # ja copiado: nao sobrescreve o progresso do jogador
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("session.lock"))
    return dst, True


def run_seeds(seeds, rules, radius, verbose, info, limit, log):
    """Pipeline com sobreposicao: enquanto o BlueMap renderiza a seed N, o Paper ja filtra/gera a N+1.
    Um render por vez (o proximo espera o anterior), e seeds reprovadas nunca vao para o BlueMap."""
    done = done_seeds()
    w = csv.writer(log, delimiter=";")
    pool = ThreadPoolExecutor(max_workers=1)
    pending = None                       # (future, seed, hits, spawn, t0) da seed que esta renderizando
    ran, t_start = 0, time.time()

    def record(seed, status, hits, spawn, t0):
        mins = (time.time() - t0) / 60   # com a sobreposicao, o tempo de uma seed inclui o que correu junto
        brief = {k.split()[-1]: (v["dist"] if v else None) for k, v in hits.items()}
        print(f"   -> {seed}: {status} {brief} ({mins:.1f} min)", flush=True)
        save_seed(seed, status, hits, spawn, mins, radius)
        w.writerow([seed, status, json.dumps(brief), f"{mins:.1f}"])
        log.flush()
        build_index()

    def finish():
        nonlocal pending
        fut, seed, hits, spawn, t0 = pending
        pending = None
        try:
            ok = fut.result()
        except Exception as e:           # um render quebrado nao derruba a rodada
            print(f"   render falhou: {e}")
            ok = False
        record(seed, "ok" if ok else "falha no bluemap", hits, spawn, t0)

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
            status, hits, spawn = prepare(seed, rules, radius, verbose, info)
            if status == "ok":
                if pending:
                    finish()             # so um render por vez: espera o anterior
                print(f"   {seed}: renderizando 3D em segundo plano...", flush=True)
                pending = (pool.submit(render, seed, safe_id(seed), i, spawn, hits), seed, hits, spawn, t0)
            else:
                record(seed, status, hits, spawn, t0)
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
    ap.add_argument("--jogar", nargs="+", metavar="SEED", help="copia o mundo das seeds para a pasta saves do Minecraft")
    ap.add_argument("--saves", metavar="PASTA", help="pasta saves do Minecraft (padrao: %%APPDATA%%\\.minecraft\\saves)")
    ap.add_argument("--forcar", action="store_true", help="com --jogar: recopia mesmo que o mundo ja exista nos saves (apaga o progresso)")
    args = ap.parse_args()

    if args.jogar:
        saves = Path(args.saves) if args.saves else default_saves()
        for s in args.jogar:
            try:
                dst, copied = play_world(s, saves, args.forcar)
            except FileNotFoundError as e:
                print(e)
                continue
            print(f"{s}: {'copiado para' if copied else 'ja existe em'} {dst}" + ("" if copied else "  (use --forcar para recopiar; apaga o progresso)"))
        print("No Minecraft 26.3: Um jogador > procure o mundo SeedHunter_<seed>.")
        return

    rules = LOCATE_RULES if args.rule is None else [parse_rule(r) for r in args.rule if not r.startswith("none")]
    check_setup()
    copy_ui()
    if args.cavernas or args.reindex:
        if args.cavernas:
            make_caves(args.cavernas)
        print(f"index.json: {build_index()} seeds")
        return
    seeds = load_seeds(args.random)
    new_file = not RESULTS.exists()
    with RESULTS.open("a", encoding="utf-8", newline="") as log:
        if new_file:
            csv.writer(log, delimiter=";").writerow(["seed", "status", "achados", "minutos"])
        run_seeds(seeds, rules, args.radius, args.verbose, not args.sem_achados, args.limit, log)
    print("Interface: http://localhost:8100/ui/  (servir: cd bluemap && java -jar bluemap-cli.jar -w; reinicie-o se ja estava ligado)")


if __name__ == "__main__":
    main()
