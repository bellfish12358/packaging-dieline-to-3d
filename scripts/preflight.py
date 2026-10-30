# -*- coding: utf-8 -*-
"""
刀版 SVG 预检（不启动 Blender）。

目的：在花几分钟跑 Blender 之前，先确认输入符合 build_box.py 的解析约定。
只做结构检查，不做几何求解；折线能不能配上由 build_box.py 的 report.json 回答。

用法：
    python preflight.py <input.svg>
    python preflight.py <input.svg> --pretty

输出：一行 JSON（默认）或缩进 JSON（--pretty）。
退出码：0 = 可以继续；2 = 有错误，先修输入。
"""
import json
import math
import os
import re
import sys
import xml.etree.ElementTree as ET

SVG_NS = "{http://www.w3.org/2000/svg}"
TOKEN = re.compile(r"[A-Za-z]|[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")
ALLOWED = set("MmLlHhVvAaZz")
UNSUPPORTED = {"C", "c", "S", "s", "Q", "q", "T", "t"}


def fail(msg, errors):
    errors.append(msg)


def parse_points(d):
    """把 path 的 d 解析成点列（圆弧按终点近似，只用于几何自检）。"""
    toks = TOKEN.findall(d or "")
    pts = []
    cur = (0.0, 0.0)
    cmd = None
    i = 0

    def num(k):
        return float(toks[k])

    while i < len(toks):
        t = toks[i]
        if t.isalpha():
            cmd = t
            i += 1
            if cmd in "Zz":
                if pts:
                    pts.append(pts[0])
                continue
            if i >= len(toks):
                break
            continue
        c = (cmd or "M").upper()
        rel = (cmd or "M").islower()
        try:
            if c in ("M", "L"):
                x, y = num(i), num(i + 1)
                i += 2
                if rel:
                    x, y = cur[0] + x, cur[1] + y
                cur = (x, y)
                pts.append(cur)
            elif c == "H":
                x = num(i)
                i += 1
                if rel:
                    x = cur[0] + x
                cur = (x, cur[1])
                pts.append(cur)
            elif c == "V":
                y = num(i)
                i += 1
                if rel:
                    y = cur[1] + y
                cur = (cur[0], y)
                pts.append(cur)
            elif c == "A":
                x, y = num(i + 5), num(i + 6)
                i += 7
                if rel:
                    x, y = cur[0] + x, cur[1] + y
                cur = (x, y)
                pts.append(cur)
            else:
                i += 1
        except (IndexError, ValueError):
            break
    return pts


def clean_poly(pts):
    out = []
    for q in pts:
        if not out or abs(q[0] - out[-1][0]) > 1e-9 or abs(q[1] - out[-1][1]) > 1e-9:
            out.append(q)
    if len(out) > 2 and abs(out[0][0] - out[-1][0]) < 1e-9 and abs(out[0][1] - out[-1][1]) < 1e-9:
        out.pop()
    return out


def poly_area(poly):
    s = 0.0
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return abs(s) * 0.5


def _cross(o, a, b):
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _proper_hit(p1, p2, p3, p4):
    d1 = _cross(p3, p4, p1)
    d2 = _cross(p3, p4, p2)
    d3 = _cross(p1, p2, p3)
    d4 = _cross(p1, p2, p4)
    return ((d1 > 1e-9 > d2) or (d1 < -1e-9 < d2)) and ((d3 > 1e-9 > d4) or (d3 < -1e-9 < d4))


def count_self_intersections(poly):
    n = len(poly)
    hits = 0
    for i in range(n):
        a1, a2 = poly[i], poly[(i + 1) % n]
        for j in range(i + 1, n):
            if j == i or (j + 1) % n == i or j == (i + 1) % n:
                continue
            if _proper_hit(a1, a2, poly[j], poly[(j + 1) % n]):
                hits += 1
    return hits


