#!/usr/bin/env python3
"""Сборка .keyshape-проектов и браузерного превью из кусков Figma.

Единственный источник истины — спеки ниже (ключи в СЕКУНДАХ). Из них генерируются:
  * AG-60517 Event Card 16x9.keyshape    — проект для Keyshape (zip + document.keyshapex)
  * AG-60517 Event Details 9x16.keyshape
  * preview/animation-data.js            — те же слои/ключи для браузерного плеера

Формат Keyshape (keyshapeapp.com/file-format):
  * abs-key-times — СЕКУНДЫ, ks:playRangeIn/Out — МИЛЛИСЕКУНДЫ;
  * timing-functions — на 1 меньше числа ключей;
  * animateMotion.path — абсолютный, в координатах родителя, начинается в позиции объекта;
  * scale/rotate крутятся вокруг пивота группы (позиция группы = пивот, контент
    нарисован со сдвигом -пивот).
"""
import json
import math
import os
import re
import zipfile

LOOP = 10.0
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(HERE, "assets")
PREVIEW = os.path.join(HERE, "preview")

EASE = {
    "linear": (0.0, 0.0, 1.0, 1.0),
    "in-out": (0.42, 0.0, 0.58, 1.0),
    "out": (0.16, 0.84, 0.28, 1.0),
    "in": (0.5, 0.0, 0.75, 0.2),
    "gentle": (0.4, 0.0, 0.2, 1.0),
}

KS_NS = 'xmlns="http://www.w3.org/2000/svg" xmlns:ks="http://ns.keyshapeapp.com"'
MARKERS = [
    ("Push-in", 0.0, "blue"), ("Hold", 2.6, "gray"), ("Push 2", 4.2, "blue"),
    ("Hold 2", 6.0, "gray"), ("Pull back", 7.0, "green"), ("Loop", 10.0, "cyan"),
]


# ---------------------------------------------------------------- helpers


def fnum(v):
    s = ("%.4f" % v).rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def tf_css(e):
    return "cubic-bezier(%s)" % ",".join(fnum(v) for v in e)


def piece_body(frame, slug):
    """Внутренности svg-куска; id префиксуются, чтобы куски не конфликтовали."""
    svg = open(os.path.join(ASSETS, frame, slug + ".svg")).read()
    m = re.search(r"<svg[^>]*?>(.*)</svg>\s*$", svg, re.S)
    return prefix_ids(m.group(1).strip(), "p%s%s-" % (frame, slug.replace("-", "")))


def prefix_ids(markup, prefix):
    ids = set(re.findall(r'\bid="([^"]+)"', markup))
    for i in sorted(ids, key=len, reverse=True):
        markup = markup.replace('id="%s"' % i, 'id="%s%s"' % (prefix, i))
        markup = markup.replace("url(#%s)" % i, "url(#%s%s)" % (prefix, i))
    return markup


def meta():
    return json.load(open(os.path.join(ASSETS, "meta.json")))


# ---------------------------------------------------------------- channels


def _ch(kind, keys, ease):
    seg = [ease] * (len(keys) - 1) if isinstance(ease, str) else list(ease)
    assert len(seg) == len(keys) - 1, (kind, len(keys), len(seg))
    return {"kind": kind, "keys": keys, "ease": [EASE[e] if isinstance(e, str) else e for e in seg]}


def motion(keys, ease):
    return _ch("motion", keys, ease)


def scale(keys, ease):
    return _ch("scale", keys, ease)


def opacity(keys, ease):
    return _ch("opacity", keys, ease)


def rotate(keys, ease):
    return _ch("rotate", keys, ease)


# ---------------------------------------------------------------- layers


