# 常见报错与排查

## 1. 先看哪里

| 文件 | 看什么 |
|---|---|
| `run.log` | Blender 全量日志、`STAGE`、`REPORT`、Python traceback |
| `report.json` | 解析/折叠结果，先看 `folds_unmatched`、`faces_in_tree` |
| `clay.png` | 几何对不对，不看灯光 |
| `render.png` / `closeup_crease.png` | 材质、折痕、板厚 |
| 终端输出 | `preflight` 的 JSON、Blender 路径、退出码 |

排查顺序：**preflight → report.json → clay → render**。不要一上来就看成品图。

---

## 2. 预检错误

### `找不到 <g id="cut">` / `找不到 <g id="fold">`

当前解析器只认这两个 group，不认颜色/虚线。

处理：

- 在 Illustrator 里把刀线放进名为 `cut` 的图层/组，折线放进 `fold`
- 或手工改 SVG：`<g id="cut">...</g>`、`<g id="fold">...</g>`
- 不要把折线放在 cut group 里，也不要把刀线放在 fold group 里

### `cut group 里没有 <path>`

- 刀线可能是 `<polygon>` / `<rect>` / `<line>`；先转成 `<path>`
- 路径可能嵌套在子 group 里；当前只读直接子级

### `fold group 里有 <path>`

折线必须是 `<line>`。Illustrator 导出折线时选「直线段」，不要用钢笔路径。

### `不支持的命令: C S Q T`

刀版里有贝塞尔曲线。当前解析器只支持 `M/L/H/V/A/Z`。

处理：

- 在 Illustrator 里把曲线转成折线/圆弧再导出
- 或让生成刀版的工具直接输出 `A` 弧线（包小盒的圆角就是 `A`）
- 不要直接跑：脚本会静默丢掉这些段，面片会缺边

### `存在 transform`

- 组/路径带 `transform="matrix(...)"` 或 `translate(...)`
- 脚本不应用 transform，坐标会错
- 在导出时「应用变换」，或把 transform 烘焙进坐标

### `根节点 width/height 不是 mm`

- SVG 用了 px/pt/in/cm
- 脚本把原始坐标当 mm 用
- 在导出时选 mm，或先做单位换算

### `有一条 cut path 含多个 M`

一条 path 里有多个子路径。脚本会把它们连成一条多边形。

处理：在 Illustrator 里「释放复合路径」，拆成多条独立 path。

### `有一条 cut path 没有 Z`

可能是开放路径。刀线必须是闭合轮廓；补 `Z` 或检查是否漏画。

---

## 3. 构建错误

### `折线一条都没配上`

`report.json` 里 `folds_matched=0`。

分离刀版检查：

- 折线是否画在 2mm 缝里
- 折线与两侧折边是否基本平行（方向余弦 > 0.85）
- 折线到折边距离是否 < 1.8 mm
- 投影重叠是否 ≥ 45%
- 折线两侧是否各有一块面片

连体刀版检查：

- 折线端点是否落在面片顶点上（容差 1e-4 mm）
- 折线是否贯穿整个面片
- 是否有三块面片共线/多重折线

### `folds_unmatched > 0`

有几条折线没配上。不要继续渲染；先对照刀版找出是哪几条，修输入。

### `折叠树不完整，面片 X 没有父级`

有面片没进 BFS 树。常见原因：

- 某条折线邻接错了
- 面片之间实际不相连（刀版画错）
- 折线端点/缝宽不对

处理：看 `report.json` 的 `faces_in_tree`，回查该面片周围的折线；不要靠缩放硬凑。

### 盒子炸开 / 折反

- 折线端点或邻接错
- 折向自动选择失败（凹盒/异形盒更容易）
- 面片法向反了

处理：先看 `clay.png`；检查 `M` 变换和折向；当前折向规则只对凸管式盒可靠。

### 黑面 / 材质错乱

面片绕序反了。`make_mesh` 建面时会统一朝 `+Z`，但如果输入多边形自交/绕序异常，仍可能出错。检查输入路径。

### 折缝太宽 / 看不到板厚

当前默认 `USE_CREASE_BAND=True`，是窄 V 槽。

想要看到 2mm 明缝和板厚断面：把 `USE_CREASE_BAND` 改成 `False`。

### 折痕太浅

先调 `CREASE_DEPTH`（默认 0.25 mm），再调 `BAND_SCALE`；不要先动倒角。

### 棱边没有高光

倒角 0.5 mm 是 1200 px 出图的经验值；特写可以降到 0.2–0.3 mm，但不要超过纸厚的 60%。

### 渲染太慢

- 先用 `-Quick` 出 640 素模，确认几何
- 完整渲染 1200 × 1200 / 64 spp，CPU 约 1–2 分钟；机器慢时先降到 800 × 800 / 32 spp 试构图
- 不要一上来 4K

---

## 4. DSH / Windows 问题

### 找不到 Blender

`run_build.ps1` 会按顺序找：

