# -*- coding: utf-8 -*-
"""
刀版 SVG -> 立体包装盒（Blender 无头构建）

L0 解析：读 SVG，识别刀线（cut）与折线（fold）
L1 建模：按折线切分面片 / 跨 2mm 缝配对、求邻接、建折叠树、折叠、加厚、倒角、UV
L2 场景：背景、相机、灯光、材质、渲染

用法：
    blender.exe -b -P build_box.py -- <input.svg> <outdir> [--quick]

    --quick  只出 640×640 的 Workbench 素模，跳过 Cycles 主图与特写；
             第一次验几何时用，确认后再跑完整。

DSH（DeepSeek Harness）适配：
    优先用同目录的 run_build.ps1，它会自动找 Blender、跑 preflight、写日志：
    powershell -ExecutionPolicy Bypass -File run_build.ps1 -Svg input.svg -OutDir out -Quick

本脚本只依赖 Blender 自带的 bpy/bmesh/mathutils，不装第三方包。
"""

import bpy
import bmesh
import math
import os
import sys
import json
import re
import xml.etree.ElementTree as ET
from mathutils import Vector, Matrix

MM = 0.001          # 1 mm = 0.001 m
GAP_MM = 2.0        # 面片间隙 mm
PAPER_T = 0.5       # 纸厚 mm
BEVEL_W = 0.5       # 倒角 mm
FOLD_DEG = 90.0     # 默认折叠角
POSE = {}           # 逐折角度覆盖 {折线序号: 度}；负值 = 反向折（外翻）；0 = 不折
AUTO_UP_AXIS = True # 自动判断盒子的高度方向（管轴可能在刀版 x 或 y 上）
FLIP_UP = False     # True = 把盒子上下翻过来（自动判断朝上的一端不合意时用）
AUTO_SCENE = True   # 按盒子包围盒自动布景；False = 用旧版固定机位（119.4×59.4×158.9 那只盒子调的）
FILL_GAP = False
USE_CREASE_BAND = True
CREASE_DEPTH = 0.25   # 折痕凹槽深度 mm   # True = 用折缝面把 2mm 缝补成折痕；False = 保留缝（教程做法）
BAND_SCALE = 1.0


# ------------------------------------------------------------------ SVG 解析
NUM = r'-?\d*\.?\d+(?:[eE][-+]?\d+)?'
TOKEN = re.compile(r'[MmLlHhVvCcSsQqTtAaZz]|' + NUM)


def svg_arc(p0, rx, ry, phi_deg, fa, fs, p1, seg=28):
    """SVG 椭圆弧 -> 折线点（不含起点）"""
    phi = math.radians(phi_deg)
    x0, y0 = p0
    x1, y1 = p1
    if rx == 0 or ry == 0:
        return [p1]
    dx2, dy2 = (x0 - x1) / 2.0, (y0 - y1) / 2.0
    x1p = math.cos(phi) * dx2 + math.sin(phi) * dy2
    y1p = -math.sin(phi) * dx2 + math.cos(phi) * dy2
    rx, ry = abs(rx), abs(ry)
    lam = x1p * x1p / (rx * rx) + y1p * y1p / (ry * ry)
    if lam > 1:
        rx *= math.sqrt(lam)
        ry *= math.sqrt(lam)
    num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    co = math.sqrt(max(0.0, num / den))
    if fa == fs:
        co = -co
    cxp = co * rx * y1p / ry
    cyp = -co * ry * x1p / rx
    cx = math.cos(phi) * cxp - math.sin(phi) * cyp + (x0 + x1) / 2.0
    cy = math.sin(phi) * cxp + math.cos(phi) * cyp + (y0 + y1) / 2.0

    def ang(ux, uy, vx, vy):
        d = math.hypot(ux, uy) * math.hypot(vx, vy)
        if d == 0:
            return 0.0
        c = max(-1.0, min(1.0, (ux * vx + uy * vy) / d))
        a = math.acos(c)
        return -a if (ux * vy - uy * vx) < 0 else a

    ux, uy = (x1p - cxp) / rx, (y1p - cyp) / ry
    vx, vy = (-x1p - cxp) / rx, (-y1p - cyp) / ry
    th1 = ang(1.0, 0.0, ux, uy)
    dth = ang(ux, uy, vx, vy)
    if not fs and dth > 0:
        dth -= 2 * math.pi
    elif fs and dth < 0:
        dth += 2 * math.pi
    pts = []
    for i in range(1, seg + 1):
        t = th1 + dth * i / seg
        pts.append((
            cx + rx * math.cos(t) * math.cos(phi) - ry * math.sin(t) * math.sin(phi),
            cy + rx * math.cos(t) * math.sin(phi) + ry * math.sin(t) * math.cos(phi),
        ))
    return pts


def parse_path(d):
    """只支持 M / L / H / V / A / Z（绝对与相对），足够覆盖刀版"""
    toks = TOKEN.findall(d)
    i = 0
    pts = []
    cur = (0.0, 0.0)
    start = (0.0, 0.0)
    cmd = None
    while i < len(toks):
        t = toks[i]
        if re.match(r'[A-Za-z]', t):
            cmd = t
            i += 1
            if cmd in 'Zz':
                if pts and (abs(pts[-1][0] - start[0]) > 1e-9 or abs(pts[-1][1] - start[1]) > 1e-9):
                    pts.append(start)
                cur = start
                continue
            if i >= len(toks):
                break
        rel = cmd.islower()
        c = cmd.upper()
        if c == 'M':
            x, y = float(toks[i]), float(toks[i + 1]); i += 2
            if rel:
                x, y = cur[0] + x, cur[1] + y
            cur = (x, y); start = cur; pts.append(cur); cmd = 'l' if rel else 'L'
        elif c == 'L':
            x, y = float(toks[i]), float(toks[i + 1]); i += 2
            if rel:
                x, y = cur[0] + x, cur[1] + y
            cur = (x, y); pts.append(cur)
        elif c == 'H':
            x = float(toks[i]); i += 1
            if rel:
                x = cur[0] + x
            cur = (x, cur[1]); pts.append(cur)
        elif c == 'V':
            y = float(toks[i]); i += 1
            if rel:
                y = cur[1] + y
            cur = (cur[0], y); pts.append(cur)
        elif c == 'A':
            rx, ry, rot = float(toks[i]), float(toks[i + 1]), float(toks[i + 2])
            fa, fs = int(float(toks[i + 3])), int(float(toks[i + 4]))
            x, y = float(toks[i + 5]), float(toks[i + 6]); i += 7
            if rel:
                x, y = cur[0] + x, cur[1] + y
            pts.extend(svg_arc(cur, rx, ry, rot, fa, fs, (x, y)))
            cur = (x, y)
        else:
            i += 1
    # 去掉与首点重复的尾点，再统一为开环
    out = []
    for p in pts:
        if not out or math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) > 1e-7:
            out.append(p)
    if len(out) > 2 and math.hypot(out[0][0] - out[-1][0], out[0][1] - out[-1][1]) < 1e-7:
        out.pop()
    return out


