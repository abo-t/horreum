"""AR-64: ZAMIAR PODMIANY drogi atomowej (0038) i automat rekoncyliacji pełnym sha1.

Proces, który zginął między podmianą systemową a rewalidacją kopii pliku wypartego, zostawiał
kopię pod nazwą, której baza nie znała; rekoncyliacja patrzyła wyłącznie na nagłówek pod ścieżką,
potwierdzała commit i osierocała wersję innego pisarza (a cofnięcie przywróciłoby potem wersję
sprzed niej). Teraz zamiar (nazwy kopii wypartej K, kopii zwrotnej Z, pliku tymczasowego T i pełny
sha1 naszej wersji N - liczony w strumieniu zapisu) leży w bazie przed pierwszą podmianą, a
rekoncyliacja rozpoznaje każdą wersję WYŁĄCZNIE pełnym sha1 i jest wznawialna po śmierci procesu
w każdym etapie. Żaden krok nie kasuje pliku, którego bajtów nie rozpoznał jako A albo N.

Śmierć procesu = wyjątek spoza `Exception` (`_Smierc`) w nazwanym punkcie; „inny pisarz" = zapis
z tego samego procesu przez zwykły uchwyt (fikstury `test_writeback_podmiana`)."""

from __future__ import annotations

import hashlib
import json
import os

import pytest
from astropy.io import fits

from horreum import repo, writeback
from test_writeback import NOW
from test_writeback_podmiana import _Smierc, _baza, _backupy, _resztki, _zmien_cudzo


def _sha(p):
    return hashlib.sha1(p.read_bytes()).hexdigest()


def _zamiary(con):
    return [dict(r) for r in con.execute("SELECT * FROM replace_intent ORDER BY backup_id")]


def _zdarzenia_kept(con):
    return [json.loads(r[0]) for r in con.execute(
        "SELECT payload FROM event WHERE verb = 'location.displaced_kept' ORDER BY id")]


def _smierc_przed_rewalidacja(monkeypatch, *, cudzy=None):
    """Podmiana zaszła, proces ginie przed rewalidacją kopii wypartej. `cudzy` - słownik: inny
    pisarz zmienia plik tuż przed naszą podmianą (jego wersja B trafia pod kopię wypartą)."""
    prawdziwy = writeback._replace_file_w

    def _replace(path, tmp, kopia):
        if cudzy is not None and "bajty" not in cudzy:
            cudzy["bajty"] = _zmien_cudzo(path, "podmiana_pliku", b"\x55")
        prawdziwy(path, tmp, kopia)

    def _rewalidacja(*a, **kw):
        raise _Smierc()
    monkeypatch.setattr(writeback, "_replace_file_w", _replace)
    monkeypatch.setattr(writeback, "_rozjazd_odcisku", _rewalidacja)


def _smierc_w_commicie(con, monkeypatch, **kw):
    _smierc_przed_rewalidacja(monkeypatch, **kw)
    with pytest.raises(_Smierc):
        writeback.commit(con, "R", now=NOW)
    monkeypatch.undo()


# ============================================================ zamiar i dowód N (Z13)


@pytest.mark.parametrize("fmt", ["fits", "xisf"])
def test_zamiar_utrwalony_z_backupem_a_sha1_n_ze_strumienia(tmp_path, monkeypatch, fmt):
    """Z13: zamiar powstaje z backupem (przed podmianą), sha1 N to sha1 pliku, który stanął pod
    ścieżką - policzony w strumieniu zapisu, BEZ wtórnego pełnego odczytu pliku tymczasowego
    (jedyny pełny hasher rekoncyliacji `_sha1_pliku` nie jest w zwykłym zapisie wołany wcale).
    Falsyfikator: sha1 N liczony odczytem pliku tymczasowego (`_sha1_pliku(tmp)`)."""
    con, p, lid = _baza(tmp_path, fmt)
    wolania = []
    prawdziwy = writeback._sha1_pliku
    monkeypatch.setattr(writeback, "_sha1_pliku", lambda s: wolania.append(s) or prawdziwy(s))
    res = writeback.commit(con, "R", now=NOW)
    monkeypatch.undo()
    assert len(res.applied) == 1, res
    assert wolania == []
    (z,) = _zamiary(con)
    assert (z["prepared_sha1"], z["prepared_size"]) == (_sha(p), p.stat().st_size)
    # C1: zwykły zapis zamyka zamiar razem z potwierdzeniem backupu - otwarty zamiar znaczy
    # wyłącznie „podmiana nierozstrzygnięta”.
    assert (z["phase"], z["outcome"]) == ("closed", "replaced")
    assert z["return_path"] == writeback._nazwa_zwrotna(z["displaced_path"])
    assert _resztki(tmp_path) == []
    con.close()