class Layer:
    def __init__(self, lid, markup, pivot=None, channels=(), collapsed=False, indent=0, extra=""):
        self.id = lid
        self.extra = extra
        self.markup = markup
        self.pivot = pivot
        self.channels = list(channels)
        self.collapsed = collapsed
        self.indent = indent

    def _body(self, ind):
        pad = " " * ind
        lines = self.markup.splitlines()
        return "\n".join(pad + ln for ln in lines)

    def ks(self, ind):
        p = " " * ind
        extra = ' ks:expand-timeline="collapsed"' if self.collapsed else ""
        if self.pivot is None:  # статичный слой: только позиция
            x, y = self.indent
            return '%s<g id="%s"%s%s transform="translate(%s,%s)">\n%s\n%s</g>' % (
                p, self.id, extra, self.extra, fnum(x), fnum(y), self._body(ind + 4), p)
        px, py = self.pivot
        out = ['%s<g id="%s"%s%s transform="translate(%s,%s)">'
               % (p, self.id, extra, self.extra, fnum(px), fnum(py))]
        for c in self.channels:
            out.append(p + "    " + self._ks_channel(c))
        out.append(p + '    <g transform="translate(%s,%s)">' % (fnum(-px), fnum(-py)))
        out.append(self._body(ind + 8))
        out.append(p + "    </g>")
        out.append(p + "</g>")
        return "\n".join(out)

    def _ks_channel(self, c):
        kt = ";".join(fnum(k[0]) for k in c["keys"])
        tf = ";".join(tf_css(e) for e in c["ease"])
        if c["kind"] == "motion":
            path = "M" + "L".join("%s,%s" % (fnum(x), fnum(y)) for _t, (x, y) in c["keys"])
            return ('<ks:animateMotion abs-key-times="%s" path="%s" timing-functions="%s" '
                    'repeat-end="indefinite"/>' % (kt, path, tf))
        if c["kind"] == "scale":
            vals = ";".join("%s,%s" % (fnum(sx), fnum(sy)) for _t, (sx, sy) in c["keys"])
            return ('<ks:animate attribute="transform" type="scale" abs-key-times="%s" values="%s" '
                    'timing-functions="%s" repeat-end="indefinite"/>' % (kt, vals, tf))
        if c["kind"] == "rotate":
            vals = ";".join(fnum(v) for _t, v in c["keys"])
            return ('<ks:animate attribute="transform" type="rotate" abs-key-times="%s" values="%s" '
                    'timing-functions="%s" repeat-end="indefinite"/>' % (kt, vals, tf))
        if c["kind"] == "opacity":
            vals = ";".join(fnum(v) for _t, v in c["keys"])
            return ('<ks:animate attribute="opacity" abs-key-times="%s" values="%s" '
                    'timing-functions="%s" repeat-end="indefinite"/>' % (kt, vals, tf))
        raise ValueError(c["kind"])

    def js(self, prefix):
        return {
            "id": prefix + self.id,
            "pivot": list(self.pivot) if self.pivot else [0, 0],
            "static": self.pivot is None,
            "channels": [
                {"kind": c["kind"],
                 "keys": [[t, (list(v) if isinstance(v, (tuple, list)) else v)] for t, v in c["keys"]],
                 "ease": c["ease"]}
                for c in self.channels
            ],
        }


# ---------------------------------------------------------------- glow / glints

GLOW_R = 1900.0
GLOW_A = 0.480
GLOW_S = 725.0
GLOW_P = 2.05


def glow_profile():
    """Профиль вместо figma-блюра (Keyshape не умеет <filter>).

    Подобрано по рендеру Figma: alpha(d) = 0.48 * exp(-(d/725)^2.05).
    """
    out = []
    for d in (0, 95, 190, 285, 380, 475, 570, 665, 760, 855, 950, 1045,
              1140, 1235, 1330, 1520, 1710, 1900):
        out.append((d / GLOW_R, round(max(GLOW_A * math.exp(-((d / GLOW_S) ** GLOW_P)), 0.0), 4)))
    return out


def defs_block(prefix):
    s = ['<radialGradient id="%sglowGrad" cx="0.5" cy="0.5" r="0.5">' % prefix]
    for off, a in glow_profile():
        s.append('    <stop offset="%s" stop-color="#67B279" stop-opacity="%s"/>' % (fnum(off), fnum(a)))
    s.append("</radialGradient>")
    s.append('<radialGradient id="%sglintHalo" cx="0.5" cy="0.5" r="0.5">' % prefix)
    s.append('    <stop offset="0" stop-color="#ffffff" stop-opacity="0.55"/>')
    s.append('    <stop offset="0.45" stop-color="#ffffff" stop-opacity="0.16"/>')
    s.append('    <stop offset="1" stop-color="#ffffff" stop-opacity="0"/>')
    s.append("</radialGradient>")
    return "\n".join(s)