def parse_svg(path):
    tree = ET.parse(path)
    root = tree.getroot()
    ns = '{http://www.w3.org/2000/svg}'
    cuts, folds = [], []
    for g in root.iter(ns + 'g'):
        gid = (g.get('id') or '').lower()
        if gid == 'cut':
            for p in g.findall(ns + 'path'):
                poly = parse_path(p.get('d'))
                if len(poly) >= 3:
                    cuts.append(poly)
        elif gid == 'fold':
            for ln in g.findall(ns + 'line'):
                folds.append(((float(ln.get('x1')), float(ln.get('y1'))),
                              (float(ln.get('x2')), float(ln.get('y2')))))
    return cuts, folds


def parse_pose(text):
    """解析 --pose "8=-90,9=-90,10=0,11=175" -> {8:-90.0, 9:-90.0, 10:0.0, 11:175.0}"""
    out = {}
    if not text:
        return out
    for item in str(text).replace(";", ",").split(","):
        item = item.strip()
        if not item:
            continue
        if "=" not in item:
            raise RuntimeError("--pose 格式应为 折线序号=角度，例如 10=0,11=175；收到 %r" % item)
        k, v = item.split("=", 1)
        out[int(k.strip())] = float(v.strip())
    return out


# ------------------------------------------------------------------ 几何
def side(p, a, b):
    return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])


def inside(p, poly, tol=1e-9):
    x, y = p
    n = len(poly)
    c = False
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xi = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if xi > x:
                c = not c
    return c


def dist_to_poly_edge(p, poly):
    best = 1e9
    n = len(poly)
    for i in range(n):
        a = poly[i]; b = poly[(i + 1) % n]
        ax, ay = a; bx, by = b
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        if L2 == 0:
            t = 0.0
        else:
            t = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L2))
        d = math.hypot(p[0] - (ax + t * dx), p[1] - (ay + t * dy))
        if d < best:
            best = d
    return best


def _nearest_vertex(poly, p, tol=1e-4):
    for i, q in enumerate(poly):
        if abs(q[0] - p[0]) < tol and abs(q[1] - p[1]) < tol:
            return i
    return None


def _ring(poly, i, j):
    n = len(poly)
    out = [poly[i]]
    k = i
    while k != j:
        k = (k + 1) % n
        out.append(poly[k])
    return out


def _nearest_vertex_dist(poly, p):
    """返回 (最近顶点的距离, 顶点序号)"""
    best = (1e9, -1)
    for i, q in enumerate(poly):
        d = math.hypot(q[0] - p[0], q[1] - p[1])
        if d < best[0]:
            best = (d, i)
    return best


def split_poly_detail(poly, a, b, tol=1e-4):
    """按折线 ab（弦）切分多边形，返回 (面片列表, 原因码, 偏差量)。

    原因码：
      ok                 切分成功
      no_start_vertex    折线起点不在面片顶点上（detail = 最近顶点距离 mm）
      no_end_vertex      折线终点不在面片顶点上（detail = 最近顶点距离 mm）
      degenerate         切出来的环太短或顶点重合
      zero_area          切出来的一侧面积为 0
      crosses_chord      面片跨在折线两侧，这条弦不是有效切口（detail = 越界量）
    """
    i1 = _nearest_vertex(poly, a, tol)
    if i1 is None:
        d, _ = _nearest_vertex_dist(poly, a)
        return [poly], "no_start_vertex", d
    i2 = _nearest_vertex(poly, b, tol)
    if i2 is None:
        d, _ = _nearest_vertex_dist(poly, b)
        return [poly], "no_end_vertex", d
    if i1 == i2:
        return [poly], "degenerate", 0.0

    r1 = _ring(poly, i1, i2)
    r2 = _ring(poly, i2, i1)
    if len(r1) < 3 or len(r2) < 3:
        return [poly], "degenerate", float(min(len(r1), len(r2)))
    a1, a2 = poly_area(r1), poly_area(r2)
    if a1 < 1e-4 or a2 < 1e-4:
        return [poly], "zero_area", float(min(a1, a2))

    s1 = [side(p, a, b) for p in r1]
    s2 = [side(p, a, b) for p in r2]
    eps = 1e-6
    # 两块必须分别落在弦的两侧，否则说明这条弦不是有效切口
    if not ((max(s1) <= eps and min(s2) >= -eps) or (max(s2) <= eps and min(s1) >= -eps)):
        return [poly], "crosses_chord", max(max(s1), max(s2), -min(s1), -min(s2))
    return [r1, r2], "ok", 0.0


def split_poly(poly, a, b, tol=1e-4):
    """按折线 ab（弦）切分多边形（兼容旧接口：失败时原样返回）。"""
    faces, _why, _detail = split_poly_detail(poly, a, b, tol)
    return faces


def poly_area(poly):
    s = 0.0
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return abs(s) * 0.5


def poly_centroid(poly):
    a = 0.0
    cx = cy = 0.0
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        cr = x1 * y2 - x2 * y1
        a += cr
        cx += (x1 + x2) * cr
        cy += (y1 + y2) * cr
    if abs(a) < 1e-12:
        return poly[0]
    a *= 0.5
    return (cx / (6 * a), cy / (6 * a))


# ------------------------------------------------------------------ 切分与邻接
SPLIT_REASON_CN = {
    "ok": "切分成功",
    "no_start_vertex": "折线起点不在面片顶点上",
    "no_end_vertex": "折线终点不在面片顶点上",
    "degenerate": "切出来的环退化（顶点重合或环太短）",
    "zero_area": "切出来的一侧面积为 0",
    "crosses_chord": "面片跨在折线两侧，这条弦不是有效切口",
    "shared_edge": "两条轮廓的公共边，不需要切分",
}


def split_faces(pieces, folds):
    """逐条折线切分，返回 (面片列表, 每条折线的诊断日志)。"""
    faces = list(pieces)
    log = []
    for k, (a, b) in enumerate(folds):
        before = len(faces)
        new_faces = []
        fails = []
        for f in faces:
            got, why, detail = split_poly_detail(f, a, b)
            if len(got) == 1 and why != "ok":
                fails.append((why, detail))
            new_faces.extend(got)
        faces = new_faces
        progressed = len(faces) > before
        reason = "ok" if progressed else (fails[0][0] if fails else "degenerate")
        detail = 0.0 if progressed else (fails[0][1] if fails else 0.0)
        log.append({
            "fold": k,
            "a": [round(a[0], 3), round(a[1], 3)],
            "b": [round(b[0], 3), round(b[1], 3)],
            "faces_before": before,
            "faces_after": len(faces),
            "split": len(faces) - before,
            "reason": reason,
            "detail": round(float(detail), 3),
        })
    return faces, log


