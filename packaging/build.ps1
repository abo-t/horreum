# build.ps1 -- freeze Horreum: onedir (default; GUI + CLI) or -Onefile (single GUI exe).
# ASCII-ONLY on purpose: Windows PowerShell 5.1 reads .ps1 in ANSI cp1250; non-ASCII
# (Polish) chars corrupt to mojibake and break the parser before any command runs.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1            # onedir (NSIS path)
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -SkipDeps  # reuse .venv-build
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -Onefile   # RELEASE artifact:
#                                                                           # dist\horreum-gui.exe
#
# The build MUST run from a venv WITHOUT pytest (see packaging\horreum.spec docstring:
# pytest present + matplotlib absent makes hook-astropy crash Analysis). .venv-build doubles
# as the test battery, so pytest is USUALLY THERE -- the script asserts and tells you the
# non-destructive recipe instead of dying mid-Analysis with a cryptic hook error.
#
# -Onefile probes the WINDOW TITLE of the frozen exe (spawns a real, visible window for a few
# seconds): the onefile bootloader (parent) has an empty MainWindowTitle, the real app is the
# CHILD process, and its title must read "Horreum <version>" with the version taken from THIS
# venv's metadata. Measured 2026-08-01: stale metadata shipped "horreum 0.0.1" to the release
# path and tests/test_version.py did NOT catch it (it guards the dev env, not .venv-build).

param([switch]$SkipDeps, [switch]$Onefile)

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
}

# 1a. Editable install ALWAYS (even with -SkipDeps): it serves two masters. (a) `import horreum`
#     must resolve during Analysis (entry script lives in horreum\gui\, not repo root).
#     (b) importlib.metadata version frozen into the exe comes from THIS install -- a stale one
#     writes an old number into the artifact (measured 2026-08-01: "horreum 0.0.1").
Write-Host "Installing horreum (editable) into build venv..." -ForegroundColor Cyan
& $py -m pip install --disable-pip-version-check -q -e .
if (-not $?) { throw "pip install -e . failed" }

# 1b. GATE: pytest must be ABSENT. Present pytest + excluded matplotlib makes hook-astropy
#     (wcsaxes -> pytest.importorskip("matplotlib")) crash Analysis. .venv-build doubles as
#     the test battery, so this is the expected state to hit -- fail fast with the recipe.
& $py -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('pytest') else 1)"
if ($LASTEXITCODE -eq 0) {
    throw ("pytest is INSTALLED in .venv-build and would crash hook-astropy during Analysis. " +
           "Non-destructive recipe: .venv-build\Scripts\python -m pip uninstall -y pytest " +
           "-> build -> pip install pytest (battery comes back untouched).")
}
Write-Host "OK -> pytest absent from build venv (hook-astropy safe)" -ForegroundColor Green

# 2. A running exe holds an exclusive lock on its own file -> cleanup would fail. Kill first.
foreach ($name in @("horreum-gui", "horreum")) {
    $proc = Get-Process -Name $name -ErrorAction SilentlyContinue
    if ($proc) {
        Write-Host "Stopping running $name.exe (locks its own file)..." -ForegroundColor Yellow
        $proc | Stop-Process -Force
    }
}

if ($Onefile) {
    # 3F. Freeze the RELEASE artifact: single-file GUI exe (no CLI, no COLLECT).
    Write-Host "Running PyInstaller (packaging\horreum-onefile.spec)..." -ForegroundColor Cyan
    & $py -m PyInstaller --clean --noconfirm packaging\horreum-onefile.spec
    if (-not $?) { throw "PyInstaller build failed" }

    # 4F. Verify the artifact exists and is fresh (< 5 min old).
    $exePath = Join-Path $repo "dist\horreum-gui.exe"
    if (-not (Test-Path $exePath)) { throw "MISSING -> dist\horreum-gui.exe" }
    $age = ([DateTime]::Now - (Get-Item $exePath).LastWriteTime).TotalSeconds
    if ($age -ge 300) { throw ("STALE -> dist\horreum-gui.exe ({0:N0}s old)" -f $age) }
    Write-Host "OK -> dist\horreum-gui.exe (fresh)" -ForegroundColor Green

    # 5F. TITLE PROBE. Onefile has no _internal\qwindows.dll on disk to assert, so the exe must
    #     PROVE itself at runtime: start it (REAL window -- offscreen has no MainWindowTitle),
    #     find the CHILD process (the bootloader parent stays title-less), and require the
    #     child's window title to be exactly "Horreum <version>" from THIS venv's metadata.
    #     One probe kills three manual traps: wrong spec, dead exe, stale version metadata.
    $ver = (& $py -c "from importlib.metadata import version; print(version('horreum'))")
    if (-not $? -or -not $ver) { throw "cannot read horreum version from build venv metadata" }
    $expected = "Horreum $($ver.Trim())"
    Write-Host ("Probing window title (expect '{0}'; a window will flash)..." -f $expected) -ForegroundColor Cyan
    $gui = Start-Process -FilePath $exePath -PassThru
    $title = $null
    $child = $null
    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Milliseconds 500
        if ($gui.HasExited) {
            throw ("Frozen GUI exited immediately (code {0}) -- onefile smoke FAILED" -f $gui.ExitCode)
        }
        $child = Get-CimInstance Win32_Process -Filter "Name='horreum-gui.exe'" |
                 Where-Object { $_.ParentProcessId -eq $gui.Id }
        if ($child) {
            $cp = Get-Process -Id $child.ProcessId -ErrorAction SilentlyContinue
            if ($cp -and $cp.MainWindowTitle) { $title = $cp.MainWindowTitle; break }
        }
    }
    # Kill the CHILD first: stopping only the parent orphans the child (measured 2026-08-01).
    if ($child) { try { Stop-Process -Id $child.ProcessId -Force -ErrorAction Stop } catch {} }
    if (-not $gui.HasExited) { try { Stop-Process -Id $gui.Id -Force -ErrorAction Stop } catch {} }
    if ($title -ne $expected) {
        throw ("Window title probe FAILED: expected '{0}', got '{1}'" -f $expected, $title)
    }
    Write-Host ("OK -> child window title is '{0}'" -f $title) -ForegroundColor Green

    Write-Host "Build complete: dist\horreum-gui.exe (single-file release artifact)" -ForegroundColor Green
    exit 0
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
