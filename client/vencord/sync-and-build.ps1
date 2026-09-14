# Copies the plugin into a Vencord source checkout and rebuilds.
#
# The plugin's source of truth is this repo; the Vencord checkout is only a
# build environment. A junction was tried first and does not work: esbuild
# resolves it to the real path, which sits outside Vencord's tree, so the
# @api/* aliases stop resolving. Copying is what keeps the build honest.
param(
    [string]$Vencord = "C:\Claude-Projects\vencord-dev\Vencord"
)
$ErrorActionPreference = "Stop"

$source = Join-Path $PSScriptRoot "ghostPlay"
$target = Join-Path $Vencord "src\userplugins\ghostPlay"

if (-not (Test-Path (Join-Path $Vencord "package.json"))) {
    Write-Host "  No Vencord checkout at $Vencord" -ForegroundColor Red
    Write-Host "  Pass one with:  .\sync-and-build.ps1 -Vencord C:\path\to\Vencord"
    exit 1
}

New-Item -ItemType Directory -Force $target | Out-Null
Copy-Item "$source\*" $target -Force -Recurse
Write-Host "  Copied ghostPlay -> $target" -ForegroundColor Green

Push-Location $Vencord
try { pnpm build } finally { Pop-Location }

Write-Host ""
Write-Host "  Built. Restart Discord to pick it up." -ForegroundColor Green
Write-Host "  First time only:  pnpm inject   (from $Vencord)"