def build_adjacency(faces, folds, tol=1e-4):
    """连体刀版：折痕正好落在两块面片的公共边上。

    返回 (edges, matched)：matched 是配上邻接的折线序号，
    用来区分「这条折线是两条轮廓的公共边，本来就不用切」和「切分失败」。
    """
    edges = []
    matched = []
    for k, (a, b) in enumerate(folds):
        mid = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
        hit = []
        for idx, f in enumerate(faces):
            if dist_to_poly_edge(mid, f) < tol:
                hit.append(idx)
        if len(hit) == 2:
            edges.append((hit[0], hit[1], a, b))
            matched.append(k)
        elif len(hit) > 2:
            hit.sort(key=lambda i: dist_to_poly_edge(mid, faces[i]))
            edges.append((hit[0], hit[1], a, b))
            matched.append(k)
    return edges, matched


def _dist_pt_seg(p, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 < 1e-12:
        return math.hypot(p[0] - ax, p[1] - ay)
    t = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L2))
    return math.hypot(p[0] - (ax + t * dx), p[1] - (ay + t * dy))


def _crease_edge_of_face(poly, a, b, maxd):
    """面片上与折痕平行、正对且投影有重叠的那条边"""
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = math.hypot(dx, dy)
    if L < 1e-9:
        return None
    ux, uy = dx / L, dy / L
    best = None
    n = len(poly)
    for i in range(n):
        p = poly[i]
        q = poly[(i + 1) % n]
        ex, ey = q[0] - p[0], q[1] - p[1]
        el = math.hypot(ex, ey)
        if el < 1e-9:
            continue
        if abs(ex * ux + ey * uy) / el < 0.85:
            continue
        d = abs((p[0] - a[0]) * uy - (p[1] - a[1]) * ux)
        if d > maxd:
            continue
        t0 = ((p[0] - a[0]) * ux + (p[1] - a[1]) * uy) / L
        t1 = ((q[0] - a[0]) * ux + (q[1] - a[1]) * uy) / L
        ov = max(0.0, min(max(t0, t1), 1.0) - max(min(t0, t1), 0.0))
        if ov < 0.45:
            continue
        if best is None or d < best[1]:
            best = (i, d)
    return best


def build_adjacency_gapped(faces, folds, gap=2.0):
    """分离刀版：折线落在 2mm 缝里，按「平行 + 正对 + 投影重叠」跨缝配对。

    返回 (edges, matched)。
    """
    edges = []
    matched = []
    maxd = gap * 0.9
    for k, (a, b) in enumerate(folds):
        cand = []
        for idx, f in enumerate(faces):
            hit = _crease_edge_of_face(f, a, b, maxd)
            if hit is None:
                continue
            cen = poly_centroid(f)
            s = side(cen, a, b)
            cand.append((hit[1], idx, 1 if s > 0 else -1))
        cand.sort()
        pos = [c for c in cand if c[2] > 0]
        neg = [c for c in cand if c[2] < 0]
        if pos and neg:
            edges.append((pos[0][1], neg[0][1], a, b))
            matched.append(k)
    return edges, matched


def build_tree(faces, edges):
    n = len(faces)
    adj = {i: [] for i in range(n)}
    for k, (i, j, a, b) in enumerate(edges):
        adj[i].append((j, k))
        adj[j].append((i, k))
    root = max(range(n), key=lambda i: poly_area(faces[i]))
    order = []
    seen = {root}
    stack = [root]
    while stack:
        p = stack.pop(0)
        for (c, k) in adj[p]:
            if c not in seen:
                seen.add(c)
                order.append((p, c, k))
                stack.append(c)
    return root, order, adj, len(seen)


# ------------------------------------------------------------------ 2mm 让位
def _line_isect(l1, l2):
    (x1, y1, x2, y2) = l1
    (x3, y3, x4, y4) = l2
    d = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(d) < 1e-12:
        return None
    a = x1 * y2 - y1 * x2
    b = x3 * y4 - y3 * x4
    return ((a * (x3 - x4) - (x1 - x2) * b) / d,
            (a * (y3 - y4) - (y1 - y2) * b) / d)


def _edge_is_fold(p, q, folds, tol=1e-4):
    """判断多边形的一条边是否落在某条折痕上"""
    mx, my = (p[0] + q[0]) / 2.0, (p[1] + q[1]) / 2.0
    for (a, b) in folds:
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dy)
        if L < 1e-9:
            continue
        # 点到直线距离
        d = abs((mx - a[0]) * dy - (my - a[1]) * dx) / L
        if d > tol:
            continue
        # 投影须落在折线范围内
        t = ((mx - a[0]) * dx + (my - a[1]) * dy) / (L * L)
        if -0.01 <= t <= 1.01:
            return True
    return False


def _drop_collinear(poly, tol=1e-6):
    """去掉共线的中间顶点，否则相邻两条边平行会让偏移求交失败"""
    out = []
    n = len(poly)
    for i in range(n):
        a = poly[(i - 1) % n]
        b = poly[i]
        c = poly[(i + 1) % n]
        d1 = (b[0] - a[0], b[1] - a[1])
        d2 = (c[0] - b[0], c[1] - b[1])
        l1 = math.hypot(*d1)
        l2 = math.hypot(*d2)
        if l1 < tol or l2 < tol:
            continue
        cr = abs(d1[0] * d2[1] - d1[1] * d2[0]) / (l1 * l2)
        if cr > 1e-6:
            out.append(b)
    return out if len(out) >= 3 else poly


def inset_faces(faces, folds, gap=2.0, sign=1.0):
    """沿折痕边平移每块面片的折痕边。

    sign=-1：向内收 gap/2（连体刀版拆成 2mm 缝）
    sign=+1：向外放 gap/2（把缝合拢，纸板连成整体）
    """
    half = gap / 2.0 * sign
    out = []
    for poly0 in faces:
        poly = _drop_collinear(poly0)
        n = len(poly)
        area2 = 0.0
        for i in range(n):
            x1, y1 = poly[i]
            x2, y2 = poly[(i + 1) % n]
            area2 += x1 * y2 - x2 * y1
        ccw = area2 > 0
        lines = []
        ok = True
        for i in range(n):
            p = poly[i]
            q = poly[(i + 1) % n]
            dx, dy = q[0] - p[0], q[1] - p[1]
            L = math.hypot(dx, dy)
            if L < 1e-12:
                ok = False
                break
            nx, ny = (-dy / L, dx / L) if ccw else (dy / L, -dx / L)
            d = half if _edge_is_fold(p, q, folds, abs(half) + 1e-4) else 0.0
            lines.append((p[0] + nx * d, p[1] + ny * d,
                          q[0] + nx * d, q[1] + ny * d))
        if not ok:
            out.append(poly)
            continue
        new = []
        good = True
        for i in range(n):
            v = _line_isect(lines[(i - 1) % n], lines[i])
            if v is None:
                good = False
                break
            new.append(v)
        if not good or len(new) < 3:
            out.append(poly)
            continue
        # 退化检查
        a2 = 0.0
        for i in range(len(new)):
            x1, y1 = new[i]
            x2, y2 = new[(i + 1) % len(new)]
            a2 += x1 * y2 - x2 * y1
        out.append(new if abs(a2) > 1e-3 else poly)
    return out


