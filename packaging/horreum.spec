# -*- mode: python ; coding: utf-8 -*-
"""Spec PyInstaller dla Horreum (Windows) — DWA exe w jednym folderze onedir.

Build:   patrz packaging/build.ps1 (czysty .venv-build, BEZ pytest)
Wynik:   dist/horreum/horreum-gui.exe  (GUI, windowed)
         dist/horreum/horreum.exe      (CLI, console)
         dist/horreum/_internal/       (współdzielone Qt + astropy + dane)

== DLACZEGO DWA Analysis, JEDNA COLLECT (recenzja krok 7 #3) ==

GUI i CLI to dwa różne skrypty entry o RÓŻNYM `console` (windowed vs konsola) → dwa `EXE`
(`console` to kwarg `EXE`, nie `COLLECT` — legalne w PyInstaller 6.x). Jedna `COLLECT`
zbiera binaria/dane OBU i DEDUPUJE identyczny dest-path → Qt/astropy lądują w `_internal/`
RAZ, nie ×2 (oba Analysis kładą je pod tę samą względną ścieżkę). `MERGE()` świadomie
NIEUŻYTE: dokłada kruche cross-exe zależności ścieżkowe dla zysku, który daje już dedup
pojedynczej COLLECT.

== ASSETY CZYTANE PRZEZ importlib.resources (recenzja #1 — inaczej runtime pada cicho) ==

Rdzeń czyta migracje i katalog przez `resources.files("horreum.schema.migrations")` (db.py)
i `resources.files("horreum.resolve.data")` (resolve/catalog.py) — WYŁĄCZNIE literałem stringa.
Graf Analysis nie idzie po stringu → `collect_data_files` wnosi DANE (.sql/.json), ale
`hiddenimports` musi jawnie wnieść `__init__` tych dwóch pakietów, inaczej `resources.files(pkg)`
robi `import_module` → `ModuleNotFoundError` we frozen. Reszta rdzenia wchodzi normalnym grafem
importu z entry-skryptów (gui.app / cli). Słowniki solar/komety/obserwatorium = KOD (nie JSON).

== CZYSTE SRODOWISKO BUDUJACE (lekcja fitsmirror.spec — patrz build.ps1) ==

Build MUSI iść z venv BEZ pytest: `hook-astropy` robi `collect_submodules('astropy')` →
`wcsaxes` → `pytest.importorskip("matplotlib")`; pytest obecny + matplotlib brak → `Skipped`
→ collect nie łapie → Analysis pada. `excludes` niżej = GUARD (rozbraja kaskadę fsspec/holoviz
u korzenia, gdyby ktoś zbudował w brudnym env); w czystym venv większość to no-opy.
"""

import os

from PyInstaller.utils.hooks import collect_data_files

# SPECPATH = katalog tego pliku (packaging/); korzeń repo o poziom wyżej.
REPO_ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

# Dane astropy (erfa/IERS) + assety pakietu horreum (.sql migracje, .json katalog).
# collect_data_files zachowuje strukturę pakietu → importlib.resources czyta z _internal/horreum/...
datas = collect_data_files("astropy")
datas += collect_data_files("horreum", includes=["**/*.sql", "**/*.json"])

# astropy.io.fits = jedyny używany submoduł; pakiety-data referowane tylko stringiem (#1):
# migracje .sql, katalog .json, oraz asset mapy stanowisk .json (F8 — `resources.files(pkg)`).
hiddenimports = [
    "astropy.io.fits",
    "horreum.schema.migrations",
    "horreum.resolve.data",
    "horreum.gui.assets",
]

# GUARD: rozbraja kaskadę przerostu w brudnym env (fsspec/holoviz/jupyter) + inne wiązania Qt.
# W czystym .venv-build to no-opy poza tkinter/matplotlib (stdlib/nieużywane). NIE wykluczać
# numpy — astropy go wymaga.
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

# pathex = korzeń repo (backstop #2): PyInstaller dokłada do path kat. entry-skryptu
# (horreum/gui/), NIE korzeń → bez tego `import horreum` padłby w Analysis. build.ps1 dodatkowo
# robi `pip install -e .`, więc to pas bezpieczeństwa.
_common = dict(
    pathex=[REPO_ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

# CLI przez launcher packaging/cli_entry.py: cli.py ma importy WZGLĘDNE (`from . import db`),
# które padają, gdy PyInstaller bierze go jako goły skrypt entry (brak kontekstu pakietu).
# GUI: gui/__main__.py używa już importu absolutnego → wprost.
a_gui = Analysis([os.path.join(REPO_ROOT, "horreum", "gui", "__main__.py")], **_common)
a_cli = Analysis([os.path.join(SPECPATH, "cli_entry.py")], **_common)

pyz_gui = PYZ(a_gui.pure, a_gui.zipped_data)
pyz_cli = PYZ(a_cli.pure, a_cli.zipped_data)

exe_gui = EXE(
    pyz_gui,
    a_gui.scripts,
    [],
    exclude_binaries=True,
    name="horreum-gui",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,   # windowed: brak okna konsoli i brak pułapki cp1250 na stdout
    disable_windowed_traceback=False,
)

exe_cli = EXE(
    pyz_cli,
    a_cli.scripts,
    [],
    exclude_binaries=True,
    name="horreum",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,    # CLI drukuje na stdout (delta / --version)
    disable_windowed_traceback=False,
)

# Jedna COLLECT → jedno dist/horreum/ z _internal/ współdzielonym przez oba exe (dedup dest-path).
coll = COLLECT(
    exe_gui,
    a_gui.binaries,
    a_gui.datas,
    exe_cli,
    a_cli.binaries,
    a_cli.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="horreum",
)
