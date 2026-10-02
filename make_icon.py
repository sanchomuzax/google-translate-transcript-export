"""Az indító ikonjának (atirat.ico) előállítása csak stdlib-bel: kék alap, fehér lap, zöld letöltés-nyíl."""

import struct
import zlib
from pathlib import Path

N, SS = 256, 3  # méret, élsimítás (supersampling)


def rrect(x, y, x0, y0, x1, y1, r):
    if not (x0 <= x <= x1 and y0 <= y <= y1):
        return False
    cx = min(max(x, x0 + r), x1 - r)
    cy = min(max(y, y0 + r), y1 - r)
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def color_at(x, y):
    if (x - 190) ** 2 + (y - 190) ** 2 <= 54 ** 2:  # zöld kör nyíllal
        arrow = (178 <= x <= 202 and 152 <= y <= 196) or (
            196 <= y <= 222 and abs(x - 190) <= (222 - y) * 1.1)
        return (255, 255, 255, 255) if arrow else (26, 127, 55, 255)
    if rrect(x, y, 62, 40, 176, 210, 12):  # fehér lap szövegsorokkal
        for i, (ly, lw) in enumerate([(78, 84), (104, 84), (130, 84), (156, 60)]):
            if 82 <= x <= 82 + lw and ly <= y <= ly + 11:
                return (11, 87, 208, 255)
        return (255, 255, 255, 255)
    if rrect(x, y, 8, 8, 248, 248, 44):  # kék alap
        return (11, 87, 208, 255)
    return (0, 0, 0, 0)


def render():
    rows = []
    for py in range(N):
        row = bytearray([0])
        for px in range(N):
            acc = [0, 0, 0, 0]
            for sy in range(SS):
                for sx in range(SS):
                    c = color_at(px + (sx + 0.5) / SS, py + (sy + 0.5) / SS)
                    a = c[3]
                    for k in range(3):
                        acc[k] += c[k] * a
                    acc[3] += a
            n = SS * SS
            alpha = acc[3] / n
            rgb = [int(acc[k] / acc[3]) if acc[3] else 0 for k in range(3)]
            row += bytes(rgb + [int(alpha)])
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", N, N, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))
    # ICO konténer egyetlen 256x256-os PNG képpel (Windows Vista óta támogatott).
    header = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32, len(png), 6 + 16)
    return header + entry + png


if __name__ == "__main__":
    out = Path(__file__).resolve().parent / "atirat.ico"
    out.write_bytes(render())
    print(f"Ikon kész: {out}")