def main():
    if len(sys.argv) < 2:
        print("usage: python preflight.py <input.svg> [--pretty]")
        return 2
    path = os.path.abspath(sys.argv[1])
    pretty = "--pretty" in sys.argv[2:]

    errors, warnings = [], []
    result = {
        "ok": False,
        "file": path,
        "cut_paths": 0,
        "fold_lines": 0,
        "unsupported_commands": [],
        "cut_contours": 0,
        "min_contour_area_mm2": None,
        "self_intersections": 0,
        "fold_endpoint_max_dev_mm": None,
        "contours_touch": None,
        "warnings": warnings,
        "errors": errors,
    }

    if not os.path.isfile(path):
        fail("文件不存在: %s" % path, errors)
        return emit(result, pretty, 2)
    if not path.lower().endswith(".svg"):
        warnings.append("扩展名不是 .svg，仍按 SVG 尝试解析")

    try:
        root = ET.parse(path).getroot()
    except Exception as exc:
        fail("XML 解析失败: %s" % exc, errors)
        return emit(result, pretty, 2)

    # 单位 / viewBox / transform
    for attr in ("width", "height"):
        value = root.get(attr)
        if value and re.search(r"(px|pt|in|cm)$", value.strip(), re.I):
            fail("根节点 %s=%s 不是 mm；build_box.py 把原始坐标当 mm 用" % (attr, value),
                 errors)
    width_attr = (root.get("width") or "").strip()
    height_attr = (root.get("height") or "").strip()
    if root.get("viewBox") and not (width_attr.lower().endswith("mm")
                                    and height_attr.lower().endswith("mm")):
        warnings.append("存在 viewBox 且根节点宽高不是 mm；build_box.py 不应用 viewBox 缩放，"
                        "请确认坐标本身已经是最终 mm 坐标")

    transforms = []
    for el in root.iter():
        if el.get("transform"):
            tag = el.tag.replace(SVG_NS, "")
            transforms.append("%s transform=%s" % (tag, el.get("transform")))
    if transforms:
        fail("存在 transform，build_box.py 不会应用：%s" % "; ".join(transforms[:3]),
             errors)

    # 找 group
    cut_groups, fold_groups = [], []
    for g in root.iter(SVG_NS + "g"):
        gid = (g.get("id") or "").strip().lower()
        if gid == "cut":
            cut_groups.append(g)
        elif gid == "fold":
            fold_groups.append(g)

    if not cut_groups:
        fail('找不到 <g id="cut">；当前解析器只认这个 group', errors)
    if not fold_groups:
        fail('找不到 <g id="fold">；当前解析器只认这个 group', errors)
    if len(cut_groups) > 1:
        warnings.append("有 %d 个 cut group，脚本会把它们合并读取" % len(cut_groups))
    if len(fold_groups) > 1:
        warnings.append("有 %d 个 fold group，脚本会把它们合并读取" % len(fold_groups))

    # cut: 只读直接子级 <path>
    cut_paths = []
    for g in cut_groups:
        if g.findall(SVG_NS + "g"):
            warnings.append("cut group 里有嵌套 group；脚本只读直接子级 <path>，"
                            "嵌套里的路径会被忽略")
        if g.findall(SVG_NS + "polygon") or g.findall(SVG_NS + "rect"):
            fail("cut group 里有 polygon/rect；脚本只支持 <path>，请先转成 path", errors)
        cut_paths.extend(g.findall(SVG_NS + "path"))
    result["cut_paths"] = len(cut_paths)
    if not cut_paths:
        fail('cut group 里没有 <path>；每个面片需要一条闭合 <path>', errors)

    unsupported = set()
    for p in cut_paths:
        d = p.get("d") or ""
        cmds = [t for t in TOKEN.findall(d) if t.isalpha()]
        unsupported.update(c for c in cmds if c in UNSUPPORTED)
        if not cmds:
            fail("有一条 <path> 没有 d 属性或为空", errors)
            continue
        if not any(c in "Zz" for c in cmds):
            warnings.append("有一条 cut path 没有 Z 闭合命令；请确认它是闭合轮廓")
        if sum(1 for c in cmds if c in "Mm") > 1:
            warnings.append("有一条 cut path 含多个 M（多个子路径）；"
                            "脚本会把它们连成一条多边形，建议拆成多条 path")
    if unsupported:
        result["unsupported_commands"] = sorted(unsupported)
        fail("不支持的命令: %s；当前只支持 M/L/H/V/A/Z。"
             "请在导出前把曲线转成折线或圆弧" % " ".join(sorted(unsupported)), errors)

    # fold: 只读直接子级 <line>
    fold_lines = []
    for g in fold_groups:
        if g.findall(SVG_NS + "path"):
            fail("fold group 里有 <path>；脚本只读 <line>，请把折线改成 line", errors)
        fold_lines.extend(g.findall(SVG_NS + "line"))
    result["fold_lines"] = len(fold_lines)
    if not fold_lines:
        fail("fold group 里没有 <line>；每条折线需要一条 <line>", errors)

    empty_lines = 0
    for ln in fold_lines:
        try:
            vals = [float(ln.get(k, "nan")) for k in ("x1", "y1", "x2", "y2")]
        except Exception:
            empty_lines += 1
            continue
        if any(v != v for v in vals):
            empty_lines += 1
        elif abs(vals[0] - vals[2]) < 1e-9 and abs(vals[1] - vals[3]) < 1e-9:
            empty_lines += 1
    if empty_lines:
        warnings.append("%d 条折线坐标缺失或长度为 0" % empty_lines)

    # ---------------------------------------------------------- 几何自检
    polys = []
    for p in cut_paths:
        poly = clean_poly(parse_points(p.get("d") or ""))
        if len(poly) >= 3:
            polys.append(poly)
    result["cut_contours"] = len(polys)

    if polys:
        areas = [poly_area(p) for p in polys]
        result["min_contour_area_mm2"] = round(min(areas), 3)
        if min(areas) < 1.0:
            warnings.append("有轮廓面积 %.3f mm2（< 1），很可能是噪点；先删掉再跑"
                            % min(areas))
        bad = [i for i, p in enumerate(polys) if count_self_intersections(p) > 0]
        result["self_intersections"] = len(bad)
        if bad:
            warnings.append("轮廓 %s 自交；切分与 UV 会异常，先把路径修成简单多边形" % bad[:6])

        # 轮廓是否相接：相接 = 连体刀版；分离刀版的面片之间本来就有缝，
        # 折线落在缝里、端点自然不落在顶点上，不该告警。
        touch = False
        for i in range(len(polys)):
            if touch:
                break
            for j in range(i + 1, len(polys)):
                for vx, vy in polys[i]:
                    if any(abs(vx - wx) < 0.01 and abs(vy - wy) < 0.01 for wx, wy in polys[j]):
                        touch = True
                        break
                if touch:
                    break
        result["contours_touch"] = touch

        verts = [q for poly in polys for q in poly]
        maxdev = 0.0
        worst = None
        for ln in fold_lines:
            for kx, ky in (("x1", "y1"), ("x2", "y2")):
                try:
                    x, y = float(ln.get(kx)), float(ln.get(ky))
                except (TypeError, ValueError):
                    continue
                d = min(math.hypot(x - vx, y - vy) for vx, vy in verts)
                if d > maxdev:
                    maxdev, worst = d, (round(x, 2), round(y, 2))
        result["fold_endpoint_max_dev_mm"] = round(maxdev, 3)
        if maxdev > 0.05 and touch:
            warnings.append(
                "折线端点离最近的面片顶点 %.3f mm（最远处 %s）。连体刀版要求端点落在顶点上，"
                "否则这条折线切不开；分离刀版（面片已留缝）可以忽略这条。" % (maxdev, worst))

    result["ok"] = not errors
    if result["ok"]:
        warnings.append("预检通过；折线配对与折叠树请以 build_box.py 的 report.json 为准")
    return emit(result, pretty, 0 if result["ok"] else 2)


def emit(result, pretty, code):
    text = json.dumps(result, ensure_ascii=False, indent=2 if pretty else None)
    print(text)
    return code


if __name__ == "__main__":
    sys.exit(main())
