"""Okno „Wciągnij mastery…” - testy STERUJĄCE realnym oknem Qt (offscreen) na PRAWDZIWYM planie
i apply rdzenia (`harvest.plan`/`harvest.apply` + klinga `projection.copy_master`) na syntetycznej
bazie. Czytnik mastera jest wstrzykiwany (`harvest.read_master` podmieniany w module rdzenia,
skąd worker go bierze): testy nie czytają XISF, ale kopia, audyt bajtów, publikacja i zeznanie
`_ZNIWA_<ts>.json` idą po prawdziwych plikach w `tmp_path`. Workery inline (`off_thread=False`)
poza testami na prawdziwym `QThread` (sonda, apply, zamknięcie w trakcie obu). QSettings
izolowane od rejestru (conftest, fixture `ustawienia`)."""

import json
import os
import re
import sys
import threading
import time
from datetime import datetime
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QDeadlineTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from horreum import db, harvest, hashing, projection, repo, stacks
from horreum.gui import i18n
from horreum.gui import harvest_dialog as hd_mod
from horreum.gui.harvest_dialog import (
    _HARVEST_KINDS, _HARVEST_REASONS, _HARVEST_STATUS, _STACK_REASONS, COL_DIR, COL_FILE, COL_KIND,
    COL_NAME, COL_REASON, COL_RELEASE, COL_STATUS, REL_STATE, HarvestDialog, clean_path, common_root,
    find_manifest, is_harvested, is_under, needs_lineage, needs_review, preselect_index, reason_text, rel_text,
    release_date_text, release_roots_of, release_state_text, release_text,
)
from horreum.gui.i18n_catalog import CATALOG

NOW = "2026-10-10T12:00:00+00:00"
SEG = "76EDPH_ASI2600MM"                 # segment zestawu: `<teleskop>_<kamera>` z `zestawy_configow`
_PL_LITERY = re.compile(r"[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]")


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def wybor_katalogu(monkeypatch):
    """Okno wyboru katalogu podmienione w KAŻDYM teście: pierwsze użycie (brak pamięci wyjścia)
    otwiera je samo po pokazaniu okna, a prawdziwy `QFileDialog` w offscreen wisiałby bez końca.
    Domyślnie „Anuluj” (pusty wynik); test ustawia `odpowiedz` i czyta `wywolania`."""
    stan = SimpleNamespace(odpowiedz="", wywolania=[])

    def wybierz(parent, title, start=""):
        stan.wywolania.append((title, start))
        return stan.odpowiedz

    monkeypatch.setattr(hd_mod.QFileDialog, "getExistingDirectory", staticmethod(wybierz))
    return stan


# ---------------------------------------------------------------- baza i wyjście WBPP

def _flat_name(i, filt="CLS", day="2023-05-07"):
    return f"{day}_20-40-{i:02d}_{filt}_-11.90_0.08s_{i:04d}.fits"


def _baza(tmp_path, db_archive=None):
    """Kamera mono, teleskop, zestaw i profile flatu CLS/Ha; surowe flaty z jednej nocy
    z PRAWDZIWYMI ścieżkami (`location.path` - nazwa jest świadkiem wejścia mastera).
    `db_archive` = korzeń archiwum, które baza zna: jeden master flat CLS w
    `<db_archive>/CALIBRATION/masters/flats/<zestaw>/CLS`. Zwraca (con, profile, {nazwa: frame_id})."""
    con = db.open_db(str(tmp_path / "h.db"))
    con.execute("INSERT INTO camera (id, model_canon, is_mono, created_at) "
                "VALUES (1, 'ASI2600MM', 1, ?)", (NOW,))
    con.execute("INSERT INTO telescope (id, telescop_canon, label, status, created_at) "
                "VALUES (1, '76EDPH', NULL, 'proposed', ?)", (NOW,))
    con.execute("INSERT INTO config (id, telescope_id, camera_id, status, created_at) "
                "VALUES (10, 1, 1, 'proposed', ?)", (NOW,))
    con.commit()
    profile = {}
    for filt in ("CLS", "Ha"):
        pid, _ = repo.upsert_calibration_profile(
            con, profile_key=f"flat|cam=1|bin=1|tel=1|filt={filt}", recipe_class="flat",
            camera_id=1, xbinning=1, telescope_id=1, filter_canon=filt, now=NOW)
        profile[filt] = pid
    flats = {}
    for filt in ("CLS", "Ha"):
        for i in range(3):
            name = _flat_name(i, filt)
            path = tmp_path / "raw" / name
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(name.encode())
            cur = con.execute(
                "INSERT INTO frame (sha1_data, kind, filetype, camera_id, config_id, filter_canon, "
                "first_seen_at) VALUES (?, 'flat', 'fits', 1, 10, ?, ?)", (f"raw-{name}", filt, NOW))
            fid = cur.lastrowid
            con.execute("INSERT INTO header (frame_id, raw_json, date_obs, exptime, xbinning) "
                        "VALUES (?, '{}', ?, 0.08, 1)", (fid, f"2023-05-07T20:40:{i:02d}"))
            con.execute("INSERT INTO location (frame_id, volume, path, present) VALUES (?, 'V', ?, 1)",
                        (fid, str(path)))
            con.commit()
            repo.assign_calibration_profile(con, frame_id=fid, profile_id=profile[filt], now=NOW)
            flats[name] = fid
    if db_archive is not None:
        mf = (db_archive / "CALIBRATION" / "masters" / "flats" / SEG / "CLS"
              / "MASTERFLAT_FLATGRP_202201010_FILTER_CLS_.xisf")
        cur = con.execute(
            "INSERT INTO frame (sha1_data, kind, filetype, camera_id, config_id, filter_canon, "
            "first_seen_at) VALUES ('mf-archiwum', 'master_flat', 'xisf', 1, 10, 'CLS', ?)", (NOW,))
        con.execute("INSERT INTO location (frame_id, volume, path, present) VALUES (?, 'V', ?, 1)",
                    (cur.lastrowid, str(mf)))
        con.commit()
        repo.assign_calibration_profile(con, frame_id=cur.lastrowid, profile_id=profile["CLS"], now=NOW)
    return con, profile, flats


def _wejscie(name):
    """Ścieżka wejścia z historii WBPP: klatka skalibrowana `_c` w warsztacie (zmierzony kształt)."""
    stem = os.path.splitext(name)[0]
    return f"D:/WBPP/2023-05-07/FLAT/{stem}_c.xisf"


def _wyjscie(tmp_path, pliki, sub=("WBPP", "master")):
    """Katalog wyjścia WBPP z PRAWDZIWYMI plikami (`{nazwa: bajty}`); zwraca ścieżkę."""
    out = tmp_path.joinpath(*sub)
    out.mkdir(parents=True, exist_ok=True)
    for name, data in pliki.items():
        (out / name).write_bytes(data)
    return out


def _czytnik(monkeypatch, zeznania, gate=None, entered=None):
    """Podmień czytnik mastera w module rdzenia: `zeznania[basename]` = dict pól zeznania
    (`kind`, `inputs`, `filter_raw`, `xbinning`) albo wyjątek do rzucenia. `sha1_data` pochodzi od
    nazwy, `file_sha1` z PRAWDZIWYCH bajtów pliku - apply audytuje kopię dokładnie nimi.
    `gate`/`entered` (testy wątku sondy): czytnik zgłasza wejście i stoi, aż ktoś otworzy bramkę."""
    def czytaj(path, **_kw):
        if gate is not None:
            entered.set()
            gate.wait(10)
        z = zeznania[os.path.basename(path)]
        if isinstance(z, Exception):
            raise z
        return harvest.MasterTestimony(
            path=path, kind=z.get("kind", "master_flat"), header=z.get("header", {}),
            inputs_enabled=tuple(z.get("inputs", ())), rows=len(z.get("inputs", ())) or None,
            sha1_data=z.get("sha1_data", f"sd-{os.path.basename(path)}"),
            file_sha1=hashing.sha1_of(path), filter_raw=z.get("filter_raw", "CLS"),
            xbinning=z.get("xbinning", 1), date_obs=z.get("date_obs", "2023-05-07T21:00:00"),
            exptime=z.get("exptime"))
    monkeypatch.setattr(harvest, "read_master", czytaj)


def _flat_cls(n=3):
    return {"inputs": [_wejscie(_flat_name(i, "CLS")) for i in range(n)]}


def _flat_ha(n=3):
    return {"inputs": [_wejscie(_flat_name(i, "Ha")) for i in range(n)], "filter_raw": "H"}


def _dlg(con, archive, **kw):
    return HarvestDialog(con, now_fn=lambda: NOW, archive_root=str(archive),
                         off_thread=kw.pop("off_thread", False), **kw)


def _kol(dlg, row, col):
    return dlg.table.item(row, col).text()


def _wiersze(dlg):
    return {_kol(dlg, r, COL_FILE): r for r in range(dlg.table.rowCount())}


def _cel(archive, filt="CLS", seq=0):
    return (archive / "CALIBRATION" / "masters" / "flats" / SEG / filt
            / f"MASTERFLAT_FLATGRP_20230507{seq}_FILTER_{filt}_.xisf")


def _wait_until(pred, timeout_ms=10_000):
    """Pompuj pętlę zdarzeń, aż `pred()` (wynik wątku tła dolatuje sygnałem KOLEJKOWANYM)."""
    deadline = QDeadlineTimer(timeout_ms)
    while not pred():
        if deadline.hasExpired():
            return False
        QTest.qWait(10)
    return True


def _spy_progress(monkeypatch, hook=None):
    """Podgląd postępu apply przez PODKLASĘ workera; `hook(done_n, worker)` po każdej emisji."""
    seen = []

    class SpyWorker(hd_mod.HarvestApplyWorker):
        def _emit_progress(self, done_n, total, dst, status):
            super()._emit_progress(done_n, total, dst, status)
            seen.append((done_n, total, status))
            if hook is not None:
                hook(done_n, self)

    monkeypatch.setattr(hd_mod, "HarvestApplyWorker", SpyWorker)
    return seen


def _bramka_sondy(monkeypatch):
    """Sonda, która stoi w czytniku, aż przyjdzie anulowanie: podklasa workera DRY otwiera bramkę
    czytnika w `request_cancel`. Moment zamknięcia jest deterministyczny, nie wyścigiem z odczytem."""
    gate, entered = threading.Event(), threading.Event()

    class SpyDry(hd_mod.HarvestDryWorker):
        def request_cancel(self):
            super().request_cancel()
            gate.set()

    monkeypatch.setattr(hd_mod, "HarvestDryWorker", SpyDry)
    return gate, entered


def _parts(root):
    return list(root.rglob("*.part"))


def _zeznania(out):
    return sorted(out.glob(f"{projection.HARVEST_MANIFEST_PREFIX}_*.json"))


# ---------------------------------------------------------------- pomocniki Qt-wolne

def test_find_manifest_w_katalogu_i_do_czterech_poziomow(tmp_path):
    """Manifest wydania szukany w wyjściu i do 4 poziomów wyżej; najbliższy wygrywa, piąty poziom
    już nie świadczy, uszkodzony JSON to „nie wiem”, nie wyjątek."""
    deep = tmp_path / "a" / "b" / "c" / "d" / "e"
    deep.mkdir(parents=True)
    assert find_manifest(str(deep)) == (None, None)
    (tmp_path / projection.MANIFEST_NAME).write_text(json.dumps({"layout": "x"}), encoding="utf-8")
    assert find_manifest(str(deep)) == (None, None)                     # 5 poziomów wyżej - poza zasięgiem
    (tmp_path / "a" / projection.MANIFEST_NAME).write_text(json.dumps({"layout": "y"}), encoding="utf-8")
    root, payload = find_manifest(str(deep))
    assert root == str(tmp_path / "a") and payload == {"layout": "y"}   # 4 poziomy wyżej
    (deep / projection.MANIFEST_NAME).write_text("{zepsuty", encoding="utf-8")
    assert find_manifest(str(deep))[0] == str(tmp_path / "a")           # zepsuty pomijany, szukamy dalej


def test_common_root_is_under_i_clean_path(tmp_path):
    a = str(tmp_path / "CALIBRATION" / "masters" / "flats" / "X" / "CLS")
    b = str(tmp_path / "CALIBRATION" / "masters" / "flats" / "X" / "Ha")
    assert common_root([a]) == a
    assert common_root([a, b, a]) == str(tmp_path / "CALIBRATION" / "masters" / "flats" / "X")
    assert common_root([]) is None
    assert common_root([r"R:\A", r"E:\B"]) is None                      # różne wolumeny
    assert is_under(a, str(tmp_path / "calibration"))                   # bez wielkości liter (NTFS)
    assert is_under(a, a)
    assert not is_under(str(tmp_path / "CALIBRATION2"), str(tmp_path / "CALIBRATION"))
    assert not is_under(r"R:\A", r"E:\A")
    assert clean_path('  "E:\\WBPP\\master"  ') == "E:\\WBPP\\master"   # „Kopiuj jako ścieżkę” Eksploratora
    assert clean_path("'E:\\x'") == "E:\\x"
    assert clean_path('"') == '"' and clean_path("") == ""


def test_rel_text_wzgledem_korzenia_albo_pelna():
    """Komórka ścieżki: względem korzenia (bez wielkości liter), poza nim - pełna; sam korzeń
    i brak korzenia - pełna."""
    assert rel_text(r"E:\Arch\CALIBRATION\masters", r"e:\arch") == r"CALIBRATION\masters"
    assert rel_text(r"R:\ASTRO_\CALIBRATION\x", r"E:\Arch") == r"R:\ASTRO_\CALIBRATION\x"
    assert rel_text(r"E:\Arch", r"E:\Arch") == r"E:\Arch"
    assert rel_text(r"E:\Arch\x", None) == r"E:\Arch\x"
    assert rel_text("", r"E:\Arch") == ""


def test_reason_text_token_detail_i_tekst_klingi():
    """Powód = zdanie tokenu z `reason_n` + `detail` (CO się nie zgadza); po apply token pusty,
    a tekst klingi jedzie wprost; `exists` bez obecnej kopii mówi to zdaniem; liczba nazw zajętych
    przychodzi z rdzenia, nie z katalogu."""
    it = lambda **kw: SimpleNamespace(**{"reason": None, "reason_n": None, "detail": None,  # noqa: E731
                                         "status": "review", "exists_path": None, "kind": "master_flat",
                                         **kw})
    assert reason_text(it(reason="inputs_unknown", reason_n=2, detail="a_c, b_c")) == \
        "wejść nieznanych bazie: 2: a_c, b_c"
    # Ten sam token, inne zdanie: master flat spoza wydania nie ma recepty ani liczby, stos ma obie.
    assert reason_text(it(reason="outside_release")) == "wejścia spoza wydania, w którego drzewie leży wyjście"
    assert reason_text(it(reason="outside_release", reason_n=2, detail="a_c_r.xisf, b_c_r.xisf",
                          kind="master_light")) == \
        ("wejść spoza wydania (stos skopiuj ręcznie do STACKS archiwum, „Przyjmij nowe” na archiwum go "
         "weźmie): 2: a_c_r.xisf, b_c_r.xisf")
    assert reason_text(it(reason="no_release", detail=r"R:\A\STACKS", kind="master_light")) == \
        ("stos spoza wydania Horreum - skopiuj go ręcznie do biblioteki stosów, „Przyjmij nowe” na archiwum "
         r"go weźmie: R:\A\STACKS")
    assert reason_text(it(reason="foreign_calibration", detail="flat=X:/C/MASTER/f.xisf",
                          kind="master_light")).endswith("TELESCOP jako Pre i Post): flat=X:/C/MASTER/f.xisf")
    assert reason_text(it(reason="no_history")) == "brak historii integracji w pliku"
    assert reason_text(it(reason="name_taken", reason_n=7)) == "zajęte wszystkie nazwy kandydujące: 7"
    assert reason_text(it(reason="no_profile", reason_n=2)) == "wejść bez profilu flatu: 2"
    assert reason_text(it(status="conflict", detail="cel istnieje")) == "cel istnieje"
    assert reason_text(it(status="exists")) == "znany bazie, bez obecnej kopii"
    assert reason_text(it(status="exists", exists_path="X")) == ""
    assert reason_text(it(reason="nowy_token")) == "nowy_token"          # nowy token rdzenia widoczny


def test_release_text_tylko_dla_ocenionych_do_konca():
    """„poza wydaniem Horreum” wyłącznie dla pozycji, które idą (albo poszły) do archiwum bez
    świadka; pozycja odrzucona wcześniej albo już w archiwum - komórka pusta; świadek - nazwa."""
    it = lambda status, release=None: SimpleNamespace(status=status, release=release)  # noqa: E731
    assert release_text(it("would-place")) == "poza wydaniem Horreum"
    assert release_text(it("placed")) == "poza wydaniem Horreum"
    for status in ("review", "exists", "cancelled", "conflict", "error", "verify_bad"):
        assert release_text(it(status)) == "", status
    assert release_text(it("review", ("Cr464", SEG))) == f"Cr464 / {SEG}"


