import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import shcubiomes

HAS_DLL = shcubiomes.DLL.exists()


@unittest.skipUnless(HAS_DLL, "compile native/build.ps1 para gerar native/shbiomes.dll")
class TriagemTests(unittest.TestCase):
    def test_known_ring_seed_scores_and_locates(self):
        import triagem
        r = triagem.score_seed(12345, 96, -32)                 # a 12345 tem um anel nevado perto de (276, -152)
        self.assertGreaterEqual(r["score"], 0.5)
        self.assertGreaterEqual(r["neve"], 0.6)
        self.assertLess(abs(r["x"] - 276) + abs(r["z"] + 152), 200)

    def test_screen_orders_and_filters(self):
        import triagem
        seeds = [860371467496767965, 12345, 777]               # plana, anel, sem relevo marcante
        out = triagem.screen(0, 3, 0.0, workers=2, seeds=seeds, log=None)
        self.assertEqual(out[0]["seed"], 12345)                # o anel vem primeiro
        self.assertEqual([r["score"] for r in out], sorted((r["score"] for r in out), reverse=True))
        strict = triagem.screen(0, 3, 0.5, workers=2, seeds=seeds, log=None)
        self.assertEqual([r["seed"] for r in strict], [12345])  # so o anel passa do limiar
        self.assertEqual(len(triagem.screen(0, 1, 0.0, workers=2, seeds=seeds, log=None)), 1)   # respeita `keep`


if __name__ == "__main__":
    unittest.main()
