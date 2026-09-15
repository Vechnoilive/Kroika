#!/usr/bin/env python3
"""Generate 50 tiny, repository-owned garment diagrams and their seed labels."""

from __future__ import annotations

import json
from pathlib import Path
import struct
import zlib


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "evaluation" / "stage10"
WIDTH, HEIGHT = 96, 128


def _png(rows: list[bytearray]) -> bytes:
    raw = b"".join(b"\x00" + bytes(row) for row in rows)

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", WIDTH, HEIGHT, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def _diagram(index: int) -> bytes:
    rows = [bytearray([250, 247, 243] * WIDTH) for _ in range(HEIGHT)]
    fit_index = index % 3
    sleeves = index % 4
    garment = index % 5
    color = (83 + index % 4 * 25, 68 + index % 3 * 18, 105 + index % 5 * 16)

    def paint(y: int, left: int, right: int) -> None:
        if not 0 <= y < HEIGHT:
            return
        for x in range(max(0, left), min(WIDTH, right + 1)):
            offset = x * 3
            rows[y][offset:offset + 3] = bytes(color)

    # Bodice and deliberately visible fitted/semi-fitted/loose changes.
    if garment in {0, 1, 2}:
        max_taper = (5, 2, 0)[fit_index]
        for y in range(20, 68):
            taper = round((y - 20) / 47 * max_taper)
            paint(y, 31 + taper, 64 - taper)
        if sleeves:
            length = (9, 18, 30)[sleeves - 1]
            for step in range(length):
                paint(24 + step, 24 - step // 5, 31)
                paint(24 + step, 64, 71 + step // 5)

    if garment == 0:  # dress
        for y in range(68, 116):
            spread = (y - 68) // 4
            paint(y, 35 - spread, 60 + spread)
    elif garment in {1, 2}:  # blouse/top
        for y in range(68, 82):
            paint(y, 34, 61)
    elif garment == 3:  # skirt
        for y in range(50, 112):
            spread = (y - 50) // 4
            paint(y, 37 - spread, 58 + spread)
    else:  # trousers
        for y in range(68, 116):
            paint(y, 35, 45)
            paint(y, 51, 61)

    # White neckline marker: round versus V.
    for step in range(8):
        if index % 2:
            paint(20 + step, 45 + step // 2, 50 - step // 2)
        else:
            paint(20 + step, 43 - step // 3, 52 + step // 3)
    return _png(rows)


def build_dataset() -> dict:
    image_directory = DATASET / "images"
    image_directory.mkdir(parents=True, exist_ok=True)
    categories = ("dress", "blouse", "top", "skirt", "trousers")
    sleeve_values = ("sleeveless", "short", "elbow", "long")
    fit_values = ("fitted", "semi_fitted", "loose")
    cases = []
    for index in range(50):
        case_id = f"synthetic-{index + 1:02d}"
        image_path = image_directory / f"{case_id}.png"
        image_path.write_bytes(_diagram(index))
        category = categories[index % len(categories)]
        labels = {
            "garment_category": category,
            "silhouette.fit": fit_values[index % len(fit_values)],
            "neckline.front": "v" if index % 2 else "round",
            "sleeves.length": sleeve_values[index % len(sleeve_values)],
        }
        if category in {"dress", "skirt"}:
            labels["lower_part.type"] = "a_line"
        cases.append({
            "case_id": case_id,
            "image": f"images/{case_id}.png",
            "license": "CC0-1.0",
            "source": "generated-by-kroika",
            "annotation_status": "developer_seed",
            "labels": labels,
            "requires_question": index % 5 == 0,
        })
    manifest = {
        "dataset_id": "kroika-stage10-synthetic-v1",
        "purpose": "Adapter regression and A/B harness seed; not a substitute for real garments.",
        "case_count": len(cases),
        "eligible_for_default_selection": False,
        "cases": cases,
    }
    (DATASET / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


if __name__ == "__main__":
    result = build_dataset()
    print(f"Создано {result['case_count']} синтетических примеров этапа 10.")