def test_parytet_powodow_i_statusow_z_rdzeniem_i_katalogiem():
    """BRAMKA NA KLUCZE Z MAP: kolektor `test_i18n` widzi tylko literały w `t(...)`. Każdy token
    i status, który rdzeń umie wyprodukować, ma klucz w mapie, mapy nie mają wpisów spoza rdzenia
    (oba kierunki to defekt: surowy token na ekranie albo martwy wpis), każdy klucz ma PL i EN."""
    assert set(_HARVEST_REASONS) == set(harvest.REASONS)
    assert set(_HARVEST_STATUS) == set(harvest.STATUSES)
    assert all(v == f"harvest.reason.{k}" for k, v in _HARVEST_REASONS.items())
    assert set(_STACK_REASONS) <= set(harvest.REASONS)                  # zdanie stosu tylko dla tokenu rdzenia
    assert {"master_flat", "master_light"} <= set(_HARVEST_KINDS)
    dynamiczne = (list(_HARVEST_REASONS.values()) + list(_STACK_REASONS.values())
                  + list(_HARVEST_STATUS.values()) + list(_HARVEST_KINDS.values())
                  + list(hd_mod._REL_HEADERS))
    braki = [k for k in dynamiczne if k not in CATALOG or not {"pl", "en"} <= set(CATALOG[k])]
    assert not braki, f"klucze żniw bez zdania PL/EN: {braki}"


@pytest.mark.parametrize("n, forma", [(1, "plik"), (2, "pliki"), (3, "pliki"), (4, "pliki"), (5, "plików"),
                                      (12, "plików"), (13, "plików"), (14, "plików"), (22, "pliki")])
def test_odmiana_liczebnikow_z_nascie(n, forma):
    """Liczby mnogie przycisku i zdań paska: 12-14 to forma „many” mimo końcówki 2-4, 22 wraca do „few”;
    EN one/other."""
    t = i18n.t_plural
    assert t("harvest.btn_apply", n) == f"Wciągnij {n} {forma}"
    assert t("harvest.status_placed", n, root="R") == f"Wciągnięto {n} {forma} do archiwum → R"
    assert t("harvest.close_placed", n) == f"Wciągnięto {n} {forma} do archiwum"
    kopie = {"plik": "kopia nieznana", "pliki": "kopie nieznane", "plików": "kopii nieznanych"}[forma]
    assert t("harvest.close_unknown", n).endswith(f" {n} {kopie} bazie")
    assert t("harvest.status_unknown", n, root="R").endswith(f" {n} {kopie} bazie → R")
    i18n.set_lang("en")
    assert t("harvest.btn_apply", n) == (f"Harvest {n} file" if n == 1 else f"Harvest {n} files")


# ---------------------------------------------------------------- DRY

def test_dry_po_wskazaniu_katalogu_liczby_naglowka_i_tabela(qapp, tmp_path, ustawienia, monkeypatch):
    """Bez pamięci pole prosi o katalog; wskazanie liczy plan PRAWDZIWYM rdzeniem: master flat
    z wejściami znanymi bazie → do wciągnięcia, darkowy → przegląd `no_raw_darks`, flat z wejściami
    spoza bazy → przegląd z liczbą i nazwami. Nagłówek, przycisk i tabela mówią to samo; dysk
    archiwum nietknięty; przycisk przyjęcia niewidoczny przed pierwszą kopią."""
    con, _profile, _flats = _baza(tmp_path)
    archive = tmp_path / "ARCH"
    out = _wyjscie(tmp_path, {"masterFlat_BIN-1_FILTER-CLS_mono.xisf": b"MF-CLS",
                              "masterDark_BIN-1_EXP-300s.xisf": b"MD",
                              "masterFlat_BIN-1_FILTER-OIII_mono.xisf": b"MF-OIII"})
    _czytnik(monkeypatch, {
        "masterFlat_BIN-1_FILTER-CLS_mono.xisf": _flat_cls(),
        "masterDark_BIN-1_EXP-300s.xisf": {"kind": "master_dark"},
        "masterFlat_BIN-1_FILTER-OIII_mono.xisf": {"inputs": [_wejscie("obca_1.fits"),
                                                              _wejscie("obca_2.fits")]},
    })
    dlg = _dlg(con, archive)
    assert dlg.notice.text() == "Wskaż katalog wyjścia WBPP - podgląd policzy się sam."
    assert not dlg.btn_apply.isEnabled() and dlg.table.rowCount() == 0
    assert dlg.btn_accept.isHidden()
    dlg._set_output(str(out))
    assert dlg.head_label.text() == "Do wciągnięcia 1 · już w archiwum 0 · do przeglądu 2"
    assert dlg.btn_apply.isEnabled() and dlg.btn_apply.text() == "Wciągnij 1 plik"
    assert dlg.busy.isHidden()
    rows = _wiersze(dlg)
    assert len(rows) == 3
    r = rows["masterFlat_BIN-1_FILTER-CLS_mono.xisf"]
    assert _kol(dlg, r, COL_STATUS) == "do wciągnięcia"
    assert _kol(dlg, r, COL_NAME) == "MASTERFLAT_FLATGRP_202305070_FILTER_CLS_.xisf"
    assert dlg.table.item(r, COL_DIR).toolTip() == str(_cel(archive).parent)   # realny `dst`, pełny pod kursorem
    assert _kol(dlg, r, COL_RELEASE) == "poza wydaniem Horreum"
    r = rows["masterDark_BIN-1_EXP-300s.xisf"]
    assert _kol(dlg, r, COL_STATUS) == "do przeglądu"
    assert _kol(dlg, r, COL_RELEASE) == ""                                         # nieoceniona - o wydaniu milczy
    assert _kol(dlg, r, COL_REASON).startswith("master dark/bias - archiwum nie ma surowych darków")
    r = rows["masterFlat_BIN-1_FILTER-OIII_mono.xisf"]
    assert _kol(dlg, r, COL_REASON) == "wejść nieznanych bazie: 2: obca_1_c.xisf, obca_2_c.xisf"
    assert not archive.exists()                                          # podgląd: zero zapisu
    con.close()


def test_przycisk_wygaszony_przy_zero(qapp, tmp_path, ustawienia, monkeypatch):
    """Nic do wciągnięcia (same darki) → szczery disabled z zerem w nazwie; nagłówek liczy przegląd."""
    con, _profile, _flats = _baza(tmp_path)
    out = _wyjscie(tmp_path, {"masterDark_a.xisf": b"A", "masterBias_b.xisf": b"B"})
    _czytnik(monkeypatch, {"masterDark_a.xisf": {"kind": "master_dark"},
                           "masterBias_b.xisf": {"kind": "master_dark"}})
    dlg = _dlg(con, tmp_path / "ARCH")
    dlg._set_output(str(out))
    assert dlg.head_label.text() == "Do wciągnięcia 0 · już w archiwum 0 · do przeglądu 2"
    assert not dlg.btn_apply.isEnabled() and dlg.btn_apply.text() == "Wciągnij 0 plików"
    dlg._on_apply()                                                      # wygaszony - i tak nic nie rusza
    assert not (tmp_path / "ARCH").exists()
    con.close()


def test_pusty_katalog_i_katalog_nieistniejacy(qapp, tmp_path, ustawienia, monkeypatch):
    """Katalog bez kandydatów → „Brak masterów i stosów w …”; produkty obróbki obok stosu
    (`…_starless`, `HOS.xisf`) kandydatami nie są. Ścieżka, której nie ma → osobne zdanie i pamięć
    pola nietknięta (literówka nie wraca przy następnym otwarciu)."""
    con, _profile, _flats = _baza(tmp_path)
    _czytnik(monkeypatch, {})
    empty = tmp_path / "WBPP" / "pusty"
    empty.mkdir(parents=True)
    (empty / "notatka.txt").write_text("x", encoding="utf-8")            # nie-master nie liczy się
    (empty / "masterLight_Ha_starless.xisf").write_bytes(b"L")           # pochodna obróbki - nie stos
    (empty / "HOS.xisf").write_bytes(b"H")
    dlg = _dlg(con, tmp_path / "ARCH")
    dlg._set_output(str(empty))
    assert dlg.notice.text() == f"Brak masterów i stosów w {empty}"
    assert dlg.head_label.text() == "" and dlg.table.rowCount() == 0
    assert not dlg.btn_apply.isEnabled()
    assert ustawienia.value("harvest/last_output") == str(empty)
    ghost = tmp_path / "nie_ma"
    dlg._set_output(str(ghost))
    assert dlg.notice.text() == f"Katalog nie istnieje: {ghost}"
    assert ustawienia.value("harvest/last_output") == str(empty)
    con.close()


def test_blad_czytnika_pozycja_unreadable_reszta_planu_zyje(qapp, tmp_path, ustawienia, monkeypatch):
    """Wyjątek czytnika jednego pliku → pozycja `review` `unreadable` z treścią wyjątku; drugi
    master dalej się planuje i przycisk go wciąga - worker nie umiera na złym pliku."""
    con, _profile, _flats = _baza(tmp_path)
    out = _wyjscie(tmp_path, {"masterFlat_A.xisf": b"A", "masterFlat_B.xisf": b"B"})
    _czytnik(monkeypatch, {"masterFlat_A.xisf": OSError("uszkodzony nagłówek XISF"),
                           "masterFlat_B.xisf": _flat_cls()})
    dlg = _dlg(con, tmp_path / "ARCH")
    dlg._set_output(str(out))
    r = _wiersze(dlg)["masterFlat_A.xisf"]
    assert _kol(dlg, r, COL_STATUS) == "do przeglądu"
    assert _kol(dlg, r, COL_REASON) == "pliku nie da się odczytać: OSError: uszkodzony nagłówek XISF"
    assert dlg.head_label.text() == "Do wciągnięcia 1 · już w archiwum 0 · do przeglądu 1"
    assert dlg.btn_apply.isEnabled()
    con.close()


def test_brak_archiwum_prosi_o_nie_i_nie_sonduje(qapp, tmp_path, ustawienia, monkeypatch):
    """Puste `archive_root` (Dostawa bez źródła) → zdanie o archiwum, zero sondy; „Zmień…” ustawia
    archiwum TYLKO dla okna (źródło Dostawy zostaje) i sonduje."""
    con, _profile, _flats = _baza(tmp_path)
    out = _wyjscie(tmp_path, {"masterFlat_A.xisf": b"A"})
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls()})
    ustawienia.setValue("harvest/last_output", str(out))
    dlg = HarvestDialog(con, now_fn=lambda: NOW, archive_root=None, off_thread=False)
    assert dlg.notice.text() == "Wskaż archiwum (źródło Dostawy) - tam trafią mastery i stosy."
    assert dlg.archive_label.text() == "Archiwum: nie wskazane"
    assert dlg.table.rowCount() == 0 and not dlg.btn_apply.isEnabled() and dlg.busy.isHidden()
    archive = tmp_path / "ARCH"
    dlg._set_archive(str(archive))
    assert dlg.archive_label.text() == f"Archiwum: {hd_mod._elide_path(str(archive))}"
    assert dlg.archive_label.toolTip() == str(archive)                   # pełna ścieżka pod kursorem
    assert dlg.btn_apply.text() == "Wciągnij 1 plik"
    assert dlg.table.item(0, COL_DIR).toolTip() == str(_cel(archive).parent)
    assert ustawienia.value("pipeline/last_source") is None              # Dostawa nieprzestawiona
    con.close()


def test_archiwum_inne_niz_w_bazie_ostrzega(qapp, tmp_path, ustawienia, monkeypatch):
    """Archiwum okna różne od archiwum, które zna baza → ostrzeżenie przy wierszu „Archiwum”; to
    samo archiwum inną wielkością liter i z ukośnikami - bez ostrzeżenia (normalizacja także
    w konstruktorze); baza bez masterów w archiwum - nie ma z czym porównać, okno milczy."""
    db_arch = tmp_path / "ARCH_DB"
    con, _profile, _flats = _baza(tmp_path, db_archive=db_arch)
    _czytnik(monkeypatch, {})
    dlg = _dlg(con, tmp_path / "ARCH")
    assert not dlg.archive_warn.isHidden()
    assert dlg.archive_warn.text().startswith(f"Baza zna archiwum w {db_arch} - pliki trafią gdzie indziej")
    zapis = str(db_arch).upper().replace("\\", "/") + "/"
    dlg2 = HarvestDialog(con, now_fn=lambda: NOW, archive_root=zapis, off_thread=False)
    assert dlg2._archive_root == os.path.normpath(zapis)
    assert dlg2.archive_warn.isHidden()
    con.close()
    (tmp_path / "bez").mkdir()
    con3, _p, _f = _baza(tmp_path / "bez")
    dlg3 = _dlg(con3, tmp_path / "ARCH")
    assert dlg3.archive_warn.isHidden()
    con3.close()


def test_pamiec_wyjscia_otwiera_z_podgladem(qapp, tmp_path, ustawienia, monkeypatch):
    """Wyjście, które istniało, wraca w następnym otwarciu i od razu ma podgląd (1 klik do „Wciągnij”)."""
    con, _profile, _flats = _baza(tmp_path)
    out = _wyjscie(tmp_path, {"masterFlat_A.xisf": b"A"})
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls()})
    dlg1 = _dlg(con, tmp_path / "ARCH")
    dlg1._set_output(str(out))
    assert ustawienia.value("harvest/last_output") == str(out)
    dlg2 = _dlg(con, tmp_path / "ARCH")
    assert dlg2.edit_output.text() == str(out)
    assert dlg2.btn_apply.isEnabled() and dlg2.btn_apply.text() == "Wciągnij 1 plik"
    con.close()


def test_stale_dry_odrzucony_i_pasek_gasnie(qapp, tmp_path, ustawienia, monkeypatch):
    """Wynik sondy starszej generacji nie uzbraja przycisku pod parametry, które przestały
    obowiązywać, i nie zostawia paska „pracuję” zapalonego."""
    con, _profile, _flats = _baza(tmp_path)
    out = _wyjscie(tmp_path, {"masterFlat_A.xisf": b"A"})
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls()})
    dlg = _dlg(con, tmp_path / "ARCH")
    dlg._set_output(str(out))
    payload = {"wbpp_dir": str(out), "missing": False, "plan": dlg._plan, "manifest_root": None}
    dlg._invalidate()
    dlg._set_probing(True)
    dlg._on_dry_done(dlg._gen - 1, payload)
    assert dlg._plan is None and not dlg.btn_apply.isEnabled() and dlg._dry_pending
    assert dlg.busy.isHidden()
    con.close()


def test_manifest_wydania_swiadkiem_w_kolumnie_wydanie(qapp, tmp_path, ustawienia, monkeypatch):
    """Wyjście WBPP w drzewie wydania obiektu: okno samo znajduje `_PROJEKCJA.json` piętro wyżej,
    nazywa go i kolumna „Wydanie” mówi, z którego wydania i zestawu master pochodzi."""
    con, _profile, flats = _baza(tmp_path)
    out = _wyjscie(tmp_path, {"masterFlat_A.xisf": b"A"})
    manifest = {"layout": projection.OBJECT_LAYOUT, "root": str(out.parent), "object_id": 1,
                "object_canon": "Cr464",
                "zestawy": {SEG: {"flat_raw": [flats[_flat_name(i, "CLS")] for i in range(3)]}}}
    (out.parent / projection.MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls()})
    dlg = _dlg(con, tmp_path / "ARCH")
    dlg._set_output(str(out))
    assert dlg.notice.text() == f"Wydanie Horreum (manifest _PROJEKCJA.json): {out.parent}"
    assert _kol(dlg, 0, COL_RELEASE) == f"Cr464 / {SEG}"
    assert _kol(dlg, 0, COL_STATUS) == "do wciągnięcia"
    con.close()


def test_pole_rozne_od_podgladu_wyszarza_tabele(qapp, tmp_path, ustawienia, monkeypatch):
    """Tekst pola odbiega od wyjścia z podglądu → tabela wyszarzona, zdanie „Podgląd dla: … - Enter
    liczy nowy”, „Wciągnij” wygaszony; powrót tekstu → tabela, komunikat i przycisk wracają.
    Ścieżka wklejona w cudzysłowach sonduje się bez nich; ścieżka względna → odmowa bez sondy."""
    con, _profile, _flats = _baza(tmp_path)
    out = _wyjscie(tmp_path, {"masterFlat_A.xisf": b"A"})
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls()})
    dlg = _dlg(con, tmp_path / "ARCH")
    dlg.edit_output.setText(f'"{out}"')
    dlg._on_output_edited(force=True)
    assert dlg.edit_output.text() == str(out) and dlg.table.rowCount() == 1
    assert dlg.table.isEnabled() and dlg.btn_apply.isEnabled()
    dlg.edit_output.setText(str(out) + "_inny")
    assert not dlg.table.isEnabled() and not dlg.btn_apply.isEnabled()
    assert dlg.notice.text() == f"Podgląd dla: {out} - Enter liczy nowy"
    dlg._on_apply()
    assert not (tmp_path / "ARCH").exists()                              # nieaktualny podgląd nie kopiuje
    dlg.edit_output.setText(str(out))
    assert dlg.table.isEnabled() and dlg.btn_apply.isEnabled() and dlg.notice.text() == ""
    dlg.edit_output.setText(r"WBPP\master")
    dlg._on_output_edited(force=True)
    assert dlg.notice.text() == r"Ścieżka wyjścia musi być pełna (z dyskiem albo \\serwer): WBPP\master"
    assert dlg.table.rowCount() == 0 and not dlg.btn_apply.isEnabled() and dlg.busy.isHidden()
    con.close()