def star(cx, cy, r, k=0.13):
    def p(dx, dy):
        return "%s,%s" % (fnum(cx + dx), fnum(cy + dy))
    return ("M%sC%s %s %sC%s %s %sC%s %s %sC%s %s %sZ" % (
        p(0, -r),
        p(r * k, -r * k), p(r * k, -r * k), p(r, 0),
        p(r * k, r * k), p(r * k, r * k), p(0, r),
        p(-r * k, r * k), p(-r * k, r * k), p(-r, 0),
        p(-r * k, -r * k), p(-r * k, -r * k), p(0, -r),
    ))


def glint(lid, prefix, center, halo, star_r, move, opa, scl):
    if move:  # pivot = первая точка пути (иначе блик «прыгнет» на старте)
        center = move[0][0][1]
    cx, cy = center
    markup = ('<ellipse cx="%s" cy="%s" rx="%s" ry="%s" fill="url(#%sglintHalo)"/>\n'
              '<path d="%s" fill="#ffffff" opacity="0.92"/>'
              % (fnum(cx), fnum(cy), fnum(halo[0]), fnum(halo[1]), prefix, star(cx, cy, star_r)))
    chans = []
    if move:
        chans.append(motion(move[0], move[1]))
    if scl:
        chans.append(scale(scl[0], scl[1]))
    chans.append(opacity(opa[0], opa[1]))
    return Layer(lid, markup, center, chans)


def glow_layer(prefix, gx, gy):
    return Layer(
        "Glow", '<circle cx="%s" cy="%s" r="%s" fill="url(#%sglowGrad)"/>'
        % (fnum(gx), fnum(gy), fnum(GLOW_R), prefix),
        (gx, gy),
        [opacity([(0.0, 0.94), (2.0, 1.0), (5.0, 0.94), (7.0, 1.0), (LOOP, 0.94)], "in-out"),
         scale([(0.0, (1.0, 1.0)), (2.0, (1.02, 1.02)), (5.0, (1.0, 1.0)),
                (7.0, (1.02, 1.02)), (LOOP, (1.0, 1.0))], "in-out")])


def character_layer(frame, by, prefix, pivot, sx, sy):
    c = by["character"]
    body = ['<g transform="translate(%s,%s)" fill="none">' % (fnum(c["x"]), fnum(c["y"]))]
    body += ["  " + ln for ln in piece_body(frame, "character").splitlines()]
    body.append("</g>")
    return Layer("Character", "\n".join(body), pivot,
                 [scale([(0.0, (1.0, 1.0)), (2.0, (sx, sy)), (5.0, (1.0, 1.0)),
                         (7.0, (sx, sy)), (LOOP, (1.0, 1.0))], "in-out")],
                 collapsed=True)


def ui_layers(frame, by):
    out = []
    for slug, lid in (("badge", "Badge"), ("title", "Title"), ("subtitle", "Subtitle"),
                      ("chip-ads", "Chip-ads"), ("chip-trackers", "Chip-trackers"),
                      ("chip-device", "Chip-device")):
        p = by[slug]
        out.append(Layer(lid, piece_body(frame, slug), None, (), indent=(p["x"], p["y"]),
                         extra=' fill="none"'))
    return out


# ---------------------------------------------------------------- specs


