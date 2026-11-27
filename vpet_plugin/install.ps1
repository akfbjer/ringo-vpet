param(
    [Parameter(Mandatory=$true)][string]$VPetDir
)
$ErrorActionPreference = 'Stop'
$source = Join-Path $PSScriptRoot 'bin\Debug\net10.0-windows\VPet.Ringo.dll'
if (-not (Test-Path -LiteralPath $source)) { throw '请先编译插件 DLL。' }
$modRoot = Join-Path $VPetDir 'mod'
if (-not (Test-Path -LiteralPath $modRoot)) { throw "未找到 VPet MOD 目录：$modRoot" }
$target = Join-Path $modRoot '1200_RingoVPet'
$plugin = Join-Path $target 'plugin'
New-Item -ItemType Directory -Force -Path $plugin | Out-Null
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'package\RingoVPet\info.lps') -Destination (Join-Path $target 'info.lps') -Force
Copy-Item -LiteralPath $source -Destination (Join-Path $plugin 'VPet.Ringo.dll') -Force
Write-Host "已安装插件到 $target"
