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
