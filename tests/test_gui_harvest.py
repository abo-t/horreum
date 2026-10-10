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
import threading
import time
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QDeadlineTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from horreum import db, harvest, hashing, projection, repo
from horreum.gui import i18n
from horreum.gui import harvest_dialog as hd_mod
from horreum.gui.harvest_dialog import (
    _HARVEST_REASONS, _HARVEST_STATUS, COL_DIR, COL_FILE, COL_NAME, COL_REASON, COL_RELEASE,
    COL_STATUS, HarvestDialog, clean_path, common_root, find_manifest, is_under, reason_text,
    rel_text, release_text,
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
            xbinning=z.get("xbinning", 1), date_obs="2023-05-07T21:00:00")
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
                                         "status": "review", "exists_path": None, **kw})
    assert reason_text(it(reason="inputs_unknown", reason_n=2, detail="a_c, b_c")) == \
        "wejść nieznanych bazie: 2: a_c, b_c"
    assert reason_text(it(reason="no_history")) == "brak historii integracji w pliku"
    assert reason_text(it(reason="name_taken", reason_n=7)) == "zajęte wszystkie nazwy tej nocy i filtru: 7"
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
    braki = [k for k in list(_HARVEST_REASONS.values()) + list(_HARVEST_STATUS.values())
             if k not in CATALOG or not {"pl", "en"} <= set(CATALOG[k])]
    assert not braki, f"klucze żniw bez zdania PL/EN: {braki}"


def test_odmiana_liczebnikow_z_nascie():
    """Liczby mnogie przycisku i paska stanu: 12-14 to forma „many” mimo końcówki 2-4."""
    t = i18n.t_plural
    assert t("harvest.btn_apply", 1) == "Wciągnij 1 master"
    assert t("harvest.btn_apply", 3) == "Wciągnij 3 mastery"
    assert t("harvest.btn_apply", 12) == "Wciągnij 12 masterów"
    assert t("harvest.btn_apply", 22) == "Wciągnij 22 mastery"
    assert t("harvest.status_placed", 13, root="R").startswith("Wciągnięto 13 masterów")
    assert t("harvest.status_placed", 24, root="R").startswith("Wciągnięto 24 mastery")


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
    assert dlg.btn_apply.isEnabled() and dlg.btn_apply.text() == "Wciągnij 1 master"
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
    assert not dlg.btn_apply.isEnabled() and dlg.btn_apply.text() == "Wciągnij 0 masterów"
    dlg._on_apply()                                                      # wygaszony - i tak nic nie rusza
    assert not (tmp_path / "ARCH").exists()
    con.close()


