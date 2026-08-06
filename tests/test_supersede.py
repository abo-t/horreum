"""R4 — zastąpienie tożsamości po podmianie pliku (`frame.superseded_by`, #DR2).

Cztery strażniki passu (replay chronologiczny · ostatni event per klatka · żywotność · odmowa
cyklu), klinga i jej idempotencja, gaszenie ogniwa przy powrocie treści oraz trzej konsumenci
kolumny. Bez plików na dysku — wejściem passu jest DZIENNIK bazy, nie drzewo.
"""
import pytest

from horreum import audit, db, repo, supersede
from horreum.gui import queries

NOW = "2026-08-06T10:00:00+00:00"


def _baza():
    return db.open_db(":memory:")


def _klatka(con, sha, *, kind="light", now=NOW):
    fid, _ = repo.upsert_frame(con, sha1_data=sha, kind=kind, filetype="raw",
                               camera_id=None, now=now)
    return fid


def _kopia(con, frame_id, path, *, now=NOW):
    lid, _ = repo.add_location(con, frame_id=frame_id, volume="TESTVOL", path=path, now=now)
    return lid


def _podmiana(con, location_id, frame_after, *, now=NOW):
    """Skan przepina lokację na nową tożsamość — to jedyne źródło zdarzeń, które czyta pass."""
    return repo.rebind_location(con, location_id=location_id, frame_after=frame_after, now=now)


# ---------------------------------------------------------------- klinga

def test_klinga_oznacza_sierote_i_jest_idempotentna():
    con = _baza()
    a, b = _klatka(con, "aaa"), _klatka(con, "bbb")
    lid = _kopia(con, a, r"R:\X\plik.dng")
    _podmiana(con, lid, b)

    assert repo.mark_superseded(con, frame_id=a, superseded_by=b, now=NOW) is True
    assert con.execute("SELECT superseded_by FROM frame WHERE id=?", (a,)).fetchone()[0] == b
    # Powtórzenie: bez UPDATE i BEZ eventu (append-only nie ma prawa puchnąć od przebiegów).
    assert repo.mark_superseded(con, frame_id=a, superseded_by=b, now=NOW) is False
    assert con.execute(
        "SELECT count(*) FROM event WHERE verb='frame.superseded'").fetchone()[0] == 1


def test_klinga_odmawia_klatce_z_obecna_kopia():
    """STRAŻNIK ŻYWOTNOŚCI: `frame` ma 1:N `location` — podmiana jednej kopii nie czyni drugiej
    duchem. To jest ten guard, którego brak kazałby bazie zapomnieć o godzinach klatki ŻYWEJ."""
    con = _baza()
    a, b = _klatka(con, "aaa"), _klatka(con, "bbb")
    lid = _kopia(con, a, r"R:\X\plik.dng")
    _kopia(con, a, r"R:\Y\ten_sam_plik.dng")        # druga ścieżka, ta sama treść
    _podmiana(con, lid, b)

    assert repo.mark_superseded(con, frame_id=a, superseded_by=b, now=NOW) is False
    assert con.execute("SELECT superseded_by FROM frame WHERE id=?", (a,)).fetchone()[0] is None


def test_klinga_odmawia_samozastapienia_i_nieistniejacej():
    con = _baza()
    a = _klatka(con, "aaa")
    with pytest.raises(ValueError):
        repo.mark_superseded(con, frame_id=a, superseded_by=a, now=NOW)
    with pytest.raises(ValueError):
        repo.mark_superseded(con, frame_id=a, superseded_by=99999, now=NOW)


def test_klinga_nie_nadpisuje_zajetego_ogniwa():
    """EXPECT: druga podmiana dokłada ogniwo NA NASTĘPCZYNI (A→B, potem B→C). Żądanie zmiany
    A→B na A→C znaczy pomyłkę wołającego, a nadpisanie zgubiłoby wersję środkową."""
    con = _baza()
    a, b, c = _klatka(con, "aaa"), _klatka(con, "bbb"), _klatka(con, "ccc")
    lid = _kopia(con, a, r"R:\X\plik.dng")
    _podmiana(con, lid, b)
    repo.mark_superseded(con, frame_id=a, superseded_by=b, now=NOW)
    with pytest.raises(ValueError):
        repo.mark_superseded(con, frame_id=a, superseded_by=c, now=NOW)