def write_svg(faces, folds, path, title="die-line"):
    import io
    minx = min(p[0] for f in faces for p in f)
    maxx = max(p[0] for f in faces for p in f)
    miny = min(p[1] for f in faces for p in f)
    maxy = max(p[1] for f in faces for p in f)
    body = []
    for f in faces:
        d = "M " + " L ".join("%.3f %.3f" % (p[0], p[1]) for p in f) + " Z"
        body.append('    <path d="%s"/>' % d)
    fl = ['    <line x1="%.3f" y1="%.3f" x2="%.3f" y2="%.3f"/>' % (a[0], a[1], b[0], b[1])
          for (a, b) in folds]
    svg = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg"
     width="{maxx - minx + 10:.2f}mm" height="{maxy - miny + 10:.2f}mm"
     viewBox="{minx - 5:.2f} {miny - 5:.2f} {maxx - minx + 10:.2f} {maxy - miny + 10:.2f}">
  <title>{title}</title>
  <desc>面片之间留 2mm 缝；id=cut 刀线，id=fold 折线</desc>
  <g id="cut" fill="none" stroke="#111111" stroke-width="0.25" stroke-linejoin="round">
{chr(10).join(body)}
  </g>
  <g id="fold" fill="none" stroke="#1E90FF" stroke-width="0.25" stroke-dasharray="2 1.2">
{chr(10).join(fl)}
  </g>
