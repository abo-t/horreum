"""Okno „Wciągnij z WBPP…” - testy STERUJĄCE realnym oknem Qt (offscreen) na PRAWDZIWYM planie
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
from PySide6.QtWidgets import QApplication, QDialog, QWidget
from shiboken6 import isValid

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
    assert t("harvest.btn_apply", n) == (f"Take in {n} file" if n == 1 else f"Take in {n} files")


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


def test_ar107_wroc_do_archiwum_bazy_jednym_klikiem_i_blokada_jak_zmien(qapp, tmp_path, ustawienia, monkeypatch):
    """AR-107: okno na archiwum innym niż archiwum bazy ma przy ostrzeżeniu „Wróć do archiwum bazy” -
    klik to zmiana archiwum jak „Zmień…”, z celem z bazy: ostrzeżenie i przycisk znikają, podgląd
    liczy się wobec archiwum bazy. Po kopii wciągniętej w tym oknie przycisk zostaje (archiwum dalej
    inne), ale wygaszony z podpowiedzią blokady - jak „Zmień…”."""
    db_arch, scratch = tmp_path / "ARCH_DB", tmp_path / "SCRATCH"
    con, _profile, _flats = _baza(tmp_path, db_archive=db_arch)
    out = _wyjscie(tmp_path, {"masterFlat_A.xisf": b"A"})
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls()})
    dlg = _dlg(con, scratch)
    dlg._set_output(str(out))
    assert not dlg.archive_warn.isHidden() and not dlg.btn_archive_back.isHidden()
    assert dlg.btn_archive_back.isEnabled() and dlg.btn_archive_back.text() == "Wróć do archiwum bazy"
    dlg.btn_archive_back.click()
    assert dlg._archive_root == str(db_arch)
    assert dlg.archive_warn.isHidden() and dlg.btn_archive_back.isHidden()
    assert dlg.table.item(0, COL_DIR).toolTip() == str(_cel(db_arch).parent)
    dlg2 = _dlg(con, scratch)
    dlg2._set_output(str(out))
    dlg2._on_apply()
    assert not dlg2.btn_archive_back.isHidden() and not dlg2.btn_archive_back.isEnabled()
    assert dlg2.btn_archive_back.toolTip().startswith("Archiwum zablokowane: w tym oknie wciągnięto już kopie")
    con.close()


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
    assert dlg.btn_archive.toolTip().startswith("Archiwum zablokowane: w tym oknie wciągnięto już kopie")
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
    from horreum.gui.wb_worker import szczegol_zdania
    zestaw = _cel(archive).parent.parent
    # Wyjątek spoza klas systemu i bazy to błąd programu (`powod_okna`, AR-264): zdanie w języku UI,
    # surowy `Typ: opis` z miejscem w kodzie - w szczególe notki i zdania paska.
    assert dlg.summary == (f"Wciągnięto 2 pliki do archiwum → {zestaw} · "
                           f"Żniwa przerwane błędem: błąd programu - szczegół w podpowiedzi")
    assert dlg.notice.text() == ("Błąd wciągania: błąd programu - szczegół w podpowiedzi "
                                 "(przetworzono 2 z 2 przed błędem)")
    szczegol = r"Szczegół techniczny: RuntimeError: po kopiach @ horreum/gui/harvest_dialog\.py:\d+"
    assert re.fullmatch(szczegol, dlg.notice.szczegol()), dlg.notice.szczegol()
    assert re.fullmatch(szczegol, szczegol_zdania(dlg.summary)), szczegol_zdania(dlg.summary)
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
    # Zdanie paska mówi i o zeznaniu (AR-218) - po zamknięciu okna notki już nie ma.
    assert dlg.summary == (f"Wciągnięto 1 plik do archiwum → {_cel(archive).parent} · "
                           "Kopie leżą w archiwum, ale zeznania żniw nie zapisano: OSError: dysk pełny")
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
    assert dlg.progress_note.full_text() == "Zamykam po bieżącym pliku…"
    # Zamknięte po sprzątnięciu wątku - i zwolnione (`deleteLater`), bo żaden wątek go już nie trzyma.
    assert _wait_until(lambda: not isValid(dlg))
    assert dlg._closing and dlg._apply_thread is None and dlg._apply_worker is None
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
    # Sprzątnięcie wątku sondy zwalnia zamknięte okno; wynik porzucony - planu nie przyjęto.
    assert _wait_until(lambda: not isValid(dlg))
    assert dlg._dry_thread is None and dlg._plan is None and dlg._probed is None
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
    assert dlg.windowTitle() == "Take in WBPP results"
    assert dlg.notice.text() == "Choose the WBPP output folder - the preview computes itself."
    dlg._set_output(str(out))
    assert dlg.head_label.text() == "To take in 2 · already in the archive 0 · to review 2"
    assert dlg.btn_apply.text() == "Take in 2 files"
    rows = _wiersze(dlg)
    assert {_kol(dlg, r, COL_STATUS) for r in rows.values()} == {"to take in", "to review"}
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
    assert dlg.head_label.text().startswith("Taken in 2 · skipped 0 (already in the archive)")
    assert dlg.btn_apply.text() == "Taken in"
    assert dlg.btn_accept.text() == "Close and receive into the archive"
    assert dlg.summary.startswith("Took 2 files into the archive → ")
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
    manifest = {"layout": projection.OBJECT_LAYOUT, "object_id": 1, "object_canon": obiekt, "root": str(root),
                "ts": ts, "zestawy": zestawy or {}}
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
                                     lineage=(("s", (1, 2), "K/STACKS/s.xisf", "X"),))
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


def test_karta_bez_folderu_mowi_o_sobie_a_nie_o_braku_wydan(qapp, tmp_path, ustawienia, wybor_katalogu):
    """AR-147: folder roboczy, którego nie ma na dysku (dysk niepodłączony), daje zdanie o brakującej
    karcie w roli ostrzeżenia - nie „na kartach nie ma jeszcze wydań”; obok listy z innej karty to samo
    zdanie stoi nad jej wydaniami, a dwie brakujące karty dostają formę mnogą."""
    con, _profile, _flats = _baza(tmp_path)
    brak = tmp_path / "F" / "ASTRO_" / "_WBPP"
    dlg = _dlg(con, tmp_path / "ARCH", work_root=str(brak))
    dlg.show()
    QTest.qWait(30)
    assert dlg.rel_notice.text() == (f"Folder karty nie istnieje: {brak} - podłącz dysk albo ustaw folder "
                                     "roboczy: Plik → Folder roboczy WBPP…")
    assert dlg.rel_notice.property("role") == "warn" and dlg.rel_table.rowCount() == 0
    work = tmp_path / "_WBPP"
    _wydanie_obiektu(work, "IC1795", ts="2026-10-09T10:00:00+00:00", con=con)
    dlg2 = _dlg(con, tmp_path / "ARCH", work_root=str(brak), release_roots=[str(work)])
    dlg2.show()
    QTest.qWait(30)
    assert dlg2.rel_table.rowCount() == 1 and dlg2.rel_notice.text().startswith("Folder karty nie istnieje: ")
    drugi = tmp_path / "G" / "_WBPP"
    dlg3 = _dlg(con, tmp_path / "ARCH", work_root=str(brak), release_roots=[str(drugi)])
    dlg3.show()
    QTest.qWait(30)
    assert dlg3.rel_notice.text().startswith(f"2 foldery kart nie istnieją: {brak}, {drugi} - ")
    dlg3._on_releases_failed(dlg3._rel_gen, "OSError: x")    # lista, która padła, nie niesie braków dalej
    assert dlg3._rel_missing == () and dlg3.rel_notice.property("role") == "error"
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
    # kanon obiektu wydania jedzie ze zbiorem (AR-103: gospodarz porówna go z obiektem stosu)
    assert sorted(dlg.harvested_stacks) == [("stos-crop", tuple(ids[:2]), "IC1795"),
                                            ("stos-ha", tuple(ids[:2]), "IC1795")]
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
    NIE zablokowane (kopie zastane, nie wciągnięte w tym oknie - AR-107), korzeń = korzeń archiwum
    (jest stos), a stos położony w innym oknie dostaje rodowód dokładny (zbiór wejść z planu);
    zwykłe „Zamknij” mówi, ile kopii czeka i którędy baza do nich dojdzie, i stosów nie oddaje."""
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
    assert dlg.btn_archive.isEnabled() and dlg.btn_archive.toolTip() == ""
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
    assert dlg.harvested_stacks == [("stos-ha", tuple(ids[:2]), "IC1795")]
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
    widoczny, archiwum otwarte (stosy z listy nie powstały w tym oknie - AR-107), a przyjęcie oddaje
    korzeń archiwum (łańcuch) i zbiór dokładny obu stosów. Po zapisie rodowodu trzecie okno: „wciągnięte 3”, zdanie o kasowaniu i „Otwórz” (otwiera,
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
    assert not dlg2.btn_accept.isHidden() and dlg2.btn_accept.isEnabled() and dlg2.btn_archive.isEnabled()
    # waga za jedyną robotą (wizytator Z11): przyjęcie grube, „Wciągnij 0” bez wagi; Enter nie przyjmuje
    assert dlg2.btn_accept.font().bold() and not dlg2.btn_accept.isDefault() and not dlg2.btn_accept.autoDefault()
    assert not dlg2.btn_apply.font().bold() and not dlg2.btn_apply.isDefault()
    assert dlg2.summary == f"Stosy do rodowodu dokładnego po Dostawie: 2 → {seat}"
    dlg2.btn_accept.click()
    assert dlg2.result() == QDialog.Accepted and dlg2.harvested_root == str(archive)
    # kanon wydania ze zbiorem także dla stosów z zeznania (`_pending_stack`)
    assert sorted(dlg2.harvested_stacks) == [("stos-crop", tuple(ids[:2]), "IC1795"),
                                             ("stos-ha", tuple(ids[:2]), "IC1795")]

    for sha, wejscia, _kanon in dlg2.harvested_stacks:                       # gospodarz po łańcuchu (`app._zdanie_rodowodu`)
        assert stacks.record_harvest_inputs(con, master_sha1_data=sha, input_frame_ids=wejscia,
                                            now=NOW)["reason"] is None
    dlg3 = _dlg(con, archive, work_root=str(work))
    assert _stan(dlg3, 0) == "wciągnięte 3"
    assert dlg3.btn_accept.isHidden() and dlg3.btn_archive.isEnabled()
    assert dlg3.rel_done_note.text() == ("Folder wydania możesz skasować - Horreum go już nie potrzebuje; "
                                         "własne pliki obróbki przenieś przed skasowaniem.")
    # „Wciągnij 0 plików” wygaszony - bez wagi i bez Enter (AR-262): okno nie ma roboty
    assert dlg3.rel_done_note.property("role") == "secondary" and not dlg3.btn_apply.isDefault()
    assert not dlg3.btn_apply.isEnabled() and not dlg3.btn_apply.font().bold()
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
    assert _stan(dlg, 0) == "taken in 3 · lineage to record 2"
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
    (jak przy wciągniętym masterze), „Wciągnij” zgaszony, bo nic nowego do skopiowania. Zajrzenie do
    innego archiwum i powrót (AR-107) nie gubi tej kopii: fakt liczy się od nowa przy powrocie."""
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
    dlg._set_archive(str(tmp_path / "INNE"))
    assert dlg.btn_accept.isHidden() and dlg.summary is None and dlg.btn_apply.isEnabled()
    dlg._set_archive(str(archive))
    assert not dlg.btn_accept.isHidden() and not dlg.btn_apply.isEnabled()
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
    QTest.qWait(50)
    assert isValid(dlg) and dlg._rel_thread is not None                 # wątek w biegu trzyma okno
    assert dlg.rel_table.rowCount() == 0 and dlg.edit_output.text() == ""
    gate.set()
    assert _wait_until(lambda: not isValid(dlg))                         # lista dobiegła - okno zwolnione
    assert dlg._rel_thread is None and dlg._releases == []              # spóźniona lista okna nie dotknęła
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
    assert [_stan(dlg, r) for r in range(2)] == ["waiting for WBPP", "to take in 3"]
    assert _kol(dlg, _wiersze(dlg)[os.path.join("master", STOS)], COL_KIND) == "stack"
    dlg._on_apply()
    assert _stan(dlg, 1) == "taken in 3 · lineage to record 2"
    assert dlg.rel_done_note.text() == (
        "Stacks from this release await their exact lineage - \"Close and receive into the archive\" "
        "records it. The set of their inputs exists only in this folder, so keep it until then.")
    assert dlg.btn_open_release.text() == "Open"
    dlg.reject()
    assert dlg.summary.startswith("Took 3 files into the archive (stacks without exact lineage: 2 - only "
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


def test_zmien_archiwum_gdy_podglad_w_petli_okna_wyboru_dal_kopie_zastane(qapp, tmp_path, ustawienia,
                                                                          monkeypatch):
    """„Zmień…” klikane, gdy podgląd jeszcze biegnie; okno wyboru kręci własną pętlę, w niej dochodzi
    podgląd z kopią zastaną w archiwum (AR-100). Taka kopia archiwum nie zamraża (AR-107): po powrocie
    archiwum się zmienia, fakt o starym archiwum znika (przyjęcie gaśnie), a nowy podgląd liczy się
    wobec nowego archiwum - bez asercji w slocie i bez zdania o blokadzie."""
    con, _profile, _flats = _baza(tmp_path)
    archive, inne = tmp_path / "ARCH", tmp_path / "INNE"
    out = _wyjscie(tmp_path, {"masterFlat_A.xisf": b"A"})
    _cel(archive).parent.mkdir(parents=True)
    _cel(archive).write_bytes(b"A")                                      # kopia nieznana bazie
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls()})
    ustawienia.setValue("harvest/last_output", str(out))
    dlg = _dlg(con, archive, off_thread=True)
    assert dlg._dry_thread is not None and dlg.btn_archive.isEnabled() and dlg.btn_accept.isHidden()

    def wybierz(parent, title, start=""):
        assert _wait_until(lambda: dlg._dry_thread is None)            # podgląd dobiega w pętli okna wyboru
        assert not dlg.btn_accept.isHidden() and dlg.btn_archive.isEnabled()
        return str(inne)

    monkeypatch.setattr(hd_mod.QFileDialog, "getExistingDirectory", staticmethod(wybierz))
    dlg.btn_archive.click()
    assert dlg._archive_root == str(inne) and dlg.btn_accept.isHidden() and dlg.summary is None
    assert _wait_until(lambda: dlg._dry_thread is None and dlg._plan is not None)
    assert dlg.btn_apply.text() == "Wciągnij 1 plik" and dlg.btn_accept.isHidden()
    assert dlg.btn_archive.isEnabled() and dlg.summary is None
    assert not dlg.notice.text().startswith("Archiwum zablokowane")
    con.close()


def test_ar107_zmien_archiwum_tam_i_z_powrotem_blokada_dopiero_od_kopii_tego_okna(qapp, tmp_path, ustawienia,
                                                                                 monkeypatch, wybor_katalogu):
    """AR-107 (wizytacja ogona fali 9, W2): okno na archiwum A → „Zmień…” na B, w którym leży kopia
    nieznana bazie (wciągnięta w innym oknie bez przyjęcia) → B podsuwa jej przyjęcie, ale archiwum
    zostaje otwarte, a powrót na A to jeden „Zmień…”: fakt o B znika (przycisk przyjęcia, zdanie
    paska), podgląd liczy się wobec A. Dopiero kopia wciągnięta W TYM oknie zamraża archiwum (AR-100:
    dwa archiwa w jednym korzeniu przyjęcia) - „Zmień…” wygaszone z podpowiedzią, obejście to EXPECT,
    a przyjęcie oddaje korzeń pod A, bez kopii z B.

    Falsyfikatory: blokada z `_receivable_dirs` → „Zmień…” wygaszone na B; `_set_archive` bez zerowania
    `_unknown` → po powrocie na A przyjęcie widoczne, a zdanie paska mówi o kopii w B."""
    con, _profile, _flats = _baza(tmp_path)
    a, b = tmp_path / "ARCH", tmp_path / "SCRATCH"
    out = _wyjscie(tmp_path, {"masterFlat_A.xisf": b"A"})
    _cel(b).parent.mkdir(parents=True)
    _cel(b).write_bytes(b"A")                                            # kopia w B nieznana bazie
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls()})
    dlg = _dlg(con, a)
    dlg._set_output(str(out))
    assert dlg.btn_apply.text() == "Wciągnij 1 plik" and dlg.btn_accept.isHidden()

    wybor_katalogu.odpowiedz = str(b)
    dlg.btn_archive.click()
    assert dlg._archive_root == str(b) and wybor_katalogu.wywolania[-1][1] == str(a)
    assert _kol(dlg, 0, COL_STATUS) == "już w archiwum" and not dlg.btn_accept.isHidden()
    assert dlg.btn_archive.isEnabled() and dlg.btn_archive.toolTip() == ""   # zajrzenie nie zamyka powrotu
    assert dlg.summary == f"W archiwum leży 1 kopia nieznana bazie → {_cel(b).parent}"

    wybor_katalogu.odpowiedz = str(a)
    dlg.btn_archive.click()
    assert dlg._archive_root == str(a)
    assert dlg.btn_accept.isHidden() and dlg.summary is None
    assert dlg.btn_apply.isEnabled() and dlg.btn_apply.text() == "Wciągnij 1 plik"

    dlg._on_apply()
    assert _cel(a).read_bytes() == b"A"
    assert not dlg.btn_archive.isEnabled()
    assert dlg.btn_archive.toolTip().startswith("Archiwum zablokowane: w tym oknie wciągnięto już kopie")
    with pytest.raises(AssertionError):
        dlg._set_archive(str(b))
    dlg.btn_accept.click()
    assert dlg.result() == QDialog.Accepted and dlg.harvested_root == str(_cel(a).parent)
    con.close()


def test_ar107_stosy_bez_rodowodu_z_listy_nie_blokuja_archiwum_i_wracaja_z_nim(qapp, tmp_path, ustawienia,
                                                                              monkeypatch):
    """AR-107 przy AR-104: okno nad stosami bez rodowodu dokładnego (zwykłe „Zamknij”, osobna Dostawa)
    odsłania przyjęcie od otwarcia, a archiwum zostaje otwarte. „Zmień…” na archiwum bez tych stosów:
    przyjęcie gaśnie, zdania paska nie ma - zbiory dokładne należą do archiwum, które okno opuściło.
    Powrót: lista liczy stosy od nowa, a przyjęcie oddaje korzeń archiwum i oba zbiory dokładne."""
    con, _profile, _flats = _baza(tmp_path)
    archive, scratch = tmp_path / "ARCH", tmp_path / "SCRATCH"
    work, _root, _out, ids, zeznania = _wydanie_ic1795(tmp_path, con, archive)
    _czytnik(monkeypatch, zeznania)
    _dlg(con, archive, work_root=str(work))._on_apply()
    _dostawa_po_zwyklym_zamknij(con, archive)
    dlg = _dlg(con, archive, work_root=str(work))
    assert _stan(dlg, 0) == "wciągnięte 3 · rodowód do zapisania 2"
    assert not dlg.btn_accept.isHidden() and dlg.btn_archive.isEnabled()
    dlg._set_archive(str(scratch))
    assert dlg.btn_accept.isHidden() and dlg.summary is None and dlg.btn_archive.isEnabled()
    dlg._set_archive(str(archive))
    assert _stan(dlg, 0) == "wciągnięte 3 · rodowód do zapisania 2" and not dlg.btn_accept.isHidden()
    dlg.btn_accept.click()
    assert dlg.result() == QDialog.Accepted and dlg.harvested_root == str(archive)
    assert sorted(dlg.harvested_stacks) == [("stos-crop", tuple(ids[:2]), "IC1795"),
                                            ("stos-ha", tuple(ids[:2]), "IC1795")]
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


@pytest.mark.parametrize("szersza, skala", [
    pytest.param(False, 1.0, id="sciezka_z_basetemp"),
    pytest.param(True, 1.0, id="sciezka_szersza_od_okna"),
    pytest.param(True, 1.6, id="sciezka_szersza_od_okna_font_x1_6", marks=pytest.mark.zmienia_motyw),
])
def test_miejsce_listy_zarezerwowane_pole_i_przyciski_nie_zjezdzaja(qapp, tmp_path, ustawienia, monkeypatch,
                                                                    szersza, skala):
    """Z kartami miejsce listy stoi od startu (pusta tabela, „Liczę wydania…”, zarezerwowany wiersz
    zdania): lista i podgląd, które dochodzą z tła, nie przesuwają NA EKRANIE pola, „Wskaż…”
    ani „Zmień…”.

    AR-140: zdanie podglądu niesie ścieżkę wydania, a zawijanie łamie wiersz tylko na spacjach -
    ścieżka dłuższa od okna poszerzała je samo (980 → 1126 px), wskazówka u góry traciła wiersz
    i pole podjeżdżało o 14 px (`(254, 281, 253)` zamiast `(268, 295, 267)`). Wariant
    `sciezka_z_basetemp` to dawny test bez zmian: długość ścieżki daje mu katalog tymczasowy pytesta,
    więc o wyniku decydowało środowisko. Warianty `sciezka_szersza_od_okna` dokładają katalog
    liczony z metryki fontu - ścieżka ~1,3 szerokości okna przy każdym foncie, także ×1,6
    (`QApplication.setFont` przed otwarciem okna); sufit długości trzyma się MAX_PATH.
    Falsyfikator: zdejmij `_szerokosc_od_okna` z `notice` → padają warianty `sciezka_szersza_od_okna`.

    AR-191 - zapas pod polem: przyrost zdania podglądu (+1-2 wiersze) bierze tabela pozycji, dopóki
    stoi nad swoim minimum; potem układ zabiera wysokość liście wydań NAD polem. Przy foncie ×1,6
    stałe 600 px okna było niższe od treści (694-760 px offscreen), tabela startowała na minimum albo
    28 px nad nim, a wynik zależał od basetemp: szerokość okna z etykiety archiwum (ścieżka
    `tmp_path`, ucinana na 64 znakach), łamanie ścieżki po `-` i po `C:`, sufit MAX_PATH.
    Warunek wstępny przed listą: okno otwiera się w wysokości treści, najwyżej `_SCREEN_SHARE`
    ekranu (`_fit_height`). Falsyfikator: zdejmij `_fit_height` z `showEvent` → warunek pada
    w każdym wariancie i przy każdym basetemp.

    AR-201 - pozycja na ekranie zamiast szerokości okna: natywnie okno po pierwszym podglądzie rośnie
    pod tabelę (980 → 1080 px przy foncie ×1, → 1655 px przy ×1,6) i ten wzrost jest zamierzony
    (`_grow_to_table`); offscreen nie rośnie nigdy (ekran 800 px, sufit 720 px), więc asercja szerokości
    była tu pusta, a natywnie czerwona. Pod kursorem liczy się, gdzie NA EKRANIE stoją „Wskaż…”,
    „Zmień…” i pole: okno rośnie w lewo (przyciski stoją przy prawej krawędzi), a zdania nad polem
    trzymają wysokość (`_zapadka_zdan_nad_polem`). Warunek wariantu mierzy ścieżkę metryką fontu
    zdania, nie minimum etykiety (to zależy od jej klasy). Falsyfikator natywny: okno rosnące w prawo
    → „Wskaż…” +100 px (×1) / +675 px (×1,6); bez zapadki przy ×1,6 pole -44 px."""
    import math

    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QFont, QFontMetrics
    if skala != 1.0:
        font = QFont(QApplication.font())
        font.setPointSizeF(font.pointSizeF() * skala)
        QApplication.setFont(font)
    con, _profile, _flats = _baza(tmp_path)
    glebia = 0
    if szersza:
        fm = QFontMetrics(QApplication.font())
        okno = max(980, _dlg(con, tmp_path / "ARCH").minimumSizeHint().width())   # podłoga okna bez kart
        wydanie = tmp_path / "_WBPP" / projection.OBJECT_NAMESPACE / "A"
        najglebszy = wydanie / projection.OUTPUT_DIR / "master" / "masterFlat_A.xisf"
        glebia = math.ceil((1.3 * okno - fm.horizontalAdvance(str(wydanie))) / fm.horizontalAdvance("x"))
        glebia = min(max(glebia, 1), 255, 259 - len(str(najglebszy)) - 1)
    work = (tmp_path / ("x" * glebia) if glebia else tmp_path) / "_WBPP"
    _wyniki(_wydanie_obiektu(work, "A", ts="2026-10-09T10:00:00+00:00", con=con), {"masterFlat_A.xisf": b"A"})
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls()})
    gate, entered = _wolna_lista(monkeypatch)
    dlg = _dlg(con, tmp_path / "ARCH", work_root=str(work), off_thread=True)
    dlg.show()
    assert entered.wait(10)
    QTest.qWait(30)
    assert dlg.rel_notice.text() == "Liczę wydania na kartach…" and not dlg.rel_table.isHidden()
    sufit = int(dlg.screen().availableGeometry().height() * hd_mod._SCREEN_SHARE)
    assert dlg.height() >= min(dlg.layout().totalHeightForWidth(dlg.width()), sufit), (
        f"okno {dlg.height()} px niższe od treści - tabela pozycji bez zapasu pod przyrost zdania")

    def na_ekranie():
        p = {w: w.mapToGlobal(QPoint(0, 0)) for w in (dlg.btn_pick, dlg.btn_archive, dlg.edit_output)}
        return ((p[dlg.btn_pick].x(), p[dlg.btn_pick].y()), (p[dlg.btn_archive].x(), p[dlg.btn_archive].y()),
                p[dlg.edit_output].y())
    szerokosc = dlg.width()
    przed = na_ekranie()
    gate.set()
    assert _wait_until(lambda: dlg._rel_thread is None and dlg._dry_thread is None and dlg.btn_apply.isEnabled())
    QTest.qWait(30)
    assert dlg.rel_table.rowCount() == 1 and dlg.rel_notice.text() == ""
    if szersza:     # warunek wariantu: ścieżka w zdaniu podglądu naprawdę szersza od okna sprzed listy
        assert (str(work) in dlg.notice.text()
                and dlg.notice.fontMetrics().horizontalAdvance(str(work)) > szerokosc), (
            f"głębokość {glebia} (sufit MAX_PATH) nie dała ścieżki szerszej od okna {szerokosc} px")
    assert na_ekranie() == przed
    con.close()


# Ścieżka bez spacji, ~300 znaków: dłuższa od okna przy każdym foncie, zawijanie jej nie złamie.
DLUGA_SCIEZKA = "R:\\ASTRO_\\" + "\\".join(["_WBPP_folder_roboczy_wydania"] * 11)


@pytest.mark.parametrize("etykieta", ["notice", "rel_notice", "archive_warn"])
def test_zdanie_ze_sciezka_nie_podnosi_podlogi_okna_i_oddaje_ja_cala(qapp, tmp_path, ustawienia, etykieta):
    """AR-140 na każdej z trzech etykiet zdania stanu, które niosą ścieżkę (podgląd, lista wydań,
    archiwum inne niż archiwum bazy): ścieżka dłuższa od okna nie podnosi podłogi jego szerokości -
    podłoga z długą ścieżką = podłoga z krótką. Ucięta ścieżka ma drogę do pełnej treści: etykieta
    zaznaczalna, pełny tekst pod kursorem. Okno bez kart i bez wątków; tekst przez setter okna.
    Podłogę mierzymy po `activate()` układu: `archive_warn` siedzi w podukładzie wiersza, którego
    zapamiętane minimum odświeża dopiero aktywacja (bez niej podłoga stała przy każdym tekście).

    Falsyfikator: zdejmij `_szerokosc_od_okna` z danej etykiety → podłoga rośnie o szerokość ścieżki
    (`notice`, `rel_notice`) albo etykieta nie jest zaznaczalna (`archive_warn`)."""
    con, _profile, _flats = _baza(tmp_path)
    dlg = _dlg(con, tmp_path / "ARCH")

    def podloga():
        dlg.layout().activate()
        return dlg.minimumSizeHint().width()

    def zdanie(sciezka):
        if etykieta == "notice":
            dlg._show_notice(i18n.t("harvest.manifest_note", path=sciezka))
        elif etykieta == "rel_notice":
            dlg._show_rel_notice(i18n.t("harvest.rel.failed", msg=sciezka), "error")
        else:
            dlg._db_archive = sciezka          # archiwum bazy inne niż archiwum okna
            dlg._show_archive()
        return getattr(dlg, etykieta)

    zdanie("R:\\ASTRO_\\A")
    krotka = podloga()
    label = zdanie(DLUGA_SCIEZKA)
    assert len(DLUGA_SCIEZKA) >= 300 and " " not in DLUGA_SCIEZKA and DLUGA_SCIEZKA in label.text()
    assert not label.isHidden() and label.fontMetrics().horizontalAdvance(DLUGA_SCIEZKA) > krotka
    assert podloga() == krotka
    assert label.textInteractionFlags() & Qt.TextSelectableByMouse
    assert label.toolTip() == label.text()
    con.close()


def test_rodowod_z_wydania_etykieta_w_panelu_i_czlon_raportu(qapp, tmp_path):
    """AR-102: wejście rangi `harvest` mówi w panelu rodowodu „z wydania” (nie surowy klucz, nie „plik
    zeznał”), a raport przebiegu liczy stosy z wydania osobnym członem obok „potwierdza sam plik”."""
    from horreum.gui.grid import _lineage_item_text
    from horreum.gui.pipeline import PipelineView
    wiersz = {"date_obs": "2025-01-03T20:00:00", "exptime": 600.0, "asserted_by": "harvest", "excluded": 0,
              "path": "R:/x.fits"}
    assert "[z wydania]" in _lineage_item_text(wiersz)
    path = str(tmp_path / "p.db")
    db.open_db(path).close()
    v = PipelineView(path, now_fn=lambda: NOW)
    try:
        linia = v._format_result("stack_lineage", stacks.StackLineageSummary(
            stacks=3, linked=3, inputs=12, by_assert={"history": 1, "harvest": 2}))
        assert "z tego 1 potwierdza sam plik" in linia and "z wydania 2" in linia
        bez = v._format_result("stack_lineage", stacks.StackLineageSummary(
            stacks=1, linked=1, inputs=4, by_assert={"window": 1}))
        assert "z wydania" not in bez
    finally:
        v.close()


# ---------------------------------------------------------------- ekran mówi prawdę (role, słowa, rozmiar)

# Najdłuższa nazwa mastera w kopii archiwum (sonda 2026-10-13 na kopii `pf4` v36: 97 znaków, stos
# `masterLight_…_CALDWELL-23_fastIntegration.xisf`) z przedrostkiem mastera flat - 96 znaków.
DLUGA_NAZWA = "masterFlat_BIN-1_6248x4176_EXPOSURE-120.00s_FILTER-NoFilter_RGB_CALDWELL-23_fastIntegration.xisf"


def test_kolumna_stan_w_kolorze_roli_z_motywu(qapp, tmp_path, ustawienia, monkeypatch):
    """Słowo stanu niesie kolor znaczenia z motywu (`projection_dialog._COLORS`): do przeglądu -
    ostrzeżenie, wciągnięty - ok; „do wciągnięcia” bez roli (stan zwykły). Mapa ról tylko na
    statusach rdzenia i tylko na rolach motywu.

    Falsyfikator: komórka bez `setForeground` - pędzel `NoBrush` także przy „do przeglądu”."""
    from horreum.gui.projection_dialog import _COLORS
    assert set(hd_mod._STATUS_ROLES) <= set(harvest.STATUSES)
    assert set(hd_mod._STATUS_ROLES.values()) <= set(_COLORS)
    con, _profile, _flats = _baza(tmp_path)
    archive = tmp_path / "ARCH"
    out = _wyjscie(tmp_path, {"masterFlat_A.xisf": b"A", "masterFlat_X.xisf": b"X"})
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls(),
                           "masterFlat_X.xisf": {**_flat_ha(), "filter_raw": "OIII"}})
    dlg = _dlg(con, archive)
    dlg._set_output(str(out))

    def stan(nazwa):
        return dlg.table.item(_wiersze(dlg)[nazwa], COL_STATUS)

    assert stan("masterFlat_X.xisf").text() == "do przeglądu"
    assert stan("masterFlat_X.xisf").foreground().color() == _COLORS["warn"]
    assert stan("masterFlat_A.xisf").foreground().style() == Qt.NoBrush       # do wciągnięcia
    dlg._on_apply()
    assert stan("masterFlat_A.xisf").text() == "wciągnięty"
    assert stan("masterFlat_A.xisf").foreground().color() == _COLORS["ok"]
    assert stan("masterFlat_X.xisf").foreground().color() == _COLORS["warn"]
    con.close()


def test_postep_zniw_jednym_licznikiem_a_dluga_nazwa_nie_rozpycha_okna(qapp, tmp_path, ustawienia,
                                                                      monkeypatch):
    """W biegu licznik mówi notatka („1/1 · plik kopii”), pasek jest bez napisu (dawniej „0%” obok
    „0/1”). Notatka z najdłuższą realną nazwą mastera nie podnosi podłogi szerokości okna w biegu -
    jest elidowana, pełna treść pod kursorem; podłoga z długą nazwą = podłoga z krótką.

    Falsyfikator: `QLabel` za treścią - podłoga z długą nazwą rośnie o szerokość nazwy."""
    con, _profile, _flats = _baza(tmp_path)
    archive = tmp_path / "ARCH"
    out = _wyjscie(tmp_path, {"masterFlat_A.xisf": b"A"})
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls()})
    dlg = _dlg(con, archive)
    w_biegu = []

    def hook(_n, _w):
        nota = dlg.progress_note
        stan = (dlg.busy.isVisible(), dlg.busy.isTextVisible(), nota.full_text(), nota.toolTip())
        krotka = dlg.minimumSizeHint().width()
        nota.set_full_text(f"1/1 · {DLUGA_NAZWA}")               # ta sama notatka, nazwa z archiwum
        w_biegu.append((stan, krotka, dlg.minimumSizeHint().width(), nota.toolTip()))

    _spy_progress(monkeypatch, hook=hook)
    dlg.show()
    dlg._set_output(str(out))
    dlg._on_apply()
    (stan, krotka, dluga, podpowiedz), = w_biegu
    plik = os.path.basename(str(_cel(archive)))
    assert stan == (True, False, f"1/1 · {plik}", f"1/1 · {plik}")
    assert len(DLUGA_NAZWA) == 96 and podpowiedz == f"1/1 · {DLUGA_NAZWA}"
    assert dluga == krotka
    con.close()


def test_lista_wydan_dluga_karta_elidowana_a_stan_caly(qapp, tmp_path, ustawienia, monkeypatch):
    """Karta to długa ścieżka (segmenty najdłuższego katalogu lokacji z kopii archiwum - katalog
    wyjścia WBPP, 99 znaków): kolumna „Karta” dostaje resztę po obiekcie, dacie i stanie i elizję
    środkiem, komórka „Stan” zostaje cała, wiersz bez przewijania w bok. Pełna ścieżka w treści
    komórki i pod kursorem.

    AR-224: kadr z TREŚCI, nie z długości katalogu tymczasowego - przy krótkim `--basetemp` karta
    mieściła się w oknie 980 px (natywnie `734 < 734` fałszywe) i test nic nie mierzył. Okno zwężone
    tak, że na kartę zostaje połowa jej treści (jak `test_lista_wydan_maly_font_stan_nie_wystaje_poza_kadr`),
    a gdy minimum okna na to nie pozwala - tyle, ile zostaje w kadrze okna na minimum, w granicach
    `minimumSectionSize + 1 .. treść karty - 1` (szerszy wiersz okna nie robi z testu fałszywej czerwieni).

    Falsyfikatory: karta za treścią (`ResizeToContents`) albo `_fit_rel_columns` z szerokością treści
    karty - suma kolumn większa od kadru, stan ucięty; `ElideNone` - karta bez elizji środkiem."""
    con, _profile, _flats = _baza(tmp_path)
    work = tmp_path.joinpath("MC_76ED_2023-08_Bulgaria", "Veil_2023-08-22_76ED_2600C_0300s_Bulgaria",
                             "WBPP2", "_WBPP")
    _wyniki(_wydanie_obiektu(work, "A", ts="2026-10-09T10:00:00+00:00", con=con), {"masterFlat_A.xisf": b"A"})
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls()})
    dlg = _dlg(con, tmp_path / "ARCH", work_root=str(work))
    dlg.show()
    _pompuj(50)
    t, rh = dlg.rel_table, dlg.rel_table.horizontalHeader()
    karta = t.item(0, hd_mod.REL_CARD)
    assert karta.text() == str(work) and karta.toolTip() == str(work)
    assert _stan(dlg, 0) == "do wciągnięcia 1"

    def tresc(c):
        return max(t.sizeHintForColumn(c), rh.sectionSizeHint(c))
    inne = tresc(hd_mod.REL_OBJECT) + tresc(hd_mod.REL_DATE) + max(tresc(REL_STATE), rh.defaultSectionSize())
    szerokosc = dlg.width()
    dlg.resize(1, dlg.height())                                  # okno na swoim minimum szerokości
    _pompuj(50)
    na_minimum = t.viewport().width() - inne                     # najwęższa karta, na którą okno pozwala
    dlg.resize(szerokosc, dlg.height())
    _pompuj(50)
    karta_w = min(max(tresc(hd_mod.REL_CARD) // 2, na_minimum, rh.minimumSectionSize() + 1),
                  tresc(hd_mod.REL_CARD) - 1)
    kadr = inne + karta_w
    dlg.resize(dlg.width() + kadr - t.viewport().width(), dlg.height())
    _pompuj(50)
    assert t.viewport().width() == kadr, "okno nie dało się zwęzić - test niczego by nie pokazał"
    assert t.textElideMode() == Qt.ElideMiddle
    assert t.columnWidth(hd_mod.REL_CARD) < t.sizeHintForColumn(hd_mod.REL_CARD)       # karta elidowana
    assert t.columnWidth(REL_STATE) >= t.sizeHintForColumn(REL_STATE)                   # stan cały
    assert sum(t.columnWidth(c) for c in range(t.columnCount())) <= t.viewport().width()
    assert not t.horizontalScrollBar().isVisible()
    con.close()


def test_rodzaj_mastera_z_naglowkiem_surowej_klatki_mowi_slowem(qapp, tmp_path, ustawienia, monkeypatch):
    """Plik `masterFlat…`, którego nagłówek mówi o surowym flacie, idzie do przeglądu, a kolumna
    „Rodzaj” mówi „surowy flat”, nie token `flat`. Mapa słów obejmuje każdy rodzaj, który umie nadać
    skan (`resolve.frames._KIND_MAP`) + `unknown`; EN z katalogu.

    Falsyfikator: rodzaj spoza mapy - komórka mówi `flat`."""
    from horreum.resolve import frames
    assert set(_HARVEST_KINDS) == set(frames._KIND_MAP.values()) | {"unknown"}
    con, _profile, _flats = _baza(tmp_path)
    out = _wyjscie(tmp_path, {"masterFlat_S.xisf": b"S"})
    _czytnik(monkeypatch, {"masterFlat_S.xisf": {**_flat_cls(), "kind": "flat",
                                                 "header": {"IMAGETYP": "FLAT"}}})
    dlg = _dlg(con, tmp_path / "ARCH")
    dlg._set_output(str(out))
    assert _kol(dlg, 0, COL_KIND) == "surowy flat"
    assert _kol(dlg, 0, COL_STATUS) == "do przeglądu"
    assert _kol(dlg, 0, COL_REASON) == "nagłówek pliku nie zgadza się z wejściami: IMAGETYP='FLAT' -> flat"
    i18n.set_lang("en")
    assert [hd_mod.kind_text(k) for k in ("light", "flat", "dark", "bias")] == \
        ["raw light", "raw flat", "raw dark", "raw bias"]
    con.close()


@pytest.mark.parametrize("data, pl, en", [
    (None, "brak DATE-OBS w nagłówku - nazwa stosu wymaga daty i godziny",
     "no DATE-OBS in the header - the stack name needs a date and time"),
    ("2025-12-16", "DATE-OBS bez godziny albo nieczytelne (2025-12-16) - nazwa stosu wymaga daty i godziny",
     "DATE-OBS without a time or unreadable (2025-12-16) - the stack name needs a date and time"),
])
def test_stos_bez_czytelnego_date_obs_powod_mowi_o_dacie_nazwy(qapp, tmp_path, ustawienia, monkeypatch,
                                                              data, pl, en):
    """Stos, któremu rdzeń odmawia nazwy (`header_mismatch` z `DATE-OBS` w `detail`), dostaje zdanie
    o dacie nazwy stosu, nie „nagłówek nie zgadza się z wejściami: DATE-OBS None”. `detail` z rdzenia
    pinowany - to jego postać czyta okno.

    Falsyfikator: zdanie tokenu z surowym `detail` - „…: DATE-OBS None”."""
    con, _profile, _flats = _baza(tmp_path)
    archive = tmp_path / "ARCH"
    work, _root, _out, _ids, zeznania = _wydanie_ic1795(tmp_path, con, archive, z_flatem=False)
    zeznania[STOS] = {**zeznania[STOS], "date_obs": data}
    _czytnik(monkeypatch, zeznania)
    dlg = _dlg(con, archive, work_root=str(work))
    it = next(i for i in dlg._plan.items if i.src.endswith(STOS))
    assert (it.status, it.reason, it.detail) == ("review", "header_mismatch", f"DATE-OBS {data!r}")
    assert _kol(dlg, _wiersze(dlg)[os.path.join("master", STOS)], COL_REASON) == pl
    i18n.set_lang("en")
    assert reason_text(it) == en
    con.close()


def test_zamkniete_okno_bez_watku_zwalnia_sie_samo(qapp, tmp_path, ustawienia, monkeypatch):
    """Zamknięte okno bez żywego wątku tła nie zostaje dzieckiem gospodarza (dawniej każde zamknięte
    okno żniw wisiało pod oknem głównym do końca sesji). Gospodarz czyta `summary` po `exec()` -
    zdanie jest tam przed usunięciem i zostaje czytelne po nim (atrybut Pythona).

    Falsyfikator: bez `deleteLater` - `findChildren(QDialog)` gospodarza zwraca zamknięte okno."""
    con, _profile, _flats = _baza(tmp_path)
    out = _wyjscie(tmp_path, {"masterFlat_A.xisf": b"A"})
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls()})
    gospodarz = QWidget()
    dlg = _dlg(con, tmp_path / "ARCH", parent=gospodarz)
    dlg._set_output(str(out))
    dlg._on_apply()
    dlg.reject()
    zdanie = dlg.summary
    assert zdanie.startswith("Wciągnięto 1 plik do archiwum")
    QTest.qWait(20)
    assert not isValid(dlg) and gospodarz.findChildren(QDialog) == []
    assert dlg.summary == zdanie
    con.close()


# ---------------------------------------------------------------- układ okna pod zdarzeniami z tła (AR-201)
# i brak folderu wyjścia klasą błędu systemu (AR-199)

def _pompuj(ms):
    """Pętla zdarzeń przez `ms` - `processEvents` + `sleep`, nie `qWait` (trzyma GIL wątkom tła)."""
    koniec = time.monotonic() + ms / 1000
    while time.monotonic() < koniec:
        QApplication.processEvents()
        time.sleep(0.005)


def _czekaj_az(warunek, ms=10_000):
    """Pętla zdarzeń do warunku (wynik wątku tła dolatuje sygnałem kolejkowanym)."""
    koniec = time.monotonic() + ms / 1000
    while time.monotonic() < koniec:
        QApplication.processEvents()
        if warunek():
            return True
        time.sleep(0.005)
    return warunek()


def _na_ekranie(*widzety):
    """Współrzędne widżetów NA EKRANIE - przycisk pod kursorem to pozycja globalna, nie lokalna okna."""
    from PySide6.QtCore import QPoint
    return tuple((p.x(), p.y()) for p in (w.mapToGlobal(QPoint(0, 0)) for w in widzety))


def test_naglowek_pozycji_zawija_sie_i_nie_podnosi_podlogi_szerokosci(qapp, tmp_path, ustawienia):
    """AR-201: zdanie liczb nad tabelą pozycji - najdłuższe, jakie okno składa (wynik biegu z kłopotami
    i przerwaniem) - nie podnosi podłogi szerokości okna: podłoga z nim = podłoga z pustym. Zdanie łamie
    się na „ · ” i zostaje całe (co najmniej dwa wiersze przy szerokości podłogi), nie ucięte. Natywnie
    przy foncie ×1,6 to zdanie trzymało minimum okna na 1287 px, offscreen poszerzało okno 980 → 1010.

    Falsyfikator: `head_label` bez `setWordWrap(True)` - podłoga rośnie do szerokości zdania."""
    from collections import Counter
    con, _profile, _flats = _baza(tmp_path)
    dlg = _dlg(con, tmp_path / "ARCH")

    def podloga():
        dlg.layout().activate()
        return dlg.minimumSizeHint().width()

    pusta = podloga()
    dlg._show_head_done(Counter(placed=12, exists=3, review=2, conflict=1, error=1, verify_bad=1, cancelled=5),
                        cancelled=True)
    tekst, fm = dlg.head_label.text(), dlg.head_label.fontMetrics()
    assert tekst.startswith("Wciągnięto 12 · ") and "konflikty 1" in tekst and tekst.endswith(": 5"), tekst
    assert fm.horizontalAdvance(tekst) > pusta, "zdanie węższe od podłogi - test niczego by nie pokazał"
    assert podloga() == pusta
    assert dlg.head_label.heightForWidth(pusta) >= 2 * fm.height()          # dwa wiersze, nie ucięte
    con.close()


@pytest.mark.parametrize("skala", [pytest.param(1.0, id="font_x1"),
                                   pytest.param(1.6, id="font_x1_6", marks=pytest.mark.zmienia_motyw)])
def test_okno_scisniete_do_minimum_pole_nie_zjezdza(qapp, tmp_path, ustawienia, monkeypatch, skala):
    """AR-201: okno ściśnięte ręką do minimum wysokości, zanim lista i podgląd doszły z tła. Zdanie
    podglądu ze ścieżką szerszą od okna dokłada wiersz POD polem; Qt liczył minimum okna bez zawijania,
    więc okno stało niżej od treści i ten wiersz układ zabierał liście wydań NAD polem - pole, „Wskaż…”
    i „Zmień…” podjeżdżały pod kursorem (natywnie -8 px przy ×1, -26 px przy ×1,6; offscreen -8/-13).
    Teraz podłoga wysokości okna idzie za treścią (`_podloga_wysokosci`, najwyżej `_SCREEN_SHARE`
    ekranu) i okno rośnie od dołu, a lista wydań ma wysokość stałą - układ nie może jej ścisnąć.

    Falsyfikatory: `_podloga_wysokosci` bez działania → pole zjeżdża; `setFixedHeight` listy z powrotem
    na `setMaximumHeight` → lista ściśnięta poniżej swojego maksimum."""
    import math

    from PySide6.QtGui import QFont, QFontMetrics
    if skala != 1.0:
        font = QFont(QApplication.font())
        font.setPointSizeF(font.pointSizeF() * skala)
        QApplication.setFont(font)
    con, _profile, _flats = _baza(tmp_path)
    fm = QFontMetrics(QApplication.font())
    wydanie = tmp_path / "_WBPP" / projection.OBJECT_NAMESPACE / "A"
    najglebszy = wydanie / projection.OUTPUT_DIR / "master" / "masterFlat_A.xisf"
    glebia = math.ceil((1.3 * 980 - fm.horizontalAdvance(str(wydanie))) / fm.horizontalAdvance("x"))
    glebia = min(max(glebia, 1), 255, 259 - len(str(najglebszy)) - 1)
    work = tmp_path / ("x" * glebia) / "_WBPP"
    _wyniki(_wydanie_obiektu(work, "A", ts="2026-10-09T10:00:00+00:00", con=con), {"masterFlat_A.xisf": b"A"})
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls()})
    gate, entered = _wolna_lista(monkeypatch)
    dlg = _dlg(con, tmp_path / "ARCH", work_root=str(work), off_thread=True)
    dlg.show()
    assert entered.wait(10)
    _pompuj(50)
    dlg.resize(dlg.width(), 0)                       # ręka: okno do minimum wysokości przed listą
    _pompuj(50)
    def miejsce():      # przyciski - cała pozycja na ekranie; pole - wysokość (rośnie w bok z oknem)
        pick, arch, pole = _na_ekranie(dlg.btn_pick, dlg.btn_archive, dlg.edit_output)
        return pick, arch, pole[1]
    przed = miejsce()
    zdanie_przed = dlg.notice.height()
    gate.set()
    assert _czekaj_az(lambda: dlg._rel_thread is None and dlg._dry_thread is None and dlg.btn_apply.isEnabled())
    _pompuj(50)
    assert str(work) in dlg.notice.text() and dlg.notice.height() > zdanie_przed, (
        "zdanie podglądu nie urosło pod polem - test niczego by nie pokazał")
    assert miejsce() == przed
    sufit = int(dlg._ekran().availableGeometry().height() * hd_mod._SCREEN_SHARE)
    assert dlg.minimumHeight() <= sufit
    assert dlg.height() >= min(dlg.layout().totalMinimumHeightForWidth(dlg.width()), sufit)
    lista = dlg.rel_table
    assert lista.minimumHeight() == lista.maximumHeight() > 0 and lista.height() == lista.maximumHeight()
    con.close()


def _atrapa_ekranu(ekran):
    """Ekran, którego obszar roboczy test zmienia w biegu (`ekran.geo`)."""
    return SimpleNamespace(availableGeometry=lambda: ekran.geo)


def _okno_z_ekranem(con, archive, lewo=0, **kw):
    """Okno z rodzicem; ekran rodzica (przed rozmieszczeniem) i WŁASNY ekran pokazanego okna podaje
    test (`_ekran`): ekran offscreen ma 800 px, a sufit `_grow_to_table` z niego (720 px) nie dałby
    oknu urosnąć w bok. Ekran startowy 1000 px od `lewo` - sufit 900 px trzyma okno na 980 px, dopóki
    test go nie poszerzy. Lewa krawędź > 0 pozwala postawić okno „za krawędzią” na dodatnich
    współrzędnych (offscreen przesuwa okno o ramkę przy ujemnym x)."""
    from PySide6.QtCore import QRect
    ekran = SimpleNamespace(geo=QRect(lewo, 0, 1000, 2100))
    rodzic = QWidget()
    rodzic.screen = lambda: _atrapa_ekranu(ekran)
    dlg = _dlg(con, archive, parent=rodzic, **kw)
    dlg.screen = lambda: _atrapa_ekranu(ekran)
    return dlg, rodzic, ekran


def _poszerz_z_tla(dlg, ekran, przyrost=400):
    """Wynik z tła, który poszerza okno o ~`przyrost` px: sufit `_grow_to_table` z ekranu = szerokość
    okna + przyrost, a powód pozycji (600 znaków) jest szerszy od każdego sufitu."""
    import dataclasses
    import math

    from PySide6.QtCore import QRect
    ekran.geo = QRect(ekran.geo.x(), 0, math.ceil((dlg.width() + przyrost) / hd_mod._SCREEN_SHARE), 2100)
    dlg._fill([dataclasses.replace(dlg._plan.items[0], status="conflict", detail="x" * 600)])


def _okno_z_podgladem(con, tmp_path, monkeypatch, x, lewo=0, **kw):
    """Pokazane okno z podglądem jednej pozycji, lewym górnym rogiem obszaru klienta w (`x`, 200);
    wyjście WBPP w atrybucie `dlg.test_out` (ponowny podgląd tego samego wyjścia)."""
    out = _wyjscie(tmp_path, {"masterFlat_A.xisf": b"A"})
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls()})
    dlg, rodzic, ekran = _okno_z_ekranem(con, tmp_path / "ARCH", lewo, **kw)
    dlg.test_out = str(out)
    dlg.show()
    _pompuj(50)
    dlg._set_output(str(out))
    dlg.setGeometry(x, 200, dlg.width(), dlg.height())
    _pompuj(50)
    return dlg, rodzic, ekran


def test_poszerzenie_okna_pod_tabele_nie_podnosi_pola(qapp, tmp_path, ustawienia, monkeypatch):
    """AR-201: wynik z tła poszerza okno pod tabelę (`_grow_to_table`), a szersze okno łamie wskazówkę
    u góry na mniej wierszy - wysokość, którą oddawała, podnosiła pole i „Wskaż…” pod kursorem
    (natywnie przy foncie ×1,6: 980 → 1655 px, wskazówka 78 → 52 px, pole -44 px). Zapadka
    (`_zapadka_zdan_nad_polem`) trzyma wysokość zdań nad polem przy wzroście z tła.

    Falsyfikator: `_grow_to_table` bez `_zapadka_zdan_nad_polem()` - pole i „Wskaż…” wyżej."""
    con, _profile, _flats = _baza(tmp_path)
    dlg, _rodzic, ekran = _okno_z_podgladem(con, tmp_path, monkeypatch, 600)
    szerokosc, wskazowka = dlg.width(), dlg.hint_label.height()
    # Warunek liczony PRZED wzrostem: po nim minimum z zapadki podnosi też `heightForWidth` etykiety.
    assert dlg.hint_label.heightForWidth(dlg.hint_label.width() + 900) < wskazowka, (
        "wskazówka w szerszym oknie nie traci wiersza - test niczego by nie pokazał")
    przed = _na_ekranie(dlg.btn_pick, dlg.edit_output)
    _poszerz_z_tla(dlg, ekran, przyrost=1000)        # wskazówka traci wiersz: natywnie od ~1800 px okna
    _pompuj(50)
    assert dlg.width() >= szerokosc + 900, "okno nie urosło - test niczego by nie pokazał"
    assert dlg.hint_label.height() == wskazowka
    assert [y for _x, y in _na_ekranie(dlg.btn_pick, dlg.edit_output)] == [y for _x, y in przed]
    con.close()


@pytest.mark.parametrize("przypadek", ["miejsce_na_lewo", "za_malo_miejsca", "za_lewa_krawedzia",
                                       "zmaksymalizowane"])
def test_poszerzenie_okna_pod_tabele_w_lewo_przyciski_stoja(qapp, tmp_path, ustawienia, monkeypatch, przypadek):
    """AR-201: okno pokazane rośnie pod tabelę W LEWO - „Wskaż…”, „Zmień…” i „Zamknij” stoją przy prawej
    krawędzi i nie uciekają spod kursora (natywnie okno rosnące w prawo przenosiło je o +100 px przy
    foncie ×1 i +675 px przy ×1,6). Brak miejsca: lewa krawędź ramki staje na krawędzi ekranu, resztę
    wzrostu bierze prawa strona. Okno już za lewą krawędzią nie skacze w prawo. Okno zmaksymalizowane
    się nie rusza.

    Falsyfikatory: wzrost przez `resize` (w prawo) - przyciski uciekają; clamp bez `min(g.x(), …)` -
    okno za lewą krawędzią skacze w prawo; bez strażnika `isMaximized` - zmaksymalizowane zmienia
    geometrię."""
    con, _profile, _flats = _baza(tmp_path)
    x0, lewo = {"miejsce_na_lewo": (600, 0), "za_malo_miejsca": (100, 0), "za_lewa_krawedzia": (450, 500),
                "zmaksymalizowane": (600, 0)}[przypadek]
    dlg, _rodzic, ekran = _okno_z_podgladem(con, tmp_path, monkeypatch, x0, lewo)
    if przypadek == "zmaksymalizowane":
        dlg.showMaximized()
        _pompuj(50)
        assert dlg.isMaximized()
    geometria, szerokosc = dlg.geometry(), dlg.width()
    przyciski = (dlg.btn_pick, dlg.btn_archive, dlg.btn_close)
    przed = _na_ekranie(*przyciski)
    _poszerz_z_tla(dlg, ekran)
    _pompuj(50)
    if przypadek == "zmaksymalizowane":
        assert dlg.geometry() == geometria and dlg.isMaximized()
        con.close()
        return
    assert dlg.width() >= szerokosc + 300, "okno nie urosło - test niczego by nie pokazał"
    if przypadek == "miejsce_na_lewo":
        assert _na_ekranie(*przyciski) == przed and dlg.geometry().x() < x0
    elif przypadek == "za_malo_miejsca":
        assert dlg.frameGeometry().x() == 0                      # lewa krawędź ekranu rodzica
        po = _na_ekranie(*przyciski)
        assert all(p[1] == q[1] and q[0] - p[0] == dlg.width() - szerokosc - (x0 - dlg.geometry().x())
                   for p, q in zip(przed, po)), (przed, po)
    else:
        assert dlg.geometry().x() == geometria.x()               # nie skacze w prawo, rośnie w prawo
    con.close()


def test_pokazane_okno_rosnie_do_krawedzi_wlasnego_ekranu_nie_ekranu_rodzica(qapp, tmp_path, ustawienia,
                                                                            monkeypatch):
    """AR-201: okno przeniesione ręką na inny monitor niż rodzic rośnie pod tabelę względem ekranu,
    na którym STOI (`_ekran` po rozmieszczeniu = `self.screen()`): lewa krawędź ramki zatrzymuje się na
    krawędzi jego ekranu, sufit szerokości też liczy się z niego. Ekran rodzica (szeroki, od 0) służy
    wyłącznie przed pierwszym rozmieszczeniem.

    Falsyfikator: `_ekran` zawsze z rodzica - okno rośnie pod sufit ekranu rodzica i staje na jego
    lewej krawędzi (x = 0), poza własnym ekranem."""
    from PySide6.QtCore import QRect
    con, _profile, _flats = _baza(tmp_path)
    dlg, _rodzic, ekran = _okno_z_podgladem(con, tmp_path, monkeypatch, 600)
    ekran.geo = QRect(0, 0, 3800, 2100)                          # ekran rodzica: szeroki, od 0
    wlasny = SimpleNamespace(geo=QRect(500, 0, 1000, 2100))       # ekran, na którym okno stoi
    dlg.screen = lambda: _atrapa_ekranu(wlasny)
    szerokosc = dlg.width()
    _poszerz_z_tla(dlg, wlasny)                                  # sufit własnego ekranu = szerokość + 400
    _pompuj(50)
    assert szerokosc + 300 <= dlg.width() <= szerokosc + 400, (szerokosc, dlg.width())
    assert dlg.frameGeometry().x() == 500                        # lewa krawędź WŁASNEGO ekranu
    con.close()


def test_podloga_przy_dolnej_krawedzi_ramka_zostaje_na_ekranie(qapp, tmp_path, ustawienia, monkeypatch):
    """AR-201: okno ściśnięte ręką i postawione kilka pikseli nad dolną krawędzią obszaru roboczego
    ekranu; zdanie z tła rośnie o kilka wierszy, a podłoga wysokości podnosi okno od dołu. Ramka zostaje
    w obszarze ekranu: okno podnosi się o tyle, ile by wystawało - dolny rząd przycisków nie schodzi pod
    ekran (pasek zadań).

    Falsyfikator: `_podloga_wysokosci` bez `_rama_w_obszarze_ekranu` - dolna krawędź ramki pod ekranem."""
    from PySide6.QtCore import QRect
    con, _profile, _flats = _baza(tmp_path)
    dlg, _rodzic, ekran = _okno_z_ekranem(con, tmp_path / "ARCH")
    dlg.show()
    _pompuj(50)
    dlg.resize(dlg.width(), 0)                                   # ręka: minimum wysokości
    dlg.move(100, 600)                                           # dodatnie y także po podniesieniu (offscreen)
    _pompuj(50)
    dol = dlg.frameGeometry().bottom() + 3                       # okno 3 px nad dolną krawędzią obszaru
    ekran.geo = QRect(0, dol + 1 - 2000, 1000, 2000)             # wysoki obszar: sufit podłogi go nie tnie
    wysokosc = dlg.height()
    dlg._show_notice("zdanie stanu, które łamie się na wiele wierszy " * 12, "error")
    _pompuj(50)
    assert dlg.height() > wysokosc, "podłoga nie podniosła okna - test niczego by nie pokazał"
    rama = dlg.frameGeometry()
    assert ekran.geo.top() <= rama.top() and rama.bottom() <= ekran.geo.bottom(), (rama, ekran.geo)
    con.close()


def _okno_z_zapadka(con, tmp_path, monkeypatch, zdanie):
    """Okno z kartą (folder bez wydań - zdanie listy ma zarezerwowany wiersz) i podglądem; zdanie
    listy `zdanie`, potem wzrost z tła - zapadka trzyma wysokość zdania. Zwraca (okno, rodzic, ekran,
    wysokość zdania w chwili zapadki)."""
    karta = tmp_path / "_WBPP"
    karta.mkdir()
    dlg, rodzic, ekran = _okno_z_podgladem(con, tmp_path, monkeypatch, 600, work_root=str(karta))
    dlg._show_rel_notice(zdanie, "error")
    _pompuj(50)
    wysokosc = dlg.rel_notice.height()
    _poszerz_z_tla(dlg, ekran)
    _pompuj(50)
    assert dlg.rel_notice.minimumHeight() == wysokosc, "zapadka nie złapała zdania - test niczego by nie pokazał"
    return dlg, rodzic, ekran, wysokosc


def test_zapadka_puszcza_gdy_zdanie_listy_znika(qapp, tmp_path, ustawienia, monkeypatch):
    """AR-201: zapadka wysokości zdań nad polem trzyma tylko do zmiany stanu. Ostrzeżenie listy (kilka
    wierszy) złapane przy wzroście okna z tła, potem zdanie znika: etykieta wraca do swojego minimum
    sprzed zapadki, a okno daje się znów zmniejszyć - puste zdanie nie trzyma wierszy ostrzeżenia.

    Falsyfikator: `event` bez `_zwolnij_zapadke(tylko_puste=True)` - minimum zdania i okna zostaje."""
    con, _profile, _flats = _baza(tmp_path)
    dlg, _rodzic, _ekran, wysokosc = _okno_z_zapadka(con, tmp_path, monkeypatch,
                                                     "ostrzeżenie listy wydań na kilka wierszy " * 12)
    podstawa = dlg._podstawy_zdan[dlg.rel_notice]
    assert wysokosc > 2 * podstawa, "zdanie bez kilku wierszy - test niczego by nie pokazał"
    minimum_okna = dlg.minimumHeight()
    dlg._show_rel_notice("")
    _pompuj(50)
    assert dlg.rel_notice.minimumHeight() == podstawa and dlg.rel_notice.height() < wysokosc
    assert dlg.minimumHeight() < minimum_okna
    dlg.resize(dlg.width(), 0)
    _pompuj(50)
    assert dlg.height() < minimum_okna
    con.close()


def test_nowy_podglad_puszcza_zapadke_a_kolejny_wzrost_lapie_biezace_zdanie(qapp, tmp_path, ustawienia,
                                                                           monkeypatch):
    """AR-201: zapadka nie przechodzi z jednego podglądu na następny. Ostrzeżenie listy (kilka wierszy)
    złapane przy wzroście z tła, potem krótkie zdanie - zapadka dalej trzyma (zdanie nie jest puste).
    Nowy podgląd (gest człowieka: to samo wyjście jeszcze raz) oddaje zapadkę, a kolejny wzrost z tła
    łapie wysokość BIEŻĄCEGO zdania, nie największą z życia okna.

    Falsyfikator: `_invalidate` bez `_zwolnij_zapadke()` - minimum zdania zostaje na wysokości ostrzeżenia."""
    con, _profile, _flats = _baza(tmp_path)
    dlg, _rodzic, ekran, wysokosc = _okno_z_zapadka(con, tmp_path, monkeypatch,
                                                    "ostrzeżenie listy wydań na kilka wierszy " * 12)
    dlg._show_rel_notice("krótkie zdanie", "error")
    _pompuj(50)
    assert dlg.rel_notice.minimumHeight() == wysokosc               # zdanie jest - zapadka trzyma
    dlg._set_output(dlg.test_out)                                   # nowy podgląd
    _pompuj(50)
    jeden_wiersz = dlg.rel_notice.height()
    assert jeden_wiersz < wysokosc
    _poszerz_z_tla(dlg, ekran)
    _pompuj(50)
    assert dlg.rel_notice.minimumHeight() == jeden_wiersz
    con.close()


@pytest.mark.zmienia_motyw
def test_lista_wydan_maly_font_stan_nie_wystaje_poza_kadr(qapp, tmp_path, ustawienia, monkeypatch):
    """Rozciągana ostatnia sekcja listy wydań („Stan”) nie schodzi poniżej domyślnej szerokości sekcji
    (100 px). Przy foncie, w którym treść stanu jest od niej węższa, a karta za długa na kadr (natywnie
    już font ×1: stan 95 px), karta liczona z samej treści stanu zostawiała sumę kolumn szerszą od kadru
    (natywnie 1061 > 1056) i pasek przewijania w bok, który zjada wiersz listy. Font testu liczony
    z metryki: zdanie stanu ~85 px (offscreen metryka jest ~2× natywnej - tam font ~×0,45). Okno
    zwężone tak, że na kartę zostaje połowa jej treści - karta ucięta niezależnie od długości
    katalogu tymczasowego (z krótkim basetemp karta mieściła się cała i test nic nie mierzył).

    Falsyfikator: `_fit_rel_columns` bez podłogi `defaultSectionSize` dla stanu - suma > kadr."""
    from PySide6.QtGui import QFont, QFontMetrics
    skala = min(1.0, 85 / QFontMetrics(QApplication.font()).horizontalAdvance("do wciągnięcia 1"))
    font = QFont(QApplication.font())
    font.setPointSizeF(font.pointSizeF() * skala)
    QApplication.setFont(font)
    con, _profile, _flats = _baza(tmp_path)
    work = tmp_path.joinpath("MC_76ED_2023-08_Bulgaria", "Veil_2023-08-22_76ED_2600C_0300s_Bulgaria",
                             "WBPP2", "_WBPP")
    _wyniki(_wydanie_obiektu(work, "A", ts="2026-10-09T10:00:00+00:00", con=con), {"masterFlat_A.xisf": b"A"})
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls()})
    dlg = _dlg(con, tmp_path / "ARCH", work_root=str(work))
    dlg.show()
    _pompuj(50)
    t, rh = dlg.rel_table, dlg.rel_table.horizontalHeader()

    def tresc(c):
        return max(t.sizeHintForColumn(c), rh.sectionSizeHint(c))
    kadr = (tresc(hd_mod.REL_OBJECT) + tresc(hd_mod.REL_DATE) + rh.defaultSectionSize()
            + tresc(hd_mod.REL_CARD) // 2)
    dlg.resize(dlg.width() + kadr - t.viewport().width(), dlg.height())
    _pompuj(50)
    assert t.viewport().width() == kadr, "okno nie dało się zwęzić - test niczego by nie pokazał"
    assert t.sizeHintForColumn(REL_STATE) < rh.defaultSectionSize(), (
        "treść stanu nie jest węższa od domyślnej sekcji - test niczego by nie pokazał")
    assert t.columnWidth(hd_mod.REL_CARD) < t.sizeHintForColumn(hd_mod.REL_CARD)       # karta elidowana
    assert sum(t.columnWidth(c) for c in range(t.columnCount())) <= t.viewport().width()
    assert not t.horizontalScrollBar().isVisible()
    con.close()


def _stat_z_bledem(monkeypatch, sciezka, exc):
    """`os.stat`, który dla JEDNEJ ścieżki rzuca `exc`, a resztę oddaje prawdziwemu (pytest, `pathlib`)."""
    prawdziwy = os.stat

    def stat(p, *a, **kw):
        if isinstance(p, (str, os.PathLike)) and os.fspath(p) == sciezka:
            raise exc
        return prawdziwy(p, *a, **kw)
    monkeypatch.setattr(os, "stat", stat)


@pytest.mark.parametrize("lang", ["pl", "en"])
@pytest.mark.parametrize("przypadek", ["brak_folderu", "brak_rodzica", "plik", "udzial_53", "odmowa_5"])
def test_wyjscie_brak_zostaje_brakiem_a_blad_systemu_mowi_klasa(qapp, tmp_path, ustawienia, monkeypatch,
                                                                przypadek, lang):
    """AR-199: folder wyjścia sprawdza `os.stat` z klasą błędu systemu, nie `os.path.isdir`, który
    połykał każdy błąd jako „nie ma”. Brak (WinError 2 - folder, 3 - rodzic albo dysk) i plik zamiast
    folderu mówią „Katalog nie istnieje”, bez szczegółu systemu. Zerwany udział (53) i odmowa (5) mówią
    zdaniem klasy w języku UI („Nie można: udział sieciowy albo dysk nie odpowiada (WinError 53)”),
    surowy tekst systemu stoi w podpowiedzi; plan znika, „Wciągnij” zgaszony, pamięć pola nie bierze
    ścieżki, której nie dało się przeczytać.

    Falsyfikatory: `os.path.isdir` z powrotem - 53 i 5 mówią „Katalog nie istnieje”; każdy `OSError` jako
    brak - to samo; bez gałęzi braku - 2 i 3 mówią zdaniem klasy."""
    from horreum.gui.wb_worker import tekst_powodu, wiersz_systemu
    from horreum.item_reasons import powod_systemu
    i18n.set_lang(lang)
    con, _profile, _flats = _baza(tmp_path)
    sciezka = os.path.normpath(str({"brak_folderu": tmp_path / "nie_ma",
                                    "brak_rodzica": tmp_path / "nie_ma" / "out",
                                    "plik": tmp_path / "h.db",
                                    "udzial_53": tmp_path / "udzial" / "out",
                                    "odmowa_5": tmp_path / "odmowa" / "out"}[przypadek]))
    winerror = {"udzial_53": 53, "odmowa_5": 5}.get(przypadek)
    if winerror is not None:
        exc = OSError(None, "Komunikat systemu", sciezka, winerror)
        _stat_z_bledem(monkeypatch, sciezka, exc)
    dlg = _dlg(con, tmp_path / "ARCH")
    dlg._set_output(sciezka)
    zdanie = dlg.notice.text()
    if winerror is None:
        assert zdanie == i18n.t("harvest.missing_dir", path=sciezka), zdanie
        assert "WinError" not in dlg.notice.toolTip()
    else:
        powod = powod_systemu(exc)
        assert powod.code == {53: "os_share_lost", 5: "os_denied"}[winerror]
        assert zdanie == i18n.t("harvest.dry_failed", msg=tekst_powodu(powod)), zdanie
        assert wiersz_systemu(powod) and wiersz_systemu(powod) in dlg.notice.toolTip()
        if lang == "en":
            assert not _PL_LITERY.search(zdanie), zdanie
    assert dlg.notice.property("role") == "error"
    assert dlg._plan is None and not dlg.btn_apply.isEnabled() and dlg.table.rowCount() == 0
    assert str(ustawienia.value("harvest/last_output", "") or "") == ""
    con.close()


@pytest.mark.parametrize("przypadek", ["nazwa_123", "znak_nul"])
def test_wyjscie_blad_bez_klasy_idzie_porazka_tekstem_systemu(qapp, tmp_path, przypadek):
    """AR-199: błąd sprawdzenia folderu wyjścia bez klasy - nazwa niepoprawna (WinError 123, znak `?`)
    i znak NUL (`ValueError`) - nie udaje braku: sonda pada (`failed`). Kod systemu spoza klas mówi
    tekstem systemu („Typ: opis”), a `ValueError` - błędem programu (`powod_okna`, AR-264) z surowym
    tekstem CPythona w szczególe (klasy błędu wejścia jeszcze nie ma). `isdir` mówił o obu „nie ma”.

    Falsyfikator: `os.path.isdir` z powrotem albo każdy `OSError` jako brak - sonda oddaje `missing`."""
    sciezka = str(tmp_path / "a?b") if przypadek == "nazwa_123" else str(tmp_path) + "\\a\x00b"
    w = hd_mod.HarvestDryWorker(None, sciezka, str(tmp_path / "ARCH"), 7, con=None)
    wyniki, bledy = [], []
    w.done.connect(lambda gen, payload: wyniki.append(payload))
    w.failed.connect(lambda gen, msg: bledy.append((gen, msg)))
    w.run()
    assert wyniki == [] and len(bledy) == 1 and bledy[0][0] == 7, (wyniki, bledy)
    msg = bledy[0][1]
    if przypadek == "nazwa_123":
        assert msg.startswith("OSError: [WinError 123]") and getattr(msg, "code", None) is None, msg
    else:
        detail = dict(msg.params)["detail"]
        assert msg.code == "prog_error", msg
        assert re.fullmatch(r"ValueError: .*embedded null character.* @ horreum/gui/harvest_dialog\.py:\d+",
                            detail), detail


# ---------------------------------------------------------------- AR-225: rezerwa zdania wiersza wydania

_ZDANIA_WIERSZA = ("harvest.rel.done_note", "harvest.rel.review_note", "harvest.rel.lineage_note")


def _wysokosc_zdania(tekst, font, szerokosc):
    """Wysokość zdania przy szerokości - NIEZALEŻNA etykieta-miara (zawijanie, font etykiety okna)."""
    from PySide6.QtWidgets import QLabel
    miara = QLabel(tekst)
    miara.setWordWrap(True)
    miara.setFont(font)
    return miara.heightForWidth(szerokosc)


@pytest.mark.parametrize("jezyk_budowy", ["pl", "en"])
def test_zdanie_wiersza_wydania_rezerwuje_najwyzsze_z_trzech_zdan(qapp, tmp_path, ustawienia, jezyk_budowy):
    """AR-225: wysokość dla szerokości zdania pod listą wydań = najwyższe z trzech zdań wiersza
    („folder możesz skasować”, „najpierw rozstrzygnij”, „rodowód dokładny”) i zdania, które etykieta
    pokazuje, tekst u góry etykiety. Szerokości z treści (`horizontalAdvance` zdania + 8 px): przy
    szerokości zdania przeglądu ono mieści się w wierszu, a zdanie o kasowaniu nie; przy szerokości
    zdania o kasowaniu - zdanie o rodowodzie nie. Zmiana języka po budowie pinuje METODĘ liczenia
    (zdania w języku chwili liczenia), nie układ okna - produkt buduje okno żniw przy każdym otwarciu.

    Falsyfikatory: `heightForWidth` bez przeglądu trzech zdań (sama etykieta), miara bez zawijania,
    tekst wyśrodkowany w pionie, zdania miar z chwili budowy."""
    i18n.set_lang(jezyk_budowy)
    con, _profile, _flats = _baza(tmp_path)
    karta = tmp_path / "_WBPP"
    karta.mkdir()
    dlg = _dlg(con, tmp_path / "ARCH", work_root=str(karta))
    dlg.show()
    _pompuj(30)
    lab = dlg.rel_done_note
    assert lab.alignment() & Qt.AlignTop
    budowy = [i18n.t(k) for k in _ZDANIA_WIERSZA]

    def rezerwa(w, zdania):
        return max(_wysokosc_zdania(z, lab.font(), w) for z in zdania)
    for lang in ("pl", "en"):
        i18n.set_lang(lang)
        lab.setText(i18n.t("harvest.rel.done_note"))          # wiersz mówi w języku bieżącym (`_sync_release_note`)
        zdania = [i18n.t(k) for k in _ZDANIA_WIERSZA]
        przeglad, kasowanie = i18n.t("harvest.rel.review_note"), i18n.t("harvest.rel.done_note")
        for wzor, nizsze, wyzsze in ((przeglad, "harvest.rel.review_note", "harvest.rel.done_note"),
                                     (kasowanie, "harvest.rel.done_note", "harvest.rel.lineage_note")):
            w = lab.fontMetrics().horizontalAdvance(wzor) + 8
            wys = {k: _wysokosc_zdania(i18n.t(k), lab.font(), w) for k in (nizsze, wyzsze)}
            assert wys[nizsze] < wys[wyzsze], (lang, w, wys, "zdania równe - test niczego by nie pokazał")
            assert lab.heightForWidth(w) == rezerwa(w, zdania), (lang, w, lab.heightForWidth(w))
        if lang != jezyk_budowy:
            # szerokości, przy których rezerwa ze zdań języka budowy dałaby inną wysokość niż bieżąca
            rozne = [w for w in range(200, 1600, 10) if rezerwa(w, zdania) != rezerwa(w, budowy + zdania[:1])]
            assert rozne, "rezerwy obu języków równe przy każdej szerokości - test niczego by nie pokazał"
            assert [lab.heightForWidth(w) for w in rozne[:5]] == [rezerwa(w, zdania) for w in rozne[:5]]
    con.close()


@pytest.mark.zmienia_motyw
def test_rezerwa_zdania_wiersza_idzie_za_fontem_etykiety_przy_arkuszu_aplikacji(qapp, tmp_path, ustawienia):
    """AR-225: przy arkuszu stylu na aplikacji (motyw) `setFont` etykiety nie schodzi do jej dzieci -
    miary rezerwy dostają font etykiety przy każdym liczeniu. Etykieta z fontem ×1,5 względem
    aplikacji: rezerwa = najwyższe z trzech zdań liczone fontem ETYKIETY przy szerokości zdania
    o kasowaniu (warunek wstępny: fontem aplikacji wyszłoby inaczej).

    Falsyfikator: miary bez `setFont(self.font())` - rezerwa liczona fontem aplikacji."""
    from PySide6.QtGui import QFont
    QApplication.instance().setStyleSheet("QToolTip { }")
    con, _profile, _flats = _baza(tmp_path)
    karta = tmp_path / "_WBPP"
    karta.mkdir()
    dlg = _dlg(con, tmp_path / "ARCH", work_root=str(karta))
    dlg.show()
    _pompuj(30)
    lab = dlg.rel_done_note
    duzy = QFont(lab.font())
    duzy.setPointSizeF(duzy.pointSizeF() * 1.5)
    lab.setFont(duzy)
    zdania = [i18n.t(k) for k in _ZDANIA_WIERSZA]
    w = lab.fontMetrics().horizontalAdvance(i18n.t("harvest.rel.done_note")) + 8
    etykiety = max(_wysokosc_zdania(z, lab.font(), w) for z in zdania)
    aplikacji = max(_wysokosc_zdania(z, QApplication.font(), w) for z in zdania)
    assert etykiety != aplikacji, (etykiety, aplikacji, "test niczego by nie pokazał")
    assert lab.heightForWidth(w) == etykiety, (lab.heightForWidth(w), etykiety, aplikacji)
    con.close()


@pytest.mark.parametrize("stan, lang, skala", [
    pytest.param("przeglad", "pl", 1.0, id="przeglad_pl_x1"),
    pytest.param("przeglad", "en", 1.0, id="przeglad_en_x1"),
    pytest.param("przeglad", "pl", 1.6, id="przeglad_pl_x1_6", marks=pytest.mark.zmienia_motyw),
    pytest.param("przeglad", "en", 1.6, id="przeglad_en_x1_6", marks=pytest.mark.zmienia_motyw),
    pytest.param("rodowod", "pl", 1.0, id="rodowod_pl_x1"),
    pytest.param("rodowod", "en", 1.0, id="rodowod_en_x1"),
])
def test_lista_wydan_z_tla_zdanie_wiersza_nie_przesuwa_pola(qapp, tmp_path, ustawienia, monkeypatch, stan,
                                                            lang, skala):
    """AR-225: lista wydań dochodzi z tła (prawdziwy `QThread`, bramka listy) i zaznacza wiersz, którego
    zdanie ma inną wysokość niż zdanie z konstrukcji: „najpierw rozstrzygnij” (krótsze - dawniej pole,
    „Wskaż…” i „Zmień…” podjeżdżały w górę: natywnie ×1,6 -18 px) albo „rodowód dokładny” (dłuższe -
    spychało w dół). Okno zwężone z TREŚCI tak, żeby wysokość wiersza naprawdę się różniła (zdanie
    przeglądu: etykieta 0,9 szerokości zdania o kasowaniu; zdanie o rodowodzie: szerokość zdania
    o kasowaniu + 8 px), warunek wstępny liczony niezależną miarą z wysokością przycisku „Otwórz”.
    Pole, „Wskaż…” i „Zmień…” stoją na ekranie tam, gdzie przed listą; „Otwórz” (stan przeglądu) stoi
    górą przy zdaniu.

    Falsyfikatory: zdanie wiersza zwykłym `QLabel` (rezerwa zdania z konstrukcji) - pozycje się
    zmieniają; „Otwórz” bez `AlignTop` - przycisk w środku wiersza wyższego od niego."""
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QFont
    i18n.set_lang(lang)
    if skala != 1.0:
        font = QFont(QApplication.font())
        font.setPointSizeF(font.pointSizeF() * skala)
        QApplication.setFont(font)
    con, _profile, _flats = _baza(tmp_path)
    archive = tmp_path / "ARCH"
    if stan == "przeglad":
        work = tmp_path / "_WBPP"
        _wyniki(_wydanie_obiektu(work, "A", ts="2026-10-09T10:00:00+00:00", con=con), {"masterDark_A.xisf": b"D"})
        _czytnik(monkeypatch, {"masterDark_A.xisf": {"kind": "master_dark"}})
        klucz = "harvest.rel.review_note"
    else:
        work, _root, _out, _ids, zeznania = _wydanie_ic1795(tmp_path, con, archive)
        _czytnik(monkeypatch, zeznania)
        _pulpit(monkeypatch)
        przed_dostawa = _dlg(con, archive, work_root=str(work))
        przed_dostawa._on_apply()
        przed_dostawa.reject()
        _dostawa_po_zwyklym_zamknij(con, archive)
        klucz = "harvest.rel.lineage_note"
    gate, entered = _wolna_lista(monkeypatch)
    dlg = _dlg(con, archive, work_root=str(work), off_thread=True)
    dlg.show()
    assert entered.wait(10)
    _pompuj(50)
    lab = dlg.rel_done_note
    kasowanie = lab.fontMetrics().horizontalAdvance(i18n.t("harvest.rel.done_note"))
    w = int(0.9 * kasowanie) if stan == "przeglad" else kasowanie + 8
    dlg.resize(dlg.width() + w - lab.width(), dlg.height())
    _pompuj(50)
    assert lab.width() == w, (lab.width(), w, "okno nie dało się zwęzić - test niczego by nie pokazał")
    przycisk = dlg.btn_open_release.sizeHint().height()
    wiersz = {k: max(_wysokosc_zdania(i18n.t(k), lab.font(), w), przycisk)
              for k in ("harvest.rel.done_note", klucz)}
    assert wiersz[klucz] != wiersz["harvest.rel.done_note"], (wiersz, "test niczego by nie pokazał")

    def na_ekranie():
        # okno rośnie pod tabelę W LEWO (AR-201) - lewa krawędź pola idzie z nim; liczy się y pola
        # i obie współrzędne przycisków przy prawej krawędzi (jak `test_miejsce_listy_zarezerwowane…`)
        p = {x: x.mapToGlobal(QPoint(0, 0)) for x in (dlg.edit_output, dlg.btn_pick, dlg.btn_archive)}
        return (p[dlg.edit_output].y(), (p[dlg.btn_pick].x(), p[dlg.btn_pick].y()),
                (p[dlg.btn_archive].x(), p[dlg.btn_archive].y()))
    przed = na_ekranie()
    gate.set()
    assert _czekaj_az(lambda: dlg._rel_thread is None and dlg._dry_thread is None and not lab.isHidden())
    _pompuj(100)
    assert lab.text() == i18n.t(klucz), lab.text()
    assert na_ekranie() == przed, (przed, na_ekranie())
    if stan == "przeglad":                         # „Otwórz” stoi przy zdaniu, nie w środku wyższego wiersza
        assert not dlg.btn_open_release.isHidden()
        assert dlg.btn_open_release.mapToGlobal(QPoint(0, 0)).y() == lab.mapToGlobal(QPoint(0, 0)).y()
    con.close()


# ---------------------------------------------------------------- zerwany udział i odmowa w żniwach (AR-222)


def _odmowa_listingu(sciezka):
    exc = PermissionError(None, "Odmowa dostępu", str(sciezka), 5)
    if getattr(exc, "winerror", None) != 5:
        pytest.skip("`winerror` istnieje wyłącznie na Windows")
    return exc


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_wyjscie_bez_listingu_mowi_klasa_jak_blad_stat(qapp, tmp_path, ustawienia, monkeypatch, lang):
    """AR-222: wyjście, którego `stat` przechodzi, a listing nie (odmowa 5 - zmierzone na
    `C:\\System Volume Information`), dawało pusty plan i „Brak masterów i stosów”. Teraz zdanie
    błędu sondy klasą w języku UI jak przy błędzie `stat` (AR-199), szczegół systemu w podpowiedzi,
    plan znika, „Wciągnij” zgaszony, pamięć pola nie bierze ścieżki. Falsyfikator: bez gałęzi
    w `_on_dry_done` - zdanie planu niepełnego i ścieżka w pamięci pola."""
    from test_harvest import _pada_dla
    from horreum.gui.wb_worker import tekst_powodu, wiersz_systemu
    from horreum.item_reasons import blad_systemu
    i18n.set_lang(lang)
    con, _profile, _flats = _baza(tmp_path)
    out = _wyjscie(tmp_path, {"masterFlat_A.xisf": b"A"})
    exc = _odmowa_listingu(out)
    _pada_dla(monkeypatch, "scandir", {out: exc})
    dlg = _dlg(con, tmp_path / "ARCH")
    dlg._set_output(str(out))
    powod = blad_systemu(exc)
    assert dlg.notice.text() == i18n.t("harvest.dry_failed", msg=tekst_powodu(powod)), dlg.notice.text()
    assert dlg.notice.property("role") == "error" and wiersz_systemu(powod) in dlg.notice.toolTip()
    assert dlg._plan is None and not dlg.btn_apply.isEnabled() and dlg.table.rowCount() == 0
    assert str(ustawienia.value("harvest/last_output", "") or "") == ""
    if lang == "en":
        assert not _PL_LITERY.search(dlg.notice.text()), dlg.notice.text()
    con.close()


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_plan_niepelny_mowi_ktore_katalogi_i_nie_liczy_wiersza(qapp, tmp_path, ustawienia, monkeypatch, lang):
    """AR-222: podkatalog wyjścia bez listingu - pozycje części czytelnej w tabeli, zdanie „Plan
    niepełny: 1 katalog wyjścia nieprzeczytany - stare” w roli ostrzeżenia ze szczegółem systemu;
    liczby planu nie trafiają do wiersza listy (`_fresh`: zera planu częściowego odsłoniłyby „folder
    możesz skasować”). Pusto w części czytelnej - to samo zdanie, nie „Brak masterów i stosów”.
    Falsyfikatory: `_show_notice` bez zdania planu niepełnego; `_fresh` z planu częściowego."""
    from test_harvest import _pada_dla
    from horreum.gui.harvest_dialog import norm_path
    from horreum.gui.wb_worker import wiersz_systemu
    from horreum.item_reasons import blad_systemu
    i18n.set_lang(lang)
    con, _profile, _flats = _baza(tmp_path)
    out = _wyjscie(tmp_path, {"masterFlat_A.xisf": b"A"})
    (out / "stare").mkdir()
    pusty = _wyjscie(tmp_path, {}, sub=("WBPP2", "master"))
    (pusty / "stare").mkdir()
    exc = _odmowa_listingu(out / "stare")
    _pada_dla(monkeypatch, "scandir", {out / "stare": exc, pusty / "stare": _odmowa_listingu(pusty / "stare")})
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls()})
    dlg = _dlg(con, tmp_path / "ARCH")
    dlg._set_output(str(out))
    zdanie = i18n.t_plural("harvest.unread_dirs", 1, paths="stare")
    assert dlg.table.rowCount() == 1 and dlg._plan is not None
    assert dlg.notice.text() == zdanie and dlg.notice.property("role") == "warn", dlg.notice.text()
    assert wiersz_systemu(blad_systemu(exc)) in dlg.notice.toolTip()
    assert norm_path(str(out)) not in dlg._fresh
    dlg._set_output(str(pusty))
    assert dlg.table.rowCount() == 0 and dlg.notice.text() == zdanie, dlg.notice.text()
    assert dlg.notice.property("role") == "warn"
    if lang == "en":
        assert not _PL_LITERY.search(zdanie), zdanie
    con.close()


def test_plan_niepelny_przy_wydaniu_mowi_oba_zdania(qapp, tmp_path, ustawienia, monkeypatch):
    """Plan niepełny w drzewie wydania obiektu: najpierw zdanie planu niepełnego, potem zdanie
    o manifeście wydania - jedno pole, rola ostrzeżenia (AR-222)."""
    from test_harvest import _pada_dla
    con, _profile, flats = _baza(tmp_path)
    out = _wyjscie(tmp_path, {"masterFlat_A.xisf": b"A"})
    (out / "stare").mkdir()
    manifest = {"layout": projection.OBJECT_LAYOUT, "root": str(out.parent), "object_id": 1,
                "object_canon": "Cr464",
                "zestawy": {SEG: {"flat_raw": [flats[_flat_name(i, "CLS")] for i in range(3)]}}}
    (out.parent / projection.MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
    _pada_dla(monkeypatch, "scandir", {out / "stare": _odmowa_listingu(out / "stare")})
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls()})
    dlg = _dlg(con, tmp_path / "ARCH")
    dlg._set_output(str(out))
    assert dlg.notice.text() == (i18n.t_plural("harvest.unread_dirs", 1, paths="stare") + " "
                                 + f"Wydanie Horreum (manifest _PROJEKCJA.json): {out.parent}"), dlg.notice.text()
    assert dlg.notice.property("role") == "warn"
    con.close()


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_karta_na_zerwanym_udziale_mowi_klasa_nie_brak(qapp, tmp_path, ustawienia, monkeypatch, lang):
    """AR-222: karta na zerwanym udziale (53 - CPython daje `FileNotFoundError`) mówiła „Folder karty
    nie istnieje … podłącz dysk”. Teraz zdanie karty niedostępnej z klasą w języku UI, szczegół
    systemu w podpowiedzi, rola ostrzeżenia; obok karty brakującej - oba zdania; karta, której
    `OBJECTS` nie da się przeczytać (odmowa 5), mówi tym samym zdaniem, nie „Na kartach nie ma jeszcze
    wydań”. Falsyfikatory: `missing_roots` na `os.path.isdir`; `_zdanie_listy` bez kart nieczytelnych;
    worker bez `errors_out` listy wydań."""
    from test_harvest import _pada_dla
    from horreum.gui.wb_worker import tekst_powodu, wiersz_systemu
    from horreum.item_reasons import blad_systemu
    i18n.set_lang(lang)
    con, _profile, _flats = _baza(tmp_path)
    karta = tmp_path / "Q" / "_WBPP"
    exc = OSError(None, "Nie można odnaleźć ścieżki sieciowej", str(karta), 53)
    if getattr(exc, "winerror", None) != 53:
        pytest.skip("`winerror` istnieje wyłącznie na Windows")
    _pada_dla(monkeypatch, "stat", {karta: exc})
    powod = blad_systemu(exc)
    zdanie = i18n.t("harvest.rel.unreachable_one", path=str(karta), msg=tekst_powodu(powod))
    dlg = _dlg(con, tmp_path / "ARCH", work_root=str(karta))
    dlg.show()
    QTest.qWait(30)
    assert dlg.rel_notice.text() == zdanie, dlg.rel_notice.text()
    assert dlg.rel_notice.property("role") == "warn" and wiersz_systemu(powod) in dlg.rel_notice.toolTip()
    if lang == "en":
        assert not _PL_LITERY.search(zdanie), zdanie
    brak = tmp_path / "F" / "_WBPP"
    dlg2 = _dlg(con, tmp_path / "ARCH", work_root=str(brak), release_roots=[str(karta)])
    dlg2.show()
    QTest.qWait(30)
    assert dlg2.rel_notice.text() == i18n.t("harvest.rel.missing_one", path=str(brak)) + " " + zdanie
    jest = tmp_path / "G" / "_WBPP"
    (jest / projection.OBJECT_NAMESPACE).mkdir(parents=True)
    odmowa = _odmowa_listingu(jest / projection.OBJECT_NAMESPACE)
    _pada_dla(monkeypatch, "listdir", {jest / projection.OBJECT_NAMESPACE: odmowa})
    dlg3 = _dlg(con, tmp_path / "ARCH", work_root=str(jest))
    dlg3.show()
    QTest.qWait(30)
    assert dlg3.rel_notice.text() == i18n.t("harvest.rel.unreachable_one", path=str(jest),
                                            msg=tekst_powodu(blad_systemu(odmowa))), dlg3.rel_notice.text()
    con.close()


def test_odmiana_zdan_planu_niepelnego_i_kart():
    """Formy mnogie nowych zdań (AR-222): PL 1/2/5/12/22, EN 1/2."""
    pl = {1: ("katalog wyjścia nieprzeczytany", "folder karty niedostępny"),
          2: ("katalogi wyjścia nieprzeczytane", "foldery kart niedostępne"),
          5: ("katalogów wyjścia nieprzeczytanych", "folderów kart niedostępnych"),
          12: ("katalogów wyjścia nieprzeczytanych", "folderów kart niedostępnych"),
          22: ("katalogi wyjścia nieprzeczytane", "foldery kart niedostępne")}
    for n, (plan_, karty) in pl.items():
        assert i18n.t_plural("harvest.unread_dirs", n, paths="x") == f"Plan niepełny: {n} {plan_} - x."
        assert i18n.t_plural("harvest.rel.unreachable_many", n, paths="x") == f"{n} {karty}: x"
    i18n.set_lang("en")
    # Kropka kończy zdanie - przy wydaniu stoi za nim zdanie manifestu, a ścieżka bez kropki zlewała się
    # z nim w jeden ciąg („master\stare Wydanie Horreum…”).
    assert i18n.t_plural("harvest.unread_dirs", 1, paths="x") == "Incomplete plan: 1 output folder not read - x."
    assert i18n.t_plural("harvest.unread_dirs", 2, paths="x") == "Incomplete plan: 2 output folders not read - x."
    assert i18n.t_plural("harvest.rel.unreachable_many", 1, paths="x") == "1 card folder is unreachable: x"
    assert i18n.t_plural("harvest.rel.unreachable_many", 2, paths="x") == "2 card folders are unreachable: x"


def test_wiersz_z_nieprzeczytanym_nie_jest_wciagniety():
    """AR-222: wiersz listy, którego lista nie przeczytała w całości (`unreadable`), nie jest
    „wciągnięty” także przy niczym do wciągnięcia - zdanie „folder możesz skasować” nie staje; stan
    mówi „nieprzeczytane N”. Falsyfikator: `is_harvested` bez `not row.unreadable`."""
    import dataclasses
    row = harvest.ReleaseRow("K", "K/OBJECTS/X", "X", None, "K/OBJECTS/X/out", 0, 3, 0,
                             unreadable=("K/OBJECTS/X/out/a", "K/OBJECTS/X/out/b"))
    assert not is_harvested(row) and not is_harvested(row, fresh=(0, 3, 0))
    assert release_state_text(row) == "wciągnięte 3 · nieprzeczytane 2"
    assert is_harvested(dataclasses.replace(row, unreadable=()))


def _wciagniete(tmp_path, monkeypatch):
    """Okno, w którym wiersz wydania i jego świeży podgląd mówią „wciągnięte 1”, a pod listą stoi
    zdanie „Folder wydania możesz skasować” - punkt wyjścia testów blokady (AR-222)."""
    con, _profile, _flats = _baza(tmp_path)
    work = tmp_path / "_WBPP"
    out = _wyniki(_wydanie_obiektu(work, "A", ts="2026-10-09T10:00:00+00:00", con=con),
                  {"masterFlat_A.xisf": b"A"})
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls()})
    dlg = _dlg(con, tmp_path / "ARCH", work_root=str(work))
    dlg._on_apply()
    dlg._set_output(str(out))                    # pełny podgląd po biegu - świeże liczby wiersza
    assert hd_mod.norm_path(str(out)) in dlg._fresh
    assert _stan(dlg, 0) == "wciągnięte 1" and _kasowanie_widac(dlg)
    return con, dlg, out


def _kasowanie_widac(dlg):
    return not dlg.rel_done_note.isHidden() and dlg.rel_done_note.text() == i18n.t("harvest.rel.done_note")


def test_podglad_niepelny_blokuje_wciagniete_do_pelnego(qapp, tmp_path, ustawienia, monkeypatch):
    """AR-222: wiersz i świeży podgląd mówią „wciągnięte”, a kolejny podgląd tego wyjścia nie czyta
    podkatalogu (odmowa 5) - stan wiersza mówi „nieprzeczytane 1”, nie „wciągnięte”, zdanie „Folder
    wydania możesz skasować” znika: ani liczby listy, ani stary podgląd go nie odsłaniają. Pełny
    podgląd zdejmuje blokadę. Falsyfikatory: `is_harvested` bez blokady; `_on_dry_done` bez blokady
    (same liczby listy); pełny podgląd bez zdjęcia blokady."""
    from test_harvest import _pada_dla
    con, dlg, out = _wciagniete(tmp_path, monkeypatch)
    stare = out / "master" / "stare"
    stare.mkdir()
    with monkeypatch.context() as m:
        _pada_dla(m, "scandir", {stare: _odmowa_listingu(stare)})
        dlg._set_output(str(out))
        assert _stan(dlg, 0) == "nieprzeczytane 1" and not _kasowanie_widac(dlg), _stan(dlg, 0)
    dlg._set_output(str(out))
    assert _stan(dlg, 0) == "wciągnięte 1" and _kasowanie_widac(dlg)
    con.close()


def test_podglad_nieudany_blokuje_wciagniete_do_pelnego(qapp, tmp_path, ustawienia, monkeypatch):
    """AR-222: podgląd tego samego wyjścia pada - listing samego wyjścia (odmowa 5, droga przez
    `_on_dry_done`) albo `stat` wyjścia (zerwany udział 53, wyjątek workera). Stan wiersza mówi
    „podgląd nieudany”, nie „wciągnięte”, zdanie o kasowaniu znika; pełny podgląd zdejmuje blokadę.
    Falsyfikator: `_on_dry_failed` bez unieważnienia - stary podgląd dalej mówi „wciągnięte 1”."""
    from test_harvest import _pada_dla
    con, dlg, out = _wciagniete(tmp_path, monkeypatch)
    zerwany = OSError(None, "Nie można odnaleźć ścieżki sieciowej", str(out), 53)
    for nazwa, exc in (("scandir", _odmowa_listingu(out)), ("stat", zerwany)):
        with monkeypatch.context() as m:
            _pada_dla(m, nazwa, {out: exc})
            dlg._set_output(str(out))
            assert dlg._plan is None and dlg.notice.property("role") == "error", nazwa
            assert _stan(dlg, 0) == "podgląd nieudany" and not _kasowanie_widac(dlg), (nazwa, _stan(dlg, 0))
        dlg._set_output(str(out))
        assert _stan(dlg, 0) == "wciągnięte 1" and _kasowanie_widac(dlg), nazwa
    con.close()


# ============================================================ AR-213: lista wydań po naprawie manifestu

def test_lista_wydan_po_naprawie_manifestu_bez_daty_i_bez_czeka_na_wbpp(tmp_path):
    """Wiersz listy wydań okna żniw z manifestu naprawionego bez dowodu czasu (`ts` None,
    `repaired_at`): data wydania pusta, a stan mówi kandydata „do sprawdzenia”, nie „czeka na
    WBPP” - chwila naprawy jako data wydania kłamałaby, że wyniki WBPP są starsze od wydania."""
    from test_harvest import _wydanie_po_naprawie_bez_czasu
    con, _p, _root, karta, _ids, _stary = _wydanie_po_naprawie_bez_czasu(tmp_path)
    [row] = harvest.releases([karta])
    assert release_date_text(row.ts) == ""
    assert release_state_text(row) == "do sprawdzenia 1"
    con.close()


# ============================================================ AR-234 / AR-240: manifest nie do przeczytania, data z drzewa

def _odmowa_odczytu(sciezka):
    import errno
    return PermissionError(errno.EACCES, "Permission denied", str(sciezka))


@pytest.fixture
def jezyk_okna():
    yield i18n.set_lang
    i18n.set_lang("pl")


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_wiersz_manifestu_nieczytelnego_i_uszkodzonego_stan_podpowiedz_i_data_z_drzewa(jezyk_okna, tmp_path,
                                                                                    monkeypatch, lang):
    """AR-234 (Qt-wolne funkcje stanu wiersza listy): manifest bez prawa odczytu - stan zaczyna się od
    „manifest nieczytelny: <klasa>”, uszkodzony - „manifest uszkodzony (JSON)”; podpowiedź komórki niesie
    zdanie o manifeście ze ścieżką i szczegół systemu; taki wiersz NIGDY nie jest „wciągnięty”. AR-240:
    data z drzewa (`ts_source`) ma znak przybliżenia i podpowiedź, data wydania - bez zmian. EN bez
    polskich znaków. Falsyfikatory: `is_harvested` bez `manifest_error`; stan bez członu manifestu."""
    import dataclasses
    from test_harvest import _open_pada_dla, _wydanie_na_dysku, _wynik_wbpp
    from horreum.gui.harvest_dialog import manifest_error_text, release_date_cell, release_state_tip
    from horreum.gui.wb_worker import wiersz_systemu
    jezyk_okna(lang)
    zamkniety = _wydanie_na_dysku(tmp_path, "ZAMKNIETY")
    _wynik_wbpp(zamkniety, "masterFlat_A.xisf")
    zly = _wydanie_na_dysku(tmp_path, "ZLY")
    (zly / projection.MANIFEST_NAME).write_bytes(b"{")
    sciezka = zamkniety / projection.MANIFEST_NAME
    _open_pada_dla(monkeypatch, {sciezka: _odmowa_odczytu(sciezka)})
    rows = {os.path.basename(r.object_root): r for r in harvest.releases([str(tmp_path / "_WBPP")])}
    z, u = rows["ZAMKNIETY"], rows["ZLY"]
    klasa = i18n.t("objchg.item.os_denied", os_code="Errno 13")
    assert release_state_text(z).startswith(i18n.t("harvest.rel.manifest_unreadable", msg=klasa)), z
    assert release_state_text(u) == i18n.t("harvest.rel.manifest_damaged", detail="JSON")
    tip = release_state_tip(z)
    assert manifest_error_text(z.manifest_error, str(sciezka)) in tip and wiersz_systemu(z.manifest_error) in tip
    assert i18n.t("harvest.manifest_damaged", path=str(zly / projection.MANIFEST_NAME), detail="JSON") in \
        release_state_tip(u)
    wciagniety = dataclasses.replace(z, pending=0, done=3)
    assert not is_harvested(wciagniety) and is_harvested(dataclasses.replace(wciagniety, manifest_error=None))
    drzewo = dataclasses.replace(rows["ZLY"], ts="2026-10-09T14:57:23+00:00",
                                 ts_source=projection.TS_SOURCE_TREE, manifest_error=None)
    tekst, podpowiedz = release_date_cell(drzewo)
    assert tekst == i18n.t("harvest.rel.date_tree", date=release_date_text(drzewo.ts))
    assert podpowiedz == i18n.t("harvest.rel.date_tree_tip", ts=drzewo.ts)
    assert release_date_cell(dataclasses.replace(drzewo, ts_source=None)) == (
        release_date_text(drzewo.ts), drzewo.ts)
    if lang == "en":
        for w in (release_state_text(z), release_state_text(u), tekst, podpowiedz):
            assert not set(w) & set("„ąćęłńóśźż"), w


def test_find_manifest_zatrzymuje_sie_na_nieczytelnym_najblizszym(tmp_path, monkeypatch):
    """AR-234: manifest najbliższego wydania, którego nie da się przeczytać, KOŃCZY szukanie
    z powodem w `errors_out` - manifest poziom wyżej należy do innego drzewa i nie może świadczyć;
    bez listy szukanie idzie wyżej jak dotąd. Falsyfikator: szukanie dalej mimo błędu."""
    from test_harvest import _open_pada_dla
    wyzej = tmp_path / "karta"
    wydanie = wyzej / "OBJECTS" / "X"
    out = wydanie / "out"
    out.mkdir(parents=True)
    (wyzej / projection.MANIFEST_NAME).write_text(json.dumps({"layout": "po-obiektach"}), encoding="utf-8")
    (wydanie / projection.MANIFEST_NAME).write_text(json.dumps({"layout": "wbpp-obiekt"}), encoding="utf-8")
    sciezka = wydanie / projection.MANIFEST_NAME
    _open_pada_dla(monkeypatch, {sciezka: _odmowa_odczytu(sciezka)})
    bledy = []
    assert find_manifest(str(out), errors_out=bledy) == (str(wydanie), None)
    assert [(p, w.code) for p, w in bledy] == [(str(sciezka), "os_denied")]
    assert find_manifest(str(out)) == (str(wyzej), {"layout": "po-obiektach"})


def test_podglad_wyjscia_pod_manifestem_nieczytelnym_mowi_klase_zamiast_planu(qapp, tmp_path, ustawienia,
                                                                            monkeypatch):
    """AR-234: podgląd wyjścia WBPP, nad którym manifest wydania leży, a nie da się go przeczytać -
    sonda pada zdaniem o manifeście ze ścieżką i klasą w roli błędu (szczegół systemu pod kursorem),
    bez planu („Wciągnij” wygaszone); wcześniej plan bez świadka mówił stosom „brak manifestu”.
    Falsyfikator: `HarvestDryWorker` z `find_manifest` bez `errors_out`."""
    from test_harvest import _open_pada_dla, _wydanie_na_dysku
    con, _profile, _flats = _baza(tmp_path)
    wydanie = _wydanie_na_dysku(tmp_path, "ZAMKNIETY")
    out = _wyjscie(wydanie, {"masterFlat_A.xisf": b"A"}, sub=("out", "master"))
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls()})
    sciezka = wydanie / projection.MANIFEST_NAME
    _open_pada_dla(monkeypatch, {sciezka: _odmowa_odczytu(sciezka)})
    ustawienia.setValue("harvest/last_output", str(out))
    dlg = _dlg(con, tmp_path / "ARCH")
    klasa = i18n.t("objchg.item.os_denied", os_code="Errno 13")
    assert dlg.notice.text() == i18n.t("harvest.manifest_unreadable", path=str(sciezka), msg=klasa)
    assert dlg.notice.property("role") == "error" and "Errno 13" in dlg.notice.toolTip()
    assert dlg._plan is None and not dlg.btn_apply.isEnabled()
    dlg.reject()
    con.close()


# ============================================================ AR-262, AR-251 - waga przycisku, notka wydania bez `out`


def _waga(btn):
    return btn.font().bold(), btn.isDefault(), btn.minimumHeight()


def test_waga_tylko_na_aktywnym_przycisku_zniw(qapp, tmp_path, ustawienia, monkeypatch):
    """AR-262: „Wciągnij” waży (bold, wysokość, Enter) WYŁĄCZNIE aktywny - okno bez roboty (bez wyjścia),
    przycisk wygaszony po biegu z nazwą skutku: bez wagi; plan z plikiem do wciągnięcia: waga. Falsyfikator:
    waga na „Wciągnij” zawsze, gdy przyjęcie jej nie bierze (wygaszony „Wciągnij 0 plików” gruby
    i domyślny)."""
    con, _profile, _flats = _baza(tmp_path)
    out = _wyjscie(tmp_path, {"masterFlat_A.xisf": b"A"})
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls()})
    dlg = _dlg(con, tmp_path / "ARCH")
    assert not dlg.btn_apply.isEnabled() and _waga(dlg.btn_apply) == (False, False, 0)
    dlg._set_output(str(out))
    assert dlg.btn_apply.isEnabled() and _waga(dlg.btn_apply) == (True, True, 34)
    dlg._on_apply()
    assert not dlg.btn_apply.isEnabled() and _waga(dlg.btn_apply) == (False, False, 0)
    dlg.reject()
    con.close()


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_wydanie_bez_wyjscia_wbpp_notka_bez_roli_bledu(qapp, tmp_path, ustawienia, monkeypatch, jezyk_okna, lang):
    """AR-262: klik myszą w wiersz wydania „czeka na WBPP” bez folderu `out` - notka mówi, że WBPP jeszcze
    nie zapisał wyników, rolą drugorzędną (normalny stan, nie awaria); ścieżka spoza listy wydań dalej
    mówi „Katalog nie istnieje” rolą błędu. Falsyfikator: brak folderu zawsze w roli błędu."""
    jezyk_okna(lang)
    con, _profile, _flats = _baza(tmp_path)
    work = tmp_path / "ASTRO_" / "_WBPP"
    ic = _wydanie_obiektu(work, "IC1795", ts="2026-10-09T10:00:00+00:00", con=con)
    czeka = _wydanie_obiektu(work, "NGC7000", ts="2026-10-10T10:00:00+00:00")
    _wyniki(ic, {"masterFlat_IC.xisf": b"I"})
    _czytnik(monkeypatch, {"masterFlat_IC.xisf": _flat_cls()})
    dlg = _dlg(con, tmp_path / "ARCH", work_root=str(work))
    dlg.show()
    try:
        assert _czekaj_az(lambda: dlg.rel_table.rowCount() == 2)
        assert dlg.rel_table.item(0, 0).text() == "NGC7000" and _stan(dlg, 0) == i18n.t("harvest.rel.waiting")
        _klik_wiersza(dlg, 0)
        out = str(czeka / projection.OUTPUT_DIR)
        assert _czekaj_az(lambda: dlg.notice.text() == i18n.t("harvest.out_waiting", path=out)), dlg.notice.text()
        assert dlg.notice.property("role") == "secondary" and not os.path.exists(out)
        if lang == "en":
            assert not _PL_LITERY.search(dlg.notice.text()), dlg.notice.text()
        brak = str(tmp_path / "nie_ma" / "out")
        dlg._set_output(brak)
        assert dlg.notice.text() == i18n.t("harvest.missing_dir", path=brak)
        assert dlg.notice.property("role") == "error"
    finally:
        dlg.reject()
        con.close()


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_zdanie_zniw_o_manifescie_innego_wydania_bez_gestu_okna_wydania(jezyk_okna, lang):
    """AR-251: zdanie żniw o manifeście, którego nie da się przyjąć (`manifest_error_text`), składa
    `proj_manifest_foreign` zdaniem katalogu - po rozdziale rady i gestu bez przycisków okna wydania
    („Odśwież podgląd”, „Zapisz manifest”), których okno żniw nie ma. Falsyfikator: gest okna wydania
    w zdaniu rdzenia albo w katalogu kodu."""
    from horreum.gui.harvest_dialog import manifest_error_text
    from horreum.gui.wb_worker import tekst_powodu
    jezyk_okna(lang)
    powod = projection._odmowa_obcego("object_id")
    sciezka = "X:\\W\\OBJECTS\\M42\\" + projection.MANIFEST_NAME
    zdanie = manifest_error_text(powod, sciezka)
    assert zdanie == i18n.t("harvest.manifest_unreadable", path=sciezka, msg=tekst_powodu(powod))
    for gest in ("Odśwież podgląd", "Zapisz manifest", "Refresh preview", "Write manifest"):
        assert gest not in zdanie, zdanie
    if lang == "en":
        assert not _PL_LITERY.search(zdanie), zdanie