1. `-BlenderExe`
2. `DSH_BLENDER_EXE`
3. `BLENDER_EXE`
4. `~/.dsh/dsh-blender.config.json` 的 `blenderExe`
5. PATH
6. 常见安装位置

本机实测路径：

```text
E:\softward\blender5.12\blender.exe
```

DSH 配置：

```json
{
  "workDir": "E:\\dsh\\blender-rt",
  "blenderExe": "E:\\softward\\blender5.12\\blender.exe"
}
```

改完配置要重启 DSH 后端（如果走插件）或新开会话。

### `run_build.ps1` 中文乱码 / 解析报错

Windows PowerShell 5.1 默认按 ANSI 读无 BOM 的 UTF-8 脚本，中文会乱码，甚至把全角括号当成语法错误。

本 skill 的 `run_build.ps1` 已保存为 **UTF-8 with BOM**。如果你改过它，重新保存时选「UTF-8 带 BOM」，或用：

```powershell
$p = "scripts\run_build.ps1"
$t = [IO.File]::ReadAllText($p, [Text.Encoding]::UTF8)
[IO.File]::WriteAllText($p, $t, (New-Object Text.UTF8Encoding($true)))
```

### `无法加载文件 ... 因为在此系统上禁止运行脚本`

用：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_build.ps1 ...
```

不要改全局执行策略。

### 路径含中文/空格

`run_build.ps1` 用 `-LiteralPath` 和数组参数，中文/空格路径可用。不要在命令里手工拼引号；直接把完整路径传给 `-Svg` / `-OutDir`。

### Python 找不到

`run_build.ps1` 会先找 `python`，再找 `py -3`。都没有时跳过 preflight，只跑 Blender。建议装 Python 3 并加入 PATH，预检能提前挡掉大部分输入错误。

### DSH 里 skill 没出现

- 确认文件夹在 `C:\Users\<你>\.agents\skills\packaging-dieline-to-3d\`
- 确认 `SKILL.md` 第一行是 `---`，frontmatter 里有 `name` 和 `description`
- 新开一个会话；skill 列表在会话启动时加载
- 如果同名旧版还在，先改名/删除，避免冲突

### DSH 的 Blender 插件在线，但 wrapper 还是走 CLI

这是故意的：本脚本需要命令行参数（`-- <svg> <outdir>`），CLI 最稳、可复现。DSH 插件的 `blender_rt_headless` 也能跑 `script_file`，但参数传递和路径映射多一层，出问题不好排查。优先 `run_build.ps1`。

---

## 5. 输出检查

### `report.json` 看起来对，但图不对

`report.json` 只证明解析/折叠树，不证明几何一定正确。必须看 `clay.png`：

- 面片有没有漏
- 法向有没有反
- 有没有穿插
- 折痕是不是细槽
- 盒子比例对不对

### `dieline_2mm_gap.svg` 和输入一样

分离刀版输入时，脚本会把源文件复制成 `dieline_2mm_gap.svg`；这是预期行为。连体刀版输入时，脚本会重新生成带 2mm 缝的版本。

### 没有 `uv_layout.png`

当前脚本不导出 UV 布局图。需要时在 Blender 里单独导出，或让 agent 加一个导出步骤。

### 输出目录混了旧图

每次用干净的输出目录；或者先删掉旧的 `render.png` / `closeup_crease.png` / `report.json`。脚本会覆盖同名文件，但不会清理旧的多余文件。

---

## 6. 仍然不对怎么办

把这三样发给维护者/下一个会话：

1. `run.log`（最后 100 行）
2. `report.json`
3. `clay.png`

不要只发 `render.png`；几何问题在成品图里看不出来。

---

## v2 新增：三个诊断字段怎么读

### `up.axis` 不对（盒子躺着 / 上下颠倒）

```json
"up": {"axis": "x", "rot": [0.0, -90.0, 0.0], "confidence": 1.0, "note": "..."}
```

- `axis=y`：旧版行为，刀版 +y 朝上；`axis=x`：管轴横着画的刀版，绕 Y −90°；
- `confidence < 0.9`：立面折线方向不干净（多半是端点没落在顶点上，或最大四片不是立面），脚本退回旧版并告警——先修刀版；
- 方向对了但上下颠倒：加 `--flip-up`。

### `crease_bands < fold_count`

折缝补面只生成了 n/m 条，缺的那几条折线两侧找不到「平行、正对、投影重叠」的边，折起来会露出 2 mm 通缝。

排查：① 那条折线是不是两条轮廓的公共边（这种情况本来不需要补面）；② 面片在折线处是否被切出斜边；③ `GAP_MM` 是否被改得比补面容差还大。

### `split_log` 里出现 `no_end_vertex`

连体切分的硬要求：折线两端必须精确落在面片顶点上（容差 0.0001 mm）。导出时常见 0.01–0.5 mm 偏差，肉眼看不出来但切分就是失败。

处理：在 Illustrator/CAD 里把折线端点吸附到刀线顶点；或导出前把端点吸附到 0.05 mm 内最近的顶点。