def test_wyczyszczone_pole_prosi_o_katalog(qapp, tmp_path, ustawienia, monkeypatch):
    """Pole wyczyszczone (krzyżyk, Delete) i Enter: podgląd znika, zdanie prosi o katalog, przycisk
    wygaszony, pasek zgaszony - nie zostaje plan katalogu, którego w polu już nie ma."""
    con, _profile, _flats = _baza(tmp_path)
    out = _wyjscie(tmp_path, {"masterFlat_A.xisf": b"A"})
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls()})
    dlg = _dlg(con, tmp_path / "ARCH")
    dlg.show()
    dlg._set_output(str(out))
    dlg.edit_output.setFocus()
    qapp.processEvents()
    dlg.edit_output.clear()
    QTest.keyClick(dlg.edit_output, Qt.Key_Return)
    assert dlg.notice.text() == "Wskaż katalog wyjścia WBPP - podgląd policzy się sam."
    assert dlg.table.rowCount() == 0 and dlg._plan is None
    assert not dlg.btn_apply.isEnabled() and dlg.busy.isHidden()
    con.close()


def _powod_w_kadrze(dlg):
    """(x, szerokość, viewport) kolumny powodu - kadr bez przewijania w bok."""
    t = dlg.table
    return t.columnViewportPosition(COL_REASON), t.columnWidth(COL_REASON), t.viewport().width()


def test_powod_w_kadrze_przy_domyslnej_szerokosci(qapp, tmp_path, ustawienia, monkeypatch):
    """Powód (jedyna kolumna, która mówi, CO się nie zgadza) stoi trzeci i przy domyślnej
    szerokości okna mieści się w kadrze bez przewijania w bok - gdy treści jest więcej niż kadru,
    w bok przewijają się ścieżki, nie powód; okno rośnie pod treść najwyżej do 90% ekranu, a przy
    miejscu powód pokazuje pełną treść."""
    con, _profile, _flats = _baza(tmp_path)
    archive = tmp_path / "ARCH"
    stary = "masterFlat_BIN-1_6248x4176_FILTER-Ha_stary.xisf"
    out = _wyjscie(tmp_path, {"masterFlat_BIN-1_6248x4176_FILTER-CLS_mono.xisf": b"A", stary: b"S"})
    _czytnik(monkeypatch, {"masterFlat_BIN-1_6248x4176_FILTER-CLS_mono.xisf": _flat_cls(),
                           stary: {"kind": "flat", "header": {"IMAGETYP": "FLAT"}}})
    dlg = _dlg(con, archive)
    dlg.show()
    dlg._set_output(str(out))
    qapp.processEvents()
    r = _wiersze(dlg)[stary]
    tekst = _kol(dlg, r, COL_REASON)
    assert tekst == "nagłówek pliku nie zgadza się z wejściami: IMAGETYP='FLAT' -> flat"
    assert dlg.table.item(r, COL_REASON).toolTip() == tekst
    assert dlg.table.horizontalScrollBar().value() == 0
    pelny = dlg.table.sizeHintForColumn(COL_REASON)
    x, w, vw = _powod_w_kadrze(dlg)
    # Offscreen mierzy czcionkę zastępczą (~12 px na znak), więc przy 980 px powód nie mieści się
    # cały: dostaje CAŁE miejsce między stanem a krawędzią kadru, nie resztkę po ścieżkach.
    assert 0 <= x and x + w <= vw
    assert w >= min(pelny, vw - x)
    cap = int(dlg.screen().availableGeometry().width() * 0.9)
    assert dlg.width() <= max(980, cap, dlg.minimumSizeHint().width())  # rośnie najwyżej do 90% ekranu
    dlg.resize(x + pelny + 200, dlg.height())                            # miejsce jest - pełna treść
    assert _wait_until(lambda: dlg.table.viewport().width() >= x + pelny)
    qapp.processEvents()
    x, w, vw = _powod_w_kadrze(dlg)
    assert w >= pelny and x + w <= vw
    con.close()


def test_sciezki_wzgledem_wyjscia_i_archiwum(qapp, tmp_path, ustawienia, monkeypatch):
    """Cztery pliki o tej samej nazwie w różnych podkatalogach wyjścia są odróżnialne: kolumna pliku
    pokazuje ścieżkę WZGLĘDEM wyjścia WBPP, katalogu - WZGLĘDEM archiwum (`CALIBRATION\\…`); kopia,
    która leży w archiwum bazy (poza archiwum okna), pokazuje pełną ścieżkę. Pełne ścieżki pod
    kursorem."""
    db_arch = tmp_path / "ARCH_DB"
    con, _profile, _flats = _baza(tmp_path, db_archive=db_arch)
    archive = tmp_path / "ARCH"
    nazwa = "masterFlat_BIN-1_6248x4176_FILTER-CLS_mono.xisf"
    out = tmp_path / "WBPP"
    for sub, data in (("mf_nowy", b"N"), ("mf_stary", b"S"), ("mf_archiwum", b"Z")):
        _wyjscie(tmp_path, {nazwa: data}, sub=("WBPP", sub))
    zeznania = {}

    def czytaj(path, **_kw):
        sub = os.path.basename(os.path.dirname(path))
        z = {"mf_archiwum": {**_flat_cls(), "sha1_data": "mf-archiwum"}}.get(sub, _flat_cls())
        zeznania[sub] = path
        return harvest.MasterTestimony(
            path=path, kind="master_flat", header={}, inputs_enabled=tuple(z["inputs"]), rows=3,
            sha1_data=z.get("sha1_data", f"sd-{sub}"), file_sha1=hashing.sha1_of(path),
            filter_raw="CLS", xbinning=1, date_obs="2023-05-07T21:00:00")

    monkeypatch.setattr(harvest, "read_master", czytaj)
    dlg = _dlg(con, archive)
    dlg._set_output(str(out))
    rows = _wiersze(dlg)
    assert set(rows) == {os.path.join(sub, nazwa) for sub in ("mf_archiwum", "mf_nowy", "mf_stary")}
    for sub in ("mf_nowy", "mf_stary"):
        r = rows[os.path.join(sub, nazwa)]
        assert dlg.table.item(r, COL_FILE).toolTip() == str(out / sub / nazwa)
        assert _kol(dlg, r, COL_DIR) == os.path.join("CALIBRATION", "masters", "flats", SEG, "CLS")
        assert dlg.table.item(r, COL_DIR).toolTip() == str(_cel(archive).parent)
    r = rows[os.path.join("mf_archiwum", nazwa)]
    assert _kol(dlg, r, COL_STATUS) == "już w archiwum"
    assert _kol(dlg, r, COL_DIR) == str(db_arch / "CALIBRATION" / "masters" / "flats" / SEG / "CLS")
    con.close()


def test_pierwsze_uzycie_od_razu_wybor_katalogu(qapp, tmp_path, ustawienia, monkeypatch, wybor_katalogu):
    """Brak pamięci wyjścia: po pokazaniu okna od razu wybór katalogu (start w archiwum), wybrany
    katalog ma podgląd - do mastera w archiwum zostają „Wciągnij” i „Zamknij i przyjmij”.
    Anulowanie wyboru zostawia okno z pustym polem; z pamięcią wyboru nie ma."""
    con, _profile, _flats = _baza(tmp_path)
    archive = tmp_path / "ARCH"
    out = _wyjscie(tmp_path, {"masterFlat_A.xisf": b"A"})
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls()})
    wybor_katalogu.odpowiedz = str(out)
    dlg = _dlg(con, archive)
    qapp.processEvents()
    assert wybor_katalogu.wywolania == []                                # nie przed pokazaniem okna
    dlg.show()
    assert _wait_until(lambda: wybor_katalogu.wywolania)
    assert wybor_katalogu.wywolania == [("Wskaż katalog wyjścia WBPP", str(archive))]
    assert dlg.edit_output.text() == str(out) and dlg.btn_apply.text() == "Wciągnij 1 plik"
    dlg.btn_apply.click()
    dlg.btn_accept.click()
    assert dlg.result() == QDialog.Accepted and dlg.harvested_root == str(_cel(archive).parent)

    ustawienia.remove("harvest/last_output")
    wybor_katalogu.odpowiedz = ""                                        # „Anuluj” w oknie wyboru
    dlg2 = _dlg(con, archive)
    dlg2.show()
    assert _wait_until(lambda: len(wybor_katalogu.wywolania) == 2)
    assert dlg2.isVisible() and dlg2.edit_output.text() == ""
    assert dlg2.notice.text() == "Wskaż katalog wyjścia WBPP - podgląd policzy się sam."

    ustawienia.setValue("harvest/last_output", str(out))
    dlg3 = _dlg(con, archive)
    dlg3.show()
    QTest.qWait(30)
    assert len(wybor_katalogu.wywolania) == 2                            # pamięć jest - okno wyboru nie wraca
    con.close()


# ---------------------------------------------------------------- apply

def test_apply_kopiuje_prawdziwy_plik_i_oddaje_korzen(qapp, tmp_path, ustawienia, monkeypatch):
    """„Wciągnij” kopiuje PRAWDZIWE bajty do `<archiwum>/CALIBRATION/masters/flats/<zestaw>/<filtr>/`
    pod nazwą z konwencji archiwum (bez `.part`), zostawia zeznanie `_ZNIWA_<ts>.json` przy wyjściu,
    nagłówek liczy skutek; „Zamknij i przyjmij” pojawia się obok i dopiero ten gest oddaje
    gospodarzowi korzeń do przyjęcia."""
    con, _profile, _flats = _baza(tmp_path)
    archive = tmp_path / "ARCH"
    out = _wyjscie(tmp_path, {"masterFlat_A.xisf": b"MASTER-CLS-BAJTY", "masterDark_D.xisf": b"D"})
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls(), "masterDark_D.xisf": {"kind": "master_dark"}})
    dlg = _dlg(con, archive)
    dlg._set_output(str(out))
    seen = _spy_progress(monkeypatch)
    dlg._on_apply()
    cel = _cel(archive)
    assert cel.read_bytes() == b"MASTER-CLS-BAJTY"
    assert (out / "masterFlat_A.xisf").read_bytes() == b"MASTER-CLS-BAJTY"   # źródło nietknięte
    assert not _parts(archive)
    assert len(_zeznania(out)) == 1
    assert seen == [(1, 1, "placed")]
    assert dlg.head_label.text() == ("Wciągnięto 1 · pominięto 0 (już w archiwum) · do przeglądu 1 · "
                                     "konflikty 0 · błędy 0")
    assert sorted(_kol(dlg, r, COL_STATUS) for r in range(2)) == ["do przeglądu", "wciągnięty"]
    assert dlg.summary == f"Wciągnięto 1 plik do archiwum → {cel.parent}"
    assert dlg.harvested_root is None                                    # jeszcze nikt nie przyjął
    assert dlg.btn_apply.text() == "Wciągnięto" and not dlg.btn_apply.isEnabled()
    assert not dlg.btn_accept.isHidden() and dlg.btn_accept.isEnabled()
    assert dlg.edit_output.isEnabled() and dlg.busy.isHidden() and dlg.btn_cancel.isHidden()
    dlg.btn_accept.click()
    assert dlg.result() == QDialog.Accepted
    assert dlg.harvested_root == str(cel.parent)
    assert dlg.summary == f"Wciągnięto 1 plik do archiwum → {cel.parent}"
    con.close()


def test_dwa_przyciski_enter_nie_przyjmuje(qapp, tmp_path, ustawienia, monkeypatch):
    """„Zamknij i przyjmij” nie jest domyślny ani autodomyślny: Enter w tabeli i w polu po
    wciągnięciu nie zamyka okna z uruchomieniem łańcucha. „Wciągnij” nie zmienia roli - po biegu
    nazywa skutek i stoi wygaszony."""
    con, _profile, _flats = _baza(tmp_path)
    out = _wyjscie(tmp_path, {"masterFlat_A.xisf": b"A"})
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls()})
    dlg = _dlg(con, tmp_path / "ARCH")
    dlg.show()
    dlg.activateWindow()
    dlg._set_output(str(out))
    assert dlg.btn_apply.isDefault() and not dlg.btn_accept.isDefault() and not dlg.btn_accept.autoDefault()
    dlg._on_apply()
    assert not dlg.btn_accept.isHidden()
    dlg.table.setFocus()
    qapp.processEvents()
    QTest.keyClick(dlg.table, Qt.Key_Return)
    dlg.edit_output.setFocus()
    qapp.processEvents()
    QTest.keyClick(dlg.edit_output, Qt.Key_Return)
    assert dlg.isVisible() and dlg.result() != QDialog.Accepted and dlg.harvested_root is None
    assert dlg.btn_accept.text() == "Zamknij i przyjmij do archiwum"
    con.close()


def test_zamknij_bez_przyjecia_zdanie_zalezy_od_zrodla_dostawy(qapp, tmp_path, ustawienia, monkeypatch):
    """Zwykłe „Zamknij” po wciągnięciu: korzeń NIE idzie do gospodarza. Kopie pod źródłem Dostawy
    → „baza pozna je przy następnej dostawie”; kopie poza nim → zdanie, którędy baza do nich dojdzie
    (następna dostawa ich nie zobaczy). Instrukcja PRZED ścieżką - pasek stanu ucina koniec zdania."""
    con, _profile, _flats = _baza(tmp_path)
    archive = tmp_path / "ARCH"
    out = _wyjscie(tmp_path, {"masterFlat_A.xisf": b"A", "masterFlat_B.xisf": b"B"})
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls(), "masterFlat_B.xisf": _flat_ha()})
    ustawienia.setValue("pipeline/last_source", str(archive).lower())
    dlg = _dlg(con, archive)
    dlg._set_output(str(out))
    dlg._on_apply()
    dlg.btn_close.click()
    assert dlg.result() == QDialog.Rejected and dlg.harvested_root is None and dlg.harvested_stacks == []
    zestaw = _cel(archive).parent.parent
    assert dlg.summary == ("Wciągnięto 2 pliki do archiwum - baza pozna je przy następnej dostawie "
                           f"(„Przyjmij”) → {zestaw}")
    ustawienia.setValue("pipeline/last_source", str(tmp_path / "LIGHTS"))
    out2 = _wyjscie(tmp_path, {"masterFlat_C.xisf": b"C"}, sub=("WBPP2",))
    _czytnik(monkeypatch, {"masterFlat_C.xisf": _flat_cls()})
    dlg2 = _dlg(con, tmp_path / "ARCH2")
    dlg2._set_output(str(out2))
    dlg2._on_apply()
    dlg2.reject()
    assert dlg2.summary == ("Wciągnięto 1 plik do archiwum - kopie leżą poza źródłem Dostawy; baza pozna je "
                            "przez „Zamknij i przyjmij do archiwum” albo Dostawę wskazaną na archiwum → "
                            f"{_cel(tmp_path / 'ARCH2').parent}")
    con.close()


def test_okno_bez_biegu_nie_niesie_zdania(qapp, tmp_path, ustawienia, monkeypatch):
    """Sam podgląd i zamknięcie: nic się nie stało, więc `summary` i korzeń zostają puste."""
    con, _profile, _flats = _baza(tmp_path)
    out = _wyjscie(tmp_path, {"masterFlat_A.xisf": b"A"})
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls()})
    dlg = _dlg(con, tmp_path / "ARCH")
    dlg._set_output(str(out))
    dlg.reject()
    assert dlg.summary is None and dlg.harvested_root is None
    con.close()