# ============================================================ śmierć w biegu zapisu


def test_smierc_przed_podmiana_tymczasowy_rozpoznany_i_sprzatniety(tmp_path, monkeypatch):
    """Etap 0: zamiar utrwalony, podmiany nie było (P = A), plik tymczasowy został. Rekoncyliacja:
    `not_replaced`, T (rozpoznany jako N) precz, ponowny commit pisze. Falsyfikator: T zostaje albo
    rekoncyliacja kasuje T bez rozpoznania."""
    con, p, lid = _baza(tmp_path, "fits")

    def _f(*a, **kw):
        raise _Smierc()
    monkeypatch.setattr(writeback, "_podmien", _f)
    # Śmierć procesu nie wykonuje bloków `finally` - plik tymczasowy zostaje na dysku.
    monkeypatch.setattr(writeback, "_sprzatnij_tmp", lambda *a, **kw: None)
    with pytest.raises(_Smierc):
        writeback.commit(con, "R", now=NOW)
    monkeypatch.undo()
    assert any(n.endswith(".tmp") for n in _resztki(tmp_path))
    res = writeback.commit(con, "R", now=NOW)
    assert len(res.applied) == 1, res
    assert _resztki(tmp_path) == []
    assert [z["outcome"] for z in _zamiary(con)] == ["not_replaced", "replaced"]
    con.close()


@pytest.mark.parametrize("fmt", ["fits", "xisf"])
def test_smierc_przed_rewalidacja_bez_obcego_dokancza_rewalidacje(tmp_path, monkeypatch, fmt):
    """Etap 1 bez obcego pisarza: P = N, K = A. Rekoncyliacja dokańcza rewalidację pełnym sha1 -
    K (rozpoznana A) precz, commit potwierdzony z dysku, zamiar `replaced`. Falsyfikator: porównanie
    K z A odwrócone - K = A zostaje albo wraca pod ścieżkę."""
    con, p, lid = _baza(tmp_path, fmt)
    _smierc_w_commicie(con, monkeypatch)
    nasza = p.read_bytes()
    assert any(n.endswith(writeback._KOPIA_SUFFIX) for n in _resztki(tmp_path))
    res = writeback.commit(con, "R", now=NOW)
    assert len(res.applied) == 1 and "potwierdzony z dysku" in res.applied[0].reason, res
    assert p.read_bytes() == nasza and _resztki(tmp_path) == []
    assert _zamiary(con)[0]["outcome"] == "replaced"
    con.close()


@pytest.mark.parametrize("fmt", ["fits", "xisf"])
@pytest.mark.parametrize("dalej", ["commit", "undo"])
def test_smierc_przed_rewalidacja_z_obcym_wraca_jego_wersje(tmp_path, monkeypatch, fmt, dalej):
    """Sedno AR-64 (A2): obcy pisarz w oknie podmiany, proces ginie przed rewalidacją (P = N,
    K = B). Ponowny commit ALBO cofnięcie (rekoncyliacja wołana z undo, Z2) wraca B pod ścieżkę
    bajt w bajt, N przepada, backup bez podmiany (cofnięcie nic nie ruszy), lokacja zablokowana
    z prawdziwym powodem, zero resztek. Falsyfikator: rekoncyliacja po nagłówku (dawna reguła) -
    commit potwierdzony, B sierotą pod kopią."""
    con, p, lid = _baza(tmp_path, fmt)
    cudzy = {}
    _smierc_w_commicie(con, monkeypatch, cudzy=cudzy)
    (b,) = _backupy(con)
    if dalej == "commit":
        res = writeback.commit(con, "R", now=NOW)
        assert len(res.blocked) == 1 and "jego wersja wróciła" in res.blocked[0].reason, res
    else:
        ures = writeback.undo(con, b["commit_id"], now=NOW)
        assert not ures.restored and len(ures.blocked) == 1, ures
    assert p.read_bytes() == cudzy["bajty"] and _resztki(tmp_path) == []
    (b,) = _backupy(con)
    assert (b["pending_since"], b["unreplaced_at"]) == (None, NOW)
    (z,) = _zamiary(con)
    assert (z["outcome"], z["displaced_sha1"]) == ("returned", hashlib.sha1(cudzy["bajty"]).hexdigest())
    con.close()


