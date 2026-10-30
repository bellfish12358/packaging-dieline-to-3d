---
name: packaging-dieline-to-3d
description: 把包装盒刀版 SVG 转成可编辑的 Blender 3D 盒体并渲染白卡效果图：解析刀线/折线、建折叠树、2mm 缝与折痕、板厚倒角、UV、布景灯光。当用户提供刀版图/刀模图/展开图，要求纸盒建模、包装盒 3D 效果图、还原折痕与板厚、生成可用 UV，或提到直插盒、管式盒、die-line 时使用。不适用于盘式盒、天地盖、异形盒和软包装；不做印刷分色与图文对位。
---

# 包装盒刀版图转 3D

把「刀版 SVG」变成「可编辑盒体 + 白卡效果图」。链路固定：

> 刀版 → 解析 → 面片/邻接 → 折叠树 → 2mm 缝/折痕 → 厚度/倒角 → UV → 布景 → 渲染

**不要从零写建模脚本。** `scripts/build_box.py` 是已跑通的实现；复制到输出目录后只改顶部常量和布景参数。

当前版本已在 DSH + Blender 5.1.2 实测：

- 分离刀版：13 片 + 2mm 缝 + 12 折 → 13 片 / 12 折 / 13 进树
- 连体刀版：5 个闭合轮廓 + 12 折 → 切分后同样 13 片 / 12 折 / 13 进树
- 外廓：119.4 × 59.4 × 158.9 mm

---

## 1. 先确认 4 项输入

| # | 输入 | 缺了怎么办 |
|---|---|---|
| 1 | 刀版 SVG | 必须问；没有就不开工 |
| 2 | 盒型参考图 | 必须问；用来确认结构、朝向、折叠状态 |
| 3 | 输出目录 | 必须问，不猜 |
| 4 | 平面图文稿 | 可缺；只用来理解配色，不负责贴准 |
| 5 | 布景/灯光参考 | 可缺；缺了按默认弧形背景 + 三点光，报告写明是推断 |

只在这三种情况停下来问：**输出目录没给、几何有歧义、参考图的布景/灯光明显超出建模范围**。其余先做再说。

---

## 2. 最短路径（DSH / Windows）

第一次先出素模，确认几何：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_build.ps1 `
  -Svg "刀版.svg" `
  -OutDir "output" `
  -Quick
```

看 `output\clay.png` 和 `output\report.json`。几何没问题后，去掉 `-Quick` 跑完整：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_build.ps1 `
  -Svg "刀版.svg" `
  -OutDir "output"
```

### 想一次出开合状态（半开盒、开盖 45°）

折角可以逐条覆盖，不用改代码：

```powershell
# 折线序号=角度，逗号分隔；负值 = 反向折（外翻），0 = 不折
powershell -ExecutionPolicy Bypass -File scripts\run_build.ps1 `
  -Svg "刀版.svg" -OutDir "output_open" -Pose "8=-90,9=-90,10=0,11=175"
```

折线序号就是 `<g id="fold">` 里 `<line>` 的先后顺序（从 0 开始）；`report.json` 的
`split_log` 里每条折线都带坐标，可以对照着数。角度是相对父面片的：0 = 和父面片共面，
90 = 垂直（默认），负值 = 朝另一侧折，180 = 完全回折。

朝向不对（盒子躺着、上下颠倒）时：先看 `report.json` 的 `up`，再决定要不要 `-FlipUp`。

`run_build.ps1` 会自动：

1. 找 Blender（`-BlenderExe` → `DSH_BLENDER_EXE` → `~/.dsh/dsh-blender.config.json` → PATH → 常见安装位置）
2. 跑 `preflight.py` 检查 SVG 结构
3. 跑 `build_box.py`，把全部输出写进 `OutDir`
4. 把 Blender 日志写进 `OutDir\run.log`，并从终端抓 `REPORT {...}`

> `-Quick` 只出 `clay.png` / `report.json` / `carton.blend`（640×640），不跑 Cycles。完整模式出 `clay.png` + `render.png` + `closeup_crease.png`（1200×1200 / 64 spp）；特写按包围盒自动取景，拍顶面前沿的折痕与板厚。
>
> 如果 `blender` 不在 PATH，不用改脚本：在 `~/.dsh/dsh-blender.config.json` 里写 `{"blenderExe":"...\\blender.exe"}`，或设环境变量 `DSH_BLENDER_EXE`，或传 `-BlenderExe`。

---

## 3. 输入约定（脚本真实规则）