def test_drugi_bieg_juz_w_archiwum(qapp, tmp_path, ustawienia, monkeypatch):
    """Ponowny podgląd tego samego wyjścia po biegu: plik już leży w siedzibie (ten sam `file_sha1`)
    → „już w archiwum”, zero do wciągnięcia; wcześniejsze wciągnięcie dalej czeka na przyjęcie.
    Samo wyjście z pola po biegu NIE zmazuje tabeli wyniku."""
    con, _profile, _flats = _baza(tmp_path)
    out = _wyjscie(tmp_path, {"masterFlat_A.xisf": b"A"})
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls()})
    dlg = _dlg(con, tmp_path / "ARCH")
    dlg._set_output(str(out))
    dlg._on_apply()
    dlg._on_output_edited()                                              # `editingFinished` bez zmiany pola
    assert _kol(dlg, 0, COL_STATUS) == "wciągnięty"
    dlg._set_output(str(out))                                            # „Wskaż…” tej samej ścieżki = świeża sonda
    assert dlg.head_label.text() == "Do wciągnięcia 0 · już w archiwum 1 · do przeglądu 0"
    assert _kol(dlg, 0, COL_STATUS) == "już w archiwum" and _kol(dlg, 0, COL_RELEASE) == ""
    assert _kol(dlg, 0, COL_NAME) == "MASTERFLAT_FLATGRP_202305070_FILTER_CLS_.xisf"
    assert dlg.btn_apply.text() == "Wciągnij 0 plików" and not dlg.btn_apply.isEnabled()
    assert not dlg.btn_accept.isHidden() and dlg.btn_accept.isEnabled()
    con.close()


def test_dwa_biegi_jednego_okna_sumuja_sie_w_korzeniu_i_zdaniu(qapp, tmp_path, ustawienia, monkeypatch):
    """Dwa wyjścia WBPP w jednym oknie: korzeń do przyjęcia obejmuje katalogi OBU biegów (wspólny
    rodzic), a zdanie paska liczy wszystkie wciągnięte mastery, nie tylko ostatni bieg."""
    con, _profile, _flats = _baza(tmp_path)
    archive = tmp_path / "ARCH"
    out1 = _wyjscie(tmp_path, {"masterFlat_A.xisf": b"A"})
    out2 = _wyjscie(tmp_path, {"masterFlat_B.xisf": b"B"}, sub=("WBPP2",))
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls(), "masterFlat_B.xisf": _flat_ha()})
    dlg = _dlg(con, archive)
    dlg._set_output(str(out1))
    dlg._on_apply()
    dlg._set_output(str(out2))
    assert dlg.btn_apply.text() == "Wciągnij 1 plik"                  # nowe wyjście ma własną robotę
    dlg._on_apply()
    zestaw = _cel(archive).parent.parent
    assert dlg.summary == f"Wciągnięto 2 pliki do archiwum → {zestaw}"
    dlg.btn_accept.click()
    assert dlg.harvested_root == str(zestaw)
    con.close()


def test_apply_anulowanie_na_granicy_pliku(qapp, tmp_path, ustawienia, monkeypatch):
    """„Przerwij” po pierwszym pliku: drugi master nietknięty (`cancelled`), brak `.part`, nagłówek
    i pasek stanu mówią o przerwaniu; to, co wciągnięte, dalej można przyjąć."""
    con, _profile, _flats = _baza(tmp_path)
    archive = tmp_path / "ARCH"
    out = _wyjscie(tmp_path, {"masterFlat_A.xisf": b"A", "masterFlat_B.xisf": b"B"})
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls(), "masterFlat_B.xisf": _flat_ha()})
    dlg = _dlg(con, archive)
    dlg._set_output(str(out))
    assert dlg.btn_apply.text() == "Wciągnij 2 pliki"
    _spy_progress(monkeypatch, hook=lambda n, w: w.request_cancel() if n == 1 else None)
    dlg._on_apply()
    assert _cel(archive, "CLS").exists() and not _cel(archive, "Ha").exists()
    assert not _parts(archive)
    assert sorted(_kol(dlg, r, COL_STATUS) for r in range(2)) == ["przerwano", "wciągnięty"]
    assert dlg.head_label.text().endswith(" · przerwano, nietknięte: 1")
    assert dlg.summary.endswith(" · przerwano, nietknięte: 1")
    assert dlg.btn_apply.text() == "Przerwano" and not dlg.btn_accept.isHidden()
    con.close()


def test_apply_zamraza_parametry_a_archiwum_od_pierwszej_kopii(qapp, tmp_path, ustawienia, monkeypatch):
    """W biegu pole, „Wskaż…” i „Zmień…” są wygaszone (zmiana wyzerowałaby plan, który worker
    kopiuje), „Przerwij” stoi w miejscu „Wciągnij”; po biegu pole wraca, a archiwum zostaje
    zamrożone z podpowiedzią dlaczego."""
    con, _profile, _flats = _baza(tmp_path)
    out = _wyjscie(tmp_path, {"masterFlat_A.xisf": b"A", "masterFlat_B.xisf": b"B"})
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls(), "masterFlat_B.xisf": _flat_ha()})
    dlg = _dlg(con, tmp_path / "ARCH")
    dlg._set_output(str(out))
    assert dlg.btn_archive.isEnabled() and dlg.btn_archive.toolTip() == ""
    frozen = []
    _spy_progress(monkeypatch, hook=lambda n, w: frozen.append((
        dlg.edit_output.isEnabled(), dlg.btn_pick.isEnabled(), dlg.btn_archive.isEnabled(),
        dlg.btn_apply.isHidden(), dlg.btn_apply.isEnabled(), dlg.btn_cancel.isHidden())))
    plan = dlg._plan
    dlg._on_output_edited()                                              # zdarzenie pola bez zmiany - plan zostaje
    assert dlg._plan is plan
    dlg._on_apply()
    assert frozen == [(False, False, False, True, False, False)] * 2
    assert dlg.edit_output.isEnabled() and dlg.btn_pick.isEnabled()
    assert not dlg.btn_archive.isEnabled()
    assert dlg.btn_archive.toolTip().startswith("Archiwum zablokowane: w tym oknie są już kopie do przyjęcia")
    con.close()


def test_przyjecie_tylko_pod_calibration_archiwum(qapp, tmp_path, ustawienia, monkeypatch):
    """Strażnik przyjęcia: katalog spoza `<archiwum>\\CALIBRATION` i `<archiwum>\\STACKS` (archiwum
    zmienione obejściem blokady) → `harvested_root=None`, zdanie odmowy, okno zostaje. Zmiana
    archiwum po pierwszej kopii to EXPECT, nie tryb."""
    con, _profile, _flats = _baza(tmp_path)
    out = _wyjscie(tmp_path, {"masterFlat_A.xisf": b"A"})
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls()})
    dlg = _dlg(con, tmp_path / "ARCH")
    dlg.show()
    dlg._set_output(str(out))
    dlg._on_apply()
    with pytest.raises(AssertionError):
        dlg._set_archive(str(tmp_path / "INNE"))
    dlg._archive_root = str(tmp_path / "INNE")                           # obejście wygaszonego przycisku
    dlg.btn_accept.click()
    assert dlg.isVisible() and dlg.result() != QDialog.Accepted and dlg.harvested_root is None
    assert dlg.notice.text() == (f"Nie przyjmę: {_cel(tmp_path / 'ARCH').parent} nie leży pod "
                                 f"{tmp_path / 'INNE' / 'CALIBRATION'} ani pod {tmp_path / 'INNE' / 'STACKS'}")
    con.close()


def test_apply_blad_przed_kopia_nie_zabija_okna(qapp, tmp_path, ustawienia, monkeypatch):
    """Wyjątek rdzenia przed jakąkolwiek kopią → sygnał `failed`: zdanie błędu w oknie i na pasku,
    tabela mówi, że planu nie tknięto, przycisk przyjęcia się nie pojawia, parametry odmrożone."""
    con, _profile, _flats = _baza(tmp_path)
    out = _wyjscie(tmp_path, {"masterFlat_A.xisf": b"A"})
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls()})
    dlg = _dlg(con, tmp_path / "ARCH")
    dlg._set_output(str(out))

    def boom(*_a, **_kw):
        raise OSError("archiwum odpięte")

    monkeypatch.setattr(harvest, "apply", boom)
    dlg._on_apply()
    assert dlg.notice.text() == "Błąd wciągania: OSError: archiwum odpięte"
    assert dlg.summary == "Żniwa przerwane błędem: OSError: archiwum odpięte"
    assert _kol(dlg, 0, COL_STATUS) == "przerwano"
    assert dlg.btn_apply.text() == "Przerwane błędem" and not dlg.btn_apply.isEnabled()
    assert dlg.btn_accept.isHidden()
    assert dlg.edit_output.isEnabled() and dlg.btn_cancel.isHidden()
    con.close()


def test_wyjatek_po_kopiach_prawda_z_postepu(qapp, tmp_path, ustawienia, monkeypatch):
    """Wyjątek rdzenia PO prawdziwych kopiach (gałąź `failed` bez wyniku): tabela, `summary`
    i droga przyjęcia biorą prawdę z postępu - obie kopie leżą i dają się przyjąć."""
    con, _profile, _flats = _baza(tmp_path)
    archive = tmp_path / "ARCH"
    out = _wyjscie(tmp_path, {"masterFlat_A.xisf": b"A", "masterFlat_B.xisf": b"B"})
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls(), "masterFlat_B.xisf": _flat_ha()})
    dlg = _dlg(con, archive)
    dlg._set_output(str(out))
    prawdziwy = harvest.apply

    def po_kopiach(plan, **kw):
        prawdziwy(plan, **kw)
        raise RuntimeError("po kopiach")

    monkeypatch.setattr(harvest, "apply", po_kopiach)
    dlg._on_apply()
    assert _cel(archive, "CLS").exists() and _cel(archive, "Ha").exists()
    assert [_kol(dlg, r, COL_STATUS) for r in range(2)] == ["wciągnięty", "wciągnięty"]
    zestaw = _cel(archive).parent.parent
    assert dlg.summary == (f"Wciągnięto 2 pliki do archiwum → {zestaw} · "
                           f"Żniwa przerwane błędem: RuntimeError: po kopiach")
    assert dlg.notice.text() == "Błąd wciągania: RuntimeError: po kopiach (przetworzono 2 z 2 przed błędem)"
    dlg.btn_accept.click()
    assert dlg.result() == QDialog.Accepted and dlg.harvested_root == str(zestaw)
    con.close()


def test_zeznanie_niezapisane_to_ostrzezenie_nie_blad_kopii(qapp, tmp_path, ustawienia, monkeypatch):
    """Zapis zeznania pada (`manifest_error`), kopie leżą: okno ostrzega przy kopiach, liczby
    i `summary` mówią o wciągnięciu, przyjęcie działa - bez udawania błędu kopii."""
    con, _profile, _flats = _baza(tmp_path)
    archive = tmp_path / "ARCH"
    out = _wyjscie(tmp_path, {"masterFlat_A.xisf": b"A"})
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls()})
    dlg = _dlg(con, archive)
    dlg._set_output(str(out))

    def zeznanie_pada(*_a, **_kw):
        raise OSError("dysk pełny")

    monkeypatch.setattr(projection, "write_harvest_manifest", zeznanie_pada)
    dlg._on_apply()
    assert _cel(archive).exists() and not _zeznania(out)
    assert dlg.notice.text() == "Kopie leżą w archiwum, ale zeznania żniw nie zapisano: OSError: dysk pełny"
    assert dlg.notice.property("role") == "warn"
    assert dlg.head_label.text().startswith("Wciągnięto 1 · ")
    assert dlg.summary == f"Wciągnięto 1 plik do archiwum → {_cel(archive).parent}"
    assert dlg.btn_apply.text() == "Wciągnięto" and dlg.btn_accept.isEnabled()
    con.close()


def test_summary_doklada_niezerowe_klopoty(qapp, tmp_path, ustawienia, monkeypatch):
    """Konflikt (cel powstał ręką między podglądem a kopią) wchodzi do zdania paska; zera milczą."""
    con, _profile, _flats = _baza(tmp_path)
    archive = tmp_path / "ARCH"
    out = _wyjscie(tmp_path, {"masterFlat_A.xisf": b"A", "masterFlat_B.xisf": b"B"})
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls(), "masterFlat_B.xisf": _flat_ha()})
    dlg = _dlg(con, archive)
    dlg._set_output(str(out))
    _cel(archive, "Ha").parent.mkdir(parents=True)
    _cel(archive, "Ha").write_bytes(b"reka")                             # wyścig z ręką
    dlg._on_apply()
    assert _cel(archive, "Ha").read_bytes() == b"reka"                   # nic nie nadpisane
    assert dlg.summary == f"Wciągnięto 1 plik do archiwum → {_cel(archive).parent} · konflikty: 1"
    assert "błędy:" not in dlg.summary and "bajty" not in dlg.summary
    con.close()


def test_zamkniecie_w_biegu_inline_anuluje_i_zamyka_po_biegu(qapp, tmp_path, ustawienia, monkeypatch):
    """Zamknięcie W BIEGU = anulowanie; okno zamyka się, gdy bieg wróci (inline - z wnętrza biegu),
    a `summary` niesie skutek przerwania."""
    con, _profile, _flats = _baza(tmp_path)
    archive = tmp_path / "ARCH"
    out = _wyjscie(tmp_path, {"masterFlat_A.xisf": b"A", "masterFlat_B.xisf": b"B"})
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls(), "masterFlat_B.xisf": _flat_ha()})
    ustawienia.setValue("pipeline/last_source", str(archive))
    dlg = _dlg(con, archive)
    dlg.show()
    dlg._set_output(str(out))
    _spy_progress(monkeypatch, hook=lambda n, w: dlg.done(0) if n == 1 else None)
    dlg._on_apply()
    assert dlg.isHidden() and dlg.result() == QDialog.Rejected
    assert _cel(archive, "CLS").exists() and not _cel(archive, "Ha").exists()
    assert dlg.summary == ("Wciągnięto 1 plik do archiwum · przerwano, nietknięte: 1 - baza pozna je przy "
                           f"następnej dostawie („Przyjmij”) → {_cel(archive, 'CLS').parent}")
    assert dlg.harvested_root is None
    con.close()


# ---------------------------------------------------------------- prawdziwy QThread

def test_realny_qthread_dry_i_apply(qapp, tmp_path, ustawienia, monkeypatch):
    """Droga przez `moveToThread` + sygnały kolejkowane + sprzątanie wątków: sonda na WŁASNYM
    połączeniu z bazą (plik bazy, nie `con` okna), apply w tle, potem przyjęcie."""
    con, _profile, _flats = _baza(tmp_path)
    archive = tmp_path / "ARCH"
    out = _wyjscie(tmp_path, {"masterFlat_A.xisf": b"A"})
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls()})
    ustawienia.setValue("harvest/last_output", str(out))
    dlg = _dlg(con, archive, off_thread=True)
    assert dlg._dry_thread is not None and not dlg.busy.isHidden()      # sonda NAPRAWDĘ w tle
    assert _wait_until(lambda: dlg.btn_apply.isEnabled() and dlg._dry_thread is None)
    assert dlg.busy.isHidden()
    dlg._on_apply()
    assert dlg._apply_thread is not None
    assert _wait_until(lambda: dlg._apply_thread is None and dlg._apply_worker is None)
    assert _cel(archive).read_bytes() == b"A"
    dlg.btn_accept.click()
    assert dlg.result() == QDialog.Accepted and dlg.harvested_root == str(_cel(archive).parent)
    con.close()


def test_realny_qthread_zamkniecie_w_biegu_nie_czeka_w_watku_glownym(qapp, tmp_path, ustawienia,
                                                                     monkeypatch):
    """Zamknięcie w biegu na PRAWDZIWYM wątku wraca OD RAZU (bez `wait` w wątku głównym): okno
    zostaje do końca bieżącego pliku z wygaszonymi przyciskami i zdaniem „Zamykam po bieżącym
    pliku…”, a zamyka je sprzątnięcie wątku. Drugi plik nietknięty, zero `.part`, `summary` mówi
    o przerwaniu. Worker stoi po pierwszym pliku, aż anulowanie przyjdzie."""
    con, _profile, _flats = _baza(tmp_path)
    archive = tmp_path / "ARCH"
    out = _wyjscie(tmp_path, {"masterFlat_A.xisf": b"A", "masterFlat_B.xisf": b"B"})
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls(), "masterFlat_B.xisf": _flat_ha()})
    ustawienia.setValue("harvest/last_output", str(out))
    stoi = threading.Event()

    def hook(n, w):
        if n == 1:
            stoi.set()
            w._cancel.wait(10)

    _spy_progress(monkeypatch, hook=hook)
    dlg = _dlg(con, archive, off_thread=True)
    dlg.show()
    assert _wait_until(lambda: dlg.btn_apply.isEnabled() and dlg._dry_thread is None)
    dlg._on_apply()
    assert stoi.wait(10)
    dlg.done(0)
    assert dlg.isVisible()                                               # wraca od razu - okno czeka na plik
    assert not dlg.btn_close.isEnabled() and not dlg.btn_cancel.isEnabled()
    assert dlg.progress_note.text() == "Zamykam po bieżącym pliku…"
    assert _wait_until(dlg.isHidden)
    assert dlg._apply_thread is None and dlg._apply_worker is None
    assert _cel(archive, "CLS").exists() and not _cel(archive, "Ha").exists()
    assert not _parts(archive)
    assert " · przerwano, nietknięte: 1" in dlg.summary and dlg.harvested_root is None
    con.close()


