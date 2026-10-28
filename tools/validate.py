#!/usr/bin/env python3
"""Проверка .keyshape перед сдачей: zip, XML, ключи, тайминги, ссылки."""
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

KS = "{http://ns.keyshapeapp.com}"
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOOP = 10.0


def check(path):
    errs = []
    if not zipfile.is_zipfile(path):
        return ["не zip: " + path]
    with zipfile.ZipFile(path) as z:
        bad = z.testzip()
        if bad:
            errs.append("битый файл в архиве: %s" % bad)
        names = z.namelist()
        if names != ["document.keyshapex"]:
            errs.append("ожидался один document.keyshapex, есть %s" % names)
        doc = z.read("document.keyshapex").decode("utf-8")
    try:
        root = ET.fromstring(doc)
    except ET.ParseError as exc:
        return errs + ["XML не парсится: %s" % exc]

    if root.get(KS + "playRangeOut") != str(int(LOOP * 1000)):
        errs.append("playRangeOut=%s, ожидалось %d (мс)" % (root.get(KS + "playRangeOut"), int(LOOP * 1000)))

    # ключи
    anims = [e for e in root.iter() if e.tag in (KS + "animate", KS + "animateMotion")]
    for a in anims:
        owner = None
        kt = a.get("abs-key-times") or ""
        tf = a.get("timing-functions") or ""
        try:
            times = [float(x) for x in kt.split(";")]
        except ValueError:
            errs.append("abs-key-times не числа: %r" % kt)
            continue
        n_tf = len([x for x in tf.split(";") if x.strip()])
        if n_tf != len(times) - 1:
            errs.append("%s: timing-functions=%d, ключей=%d (нужно %d)"
                        % (a.get("attribute") or "motion", n_tf, len(times), len(times) - 1))
        if any(b <= a0 for a0, b in zip(times, times[1:])):
            errs.append("abs-key-times не возрастают: %s" % kt)
        if abs(times[0]) > 1e-9:
            errs.append("первый ключ не 0: %s" % kt)
        if abs(times[-1] - LOOP) > 1e-6:
            errs.append("последний ключ %s != длины лупа %s" % (times[-1], LOOP))
        if a.get("repeat-end") != "indefinite":
            errs.append("repeat-end=%r" % a.get("repeat-end"))
        if a.tag == KS + "animateMotion":
            p = a.get("path") or ""
            if not p.startswith("M") or "C" in p and "L" not in p:
                errs.append("path не M/L: %r" % p[:40])
            pts = re.findall(r"(-?[\d.]+),(-?[\d.]+)", p)
            if len(pts) != len(times):
                errs.append("точек в path=%d, ключей=%d" % (len(pts), len(times)))
        else:
            vals = (a.get("values") or "").split(";")
            if len(vals) != len(times):
                errs.append("%s: values=%d, ключей=%d"
                            % (a.get("attribute"), len(vals), len(times)))
            if a.get("attribute") == "transform" and a.get("type") not in ("scale", "rotate", "skewXY", "anchor"):
                errs.append("неизвестный type=%r" % a.get("type"))
    if not anims:
        errs.append("нет ни одной анимации")

    # path[0] должен совпадать с translate группы (иначе объект «прыгает» на старте)
    SVG = "{http://www.w3.org/2000/svg}"
    for g in root.iter(SVG + "g"):
        motion = g.find(KS + "animateMotion")
        if motion is None:
            continue
        tr = g.get("transform") or ""
        m = re.match(r"translate\(\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*\)", tr)
        if not m:
            errs.append("слой %s: нет translate при animateMotion" % g.get("id"))
            continue
        pts = re.findall(r"(-?[\d.]+),(-?[\d.]+)", motion.get("path") or "")
        if pts and (abs(float(pts[0][0]) - float(m.group(1))) > 0.01
                    or abs(float(pts[0][1]) - float(m.group(2))) > 0.01):
            errs.append("слой %s: path начинается в %s, а translate=%s"
                        % (g.get("id"), pts[0], (m.group(1), m.group(2))))

    # луп бесшовный: первое и последнее значение канала совпадают
    for a in anims:
        if a.tag == KS + "animateMotion":
            pts = re.findall(r"(-?[\d.]+),(-?[\d.]+)", a.get("path") or "")
            if len(pts) > 1 and pts[0] != pts[-1]:
                errs.append("motion не замыкается: %s -> %s" % (pts[0], pts[-1]))
        else:
            vals = (a.get("values") or "").split(";")
            if len(vals) > 1 and vals[0] != vals[-1]:
                errs.append("%s не замыкается: %s -> %s"
                            % (a.get("attribute"), vals[0], vals[-1]))

    # ссылки url(#...)
    ids = {e.get("id") for e in root.iter() if e.get("id")}
    for ref in set(re.findall(r"url\(#([^)]+)\)", doc)):
        if ref not in ids:
            errs.append("ссылка url(#%s) не резолвится" % ref)

    # неподдерживаемые Keyshape вещи
    for tag in ("filter", "feGaussianBlur", "foreignObject"):
        if "<%s" % tag in doc:
            errs.append("неподдерживаемый элемент <%s>" % tag)

    # человеческие имена слоёв верхнего уровня
    clip = [e for e in root.iter("{http://www.w3.org/2000/svg}g") if e.get("clip-path")]
    top = list(clip[0]) if clip else []
    for g in top:
        gid = g.get("id") or ""
        if not gid or gid.startswith("f1") or re.fullmatch(r"[0-9a-f:;-]+", gid):
            errs.append("слой без человеческого имени: %r" % gid)
    return errs


def main():
    ok = True
    for path in sys.argv[1:] or [f for f in os.listdir(HERE) if f.endswith(".keyshape")]:
        full = path if os.path.isabs(path) else os.path.join(HERE, path)
        errs = check(full)
        if errs:
            ok = False
            print("FAIL %s" % os.path.basename(full))
            for e in errs:
                print("   -", e)
        else:
            print("OK   %s" % os.path.basename(full))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