def test_pusty_katalog_i_katalog_nieistniejacy(qapp, tmp_path, ustawienia, monkeypatch):
    """Pusty katalog → „Brak masterów w …”; ścieżka, której nie ma → osobne zdanie i pamięć pola
    nietknięta (literówka nie wraca przy następnym otwarciu)."""
    con, _profile, _flats = _baza(tmp_path)
    _czytnik(monkeypatch, {})
    empty = tmp_path / "WBPP" / "pusty"
    empty.mkdir(parents=True)
    (empty / "notatka.txt").write_text("x", encoding="utf-8")            # nie-master nie liczy się
    (empty / "masterLight_Ha.xisf").write_bytes(b"L")                    # stos - droga „Stosy”, nie żniwa
    dlg = _dlg(con, tmp_path / "ARCH")
    dlg._set_output(str(empty))
    assert dlg.notice.text() == f"Brak masterów w {empty}"
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
    assert dlg.notice.text() == "Wskaż archiwum (źródło Dostawy) - tam trafią mastery."
    assert dlg.archive_label.text() == "Archiwum: nie wskazane"
    assert dlg.table.rowCount() == 0 and not dlg.btn_apply.isEnabled() and dlg.busy.isHidden()
    archive = tmp_path / "ARCH"
    dlg._set_archive(str(archive))
    assert dlg.archive_label.text() == f"Archiwum: {hd_mod._elide_path(str(archive))}"
    assert dlg.archive_label.toolTip() == str(archive)                   # pełna ścieżka pod kursorem
    assert dlg.btn_apply.text() == "Wciągnij 1 master"
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
    assert dlg.archive_warn.text().startswith(f"Baza zna archiwum w {db_arch} - mastery trafią gdzie indziej")
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
    assert dlg2.btn_apply.isEnabled() and dlg2.btn_apply.text() == "Wciągnij 1 master"
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
    assert tekst == "nagłówek mastera nie zgadza się z wejściami: IMAGETYP='FLAT' -> flat"
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
    assert dlg.edit_output.text() == str(out) and dlg.btn_apply.text() == "Wciągnij 1 master"
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
    assert dlg.summary == f"Wciągnięto 1 master do archiwum → {cel.parent}"
    assert dlg.harvested_root is None                                    # jeszcze nikt nie przyjął
    assert dlg.btn_apply.text() == "Wciągnięto" and not dlg.btn_apply.isEnabled()
    assert not dlg.btn_accept.isHidden() and dlg.btn_accept.isEnabled()
    assert dlg.edit_output.isEnabled() and dlg.busy.isHidden() and dlg.btn_cancel.isHidden()
    dlg.btn_accept.click()
    assert dlg.result() == QDialog.Accepted
    assert dlg.harvested_root == str(cel.parent)
    assert dlg.summary == f"Wciągnięto 1 master do archiwum → {cel.parent}"
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
    (następna dostawa ich nie zobaczy)."""
    con, _profile, _flats = _baza(tmp_path)
    archive = tmp_path / "ARCH"
    out = _wyjscie(tmp_path, {"masterFlat_A.xisf": b"A", "masterFlat_B.xisf": b"B"})
    _czytnik(monkeypatch, {"masterFlat_A.xisf": _flat_cls(), "masterFlat_B.xisf": _flat_ha()})
    ustawienia.setValue("pipeline/last_source", str(archive).lower())
    dlg = _dlg(con, archive)
    dlg._set_output(str(out))
    dlg._on_apply()
    dlg.btn_close.click()
    assert dlg.result() == QDialog.Rejected and dlg.harvested_root is None
    assert dlg.summary.endswith(" - baza pozna je przy następnej dostawie („Przyjmij”).")
    ustawienia.setValue("pipeline/last_source", str(tmp_path / "LIGHTS"))
    out2 = _wyjscie(tmp_path, {"masterFlat_C.xisf": b"C"}, sub=("WBPP2",))
    _czytnik(monkeypatch, {"masterFlat_C.xisf": _flat_cls()})
    dlg2 = _dlg(con, tmp_path / "ARCH2")
    dlg2._set_output(str(out2))
    dlg2._on_apply()
    dlg2.reject()
    assert dlg2.summary.endswith(" - kopie leżą poza źródłem Dostawy; baza pozna je przez „Zamknij "
                                 "i przyjmij do archiwum” albo Dostawę wskazaną na archiwum.")
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
    assert dlg.btn_apply.text() == "Wciągnij 0 masterów" and not dlg.btn_apply.isEnabled()
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
    assert dlg.btn_apply.text() == "Wciągnij 1 master"                  # nowe wyjście ma własną robotę
    dlg._on_apply()
    zestaw = _cel(archive).parent.parent
    assert dlg.summary == f"Wciągnięto 2 mastery do archiwum → {zestaw}"
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
    assert dlg.btn_apply.text() == "Wciągnij 2 mastery"
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
    assert dlg.btn_archive.toolTip().startswith("Archiwum zablokowane: w tym oknie wciągnięto już mastery")
    con.close()


def test_przyjecie_tylko_pod_calibration_archiwum(qapp, tmp_path, ustawienia, monkeypatch):
    """Strażnik przyjęcia: korzeń spoza `<archiwum>\\CALIBRATION` (archiwum zmienione obejściem
    blokady) → `harvested_root=None`, zdanie odmowy, okno zostaje. Zmiana archiwum po pierwszej
    kopii to EXPECT, nie tryb."""
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
                                 f"{tmp_path / 'INNE' / 'CALIBRATION'}")
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
    assert dlg.summary == (f"Wciągnięto 2 mastery do archiwum → {zestaw} · "
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
    assert dlg.summary == f"Wciągnięto 1 master do archiwum → {_cel(archive).parent}"
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
    assert dlg.summary == f"Wciągnięto 1 master do archiwum → {_cel(archive).parent} · konflikty: 1"
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
    assert " · przerwano, nietknięte: 1" in dlg.summary
    assert dlg.summary.endswith("przy następnej dostawie („Przyjmij”).")
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
    assert dlg.btn_apply.isEnabled() and dlg.btn_apply.text() == "Wciągnij 1 master"
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
    assert dlg.windowTitle() == "Harvest masters from WBPP output"
    assert dlg.notice.text() == "Choose the WBPP output folder - the preview computes itself."
    dlg._set_output(str(out))
    assert dlg.head_label.text() == "To harvest 2 · already in the archive 0 · to review 2"
    assert dlg.btn_apply.text() == "Harvest 2 masters"
    rows = _wiersze(dlg)
    assert {_kol(dlg, r, COL_STATUS) for r in rows.values()} == {"to harvest", "to review"}
    assert _kol(dlg, rows["masterDark_D.xisf"], COL_REASON).startswith("dark/bias master")
    powod = _kol(dlg, rows["masterFlat_X.xisf"], COL_REASON)
    assert powod.startswith("the master header disagrees with its inputs: ")
    assert "OIII" in powod and "Ha" in powod and not _PL_LITERY.search(powod)
    assert [dlg.table.horizontalHeaderItem(c).text() for c in range(6)] == \
        ["File", "Status", "Reason", "Target name", "Target folder", "Release"]
    assert _kol(dlg, rows["masterFlat_A.xisf"], COL_RELEASE) == "outside a Horreum release"
    dlg._on_apply()
    assert dlg.head_label.text().startswith("Harvested 2 · skipped 0 (already in the archive)")
    assert dlg.btn_apply.text() == "Harvested"
    assert dlg.btn_accept.text() == "Close and receive into the archive"
    assert dlg.summary.startswith("Harvested 2 masters into the archive → ")
    con.close()
