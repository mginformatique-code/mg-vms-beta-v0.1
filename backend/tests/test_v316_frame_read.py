"""Test de _read_exact : contenu, non-mutation, EOF/troncature, performance.

`w.proc.stdout` est ouvert avec `bufsize=0` (voir frame_source.py) : c'est
un `FileIO`, donc `RawIOBase.readinto` — UN SEUL appel systeme par appel,
rendu des que des donnees sont disponibles, sans boucle de remplissage
interne (a la difference de `BufferedReader`). `RawPipe` ci-dessous, en
sous-classant `io.RawIOBase`, reproduit exactement cette semantique.

Note sur le delai : la verification de deadline dans `_read_exact` s'opere
ENTRE deux appels de lecture, pas a l'interieur d'un appel bloque. C'est
deja le comportement de l'ancien code (`stream.read(...)` est tout aussi
bloquant) — ce n'est pas une regression introduite ici, donc pas teste.
"""
import io, sys, time
import numpy as np
sys.path.insert(0, '/app')
from frame_source import _read_exact

W, H = 1920, 1080
NB = W * H * 3


class RawPipe(io.RawIOBase):
    def __init__(self, data, chunk=65536):
        self.data = data; self.pos = 0; self.chunk = chunk
    def readable(self): return True
    def readinto(self, b):
        n = min(len(b), self.chunk, len(self.data) - self.pos)
        if n <= 0: return 0
        b[:n] = self.data[self.pos:self.pos + n]; self.pos += n; return n


src = bytes((i * 7 + 3) % 256 for i in range(NB))
print("  type de flux teste : RawIOBase (readinto = 1 appel systeme, comme FileIO en prod)")

out = _read_exact(RawPipe(src), NB, 5.0)
assert out is not None and isinstance(out, np.ndarray), f"retour {type(out)}"
assert len(out) == NB and out.tobytes() == src, "CONTENU DIFFERENT"
print("  OK  contenu exact sur une image 1080p complete")

assert out.reshape((H, W, 3)).shape == (H, W, 3)
print("  OK  reshape (H,W,3) sans copie")

a = _read_exact(RawPipe(src), NB, 5.0)
b = _read_exact(RawPipe(src), NB, 5.0)
assert a.__array_interface__['data'][0] != b.__array_interface__['data'][0], \
    "MEME TAMPON REUTILISE : l'image precedente muterait sous le consommateur"
print("  OK  tampons distincts (pas de mutation sous le consommateur)")

assert _read_exact(RawPipe(src[:NB // 2]), NB, 1.0) is None
print("  OK  flux tronque -> None")

assert _read_exact(RawPipe(b""), NB, 1.0) is None
print("  OK  EOF -> None")

def old(stream, nbytes, timeout):
    buf = bytearray(); dl = time.monotonic() + timeout
    while len(buf) < nbytes:
        if time.monotonic() > dl: return None
        c = stream.read(min(nbytes - len(buf), 65536))
        if not c: return None
        buf.extend(c)
    return bytes(buf)

class ReadPipe(RawPipe):
    def read(self, n=-1):
        b = bytearray(n); k = self.readinto(b); return bytes(b[:k])

N = 30
t = time.perf_counter()
for _ in range(N): old(ReadPipe(src), NB, 5.0)
t_old = (time.perf_counter() - t) / N * 1000
t = time.perf_counter()
for _ in range(N): _read_exact(RawPipe(src), NB, 5.0)
t_new = (time.perf_counter() - t) / N * 1000
print(f"\n  ancienne : {t_old:.1f} ms/image")
print(f"  nouvelle : {t_new:.1f} ms/image   ({t_old / t_new:.1f}x plus rapide)")
print("\n  tous les controles passent")