def spec_16x9(m, prefix):
    W, H = 1920, 1080
    by = {p["slug"]: p for p in m["frames"]["16x9"]["pieces"]}
    cx, cy = W / 2, H / 2
    camera = Layer("Camera", "", (cx, cy), [
        motion([(0.0, (cx, cy)), (2.6, (cx + 12, cy + 4)), (4.2, (cx + 12, cy + 4)),
                (6.0, (cx + 26, cy + 8)), (7.0, (cx + 26, cy + 8)), (LOOP, (cx, cy))],
               ["gentle", "linear", "gentle", "linear", "gentle"]),
        scale([(0.0, (1.0, 1.0)), (2.6, (1.026, 1.026)), (4.2, (1.026, 1.026)),
               (6.0, (1.052, 1.052)), (7.0, (1.052, 1.052)), (LOOP, (1.0, 1.0))],
              ["gentle", "linear", "gentle", "linear", "gentle"]),
    ])
    crown = glint(
        "Glint-crown", prefix, (1507.0, 138.0), (95.0, 62.0), 26.0,
        ([(0.0, (1507.0, 138.0)), (2.85, (1507.0, 138.0)), (3.9, (1583.0, 166.0)),
          (LOOP, (1507.0, 138.0))], ["linear", "in-out", "gentle"]),
        ([(0.0, 0.0), (2.85, 0.0), (3.15, 1.0), (3.55, 1.0), (4.05, 0.0), (LOOP, 0.0)],
         ["linear", "out", "linear", "in", "linear"]),
        ([(0.0, (0.8, 0.8)), (2.85, (0.8, 0.8)), (3.2, (1.06, 1.06)), (3.9, (1.0, 1.0)),
          (LOOP, (0.8, 0.8))], ["linear", "out", "in-out", "gentle"]))
    sword = glint(
        "Glint-sword", prefix, (1533.0, 664.0), (78.0, 40.0), 22.0,
        ([(0.0, (1533.0, 664.0)), (7.15, (1533.0, 664.0)), (7.6, (1548.0, 676.0)),
          (LOOP, (1533.0, 664.0))], ["linear", "out", "gentle"]),
        ([(0.0, 0.0), (7.15, 0.0), (7.45, 1.0), (7.85, 0.0), (LOOP, 0.0)],
         ["linear", "out", "in", "linear"]),
        ([(0.0, (0.85, 0.85)), (7.15, (0.85, 0.85)), (7.45, (1.08, 1.08)), (7.85, (0.9, 0.9)),
          (LOOP, (0.85, 0.85))], ["linear", "out", "in", "gentle"]))
    return {
        "key": "16x9", "size": (W, H), "title": "AdGuard v5 — Event Card 16:9",
        "export": "ag-60517-event-card-16x9.svg", "prefix": prefix,
        "layers": [camera, glow_layer(prefix, 1530.0, 671.0),
                   character_layer("16x9", by, prefix, (1520.0, 1080.0), 1.0040, 1.0090),
                   crown, sword] + ui_layers("16x9", by),
    }


def spec_9x16(m, prefix):
    W, H = 1080, 1920
    by = {p["slug"]: p for p in m["frames"]["9x16"]["pieces"]}
    cx, cy = W / 2, H / 2
    camera = Layer("Camera", "", (cx, cy), [
        motion([(0.0, (cx, cy)), (2.6, (cx + 5, cy + 2)), (4.2, (cx + 5, cy + 2)),
                (6.0, (cx + 10, cy + 4)), (7.0, (cx + 10, cy + 4)), (LOOP, (cx, cy))],
               ["gentle", "linear", "gentle", "linear", "gentle"]),
        scale([(0.0, (1.0, 1.0)), (2.6, (1.020, 1.020)), (4.2, (1.020, 1.020)),
               (6.0, (1.042, 1.042)), (7.0, (1.042, 1.042)), (LOOP, (1.0, 1.0))],
              ["gentle", "linear", "gentle", "linear", "gentle"]),
    ])
    crown = glint(
        "Glint-crown", prefix, (664.0, 518.0), (62.0, 42.0), 17.0,
        ([(0.0, (664.0, 518.0)), (2.75, (664.0, 518.0)), (3.75, (724.0, 540.0)),
          (LOOP, (664.0, 518.0))], ["linear", "in-out", "gentle"]),
        ([(0.0, 0.0), (2.75, 0.0), (3.05, 1.0), (3.45, 1.0), (3.95, 0.0), (LOOP, 0.0)],
         ["linear", "out", "linear", "in", "linear"]),
        ([(0.0, (0.8, 0.8)), (2.75, (0.8, 0.8)), (3.1, (1.06, 1.06)), (3.75, (1.0, 1.0)),
          (LOOP, (0.8, 0.8))], ["linear", "out", "in-out", "gentle"]))
    sword = glint(
        "Glint-sword", prefix, (700.0, 1130.0), (34.0, 120.0), 16.0,
        ([(0.0, (700.0, 1110.0)), (6.15, (700.0, 1110.0)), (7.35, (700.0, 1450.0)),
          (LOOP, (700.0, 1110.0))], ["linear", "in-out", "gentle"]),
        ([(0.0, 0.0), (6.15, 0.0), (6.5, 0.95), (6.95, 0.95), (7.35, 0.0), (LOOP, 0.0)],
         ["linear", "out", "linear", "in", "linear"]),
        ([(0.0, (0.9, 0.9)), (6.15, (0.9, 0.9)), (6.5, (1.05, 1.05)), (7.35, (1.0, 1.0)),
          (LOOP, (0.9, 0.9))], ["linear", "out", "in-out", "gentle"]))
    return {
        "key": "9x16", "size": (W, H), "title": "AdGuard v5 — Event Details 9:16",
        "export": "ag-60517-event-details-9x16.svg", "prefix": prefix,
        "layers": [camera, glow_layer(prefix, 1210.0, 1001.0),
                   character_layer("9x16", by, prefix, (683.0, 1900.0), 1.0040, 1.0090),
                   crown, sword] + ui_layers("9x16", by),
    }


