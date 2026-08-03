"""Assety DANYCH rdzenia (katalog celów planera) — ładowane przez `importlib.resources`.

Pakiet jest CZYSTYMI DANYMI: zero importów, zero kodu. `targets_core.json` i `targets_cirrus.json`
produkuje `scripts/build_catalog.py` (jedyne miejsce w repo z siecią). Plik CZŁOWIEKA mieszka od
D-OW-1/E′ obok assetów resolvera (`horreum/resolve/data/objects_own.json`), bo czytają go dwie
warstwy naraz; skrypt go waliduje i NIGDY nie nadpisuje. Proweniencja i licencje: `PROVENANCE.md`.
"""
