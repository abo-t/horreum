"""Kontrola NIEZALEŻNA pilotażu zapisu w miejscu (O5) - poza pisarzem, poza bazą (astra Z9/Z16).

Weryfikacja pisarza (`writeback._verify_inplace`) to odczyt KLIENTA: osobny uchwyt tej samej
maszyny, który może przyjść z pamięci podręcznej systemu. Ten skrypt daje kontrolę, której pisarz
dać nie może: pełną kopię lokalną każdego pliku pilotażu sprzed zapisu i porównanie CAŁEGO pliku po
zapisie z PLANEM. Niezależność od pamięci podręcznej daje dopiero uruchomienie `po` z drugiego
komputera albo po restarcie - sam skrypt tego nie dowodzi.

Tryby (pliki pilotażu czytane WYŁĄCZNIE do odczytu):

  przed KATALOG_KOPII PLAN.json
      PLAN.json = lista `{"plik": ścieżka, "object": oczekiwana forma karty OBJECT}`. Pełna kopia
      każdego pliku do KATALOG_KOPII (lokalny dysk, NIE udział z oryginałami), sha1 oryginału i kopii
      (muszą być równe), rozmiar, `st_ino`, granice nagłówka, karty → manifest.json.
  po KATALOG_KOPII
      dla każdego pliku: rozmiar i `st_ino` bez zmian, bajty POZA regionem nagłówka identyczne z kopią
      (cały plik), nagłówek parsowalny, a różnice kart ZGODNE Z PLANEM: zmieniła się wyłącznie
      wartość karty OBJECT, na formę z planu, a jej komentarz został. Każda inna różnica kart - błąd.
      Własności XML XISF (np. `Observation:Object:Name`) nie są porównywane - to granica kontroli.
      Kod wyjścia 1 przy którymkolwiek NIE.
  po-undo KATALOG_KOPII
      po cofnięciu pilotażu: sha1 CAŁEGO pliku == sha1 sprzed pilotażu i ten sam `st_ino`.
  blokada KATALOG_TESTOWY
      pomiar blokady `writeback._exclusive` na udziale: tworzy WŁASNE pliki testowe (unikalna nazwa,
      tworzenie wyłączne `xb`), trzyma blokadę i sprawdza, że zapis z INNEGO procesu, drugie
      otwarcie do zapisu, usunięcie i `os.replace` na plik są odrzucane, a odczyt działa; sprząta
      wyłącznie swoje pliki. Odmawia drzewa archiwum `R:\\ASTRO_`.

Wynik na stdout (ASCII), manifest i raport JSON w KATALOG_KOPII."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

from astropy.io import fits

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from horreum import scan, writeback  # noqa: E402

ARCHIWUM = "R:\\ASTRO_"


def _sha1(path):
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        for kawalek in iter(lambda: fh.read(1 << 20), b""):
            h.update(kawalek)
    return h.hexdigest()


def _granice(path):
    """(początek, koniec) regionu nagłówka, który wolno zmienić: FITS `[hdrLoc, datLoc)` wybranego
    HDU, XISF `[0, first_attachment)`."""
    if os.path.splitext(path)[1].lower() in scan.XISF_SUFFIXES:
        return 0, scan.read_xisf_meta_full(path).first_attachment
    with fits.open(path, mode="readonly", memmap=False) as hdul:
        index, _ = scan._select_hdu(hdul)
        info = hdul.fileinfo(index)
        return info["hdrLoc"], info["datLoc"]


def _karty(path):
    rec = scan.scan_file(path)
    return {f"{c.keyword}[{c.idx}]": [c.value_raw, c.comment] for c in (rec.cards or [])}, rec.error


def przed(katalog, plan_json):
    katalog = Path(katalog)
    katalog.mkdir(parents=True, exist_ok=True)
    plan = json.loads(Path(plan_json).read_text(encoding="utf-8"))
    manifest = []
    for i, pozycja in enumerate(plan):
        p = os.path.abspath(pozycja["plik"])
        kopia = katalog / f"{i:04d}{os.path.splitext(p)[1]}"
        shutil.copyfile(p, kopia)
        st = os.stat(p)
        karty, _ = _karty(p)
        wpis = {"plik": p, "kopia": str(kopia), "sha1": _sha1(p), "sha1_kopii": _sha1(kopia),
                "rozmiar": st.st_size, "ino": st.st_ino, "granice": list(_granice(p)),
                "object": pozycja["object"], "karty": karty}
        if wpis["sha1"] != wpis["sha1_kopii"]:
            raise SystemExit(f"KOPIA NIEZGODNA: {p}")
        manifest.append(wpis)
        print(f"przed OK {p} sha1={wpis['sha1']}")
    (katalog / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")


def _porownaj_poza(plik, kopia, a, b):
    """Czy bajty pliku poza [a, b) są identyczne z kopią (cały plik, strumieniowo)."""
    with open(plik, "rb") as f1, open(kopia, "rb") as f2:
        pozycja = 0
        while True:
            x, y = f1.read(1 << 20), f2.read(1 << 20)
            if not x and not y:
                return True
            if len(x) != len(y):
                return False
            if x != y:
                for k in range(len(x)):
                    if x[k] != y[k] and not (a <= pozycja + k < b):
                        return False
            pozycja += len(x)


def _zmiany_zgodne_z_planem(przed_karty, po_karty, forma):
    """Różnice kart dozwolone przez plan: wyłącznie OBJECT[0] → `forma`, komentarz bez zmian."""
    rozne = {k for k in set(przed_karty) | set(po_karty) if przed_karty.get(k) != po_karty.get(k)}
    if rozne - {"OBJECT[0]"}:
        return False, sorted(rozne)
    if "OBJECT[0]" in rozne:
        stara, nowa = przed_karty.get("OBJECT[0]"), po_karty.get("OBJECT[0]")
        if stara is None or nowa is None or nowa[0] != forma or nowa[1] != stara[1]:
            return False, sorted(rozne)
    return True, sorted(rozne)


def po(katalog):
    katalog = Path(katalog)
    manifest = json.loads((katalog / "manifest.json").read_text(encoding="utf-8"))
    raport, zle = [], 0
    for w in manifest:
        st = os.stat(w["plik"])
        a, b = w["granice"]
        karty_po, blad = _karty(w["plik"])
        zgodne, zmiany = _zmiany_zgodne_z_planem(w["karty"], karty_po, w["object"])
        wynik = {"plik": w["plik"], "sha1_po": _sha1(w["plik"]),
                 "rozmiar_ok": st.st_size == w["rozmiar"], "ino_ok": st.st_ino == w["ino"],
                 "dane_ok": _porownaj_poza(w["plik"], w["kopia"], a, b),
                 "naglowek_ok": blad is None, "zmiany_zgodne_z_planem": zgodne,
                 "zmienione_karty": zmiany}
        ok = all(wynik[k] for k in ("rozmiar_ok", "ino_ok", "dane_ok", "naglowek_ok",
                                    "zmiany_zgodne_z_planem"))
        zle += not ok
        raport.append(wynik)
        print(f"po {'OK ' if ok else 'NIE'} {w['plik']} zmiany={json.dumps(zmiany, ensure_ascii=True)}")
    (katalog / "raport_po.json").write_text(json.dumps(raport, indent=1, ensure_ascii=False),
                                            encoding="utf-8")
    return 1 if zle else 0


def po_undo(katalog):
    manifest = json.loads((Path(katalog) / "manifest.json").read_text(encoding="utf-8"))
    zle = 0
    for w in manifest:
        ok = _sha1(w["plik"]) == w["sha1"] and os.stat(w["plik"]).st_ino == w["ino"]
        zle += not ok
        print(f"po-undo {'OK ' if ok else 'NIE'} {w['plik']}")
    return 1 if zle else 0


_INNY_PROCES = ("import sys\n"
                "try:\n"
                "    open(sys.argv[1], 'r+b').write(b'X')\n"
                "    print('NIE odrzucone')\n"
                "except PermissionError:\n"
                "    print('odrzucone')\n")


def blokada(katalog):
    """Pomiar blokady na udziale testowym. Zwraca dict wyników z kluczem `kod` (0 = wszystko OK)."""
    katalog = os.path.abspath(katalog)
    if os.path.normcase(katalog).startswith(os.path.normcase(ARCHIWUM)):
        raise SystemExit(f"odmowa: {ARCHIWUM} to drzewo archiwum - pomiar tylko poza nim")
    znacznik = f"{os.getpid()}_{uuid.uuid4().hex}"
    p = Path(katalog) / f"horreum_proba_blokady_{znacznik}.bin"
    zapas = Path(katalog) / f"horreum_proba_podmiany_{znacznik}.bin"
    moje = []
    wyniki = {}
    try:
        for plik, bajt in ((p, b"\x00"), (zapas, b"\x01")):
            with open(plik, "xb") as fh:                   # wyłącznie NOWY plik - nie cudzy
                fh.write(bajt * 8192)
            moje.append(plik)
        ino = os.stat(p).st_ino
        with writeback._exclusive(str(p)) as fh:
            for nazwa, proba in (("drugie otwarcie do zapisu", lambda: open(p, "r+b").close()),
                                 ("usuniecie", lambda: os.remove(p)),
                                 ("os.replace na plik", lambda: os.replace(zapas, p))):
                try:
                    proba()
                    wyniki[nazwa] = "NIE odrzucone - blokada NIE dziala"
                except PermissionError:
                    wyniki[nazwa] = "odrzucone"
            wyniki["zapis z INNEGO procesu"] = subprocess.run(
                [sys.executable, "-c", _INNY_PROCES, str(p)], capture_output=True,
                text=True).stdout.strip()
            wyniki["odczyt osobnym uchwytem"] = "dziala" if p.read_bytes()[:1] == b"\x00" \
                else "NIE dziala"
            fh.seek(0)
            fh.write(b"\x02")
            fh.flush()
            os.fsync(fh.fileno())
        wyniki["zapis wlasnym uchwytem"] = "dziala" if p.read_bytes()[:1] == b"\x02" \
            else "NIE dziala"
        wyniki["st_ino stabilny"] = "tak" if os.stat(p).st_ino == ino and ino else "NIE"
    finally:
        for plik in moje:                                  # sprzątanie WYŁĄCZNIE własnych plików
            if plik.exists():
                os.remove(plik)
    dobre = {"odrzucone", "dziala", "tak"}
    wyniki["kod"] = 0 if all(v in dobre for v in wyniki.values()) else 1
    for k, v in wyniki.items():
        print(f"blokada {k}: {v}")
    return wyniki


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    tryb = sys.argv[1]
    if tryb == "przed" and len(sys.argv) == 4:
        przed(sys.argv[2], sys.argv[3])
    elif tryb == "po":
        sys.exit(po(sys.argv[2]))
    elif tryb == "po-undo":
        sys.exit(po_undo(sys.argv[2]))
    elif tryb == "blokada":
        sys.exit(blokada(sys.argv[2])["kod"])
    else:
        raise SystemExit(__doc__)
