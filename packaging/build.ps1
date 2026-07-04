# build.ps1 -- freeze Horreum to dist/horreum/ (GUI + CLI, onedir).
# ASCII-ONLY on purpose: Windows PowerShell 5.1 reads .ps1 in ANSI cp1250; non-ASCII
# (Polish) chars corrupt to mojibake and break the parser before any command runs.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1            # full build
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -SkipDeps  # reuse .venv-build
#
# The build MUST run from a clean venv WITHOUT pytest (see packaging\horreum.spec docstring:
# pytest present + matplotlib absent makes hook-astropy crash Analysis).

param([switch]$SkipDeps)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

$venv = Join-Path $repo ".venv-build"
$py   = Join-Path $venv "Scripts\python.exe"

# 1. Clean build venv (gitignored). Created once; deps installed unless -SkipDeps.
if (-not (Test-Path $py)) {
    Write-Host "Creating clean build venv (.venv-build)..." -ForegroundColor Cyan
    python -m venv $venv
    if (-not $?) { throw "venv creation failed" }
    $SkipDeps = $false
}

if (-not $SkipDeps) {
    Write-Host "Installing build deps (pyside6 astropy numpy pyinstaller; NO pytest)..." -ForegroundColor Cyan
    & $py -m pip install --disable-pip-version-check -q pyside6 astropy numpy pyinstaller
    if (-not $?) { throw "pip install (build deps) failed" }
    # Install horreum itself so `import horreum` resolves during Analysis (entry script lives
    # in horreum\gui\, not repo root -> PyInstaller path would miss the package otherwise).
    Write-Host "Installing horreum (editable) into build venv..." -ForegroundColor Cyan
    & $py -m pip install --disable-pip-version-check -q -e .
    if (-not $?) { throw "pip install -e . failed" }
}

# 2. A running exe holds an exclusive lock on its own file -> cleanup would fail. Kill first.
foreach ($name in @("horreum-gui", "horreum")) {
    $proc = Get-Process -Name $name -ErrorAction SilentlyContinue
    if ($proc) {
        Write-Host "Stopping running $name.exe (locks its own file)..." -ForegroundColor Yellow
        $proc | Stop-Process -Force
    }
}

# 3. Freeze. --clean drops PyInstaller cache; --noconfirm overwrites dist without prompting.
Write-Host "Running PyInstaller (packaging\horreum.spec)..." -ForegroundColor Cyan
& $py -m PyInstaller --clean --noconfirm packaging\horreum.spec
if (-not $?) { throw "PyInstaller build failed" }

# 4. Verify both artifacts exist and are fresh (< 5 min old).
$distDir = Join-Path $repo "dist\horreum"
$ok = $true
foreach ($exe in @("horreum-gui.exe", "horreum.exe")) {
    $path = Join-Path $distDir $exe
    if (Test-Path $path) {
        $age = ([DateTime]::Now - (Get-Item $path).LastWriteTime).TotalSeconds
        if ($age -lt 300) {
            Write-Host ("OK -> dist\horreum\{0} (fresh)" -f $exe) -ForegroundColor Green
        } else {
            Write-Host ("STALE -> dist\horreum\{0} ({1:N0}s old)" -f $exe, $age) -ForegroundColor Yellow
            $ok = $false
        }
    } else {
        Write-Host ("MISSING -> dist\horreum\{0}" -f $exe) -ForegroundColor Red
        $ok = $false
    }
}
if (-not $ok) { throw "Build did not produce both fresh exe" }
Write-Host "Build complete: dist\horreum\ (zip this folder to distribute)" -ForegroundColor Green