def test_ddl_odrzuca_samozastapienie_goly_sqlite():
    """Baza jest OSTATNIĄ bramką: CHECK z 0014 czerwieni nawet zapis z pominięciem klingi."""
    con = _baza()
    a = _klatka(con, "aaa")
    with pytest.raises(Exception):
        con.execute("UPDATE frame SET superseded_by = id WHERE id = ?", (a,))


# ---------------------------------------------------------------- pass

def test_pass_dry_nie_dotyka_bazy_ale_liczy_zakres():
    con = _baza()
    a, b = _klatka(con, "aaa"), _klatka(con, "bbb")
    lid = _kopia(con, a, r"R:\X\plik.dng")
    _podmiana(con, lid, b)

    s = supersede.backfill(con, now=NOW)                  # DRY domyślnie
    assert (s.events, s.proposed, s.marked) == (1, 1, 1)
    assert con.execute("SELECT superseded_by FROM frame WHERE id=?", (a,)).fetchone()[0] is None
    assert con.execute(
        "SELECT count(*) FROM event WHERE verb='frame.superseded'").fetchone()[0] == 0


def test_pass_dry_nie_przypisuje_sobie_zrobionej_roboty():
    """DRY na bazie JUŻ oznaczonej melduje `already`, nie `marked` — inaczej raport przed
    przebiegiem na żywej bazie zawyżałby zakres o wszystko, co zrobiły poprzednie przebiegi."""
    con = _baza()
    a, b = _klatka(con, "aaa"), _klatka(con, "bbb")
    lid = _kopia(con, a, r"R:\X\plik.dng")
    _podmiana(con, lid, b)
    supersede.backfill(con, now=NOW, apply=True)

    s = supersede.backfill(con, now=NOW)                  # DRY po zapisie
    assert (s.marked, s.already) == (0, 1)


def test_pass_apply_oznacza_i_jest_idempotentny():
    con = _baza()
    a, b = _klatka(con, "aaa"), _klatka(con, "bbb")
    lid = _kopia(con, a, r"R:\X\plik.dng")
    _podmiana(con, lid, b)

    s = supersede.backfill(con, now=NOW, apply=True)
    assert (s.marked, s.already) == (1, 0)
    assert con.execute("SELECT superseded_by FROM frame WHERE id=?", (a,)).fetchone()[0] == b

    s2 = supersede.backfill(con, now=NOW, apply=True)
    assert (s2.marked, s2.already) == (0, 1)
    assert con.execute(
        "SELECT count(*) FROM event WHERE verb='frame.superseded'").fetchone()[0] == 1


def test_pass_lancuch_zostaje_lancuchem():
    """A→B→C to DWA ogniwa, nigdy skrót A→C: skrót zgubiłby wersję środkową (D-DR-4)."""
    con = _baza()
    a, b, c = _klatka(con, "aaa"), _klatka(con, "bbb"), _klatka(con, "ccc")
    lid = _kopia(con, a, r"R:\X\plik.dng")
    _podmiana(con, lid, b, now="2026-08-06T10:00:00+00:00")
    _podmiana(con, lid, c, now="2026-08-06T11:00:00+00:00")

    supersede.backfill(con, now=NOW, apply=True)
    assert con.execute("SELECT superseded_by FROM frame WHERE id=?", (a,)).fetchone()[0] == b
    assert con.execute("SELECT superseded_by FROM frame WHERE id=?", (b,)).fetchone()[0] == c


def test_pass_ostatni_event_per_klatka_wygrywa():
    """STRAŻNIK 2: ta sama tożsamość bywa `frame_before` więcej niż raz (dwie ścieżki, kolejne
    edycje). Liczy się OSTATNIA obserwacja — wcześniejsze opisują stan, który już minął."""
    con = _baza()
    a, b, c = _klatka(con, "aaa"), _klatka(con, "bbb"), _klatka(con, "ccc")
    lid = _kopia(con, a, r"R:\X\plik.dng")
    _podmiana(con, lid, b, now="2026-08-06T10:00:00+00:00")
    _podmiana(con, lid, a, now="2026-08-06T11:00:00+00:00")     # treść wróciła
    _podmiana(con, lid, c, now="2026-08-06T12:00:00+00:00")     # i znów się zmieniła

    s = supersede.backfill(con, now=NOW, apply=True)
    # Ostatnie zdanie dziennika o `a` to `a → c`; ogniwo `a → b` jest HISTORIĄ, nie stanem.
    assert con.execute("SELECT superseded_by FROM frame WHERE id=?", (a,)).fetchone()[0] == c
    # `b` też został zastąpiony (przez `a`), więc oznaczone są DWIE klatki — i to jest poprawne:
    # pod ścieżką leży dziś `c`, a łańcuch `b → a → c` prowadzi do niej z każdej strony.
    # Cyklu tu NIE MA: powrót `b → a` przykryła późniejsza podmiana `a → c`.
    assert s.marked == 2 and s.cycles == 0
    assert con.execute("SELECT superseded_by FROM frame WHERE id=?", (b,)).fetchone()[0] == a
    # INWARIANT ŁAŃCUCHA: z każdej zastąpionej klatki dochodzi się do klatki ŻYWEJ.
    kolejna, kroki = b, 0
    while kolejna is not None and kroki < 10:
        kolejna, kroki = con.execute(
            "SELECT superseded_by FROM frame WHERE id=?", (kolejna,)).fetchone()[0], kroki + 1
    assert kroki == 3          # b → a → c → (koniec)