def test_smierc_w_powrocie_biegu_po_podmianie_powrotnej(tmp_path, monkeypatch):
    """Etap okna powrotu BIEGU (`_oddaj_wyparty`): rewalidacja wykryła B, powrót zaszedł (P = B,
    Z = N, K brak), proces ginie przed sprzątnięciem Z. Nazwa Z jest znana z zamiaru, więc
    rekoncyliacja rozpoznaje Z jako N i ją sprząta; werdykt `returned`. Falsyfikator: losowa nazwa
    kopii zwrotnej w biegu - Z zostaje sierotą, a werdykt nie widzi powrotu."""
    con, p, lid = _baza(tmp_path, "fits")
    cudzy = {}
    prawdziwy = writeback._replace_file_w

    def _replace(path, zamiennik, kopia):
        if "bajty" not in cudzy:
            cudzy["bajty"] = _zmien_cudzo(path, "podmiana_pliku", b"\x55")
            prawdziwy(path, zamiennik, kopia)
            return
        prawdziwy(path, zamiennik, kopia)              # powrót B
        raise _Smierc()
    monkeypatch.setattr(writeback, "_replace_file_w", _replace)
    with pytest.raises(_Smierc):
        writeback.commit(con, "R", now=NOW)
    monkeypatch.undo()
    (z,) = _zamiary(con)
    assert os.path.exists(z["return_path"]) and not os.path.exists(z["displaced_path"])
    res = writeback.commit(con, "R", now=NOW)
    assert len(res.blocked) == 1 and "jego wersja wróciła" in res.blocked[0].reason, res
    assert p.read_bytes() == cudzy["bajty"] and _resztki(tmp_path) == []
    assert _zamiary(con)[0]["outcome"] == "returned"
    con.close()


def test_smierc_w_powrocie_biegu_bez_sciezki(tmp_path, monkeypatch):
    """Z2, „brak path”: powrót biegu przerwany w stanie 1177 (P brak, K = B, Z = N). Rekoncyliacja
    nie bierze blokady na nieistniejącej ścieżce: K wraca pod P, Z (rozpoznana N) precz. Falsyfikator:
    blokada pliku przed rozpoznaniem - rekoncyliacja pada na braku ścieżki, lokacja wisi."""
    con, p, lid = _baza(tmp_path, "fits")
    cudzy = {}
    prawdziwy = writeback._replace_file_w

    def _replace(path, zamiennik, kopia):
        if "bajty" not in cudzy:
            cudzy["bajty"] = _zmien_cudzo(path, "podmiana_pliku", b"\x55")
            prawdziwy(path, zamiennik, kopia)
            return
        os.rename(path, kopia)                          # 1177: P pod Z, K nie dotarło
        raise _Smierc()
    monkeypatch.setattr(writeback, "_replace_file_w", _replace)
    with pytest.raises(_Smierc):
        writeback.commit(con, "R", now=NOW)
    monkeypatch.undo()
    assert not p.exists()
    res = writeback.commit(con, "R", now=NOW)
    assert len(res.blocked) == 1, res
    assert p.read_bytes() == cudzy["bajty"] and _resztki(tmp_path) == []
    con.close()


def test_porazka_potwierdzenia_zostawia_kopie_dla_rekoncyliacji(tmp_path, monkeypatch):
    """Z12: potwierdzenie podmiany w bazie przepada (backup niepotwierdzony) - kopia wyparta (A)
    ZOSTAJE jako dowód, a rekoncyliacja (tu z cofnięcia) ją rozpoznaje i sprząta. Falsyfikator:
    kopia znika bezwarunkowo po podmianie."""
    con, p, lid = _baza(tmp_path, "fits")
    przed = p.read_bytes()

    def _pada(*a, **kw):
        raise RuntimeError("baza zajęta")
    monkeypatch.setattr(repo, "confirm_backup_replaced", _pada)
    res = writeback.commit(con, "R", now=NOW)
    monkeypatch.undo()
    assert len(res.applied) == 1, res
    assert any(n.endswith(writeback._KOPIA_SUFFIX) for n in _resztki(tmp_path))
    (b,) = _backupy(con)
    assert b["pending_since"] is not None
    ures = writeback.undo(con, res.commit_id, now=NOW)
    assert len(ures.restored) == 1, ures
    assert p.read_bytes() == przed and _resztki(tmp_path) == []
    con.close()


# ============================================================ Z1/Z12: wersja C (ten sam nagłówek)