</svg>
'''
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(svg)


# ------------------------------------------------------------------ Blender
def clear_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def make_mesh(name, poly, bbox=None):
    """poly: 2D 点列（SVG 坐标，y 向下）-> 网格对象，z=0，法线朝 +Z

    UV 在这里就用刀版平面坐标写入（不是折叠后的三维坐标），
    这样每块面片的 UV 岛位置与刀版一一对应。
    """
    verts = [(x * MM, -y * MM, 0.0) for (x, y) in poly]
    # 保证绕序一致（法线朝 +Z），折叠后印刷面自然朝外
    area = 0.0
    for i in range(len(verts)):
        x1, y1 = verts[i][0], verts[i][1]
        x2, y2 = verts[(i + 1) % len(verts)][0], verts[(i + 1) % len(verts)][1]
        area += x1 * y2 - x2 * y1
    if area < 0:
        verts.reverse()
    faces = [list(range(len(verts)))]
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.update()
    if bbox:
        x0, x1, y0, y1 = bbox
        w = max(1e-6, x1 - x0)
        h = max(1e-6, y1 - y0)
        uvl = me.uv_layers.new(name="UVMap")
        for i, (x, y) in enumerate(poly):
            uvl.data[i].uv = ((x - x0) / w, 1.0 - (y - y0) / h)
    ob = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(ob)
    return ob


def fold_matrix(a3, b3, angle):
    axis = (b3 - a3)
    if axis.length < 1e-9:
        return Matrix.Identity(4)
    axis.normalize()
    R = Matrix.Rotation(angle, 4, axis)
    T = Matrix.Translation(a3)
    return T @ R @ T.inverted()


def _edge_near_crease(poly, a, b, tol=2.5):
    """返回离折痕最近、且基本平行的那条边的索引"""
    n = len(poly)
    best = None
    bestd = 1e9
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = math.hypot(dx, dy)
    if L < 1e-9:
        return None
    for i in range(n):
        p = poly[i]
        q = poly[(i + 1) % n]
        mx, my = (p[0] + q[0]) / 2.0, (p[1] + q[1]) / 2.0
        d = abs((mx - a[0]) * dy - (my - a[1]) * dx) / L
        if d > tol:
            continue
        t = ((mx - a[0]) * dx + (my - a[1]) * dy) / (L * L)
        if not (-0.02 <= t <= 1.02):
            continue
        ex, ey = q[0] - p[0], q[1] - p[1]
        el = math.hypot(ex, ey)
        if el < 1e-9:
            continue
        if abs(ex * dx + ey * dy) / (el * L) < 0.9:
            continue
        if d < bestd:
            bestd = d
            best = i
    return best


def build_bands(gfaces, edges, order, M, bbox, gap=2.0):
    """折痕两侧各有一条边，用一条窄面带连起来，充当纸板的折痕区。

    平铺刀版里保留 2mm 缝；折起来后由这条面带补上，
    外面看不到贯穿裂缝，折痕本身又是一条明确的细线。
    """
    x0, x1, y0, y1 = bbox
    w = max(1e-6, x1 - x0)
    h = max(1e-6, y1 - y0)

    def flat_uv(pt):
        return ((pt[0] - x0) / w, 1.0 - (pt[1] - y0) / h)

    bands = []
    for (p, c, k) in order:
        i, j, a, b = edges[k]
        ei = _edge_near_crease(gfaces[p], a, b)
        ej = _edge_near_crease(gfaces[c], a, b)
        if ei is None or ej is None:
            continue
        P, C = gfaces[p], gfaces[c]
        u1, u2 = P[ei], P[(ei + 1) % len(P)]
        v1, v2 = C[ej], C[(ej + 1) % len(C)]

        def wp(pt):
            return M[p] @ Vector((pt[0] * MM, -pt[1] * MM, 0.0))

        def wc(pt):
            return M[c] @ Vector((pt[0] * MM, -pt[1] * MM, 0.0))

        d_direct = (wp(u1) - wc(v1)).length + (wp(u2) - wc(v2)).length
        d_cross = (wp(u1) - wc(v2)).length + (wp(u2) - wc(v1)).length
        if d_cross < d_direct:
            v1, v2 = v2, v1

        # 沿折痕方向两端各延长半个缝宽，让相邻折缝面在角部互相压住，不留洞
        ext = 0.0
        du = (u2[0] - u1[0], u2[1] - u1[1])
        lu = math.hypot(*du)
        if lu > 1e-9:
            du = (du[0] / lu, du[1] / lu)
            dv = (v2[0] - v1[0], v2[1] - v1[1])
            lv = math.hypot(*dv)
            if lv > 1e-9 and (dv[0] * du[0] + dv[1] * du[1]) < 0:
                du = (-du[0], -du[1])
            u1 = (u1[0] - du[0] * ext, u1[1] - du[1] * ext)
            u2 = (u2[0] + du[0] * ext, u2[1] + du[1] * ext)
            v1 = (v1[0] - du[0] * ext, v1[1] - du[1] * ext)
            v2 = (v2[0] + du[0] * ext, v2[1] + du[1] * ext)

        verts = [wp(u1), wp(u2), wc(v2), wc(v1)]
        uvs = [flat_uv(u1), flat_uv(u2), flat_uv(v2), flat_uv(v1)]

        # 折痕做成一条 V 形浅槽：桥接面从中间下陷一点，形成可见的压痕
        npv = (M[p].to_3x3() @ Vector((0, 0, 1))).normalized()
        ncv = (M[c].to_3x3() @ Vector((0, 0, 1))).normalized()
        bis = npv + ncv
        if bis.length < 1e-6:
            bis = npv.copy()
        bis.normalize()
        dep = CREASE_DEPTH * MM
        m1 = ((verts[0] + verts[3]) * 0.5) - bis * dep
        m2 = ((verts[1] + verts[2]) * 0.5) - bis * dep

        me = bpy.data.meshes.new("crease_%d" % k)
        me.from_pydata([tuple(verts[0]), tuple(verts[1]), tuple(m2), tuple(m1),
                        tuple(verts[2]), tuple(verts[3])], [],
                       [[0, 1, 2, 3], [3, 2, 4, 5]])
        me.update()
        uvl = me.uv_layers.new(name="UVMap").data
        mu1 = ((uvs[0][0] + uvs[3][0]) / 2, (uvs[0][1] + uvs[3][1]) / 2)
        mu2 = ((uvs[1][0] + uvs[2][0]) / 2, (uvs[1][1] + uvs[2][1]) / 2)
        alluv = [uvs[0], uvs[1], mu2, mu1, uvs[2], uvs[3]]
        for lidx, li in enumerate(me.loops):
            uvl[lidx].uv = alluv[li.vertex_index]
        ob = bpy.data.objects.new("crease_%d" % k, me)
        bpy.context.collection.objects.link(ob)
        bands.append(ob)
    return bands


def build_box(svg_path, gapped_svg=None, gap=2.0, pose=None):
    pieces, folds = parse_svg(svg_path)

    # 逐折角度：{折线序号: 度}。传 None 时用模块级 POSE，便于从外部脚本设置。
    pose = dict(POSE) if pose is None else dict(pose)
    pose = {int(k): float(v) for k, v in pose.items()}
    bad = sorted(k for k in pose if k < 0 or k >= len(folds))
    if bad:
        raise RuntimeError(
            "POSE 里的折线序号超出范围 %s（本刀版共 %d 条折线，序号 0..%d）"
            % (bad, len(folds), len(folds) - 1))

    if not pieces:
        raise RuntimeError(
            '没有解析到闭合面片。请确认 SVG 里有 <g id="cut">，'
            '且每个面片是它下面的直接 <path> 子元素。')
    if not folds:
        raise RuntimeError(
            '没有解析到折线。请确认 SVG 里有 <g id="fold">，'
            '折线是它下面的直接 <line> 子元素。')

    # 两条路都试：
    #   connected  = 面片相接，先按折线切分，再把折痕边各收 1mm
    #   separated  = 面片已经分开、留 2mm 缝，跨缝配对
    # 选“匹配折线更多”的那条。旧版只看 build_adjacency(pieces)，
    # 连体盒只有 4 条竖折线落在公共边上，会被误判成分离盒。
    faces_split, split_log = split_faces(pieces, folds)
    edges_split, matched_split = build_adjacency(faces_split, folds)
    edges_gap, matched_gap = build_adjacency_gapped(pieces, folds, gap)

    if len(edges_gap) == len(folds) and len(edges_gap) >= len(edges_split):
        mode = "separated"
    elif len(edges_split) == len(folds) and len(edges_split) >= len(edges_gap):
        mode = "connected"
    elif len(edges_gap) > len(edges_split):
        mode = "separated"
    elif len(edges_split) > len(edges_gap):
        mode = "connected"
    elif len(faces_split) > len(pieces):
        mode = "connected"
    elif len(edges_gap) > 0:
        mode = "separated"
    else:
        raise RuntimeError(
            "折线一条都没配上。检查：折线是否画在 2mm 缝里、是否与两侧折边平行、"
            "投影是否重叠；连体刀版则检查折线端点是否落在面片顶点上。"
            "cut=%d, fold=%d" % (len(pieces), len(folds)))

    if mode == "separated":
        faces = [list(p) for p in pieces]
        edges = edges_gap
        if FILL_GAP:
            # 把 2mm 缝合拢：折痕处两块板重新接上，纸板成为连续整体
            gfaces = inset_faces(faces, folds, gap, sign=-1.0)
        else:
            gfaces = [_drop_collinear(f) for f in faces]
        # 分离刀版本身就是“带 2mm 缝的刀版”，复制一份作为交付物
        if gapped_svg and os.path.abspath(svg_path) != os.path.abspath(gapped_svg):
            try:
                import shutil
                shutil.copyfile(svg_path, gapped_svg)
            except Exception as exc:
                print("WARN copy dieline failed: %s" % exc, flush=True)
    else:
        faces = faces_split
        edges = edges_split
        # 沿折痕把每块面片向内收 1mm，形成 2mm 缝（只动折痕边，外形尺寸不变）
        gfaces = inset_faces(faces, folds, gap)
        if gapped_svg:
            write_svg(gfaces, folds, gapped_svg,
                      title="直插盒刀版（面片间留 %gmm 缝）" % gap)

    root, order, adj, tree_faces = build_tree(faces, edges)

    diag = {
        "mode": mode,
        "pose": {str(k): v for k, v in sorted(pose.items())},
        "split_log": split_log,
        "contours_from_svg": len(pieces),
        "faces_after_split": len(faces_split),
        "folds_in_svg": len(folds),
        "folds_matched": len(edges),
        "folds_unmatched": len(folds) - len(edges),
        "faces_in_tree": tree_faces,
        "warnings": [],
    }
    if diag["folds_unmatched"]:
        diag["warnings"].append("%d 条折线没有配上" % diag["folds_unmatched"])
    if diag["faces_in_tree"] != len(faces):
        diag["warnings"].append(
            "%d/%d 块面片进树" % (diag["faces_in_tree"], len(faces)))
    matched = set(matched_split if mode == "connected" else matched_gap)
    # 落在两条轮廓公共边上的折线本来就不需要切分，把日志里的失败原因改成 shared_edge
    for item in split_log:
        if item["split"] <= 0 and item["fold"] in matched:
            item["reason"] = "shared_edge"
            item["detail"] = 0.0
    if mode == "connected":
        for item in split_log:
            if item["split"] <= 0 and item["fold"] not in matched:
                diag["warnings"].append(
                    "折线 #%d %s → %s 没有切开任何面片：%s（偏差 %.3f mm）"
                    % (item["fold"], item["a"], item["b"],
                       SPLIT_REASON_CN.get(item["reason"], item["reason"]),
                       item["detail"]))
    for w in diag["warnings"]:
        print("WARN " + w, flush=True)

    xs = [p[0] for f in gfaces for p in f]
    ys = [p[1] for f in gfaces for p in f]
    bbox = (min(xs), max(xs), min(ys), max(ys))

    # 每个面片一个对象（UV 在平铺状态下写入）
    objs = []
    for i, f in enumerate(gfaces):
        objs.append(make_mesh("panel_%02d" % i, f, bbox))

    # 世界变换
    M = {root: Matrix.Identity(4)}

    def p3(pt):
        return Vector((pt[0] * MM, -pt[1] * MM, 0.0))

    if pose and len(edges) != len(folds):
        print("WARN 有折线没配上，POSE 按折线序号对不上，本次忽略 POSE", flush=True)
        pose = {}

    for (p, c, k) in order:
        i, j, a, b = edges[k]
        a3, b3 = p3(a), p3(b)
        Rpos = fold_matrix(a3, b3, math.radians(FOLD_DEG))
        Rneg = fold_matrix(a3, b3, math.radians(-FOLD_DEG))
        cen = p3(poly_centroid(faces[c]))
        zp = (Rpos @ cen).z
        zn = (Rneg @ cen).z
        sgn = 1.0 if zp < zn else -1.0
        ang = pose.get(k, FOLD_DEG)
        if abs(ang) < 1e-9:
            R = Matrix.Identity(4)
        else:
            R = fold_matrix(a3, b3, math.radians(sgn * ang))
        M[c] = M[p] @ R

    missing = [i for i in range(len(faces)) if i not in M]
    if missing:
        raise RuntimeError(
            "折叠树不完整，面片 %s 没有父级。先查邻接/折线，不要继续渲染。" % missing)

    for i, ob in enumerate(objs):
        ob.matrix_world = M[i]
    bpy.context.view_layer.update()

    # 贴合面让位：与更大的平行面共面时，向盒内挪一个纸厚，避免 z-fighting
    info = []
    for i, ob in enumerate(objs):
        mw = ob.matrix_world
        vs = [mw @ v.co for v in ob.data.vertices]
        c = sum(vs, Vector((0, 0, 0))) / max(1, len(vs))
        n = (mw.to_3x3() @ ob.data.polygons[0].normal).normalized()
        area = ob.data.polygons[0].area
        info.append((c, n, area))
    center = sum((t[0] for t in info), Vector((0, 0, 0))) / len(info)
    for i, (ci, ni, ai) in enumerate(info):
        for j, (cj, nj, aj) in enumerate(info):
            if i == j or aj < ai * 1.5:
                continue
            if abs(ni.dot(nj)) < 0.999:
                continue
            if abs(ni.dot(cj - ci)) > 1e-4:
                continue
            d = (center - ci)
            if d.length < 1e-9:
                continue
            d.normalize()
            off_world = d * PAPER_T * MM
            off_local = objs[i].matrix_world.to_3x3().inverted() @ off_world
            for v in objs[i].data.vertices:
                v.co += off_local
            break

    # 判断盒子的高度方向（管轴）：端盖/锁底法向平行于管轴，立面法向垂直于管轴
    up = detect_up_rotation(faces, edges, order, M, flip=FLIP_UP)
    diag["up"] = up
    print("UP " + json.dumps(up, ensure_ascii=False), flush=True)

    # 折痕补面（默认关闭：按教程做法保留 2mm 缝，折痕由两侧板厚断面构成）
    if USE_CREASE_BAND:
        bands = build_bands(gfaces, edges, order, M, bbox, gap=gap * BAND_SCALE)
        objs.extend(bands)
        diag["crease_bands"] = len(bands)
        if len(bands) < len(edges):
            diag["warnings"].append(
                "折缝补面只生成了 %d/%d 条，缺的位置会露出 2mm 通缝"
                % (len(bands), len(edges)))
            print("WARN " + diag["warnings"][-1], flush=True)

    # 合并（不焊接：面片之间保留 2mm 缝，实体化后每条折痕都能看到板厚断面）
    bpy.ops.object.select_all(action='DESELECT')
    for ob in objs:
        ob.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.join()
    box = bpy.context.active_object
    box.name = "Carton"

    bpy.context.view_layer.objects.active = box
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.remove_doubles(threshold=1e-5)
    bpy.ops.object.mode_set(mode='OBJECT')

    return box, gfaces, edges, root, order, diag


def setup_uv(box, bbox):
    """UV 直接取刀版平面坐标"""
    me = box.data
    if not me.uv_layers:
        me.uv_layers.new(name="UVMap")
    uvl = me.uv_layers.active.data
    x0, x1, y0, y1 = bbox
    w = max(1e-6, x1 - x0)
    h = max(1e-6, y1 - y0)
    for poly in me.polygons:
        for li in poly.loop_indices:
            v = me.vertices[me.loops[li].vertex_index].co
            uvl[li].uv = ((v.x * 1000.0 - x0) / w, 1.0 - (-v.y * 1000.0 - y0) / h)


def add_modifiers(box):
    sol = box.modifiers.new("Solidify", 'SOLIDIFY')
    sol.thickness = PAPER_T * MM
    sol.offset = -1.0            # 向盒内加厚，印刷面在外
    sol.use_even_offset = False  # 均匀偏移在近零折角上会数值爆炸
    sol.use_quality_normals = True
    sol.use_rim = True

    bev = box.modifiers.new("Bevel", 'BEVEL')
    bev.width = BEVEL_W * MM
    bev.segments = 3
    bev.limit_method = 'ANGLE'
    bev.angle_limit = math.radians(40)
    bev.harden_normals = False

    for p in box.data.polygons:
        p.use_smooth = False
    # 按角度自动平滑：大平面保持平整，只有倒角处过渡
    try:
        bpy.context.view_layer.objects.active = box
        box.select_set(True)
        bpy.ops.object.shade_auto_smooth(angle=math.radians(30))
    except Exception as e:
        print("auto smooth skipped:", e)


def detect_up_rotation(faces, edges, order, M, flip=False):
    """判断盒子的高度方向（管轴），返回立起方式。

    判据：管式盒的 4 个立面就是面积最大的 4 片；这 4 片彼此之间的折线
    方向就是管轴（其余折线是端盖/锁底/防尘翼，方向与管轴垂直）。
    管轴只可能落在刀版 x 或 y 上（刀版是平的，所有折线都在 xy 平面内）。
    """
    areas = [poly_area(f) for f in faces]
    if len(areas) < 5:
        walls = set(range(len(areas)))
    else:
        walls = set(sorted(range(len(areas)), key=lambda i: -areas[i])[:4])
    acc = Vector((0.0, 0.0, 0.0))
    hits = 0
    for (p, c, k) in order:
        if p in walls and c in walls:
            i, j, a, b = edges[k]
            d = Vector((b[0] - a[0], -(b[1] - a[1]), 0.0))
            d = M[p].to_3x3() @ d
            if d.length > 1e-9:
                acc += d.normalized()
                hits += 1
    fallback = {"axis": "y", "rot": [90.0, 0.0, 0.0], "confidence": 0.0,
                "folds_used": hits,
                "note": "没能从立面折线判断管轴，回退旧版绕 X +90°"}
    if hits == 0 or acc.length < 1e-9:
        return fallback
    acc.normalize()
    comps = [abs(acc.x), abs(acc.y), abs(acc.z)]
    ax = max(range(3), key=lambda i: comps[i])
    conf = round(comps[ax], 4)
    if conf < 0.9:
        return fallback
    if ax == 0:
        ang = 90.0 if flip else -90.0
        return {"axis": "x", "rot": [0.0, ang, 0.0], "confidence": conf,
                "folds_used": hits,
                "note": "管轴=刀版 x：绕 Y %+.0f°，刀版 %sx 朝上" % (ang, "-" if flip else "+")}
    if ax == 1:
        ang = -90.0 if flip else 90.0
        return {"axis": "y", "rot": [ang, 0.0, 0.0], "confidence": conf,
                "folds_used": hits,
                "note": "管轴=刀版 y（旧版行为）：绕 X %+.0f°，刀版 %sy 朝上" % (ang, "-" if flip else "+")}
    return {"axis": "z", "rot": [0.0, 0.0, 0.0], "confidence": conf,
            "folds_used": hits,
            "note": "管轴落在世界 z（异常）：不旋转，请人工检查"}


def up_euler(up):
    """把 detect_up_rotation 的结果转成 rotation_euler（弧度）。"""
    rot = (up or {}).get("rot") or [90.0, 0.0, 0.0]
    return tuple(math.radians(v) for v in rot)


def stand_up_and_ground(box, rot_euler=None):
    """把躺着的盒子立起来，落到地面。rot_euler 为空时用旧版绕 X +90°。"""
    if rot_euler is None:
        rot_euler = (math.radians(90), 0.0, 0.0)
    bpy.context.view_layer.objects.active = box
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    box.rotation_euler = rot_euler
    bpy.context.view_layer.update()
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    zmin = min(v.co.z for v in box.data.vertices)
    for v in box.data.vertices:
        v.co.z -= zmin


def make_backdrop(size=0.9, scale=1.0, cx=0.0, cy=0.0):
    """弧形无缝背景。scale / cx / cy 用来按盒子尺寸和位置整体缩放平移。"""
    pts = []
    pts.append((cy + (-size * 2) * scale, 0.0))
    pts.append((cy + 0.55 * scale, 0.0))
    r = 0.35 * scale
    for i in range(1, 17):
        a = -math.pi / 2 + (math.pi / 2) * i / 16
        pts.append((cy + 0.55 * scale + r * math.cos(a), r + r * math.sin(a)))
    pts.append((cy + 0.55 * scale + r, size * scale))
    verts = []
    for x in (cx - size * scale, cx + size * scale):
        for (y, z) in pts:
            verts.append((x, y, z))
    n = len(pts)
    faces = []
    for i in range(n - 1):
        faces.append([i, i + 1, n + i + 1, n + i])
    me = bpy.data.meshes.new("Backdrop")
    me.from_pydata(verts, [], faces)
    me.update()
    ob = bpy.data.objects.new("Backdrop", me)
    bpy.context.collection.objects.link(ob)
    mat = bpy.data.materials.new("BackdropMat")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (0.52, 0.53, 0.55, 1)
    bsdf.inputs["Roughness"].default_value = 0.85
    ob.data.materials.append(mat)
    return ob


def make_paper_material():
    mat = bpy.data.materials.new("Paper")
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (0.86, 0.85, 0.83, 1)
    bsdf.inputs["Roughness"].default_value = 0.78
    bsdf.inputs["Specular IOR Level"].default_value = 0.35
    # 纸纹
    tex = nt.nodes.new("ShaderNodeTexNoise")
    tex.inputs["Scale"].default_value = 900.0
    tex.inputs["Detail"].default_value = 6.0
    tex.inputs["Roughness"].default_value = 0.6
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.12
    bump.inputs["Distance"].default_value = 0.00015
    nt.links.new(tex.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def add_sun(name, loc, target, energy, angle=0.25, color=(1, 1, 1)):
    ld = bpy.data.lights.new(name, 'SUN')
    ld.energy = energy
    ld.angle = angle
    ld.color = color
    ob = bpy.data.objects.new(name, ld)
    bpy.context.collection.objects.link(ob)
    ob.location = loc
    d = Vector(target) - Vector(loc)
    ob.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
    return ob


def setup_camera(target=(0.06, 0.026, 0.078), loc=(0.255, -0.355, 0.255), lens=70):
    cd = bpy.data.cameras.new("Cam")
    cd.lens = lens
    cam = bpy.data.objects.new("Cam", cd)
    bpy.context.collection.objects.link(cam)
    cam.location = loc
    d = Vector(target) - Vector(loc)
    cam.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
    bpy.context.scene.camera = cam
    return cam


CAM_DIR = Vector((0.195, -0.381, 0.177)).normalized()   # 旧版机位方向（相对目标点）


def scene_corners(lo, hi):
    return [Vector((x, y, z)) for x in (lo.x, hi.x) for y in (lo.y, hi.y) for z in (lo.z, hi.z)]


def fit_camera(cam, target, corners, lens=70.0, margin=1.12, sensor=36.0):
    """把相机沿 CAM_DIR 推到刚好装下 corners 的距离（方形画幅）。"""
    target = Vector(target)
    d = Vector(CAM_DIR)
    right = d.cross(Vector((0.0, 0.0, 1.0)))
    if right.length < 1e-6:
        right = Vector((1.0, 0.0, 0.0))
    right.normalize()
    up = right.cross(d).normalized()
    fov = 2.0 * math.atan(0.5 * sensor / lens)
    half = math.tan(fov / 2.0)
    dist = 0.0
    for p in corners:
        rel = p - target
        x, y, z = abs(rel.dot(right)), abs(rel.dot(up)), rel.dot(d)
        dist = max(dist, x / half + z, y / half + z)
    dist *= margin
    cam.data.lens = lens
    cam.location = target + d * dist
    cam.rotation_euler = (target - cam.location).to_track_quat('-Z', 'Y').to_euler()
    return dist


def main():
    argv = sys.argv
    if "--" in argv:
        args = argv[argv.index("--") + 1:]
    else:
        args = []
    if len(args) < 2:
        print("usage: blender -b -P build_box.py -- <input.svg> <outdir> [--quick]")
        sys.exit(2)

    svg = os.path.abspath(args[0])
    outdir = os.path.abspath(args[1])
    quick = ("--quick" in args) or ("quick" in args)
    pose = {}
    for a in args:
        if a.startswith("--pose="):
            pose = parse_pose(a.split("=", 1)[1])
    global FLIP_UP
    if "--flip-up" in args:
        FLIP_UP = True
    os.makedirs(outdir, exist_ok=True)

    if not os.path.isfile(svg):
        raise RuntimeError("input SVG not found: %s" % svg)

    print("STAGE build %s" % os.path.basename(svg), flush=True)
    clear_scene()
    box, faces, edges, root, order, diag = build_box(
        svg, gapped_svg=os.path.join(outdir, "dieline_2mm_gap.svg"), gap=GAP_MM,
        pose=pose)

    add_modifiers(box)
    stand_up_and_ground(box, up_euler(diag.get("up")))
    box.data.materials.append(make_paper_material())

    # 包围盒 / 报告：先写，后面渲染失败也能拿到几何结果
    vs = [box.matrix_world @ v.co for v in box.data.vertices]
    bb = {
        "x": [min(v.x for v in vs) * 1000, max(v.x for v in vs) * 1000],
        "y": [min(v.y for v in vs) * 1000, max(v.y for v in vs) * 1000],
        "z": [min(v.z for v in vs) * 1000, max(v.z for v in vs) * 1000],
    }
    report = {
        "input": os.path.basename(svg),
        "mode": diag["mode"],
        "contours_from_svg": diag["contours_from_svg"],
        "faces_after_split": diag["faces_after_split"],
        "pieces_from_svg": len(faces),
        "fold_count": len(edges),
        "folds_in_svg": diag["folds_in_svg"],
        "folds_matched": diag["folds_matched"],
        "folds_unmatched": diag["folds_unmatched"],
        "faces_in_tree": diag["faces_in_tree"],
        "root_face": root,
        "size_mm": {
            "dx": round(bb["x"][1] - bb["x"][0], 2),
            "dy": round(bb["y"][1] - bb["y"][0], 2),
            "dz": round(bb["z"][1] - bb["z"][0], 2),
        },
        "params": {
            "paper_mm": PAPER_T,
            "bevel_mm": BEVEL_W,
            "fold_deg": FOLD_DEG,
            "gap_mm": GAP_MM,
            "crease_mode": "V-groove" if USE_CREASE_BAND else "open-gap",
            "crease_depth_mm": CREASE_DEPTH,
        },
        "crease_bands": diag.get("crease_bands"),
        "up": diag.get("up"),
        "split_log": diag.get("split_log"),
        "pose": diag.get("pose"),
        "warnings": diag["warnings"],
        "quick": quick,
        "outdir": outdir,
    }
    lo = Vector((bb["x"][0] / 1000.0, bb["y"][0] / 1000.0, bb["z"][0] / 1000.0))
    hi = Vector((bb["x"][1] / 1000.0, bb["y"][1] / 1000.0, bb["z"][1] / 1000.0))

    report_path = os.path.join(outdir, "report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print("REPORT " + json.dumps(report, ensure_ascii=False), flush=True)

    # 布景：默认按实际包围盒缩放；AUTO_SCENE=False 时退回旧版固定机位
    center = (lo + hi) * 0.5
    span = max(hi.x - lo.x, hi.y - lo.y, hi.z - lo.z)
    if AUTO_SCENE:
        s = max(0.2, span / 0.1589)
        make_backdrop(0.9, scale=s, cx=center.x, cy=center.y)
        light_dist = 3.0 * max(span, 1e-3)
    else:
        make_backdrop()
        light_dist = 1.0
    # 盒内补光：让 2mm 折缝里透出的不是纯黑，而是一道灰线
    pd = bpy.data.lights.new("Inner", 'POINT')
    pd.energy = 0.05
    pd.shadow_soft_size = 0.01
    inner = bpy.data.objects.new("Inner", pd)
    bpy.context.collection.objects.link(inner)
    inner.location = center if AUTO_SCENE else (0.06, 0.03, 0.09)

    def _sun_pos(direction):
        d = Vector(direction).normalized()
        return Vector(center) + d * light_dist if AUTO_SCENE else d * light_dist

    add_sun("Key", _sun_pos((-0.55, -0.75, 0.85)),
            tuple(center) if AUTO_SCENE else (0.06, 0.02, 0.08), 3.6, 0.08)
    add_sun("Fill", _sun_pos((0.85, -0.35, 0.45)),
            tuple(center) if AUTO_SCENE else (0.06, 0.03, 0.07), 0.55, 0.7)
    add_sun("Rim", _sun_pos((0.15, 0.85, 0.65)),
            tuple(center) if AUTO_SCENE else (0.06, 0.03, 0.10), 1.6, 0.45)
    cam = setup_camera(target=tuple(center) if AUTO_SCENE else (0.06, 0.026, 0.078))
    if AUTO_SCENE:
        fit_camera(cam, center, scene_corners(lo, hi), 70.0)
        print("SCENE center=(%.3f, %.3f, %.3f) span=%.3f" % (center.x, center.y, center.z, span),
              flush=True)

    sc = bpy.context.scene
    sc.render.engine = 'CYCLES'
    sc.cycles.device = 'CPU'
    sc.cycles.samples = 64
    sc.cycles.use_denoising = True
    sc.render.resolution_x = 1200
    sc.render.resolution_y = 1200
    sc.render.film_transparent = False

    # clay 校验图：Workbench，不看灯光，只验几何
    sc.render.engine = 'BLENDER_WORKBENCH'
    sc.display.shading.light = 'STUDIO'
    sc.display.shading.color_type = 'SINGLE'
    sc.display.shading.single_color = (0.72, 0.55, 0.38)
    sc.display.shading.show_shadows = True
    sc.display.shading.show_cavity = True
    sc.render.resolution_x = 640 if quick else 1200
    sc.render.resolution_y = 640 if quick else 1200
    sc.render.filepath = os.path.join(outdir, "clay.png")
    print("STAGE clay", flush=True)
    bpy.ops.render.render(write_still=True)

    sc.render.engine = 'CYCLES'
    vt = [t.name for t in sc.view_settings.bl_rna.properties['view_transform'].enum_items]
    sc.view_settings.view_transform = 'AgX' if 'AgX' in vt else 'Standard'
    sc.view_settings.look = 'None'
    sc.view_settings.exposure = -0.2

    world = bpy.data.worlds.new("W")
    sc.world = world
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.38, 0.39, 0.42, 1)
    world.node_tree.nodes["Background"].inputs[1].default_value = 0.28

    # 版本标记：打开 .blend 后可在大纲/文本编辑器里确认这是哪一版
    import datetime
    stamp = (
        "BUILD INFO\n"
        "time      : %s\n"
        "input     : %s\n"
        "panels    : %d\n"
        "folds     : %d\n"
        "gap mm    : %s\n"
        "crease    : %s (depth %.2f mm)\n"
        "paper mm  : %.2f\n"
        "bevel mm  : %.2f\n"
    ) % (
        datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        os.path.basename(svg), len(faces), len(edges),
        "bridged" if USE_CREASE_BAND else "open",
        "V-groove" if USE_CREASE_BAND else "none", CREASE_DEPTH,
        PAPER_T, BEVEL_W,
    )
    box.name = "Carton_%dpanels_%s" % (len(faces),
                                       "bridged" if USE_CREASE_BAND else "gapped")
    txt = bpy.data.texts.new("BUILD_INFO")
    txt.write(stamp)

    sc.render.resolution_x = 1200
    sc.render.resolution_y = 1200
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(outdir, "carton.blend"))

    if not quick:
        print("STAGE render", flush=True)
        sc.render.filepath = os.path.join(outdir, "render.png")
        bpy.ops.render.render(write_still=True)

        # 折痕细节图：顶面靠前的一条棱，看折痕、板缝和纸厚
        print("STAGE closeup", flush=True)
        cam = sc.camera
        cam.data.lens = 85
        tgt = Vector((center.x + 0.34 * (hi.x - lo.x),
                      lo.y + 0.22 * (hi.y - lo.y),
                      hi.z - 0.12 * (hi.z - lo.z)))
        cam.location = tgt + CAM_DIR * (1.75 * (hi.z - lo.z))
        cam.rotation_euler = (tgt - cam.location).to_track_quat('-Z', 'Y').to_euler()
        sc.render.filepath = os.path.join(outdir, "closeup_crease.png")
        bpy.ops.render.render(write_still=True)

    print("STAGE done %s" % outdir, flush=True)


if __name__ == "__main__":
    main()
