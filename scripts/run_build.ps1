# -*- coding: utf-8 -*-
<#
包装盒刀版 -> 3D · DSH / Windows 启动器

用法：
  powershell -ExecutionPolicy Bypass -File run_build.ps1 `
    -Svg "刀版.svg" -OutDir "output"

  # 第一次只验几何，出 640 素模，不跑 Cycles
  powershell -ExecutionPolicy Bypass -File run_build.ps1 `
    -Svg "刀版.svg" -OutDir "output" -Quick

  # 手动指定 Blender
  ... -BlenderExe "E:\softward\blender5.12\blender.exe"

Blender 查找顺序：
  1. -BlenderExe
  2. 环境变量 DSH_BLENDER_EXE / BLENDER_EXE
  3. C:\Users\<你>\.dsh\dsh-blender.config.json 的 blenderExe（DSH 插件配置）
  4. PATH 里的 blender / blender.exe
  5. 常见安装位置（含本机 E:\softward\blender5.12\blender.exe）

退出码：0 = 成功；2 = 预检失败；其他 = Blender 失败。
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Svg,

    [Parameter(Mandatory = $true)]
    [string]$OutDir,

    [switch]$Quick,
    [switch]$SkipPreflight,
    [string]$BlenderExe,
    [string]$Pose,
    [switch]$FlipUp
)

$ErrorActionPreference = 'Stop'

try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $env:PYTHONIOENCODING = 'utf-8'
    chcp 65001 | Out-Null
} catch { }

function Resolve-Blender {
    param([string]$Explicit)

    $candidates = New-Object System.Collections.Generic.List[string]
    if ($Explicit) { $candidates.Add($Explicit) }
    if ($env:DSH_BLENDER_EXE) { $candidates.Add($env:DSH_BLENDER_EXE) }
    if ($env:BLENDER_EXE) { $candidates.Add($env:BLENDER_EXE) }

    # DSH 插件配置：优先于 PATH
    $cfg = Join-Path $env:USERPROFILE '.dsh\dsh-blender.config.json'
    if (Test-Path $cfg) {
        try {
            $j = Get-Content $cfg -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($j.blenderExe) { $candidates.Add([string]$j.blenderExe) }
        } catch { }
    }

    $cmd = Get-Command blender.exe -ErrorAction SilentlyContinue
    if (-not $cmd) { $cmd = Get-Command blender -ErrorAction SilentlyContinue }
    if ($cmd) { $candidates.Add($cmd.Source) }

    # 常见安装位置 + 本机实测路径
    foreach ($p in @(
        'E:\softward\blender5.12\blender.exe',
        'C:\Program Files\Blender Foundation\Blender 5.1\blender.exe',
        'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe',
        'C:\Program Files\Blender Foundation\Blender 4.5\blender.exe',
        'C:\Program Files\Blender Foundation\Blender 4.4\blender.exe',
        'C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe',
        'C:\ProgramData\chocolatey\bin\blender.exe',
        (Join-Path $env:USERPROFILE 'scoop\apps\blender\current\blender.exe')
    )) {
        $candidates.Add($p)
    }

    # Program Files / LocalAppData 下的任意版本
    foreach ($root in @(
        'C:\Program Files\Blender Foundation',
        'C:\Program Files (x86)\Blender Foundation',
        (Join-Path $env:LOCALAPPDATA 'Programs\Blender Foundation')
    )) {
        if (Test-Path $root) {
            Get-ChildItem $root -Filter blender.exe -Recurse -Depth 3 -ErrorAction SilentlyContinue |
                ForEach-Object { $candidates.Add($_.FullName) }
        }
    }

    foreach ($c in $candidates) {
        if ([string]::IsNullOrWhiteSpace($c)) { continue }
        if (Test-Path -LiteralPath $c) {
            return (Resolve-Path -LiteralPath $c).Path
        }
    }
    return $null
}

function Resolve-Python {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { return @($cmd.Source) }
    $cmd = Get-Command py -ErrorAction SilentlyContinue
    if ($cmd) { return @($cmd.Source, '-3') }
    return $null
}