# ---------------------------------------------------------------- emit


def build_keyshape(spec, path):
    W, H = spec["size"]
    prefix = spec["prefix"]
    out = ['<?xml version="1.0" encoding="UTF-8" standalone="no"?>',
           "<!-- Created with Keyshape -->",
           '<svg %s viewBox="0 0 %d %d" ks:preview="svg/css" ks:fps="60" ks:playRangeIn="0" '
           'ks:playRangeOut="%d" ks:version="1.1" style="white-space: pre;">'
           % (KS_NS, W, H, int(LOOP * 1000)),
           "    <title>%s</title>" % spec["title"],
           '    <ks:export filename="%s" format="svg" animation="css" loop-count="0"/>'
           % spec["export"]]
    for name, t, color in MARKERS:
        out.append('    <ks:timemarker name="%s" time="%s" color="%s"/>' % (name, fnum(t), color))
    out.append("    <defs>")
    out.append("\n".join("        " + ln for ln in defs_block(prefix).splitlines()))
    out.append('        <clipPath id="%sksclip"><rect width="%d" height="%d"/></clipPath>'
               % (prefix, W, H))
    out.append("    </defs>")
    out.append('    <rect width="%d" height="%d" fill="#000000"/>' % (W, H))
    out.append('    <g clip-path="url(#%sksclip)">' % prefix)
    for layer in spec["layers"]:
        out.append(layer.ks(8))
    out.append("    </g>")
    out.append("</svg>")
    doc = "\n".join(out) + "\n"
    tmp = path + ".keyshapex"
    with open(tmp, "w") as fh:
        fh.write(doc)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("document.keyshapex", doc)
    os.remove(tmp)
    return doc


def build_preview_svg(spec):
    W, H = spec["size"]
    prefix = spec["prefix"]
    out = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d">' % (W, H),
           "  <defs>",
           "\n".join("    " + ln for ln in defs_block(prefix).splitlines()),
           '    <clipPath id="%sksclip"><rect width="%d" height="%d"/></clipPath>' % (prefix, W, H),
           "  </defs>",
           '  <rect width="%d" height="%d" fill="#000000"/>' % (W, H),
           '  <g clip-path="url(#%sksclip)">' % prefix]
    for layer in spec["layers"]:
        if layer.pivot is None:
            x, y = layer.indent
            out.append('    <g id="%s%s"%s transform="translate(%s,%s)">'
                       % (prefix, layer.id, layer.extra, fnum(x), fnum(y)))
            out.append("\n".join("      " + ln for ln in layer.markup.splitlines()))
            out.append("    </g>")
        else:
            px, py = layer.pivot
            out.append('    <g id="%s%s" transform="translate(%s,%s)">'
                       % (prefix, layer.id, fnum(px), fnum(py)))
            out.append('      <g transform="translate(%s,%s)">' % (fnum(-px), fnum(-py)))
            out.append("\n".join("        " + ln for ln in layer.markup.splitlines()))
            out.append("      </g>")
            out.append("    </g>")
    out.append("  </g>")
    out.append("</svg>")
    return "\n".join(out)


def main():
    m = meta()
    os.makedirs(PREVIEW, exist_ok=True)
    data = {"loop": LOOP, "frames": []}
    for spec, fname in (
        (spec_16x9(m, "f169-"), "AG-60517 Event Card 16x9.keyshape"),
        (spec_9x16(m, "f916-"), "AG-60517 Event Details 9x16.keyshape"),
    ):
        doc = build_keyshape(spec, os.path.join(HERE, fname))
        data["frames"].append({
            "key": spec["key"], "title": spec["title"],
            "w": spec["size"][0], "h": spec["size"][1],
            "svg": build_preview_svg(spec),
            "layers": [layer.js(spec["prefix"]) for layer in spec["layers"]],
        })
        print("%-42s %7.1f KB" % (fname, len(doc) / 1024))
    path = os.path.join(PREVIEW, "animation-data.js")
    with open(path, "w") as fh:
        fh.write("window.ANIM = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n")
    print("%-42s %7.1f KB" % ("preview/animation-data.js", os.path.getsize(path) / 1024))


if __name__ == "__main__":
    main()