def test_pass_odmawia_cyklu_obu_stronom():
    """STRAŻNIK 4: `A→B→A` (edycja i cofnięcie edycji) — żadna strona nie jest zastąpiona.
    Pass odmawia OBU zamiast wybierać arbitralnie; rozstrzyga odczyt z dysku, nie dziennik."""
    con = _baza()
    a, b = _klatka(con, "aaa"), _klatka(con, "bbb")
    la = _kopia(con, a, r"R:\X\plik.dng")
    lb = _kopia(con, b, r"R:\Y\inny.dng")
    _podmiana(con, la, b, now="2026-08-06T10:00:00+00:00")
    _podmiana(con, lb, a, now="2026-08-06T11:00:00+00:00")

    s = supersede.backfill(con, now=NOW, apply=True)
    assert s.cycles == 2 and s.marked == 0
    assert con.execute(
        "SELECT count(*) FROM frame WHERE superseded_by IS NOT NULL").fetchone()[0] == 0


def test_pass_partycja_sie_domyka():
    """Kubełek, który wypadnie z sumy, znaczy odmowę BEZ POWODU — ta sama lekcja, co partycja
    128 stosów w rodowodzie."""
    con = _baza()
    a, b, c, d = (_klatka(con, s) for s in ("aaa", "bbb", "ccc", "ddd"))
    la = _kopia(con, a, r"R:\X\1.dng")
    lc = _kopia(con, c, r"R:\Y\2.dng")
    _kopia(con, c, r"R:\Z\2_kopia.dng")            # `c` zostaje żywa pod drugą ścieżką
    _podmiana(con, la, b)
    _podmiana(con, lc, d)

    s = supersede.backfill(con, now=NOW, apply=True)
    assert s.proposed == s.marked + s.already + s.alive + s.cycles + s.conflicts + s.missing
    assert (s.marked, s.alive) == (1, 1)


# ---------------------------------------------------------------- powrót treści (skan gasi)

def test_powrot_tresci_gasi_ogniwo():
    """G1-8: cykl `A→B→A` gasi `superseded_by`. Dowodem jest ODCZYT Z DYSKU (gałąź podmiany
    w skanie), nie upływ czasu i nie pass — dziennik mówi, co się działo, dysk mówi, co JEST."""
    con = _baza()
    a, b = _klatka(con, "aaa"), _klatka(con, "bbb")
    lid = _kopia(con, a, r"R:\X\plik.dng")
    _podmiana(con, lid, b)
    repo.mark_superseded(con, frame_id=a, superseded_by=b, now=NOW)

    # treść wraca pod tę ścieżkę: skan przepina lokację z powrotem na `a` i gasi ogniwo
    _podmiana(con, lid, a)
    assert repo.clear_superseded(con, frame_id=a, now=NOW) is True
    assert con.execute("SELECT superseded_by FROM frame WHERE id=?", (a,)).fetchone()[0] is None
    assert repo.clear_superseded(con, frame_id=a, now=NOW) is False       # idempotencja


# ---------------------------------------------------------------- konsumenci kolumny (W9)

