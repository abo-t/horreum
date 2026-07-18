# make-installer.ps1 -- build the per-user Horreum installer (Horreum-Setup-<ver>.exe).
# ASCII-ONLY (Windows PowerShell 5.1 reads .ps1 in ANSI; non-ASCII corrupts the parser).
#
# Wraps the frozen dist\horreum\ (from build.ps1) into a single NSIS Setup.exe --
# same distribution pattern as mentor-flux, adapted for a per-user hobby install.
# Uses makensis from the electron-builder NSIS cache (no separate NSIS install).
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File packaging\make-installer.ps1

param([string]$Version)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

# Version is single-sourced from horreum\__init__.py (SPOT) unless passed explicitly.
if (-not $Version) {
    $m = Select-String -Path "horreum\__init__.py" -Pattern '__version__\s*=\s*"([^"]+)"'
    if (-not $m) { throw "Nie moge odczytac __version__ z horreum\__init__.py" }
    $Version = $m.Matches[0].Groups[1].Value
}
Write-Host "Wersja: $Version" -ForegroundColor Cyan

$makensis = Join-Path $env:LOCALAPPDATA "electron-builder\Cache\nsis\nsis-3.0.4.1-nsis-3.0.4.1\Bin\makensis.exe"
if (-not (Test-Path $makensis)) { throw "makensis nie znaleziony: $makensis" }
if (-not (Test-Path "dist\horreum\horreum-gui.exe")) {
    throw "Brak frozen dist\horreum\horreum-gui.exe -- najpierw uruchom packaging\build.ps1"
}

New-Item -ItemType Directory -Force "release" | Out-Null

Write-Host "Buduje instalator (makensis)..." -ForegroundColor Cyan
& $makensis "/DVERSION=$Version" "/DROOT=$repo" "packaging\horreum-installer.nsi"
if ($LASTEXITCODE -ne 0) { throw "makensis zwrocil kod $LASTEXITCODE" }

$out = "release\Horreum-Setup-$Version.exe"
if (-not (Test-Path $out)) { throw "Instalator nie powstal: $out" }
$mb = [math]::Round((Get-Item $out).Length / 1MB, 1)
Write-Host ("OK -> {0} ({1} MB)" -f $out, $mb) -ForegroundColor Green
