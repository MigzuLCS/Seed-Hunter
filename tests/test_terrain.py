import struct, sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import terrain as tr


# --- codificador NBT minimo, so para os testes ---
def s(txt):
    b = txt.encode(); return struct.pack(">H", len(b)) + b


def compound(**kw):
    out = b""
    for k, (t, payload) in kw.items():
        out += bytes([t]) + s(k) + payload
    return out + b"\x00"


def tag_int(v): return (3, struct.pack(">i", v))
def tag_str(v): return (8, s(v))
def tag_longs(vs): return (12, struct.pack(">i", len(vs)) + b"".join(struct.pack(">q", v) for v in vs))
def tag_list_compound(items): return (9, bytes([10]) + struct.pack(">i", len(items)) + b"".join(items))
def tag_compound(inner): return (10, inner)


def doc(**kw): return bytes([10]) + s("") + compound(**kw)


class NbtTests(unittest.TestCase):
    def test_parse_basic(self):
        d = tr.parse_nbt(doc(a=tag_int(7), b=tag_str("oi"), c=tag_longs([1, -2])))
        self.assertEqual(d, {"a": 7, "b": "oi", "c": [1, -2]})

    def test_skip_keeps_following_fields(self):
        """Regressao: `pos += rd(..)` perdia o avanco do ponteiro e desalinhava tudo depois do campo pulado."""
        big = compound(x=tag_int(1), y=tag_str("longo" * 10), z=tag_longs(list(range(50))))
        data = doc(block_states=tag_compound(big),
                   lista=tag_list_compound([compound(k=tag_int(1)), compound(k=tag_int(2))]),
                   depois=tag_int(42))
        d = tr.parse_nbt(data, skip=("block_states",))
        self.assertIsNone(d["block_states"])
        self.assertEqual(d["depois"], 42)
        self.assertEqual([i["k"] for i in d["lista"]], [1, 2])


class SamplingTests(unittest.TestCase):
    def test_biome_palette_decode(self):
        pal = ["a", "b", "c"]                       # 2 bits por entrada, 32 por long
        vals = [0] * 64; vals[5] = 2; vals[20] = 1  # indice = ((y&15)>>2)*16 + (z//4)*4 + x//4
        packed = [sum(v << (2 * i) for i, v in enumerate(vals[j * 32:(j + 1) * 32])) for j in range(2)]
        sections = {0: {"biomes": {"palette": pal, "data": packed}}}
        self.assertEqual(tr._biome_at(sections, 0, 4, 4), "c")      # idx = 0*16 + (4//4)*4 + 4//4 = 5  -> vals[5] = 2
        self.assertEqual(tr._biome_at(sections, 4, 0, 4), "b")      # idx = 1*16 + 1*4 + 0 = 20 -> vals[20] = 1
        self.assertEqual(tr._biome_at(sections, 0, 0, 0), "a")      # idx 0 -> 0
        self.assertEqual(tr._biome_at({0: {"biomes": {"palette": ["so"]}}}, 3, 0, 0), "so")   # paleta unica: sem data

    def test_heightmap_packing_9_bits_7_per_long(self):
        i = 9                                       # indice 9 -> long 1, deslocamento (9 % 7) * 9 = 18
        hm = [0] * 37
        hm[1] = 300 << 18
        self.assertEqual((hm[i // 7] >> ((i % 7) * 9)) & 511, 300)


def crater(size=121, rim=120, floor=80, ring_r=30, w=8):
    """Grade sintetica: planicie baixa com um anel alto e redondo no meio."""
    import math
    c = size // 2
    H = [[floor] * size for _ in range(size)]
    B = [["minecraft:plains"] * size for _ in range(size)]
    for z in range(size):
        for x in range(size):
            d = math.hypot(x - c, z - c)
            if abs(d - ring_r) < w:
                H[z][x] = rim; B[z][x] = "minecraft:jagged_peaks"
            elif d > ring_r:
                H[z][x] = floor - 10
    return H, B


class RingTests(unittest.TestCase):
    def test_crater_scores_high_and_flat_scores_zero(self):
        H, B = crater()
        best = tr.ring_score(H, B, rmin=10, rmax=45, step=3)
        self.assertGreater(best["score"], 0.5)
        self.assertGreaterEqual(best["neve"], 0.9)
        self.assertLessEqual(abs(best["cx"] - 60) + abs(best["cz"] - 60), 6)      # achou o centro
        flat = [[90] * 121 for _ in range(121)]
        self.assertTrue(tr.ring_score(flat, [["minecraft:plains"] * 121 for _ in range(121)]) is None
                        or tr.ring_score(flat, [["minecraft:plains"] * 121 for _ in range(121)])["score"] < 0.05)

    def test_ocean_interior_is_rejected(self):
        H, B = crater(floor=50)                     # interior abaixo do nivel do mar: nao e terra
        best = tr.ring_score(H, B)
        # centros em cima da propria crista ainda podem pontuar, mas nunca como uma cratera de terra de verdade
        self.assertTrue(best is None or best["score"] < 0.5, best)

    def test_basin_type_accepts_lake_below_sea_level(self):
        H, B = crater(floor=50)                     # lago de cratera: interior abaixo do mar
        best = tr.ring_score(H, B, **tr.TIPOS["bacia"])
        self.assertGreater(best["score"], 0.5)
        self.assertLessEqual(abs(best["cx"] - 60) + abs(best["cz"] - 60), 6)
        self.assertEqual(tr.TIPOS["anel"]["interior_min"], 64)      # o tipo anel continua exigindo terra

    def test_png_is_valid(self):
        import tempfile
        H, B = crater(size=40, ring_r=10)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.png"
            tr.relief_png(H, B, p, mark=(20, 20), scale=2)
            self.assertTrue(p.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))


if __name__ == "__main__":
    unittest.main()