def test_c_z_naglowkiem_n_pod_sciezka_nic_nie_kasuje(tmp_path, monkeypatch):
    """Z1: po śmierci (P = N, K = B) trzeci pisarz zmienia dane P przy tym samym nagłówku (C).
    Nagłówek mówi „N”, pełny sha1 - nie: nic nie wraca, nic nie znika, oba pliki zostają, lokacja
    zablokowana, zdarzenie ze ścieżkami. Falsyfikator: rozpoznanie N po nagłówku - B wraca, C ginie."""
    con, p, lid = _baza(tmp_path, "fits")
    cudzy = {}
    _smierc_w_commicie(con, monkeypatch, cudzy=cudzy)
    c = _zmien_cudzo(str(p), "w_miejscu", b"\x66")
    (z,) = _zamiary(con)
    k = z["displaced_path"]
    b_bajty = open(k, "rb").read()
    res = writeback.commit(con, "R", now=NOW)
    assert len(res.blocked) == 1 and "zostają do oka" in res.blocked[0].reason, res
    assert p.read_bytes() == c and open(k, "rb").read() == b_bajty
    assert _zamiary(con)[0]["outcome"] == "kept"
    assert _zdarzenia_kept(con)[0]["paths"] == [str(p), k]
    con.close()


def test_a_pod_kopia_i_c_pod_sciezka_a_zostaje(tmp_path, monkeypatch):
    """Z1: śmierć bez obcego (P = N, K = A), potem trzeci pisarz zmienia dane P (C). K to jedyna kopia
    wersji sprzed zapisu - nie znika, choć rozpoznana jako A; lokacja zablokowana do oka.
    Falsyfikator: K = A kasowana bez względu na P - wersja sprzed zapisu ginie."""
    con, p, lid = _baza(tmp_path, "fits")
    _smierc_w_commicie(con, monkeypatch)
    (z,) = _zamiary(con)
    a_bajty = open(z["displaced_path"], "rb").read()
    c = _zmien_cudzo(str(p), "w_miejscu", b"\x66")
    res = writeback.commit(con, "R", now=NOW)
    assert len(res.blocked) == 1 and "zostają do oka" in res.blocked[0].reason, res
    assert open(z["displaced_path"], "rb").read() == a_bajty and p.read_bytes() == c
    assert _zamiary(con)[0]["outcome"] == "kept"
    con.close()


def test_c_bez_kopii_nie_potwierdza_commitu(tmp_path, monkeypatch):
    """Z12: kopii wypartej brak (sprzątnięta), pod ścieżką C z nagłówkiem N. Dawna reguła (nagłówek
    = `post_hash`) potwierdziłaby commit; pełny sha1 - nie: backup bez dowodu wykonania, wpis nie
    'applied'. Falsyfikator: gałąź „K brak” z rozpoznaniem po nagłówku."""
    con, p, lid = _baza(tmp_path, "fits")
    _smierc_w_commicie(con, monkeypatch)
    (z,) = _zamiary(con)
    os.remove(z["displaced_path"])
    _zmien_cudzo(str(p), "w_miejscu", b"\x66")
    res = writeback.commit(con, "R", now=NOW)
    assert not res.applied, res
    (b,) = _backupy(con)
    assert (b["pending_since"], b["unreplaced_at"]) == (None, NOW)
    assert _zamiary(con)[0]["outcome"] == "kept"
    assert con.execute("SELECT status FROM pending_changes").fetchone()[0] != "applied"
    con.close()


# ============================================================ Z11: rekoncyliacja wznawialna w każdym etapie


def _po_smierci_z_obcym(tmp_path, monkeypatch):
    con, p, lid = _baza(tmp_path, "fits")
    cudzy = {}
    _smierc_w_commicie(con, monkeypatch, cudzy=cudzy)
    return con, p, cudzy


def _konczy_sie_powrotem(con, p, cudzy, tmp_path):
    res = writeback.commit(con, "R", now=NOW)
    assert len(res.blocked) == 1, res
    assert p.read_bytes() == cudzy["bajty"] and _resztki(tmp_path) == []
    assert _zamiary(con)[0]["outcome"] == "returned"