try {
    $svgPath = (Resolve-Path -LiteralPath $Svg).Path
    if (-not (Test-Path -LiteralPath $OutDir)) {
        New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
    }
    $outPath = (Resolve-Path -LiteralPath $OutDir).Path

    $blender = Resolve-Blender -Explicit $BlenderExe
    if (-not $blender) {
        Write-Host "找不到 Blender。任选一种配置：" -ForegroundColor Red
        Write-Host "  1) 传参：-BlenderExe `"E:\softward\blender5.12\blender.exe`""
        Write-Host "  2) 环境变量：`$env:DSH_BLENDER_EXE = `"E:\softward\blender5.12\blender.exe`""
        Write-Host "  3) DSH 配置：%USERPROFILE%\.dsh\dsh-blender.config.json 里写 {`"blenderExe`": `"...\\blender.exe`"}"
        exit 3
    }

    Write-Host "SVG    : $svgPath"
    Write-Host "输出   : $outPath"
    Write-Host "Blender: $blender"
    Write-Host "模式   : $(if ($Quick) { 'quick（只出 clay）' } else { '完整（clay + render + closeup）' })"
    if ($Pose) { Write-Host "姿态   : POSE=$Pose$(if ($FlipUp) { ' + FlipUp' })" }

    if (-not $SkipPreflight) {
        $preflight = Join-Path $PSScriptRoot 'preflight.py'
        if (Test-Path -LiteralPath $preflight) {
            $python = @(Resolve-Python)
            if ($python.Count -gt 0 -and $python[0]) {
                Write-Host "`n--- preflight ---"
                $pyExe = [string]$python[0]
                $pyArgs = @()
                if ($python.Count -gt 1) { $pyArgs = @($python[1..($python.Count - 1)]) }
                $prevEap = $ErrorActionPreference
                $ErrorActionPreference = 'Continue'
                try {
                    $preOut = & $pyExe @pyArgs $preflight $svgPath 2>&1
                    $preCode = $LASTEXITCODE
                } finally {
                    $ErrorActionPreference = $prevEap
                }
                $preOut | ForEach-Object { Write-Host $_ }
                if ($preCode -ne 0) {
                    Write-Host "`n预检失败：先按上面的 errors 修 SVG，不要直接跑 Blender。" -ForegroundColor Red
                    exit 2
                }
            } else {
                Write-Host "WARN 找不到 python/py，跳过 preflight" -ForegroundColor Yellow
            }
        } else {
            Write-Host "WARN 找不到 preflight.py，跳过预检" -ForegroundColor Yellow
        }
    }

    $buildScript = Join-Path $PSScriptRoot 'build_box.py'
    if (-not (Test-Path -LiteralPath $buildScript)) {
        Write-Host "找不到 build_box.py：$buildScript" -ForegroundColor Red
        exit 3
    }

    $blenderArgs = @('-b', '-P', $buildScript, '--', $svgPath, $outPath)
    if ($Quick) { $blenderArgs += '--quick' }
    if ($Pose) { $blenderArgs += "--pose=$Pose" }
    if ($FlipUp) { $blenderArgs += '--flip-up' }

    $logPath = Join-Path $outPath 'run.log'
    Write-Host "`n--- blender ---"
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $raw = & $blender @blenderArgs 2>&1 | Tee-Object -FilePath $logPath
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $prevEap
    }

    $lines = @($raw | ForEach-Object { $_.ToString() })
    $reportLine = $lines | Where-Object { $_ -match '^REPORT ' } | Select-Object -Last 1
    if ($reportLine) {
        Write-Host "`n$reportLine"
    }

    if ($code -ne 0) {
        Write-Host "`nBlender 失败，退出码 $code。日志：$logPath" -ForegroundColor Red
        $lines | Select-Object -Last 40 | ForEach-Object { Write-Host $_ }
        exit $code
    }

    $required = @('clay.png', 'report.json', 'carton.blend')
    if (-not $Quick) { $required += @('render.png', 'closeup_crease.png') }
    $missing = @($required | Where-Object {
        -not (Test-Path -LiteralPath (Join-Path $outPath $_))
    })
    if ($missing.Count -gt 0) {
        Write-Host "`n缺少输出：$($missing -join ', ')" -ForegroundColor Red
        Write-Host "看日志：$logPath"
        exit 4
    }

    $reportPath = Join-Path $outPath 'report.json'
    if (Test-Path -LiteralPath $reportPath) {
        $rep = Get-Content -LiteralPath $reportPath -Raw -Encoding UTF8 | ConvertFrom-Json
        Write-Host ("`n模式: {0} | 轮廓: {1} | 面片: {2} | 折线: {3}/{4} | 进树: {5}/{6} | 尺寸: {7} x {8} x {9} mm" -f `
            $rep.mode, $rep.contours_from_svg, $rep.pieces_from_svg,
            $rep.folds_matched, $rep.folds_in_svg,
            $rep.faces_in_tree, $rep.pieces_from_svg,
            $rep.size_mm.dx, $rep.size_mm.dy, $rep.size_mm.dz)
        if ($null -ne $rep.folds_unmatched -and $rep.folds_unmatched -ne 0) {
            Write-Host "几何检查失败：有 $($rep.folds_unmatched) 条折线没配上。" -ForegroundColor Red
            exit 5
        }
        if ($null -ne $rep.faces_in_tree -and $rep.faces_in_tree -ne $rep.pieces_from_svg) {
            Write-Host "几何检查失败：$($rep.faces_in_tree)/$($rep.pieces_from_svg) 块面片进树。" -ForegroundColor Red
            exit 5
        }
    }

    if ($Quick) {
        Write-Host "`nQuick 完成：只出了 clay.png / report.json / carton.blend；" -ForegroundColor Yellow
        Write-Host "确认几何没问题后，去掉 -Quick 再跑完整渲染。" -ForegroundColor Yellow
    } else {
        Write-Host "`n完成：$outPath" -ForegroundColor Green
    }
    Write-Host "日志：$logPath"
    exit 0
} catch {
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