def test_realny_qthread_zamkniecie_w_trakcie_sondy(qapp, tmp_path, ustawienia, monkeypatch):
    """Zamknięcie w trakcie sondy na PRAWDZIWYM wątku: anulowanie na granicy pliku (`should_cancel`
    rdzenia) i krótkie czekanie - sonda nie czyta drugiego mastera, wynik porzucony (tabela pusta),
    wątek sprzątnięty."""
    con, _profile, _flats = _baza(tmp_path)
    out = _wyjscie(tmp_path, {"masterFlat_A.xisf": b"A", "masterFlat_B.xisf": b"B"})
    gate, entered = _bramka_sondy(monkeypatch)
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls(), "masterFlat_B.xisf": _flat_ha()},
             gate=gate, entered=entered)
    ustawienia.setValue("harvest/last_output", str(out))
    dlg = _dlg(con, tmp_path / "ARCH", off_thread=True)
    dlg.show()
    assert entered.wait(10)
    t0 = time.monotonic()
    dlg.done(0)
    assert time.monotonic() - t0 < 5                                     # anulowanie, nie limit 10 s
    assert dlg.isHidden()
    assert _wait_until(lambda: dlg._dry_thread is None)
    assert dlg.table.rowCount() == 0 and dlg._plan is None
    con.close()


def test_realny_qthread_pasek_sondy_gasnie_po_wyczyszczeniu_pola(qapp, tmp_path, ustawienia, monkeypatch):
    """Pole wyczyszczone w trakcie sondy: sonda dostaje anulowanie, wczesny powrót gasi pasek
    „pracuję” i nic nie zlecono - po sprzątnięciu wątku pasek nie wisi, zdanie prosi o katalog."""
    con, _profile, _flats = _baza(tmp_path)
    out = _wyjscie(tmp_path, {"masterFlat_A.xisf": b"A", "masterFlat_B.xisf": b"B"})
    gate, entered = _bramka_sondy(monkeypatch)
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls(), "masterFlat_B.xisf": _flat_ha()},
             gate=gate, entered=entered)
    ustawienia.setValue("harvest/last_output", str(out))
    dlg = _dlg(con, tmp_path / "ARCH", off_thread=True)
    assert entered.wait(10) and not dlg.busy.isHidden()
    dlg.edit_output.clear()
    dlg._on_output_edited(force=True)
    assert _wait_until(lambda: dlg._dry_thread is None)
    assert dlg.busy.isHidden() and dlg.table.rowCount() == 0
    assert dlg.notice.text() == "Wskaż katalog wyjścia WBPP - podgląd policzy się sam."
    con.close()


# ---------------------------------------------------------------- klawiatura

def test_enter_w_polu_sonduje_a_nie_wciaga(qapp, tmp_path, ustawienia, monkeypatch):
    """Prawdziwe klawisze w polu z fokusem: wpisana ścieżka + Enter = podgląd, NIE kopia (Enter nie
    dochodzi do domyślnego „Wciągnij”); drugi Enter na tej samej ścieżce też nic nie kopiuje.
    Klik w „Wciągnij” prosto z pola (wyjście z pola = `editingFinished`) nie unieważnia planu,
    który ten klik wydaje."""
    con, _profile, _flats = _baza(tmp_path)
    archive = tmp_path / "ARCH"
    out = _wyjscie(tmp_path, {"masterFlat_A.xisf": b"A"})
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls()})
    dlg = _dlg(con, archive)
    dlg.show()
    dlg.activateWindow()
    dlg.edit_output.setFocus()
    qapp.processEvents()
    assert dlg.edit_output.hasFocus()
    QTest.keyClicks(dlg.edit_output, str(out))
    assert dlg.table.rowCount() == 0                                     # pisanie nie sonduje
    QTest.keyClick(dlg.edit_output, Qt.Key_Return)
    assert dlg.btn_apply.isEnabled() and dlg.btn_apply.text() == "Wciągnij 1 plik"
    assert dlg.isVisible() and not archive.exists()
    QTest.keyClick(dlg.edit_output, Qt.Key_Return)
    assert not archive.exists() and dlg.edit_output.hasFocus() and dlg.isVisible()
    QTest.mouseClick(dlg.btn_apply, Qt.LeftButton)
    assert _cel(archive).exists()
    con.close()


# ---------------------------------------------------------------- EN

def test_en_render_z_katalogu(qapp, tmp_path, ustawienia, monkeypatch):
    """`set_lang('en')` przed budową: tytuł, nagłówek, przycisk z liczbą mnogą, słowa statusów
    i powody renderują EN z katalogu; `detail` rdzenia to DANE (symbole, wartości), nie polskie
    zdanie w angielskim oknie; po apply przyciski i `summary` też EN."""
    i18n.set_lang("en")
    con, _profile, _flats = _baza(tmp_path)
    archive = tmp_path / "ARCH"
    out = _wyjscie(tmp_path, {"masterFlat_A.xisf": b"A", "masterFlat_B.xisf": b"B",
                              "masterDark_D.xisf": b"D", "masterFlat_X.xisf": b"X"})
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls(), "masterFlat_B.xisf": _flat_ha(),
                           "masterDark_D.xisf": {"kind": "master_dark"},
                           "masterFlat_X.xisf": {**_flat_ha(), "filter_raw": "OIII"}})
    dlg = _dlg(con, archive)
    assert dlg.windowTitle() == "Harvest WBPP results"
    assert dlg.notice.text() == "Choose the WBPP output folder - the preview computes itself."
    dlg._set_output(str(out))
    assert dlg.head_label.text() == "To harvest 2 · already in the archive 0 · to review 2"
    assert dlg.btn_apply.text() == "Harvest 2 files"
    rows = _wiersze(dlg)
    assert {_kol(dlg, r, COL_STATUS) for r in rows.values()} == {"to harvest", "to review"}
    assert _kol(dlg, rows["masterDark_D.xisf"], COL_REASON).startswith("dark/bias master")
    powod = _kol(dlg, rows["masterFlat_X.xisf"], COL_REASON)
    assert powod.startswith("the file header disagrees with its inputs: ")
    assert "OIII" in powod and "Ha" in powod and not _PL_LITERY.search(powod)
    assert [dlg.table.horizontalHeaderItem(c).text() for c in range(dlg.table.columnCount())] == \
        ["File", "Kind", "Status", "Reason", "Target name", "Target folder", "Release"]
    assert _kol(dlg, rows["masterFlat_A.xisf"], COL_KIND) == "master flat"
    assert _kol(dlg, rows["masterDark_D.xisf"], COL_KIND) == "master dark"
    assert _kol(dlg, rows["masterFlat_A.xisf"], COL_RELEASE) == "outside a Horreum release"
    dlg._on_apply()
    assert dlg.head_label.text().startswith("Harvested 2 · skipped 0 (already in the archive)")
    assert dlg.btn_apply.text() == "Harvested"
    assert dlg.btn_accept.text() == "Close and receive into the archive"
    assert dlg.summary.startswith("Harvested 2 files into the archive → ")
    con.close()


# ---------------------------------------------------------------- lista wydań i stosy

LIGHT_SEAT = ("IC1795", "76EDPH_2600MM", "Ha")      # ogon lightów pod `LIGHTS` = siedziba stosu pod `STACKS`
STOS = "masterLight_BIN-1_6248x4176_EXPOSURE-600.00s_FILTER-H_mono.xisf"
STOS_CROP = "masterLight_BIN-1_6248x4176_EXPOSURE-600.00s_FILTER-H_mono_autocrop.xisf"
NAZWA_STOSU = "IC1795_2025-12-16_76EDPH_2600MM_Ha_600s_mono.xisf"
# mtime wyjścia WBPP: PO wydaniach testów (najpóźniejsze 2026-10-10T10:00Z), PRZED zeznaniem żniw (`NOW`) -
# wynik nowszy od wydania nie czeka na WBPP, a zeznanie i tak rozstrzyga po `src_mtime_ns`.
_PO_WYDANIU = datetime.fromisoformat("2026-10-10T11:00:00+00:00").timestamp()


def _lighty(con, archive, n=3):
    """`n` lightów IC1795 Ha 600 s w `<archiwum>/LIGHTS/<ogon>` (zestaw configu 10 z `_baza`)."""
    names, ids = [], []
    for i in range(n):
        name = f"20251216_1727{i:02d}_IC1795_LIGHT_Ha_600s_{i:04d}.fits"
        cur = con.execute(
            "INSERT INTO frame (sha1_data, kind, filetype, camera_id, config_id, filter_canon, first_seen_at) "
            "VALUES (?, 'light', 'fits', 1, 10, 'Ha', ?)", (f"light-{name}", NOW))
        fid = cur.lastrowid
        con.execute("INSERT INTO header (frame_id, raw_json, date_obs, exptime) VALUES (?, '{}', ?, 600.0)",
                    (fid, "2025-12-16T17:27:54"))
        con.execute("INSERT INTO location (frame_id, volume, path, present) VALUES (?, 'V', ?, 1)",
                    (fid, str(archive.joinpath("LIGHTS", *LIGHT_SEAT, name))))
        con.commit()
        names.append(name)
        ids.append(fid)
    return names, ids


def _wydanie_obiektu(work, obiekt, *, ts, zestawy=None, con=None):
    """Folder wydania `<work>/OBJECTS/<obiekt>` z manifestem układu obiektu; zwraca korzeń wydania.
    Z `con` (bez `zestawy`) zestaw wydania obejmuje wszystkie surowe flaty bazy - masterflat z tego
    wyjścia ma wtedy świadka wydania, a nie `outside_release`."""
    root = work / projection.OBJECT_NAMESPACE / obiekt
    root.mkdir(parents=True)
    if zestawy is None and con is not None:
        zestawy = {SEG: {"flat_raw": _flats_ids(con, "CLS") + _flats_ids(con, "Ha")}}
    manifest = {"layout": projection.OBJECT_LAYOUT, "object_canon": obiekt, "root": str(root), "ts": ts,
                "zestawy": zestawy or {}}
    (root / projection.MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
    return root


def _wyniki(root, pliki):
    """Pliki wyjścia WBPP w `<wydanie>/out/master` z mtime sprzed zeznania żniw (`NOW`)."""
    out = root / projection.OUTPUT_DIR / "master"
    out.mkdir(parents=True, exist_ok=True)
    for name, data in pliki.items():
        (out / name).write_bytes(data)
        os.utime(out / name, (_PO_WYDANIU, _PO_WYDANIU))
    return root / projection.OUTPUT_DIR


def _stos(names, *, sha):
    """Zeznanie stosu WBPP: wejścia = nazwy lightów wydania + `_c_r` (krok rejestracji)."""
    return {"kind": "master_light", "sha1_data": sha, "filter_raw": "H", "exptime": 600.0,
            "date_obs": "2025-12-16T17:27:54",
            "inputs": [f"C:/WBPP/registered/{os.path.splitext(n)[0]}_c_r.xisf" for n in names],
            "header": {"IMAGETYP": "Master Light", "FILTER": "H", "TELESCOP": "76EDPH",
                       "INSTRUME": "ZWO ASI2600MM Pro", "DATE-OBS": "2025-12-16T17:27:54",
                       "EXPTIME": "600.000"}}


def _pulpit(monkeypatch):
    """Podmiana `QDesktopServices` - test nie otwiera Eksploratora, tylko zapisuje ścieżki."""
    otwarte = []
    monkeypatch.setattr(hd_mod, "QDesktopServices",
                        SimpleNamespace(openUrl=lambda url: otwarte.append(url.toLocalFile())))
    return otwarte


def _stan(dlg, row):
    return dlg.rel_table.item(row, REL_STATE).text()


def _klik_wiersza(dlg, row):
    """Klik myszą w wiersz listy wydań (okno pokazane)."""
    item = dlg.rel_table.item(row, 0)
    QTest.mouseClick(dlg.rel_table.viewport(), Qt.LeftButton, pos=dlg.rel_table.visualItemRect(item).center())


def test_stan_wiersza_data_i_korzenie_kart():
    """Stan wiersza: zera milczą, bez kandydatów „czeka na WBPP”; kandydaci bez rozstrzygającego
    zeznania to „do sprawdzenia”, „do wciągnięcia” mówi dopiero świeży plan; wydanie nowsze od wyników
    czeka na WBPP, a wciągnięte z nich są „poprzednio”. Zdanie o kasowaniu wyłącznie bez przeglądu
    i bez czekania na WBPP; przegląd bez niczego do wciągnięcia ma własne zdanie. Data lokalna bez
    sekund; ta sama karta pod dwiema pisowniami liczy się raz, folder roboczy pierwszy."""
    row = lambda p, d, r, czeka=False: harvest.ReleaseRow(  # noqa: E731
        "K", "K/OBJECTS/X", "X", None, "K/OBJECTS/X/out", p, d, r, awaiting_wbpp=czeka)
    assert release_state_text(row(0, 0, 0)) == "czeka na WBPP"
    assert release_state_text(row(3, 0, 0)) == "do sprawdzenia 3"
    assert release_state_text(row(0, 3, 0)) == "wciągnięte 3"
    assert release_state_text(row(1, 2, 1)) == "do sprawdzenia 1 · wciągnięte 2 · do przeglądu 1"
    assert release_state_text(row(8, 0, 0), fresh=(1, 2, 5)) == "do wciągnięcia 1 · wciągnięte 2 · do przeglądu 5"
    assert release_state_text(row(0, 3, 0, czeka=True)) == "czeka na WBPP · poprzednio wciągnięte 3"
    assert is_harvested(row(0, 3, 0)) and not needs_review(row(0, 3, 0))
    assert not is_harvested(row(0, 3, 1)) and needs_review(row(0, 3, 1))          # pliki przeglądu tylko tam
    assert not is_harvested(row(0, 3, 0, czeka=True))                             # wyniki nie z ostatniego wydania
    assert not is_harvested(row(1, 3, 0)) and not needs_review(row(1, 0, 1))
    assert not is_harvested(row(5, 0, 0), fresh=(0, 0, 2)) and needs_review(row(5, 0, 0), fresh=(0, 0, 2))
    assert is_harvested(row(0, 3, 0), fresh=(0, 3, 0)) and not is_harvested(row(0, 3, 0), fresh=(1, 3, 0))
    # AR-104: stos bez rodowodu dokładnego trzyma folder - własny stan i własne zdanie, nie „skasuj”.
    z_rodowodem = harvest.ReleaseRow("K", "K/OBJECTS/X", "X", None, "K/OBJECTS/X/out", 0, 3, 0,
                                     lineage=(("s", (1, 2), "K/STACKS/s.xisf"),))
    assert release_state_text(z_rodowodem) == "wciągnięte 3 · rodowód do zapisania 1"
    assert not is_harvested(z_rodowodem) and needs_lineage(z_rodowodem) and not needs_review(z_rodowodem)
    assert not is_harvested(z_rodowodem, fresh=(0, 3, 0)) and not needs_lineage(z_rodowodem, fresh=(1, 3, 0))
    assert not needs_lineage(row(0, 3, 0))
    assert preselect_index([row(0, 3, 0), z_rodowodem, row(1, 0, 0)]) == 2       # robota do wciągnięcia pierwsza
    assert preselect_index([row(0, 3, 0), z_rodowodem]) == 1                      # potem rodowód (wizytator Z13)
    assert preselect_index([row(0, 3, 0, czeka=True), row(2, 0, 0), row(4, 0, 0)]) == 1
    assert preselect_index([row(0, 3, 0, czeka=True), row(0, 0, 0)]) is None
    lokalnie = time.strftime("%Y-%m-%d %H:%M", time.localtime(1760097600))     # 2025-10-10T12:00:00Z
    assert release_date_text("2025-10-10T12:00:00+00:00") == lokalnie
    assert release_date_text("zepsuty") == "zepsuty" and release_date_text(None) == ""
    assert release_roots_of(r"E:\W\_WBPP", ["e:/w/_wbpp", r"F:\Karta", "", r"f:\karta\\"]) == \
        (r"E:\W\_WBPP", r"F:\Karta")
    assert release_roots_of(None, ()) == ()


def test_lista_wydan_stany_kolejnosc_i_wybor_startowy(qapp, tmp_path, ustawienia, monkeypatch, wybor_katalogu):
    """Lista nad polem od najnowszego wydania; na starcie zaznaczone najnowsze wydanie z kandydatami
    (nie najnowsze w ogóle), pole = jego `out` i podgląd policzony - bez okna wyboru katalogu. Wiersz
    zaznaczony mówi świeżym planem („do wciągnięcia”), wiersz bez zeznania i bez podglądu - „do
    sprawdzenia”; wydanie bez wyników WBPP - „czeka na WBPP”."""
    con, _profile, _flats = _baza(tmp_path)
    work = tmp_path / "ASTRO_" / "_WBPP"
    stare = _wydanie_obiektu(work, "M31", ts="2026-10-08T10:00:00+00:00", con=con)
    ic = _wydanie_obiektu(work, "IC1795", ts="2026-10-09T10:00:00+00:00", con=con)
    _wydanie_obiektu(work, "NGC7000", ts="2026-10-10T10:00:00+00:00")
    _wyniki(stare, {"masterFlat_M31.xisf": b"M"})
    out = _wyniki(ic, {"masterFlat_IC.xisf": b"I"})
    _czytnik(monkeypatch, {"masterFlat_M31.xisf": _flat_ha(), "masterFlat_IC.xisf": _flat_cls()})
    dlg = _dlg(con, tmp_path / "ARCH", work_root=str(work))
    dlg.show()
    QTest.qWait(30)
    assert wybor_katalogu.wywolania == []                                # lista jest wyborem - okno wyboru nie wyskakuje
    assert [dlg.rel_table.item(r, 0).text() for r in range(dlg.rel_table.rowCount())] == ["NGC7000", "IC1795", "M31"]
    assert [_stan(dlg, r) for r in range(3)] == ["czeka na WBPP", "do wciągnięcia 1", "do sprawdzenia 1"]
    assert dlg.rel_table.item(1, 1).text() == str(work)
    assert [i.row() for i in dlg.rel_table.selectionModel().selectedRows()] == [1]
    assert dlg.edit_output.text() == str(out)
    assert dlg.btn_apply.isEnabled() and dlg.btn_apply.text() == "Wciągnij 1 plik"
    assert _kol(dlg, 0, COL_FILE) == os.path.join("master", "masterFlat_IC.xisf")
    assert [dlg.table.horizontalHeaderItem(c).text() for c in range(dlg.table.columnCount())] == \
        ["Plik", "Rodzaj", "Stan", "Powód", "Nazwa docelowa", "Katalog docelowy", "Wydanie"]
    assert _kol(dlg, 0, COL_KIND) == "master flat"
    assert dlg.rel_notice.text() == "" and dlg.rel_done_note.isHidden() and dlg.btn_open_release.isHidden()
    con.close()


def test_wybor_wiersza_pole_i_podglad_bez_drugiej_sondy(qapp, tmp_path, ustawienia, monkeypatch):
    """Klik w wiersz = pole `<wydanie>\\out` i świeży podgląd; ścieżka wpisana ręcznie w pole i Enter
    przenosi zaznaczenie na swój wiersz albo je zdejmuje - zaznaczenie idzie za polem."""
    con, _profile, _flats = _baza(tmp_path)
    work = tmp_path / "_WBPP"
    a = _wydanie_obiektu(work, "A", ts="2026-10-09T10:00:00+00:00", con=con)
    b = _wydanie_obiektu(work, "B", ts="2026-10-08T10:00:00+00:00", con=con)
    out_a = _wyniki(a, {"masterFlat_A.xisf": b"A"})
    out_b = _wyniki(b, {"masterFlat_B.xisf": b"B", "masterFlat_B2.xisf": b"B2"})
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls(), "masterFlat_B.xisf": _flat_ha(),
                           "masterFlat_B2.xisf": {"kind": "master_dark"}})
    dlg = _dlg(con, tmp_path / "ARCH", release_roots=[str(work)])
    dlg.show()
    assert dlg.edit_output.text() == str(out_a)
    _klik_wiersza(dlg, 1)
    assert dlg.edit_output.text() == str(out_b)
    assert dlg.head_label.text() == "Do wciągnięcia 1 · już w archiwum 0 · do przeglądu 1"
    assert ustawienia.value("harvest/last_output") == str(out_b)
    dlg.edit_output.setFocus()
    qapp.processEvents()
    dlg.edit_output.setText(str(out_a))
    QTest.keyClick(dlg.edit_output, Qt.Key_Return)
    assert [i.row() for i in dlg.rel_table.selectionModel().selectedRows()] == [0]
    dlg.edit_output.setText(str(tmp_path))
    QTest.keyClick(dlg.edit_output, Qt.Key_Return)
    assert dlg.rel_table.selectionModel().selectedRows() == []
    con.close()


