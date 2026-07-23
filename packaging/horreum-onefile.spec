# -*- mode: python ; coding: utf-8 -*-
"""Spec PyInstaller dla Horreum (Windows) — GUI jako JEDEN samodzielny exe (onefile).

Build:   .venv-build\\Scripts\\python -m PyInstaller --clean --noconfirm packaging\\horreum-onefile.spec
Wynik:   dist/horreum-gui.exe   (GUI, windowed, wszystko w JEDNYM pliku)

== ROZNICA vs horreum.spec (onedir, DWA exe) ==

`horreum.spec` produkuje folder dist/horreum/ z GUI+CLI i wspoldzielonym _internal/ — pod niego
podpiety jest instalator NSIS. TEN spec robi JEDEN plik tylko z GUI (`--onefile`): Qt + astropy +
dane sa spakowane WEWNATRZ exe i rozpakowywane do %TEMP% przy kazdym uruchomieniu (stad start jest
wolniejszy niz onedir). CLI (horreum.exe) tu NIE powstaje — to droga dev/interim, poza „jeden exe".

Onefile = brak COLLECT: binaria i dane wchodza WPROST do EXE(a.binaries, a.datas), nie do folderu.

== ASSETY CZYTANE PRZEZ importlib.resources (inaczej runtime pada cicho) ==

Rdzen czyta migracje/katalog/mape przez `resources.files(pkg)` WYLACZNIE literalem stringa — graf
Analysis nie idzie po stringu, wiec `hiddenimports` musi jawnie wniesc te pakiety, a
`collect_data_files` ich DANE (.sql/.json). Identycznie jak w horreum.spec.

== CZYSTE SRODOWISKO BUDUJACE (.venv-build BEZ pytest) ==

pytest obecny + matplotlib brak => hook-astropy (`wcsaxes` -> `pytest.importorskip`) wywala
Analysis. `excludes` nizej rozbraja tez kaskade fsspec/holoviz. Buduj z .venv-build.
"""

import os

from PyInstaller.utils.hooks import collect_data_files

# SPECPATH = katalog tego pliku (packaging/); korzen repo o poziom wyzej.
REPO_ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

# Ikona aplikacji (astro: zlota gwiazda na nocnym tle).
ICON = os.path.join(SPECPATH, "horreum.ico")

# Dane astropy (erfa/IERS) + assety pakietu horreum (.sql migracje, .json katalog + mapa).
datas = collect_data_files("astropy")
datas += collect_data_files("horreum", includes=["**/*.sql", "**/*.json"])

# Pakiety referowane WYLACZNIE stringiem przez importlib.resources — graf ich nie widzi.
hiddenimports = [
    "astropy.io.fits",
    "horreum.schema.migrations",
    "horreum.resolve.data",
    "horreum.gui.assets",
]

# GUARD: rozbraja przerost w brudnym env (fsspec/holoviz/jupyter) + inne wiazania Qt.
# NIE wykluczac numpy — astropy go wymaga.
excludes = [
    "PyQt6", "PyQt5", "PySide2",
    "fsspec", "dask", "distributed",
    "panel", "holoviews", "bokeh", "plotly", "hvplot", "datashader", "intake",
    "jupyter", "jupyterlab", "jupyter_server", "notebook", "notebook_shim",
    "ipywidgets", "ipywidgets_bokeh", "IPython",
    "patchright", "playwright",
    "sklearn", "skimage", "sphinx", "statsmodels", "xarray",
    "babel", "h5py", "lxml", "psycopg2", "cryptography", "shapely",
    "mpi4py", "huggingface_hub", "win32com",
    "torch", "scipy", "pandas", "pyarrow", "sympy", "numba",
    "pytest",
    "tkinter", "matplotlib",
]

# pathex = korzen repo: entry-skrypt lezy w horreum/gui/, nie w korzeniu -> bez tego `import horreum`
# padlby w Analysis. build.ps1 dodatkowo robi `pip install -e .` (pas bezpieczenstwa).
a = Analysis(
    [os.path.join(REPO_ROOT, "horreum", "gui", "__main__.py")],
    pathex=[REPO_ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

# ONEFILE: binaria + dane wchodza WPROST do EXE (brak COLLECT) -> jeden dist/horreum-gui.exe.
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="horreum-gui",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,   # windowed: brak okna konsoli
    disable_windowed_traceback=False,
    icon=ICON,
)