| 项 | 要求 |
|---|---|
| 单位 | mm，1:1；脚本直接用原始坐标，不做单位换算 |
| 刀线 | `<g id="cut">` 下的直接 `<path>` 子元素；每条 path 一块闭合面片 |
| 折线 | `<g id="fold">` 下的直接 `<line>` 子元素；折线不能用 `<path>` |
| 路径命令 | 只支持 `M / L / H / V / A / Z`；不支持 `C / S / Q / T` |
| transform | 不支持；坐标必须是最终 mm 坐标 |
| viewBox | 不应用缩放；确认坐标本身已是 mm |
| polygon/rect | 不支持；先转成 `<path>` |
| 小噪点 | 不做面积过滤；输入前删掉 |
| 连体刀版 | 折线端点要落在面片顶点上；脚本会先切分再让 2mm 缝 |
| 分离刀版 | 面片之间留 2mm 缝；折线画在缝里，与两侧折边平行、正对、投影重叠 ≥45% |

**任何一条不符合，先停下来修输入，不要靠缩放或手工补面硬凑。**

`preflight.py` 会在 Blender 启动前检查上面大部分项，失败直接退出。详细规则见 [reference/svg-spec.md](reference/svg-spec.md)。

---

## 4. 工作流

### 第 1 步：预检

`run_build.ps1` 已经自动跑。也可以单独跑：

```powershell
python scripts\preflight.py "刀版.svg" --pretty
```

- `ok: true` → 继续
- `ok: false` → 按 `errors` 修 SVG，不要启动 Blender
- `warnings` 不阻止运行，但要读一遍

### 第 2 步：Quick 建盒 + clay

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_build.ps1 -Svg "刀版.svg" -OutDir "output" -Quick
```

先看 `report.json`，必须满足：

| 字段 | 期望 | 不满足说明 |
|---|---|---|
| `mode` | `separated` 或 `connected` | 脚本选错了路径 |
| `contours_from_svg` | 与刀版闭合轮廓数一致 | 解析漏片 |
| `faces_after_split` | 切分后的面片数（基线 13） | 切分/邻接失败 |
| `folds_in_svg` | 与刀版折线数一致（基线 12） | 解析漏折线 |
| `folds_matched` | 等于 `folds_in_svg` | 有几条折线没配上 |
| `folds_unmatched` | 0 | 同上，必须为 0 才继续 |
| `faces_in_tree` | 等于 `pieces_from_svg` | 有面片没进折叠树 |
| `size_mm` | 与刀版尺寸一致 | 折叠/缩放错 |
| `crease_bands` | 等于 `fold_count` | 有几条折缝没补上，那几处会露出 2mm 通缝 |
| `up.axis` | `x` 或 `y`，`confidence` ≈ 1 | 立起方向没判断出来，盒子会躺着 |
| `split_log[].reason` | `ok` 或 `shared_edge` | 其它值说明这条折线切分失败，`detail` 里有偏差 |

任何一项不对，先回查输入和 `run.log`，不要继续渲染。

### 第 3 步：看 clay

`clay.png` 是 Workbench 素模，不受灯光干扰，先用它验几何：

- [ ] 面片数量与刀版一致，没有漏片/多片
- [ ] 所有面片法向朝外（没有黑面）
- [ ] 折叠后盒子闭合，没有贯穿裂缝
- [ ] 没有穿插：盖片压不到立面，防尘翼不穿出盒外
- [ ] 没有折反：印刷面全部在外
- [ ] 折痕是细槽，不是裂开的大缝
- [ ] 棱边有倒角，不是死硬边
- [ ] 大平面没有异常明暗
- [ ] 盒子比例与刀版一致

### 第 4 步：完整渲染

几何过了再去掉 `-Quick`：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_build.ps1 -Svg "刀版.svg" -OutDir "output"
```

输出 `render.png`（主图）和 `closeup_crease.png`（折痕/板厚特写）。

### 第 5 步：交付

| 文件 | 说明 |
|---|---|
| `carton.blend` | 完整场景，可编辑 |
| `render.png` | 主视图 |
| `closeup_crease.png` | 折痕/板厚特写 |
| `clay.png` | 素模校验 |
| `report.json` | 结构化结果（脚本生成） |
| `report.md` | 人写的构建报告 |
| `dieline_2mm_gap.svg` | 带 2mm 缝的刀版；分离输入会复制源文件，连体输入会重新生成 |
| `run.log` | Blender 全量日志 |

`report.md` 必须写：

1. 输入文件与输出路径
2. 面片数、折痕数、折叠树结构、根面片
3. 折缝宽、纸厚、倒角、折叠角、折痕模式（V 槽/明缝）与槽深
4. 折向说明：默认按几何向下折，印刷面朝外；没有逐折山/谷输入
5. **所有靠推断而不是靠参考图确定的地方**
6. 复现命令与 Blender 版本

不要承诺「图文 1:1 对位」。AI 只保证 UV 形状与刀版一致，贴准是人的事。

---

## 5. 参数（以脚本常量为准）