def test_godziny_nie_licza_ducha_dwa_razy():
    """`object_exposure` obejmuje klatki `present=0` (parytet z facetem) — i to właśnie tą furtką
    duch wchodziłby do rachunku, bo sierota nie ma obecnej kopii."""
    con = _baza()
    oid = repo.upsert_object(con, canon="IC443", catalog="IC", kind=None, now=NOW)[0]
    a, b = _klatka(con, "aaa"), _klatka(con, "bbb")
    lid = _kopia(con, a, r"R:\X\plik.dng")
    for fid in (a, b):
        repo.record_header(con, frame_id=fid, raw_json="{}", exptime=91.0,
                           date_obs="2019-01-10T21:42:10", now=NOW)
        repo.assign_object(con, frame_id=fid, object_id=oid, object_source="user", now=NOW)
    _podmiana(con, lid, b)

    przed = queries.object_exposure(con, [a, b])
    assert przed[0]["secs"] == pytest.approx(182.0)       # duch dolicza swoje 91 s
    repo.mark_superseded(con, frame_id=a, superseded_by=b, now=NOW)
    po = queries.object_exposure(con, [a, b])
    assert po[0]["secs"] == pytest.approx(91.0)           # ta sama ekspozycja liczona RAZ


def test_inwarianty_audytu_lapia_rozjazd_ze_swiatem():
    con = _baza()
    a, b = _klatka(con, "aaa"), _klatka(con, "bbb")
    lid = _kopia(con, a, r"R:\X\plik.dng")
    _kopia(con, b, r"R:\Y\nowy.dng")
    _podmiana(con, lid, b)
    repo.mark_superseded(con, frame_id=a, superseded_by=b, now=NOW)
    assert audit.supersede_invariants(con) == {"zastapiona_z_obecna_kopia": 0,
                                               "ogniwo_do_zastapionej": 0}

    # kopia `a` odżywa inną drogą niż gałąź podmiany — oznaczenie przestało być prawdą
    repo.add_location(con, frame_id=a, volume="TESTVOL", path=r"R:\Z\wrocil.dng", now=NOW)
    assert audit.supersede_invariants(con)["zastapiona_z_obecna_kopia"] == 1


def test_sieroty_nierozstrzygniete_to_predykat_bramki():
    con = _baza()
    a, b = _klatka(con, "aaa"), _klatka(con, "bbb")
    lid = _kopia(con, a, r"R:\X\plik.dng")
    _podmiana(con, lid, b)

    assert supersede.orphans(con) == [a]                  # sierota bez ogniwa = otwarte pytanie
    repo.mark_superseded(con, frame_id=a, superseded_by=b, now=NOW)
    assert supersede.orphans(con) == []                   # sierota ZOSTAJE, ale jest wyjaśniona


# ---------------------------------------------------------------- przeniesienie faktów (D-DR-4)

def _z_obiektem(con, fid, oid, source):
    repo.assign_object(con, frame_id=fid, object_id=oid, object_source=source, now=NOW)


def test_przenosi_fakt_reki_na_nastepczynie():
    """Werdykt ręki nie ginie przy podmianie pliku — to jest cała racja bytu R4."""
    con = _baza()
    oid = repo.upsert_object(con, canon="IC443", catalog="IC", kind=None, now=NOW)[0]
    a, b = _klatka(con, "aaa"), _klatka(con, "bbb")
    lid = _kopia(con, a, r"R:\X\plik.dng")
    _z_obiektem(con, a, oid, "user")
    _podmiana(con, lid, b)
    repo.mark_superseded(con, frame_id=a, superseded_by=b, now=NOW)

    assert supersede.pending_transfer(con) == [(a, b, "user")]
    wynik = repo.transfer_human_facts(con, frame_id=a, now=NOW)
    assert wynik.object_moved is True and wynik.skipped == ""
    assert con.execute(
        "SELECT object_id, object_source FROM frame WHERE id=?", (b,)).fetchone()[:] == (oid, "user")
    # stara klatka ZOSTAJE nietknięta (append-only) — z rachunku godzin wypada przez `superseded_by`
    assert con.execute("SELECT object_id FROM frame WHERE id=?", (a,)).fetchone()[0] == oid
    assert supersede.pending_transfer(con) == []          # kubełek się domknął


