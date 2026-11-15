"""Make the PWA's PNG icons: the lavender ground with a cream plus. Stdlib only (zlib + struct).

    python3 scripts/make_icons.py
"""

import struct
import zlib
from pathlib import Path

GROUND = (0x6A, 0x5F, 0xB3)   # tokens.json ground-top
DEEP = (0x58, 0x4C, 0x9E)     # ground-deep
CREAM = (0xFF, 0xFD, 0xF6)    # glyph
OUT = Path(__file__).resolve().parents[1] / "pwa" / "icons"


def chunk(kind: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + kind + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))


def png(width: int, height: int, pixel) -> bytes:
    rows = bytearray()
    for y in range(height):
        rows.append(0)  # filter: none
        for x in range(width):
            rows.extend(pixel(x, y))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit RGB
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(bytes(rows), 9)) + chunk(b"IEND", b""))


def icon(size: int, plus_frac: float) -> bytes:
    """A vertical lavender gradient with a centred cream plus (arm length = plus_frac of size)."""
    arm = size * plus_frac / 2
    bar = max(2.0, size * plus_frac / 5) / 2
    c = (size - 1) / 2

    def pixel(x: int, y: int) -> tuple[int, int, int]:
        dx, dy = abs(x - c), abs(y - c)
        if (dx <= bar and dy <= arm) or (dy <= bar and dx <= arm):
            return CREAM
        t = y / (size - 1)
        return tuple(round(a + (b - a) * t) for a, b in zip(GROUND, DEEP, strict=True))

    return png(size, size, pixel)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "icon-192.png").write_bytes(icon(192, 0.5))
    (OUT / "icon-512.png").write_bytes(icon(512, 0.5))
    (OUT / "maskable-512.png").write_bytes(icon(512, 0.36))  # inside the maskable safe zone
    print("wrote", ", ".join(p.name for p in sorted(OUT.glob("*.png"))))


if __name__ == "__main__":
    main()
