import sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import shcubiomes

HAS_DLL = shcubiomes.DLL.exists()
WORLD = ROOT / "worlds" / "seed_12345"


@unittest.skipUnless(HAS_DLL, "compile native/build.ps1 para gerar native/shbiomes.dll")
class CubiomesTests(unittest.TestCase):
    def test_deterministic_and_seed_sign(self):
        a, b = shcubiomes.World(12345), shcubiomes.World(12345)
        c = shcubiomes.World(-12345)                      # seed negativa: vira 64 bits sem sinal sem estourar
        pts = [(x, y, z) for x in (-300, 0, 400) for z in (-250, 90) for y in (60, 120)]
        self.assertEqual([a.biome_at(*p) for p in pts], [b.biome_at(*p) for p in pts])
        self.assertNotEqual([a.biome_at(*p) for p in pts], [c.biome_at(*p) for p in pts])

    def test_grid_and_surface_shapes(self):
        w = shcubiomes.World(12345)
        g = w.grid(-8, -8, 6, 4, y=16)
        self.assertEqual((len(g), len(g[0])), (4, 6))
        ys, ids = w.surface(-8, -8, 6, 4)
        self.assertEqual((len(ys), len(ys[0]), len(ids), len(ids[0])), (4, 6, 4, 6))

    @unittest.skipUnless(WORLD.exists(), "precisa do mundo worlds/seed_12345 (gerado pelo Paper)")
    def test_biomes_match_the_real_generated_world(self):
        """Verificacao contra o jogo real: ~99,9% das celulas 4x4 devem ser iguais (medido: 99,95% em 18 mundos)."""
        import terrain
        cells = terrain.sample_world(WORLD)
        w = shcubiomes.World(12345)
        items = list(cells.items())[::10]                 # 1 de cada 10 para ficar rapido
        same = sum(w.name(w.biome_at(gx, y >> 2, gz, scale=4)) == real.replace("minecraft:", "")
                   for (gx, gz), (y, real) in items)
        self.assertGreater(same / len(items), 0.995)


if __name__ == "__main__":
    unittest.main()
