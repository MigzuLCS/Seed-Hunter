import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import seed_hunter as sh

# Linhas reais capturadas no smoke test (Paper 26.3), com codigos ANSI.
VILLAGE = "[12:14:39 INFO]: System chat: The nearest #minecraft:village (minecraft:village_plains) is at \x1b[38;2;85;255;85m[160, ~, 880]\x1b[0m (894 blocks away)"
BIOME = "[12:14:45 INFO]: System chat: The nearest minecraft:cherry_grove is at \x1b[38;2;85;255;85m[-416, 64, 768]\x1b[0m (873 blocks away)"
SPAWN = "[12:15:03 INFO]: System chat: Set the world spawn point to 96, 145, -32 [0.0, 0.0] in minecraft:overworld"


class ParseTests(unittest.TestCase):
    def test_structure_with_tilde_y(self):
        self.assertEqual(sh.parse_locate(VILLAGE), {"x": 160, "y": None, "z": 880, "dist": 894})

    def test_biome_negative_coords(self):
        self.assertEqual(sh.parse_locate(BIOME), {"x": -416, "y": 64, "z": 768, "dist": 873})

    def test_not_found(self):
        self.assertIsNone(sh.parse_locate("Could not find a biome of type minecraft:x within a reasonable distance"))

    def test_spawn(self):
        self.assertEqual(sh.parse_spawn(SPAWN), {"x": 96, "y": 145, "z": -32})

    def test_safe_id(self):
        self.assertEqual(sh.safe_id("-123"), "seed_n123")
        self.assertEqual(sh.safe_id("abc def"), "seed_abc_def")

    def test_markers(self):
        out = sh.markers_hocon({"x": 1, "y": 2, "z": 3}, {"structure #minecraft:village": sh.parse_locate(VILLAGE)})
        self.assertIn('label: "Spawn"', out)
        self.assertIn("village (894 blocos)", out)
        self.assertIn("y: 100", out)   # y '~' vira 100


class PatchConfTests(unittest.TestCase):
    def test_only_active_lines(self):
        src = "# hires-slider-default: 1\nhires-slider-default: 100\nother: 5\n"
        out = sh.patch_conf(src, {"hires-slider-default": 500})
        self.assertEqual(out, "# hires-slider-default: 1\nhires-slider-default: 500\nother: 5\n")


class PipelineTests(unittest.TestCase):
    """run_seeds com prepare/render falsos: ordem, sobreposicao e destino de cada status."""

    def run_fake(self, statuses, render_results, centros=None):
        import io, threading, time
        events, lock = [], threading.Lock()
        live = {"n": 0, "max": 0}
        self.centers_seen, self.saved, self.radius_seen = {}, {}, {}

        def log_ev(*e):
            with lock:
                events.append((time.time(),) + e)

        def fake_prepare(seed, rules, radius, verbose, info=True, anel_min=None, center=None, tipo="anel", neve_min=None):
            self.centers_seen[seed] = center
            self.radius_seen[seed] = radius
            log_ev("prep_start", seed); time.sleep(0.2); log_ev("prep_end", seed)
            return statuses[seed], {}, {"x": 0, "y": 64, "z": 0}, None

        def fake_render(seed, level, index, spawn, hits):
            with lock:
                live["n"] += 1; live["max"] = max(live["max"], live["n"])
            log_ev("render_start", seed); time.sleep(0.5); log_ev("render_end", seed)
            with lock:
                live["n"] -= 1
            r = render_results[seed]
            if isinstance(r, Exception):
                raise r
            return r

        saved = (sh.prepare, sh.render, sh.save_seed, sh.build_index, sh.done_seeds)
        def fake_save(seed, status, hits, spawn, mins, radius, centro=None, triagem=None):
            self.saved[seed] = (centro, triagem)

        sh.prepare, sh.render, sh.save_seed = fake_prepare, fake_render, fake_save
        sh.build_index, sh.done_seeds = lambda: 0, lambda: set()
        buf = io.StringIO()
        try:
            sh.run_seeds(list(statuses), [], 480, False, False, 0, buf, None, centros)
        finally:
            sh.prepare, sh.render, sh.save_seed, sh.build_index, sh.done_seeds = saved
        rows = {l.split(";")[0]: l.split(";")[1] for l in buf.getvalue().splitlines()}
        return events, rows, live["max"]

    def test_overlap_order_and_destinations(self):
        statuses = {"a": "ok", "b": "ok", "c": "reprovada", "d": "ok", "e": "ok"}
        results = {"a": True, "b": True, "d": False, "e": RuntimeError("boom")}
        events, rows, max_live = self.run_fake(statuses, results)
        t = {(kind, seed): ts for ts, kind, seed in events}
        self.assertLess(t[("prep_start", "b")], t[("render_end", "a")])        # gera a b enquanto a a renderiza
        self.assertEqual(max_live, 1)                                          # nunca dois renders juntos
        self.assertNotIn(("render_start", "c"), t)                             # reprovada nao vai ao BlueMap
        self.assertEqual(rows, {"a": "ok", "b": "ok", "c": "reprovada", "d": "falha no bluemap", "e": "falha no bluemap"})