def test_bez_folderu_roboczego_i_kart_zdanie_a_puste_karty_pamiec_pola(qapp, tmp_path, ustawienia, monkeypatch,
                                                                       wybor_katalogu):
    """Bez folderu roboczego i bez kart: zdanie, gdzie go ustawić, listy nie ma, a pierwsze użycie
    otwiera okno wyboru jak dotąd. Karty bez wydań: zdanie o pustych kartach nad pustą listą (miejsce
    listy stoi), podgląd z pamięci pola, bez okna wyboru."""
    con, _profile, _flats = _baza(tmp_path)
    dlg = _dlg(con, tmp_path / "ARCH")
    dlg.show()
    assert _wait_until(lambda: wybor_katalogu.wywolania)
    assert dlg.rel_notice.text() == "Ustaw folder roboczy: Plik → Folder roboczy WBPP…"
    assert not dlg.rel_notice.isHidden() and dlg.rel_table.isHidden()
    out = _wyjscie(tmp_path, {"masterFlat_A.xisf": b"A"})
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls()})
    ustawienia.setValue("harvest/last_output", str(out))
    (tmp_path / "_WBPP").mkdir()
    dlg2 = _dlg(con, tmp_path / "ARCH", work_root=str(tmp_path / "_WBPP"))
    dlg2.show()
    QTest.qWait(30)
    assert len(wybor_katalogu.wywolania) == 1
    assert dlg2.rel_notice.text() == "Na kartach nie ma jeszcze wydań obiektu."
    assert not dlg2.rel_table.isHidden() and dlg2.rel_table.rowCount() == 0
    assert dlg2.edit_output.text() == str(out) and dlg2.btn_apply.text() == "Wciągnij 1 plik"
    con.close()


def test_wskaz_startuje_w_objects_folderu_roboczego(qapp, tmp_path, ustawienia, monkeypatch, wybor_katalogu):
    """„Wskaż…” startuje w `<folder roboczy>\\OBJECTS`, gdy istnieje; bez niego - w ostatnim wyjściu."""
    con, _profile, _flats = _baza(tmp_path)
    _czytnik(monkeypatch, {})
    work = tmp_path / "_WBPP"
    ustawienia.setValue("harvest/last_output", str(tmp_path / "ostatnie"))
    dlg = _dlg(con, tmp_path / "ARCH", work_root=str(work))
    dlg.btn_pick.click()
    assert wybor_katalogu.wywolania[-1][1] == str(tmp_path / "ostatnie")
    assert not work.exists()                                             # wskazanie niczego nie zakłada
    (work / projection.OBJECT_NAMESPACE).mkdir(parents=True)
    dlg.btn_pick.click()
    assert wybor_katalogu.wywolania[-1][1] == str(work / projection.OBJECT_NAMESPACE)
    con.close()


def _wydanie_ic1795(tmp_path, con, archive, *, z_flatem=True):
    """Wydanie IC1795 na folderze roboczym: 3 lighty w archiwum (manifest z `names`), w `out\\master`
    stos z historią DWÓCH lightów (trzeci odrzucony przez WBPP), jego wariant `_autocrop`, produkty
    obróbki (`HOS`, `…_starless`) i - opcjonalnie - masterflat z surowych flatów wydania."""
    names, ids = _lighty(con, archive)
    work = tmp_path / "ASTRO_" / "_WBPP"
    zestawy = {SEG: {"lights": ids, "names": dict(zip(names, ids)),
                     "flat_raw": _flats_ids(con, "CLS") if z_flatem else []}}
    root = _wydanie_obiektu(work, "IC1795", ts="2026-10-09T20:00:00+00:00", zestawy=zestawy)
    pliki = {STOS: b"STOS-HA", STOS_CROP: b"STOS-HA-CROP", "HOS.xisf": b"HOS",
             "masterLight_BIN-1_FILTER-H_mono_starless.xisf": b"SL"}
    zeznania = {STOS: _stos(names[:2], sha="stos-ha"), STOS_CROP: _stos(names[:2], sha="stos-crop")}
    if z_flatem:
        pliki["masterFlat_BIN-1_FILTER-CLS_mono.xisf"] = b"MF-CLS"
        zeznania["masterFlat_BIN-1_FILTER-CLS_mono.xisf"] = _flat_cls()
    out = _wyniki(root, pliki)
    return work, root, out, ids, zeznania


def _flats_ids(con, filt):
    return [r[0] for r in con.execute("SELECT id FROM frame WHERE kind = 'flat' AND filter_canon = ? ORDER BY id",
                                      (filt,))]


def test_stos_z_wydania_do_stacks_korzen_archiwum_i_rodowod_po_przyjeciu(qapp, tmp_path, ustawienia,
                                                                          monkeypatch):
    """Scenariusz wizytatora na oknie: wiersz „do wciągnięcia 3” zaznaczony sam (stos, wariant, master
    flat; produkty obróbki poza listą) → stosy do `<archiwum>\\STACKS\\<ogon lightów>` pod nazwą
    archiwum, master flat pod `CALIBRATION` → po „Wciągnij” lista mówi „wciągnięte 3 · rodowód do
    zapisania 2” i zdanie o „Zamknij i przyjmij” zamiast „folder możesz skasować” (AR-104: zbiór wejść
    stosów leży tylko w zeznaniu w folderze wydania), bez „Otwórz” → „Zamknij i przyjmij” oddaje KORZEŃ
    ARCHIWUM (sito `STACKS`) i dokładny zbiór wejść stosów; przed przyjęciem `harvested_stacks` puste.
    Ponowny podgląd po biegu (stosy leżą, baza ich nie zna) nie dubluje stosów - jeden wpis na
    `sha1_data`."""
    con, _profile, _flats = _baza(tmp_path)
    archive = tmp_path / "ARCH"
    work, root, out, ids, zeznania = _wydanie_ic1795(tmp_path, con, archive)
    _czytnik(monkeypatch, zeznania)
    otwarte = _pulpit(monkeypatch)
    dlg = _dlg(con, archive, work_root=str(work))
    dlg.show()
    assert _stan(dlg, 0) == "do wciągnięcia 3" and dlg.edit_output.text() == str(out)
    assert dlg.head_label.text() == "Do wciągnięcia 3 · już w archiwum 0 · do przeglądu 0"
    rows = _wiersze(dlg)
    seat = archive.joinpath("STACKS", *LIGHT_SEAT)
    r = rows[os.path.join("master", STOS)]
    assert _kol(dlg, r, COL_KIND) == "stos" and _kol(dlg, r, COL_NAME) == NAZWA_STOSU
    assert _kol(dlg, r, COL_DIR) == os.path.join("STACKS", *LIGHT_SEAT)
    assert _kol(dlg, r, COL_RELEASE) == f"IC1795 / {SEG}"
    assert _kol(dlg, rows[os.path.join("master", STOS_CROP)], COL_NAME) == \
        "IC1795_2025-12-16_76EDPH_2600MM_Ha_600s_mono_autocrop.xisf"
    dlg.btn_apply.click()
    assert (seat / NAZWA_STOSU).read_bytes() == b"STOS-HA" and _cel(archive).read_bytes() == b"MF-CLS"
    assert _stan(dlg, 0) == "wciągnięte 3 · rodowód do zapisania 2"     # lista przeliczona po biegu
    assert [i.row() for i in dlg.rel_table.selectionModel().selectedRows()] == [0]
    assert not dlg.rel_done_note.isHidden() and dlg.btn_open_release.isHidden()
    assert dlg.rel_done_note.text() == (
        "Stosy z tego wydania czekają na rodowód dokładny - zapisze go „Zamknij i przyjmij do archiwum”. "
        "Zbiór ich wejść leży tylko w tym folderze, więc nie kasuj go do tego czasu.")
    assert otwarte == [] and root.is_dir()
    assert dlg.harvested_stacks == [] and dlg.harvested_root is None
    assert dlg.summary == f"Wciągnięto 3 pliki do archiwum → {archive}"
    dlg._set_output(str(out))                                            # „Wskaż…” tego samego wyjścia po biegu
    assert dlg.head_label.text() == "Do wciągnięcia 0 · już w archiwum 3 · do przeglądu 0"
    assert _stan(dlg, 0) == "wciągnięte 3 · rodowód do zapisania 2" and not dlg.rel_done_note.isHidden()
    dlg.btn_accept.click()
    assert dlg.result() == QDialog.Accepted and dlg.harvested_root == str(archive)
    assert sorted(dlg.harvested_stacks) == [("stos-crop", tuple(ids[:2])), ("stos-ha", tuple(ids[:2]))]
    con.close()


def test_przyjecie_samego_stosu_korzen_archiwum_zwykle_zamknij_bez_stosow(qapp, tmp_path, ustawienia,
                                                                          monkeypatch):
    """Sam stos (bez mastera) też daje korzeń archiwum, nie wspólny rodzic kopii; zwykłe „Zamknij”
    nie oddaje ani korzenia, ani stosów, a zdanie paska mówi, że rodowód dokładny zapisze tylko
    „Zamknij i przyjmij” (AR-104), i kończy się ścieżką za instrukcją."""
    con, _profile, _flats = _baza(tmp_path)
    archive = tmp_path / "ARCH"
    work, _root, _out, _ids, zeznania = _wydanie_ic1795(tmp_path, con, archive, z_flatem=False)
    _czytnik(monkeypatch, zeznania)
    ustawienia.setValue("pipeline/last_source", str(archive))
    dlg = _dlg(con, archive, work_root=str(work))
    dlg._on_apply()
    assert dlg._receivable_root() == (str(archive), None)
    dlg.reject()
    assert dlg.harvested_root is None and dlg.harvested_stacks == []
    assert dlg.summary == ("Wciągnięto 2 pliki do archiwum (stosy bez rodowodu dokładnego: 2 - zapisze go tylko "
                           "„Zamknij i przyjmij do archiwum”, także po ponownym otwarciu tego okna; folderu wydania "
                           "nie kasuj) - baza pozna je przy następnej dostawie („Przyjmij”) → "
                           f"{archive.joinpath('STACKS', *LIGHT_SEAT)}")
    con.close()


def test_ar100_kopie_nieznane_bazie_bez_placed_daja_przyjecie(qapp, tmp_path, ustawienia, monkeypatch):
    """AR-100: kopie, które leżą w archiwum (master flat w siedzibie, stos w `STACKS`), a których baza
    nie zna - plan mówi `exists` bez nowej kopii. „Zamknij i przyjmij” jest widoczny, archiwum
    zablokowane, korzeń = korzeń archiwum (jest stos), a stos położony w innym oknie dostaje rodowód
    dokładny (zbiór wejść z planu); zwykłe „Zamknij” mówi, ile kopii czeka i którędy baza do nich
    dojdzie, i stosów nie oddaje."""
    con, _profile, _flats = _baza(tmp_path)
    archive = tmp_path / "ARCH"
    work, _root, out, ids, zeznania = _wydanie_ic1795(tmp_path, con, archive)
    _cel(archive).parent.mkdir(parents=True)
    _cel(archive).write_bytes(b"MF-CLS")                                # wciągnięte w innym oknie, bez przyjęcia
    seat = archive.joinpath("STACKS", *LIGHT_SEAT)
    seat.mkdir(parents=True)
    (seat / "stos_recznie.xisf").write_bytes(b"STOS-HA")
    _czytnik(monkeypatch, zeznania)
    ustawienia.setValue("pipeline/last_source", str(tmp_path / "INNE"))
    dlg = _dlg(con, archive, work_root=str(work))
    assert dlg.head_label.text() == "Do wciągnięcia 1 · już w archiwum 2 · do przeglądu 0"
    assert not dlg.btn_accept.isHidden() and dlg.btn_accept.isEnabled()
    assert not dlg.btn_archive.isEnabled()
    assert dlg.summary == f"W archiwum leżą 2 kopie nieznane bazie → {archive}"
    dlg2 = _dlg(con, archive, work_root=str(work))
    dlg2.reject()
    assert dlg2.summary == ("W archiwum leżą 2 kopie nieznane bazie (stosy bez rodowodu dokładnego: 1 - zapisze "
                            "go tylko „Zamknij i przyjmij do archiwum”, także po ponownym otwarciu tego okna; "
                            "folderu wydania nie kasuj) - kopie leżą poza źródłem Dostawy; baza pozna je przez "
                            f"„Zamknij i przyjmij do archiwum” albo Dostawę wskazaną na archiwum → {archive}")
    assert dlg2.harvested_stacks == []
    dlg.btn_accept.click()
    assert dlg.result() == QDialog.Accepted and dlg.harvested_root == str(archive)
    assert dlg.harvested_stacks == [("stos-ha", tuple(ids[:2]))]
    assert out.exists()
    con.close()


NAZWA_STOSU_CROP = "IC1795_2025-12-16_76EDPH_2600MM_Ha_600s_mono_autocrop.xisf"