| 参数 | 常量 | 默认 | 说明 |
|---|---|---|---|
| 面片间隙 | `GAP_MM` / `gap` | 2.0 mm | 折轴走缝中线 |
| 纸厚 | `PAPER_T` | 0.5 mm | 350g 白卡；Solidify 向盒内 |
| 倒角 | `BEVEL_W` | 0.5 mm | 3 段，角度限制 40° |
| 折叠角 | `FOLD_DEG` | 90° | 默认值；可用 `--pose` 逐折覆盖（支持负值 / 0 / >90°） |
| 立起方向 | `AUTO_UP_AXIS` / `FLIP_UP` | 自动 | 用「最大四片立面之间的折线」判断管轴；`--flip-up` 上下翻转 |
| 布景 | `AUTO_SCENE` | `True` | 按包围盒自动取景；`False` = 旧版固定机位 |
| 折痕模式 | `USE_CREASE_BAND` | `True` | True = 窄 V 槽；False = 2mm 明缝 |
| 折槽深度 | `CREASE_DEPTH` | 0.25 mm | 仅 V 槽模式 |
| 折槽缩放 | `BAND_SCALE` | 1.0 | V 槽宽度缩放 |
| 填充缝 | `FILL_GAP` | `False` | 保留缝 |
| 平滑角 | 自动平滑 | 30° | 避免大平面异常明暗 |

完整参数、灯光/相机坐标、换尺寸缩放规则见 [reference/parameters.md](reference/parameters.md)。

**调参顺序**：先验几何（clay）→ 折缝模式/槽深 → 纸厚/倒角/纸纹 → 相机/灯光/背景。一次只动一个参数。

---

## 6. 场景（默认自适应）

`AUTO_SCENE=True`（默认）时按折叠后的实际包围盒布景，换盒型、换尺寸都不用改坐标：

- 目标点 = 包围盒中心；相机沿旧机位方向（方位角约 27°、俯角约 22°）自动后退到刚好装下整个包围盒（留 12% 余量，方形画幅，70 mm）；
- 背景、灯位、盒内补光按最长边等比缩放；
- 特写（`closeup_crease.png`）同样按包围盒算：85 mm，距离 1.75 × 盒高，瞄准顶面前沿偏右的棱。

想看旧版固定构图就把 `AUTO_SCENE=False`——那套坐标是按 119.4 × 59.4 × 158.9 mm 那只盒子调的，只对那个尺寸合适。

灯还是三点光 + 盒内点光，能量不变（SUN 只看方向）。详细参数见 [reference/parameters.md](reference/parameters.md)。

---

## 7. 常见失败

| 现象 | 原因 | 处理 |
|---|---|---|
| 预检报 `找不到 <g id="cut">` | SVG 没有 cut/fold group | 在 Illustrator/包小盒里按约定分组，或先人工整理 |
| 预检报不支持的命令 | 有 `C/S/Q/T` 曲线 | 导出前把曲线转成折线或圆弧 |
| 预检报 transform | 组/路径带 transform | 在导出时应用变换，坐标落到 mm |
| 面片数不对 | path 多子路径/噪点/曲线被跳过 | 清理输入；确认一条 path 一块面片 |
| `folds_unmatched > 0` | 折线不在 2mm 缝里、不平行、投影重叠不足 | 看 `reference/svg-spec.md` 的配对条件；修刀版 |
| `faces_in_tree < pieces` | 邻接漏了 | 回退查折线与折边；不要缩放硬凑 |
| 盒子炸开/折反 | 折线端点/邻接错，或折向选错 | 先看 clay；查折叠树与折向 |
| 黑面/材质错乱 | 面片绕序反了 | 建面时统一朝 +Z；折叠后才发现要回退 |
| 折缝太宽/看不到板厚 | 当前是 V 槽模式 | `USE_CREASE_BAND=False` 保留 2mm 明缝 |
| 棱边看不到高光 | 倒角太小 | 当前 0.5 mm；不要超过纸厚的 60% |
| 渲染太慢 | 采样/分辨率高 | 先 `-Quick` 出 640 素模 |
| `split_log` 里某条 `reason` 不是 `ok`/`shared_edge` | 这条折线没切开面片 | 看同条 `detail`：`no_end_vertex` 端点没落在顶点；`crosses_chord` 面片跨线；`zero_area`/`degenerate` 退化 |
| `crease_bands < fold_count` | 折缝补面没生成 | 那条缝会露出 2mm 通缝；查该折线两侧是否各有一条与折线平行、正对的边 |
| 盒子躺着出图 / 上下颠倒 | 管轴判断失败，或朝上的那头不对 | 看 `up.axis`、`up.confidence`；加 `-FlipUp` 翻面，或 `AUTO_UP_AXIS=False` 退回旧版绕 X +90° |

更多报错和 DSH 路径问题见 [reference/troubleshooting.md](reference/troubleshooting.md)。