def test_przenosi_nagrobek_bez_psucia_parytetu():
    """NAGROBEK to też werdykt („ta klatka obiektu NIE ma"). Emituje `object.cleared` BEZ
    `object.assigned` — `object_id` zostaje NULL, więc parytet §5.9 nie ma prawa drgnąć."""
    con = _baza()
    oid = repo.upsert_object(con, canon="IC443", catalog="IC", kind=None, now=NOW)[0]
    a, b = _klatka(con, "aaa"), _klatka(con, "bbb")
    lid = _kopia(con, a, r"R:\X\plik.dng")
    _z_obiektem(con, a, oid, "path")
    repo.clear_object_assignment(con, frame_ids=[a], now=NOW)      # ręka zdejmuje → nagrobek
    _podmiana(con, lid, b)
    repo.mark_superseded(con, frame_id=a, superseded_by=b, now=NOW)

    assert repo.transfer_human_facts(con, frame_id=a, now=NOW).object_moved is True
    assert con.execute(
        "SELECT object_id, object_source FROM frame WHERE id=?", (b,)).fetchone()[:] \
        == (None, "user_cleared")
    stan = con.execute("SELECT count(*) FROM frame WHERE object_id IS NOT NULL").fetchone()[0]
    przypisania = con.execute(
        "SELECT count(*) FROM event WHERE verb='object.assigned'").fetchone()[0]
    odpiecia = con.execute(
        "SELECT count(*) FROM event WHERE verb='object.unassigned'").fetchone()[0]
    assert stan == przypisania - odpiecia                 # parytet §5.9


def test_nie_nadpisuje_nastepczyni_ktora_przemowila_sama():
    """Klatka z własnym źródłem (nagłówek/xref/region/drugi gest) nie dostaje cudzego werdyktu."""
    con = _baza()
    oid = repo.upsert_object(con, canon="IC443", catalog="IC", kind=None, now=NOW)[0]
    inny = repo.upsert_object(con, canon="M42", catalog="M", kind=None, now=NOW)[0]
    a, b = _klatka(con, "aaa"), _klatka(con, "bbb")
    lid = _kopia(con, a, r"R:\X\plik.dng")
    _z_obiektem(con, a, oid, "user")
    _podmiana(con, lid, b)
    repo.mark_superseded(con, frame_id=a, superseded_by=b, now=NOW)
    _z_obiektem(con, b, inny, "header")                   # następczyni ma zeznanie z pliku

    assert supersede.pending_transfer(con) == []          # w kolejce jej nie ma
    wynik = repo.transfer_human_facts(con, frame_id=a, now=NOW)
    assert wynik.object_moved is False and wynik.skipped == "nastepczyni ma wlasne zrodlo"
    assert con.execute("SELECT object_id FROM frame WHERE id=?", (b,)).fetchone()[0] == inny


def test_bez_faktow_reki_nie_ma_czego_przenosic():
    """Rozpoznanie z nagłówka wraca samo przy najbliższym przebiegu — przeniesione ręcznie byłoby
    DRUGĄ derywacją tego samego faktu."""
    con = _baza()
    oid = repo.upsert_object(con, canon="IC443", catalog="IC", kind=None, now=NOW)[0]
    a, b = _klatka(con, "aaa"), _klatka(con, "bbb")
    lid = _kopia(con, a, r"R:\X\plik.dng")
    _z_obiektem(con, a, oid, "header")
    _podmiana(con, lid, b)
    repo.mark_superseded(con, frame_id=a, superseded_by=b, now=NOW)

    assert repo.transfer_human_facts(con, frame_id=a, now=NOW).skipped == "brak faktow czlowieka"
    assert con.execute("SELECT object_id FROM frame WHERE id=?", (b,)).fetchone()[0] is None


def test_przeniesienie_jest_idempotentne_i_wymaga_ogniwa():
    con = _baza()
    oid = repo.upsert_object(con, canon="IC443", catalog="IC", kind=None, now=NOW)[0]
    a, b = _klatka(con, "aaa"), _klatka(con, "bbb")
    lid = _kopia(con, a, r"R:\X\plik.dng")
    _z_obiektem(con, a, oid, "user")

    with pytest.raises(ValueError):                       # klatka nie jest zastąpiona
        repo.transfer_human_facts(con, frame_id=a, now=NOW)

    _podmiana(con, lid, b)
    repo.mark_superseded(con, frame_id=a, superseded_by=b, now=NOW)
    assert repo.transfer_human_facts(con, frame_id=a, now=NOW).object_moved is True
    powtorka = repo.transfer_human_facts(con, frame_id=a, now=NOW)
    assert powtorka.object_moved is False and powtorka.skipped == "nastepczyni ma wlasne zrodlo"
    assert con.execute(
        "SELECT count(*) FROM event WHERE verb='object.assigned'").fetchone()[0] == 2  # gest + przeniesienie
