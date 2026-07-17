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
    # PySide6 PINNED to the version proven to load on this machine (dev env). Unpinned install
    # pulled 6.11.1 whose Qt6Core.dll fails to load here (WinError 127) -> PyInstaller's Qt hook
    # only WARNS, collects ZERO plugins (no qwindows.dll) and the build still exits 0 -> frozen
    # GUI dies with "no Qt platform plugin". Bump the pin only after proving the new version
    # imports in the build venv: .venv-build\Scripts\python -c "from PySide6 import QtCore"
    Write-Host "Installing build deps (pyside6==6.9.2 astropy numpy pyinstaller; NO pytest)..." -ForegroundColor Cyan
    & $py -m pip install --disable-pip-version-check -q pyside6==6.9.2 astropy numpy pyinstaller
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

# 5. TRIPWIRE: exe presence is NOT enough. If PySide6 fails to import inside the build venv,
#    PyInstaller's Qt hook degrades to a WARNING and ships a dist WITHOUT Qt plugins -- the GUI
#    then fails at startup with "no Qt platform plugin could be initialized". Assert the one
#    file that proves plugin collection worked.
$qwindows = Join-Path $distDir "_internal\PySide6\plugins\platforms\qwindows.dll"
if (-not (Test-Path $qwindows)) {
    throw "Qt platform plugin MISSING (qwindows.dll not in dist) -- Qt hook collected no plugins; check that PySide6 imports in .venv-build"
}
Write-Host "OK -> Qt platform plugin present (qwindows.dll)" -ForegroundColor Green

# 6. SMOKE: actually start the frozen GUI (offscreen, no window) and require it to survive 6 s.
#    Catches runtime-only failures that build exit codes never see (missing plugin, ImportError).
$env:QT_QPA_PLATFORM = "offscreen"
$gui = Start-Process -FilePath (Join-Path $distDir "horreum-gui.exe") -PassThru
Start-Sleep -Seconds 6
Remove-Item Env:QT_QPA_PLATFORM
if ($gui.HasExited) {
    throw ("Frozen GUI exited immediately (code {0}) -- startup smoke FAILED" -f $gui.ExitCode)
}
Stop-Process -Id $gui.Id -Force
Write-Host "OK -> frozen GUI startup smoke passed (offscreen, 6 s alive)" -ForegroundColor Green

Write-Host "Build complete: dist\horreum\ (zip this folder to distribute)" -ForegroundColor Green