class FunnelTests(unittest.TestCase):
    """Funil de relevo + juiz de imagem, com geracao, analise e render falsos, em pastas temporarias."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.saved = {k: getattr(sh, k) for k in ("SERVER_DIR", "WORLDS_DIR", "DATA_DIR", "RESULTS", "BLUEMAP_DIR", "WEB_UI")}
        sh.SERVER_DIR, sh.WORLDS_DIR, sh.DATA_DIR = d / "server", d / "worlds", d / "resultados"
        sh.RESULTS, sh.BLUEMAP_DIR, sh.WEB_UI = d / "resultados.csv", d / "bluemap", d / "bluemap" / "web" / "ui"
        for p in (sh.SERVER_DIR, sh.WORLDS_DIR, sh.DATA_DIR / "relevo"):
            p.mkdir(parents=True)
        self.scores = {}
        self.rendered = []
        self.orig = (sh.generate, sh.terrain.analyze_world, sh.render)

        def fake_generate(seed, level, rules, radius, verbose, info=True, center=None):
            (sh.SERVER_DIR / level).mkdir()
            return "ok", {"structure #minecraft:village": {"x": 1, "y": None, "z": 2, "dist": 5}}, {"x": 0, "y": 64, "z": 0}

        def fake_analyze(level, out_dir=None, rmax=45, tipo="anel"):
            (sh.DATA_DIR / "relevo" / f"{level}.png").write_bytes(b"\x89PNG")
            return {"score": self.scores[level]}

        sh.generate, sh.terrain.analyze_world = fake_generate, fake_analyze
        sh.render = lambda seed, level, sorting, spawn, hits: self.rendered.append(seed) or True

    def tearDown(self):
        sh.generate, sh.terrain.analyze_world, sh.render = self.orig
        for k, v in self.saved.items():
            setattr(sh, k, v)
        self.tmp.cleanup()

    def test_prepare_funnel_statuses(self):
        self.scores = {"seed_1": 0.9, "seed_2": 0.2}
        st1 = sh.prepare("1", [], 480, False, False, anel_min=0.5)
        st2 = sh.prepare("2", [], 480, False, False, anel_min=0.5)
        self.assertEqual(st1[0], "candidata")
        self.assertTrue((sh.WORLDS_DIR / "seed_1").exists())            # candidata guarda o mundo para o juiz
        self.assertEqual(st2[0], "sem relevo")
        self.assertFalse((sh.WORLDS_DIR / "seed_2").exists())           # sem relevo: apagado na hora
        self.assertFalse((sh.SERVER_DIR / "seed_2").exists())
        st3 = sh.prepare("3", [], 480, False, False, anel_min=None)     # funil desligado: vai direto ao BlueMap
        self.assertEqual(st3[0], "ok")
        self.assertIsNone(st3[3])

    def test_judge_flow(self):
        import json
        self.scores = {"seed_1": 0.9, "seed_2": 0.8, "seed_3": 0.7, "seed_4": 0.1}
        for s in ("1", "2", "3", "4"):
            status, hits, spawn, _ = sh.prepare(s, [], 480, False, False, anel_min=0.5)
            sh.write_row(s, status, hits, spawn, 1.0, 480)
        lotes = sh.juiz_preparar(lote_size=2)
        self.assertEqual(len(lotes), 2)                                  # 3 candidatas em lotes de 2 (a 4 foi descartada)
        mapa = {}
        for d in lotes:
            self.assertTrue(all((d / f"{k}.png").exists() for k in json.loads((d / "mapa.json").read_text())))
            mapa.update({v: (d, k) for k, v in json.loads((d / "mapa.json").read_text()).items()})
        self.assertEqual(set(mapa), {"1", "2", "3"})
        for seed, nota in (("1", 9), ("2", 6), ("3", 8)):                # o juiz responde por imagem, com ou sem .png
            d, img = mapa[seed]
            resp = d / f"resp_{seed}.json"
            resp.write_text(json.dumps({"notas": {img + ".png": {"nota": nota, "neve": seed == "1", "motivo": "x"}}}), encoding="utf-8")
            self.assertEqual(sh.juiz_aplicar(resp, d), 1)
        self.assertEqual(sh.juiz_preparar(), [])                         # tudo ja julgado: nada novo para julgar
        feitos = sh.aprovar(nota_min=7, radius=480)
        self.assertEqual(feitos["ok"], 2)                                # notas 9 e 8
        self.assertEqual(feitos["descartada"], 1)                        # nota 6
        self.assertEqual(sorted(self.rendered), ["1", "3"])
        self.assertFalse((sh.WORLDS_DIR / "seed_2").exists())            # descartada: mundo apagado
        self.assertTrue((sh.WORLDS_DIR / "seed_1").exists())
        rows = sh.read_rows()
        self.assertEqual({s: r["status"] for s, r in rows.items()},
                         {"1": "ok", "2": "descartada", "3": "ok", "4": "sem relevo"})
        idx = {s["seed"]: s for s in json.loads((sh.WEB_UI / "index.json").read_text(encoding="utf-8"))["seeds"]}
        self.assertEqual(idx["1"]["juiz"]["nota"], 9.0)
        self.assertTrue(idx["1"]["juiz"]["neve"])
        self.assertTrue(idx["1"]["imagem"])
        self.assertFalse(idx["4"]["imagem"])                             # sem relevo: sem imagem na interface


class PlayWorldTests(unittest.TestCase):
    def test_copy_keeps_progress_and_skips_lock(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            world = d / "worlds" / "seed_n42"
            ow = world / "dimensions" / "minecraft" / "overworld" / "data" / "minecraft"
            ow.mkdir(parents=True)                                       # layout do Paper: .dat dentro da dimensao
            for n in ("world_gen_settings.dat", "game_rules.dat", "weather.dat", "scheduled_events.dat"):
                (ow / n).write_text("paper-" + n)
            (world / "data" / "minecraft").mkdir(parents=True)
            (world / "data" / "minecraft" / "scoreboard.dat").write_text("sb")
            (world / "level.dat").write_text("x"); (world / "session.lock").write_text("lock")
            saves = d / "saves"; saves.mkdir()
            old = sh.WORLDS_DIR; sh.WORLDS_DIR = d / "worlds"
            try:
                dst, action = sh.play_world("-42", saves)
                self.assertEqual(action, "copiado")
                self.assertEqual(dst.name, "SeedHunter_n42")
                self.assertTrue((dst / "level.dat").exists())
                self.assertFalse((dst / "session.lock").exists())
                # o jogo le os .dat globais da raiz: sem world_gen_settings.dat falha com "Overworld settings missing"
                for n in ("world_gen_settings.dat", "game_rules.dat", "weather.dat", "scheduled_events.dat"):
                    self.assertTrue((dst / "data" / "minecraft" / n).exists(), n)
                (dst / "progresso.txt").write_text("jogador")            # o jogador mexeu no mundo
                (dst / "data" / "minecraft" / "game_rules.dat").write_text("do-jogador")
                _, action2 = sh.play_world("-42", saves)                 # segunda chamada nao sobrescreve
                self.assertEqual(action2, "existente")
                self.assertTrue((dst / "progresso.txt").exists())
                (dst / "data" / "minecraft" / "weather.dat").unlink()    # mundo copiado pela versao antiga do script
                _, action3 = sh.play_world("-42", saves)
                self.assertEqual(action3, "reparado")
                self.assertTrue((dst / "data" / "minecraft" / "weather.dat").exists())
                self.assertEqual((dst / "data" / "minecraft" / "game_rules.dat").read_text(), "do-jogador")   # nao sobrescreve
                _, action4 = sh.play_world("-42", saves, force=True)     # --forcar recopia
                self.assertEqual(action4, "copiado")
                self.assertFalse((dst / "progresso.txt").exists())
                with self.assertRaises(FileNotFoundError):
                    sh.play_world("999", saves)                          # seed sem mundo
            finally:
                sh.WORLDS_DIR = old


class RingCenterTests(unittest.TestCase):
    def test_chunky_commands_use_given_center(self):
        cmds = sh.chunky_commands("seed_1", {"x": 276, "z": -152}, 480)
        self.assertEqual(cmds, ("chunky world seed_1", "chunky center 276 -152", "chunky shape square",
                                "chunky radius 480", "chunky start"))

    def test_pipeline_passes_ring_center_and_saves_triage(self):
        tri = {"seed": "1", "score": 0.55, "neve": 0.9, "raio": 120, "x": 276, "z": -152}
        p = PipelineTests()
        statuses = {"1": "candidata", "2": "sem relevo"}
        p.run_fake(statuses, {}, centros={"1": tri})
        self.assertEqual(p.centers_seen["1"], {"x": 276, "z": -152})      # o Chunky gera em volta do anel
        self.assertIsNone(p.centers_seen["2"])                              # sem triagem: usa o spawn
        self.assertEqual(p.saved["1"], ({"x": 276, "z": -152}, tri))        # centro e triagem ficam gravados
        self.assertEqual(p.saved["2"], (None, None))

    def test_adaptive_radius_per_seed(self):
        mk = lambda s, raio: {"seed": s, "score": 0.6, "neve": 0.5, "raio": raio, "x": 10, "z": 20}
        p = PipelineTests()
        p.run_fake({"a": "sem relevo", "b": "sem relevo", "c": "sem relevo", "d": "sem relevo"}, {},
                   centros={"a": mk("a", 120), "b": mk("b", 300), "c": mk("c", 900)})
        self.assertEqual(p.radius_seen["a"], 320)        # anel pequeno: o minimo (anel + margem ficaria < 320)
        self.assertEqual(p.radius_seen["b"], 460)        # anel de 300 + margem de 160
        self.assertEqual(p.radius_seen["c"], 960)        # limitado ao maximo
        self.assertEqual(p.radius_seen["d"], 480)        # sem triagem: o raio fixo padrao
        self.assertEqual(p.saved["a"][0], {"x": 10, "z": 20})


class LocateCmdTests(unittest.TestCase):
    def test_measured_from_spawn(self):
        self.assertEqual(
            sh.locate_cmd({"x": 96, "y": 145, "z": -32}, "structure #minecraft:village"),
            "execute in minecraft:overworld positioned 96 145 -32 run locate structure #minecraft:village")


class IndexTests(unittest.TestCase):
    def test_build_index(self):
        import json, tempfile
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "resultados").mkdir()
            (d / "bluemap" / "web" / "maps" / "seed_1").mkdir(parents=True)
            (d / "bluemap" / "web" / "maps" / "seed_1_cav").mkdir()
            (d / "resultados.csv").write_text(
                "seed;status;achados;minutos\n"
                '1;falha no chunky;"{}";1.0\n'                                   # linha antiga da seed 1...
                '1;ok;"{""#minecraft:village"": 100}";3.0\n'                     # ...a ultima vence
                '2;reprovada;"{""#minecraft:village"": 900}";0.5\n', encoding="utf-8")
            (d / "resultados" / "seed_1.json").write_text(json.dumps(
                {"spawn": {"x": 1, "y": 2, "z": 3}, "raio": 480,
                 "achados": {"structure #minecraft:village": {"x": 10, "y": None, "z": 20, "dist": 100}}}), encoding="utf-8")
            saved = (sh.RESULTS, sh.DATA_DIR, sh.BLUEMAP_DIR, sh.WEB_UI)
            sh.RESULTS, sh.DATA_DIR, sh.BLUEMAP_DIR, sh.WEB_UI = (
                d / "resultados.csv", d / "resultados", d / "bluemap", d / "bluemap" / "web" / "ui")
            try:
                self.assertEqual(sh.build_index(), 2)
                seeds = {s["seed"]: s for s in json.loads((sh.WEB_UI / "index.json").read_text(encoding="utf-8"))["seeds"]}
            finally:
                sh.RESULTS, sh.DATA_DIR, sh.BLUEMAP_DIR, sh.WEB_UI = saved
        self.assertEqual(seeds["1"]["status"], "ok")
        self.assertTrue(seeds["1"]["mapa"] and seeds["1"]["cavernas"])
        self.assertEqual(seeds["1"]["achados"]["structure #minecraft:village"]["x"], 10)
        self.assertFalse(seeds["2"]["mapa"])                                       # reprovada nao tem mapa
        self.assertEqual(seeds["2"]["achados"]["#minecraft:village"], {"dist": 900})   # so as distancias do CSV


class SeedsFileTests(unittest.TestCase):
    def test_bom_and_comments(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "seeds.txt"
            f.write_bytes("﻿12345\n# nota\n-42 # com nota\n\n".encode("utf-8"))
            old, sh.SEEDS_FILE = sh.SEEDS_FILE, f
            try:
                self.assertEqual(sh.load_seeds(0), ["12345", "-42"])
            finally:
                sh.SEEDS_FILE = old


if __name__ == "__main__":
    unittest.main()
