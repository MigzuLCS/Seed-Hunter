"""shcubiomes.py - biomas direto da seed, sem gerar chunks (cubiomes do fork xpple via native/shbiomes.dll).

Compile a DLL uma vez com native/build.ps1. So biblioteca padrao (ctypes).
"""
import ctypes
from pathlib import Path

DLL = Path(__file__).resolve().parent / "native" / "shbiomes.dll"
_lib = None


def _load():
    global _lib
    if _lib is None:
        if not DLL.exists():
            raise FileNotFoundError(f"{DLL} nao existe: rode native/build.ps1 (precisa de tools/cubiomes e do Visual Studio)")
        lib = ctypes.CDLL(str(DLL))
        lib.sh_mc_26_3.restype = ctypes.c_int
        lib.sh_new.restype, lib.sh_new.argtypes = ctypes.c_void_p, [ctypes.c_int, ctypes.c_ulonglong]
        lib.sh_free.restype, lib.sh_free.argtypes = None, [ctypes.c_void_p]
        lib.sh_biome_at.restype = ctypes.c_int
        lib.sh_biome_at.argtypes = [ctypes.c_void_p] + [ctypes.c_int] * 4
        lib.sh_biome_grid.restype = ctypes.c_int
        lib.sh_biome_grid.argtypes = [ctypes.c_void_p] + [ctypes.c_int] * 6 + [ctypes.POINTER(ctypes.c_int)]
        lib.sh_biome_name.restype, lib.sh_biome_name.argtypes = ctypes.c_char_p, [ctypes.c_int, ctypes.c_int]
        lib.sh_surface.restype = ctypes.c_int
        lib.sh_surface.argtypes = [ctypes.c_void_p] + [ctypes.c_int] * 4 + [ctypes.POINTER(ctypes.c_float), ctypes.POINTER(ctypes.c_int)]
        _lib = lib
    return _lib


class World:
    """Gerador de biomas de uma seed (overworld, Minecraft 26.3)."""

    def __init__(self, seed):
        self.lib = _load()
        self.mc = self.lib.sh_mc_26_3()
        self.seed = int(seed)
        self.g = self.lib.sh_new(self.mc, self.seed & 0xFFFFFFFFFFFFFFFF)   # seed com sinal -> 64 bits sem sinal
        if not self.g:
            raise MemoryError("sh_new falhou")
        self._names = {}

    def close(self):
        if self.g:
            self.lib.sh_free(self.g)
            self.g = None

    __del__ = close

    def name(self, biome_id):
        n = self._names.get(biome_id)
        if n is None:
            raw = self.lib.sh_biome_name(self.mc, biome_id)
            n = (raw.decode() if raw else f"id_{biome_id}").replace("minecraft:", "")
            self._names[biome_id] = n
        return n

    def biome_at(self, x, y, z, scale=1):
        """Bioma em (x, y, z). scale 1 = blocos; 4 = celulas de bioma (bloco >> 2, y tambem)."""
        return self.lib.sh_biome_at(self.g, scale, x, y, z)

    def surface(self, x0, z0, w, h):
        """Estimativa da altura da superficie e bioma da superficie num retangulo de w x h celulas de 4 blocos
        (x0, z0 em celulas = bloco >> 2). Devolve (alturas, ids): listas de h linhas com w valores.
        A altura e relativa (parametro de profundidade do clima): calibre antes de comparar com blocos."""
        ys = (ctypes.c_float * (w * h))()
        ids = (ctypes.c_int * (w * h))()
        rc = self.lib.sh_surface(self.g, x0, z0, w, h, ys, ids)
        if rc != 0:
            raise RuntimeError(f"mapApproxHeight falhou ({rc})")
        return ([list(ys[r * w:(r + 1) * w]) for r in range(h)], [list(ids[r * w:(r + 1) * w]) for r in range(h)])

    def grid(self, x0, z0, w, h, y=100, scale=4):
        """IDs de bioma num plano (w x h celulas de `scale` blocos, a partir de x0,z0 em celulas) na altura y.
        Devolve uma lista de h linhas com w IDs."""
        buf = (ctypes.c_int * (w * h))()
        rc = self.lib.sh_biome_grid(self.g, scale, x0, z0, w, h, y, buf)
        if rc != 0:
            raise RuntimeError(f"genBiomes falhou ({rc})")
        return [list(buf[r * w:(r + 1) * w]) for r in range(h)]