def test_smierc_po_utrwaleniu_b_przed_powrotem(tmp_path, monkeypatch):
    """Faza `returning` utrwalona, powrót nie zaszedł (P = N, K = B, Z brak): wznowienie wykonuje
    powrót. Falsyfikator: faza `returning` bez gałęzi „powrót jeszcze nie zaszedł”."""
    con, p, cudzy = _po_smierci_z_obcym(tmp_path, monkeypatch)
    prawdziwa = repo.mark_intent_returning

    def _f(*a, **kw):
        prawdziwa(*a, **kw)
        raise _Smierc()
    monkeypatch.setattr(repo, "mark_intent_returning", _f)
    with pytest.raises(_Smierc):
        writeback.commit(con, "R", now=NOW)
    monkeypatch.undo()
    assert _zamiary(con)[0]["phase"] == "returning"
    _konczy_sie_powrotem(con, p, cudzy, tmp_path)
    con.close()


def test_smierc_po_powrocie_przed_faza_returned(tmp_path, monkeypatch):
    """Powrót zaszedł (P = B, Z = N, K brak), faza nadal `returning`: wznowienie rozpoznaje Z jako N
    pełnym sha1, utrwala `returned`, sprząta Z. Falsyfikator: nazwa Z losowana przy powrocie
    (nieutrwalona) - wznowienie jej nie zna, Z sierotą."""
    con, p, cudzy = _po_smierci_z_obcym(tmp_path, monkeypatch)
    prawdziwy = writeback._replace_file_w

    def _f(path, zamiennik, kopia):
        prawdziwy(path, zamiennik, kopia)
        raise _Smierc()
    monkeypatch.setattr(writeback, "_replace_file_w", _f)
    with pytest.raises(_Smierc):
        writeback.commit(con, "R", now=NOW)
    monkeypatch.undo()
    (z,) = _zamiary(con)
    assert z["phase"] == "returning" and os.path.exists(z["return_path"])
    _konczy_sie_powrotem(con, p, cudzy, tmp_path)
    con.close()


def test_smierc_po_fazie_returned_przed_sprzataniem(tmp_path, monkeypatch):
    """Faza `returned` utrwalona, Z jeszcze na dysku: wznowienie sprząta Z i zamyka. Falsyfikator:
    faza `returned` bez sprzątania."""
    con, p, cudzy = _po_smierci_z_obcym(tmp_path, monkeypatch)
    prawdziwa = repo.mark_intent_returned

    def _f(*a, **kw):
        prawdziwa(*a, **kw)
        raise _Smierc()
    monkeypatch.setattr(repo, "mark_intent_returned", _f)
    with pytest.raises(_Smierc):
        writeback.commit(con, "R", now=NOW)
    monkeypatch.undo()
    assert _zamiary(con)[0]["phase"] == "returned"
    _konczy_sie_powrotem(con, p, cudzy, tmp_path)
    con.close()


@pytest.mark.parametrize("c_pod_sciezka", [False, True], ids=["B", "C"])
def test_smierc_po_sprzataniu_przed_werdyktem(tmp_path, monkeypatch, c_pod_sciezka):
    """Z11: powrót wykonany, Z już skasowana, proces ginie przed transakcją werdyktu - stan
    `returned`, P = B, Z brak, K brak. Wznowienie zamyka `returned`; gdy w międzyczasie trzeci pisarz
    podstawił pod P wersję C, wynik to `kept` z P nietkniętym (sha1 B utrwalony przed powrotem to
    odróżnia). Falsyfikator: brak `displaced_sha1` - C uznane za B."""
    con, p, cudzy = _po_smierci_z_obcym(tmp_path, monkeypatch)
    prawdziwa = writeback._usun_kopie

    def _f(sciezka):
        uwaga = prawdziwa(sciezka)
        if sciezka.endswith(".zwrot" + writeback._KOPIA_SUFFIX):
            raise _Smierc()
        return uwaga
    monkeypatch.setattr(writeback, "_usun_kopie", _f)
    with pytest.raises(_Smierc):
        writeback.commit(con, "R", now=NOW)
    monkeypatch.undo()
    (z,) = _zamiary(con)
    assert z["phase"] == "returned" and not os.path.exists(z["return_path"])
    if not c_pod_sciezka:
        _konczy_sie_powrotem(con, p, cudzy, tmp_path)
    else:
        c = _zmien_cudzo(str(p), "w_miejscu", b"\x66")
        (b,) = _backupy(con)
        ures = writeback.undo(con, b["commit_id"], now=NOW)        # rekoncyliacja z cofnięcia
        assert not ures.restored, ures
        assert p.read_bytes() == c
        assert _zamiary(con)[0]["outcome"] == "kept"
    con.close()


