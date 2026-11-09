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

    def run_fake(self, statuses, render_results):
        import io, threading, time
        events, lock = [], threading.Lock()
        live = {"n": 0, "max": 0}

        def log_ev(*e):
            with lock:
                events.append((time.time(),) + e)

        def fake_prepare(seed, rules, radius, verbose, info=True):
            log_ev("prep_start", seed); time.sleep(0.2); log_ev("prep_end", seed)
            return statuses[seed], {}, {"x": 0, "y": 64, "z": 0}

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
        sh.prepare, sh.render, sh.save_seed = fake_prepare, fake_render, lambda *a, **k: None
        sh.build_index, sh.done_seeds = lambda: 0, lambda: set()
        buf = io.StringIO()
        try:
            sh.run_seeds(list(statuses), [], 480, False, False, 0, buf)
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
