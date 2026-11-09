#!/usr/bin/env python3
"""seed_hunter.py - preview 3D de varias seeds de Minecraft Java.

Paper + Chunky + BlueMap CLI. So biblioteca padrao do Python 3.10+.
Fluxo por seed: sobe o Paper -> filtra com /locate (centrado em 0,0) ->
pre-gera com Chunky -> renderiza no BlueMap com marcadores nativos.
O resultados.csv e a fonte da verdade para retomar de onde parou.
"""
import argparse, csv, json, queue, random, re, shutil, subprocess, sys, threading, time
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

RADIUS = 480                        # blocos em volta de (0,0): 30 chunks
# Regras do filtro: (alvo do /locate, distancia maxima de (0,0) em blocos).
# Alvo = "structure <id>" ou "biome <id>". Lista vazia = sem filtro.
LOCATE_RULES = [
    ("structure #minecraft:village", 480),
    # ("biome minecraft:cherry_grove", 800),
    # ("biome minecraft:dappled_forest", 800),
]
ORIGIN = "execute in minecraft:overworld positioned 0 64 0 run locate "

# Ajustes do site do BlueMap (config/webapp.conf). O padrao do BlueMap e hires 100;
# 300 cobre boa parte do mapa sem pesar tanto na GPU. Resolucao 0.8 alivia mais.
# O slider continua livre no menu (max 1000 deixa ver os 480 blocos inteiros).
WEBAPP_TWEAKS = {"hires-slider-max": 1000, "hires-slider-default": 300, "resolution-default": 0.8}

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


def generate(seed, level, rules, radius, verbose):
    """Retorna (status, achados, spawn). O mundo fica em server/<level>."""
    set_props({"level-seed": seed, "level-name": level, "sync-chunk-writes": "false"})
    srv = Server(verbose)
    try:
        if not srv.wait_for(r"Done \(.*\)! For help", 300):
            return "falha ao iniciar", {}, None
        hits = {}
        for target, max_dist in rules:
            srv.send(ORIGIN + target)
            line = srv.wait_for(r"blocks away\)|Could not find|Unknown|Invalid", 180)
            hit = parse_locate(line) if line else None
            if line and not hit and not LOCATE_FAIL.search(line):
                return f"locate inesperado: {line[:80]}", hits, None
            hits[target] = hit
            if hit is None or hit["dist"] > max_dist:
                return "reprovada", hits, None
        srv.send("execute in minecraft:overworld run setworldspawn ~ ~ ~")   # repete o spawn atual so para le-lo
        spawn = parse_spawn(srv.wait_for(r"world spawn point", 30) or "")
        for cmd in (f"chunky world {level}", "chunky center 0 0", "chunky shape square",
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


def process(seed, index, rules, radius, verbose):
    level = safe_id(seed)
    shutil.rmtree(SERVER_DIR / level, ignore_errors=True)      # restos de uma rodada interrompida
    shutil.rmtree(WORLDS_DIR / level, ignore_errors=True)
    status, hits, spawn = generate(seed, level, rules, radius, verbose)
    src = SERVER_DIR / level
    if status == "ok" and not src.exists():
        status = "mundo nao encontrado"
    if status == "ok":
        try:
            shutil.move(str(src), str(WORLDS_DIR / level))
        except OSError as e:
            return f"falha ao mover mundo: {e}", hits
        print("   renderizando 3D...", flush=True)
        if render(seed, level, index, spawn, hits):
            (DATA_DIR / f"{level}.json").write_text(
                json.dumps({"seed": seed, "spawn": spawn, "achados": hits}, indent=2), encoding="utf-8")
        else:
            status = "falha no bluemap"
    else:
        shutil.rmtree(src, ignore_errors=True)
    return status, hits


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
    args = ap.parse_args()

    rules = LOCATE_RULES if args.rule is None else [parse_rule(r) for r in args.rule if not r.startswith("none")]
    check_setup()
    seeds = load_seeds(args.random)
    done = done_seeds()
    new_file = not RESULTS.exists()
    ran = 0
    with RESULTS.open("a", encoding="utf-8", newline="") as log:
        w = csv.writer(log, delimiter=";")
        if new_file:
            w.writerow(["seed", "status", "achados", "minutos"])
        for i, seed in enumerate(seeds, 1):
            if seed in done:
                print(f"[{i}/{len(seeds)}] {seed}: ja processada, pulando")
                continue
            if args.limit and ran >= args.limit:
                break
            ran += 1
            t0 = time.time()
            print(f"[{i}/{len(seeds)}] {seed}: gerando...", flush=True)
            status, hits = process(seed, i, rules, args.radius, args.verbose)
            mins = (time.time() - t0) / 60
            brief = {k.split()[-1]: (v["dist"] if v else None) for k, v in hits.items()}
            print(f"   -> {status} {brief} ({mins:.1f} min)")
            w.writerow([seed, status, json.dumps(brief), f"{mins:.1f}"])
            log.flush()
    print("\nPronto! Para ver: cd bluemap && java -jar bluemap-cli.jar -w  ->  http://localhost:8100")


if __name__ == "__main__":
    main()