def test_trzeci_pisarz_w_oknie_powrotu_rekoncyliacji(tmp_path, monkeypatch):
    """Z1 w oknie powrotu rekoncyliacji: tuż przed powrotem trzeci pisarz zmienia P (N → C), więc
    powrót odkłada pod Z wersję C, nie N. Pełny sha1 Z ≠ N: Z zostaje (C nie ginie), P = B, wynik
    `kept`. Falsyfikator: rozpoznanie zwrotnej odciskiem odczytanym z bieżącego pliku tuż przed
    powrotem - C uznane za N i skasowane."""
    con, p, cudzy = _po_smierci_z_obcym(tmp_path, monkeypatch)
    prawdziwy = writeback._replace_file_w
    trzeci = {}

    def _f(path, zamiennik, kopia):
        trzeci["bajty"] = _zmien_cudzo(path, "w_miejscu", b"\x77")
        prawdziwy(path, zamiennik, kopia)
    monkeypatch.setattr(writeback, "_replace_file_w", _f)
    res = writeback.commit(con, "R", now=NOW)
    monkeypatch.undo()
    assert len(res.blocked) == 1 and "zostają do oka" in res.blocked[0].reason, res
    (z,) = _zamiary(con)
    assert z["outcome"] == "kept" and open(z["return_path"], "rb").read() == trzeci["bajty"]
    assert p.read_bytes() == cudzy["bajty"]
    con.close()


# ============================================================ poprawki bramki bloku B (C1..C8)


def _frame(con, p):
    return con.execute("SELECT frame_id FROM location WHERE path = ?", (str(p),)).fetchone()[0]


def test_skan_nie_potwierdza_proby_z_nierozstrzygnieta_podmiana(tmp_path, monkeypatch):
    """C1: podmiana wyparła B, a odczyt kopii przy rewalidacji padł (OSError) - wpisy 'failed',
    backup niepotwierdzony, zamiar otwarty. Skan widzi pod ścieżką nagłówek N, ale próby NIE
    rozlicza (dawniej 'applied' i zgaszony nagrobek); rozstrzyga automat - B wraca.
    Falsyfikator: `confirm_failed_commit_by_scan` bez wykluczenia nierozstrzygniętej podmiany."""
    from horreum import scan
    con, p, lid = _baza(tmp_path, "fits")
    cudzy = {}
    prawdziwy = writeback._replace_file_w

    def _replace(path, tmp, kopia):
        if "bajty" not in cudzy:
            cudzy["bajty"] = _zmien_cudzo(path, "podmiana_pliku", b"\x55")
        prawdziwy(path, tmp, kopia)

    def _odczyt_pada(*a, **kw):
        raise OSError(5, "zerwany udział")
    monkeypatch.setattr(writeback, "_replace_file_w", _replace)
    monkeypatch.setattr(writeback, "_rozjazd_odcisku", _odczyt_pada)
    res = writeback.commit(con, "R", now=NOW)
    monkeypatch.undo()
    assert len(res.failed) == 1, res
    scan.ingest_record(con, scan.scan_file(str(p)), volume="V", now=NOW, summary=scan.ScanSummary())
    assert con.execute("SELECT status FROM pending_changes").fetchone()[0] == "failed"
    assert _zamiary(con)[0]["phase"] == "prepared"
    writeback.commit(con, "R", now=NOW)                       # nic do zapisu - ale rekoncyliacja
    (b,) = _backupy(con)
    ures = writeback.undo(con, b["commit_id"], now=NOW)       # rekoncyliacja z cofnięcia
    assert not ures.restored, ures
    assert p.read_bytes() == cudzy["bajty"] and _zamiary(con)[0]["outcome"] == "returned"
    con.close()


def test_odmowa_strazy_zamyka_zamiar(tmp_path, monkeypatch):
    """C1: straż odbiła podmianę (plik nietknięty) - backup bez podmiany i zamiar zamknięty
    `not_replaced` w tej samej transakcji. Falsyfikator: `mark_backup_unreplaced` bez zamknięcia
    zamiaru - zostaje otwarty, choć nic nie jest nierozstrzygnięte."""
    con, p, lid = _baza(tmp_path, "fits")

    def _straz(con_, *, location_id, generation):
        raise repo.InplaceConflict({"id": 99, "kind": "commit", "phase": "synced",
                                    "commit_id": None})
    monkeypatch.setattr(repo, "guard_file_replace", _straz)
    res = writeback.commit(con, "R", now=NOW)
    monkeypatch.undo()
    assert len(res.blocked) == 1, res
    assert [(z["phase"], z["outcome"]) for z in _zamiary(con)] == [("closed", "not_replaced")]
    con.close()


