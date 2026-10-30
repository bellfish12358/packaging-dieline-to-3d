# -*- coding: utf-8 -*-
<#
把当前 skill 安装到 DSH 的 skills 目录。

用法：
  powershell -ExecutionPolicy Bypass -File install.ps1
  powershell -ExecutionPolicy Bypass -File install.ps1 -Force

默认安装到：C:\Users\<你>\.agents\skills\packaging-dieline-to-3d
已存在同名目录时：
  - 不加 -Force：停下来，不覆盖
  - 加 -Force：先改名备份，再复制

安装后新开一个 DSH 会话，skill 会被自动发现。
#>
[CmdletBinding()]
param(
    [string]$TargetRoot = (Join-Path $env:USERPROFILE '.agents\skills'),
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
} catch { }

$src = $PSScriptRoot
$name = Split-Path -Path $src -Leaf
$dst = Join-Path $TargetRoot $name

Write-Host "源目录  : $src"
Write-Host "目标目录: $dst"

if (-not (Test-Path -LiteralPath $TargetRoot)) {
    New-Item -ItemType Directory -Force -Path $TargetRoot | Out-Null
}

if (Test-Path -LiteralPath $dst) {
    if (-not $Force) {
        Write-Host "目标已存在。确认要覆盖时加 -Force；脚本会先备份旧目录。" -ForegroundColor Yellow
        exit 2
    }
    $bakName = "$name.bak-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
    $bakPath = Join-Path $TargetRoot $bakName
    Rename-Item -LiteralPath $dst -NewName $bakName
    Write-Host "已备份旧版: $bakPath" -ForegroundColor Yellow
}

Copy-Item -LiteralPath $src -Destination $dst -Recurse -Force
Write-Host "已安装: $dst" -ForegroundColor Green
Write-Host ""
Write-Host "下一步："
Write-Host "  1. 新开一个 DSH 会话（skill 在会话启动时加载）"
Write-Host "  2. 说：用 packaging-dieline-to-3d，把 <刀版.svg> 做成 3D，输出到 <目录>，先 Quick 验几何"
Write-Host "  3. 如果 Blender 路径没配，编辑 ~/.dsh/dsh-blender.config.json 的 blenderExe"
exit 0
