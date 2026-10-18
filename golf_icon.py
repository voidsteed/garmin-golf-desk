"""Small locally generated app icon; no downloaded artwork or dependencies."""

import base64
import struct
import zlib
from pathlib import Path


def icon_png() -> bytes:
    rows = []
    for y in range(64):
        row = bytearray()
        for x in range(64):
            color = (17, 52, 41, 255) if (x-31.5)**2 + (y-31.5)**2 < 31**2 else (0, 0, 0, 0)
            if ((x-31)**2/22**2 + (y-48)**2/7**2 < 1):
                color = (81, 185, 132, 255)
            if 26 <= x <= 28 and 13 <= y <= 48:
                color = (255, 255, 255, 255)
            if 29 <= x <= 48 and 14 <= y <= 27 and y < 14 + (49-x)*0.7:
                color = (236, 247, 230, 255)
            row.extend(color)
        rows.append(b"\x00" + row)
    def chunk(name, payload):
        return struct.pack(">I", len(payload)) + name + payload + struct.pack(">I", zlib.crc32(name + payload) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 64, 64, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b"")


def tk_icon_data() -> str:
    return base64.b64encode(icon_png()).decode("ascii")


def write_ico(path: Path) -> Path:
    png = icon_png()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack("<HHH", 0, 1, 1) + struct.pack("<BBBBHHII", 64, 64, 0, 0, 1, 32, len(png), 22) + png)
    return path