def test_sam_tymczasowy_zostaje_jako_material_odzysku(tmp_path, monkeypatch):
    """C2: stan P = ∅, K = ∅, Z = ∅, T = N - plik tymczasowy jest ostatnią pełną kopią danych.
    Rozpoznanie jako N nie znaczy „zbędny”: T zostaje, lokacja zablokowana z powodem wskazującym T,
    stan widoczny w Porządkach. Falsyfikator: sprzątanie T bez warunku „pod ścieżką A albo N”."""
    from horreum.gui import queries
    con, p, lid = _baza(tmp_path, "fits")

    def _f(*a, **kw):
        raise _Smierc()
    monkeypatch.setattr(writeback, "_podmien", _f)
    monkeypatch.setattr(writeback, "_sprzatnij_tmp", lambda *a, **kw: None)
    with pytest.raises(_Smierc):
        writeback.commit(con, "R", now=NOW)
    monkeypatch.undo()
    (z,) = _zamiary(con)
    fid = _frame(con, p)
    p.unlink()
    res = writeback.commit(con, "R", now=NOW)
    assert os.path.exists(z["prepared_path"]), res
    assert len(res.blocked) == 1 and z["prepared_path"] in res.blocked[0].reason, res
    assert _zamiary(con)[0]["outcome"] == "kept"
    assert queries.kept_copy_frame_ids(con) == {fid}
    assert queries.tasks_state(con)["kept_copy_frames"] == 1
    con.close()


def test_cudza_wersja_rowna_naszej_nie_potwierdza_commitu(tmp_path, monkeypatch):
    """C3 (kontrprzykład astry): inny pisarz zrobił DOKŁADNIE tę samą zmianę (B bajtowo = N), nasza
    podmiana ją wyparła, rewalidacja oddaje B, proces ginie po usunięciu kopii zwrotnej. Faza powrotu
    utrwalona w osobnej transakcji przed mutacją mówi, że pod ścieżką stoi B - commit NIE jest
    potwierdzony, a cofnięcie nie przywraca A ponad cudzą zmianę. Falsyfikator: powrót w biegu
    zapisu z fazą w transakcji straży (wycofanej) - wznowienie widzi P = N i potwierdza commit."""
    import shutil
    con, p, lid = _baza(tmp_path, "fits")
    przed = p.read_bytes()
    prawdziwy = writeback._replace_file_w
    cudzy = {}

    def _replace(path, tmp, kopia):
        if "bajty" not in cudzy:
            shutil.copyfile(tmp, path + ".obcy")               # ta sama zmiana, inny pisarz
            os.replace(path + ".obcy", path)
            cudzy["bajty"] = open(path, "rb").read()
        prawdziwy(path, tmp, kopia)
    usun = writeback._usun_kopie

    def _usun(sciezka):
        uwaga = usun(sciezka)
        if sciezka.endswith(".zwrot" + writeback._KOPIA_SUFFIX):
            raise _Smierc()
        return uwaga
    monkeypatch.setattr(writeback, "_replace_file_w", _replace)
    monkeypatch.setattr(writeback, "_usun_kopie", _usun)
    with pytest.raises(_Smierc):
        writeback.commit(con, "R", now=NOW)
    monkeypatch.undo()
    (b,) = _backupy(con)
    ures = writeback.undo(con, b["commit_id"], now=NOW)
    assert not ures.restored, ures
    assert p.read_bytes() == cudzy["bajty"] != przed
    (b,) = _backupy(con)
    assert b["unreplaced_at"] == NOW and _zamiary(con)[0]["outcome"] == "returned"
    assert con.execute("SELECT status FROM pending_changes").fetchone()[0] != "applied"
    con.close()