def _dostawa_po_zwyklym_zamknij(con, archive):
    """Osobna Dostawa po zwykłym „Zamknij”: master flat i oba stosy znane bazie (obecne kopie tam, gdzie
    je położyły żniwa), a łańcuch dał stosom rodowód okna rozjechany z historią pliku - głowa
    `history_mismatch`, zero wierszy (stan z wizytacji W1 fali 9)."""
    seat = archive.joinpath("STACKS", *LIGHT_SEAT)
    for sha, kind, filt, path in (("sd-masterFlat_BIN-1_FILTER-CLS_mono.xisf", "master_flat", "CLS", _cel(archive)),
                                  ("stos-ha", "master_light", "Ha", seat / NAZWA_STOSU),
                                  ("stos-crop", "master_light", "Ha", seat / NAZWA_STOSU_CROP)):
        cur = con.execute("INSERT INTO frame (sha1_data, kind, filetype, camera_id, config_id, filter_canon, "
                          "first_seen_at) VALUES (?, ?, 'xisf', 1, 10, ?, ?)", (sha, kind, filt, NOW))
        con.execute("INSERT INTO location (frame_id, volume, path, present) VALUES (?, 'V', ?, 1)",
                    (cur.lastrowid, str(path)))
        con.commit()
        if kind == "master_light":
            repo.upsert_integration(
                con, master_frame_id=cur.lastrowid, integ_hash=None, tool=None,
                window_start="2025-12-16T17:00:00", window_end="2025-12-16T19:00:00", declared_rows=2,
                drizzle_inputs=None, disabled_inputs=None, degenerate=0, ambiguous=0, telescope_mismatch=0,
                unresolved_reason="history_mismatch", now=NOW)
    return seat


def test_ar104_zwykle_zamknij_dostawa_ponowne_okno_oddaje_zbior_dokladny(qapp, tmp_path, ustawienia,
                                                                          monkeypatch):
    """AR-104 (wizytacja W1 fali 9): stosy wciągnięte, zwykłe „Zamknij” - pasek mówi, że rodowód
    dokładny zapisze tylko „Zamknij i przyjmij”; potem osobna Dostawa (stosy znane bazie, rodowód okna
    rozjechany z historią). Ponowne okno OD OTWARCIA: wiersz „wciągnięte 3 · rodowód do zapisania 2”,
    zdanie o „Zamknij i przyjmij” zamiast „folder możesz skasować”, bez „Otwórz”, przycisk przyjęcia
    widoczny, archiwum zablokowane, a przyjęcie oddaje korzeń archiwum (łańcuch) i zbiór dokładny obu
    stosów. Po zapisie rodowodu trzecie okno: „wciągnięte 3”, zdanie o kasowaniu i „Otwórz” (otwiera,
    nie kasuje), bez przyjęcia i bez zdania na pasku."""
    con, _profile, _flats = _baza(tmp_path)
    archive = tmp_path / "ARCH"
    work, root, _out, ids, zeznania = _wydanie_ic1795(tmp_path, con, archive)
    _czytnik(monkeypatch, zeznania)
    otwarte = _pulpit(monkeypatch)
    ustawienia.setValue("pipeline/last_source", str(archive))
    dlg = _dlg(con, archive, work_root=str(work))
    dlg._on_apply()
    dlg.reject()
    assert dlg.harvested_root is None and dlg.harvested_stacks == []
    assert dlg.summary == ("Wciągnięto 3 pliki do archiwum (stosy bez rodowodu dokładnego: 2 - zapisze go tylko "
                           "„Zamknij i przyjmij do archiwum”, także po ponownym otwarciu tego okna; folderu wydania "
                           f"nie kasuj) - baza pozna je przy następnej dostawie („Przyjmij”) → {archive}")
    seat = _dostawa_po_zwyklym_zamknij(con, archive)

    dlg2 = _dlg(con, archive, work_root=str(work))
    assert _stan(dlg2, 0) == "wciągnięte 3 · rodowód do zapisania 2"
    assert dlg2.head_label.text() == "Do wciągnięcia 0 · już w archiwum 3 · do przeglądu 0"
    assert not dlg2.rel_done_note.isHidden() and dlg2.btn_open_release.isHidden()
    assert dlg2.rel_done_note.text().startswith("Stosy z tego wydania czekają na rodowód dokładny")
    assert dlg2.rel_done_note.property("role") == "warn"                 # wstrzymuje kasowanie (wizytator Z12)
    assert not dlg2.btn_accept.isHidden() and dlg2.btn_accept.isEnabled() and not dlg2.btn_archive.isEnabled()
    # waga za jedyną robotą (wizytator Z11): przyjęcie grube, „Wciągnij 0” bez wagi; Enter nie przyjmuje
    assert dlg2.btn_accept.font().bold() and not dlg2.btn_accept.isDefault() and not dlg2.btn_accept.autoDefault()
    assert not dlg2.btn_apply.font().bold() and not dlg2.btn_apply.isDefault()
    assert dlg2.summary == f"Stosy do rodowodu dokładnego po Dostawie: 2 → {seat}"
    dlg2.btn_accept.click()
    assert dlg2.result() == QDialog.Accepted and dlg2.harvested_root == str(archive)
    assert sorted(dlg2.harvested_stacks) == [("stos-crop", tuple(ids[:2])), ("stos-ha", tuple(ids[:2]))]

    for sha, wejscia in dlg2.harvested_stacks:                         # gospodarz po łańcuchu (`app._zdanie_rodowodu`)
        assert stacks.record_harvest_inputs(con, master_sha1_data=sha, input_frame_ids=wejscia,
                                            now=NOW)["reason"] is None
    dlg3 = _dlg(con, archive, work_root=str(work))
    assert _stan(dlg3, 0) == "wciągnięte 3"
    assert dlg3.btn_accept.isHidden() and dlg3.btn_archive.isEnabled()
    assert dlg3.rel_done_note.text() == ("Folder wydania możesz skasować - Horreum go już nie potrzebuje; "
                                         "własne pliki obróbki przenieś przed skasowaniem.")
    assert dlg3.rel_done_note.property("role") == "secondary" and dlg3.btn_apply.isDefault()
    dlg3.btn_open_release.click()
    assert [os.path.normpath(p) for p in otwarte] == [str(root)] and root.is_dir()   # otwiera, nie kasuje
    dlg3.reject()
    assert dlg3.summary is None and dlg3.harvested_stacks == []
    con.close()


def test_ar104_zwykle_zamknij_samych_stosow_bez_kopii_do_przyjecia(qapp, tmp_path, ustawienia, monkeypatch):
    """Zwykłe „Zamknij” okna, w którym jedyną robotą są stosy bez rodowodu dokładnego (kopie baza zna):
    zdanie paska niesie instrukcję samo i nie mówi o następnej dostawie - Dostawa rodowodu dokładnego
    nie zapisze. EN tak samo."""
    con, _profile, _flats = _baza(tmp_path)
    archive = tmp_path / "ARCH"
    work, _root, _out, _ids, zeznania = _wydanie_ic1795(tmp_path, con, archive)
    _czytnik(monkeypatch, zeznania)
    _dlg(con, archive, work_root=str(work))._on_apply()
    _dostawa_po_zwyklym_zamknij(con, archive)
    dlg = _dlg(con, archive, work_root=str(work))
    dlg.reject()
    assert dlg.summary == ("Stosy w archiwum bez rodowodu dokładnego: 2 - zapisze go tylko „Zamknij i przyjmij "
                           "do archiwum” w oknie żniw; folderu wydania nie kasuj do tego czasu")
    i18n.set_lang("en")
    dlg = _dlg(con, archive, work_root=str(work))
    assert _stan(dlg, 0) == "harvested 3 · lineage to record 2"
    dlg.reject()
    assert dlg.summary == ("Stacks in the archive without their exact lineage: 2 - only \"Close and receive into "
                           "the archive\" in the harvest window records it; keep the release folder until then")
    con.close()


def test_okno_bez_archiwum_nie_radzi_kasowac_folderu(qapp, tmp_path, ustawienia, monkeypatch):
    """Bramka `kimi` Z6: okno bez archiwum (baza bez archiwum, puste źródło Dostawy) nie policzy
    rodowodu stosów - puste `lineage` znaczy „nie wiem”, więc wiersz „wciągnięte 3” NIE dostaje zdania
    o kasowaniu ani „Otwórz”, choć zbiór dokładny leży tylko w zeznaniu w folderze wydania."""
    con, _profile, _flats = _baza(tmp_path)
    archive = tmp_path / "ARCH"
    work, _root, out, _ids, zeznania = _wydanie_ic1795(tmp_path, con, archive)
    _czytnik(monkeypatch, zeznania)
    _dlg(con, archive, work_root=str(work))._on_apply()
    dlg = _dlg(con, "", work_root=str(work))
    assert _stan(dlg, 0) == "wciągnięte 3" and dlg.edit_output.text() == str(out)
    assert [i.row() for i in dlg.rel_table.selectionModel().selectedRows()] == [0]
    assert dlg.rel_done_note.isHidden() and dlg.btn_open_release.isHidden()
    con.close()


def test_okno_na_archiwum_innym_niz_baza_nie_radzi_kasowac_folderu(qapp, tmp_path, ustawienia, monkeypatch):
    """Wizytator Z9 (bliźniak AR-105): okno, które samo wciąga do archiwum innego niż archiwum bazy,
    liczy wiersz „wciągnięte 1” wobec swojego archiwum, ale o kasowaniu milczy - Dostawa bazy tych
    kopii nie zobaczy, a jedynym źródłem do archiwum bazy jest dalej folder wydania. Ostrzeżenie
    o archiwum stoi nad listą."""
    archive, scratch = tmp_path / "ARCH", tmp_path / "SCRATCH"
    con, _profile, _flats = _baza(tmp_path, db_archive=archive)
    work = tmp_path / "_WBPP"
    _wyniki(_wydanie_obiektu(work, "A", ts="2026-10-09T10:00:00+00:00", con=con), {"masterFlat_A.xisf": b"A"})
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls()})
    dlg = _dlg(con, scratch, work_root=str(work))
    dlg._on_apply()
    assert _stan(dlg, 0) == "wciągnięte 1" and not dlg.archive_warn.isHidden()
    assert dlg.rel_done_note.isHidden() and dlg.btn_open_release.isHidden()
    con.close()


def test_ar105_wciagniete_do_innego_archiwum_nie_sa_wciagniete_w_archiwum_okna(qapp, tmp_path, ustawienia,
                                                                              monkeypatch):
    """AR-105 (wizytacja W2 fali 9): wyjście wciągnięte do archiwum w scratchu. Okno z innym archiwum
    widzi wiersz bez „wciągnięte” (zeznanie scratchu o tym archiwum nie świadczy), zaznacza go sam,
    podgląd mówi „do wciągnięcia 1”, „Wciągnij” aktywny, a zdanie o kasowaniu nie pada. Zmiana
    archiwum w oknie liczy listę od nowa - wobec scratchu wiersz znów jest wciągnięty."""
    con, _profile, _flats = _baza(tmp_path)
    work = tmp_path / "_WBPP"
    out = _wyniki(_wydanie_obiektu(work, "A", ts="2026-10-09T10:00:00+00:00", con=con), {"masterFlat_A.xisf": b"A"})
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls()})
    scratch, archive = tmp_path / "SCRATCH", tmp_path / "ARCH"
    dlg = _dlg(con, scratch, work_root=str(work))
    dlg._on_apply()
    assert _stan(dlg, 0) == "wciągnięte 1" and not dlg.rel_done_note.isHidden()
    dlg.reject()
    dlg2 = _dlg(con, archive, work_root=str(work))
    assert _stan(dlg2, 0) == "do wciągnięcia 1" and dlg2.edit_output.text() == str(out)
    assert dlg2.rel_done_note.isHidden() and dlg2.btn_apply.text() == "Wciągnij 1 plik"
    assert dlg2.btn_apply.isEnabled()
    dlg2._fresh.clear()                                                 # sam stan listy, bez podglądu
    dlg2._render_release_states()
    assert _stan(dlg2, 0) == "do sprawdzenia 1"
    dlg2._set_archive(str(scratch))
    assert _stan(dlg2, 0) == "wciągnięte 1" and not dlg2.rel_done_note.isHidden()
    con.close()


def test_ar100_sam_master_flat_korzen_z_calibration(qapp, tmp_path, ustawienia, monkeypatch):
    """AR-100 bez stosu: jedyna kopia do przyjęcia leży pod `CALIBRATION` → korzeń = jej katalog
    (jak przy wciągniętym masterze), „Wciągnij” zgaszony, bo nic nowego do skopiowania."""
    con, _profile, _flats = _baza(tmp_path)
    archive = tmp_path / "ARCH"
    out = _wyjscie(tmp_path, {"masterFlat_A.xisf": b"A"})
    _cel(archive).parent.mkdir(parents=True)
    _cel(archive).write_bytes(b"A")
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls()})
    dlg = _dlg(con, archive)
    dlg._set_output(str(out))
    assert _kol(dlg, 0, COL_STATUS) == "już w archiwum" and not dlg.btn_apply.isEnabled()
    assert not dlg.btn_accept.isHidden()
    with pytest.raises(AssertionError):
        dlg._set_archive(str(tmp_path / "INNE"))
    dlg.btn_accept.click()
    assert dlg.harvested_root == str(_cel(archive).parent) and dlg.harvested_stacks == []
    assert dlg.summary == f"W archiwum leży 1 kopia nieznana bazie → {_cel(archive).parent}"
    con.close()


def test_wynik_listy_nie_przestawia_pola_ani_nie_sonduje(qapp, tmp_path, ustawienia, monkeypatch):
    """Inwentarz akcji kontra lista w tle: lista policzona po wyborze człowieka nie przestawia pola
    i nie sonduje drugi raz (zaznaczenie idzie za polem); lista starszej generacji odpada; lista,
    która przychodzi w biegu „Wciągnij”, nie rusza pola ani planu, a lista wydań jest w biegu
    wygaszona."""
    con, _profile, _flats = _baza(tmp_path)
    work = tmp_path / "_WBPP"
    a = _wydanie_obiektu(work, "A", ts="2026-10-09T10:00:00+00:00", con=con)
    b = _wydanie_obiektu(work, "B", ts="2026-10-08T10:00:00+00:00", con=con)
    _wyniki(a, {"masterFlat_A.xisf": b"A"})
    out_b = _wyniki(b, {"masterFlat_B.xisf": b"B", "masterFlat_C.xisf": b"C"})
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls(), "masterFlat_B.xisf": _flat_ha(),
                           "masterFlat_C.xisf": _flat_cls()})
    dlg = _dlg(con, tmp_path / "ARCH", work_root=str(work))
    dlg.show()
    _klik_wiersza(dlg, 1)
    plan = dlg._plan
    rows = harvest.releases([str(work)])
    dlg._on_releases_done(dlg._rel_gen, rows)                            # przeliczenie po wyborze B
    assert dlg.edit_output.text() == str(out_b) and dlg._plan is plan
    assert [i.row() for i in dlg.rel_table.selectionModel().selectedRows()] == [1]
    dlg._on_releases_done(dlg._rel_gen - 1, [])                          # starsza generacja - odpada
    assert dlg.rel_table.rowCount() == 2 and dlg._rel_pending
    w_biegu = []

    def hook(n, _w):
        if n == 1:
            dlg._on_releases_done(dlg._rel_gen, rows)
            w_biegu.append((dlg.edit_output.text(), dlg.rel_table.isEnabled()))

    _spy_progress(monkeypatch, hook=hook)
    dlg._on_apply()
    assert w_biegu == [(str(out_b), False)]
    assert dlg.rel_table.isEnabled() and dlg.edit_output.text() == str(out_b)
    con.close()


def test_realny_qthread_lista_wydan_po_wyborze_czlowieka_nie_wybiera(qapp, tmp_path, ustawienia, monkeypatch):
    """PRAWDZIWY wątek listy: pierwsza lista, która przychodzi PO wskazaniu wyjścia przez człowieka,
    nie robi wyboru startowego (pole i podgląd zostają), tylko zaznacza wiersz pola."""
    con, _profile, _flats = _baza(tmp_path)
    work = tmp_path / "_WBPP"
    a = _wydanie_obiektu(work, "A", ts="2026-10-09T10:00:00+00:00", con=con)
    b = _wydanie_obiektu(work, "B", ts="2026-10-08T10:00:00+00:00", con=con)
    _wyniki(a, {"masterFlat_A.xisf": b"A"})
    out_b = _wyniki(b, {"masterFlat_B.xisf": b"B"})
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls(), "masterFlat_B.xisf": _flat_ha()})
    gate, entered = threading.Event(), threading.Event()
    prawdziwe = harvest.releases

    def wolne(roots, **kw):
        entered.set()
        gate.wait(10)
        return prawdziwe(roots, **kw)

    monkeypatch.setattr(harvest, "releases", wolne)
    dlg = _dlg(con, tmp_path / "ARCH", work_root=str(work), off_thread=True)
    assert entered.wait(10) and dlg.rel_notice.text() == "Liczę wydania na kartach…"
    dlg._set_output(str(out_b))
    assert _wait_until(lambda: dlg.btn_apply.isEnabled() and dlg._dry_thread is None)
    gate.set()
    assert _wait_until(lambda: dlg._rel_thread is None and dlg.rel_table.rowCount() == 2)
    assert dlg.edit_output.text() == str(out_b) and dlg.btn_apply.text() == "Wciągnij 1 plik"
    assert [i.row() for i in dlg.rel_table.selectionModel().selectedRows()] == [1]
    con.close()


