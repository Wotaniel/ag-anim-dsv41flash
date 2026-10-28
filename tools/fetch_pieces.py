#!/usr/bin/env python3
"""Экспорт кусков из Figma через REST.

REST-экспорт сплющивает группы, поэтому каждый кусок (персонаж, бейдж, заголовок,
подпись, каждый чип) экспортируется отдельным узлом. Координаты кусков берутся из
get_metadata (nodes?depth=) — это абсолютные координаты в канвасе; здесь они
пересчитываются в координаты кадра.

Результат: assets/<frame>/<piece>.svg + assets/meta.json
"""
import json
import re
import os
import time
import urllib.parse
import urllib.request

FILE_KEY = "HAd3I2CYWl0dzYKKN5cKiC"  # branch key (ветка файла ruxMmfjAvPDFzBXPeETeaC)
TOKEN = os.environ["FIGMA_API_KEY"]
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(HERE, "assets")

FRAMES = {
    "16x9": {
        "id": "3187:2995",
        "name": "AG-60517 · Event Card 16:9",
        "size": (1920, 1080),
        "pieces": [
            ("glow", "3187:2996", "Glow ellipse"),
            ("badge", "3187:2997", "Badge / Major Update"),
            ("title", "3187:2999", "AdGuard v5 is here"),
            ("subtitle", "3187:3000", "Reimagined. More powerful"),
            ("chip-ads", "3187:3003", "Chip / Clean Safari"),
            ("chip-trackers", "3187:3008", "Chip / Tracker protection"),
            ("chip-device", "3187:3015", "Chip / DNS privacy"),
            ("character", "3187:3022", "Agnar King (bust)"),
        ],
    },
    "9x16": {
        "id": "3187:3529",
        "name": "AG-60517 · Event Details 9:16",
        "size": (1080, 1920),
        "pieces": [
            ("glow", "3187:3530", "Glow ellipse"),
            ("badge", "3187:4163", "Badge / Major Update"),
            ("title", "3187:4165", "AdGuard v5 is here"),
            ("subtitle", "3187:4166", "Reimagined. More powerful"),
            ("chip-ads", "3187:4168", "Chip / Ad blocking"),
            ("chip-trackers", "3187:4173", "Chip / Tracker protection"),
            ("chip-device", "3187:4185", "Chip / Clean Safari"),
            ("character", "3187:3531", "Agnar King (full)"),
        ],
    },
}


def get(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"X-Figma-Token": TOKEN})
            return urllib.request.urlopen(req, timeout=120).read()
        except Exception as exc:  # noqa: BLE001
            if i == tries - 1:
                raise
            print(f"  retry {i + 1}: {exc}")
            time.sleep(20)


def node_index(node, out):
    out[node["id"]] = node
    for child in node.get("children", []):
        node_index(child, out)


def main():
    os.makedirs(ASSETS, exist_ok=True)
    meta = {"file": FILE_KEY, "frames": {}}
    for key, frame in FRAMES.items():
        print(f"== {key} {frame['name']}")
        url = (
            f"https://api.figma.com/v1/files/{FILE_KEY}/nodes"
            f"?ids={urllib.parse.quote(frame['id'])}&depth=6"
        )
        doc = json.loads(get(url))["nodes"][frame["id"]]["document"]
        index = {}
        node_index(doc, index)
        fb = doc["absoluteBoundingBox"]
        outdir = os.path.join(ASSETS, key)
        os.makedirs(outdir, exist_ok=True)
        fmeta = {"name": frame["name"], "node": frame["id"], "size": list(frame["size"]), "pieces": []}
        ids = [p[1] for p in frame["pieces"]]
        img_url = (
            f"https://api.figma.com/v1/images/{FILE_KEY}"
            f"?ids={urllib.parse.quote(','.join(ids))}&format=svg"
        )
        images = json.loads(get(img_url))["images"]
        for slug, nid, label in frame["pieces"]:
            node = index[nid]
            bb = node["absoluteBoundingBox"]
            rb = node.get("absoluteRenderBounds") or bb
            svg = get(images[nid]).decode("utf-8")
            path = os.path.join(outdir, slug + ".svg")
            with open(path, "w") as fh:
                fh.write(svg)
            # Figma экспортирует узел по его видимой области: для текста это ink-bbox
            # (absoluteRenderBounds), для групп/фигур — обычный bbox. Какой именно —
            # определяем по размеру viewBox экспортированного svg.
            m = re.match(r'<svg[^>]*width="([\d.]+)"[^>]*height="([\d.]+)"', svg)
            sw, sh = float(m.group(1)), float(m.group(2))
            use_render = abs(sw - rb["width"]) <= 2 and abs(sh - rb["height"]) <= 2
            src = rb if use_render else bb
            entry = {
                "slug": slug,
                "node": nid,
                "label": label,
                "x": round(src["x"] - fb["x"], 3),
                "y": round(src["y"] - fb["y"], 3),
                "w": round(sw, 3),
                "h": round(sh, 3),
                "bbox": [round(bb["x"] - fb["x"], 3), round(bb["y"] - fb["y"], 3),
                         round(bb["width"], 3), round(bb["height"], 3)],
                "render_bbox": [round(rb["x"] - fb["x"], 3), round(rb["y"] - fb["y"], 3),
                                round(rb["width"], 3), round(rb["height"], 3)],
                "origin": "render" if use_render else "bbox",
            }
            fmeta["pieces"].append(entry)
            print(f"  {slug:14s} {entry['w']:7.2f}x{entry['h']:7.2f} at {entry['x']:8.2f},{entry['y']:8.2f}")
        meta["frames"][key] = fmeta

    # полнокадровые экспорты — только для сверки при сборке
    ids = ",".join(f["id"] for f in FRAMES.values())
    images = json.loads(
        get(f"https://api.figma.com/v1/images/{FILE_KEY}?ids={urllib.parse.quote(ids)}&format=svg")
    )["images"]
    for key, frame in FRAMES.items():
        with open(os.path.join(ASSETS, key, "_frame.svg"), "w") as fh:
            fh.write(get(images[frame["id"]]).decode("utf-8"))
        meta["frames"][key]["frame_svg"] = "_frame.svg"

    with open(os.path.join(ASSETS, "meta.json"), "w") as fh:
        json.dump(meta, fh, indent=1, ensure_ascii=False)
    print("meta.json written")


if __name__ == "__main__":
    main()