def test_c_pod_pusta_sciezka_po_1177_powrotu_zachowuje_wszystko(tmp_path, monkeypatch):
    """C4: powrót przerwany w stanie 1177 (P = ∅, K = B, Z = N, faza `returning`), a przed
    wznowieniem trzeci pisarz tworzy C pod ścieżką. Automat nie ogłasza powrotu: wszystkie pliki
    zostają, zdarzenie i stan wymieniają K i Z, lokacja zablokowana. Falsyfikator: przejście do
    `returned` bez sprawdzenia K - Z skasowana, B pod K bez śladu."""
    from horreum.gui import queries
    con, p, cudzy = _po_smierci_z_obcym(tmp_path, monkeypatch)
    fid = _frame(con, p)

    def _f(path, zamiennik, kopia):
        os.rename(path, kopia)                                  # 1177 powrotu: P pod Z, K stoi
        raise _Smierc()
    monkeypatch.setattr(writeback, "_replace_file_w", _f)
    with pytest.raises(_Smierc):
        writeback.commit(con, "R", now=NOW)
    monkeypatch.undo()
    p.write_bytes(b"C" * 2880)
    res = writeback.commit(con, "R", now=NOW)
    (z,) = _zamiary(con)
    assert len(res.blocked) == 1 and "zostają do oka" in res.blocked[0].reason, res
    assert z["outcome"] == "kept"
    assert os.path.exists(z["displaced_path"]) and os.path.exists(z["return_path"])
    assert set(json.loads(z["kept_paths"])) == {z["displaced_path"], z["return_path"]}
    assert queries.kept_copy_frame_ids(con) == {fid}
    con.close()


def test_kopia_a_znika_dopiero_po_potwierdzeniu_pod_blokada(tmp_path, monkeypatch):
    """C5: K = A, P = N bez blokady, ale tuż przed blokadą trzeci pisarz zmienia P (C). Potwierdzenie
    pod blokadą odmawia, a K (jedyna kopia wersji sprzed zapisu) zostaje. Falsyfikator: K kasowana
    przed potwierdzeniem pod blokadą."""
    con, p, lid = _baza(tmp_path, "fits")
    _smierc_w_commicie(con, monkeypatch)
    (z,) = _zamiary(con)
    prawdziwa = writeback._exclusive
    stan = {}

    def _blokada(path):
        if "c" not in stan:
            stan["c"] = _zmien_cudzo(str(p), "w_miejscu", b"\x66")
        return prawdziwa(path)
    monkeypatch.setattr(writeback, "_exclusive", _blokada)
    res = writeback.commit(con, "R", now=NOW)
    monkeypatch.undo()
    assert len(res.blocked) == 1 and "zmienił się w trakcie rekoncyliacji" in res.blocked[0].reason
    assert os.path.exists(z["displaced_path"]) and p.read_bytes() == stan["c"]
    con.close()


def test_cofniecie_bez_zamiaru_mowi_prawde_o_kopii(tmp_path, monkeypatch):
    """C6: cofnięcie (bez zamiaru podmiany), zamknięcie straży pada po podmianie - kopia zostaje,
    a zdanie NIE obiecuje rekoncyliacji, której nie będzie: mówi, gdzie leży kopia i że można ją
    skasować ręcznie. Falsyfikator: wspólne zdanie z drogą z zamiarem."""
    con, p, lid = _baza(tmp_path, "fits")
    res = writeback.commit(con, "R", now=NOW)
    prawdziwa = repo.guard_file_replace

    class _Straz:
        def __init__(self, *a, **kw):
            self._s = prawdziwa(*a, **kw)

        def __enter__(self):
            return self._s.__enter__()

        def __exit__(self, *exc):
            self._s.__exit__(*exc)
            if exc[0] is None:
                raise RuntimeError("zamknięcie transakcji padło")
            return False
    monkeypatch.setattr(repo, "guard_file_replace", _Straz)
    ures = writeback.undo(con, res.commit_id, now=NOW)
    monkeypatch.undo()
    (r,) = ures.restored
    assert "skasować ręcznie" in r.reason and "rekoncyliacji" not in r.reason, r
    assert any(n.endswith(writeback._KOPIA_SUFFIX) for n in _resztki(tmp_path))
    con.close()


def test_po_powrocie_baza_opisuje_wrocona_wersje(tmp_path, monkeypatch):
    """C7: po śmierci (P = N, K = B) skan przyjął naszą wersję do bazy; automat wraca B - baza ma
    opisywać B (nagłówek), a nie N. Falsyfikator: brak odświeżenia po powrocie - baza opisuje N,
    którego na dysku już nie ma."""
    from horreum import scan
    con, p, cudzy = _po_smierci_z_obcym(tmp_path, monkeypatch)
    scan.ingest_record(con, scan.scan_file(str(p)), volume="V", now=NOW, summary=scan.ScanSummary())
    writeback.commit(con, "R", now=NOW)
    assert p.read_bytes() == cudzy["bajty"]
    lok = con.execute("SELECT header_hash, mtime FROM location WHERE path = ?", (str(p),)).fetchone()
    assert lok["header_hash"] == scan.scan_file(str(p)).header_hash
    assert lok["mtime"] is not None
    con.close()
