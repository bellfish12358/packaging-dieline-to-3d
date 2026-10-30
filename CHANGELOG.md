# CHANGELOG

## v2 — 2026-10-30

起因：用这个 skill 做一个「只有刀版截图、要闭合 + 半打开两个状态」的盒子时踩到的坑。

### 新增

- **逐折角度**：`--pose "8=-90,9=-90,10=0,11=175"`，或 `build_box(pose={...})`。支持负值（反向折/外翻）、`0`（不折）、`>90`（回折）。半开盒、开盖 45° 不用再改代码。
- **自动朝向**：`detect_up_rotation()` 用「面积最大的 4 片立面之间的折线」判断管轴，支持管轴横着画的刀版（绕 Y −90°）；`--flip-up` 上下翻。
- **切分诊断**：`report.json` 新增 `split_log`，逐条折线给出 `faces_before/after`、`reason`、`detail`。`shared_edge` 表示「两条轮廓的公共边，本来就不用切」，不是错误。
- **预检增强**：新增 `cut_contours`、`min_contour_area_mm2`、`self_intersections`、`fold_endpoint_max_dev_mm`、`contours_touch`，能在启动 Blender 前发现自交、噪点、折线端点没落在顶点上。
- **布景自适应**：`AUTO_SCENE=True`（默认）按折叠后的包围盒自动取景，背景/灯位/盒内光按最长边缩放；折痕特写改为 1.75 × 盒高，能真正看到折痕与板厚。
- `report.json` 新增 `crease_bands`（折缝补面数）、`up`、`pose`、`split_log`。
- `run_build.ps1` 新增 `-Pose` / `-FlipUp` 透传。

### 修复

- 连体刀版里「落在两条轮廓公共边上的折线」不再被误报为切分失败。
- 折线端点告警只在轮廓相接（连体）时出现，分离刀版不再刷屏。
- `preflight.py` 去掉 GBK 控制台编不了的字符（`mm²` 改成 `mm2`）。

### 兼容性

- `build_adjacency()` / `build_adjacency_gapped()` 现在返回 `(edges, matched)`；`split_faces()` 返回 `(faces, log)`。外部脚本若直接 import 这两个函数，需要跟着解包。
- 默认布景由「固定机位」改为「自适应」：对样例盒子（119.4 × 59.4 × 158.9）观感接近但不完全相同。要旧构图设 `AUTO_SCENE=False`。
- `-Quick` 仍然只出 `clay.png` / `report.json` / `carton.blend`，行为不变。

### 回滚

原版完整备份在：

```text
C:\Users\<你>\.agents\skills\packaging-dieline-to-3d.backup-20261030-1406\
C:\Users\<你>\.agents\skills\packaging-dieline-to-3d.backup-20261030-1406.zip
```