def test_realny_qthread_lista_wybor_startowy_i_sonda(qapp, tmp_path, ustawienia, monkeypatch):
    """PRAWDZIWE wątki listy i sondy: lista przychodzi kolejką, wybór startowy rusza sondę w drugim
    wątku, oba wątki sprzątnięte; po „Wciągnij” lista liczy się ponownie w tle."""
    con, _profile, _flats = _baza(tmp_path)
    work = tmp_path / "_WBPP"
    out = _wyniki(_wydanie_obiektu(work, "A", ts="2026-10-09T10:00:00+00:00", con=con), {"masterFlat_A.xisf": b"A"})
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls()})
    dlg = _dlg(con, tmp_path / "ARCH", work_root=str(work), off_thread=True)
    assert dlg._rel_thread is not None                                   # lista NAPRAWDĘ w tle
    assert _wait_until(lambda: dlg.btn_apply.isEnabled() and dlg._dry_thread is None and dlg._rel_thread is None)
    assert dlg.edit_output.text() == str(out) and _stan(dlg, 0) == "do wciągnięcia 1"
    dlg._on_apply()
    assert _wait_until(lambda: dlg._apply_thread is None and dlg._rel_thread is None and _stan(dlg, 0) == "wciągnięte 1")
    assert not dlg.btn_open_release.isHidden()
    con.close()


def test_realny_qthread_zamkniecie_w_trakcie_listy_nie_czeka(qapp, tmp_path, ustawienia, monkeypatch):
    """Zamknięcie w trakcie listy na PRAWDZIWYM wątku wraca od razu - rdzeń listy nie ma punktu
    przerwania, więc okno na nią nie czeka w wątku głównym; wątek dobiega i sprząta się sam,
    a spóźniona lista nie dotyka zamkniętego okna."""
    con, _profile, _flats = _baza(tmp_path)
    work = tmp_path / "_WBPP"
    _wyniki(_wydanie_obiektu(work, "A", ts="2026-10-09T10:00:00+00:00", con=con), {"masterFlat_A.xisf": b"A"})
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls()})
    gate, entered = threading.Event(), threading.Event()
    prawdziwe = harvest.releases

    def wolne(roots, **kw):
        entered.set()
        gate.wait(10)
        return prawdziwe(roots, **kw)

    monkeypatch.setattr(harvest, "releases", wolne)
    dlg = _dlg(con, tmp_path / "ARCH", work_root=str(work), off_thread=True)
    dlg.show()
    assert entered.wait(10)
    t0 = time.monotonic()
    dlg.done(0)
    assert time.monotonic() - t0 < 1 and dlg.isHidden()
    gate.set()
    assert _wait_until(lambda: dlg._rel_thread is None)
    assert dlg.rel_table.rowCount() == 0 and dlg.edit_output.text() == ""
    con.close()


def test_en_lista_wydan_i_rodzaj(qapp, tmp_path, ustawienia, monkeypatch):
    """EN: nagłówki listy, stany wiersza, zdanie o rodowodzie stosów (AR-104) i słowo rodzaju stosu
    z katalogu."""
    i18n.set_lang("en")
    con, _profile, _flats = _baza(tmp_path)
    archive = tmp_path / "ARCH"
    work, _root, _out, _ids, zeznania = _wydanie_ic1795(tmp_path, con, archive)
    _wydanie_obiektu(work, "M31", ts="2026-10-10T10:00:00+00:00")
    _czytnik(monkeypatch, zeznania)
    dlg = _dlg(con, archive, work_root=str(work))
    assert [dlg.rel_table.horizontalHeaderItem(c).text() for c in range(4)] == \
        ["Object", "Card", "Release date", "Status"]
    assert [_stan(dlg, r) for r in range(2)] == ["waiting for WBPP", "to harvest 3"]
    assert _kol(dlg, _wiersze(dlg)[os.path.join("master", STOS)], COL_KIND) == "stack"
    dlg._on_apply()
    assert _stan(dlg, 1) == "harvested 3 · lineage to record 2"
    assert dlg.rel_done_note.text() == (
        "Stacks from this release await their exact lineage - \"Close and receive into the archive\" "
        "records it. The set of their inputs exists only in this folder, so keep it until then.")
    assert dlg.btn_open_release.text() == "Open"
    dlg.reject()
    assert dlg.summary.startswith("Harvested 3 files into the archive (stacks without exact lineage: 2 - only "
                                  "\"Close and receive into the archive\" records it, also after reopening this "
                                  "window; keep the release folder)")
    con.close()


# ---------------------------------------------------------------- wiersz listy ze świeżego planu

def test_wiersz_z_samym_przegladem_bez_zdania_o_kasowaniu(qapp, tmp_path, ustawienia, monkeypatch):
    """Wyjście, w którym jest tylko pozycja do przeglądu (bieg bez `would-place` nie zostawia zeznania):
    po podglądzie wiersz mówi „do przeglądu 1” ze świeżego planu, zamiast wisieć jako „do sprawdzenia”;
    zdanie o kasowaniu NIE pada - pada „najpierw rozstrzygnij” z „Otwórz” (pliki przeglądu leżą tylko
    w folderze wydania)."""
    con, _profile, _flats = _baza(tmp_path)
    work = tmp_path / "_WBPP"
    _wyniki(_wydanie_obiektu(work, "A", ts="2026-10-09T10:00:00+00:00", con=con), {"masterDark_A.xisf": b"D"})
    _czytnik(monkeypatch, {"masterDark_A.xisf": {"kind": "master_dark"}})
    dlg = _dlg(con, tmp_path / "ARCH", work_root=str(work))
    assert dlg.head_label.text() == "Do wciągnięcia 0 · już w archiwum 0 · do przeglądu 1"
    assert _stan(dlg, 0) == "do przeglądu 1"
    assert not dlg.rel_done_note.isHidden() and not dlg.btn_open_release.isHidden()
    assert dlg.rel_done_note.text() == "Najpierw rozstrzygnij pozycje do przeglądu - ich pliki leżą tylko w tym folderze."
    con.close()


def test_wbpp_dopisal_wynik_podglad_przelicza_wiersz_i_gasi_zdanie(qapp, tmp_path, ustawienia, monkeypatch):
    """Wydanie wciągnięte („wciągnięte 1”, zdanie o kasowaniu), potem WBPP dopisuje wynik do `out`:
    świeży podgląd tego wyjścia liczy wiersz od nowa - „do wciągnięcia 1 · wciągnięte 1” - i zdanie
    o kasowaniu znika. Podgląd INNEGO wyjścia wiersza nie rusza."""
    con, _profile, _flats = _baza(tmp_path)
    work = tmp_path / "_WBPP"
    a = _wydanie_obiektu(work, "A", ts="2026-10-09T10:00:00+00:00", con=con)
    out = _wyniki(a, {"masterFlat_A.xisf": b"A"})
    inne = _wyjscie(tmp_path, {"masterFlat_X.xisf": b"X"}, sub=("WBPP_inne",))
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls(), "masterFlat_B.xisf": _flat_ha(),
                           "masterFlat_X.xisf": _flat_ha()})
    dlg = _dlg(con, tmp_path / "ARCH", work_root=str(work))
    dlg._on_apply()
    assert _stan(dlg, 0) == "wciągnięte 1" and not dlg.rel_done_note.isHidden()
    _wyniki(a, {"masterFlat_B.xisf": b"B"})                               # nowy przebieg WBPP dopisał wynik
    dlg._set_output(str(inne))                                            # podgląd innego wyjścia
    assert _stan(dlg, 0) == "wciągnięte 1"
    dlg._set_output(str(out))
    assert _stan(dlg, 0) == "do wciągnięcia 1 · wciągnięte 1"
    assert dlg.rel_done_note.isHidden() and dlg.btn_open_release.isHidden()
    con.close()


def test_wydanie_nowsze_od_wynikow_czeka_na_wbpp_bez_wyboru_i_zdania(qapp, tmp_path, ustawienia, monkeypatch):
    """Obiekt wydany ponownie po wynikach WBPP: wiersz „czeka na WBPP · poprzednio wciągnięte 1”, wybór
    startowy go nie bierze (nic do sprawdzenia), a zaznaczony ręcznie - po podglądzie dalej bez zdania
    o kasowaniu: wyniki w `out` nie są wynikami ostatniego wydania."""
    con, _profile, _flats = _baza(tmp_path)
    archive = tmp_path / "ARCH"
    work = tmp_path / "_WBPP"
    a = _wydanie_obiektu(work, "A", ts="2026-10-10T11:30:00+00:00", con=con)   # po `_PO_WYDANIU`
    out = _wyniki(a, {"masterFlat_A.xisf": b"A"})
    src = out / "master" / "masterFlat_A.xisf"
    projection.write_harvest_manifest(str(out), {"ts": NOW, "archive_root": str(archive), "items": [
        {"src": str(src), "status": "placed", "src_mtime_ns": os.stat(src).st_mtime_ns}]}, now=NOW)
    _cel(archive).parent.mkdir(parents=True)
    _cel(archive).write_bytes(b"A")                                      # wciągnięty wcześniej, leży w archiwum
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls()})
    dlg = _dlg(con, archive, work_root=str(work))
    dlg.show()
    assert _stan(dlg, 0) == "czeka na WBPP · poprzednio wciągnięte 1"
    assert dlg.rel_table.selectionModel().selectedRows() == [] and dlg.edit_output.text() == ""
    _klik_wiersza(dlg, 0)
    assert dlg.head_label.text() == "Do wciągnięcia 0 · już w archiwum 1 · do przeglądu 0"
    assert _stan(dlg, 0) == "czeka na WBPP · poprzednio wciągnięte 1"
    assert dlg.rel_done_note.isHidden() and dlg.btn_open_release.isHidden()
    con.close()


# ---------------------------------------------------------------- wyścigi z tłem i sprzątanie

def _wolna_lista(monkeypatch):
    """`harvest.releases`, który stoi na bramce, aż test ją otworzy (moment dojścia listy w ręku testu)."""
    gate, entered = threading.Event(), threading.Event()
    prawdziwe = harvest.releases

    def wolne(roots, **kw):
        entered.set()
        gate.wait(10)
        return prawdziwe(roots, **kw)

    monkeypatch.setattr(harvest, "releases", wolne)
    return gate, entered


def test_zatrzymaj_pola_czeka_na_watek_listy_i_jest_idempotentne(qapp, tmp_path, ustawienia, monkeypatch):
    """Okno zamknięte w trakcie listy zostaje ukrytym dzieckiem gospodarza z żywym wątkiem; gospodarz
    przed zniknięciem woła `zatrzymaj_pola` - ta czeka do końca wątku (bez limitu), zbiera go i wraca;
    drugie wołanie nic nie robi, a spóźniony `finished` z kolejki nie wywraca sprzątania."""
    con, _profile, _flats = _baza(tmp_path)
    work = tmp_path / "_WBPP"
    _wyniki(_wydanie_obiektu(work, "A", ts="2026-10-09T10:00:00+00:00", con=con), {"masterFlat_A.xisf": b"A"})
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls()})
    gate, entered = _wolna_lista(monkeypatch)
    dlg = _dlg(con, tmp_path / "ARCH", work_root=str(work), off_thread=True)
    dlg.show()
    assert entered.wait(10)
    dlg.done(0)
    assert dlg.isHidden() and dlg._rel_thread is not None                # zamknięcie nie czekało
    bledy = []
    monkeypatch.setattr(sys, "excepthook", lambda *a: bledy.append(a))
    otworz = threading.Timer(0.3, gate.set)
    otworz.start()
    t0 = time.monotonic()
    dlg.zatrzymaj_pola()
    assert time.monotonic() - t0 >= 0.2 and dlg._rel_thread is None and dlg._rel_worker is None
    t1 = time.monotonic()
    dlg.zatrzymaj_pola()
    assert time.monotonic() - t1 < 0.1
    QTest.qWait(50)
    assert bledy == [] and dlg.rel_table.rowCount() == 0
    otworz.join()
    con.close()


def test_zmien_archiwum_gdy_podglad_w_petli_okna_wyboru_dal_kopie_do_przyjecia(qapp, tmp_path, ustawienia,
                                                                               monkeypatch):
    """„Zmień…” klikane, gdy podgląd jeszcze biegnie; okno wyboru kręci własną pętlę, w niej dochodzi
    podgląd z kopią do przyjęcia (AR-100) - po powrocie archiwum zostaje, pada zdanie o blokadzie,
    zamiast asercji w slocie."""
    con, _profile, _flats = _baza(tmp_path)
    archive = tmp_path / "ARCH"
    out = _wyjscie(tmp_path, {"masterFlat_A.xisf": b"A"})
    _cel(archive).parent.mkdir(parents=True)
    _cel(archive).write_bytes(b"A")                                      # kopia nieznana bazie
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls()})
    ustawienia.setValue("harvest/last_output", str(out))
    dlg = _dlg(con, archive, off_thread=True)
    assert dlg._dry_thread is not None and dlg.btn_archive.isEnabled() and dlg.btn_accept.isHidden()

    def wybierz(parent, title, start=""):
        assert _wait_until(lambda: dlg._dry_thread is None)            # podgląd dobiega w pętli okna wyboru
        return str(tmp_path / "INNE")

    monkeypatch.setattr(hd_mod.QFileDialog, "getExistingDirectory", staticmethod(wybierz))
    dlg.btn_archive.click()
    assert dlg._archive_root == str(archive)
    assert dlg.notice.text().startswith("Archiwum zablokowane: w tym oknie są już kopie do przyjęcia")
    assert not dlg.btn_archive.isEnabled() and not dlg.btn_accept.isHidden()
    con.close()


def test_pierwsza_lista_nie_nadpisuje_pola_w_ktorym_czlowiek_pisze(qapp, tmp_path, ustawienia, monkeypatch):
    """Człowiek pisze w polu, zanim przyszła pierwsza lista: wybór startowy nie podmienia mu tekstu
    i nie sonduje - lista tylko się wypełnia."""
    con, _profile, _flats = _baza(tmp_path)
    work = tmp_path / "_WBPP"
    _wyniki(_wydanie_obiektu(work, "A", ts="2026-10-09T10:00:00+00:00", con=con), {"masterFlat_A.xisf": b"A"})
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls()})
    gate, entered = _wolna_lista(monkeypatch)
    dlg = _dlg(con, tmp_path / "ARCH", work_root=str(work), off_thread=True)
    dlg.show()
    dlg.activateWindow()
    dlg.edit_output.setFocus()
    qapp.processEvents()
    assert entered.wait(10) and dlg.edit_output.hasFocus()
    QTest.keyClicks(dlg.edit_output, r"E:\pisze")
    assert dlg.edit_output.isModified()
    gate.set()
    assert _wait_until(lambda: dlg._rel_thread is None and dlg.rel_table.rowCount() == 1)
    assert dlg.edit_output.text() == r"E:\pisze" and dlg._requested is None and dlg.table.rowCount() == 0
    assert dlg.rel_table.selectionModel().selectedRows() == []
    con.close()


def test_miejsce_listy_zarezerwowane_pole_i_przyciski_nie_zjezdzaja(qapp, tmp_path, ustawienia, monkeypatch):
    """Z kartami miejsce listy stoi od startu (pusta tabela, „Liczę wydania…”, zarezerwowany wiersz
    zdania): lista i podgląd, które dochodzą z tła, nie przesuwają pola, „Wskaż…” ani „Zmień…”."""
    con, _profile, _flats = _baza(tmp_path)
    work = tmp_path / "_WBPP"
    _wyniki(_wydanie_obiektu(work, "A", ts="2026-10-09T10:00:00+00:00", con=con), {"masterFlat_A.xisf": b"A"})
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls()})
    gate, entered = _wolna_lista(monkeypatch)
    dlg = _dlg(con, tmp_path / "ARCH", work_root=str(work), off_thread=True)
    dlg.show()
    assert entered.wait(10)
    QTest.qWait(30)
    assert dlg.rel_notice.text() == "Liczę wydania na kartach…" and not dlg.rel_table.isHidden()
    przed = (dlg.btn_pick.y(), dlg.btn_archive.y(), dlg.edit_output.y())
    gate.set()
    assert _wait_until(lambda: dlg._rel_thread is None and dlg._dry_thread is None and dlg.btn_apply.isEnabled())
    QTest.qWait(30)
    assert dlg.rel_table.rowCount() == 1 and dlg.rel_notice.text() == ""
    assert (dlg.btn_pick.y(), dlg.btn_archive.y(), dlg.edit_output.y()) == przed
    con.close()