---

## 8. 已知限制

- **只做管式盒**：四立面 + 插舌 + 防尘翼 + 粘口。盘式盒（天地盖、抽屉盒）、异形盒、曲面盒、软包装不在范围内。
- **逐折角度要自己给**：`--pose` 只改折角，不解决穿模；相邻面在 0°/180° 附近会互相插入，要留 2–5° 余量或错开层。
- **折线中段的局部切口不支持**：比如盖/插舌折线中间的半月拇指缺口——`split_poly` 只认整段直线弦，这种要么忽略，要么建模后布尔。
- **解析器很窄**：只认 group id，不认虚线/蓝色样式；不支持曲线、transform、polygon/rect、多子路径、小噪点过滤。跑真实文件前先过 `preflight.py`。
- **不做印刷工艺**：不烫金、不做局部 UV/击凸/压纹，不做印刷分色。
- **不做图文对位**：UV 形状与刀版一致，但把图文贴准是人的事。
- **盒角有 1–2 mm 细缝**：2 mm 缝在折线两端截止，盒角会留一个小孔，渲染里是一条细亮线（不是通缝）；要完全干净得给每个折-折交点补小三角面。
- **不导出 uv_layout.png**：当前脚本不生成 UV 布局图；需要时单独导出。
- **闭合盒**：插舌、防尘翼折在盒内，成品图只看到折痕和板厚断面。

超出范围先说明，不要硬做。

---

## 9. 冒烟测试

第一次安装或换机器，先跑自带样例：

```powershell
# 分离刀版：13 片 + 2mm 缝
powershell -ExecutionPolicy Bypass -File scripts\run_build.ps1 `
  -Svg examples\example_straight_tuck_2mm.svg `
  -OutDir "$env:TEMP\carton_smoke_2mm" `
  -Quick

# 连体刀版：5 轮廓 + 12 折
powershell -ExecutionPolicy Bypass -File scripts\run_build.ps1 `
  -Svg examples\example_straight_tuck_connected.svg `
  -OutDir "$env:TEMP\carton_smoke_connected" `
  -Quick
```

两次都应得到：

```text
mode              separated / connected
contours_from_svg 13 / 5
faces_after_split 13
fold_count        12
folds_unmatched   0
faces_in_tree     13
size_mm           119.4 × 59.4 × 158.9
crease_bands      12
up.axis           y
```

对不上先修环境，不要拿用户的刀版试错。

---

## 10. 安装到 DSH

最省事：在 `packaging-dieline-to-3d` 文件夹里运行安装脚本（已存在同名目录时会先备份）：

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1
```

手动安装：

1. 把整个 `packaging-dieline-to-3d` 文件夹复制到：

   ```text
   C:\Users\<你>\.agents\skills\packaging-dieline-to-3d
   ```

2. 如果已经有同名旧版，先备份/改名：

   ```powershell
   Rename-Item "$env:USERPROFILE\.agents\skills\packaging-dieline-to-3d" `
     "packaging-dieline-to-3d.bak"
   ```

3. 复制后新开一个 DSH 会话，skill 会被自动发现（不需要重启后端）。

4. 确认 Blender 路径。DSH 的 Blender 插件配置在：

   ```text
   C:\Users\<你>\.dsh\dsh-blender.config.json
   ```

   里面有 `"blenderExe": "E:\\softward\\blender5.12\\blender.exe"` 就够了。没有的话，`run_build.ps1` 会按 §2 的顺序继续找；也可以设 `DSH_BLENDER_EXE` 或传 `-BlenderExe`。

5. 在 DSH 里说：

   > 用 packaging-dieline-to-3d，把 `D:\刀版\盒子.svg` 做成 3D，输出到 `D:\out\盒子`，先 Quick 验几何。

---

## 11. 文件

- [install.ps1](install.ps1) — 安装到 `~/.agents/skills`，已存在时先备份
- [scripts/build_box.py](scripts/build_box.py) — 主脚本，已跑通；不要重写
- [scripts/preflight.py](scripts/preflight.py) — SVG 预检，不启动 Blender
- [scripts/run_build.ps1](scripts/run_build.ps1) — DSH/Windows 启动器，自动找 Blender、跑预检、写日志
- [examples/example_straight_tuck_2mm.svg](examples/example_straight_tuck_2mm.svg) — 分离刀版样例（13 片）
- [examples/example_straight_tuck_connected.svg](examples/example_straight_tuck_connected.svg) — 连体刀版样例（5 轮廓）
- [reference/svg-spec.md](reference/svg-spec.md) — 刀版结构、解析规则、容差
- [reference/parameters.md](reference/parameters.md) — 参数、灯光、相机、换尺寸
- [reference/troubleshooting.md](reference/troubleshooting.md) — 常见报错与 DSH 路径问题
