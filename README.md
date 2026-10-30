# packaging-dieline-to-3d

把**包装盒刀版图（die-line）**转成可编辑的 Blender 3D 盒体，并渲染白卡效果图的一个技能包（给 DeepSeek Harness / DSH 用）。

> 这个仓库是本地已安装版本的备份。电脑坏了、误删了，都可以从这里拉回来。

## 能做什么

- 读入刀版 SVG（刀线 + 折线），自动切分面片、建折叠树、折成盒子
- 折缝留 2mm 缝并用 V 槽补面，纸厚 0.5mm、棱边倒角 0.5mm
- 每块面片按刀版平面坐标写 UV，可以直接按刀版做图文
- 逐条折线改角度：全闭合、半打开、开盖 45° 都能出
- 一次出素模（`clay.png`）、主图（`render.png`）、折痕特写（`closeup_crease.png`）
- 自带预检：轮廓自交、噪点、折线端点没落在顶点上，在启动 Blender 之前就报出来

## 目录

| 路径 | 说明 |
|---|---|
| `SKILL.md` | 技能说明（给 AI 看的完整工作流） |
| `scripts/build_box.py` | 主脚本：解析 → 折叠 → 加厚 → 倒角 → UV → 布景 → 渲染 |
| `scripts/preflight.py` | 刀版预检，不启动 Blender |
| `scripts/run_build.ps1` | Windows 启动器：自动找 Blender、跑预检、写日志 |
| `scripts/install.ps1` | 安装到 `~/.agents/skills`（已存在时先备份） |
| `examples/` | 两个冒烟样例（分离刀版 13 片 / 连体刀版 5 轮廓） |
| `reference/` | 参数、SVG 规范、排错手册 |
| `CHANGELOG.md` | 版本改动 |

## 环境

- Windows（启动器是 PowerShell）
- Blender **5.1.2**（脚本只用自带 bpy，不需要第三方包）
- Python 3（只有预检用；没有也能跑，`run_build.ps1` 会跳过预检）
- 可选：在 `~/.dsh/dsh-blender.config.json` 里写 `{"blenderExe":"...\\blender.exe"}`，启动器会自动找到 Blender

## 安装

把整个文件夹复制到：

```text
C:\Users\<你的用户名>\.agents\skills\packaging-dieline-to-3d
```

或者在这个文件夹里运行：

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1
```

装完新开一个 DSH 会话就能被识别。

## 用

```powershell
# 先出素模验几何
powershell -ExecutionPolicy Bypass -File scripts\run_build.ps1 -Svg "刀版.svg" -OutDir "output" -Quick

# 几何没问题再出完整渲染
powershell -ExecutionPolicy Bypass -File scripts\run_build.ps1 -Svg "刀版.svg" -OutDir "output"

# 半打开的姿态：折线序号=角度，负值=反向折
powershell -ExecutionPolicy Bypass -File scripts\run_build.ps1 `
  -Svg "刀版.svg" -OutDir "output_open" -Pose "8=-90,9=-90,10=0,11=175"
```

产物：`clay.png`（素模）、`render.png`（主图）、`closeup_crease.png`（折痕/板厚特写）、`carton.blend`（可编辑场景）、`report.json`（结构化数据）、`dieline_2mm_gap.svg`（带 2mm 缝的刀版）。

## 已知限制

只做管式盒（四立面 + 插舌 + 防尘翼 + 粘口）；不做盘式盒、天地盖、异形盒。折线中段的局部切口（比如半月拇指缺口）不支持。盒角会留 1–2mm 细缝（2mm 缝在折线端点截止）。

## 版本

v2（2026-10-30）：新增逐折角度、自动判断立起方向、切分诊断、预检增强、布景自适应。相对原版的改动见 [CHANGELOG.md](CHANGELOG.md)。

原版备份留在本地 `~/.agents/skills/packaging-dieline-to-3d.backup-20261030-1406/`。
