r"""OBIEKT STOSU WOBEC OBIEKTU WYDANIA (AR-103) - rdzeń: porównanie i klinga jawnego nadpisania ręką.

Stos dostaje obiekt po Dostawie z nagłówka (`OBJECT` przepisany przez WBPP z lightów), a żniwa wiedzą,
dla jakiego obiektu Horreum wydało lighty. Porównanie (`stacks.release_object_check`) niczego nie
zapisuje; zapis robi wyłącznie gest ręki (`repo.user_override_stack_object`) - z CAS na stanie, który
człowiek widział, idempotentny i odwracalny (`repo.restore_stack_object`). Ochrona `user_assign_object`
(nie zamaluje faktu z nagłówka) zostaje nietknięta - ta klinga jest osobna i działa tylko na stosie.

Testy pytają o stan ORAZ o dziennik: drugi gest i dryf to ZERO eventów, a bilans osi `§5.9`
(`audit.entity_event_parity`) domyka się po geście i po cofnięciu.
"""
import pytest

from horreum import audit, db, repo, resolver, stacks

NOW = "2026-10-11T12:00:00+00:00"


def _baza(raw_stosu="IC 1795"):
    """Stos (`master_light`) z nagłówkiem `OBJECT=raw_stosu` (id 1), light (id 2), obiekt wydania NGC7000.
    Obiekt stosu stawia resolver - zwykła droga, z eventami, więc bilans §5.9 jest od początku zielony."""
    con = db.connect(":memory:")
    db.migrate(con)
    for fid, kind, raw in ((1, "master_light", raw_stosu), (2, "light", "IC 1795")):
        con.execute("INSERT INTO frame(id, kind, filetype, sha1_data, first_seen_at) VALUES (?, ?, 'xisf', ?, ?)",
                    (fid, kind, f"sha{fid}", NOW))
        con.execute("INSERT INTO header(frame_id, object_raw, raw_json) VALUES (?, ?, '{}')", (fid, raw))
    con.commit()
    resolver.run_resolver(con, now=NOW)
    repo.upsert_object(con, canon="NGC7000", catalog="NGC", kind="deep_sky", now=NOW)
    return con


def _stan(con, fid=1):
    r = con.execute("SELECT object_id, object_source, object_cleared_id FROM frame WHERE id = ?",
                    (fid,)).fetchone()
    return r["object_id"], r["object_source"], r["object_cleared_id"]


def _oid(con, canon):
    return con.execute("SELECT id FROM object WHERE canon = ?", (canon,)).fetchone()[0]


def _ev(con):
    return con.execute("SELECT count(*) FROM event").fetchone()[0]


def _bilans_osi(con):
    [p] = [p for p in audit.entity_event_parity(con) if p.name == "frame.object_id"]
    return p.ok


def _nadpisz(con, check, **kw):
    return repo.user_override_stack_object(
        con, frame_id=check["frame_id"], object_id=check["release_object_id"],
        expected_object_id=check["stack_object_id"], expected_source=check["stack_source"],
        expected_cleared_id=check["stack_cleared_id"], now=NOW, **kw)


# ═══════════════════════════════════════════ porównanie (read-only)


def test_porownanie_zgodny_inny_brak_i_milczenie_bez_celu():
    con = _baza()
    ic, ngc = _oid(con, "IC1795"), _oid(con, "NGC7000")
    assert _stan(con)[:2] == (ic, "header")
    przed = _ev(con)
    inny = stacks.release_object_check(con, master_sha1_data="sha1", object_canon="NGC7000")
    assert inny == {"verdict": "inny", "frame_id": 1, "stack_object_id": ic, "stack_source": "header",
                    "stack_cleared_id": None, "stack_canon": "IC1795", "release_object_id": ngc,
                    "release_canon": "NGC7000"}
    assert stacks.release_object_check(con, master_sha1_data="sha1", object_canon="IC1795")["verdict"] == "zgodny"
    # stos bez obiektu (nazwa potoczna bez aliasu) i nagrobek ręki - oba „brak”
    con.execute("UPDATE frame SET object_id = NULL, object_source = NULL WHERE id = 1")
    assert stacks.release_object_check(con, master_sha1_data="sha1", object_canon="NGC7000")["verdict"] == "brak"
    con.execute("UPDATE frame SET object_source = 'user_cleared', object_cleared_id = ? WHERE id = 1", (ic,))
    nagrobek = stacks.release_object_check(con, master_sha1_data="sha1", object_canon="NGC7000")
    assert (nagrobek["verdict"], nagrobek["stack_cleared_id"]) == ("brak", ic)    # pamięć nagrobka do CAS
    # kanon wydania nieznany tej bazie: werdykt jawny, bez celu gestu (nie cisza)
    obce = stacks.release_object_check(con, master_sha1_data="sha1", object_canon="NGC9999")
    assert (obce["verdict"], obce["release_object_id"], obce["release_canon"]) == \
        ("wydanie_poza_baza", None, "NGC9999")
    # bez celu gestu: brak kanonu, klatka nieznana, nie-stos, stos zastąpiony, stos wycofany
    assert stacks.release_object_check(con, master_sha1_data="sha1", object_canon=None) is None
    assert stacks.release_object_check(con, master_sha1_data="nie-ma", object_canon="NGC7000") is None
    assert stacks.release_object_check(con, master_sha1_data="sha2", object_canon="NGC7000") is None
    con.execute("UPDATE frame SET superseded_by = 2 WHERE id = 1")
    assert stacks.release_object_check(con, master_sha1_data="sha1", object_canon="NGC7000") is None
    con.execute("UPDATE frame SET superseded_by = NULL, retired_at = ? WHERE id = 1", (NOW,))
    assert stacks.release_object_check(con, master_sha1_data="sha1", object_canon="NGC7000") is None
    assert _ev(con) == przed                                               # porównanie niczego nie zapisuje


# ═══════════════════════════════════════════ klinga: nadpisanie, idempotencja, dryf, cofnięcie


def test_gest_nadpisuje_obiekt_z_naglowka_para_eventow_a_drugi_gest_zero_eventow():
    """Stos „inny”: obiekt z nagłówka (którego `user_assign_object` nie ruszy) zastępuje obiekt wydania
    ze źródłem `user`; para `object.unassigned` + `object.assigned` z `before`; drugi gest = `unchanged`
    i zero eventów; resolver nie cofa ręki (źródło lepkie)."""
    con = _baza()
    ic, ngc = _oid(con, "IC1795"), _oid(con, "NGC7000")
    check = stacks.release_object_check(con, master_sha1_data="sha1", object_canon="NGC7000")
    # istniejąca klinga zostaje przy swojej ochronie - dlatego nowa klinga istnieje
    g = repo.user_assign_object(con, alias_norm=None, canon="NGC7000", catalog="NGC", kind="deep_sky",
                                frame_ids=[1], now=NOW, overwrite_weak=True)
    assert (g.assigned, g.skipped_source) == (0, 1) and _stan(con)[:2] == (ic, "header")

    przed, zmiany = _ev(con), []
    assert _nadpisz(con, check, changes_out=zmiany) == "assigned"
    assert _stan(con) == (ngc, "user", None)
    assert zmiany == [repo.StackObjectChange(1, (ic, "header", None), ngc)]
    verby = [r[0] for r in con.execute("SELECT verb FROM event WHERE id > (SELECT max(id) - 2 FROM event) "
                                       "ORDER BY id")]
    assert _ev(con) - przed == 2 and verby == ["object.unassigned", "object.assigned"]
    assert _bilans_osi(con)

    po = _ev(con)
    assert _nadpisz(con, check, changes_out=zmiany) == "unchanged"       # drugi klik, stary stan w ręku
    assert _ev(con) == po and len(zmiany) == 1
    resolver.run_resolver(con, now=NOW)
    assert _stan(con) == (ngc, "user", None)                              # przebieg nie przegłosował ręki


@pytest.mark.parametrize("pole", ["stack_object_id", "stack_source", "stack_cleared_id"])
def test_dryf_stanu_oczekiwanego_to_odmowa_bez_zapisu_i_bez_eventu(pole):
    """CAS na pełnej trójce: stan inny niż ten, który zdanie pokazało (obiekt, samo źródło albo sama
    pamięć nagrobka) - `drift`, nic się nie zmienia, dziennik stoi."""
    con = _baza()
    check = stacks.release_object_check(con, master_sha1_data="sha1", object_canon="NGC7000")
    zly = {**check, pole: {"stack_object_id": check["stack_object_id"] + 100, "stack_source": "alias",
                           "stack_cleared_id": 4242}[pole]}
    przed, stan, zmiany = _ev(con), _stan(con), []
    assert _nadpisz(con, zly, changes_out=zmiany) == "drift"
    assert (_ev(con), _stan(con), zmiany) == (przed, stan, [])


def test_ABA_nagrobka_miedzy_zdaniem_a_gestem_to_dryf():
    """Nagrobek X → (zdanie) → ręka przypisuje Y i zdejmuje Y: klatka znów `(NULL, user_cleared)`, ale
    nagrobek pamięta Y. Stary gest NIE zamalowuje nowszej decyzji: `drift`, zero eventów, stan stoi."""
    con = _baza(raw_stosu=None)
    repo.user_assign_object(con, alias_norm=None, canon="M31", catalog="M", kind="deep_sky", frame_ids=[1],
                            now=NOW)
    repo.clear_object_assignment(con, frame_ids=[1], now=NOW)              # nagrobek M31
    check = stacks.release_object_check(con, master_sha1_data="sha1", object_canon="NGC7000")
    repo.user_assign_object(con, alias_norm=None, canon="M33", catalog="M", kind="deep_sky", frame_ids=[1],
                            now=NOW, overwrite_weak=True, expected_source="user_cleared")
    repo.clear_object_assignment(con, frame_ids=[1], now=NOW)              # nagrobek M33 - ta sama etykieta
    stan, przed, zmiany = _stan(con), _ev(con), []
    assert stan == (None, "user_cleared", _oid(con, "M33"))
    assert _nadpisz(con, check, changes_out=zmiany) == "drift"
    assert (_stan(con), _ev(con), zmiany) == (stan, przed, [])


@pytest.mark.parametrize("pole, wartosc", [("retired_at", NOW), ("superseded_by", 2)])
def test_stos_wycofany_albo_zastapiony_miedzy_zdaniem_a_gestem_to_dryf(pole, wartosc):
    """Martwa tożsamość (wycofanie, zastąpienie) między zdaniem a klikiem: klinga czyta oba pola pod
    blokadą i odmawia - `drift`, zero eventów, obiekt stoi."""
    con = _baza()
    check = stacks.release_object_check(con, master_sha1_data="sha1", object_canon="NGC7000")
    con.execute(f"UPDATE frame SET {pole} = ? WHERE id = 1", (wartosc,))
    con.commit()
    stan, przed = _stan(con), _ev(con)
    assert _nadpisz(con, check) == "drift"
    assert (_stan(con), _ev(con)) == (stan, przed)


def test_cofniecie_przywraca_stan_sprzed_i_tylko_raz():
    """Cofnięcie = stan `before` z klingi (obiekt i źródło z nagłówka), para eventów lustrem gestu,
    bilans zielony; drugie cofnięcie i cofnięcie po nowszej decyzji = `False` bez eventu."""
    con = _baza()
    ic, ngc = _oid(con, "IC1795"), _oid(con, "NGC7000")
    check = stacks.release_object_check(con, master_sha1_data="sha1", object_canon="NGC7000")
    zmiany = []
    _nadpisz(con, check, changes_out=zmiany)
    przed = _ev(con)
    assert repo.restore_stack_object(con, change=zmiany[0], now=NOW) is True
    assert _stan(con) == (ic, "header", None) and _ev(con) - przed == 2 and _bilans_osi(con)
    po = _ev(con)
    assert repo.restore_stack_object(con, change=zmiany[0], now=NOW) is False
    assert _ev(con) == po

    # nowsza decyzja ręki po geście: cofnięcie jej nie nadpisuje
    zmiany = []
    _nadpisz(con, check, changes_out=zmiany)
    repo.clear_object_assignment(con, frame_ids=[1], now=NOW)             # „Cofnij przypisanie” w Zbiorach
    stan, po = _stan(con), _ev(con)
    assert stan == (None, "user_cleared", ngc)
    assert repo.restore_stack_object(con, change=zmiany[0], now=NOW) is False
    assert (_stan(con), _ev(con)) == (stan, po)


def test_stos_bez_obiektu_i_nagrobek_wracaja_po_cofnieciu_z_pamiecia():
    """Stos „brak” z nagrobkiem ręki: gest zapisuje obiekt wydania (jeden `object.assigned`, pamięć
    nagrobka gaśnie), cofnięcie wraca do nagrobka Z PAMIĘCIĄ (CHECK 0017 przepuszcza tylko taką parę)."""
    con = _baza(raw_stosu=None)                                             # stos bez `OBJECT`
    assert _stan(con) == (None, None, None)
    repo.user_assign_object(con, alias_norm=None, canon="M31", catalog="M", kind="deep_sky", frame_ids=[1],
                            now=NOW)
    m31, ngc = _oid(con, "M31"), _oid(con, "NGC7000")
    repo.clear_object_assignment(con, frame_ids=[1], now=NOW)              # ręka zdjęła M31 - nagrobek
    assert _stan(con) == (None, "user_cleared", m31) and _bilans_osi(con)
    check = stacks.release_object_check(con, master_sha1_data="sha1", object_canon="NGC7000")
    assert check["verdict"] == "brak"
    przed, zmiany = _ev(con), []
    assert _nadpisz(con, check, changes_out=zmiany) == "assigned"
    assert _stan(con) == (ngc, "user", None) and _ev(con) - przed == 1 and _bilans_osi(con)
    assert repo.restore_stack_object(con, change=zmiany[0], now=NOW) is True
    assert _stan(con) == (None, "user_cleared", m31) and _bilans_osi(con)


def test_klinga_odmawia_spoza_stosu_i_obiektowi_spoza_bazy():
    con = _baza()
    ngc = _oid(con, "NGC7000")
    for kw in ({"frame_id": 2, "object_id": ngc}, {"frame_id": 1, "object_id": 9999},
               {"frame_id": 77, "object_id": ngc}):
        przed = _ev(con)
        with pytest.raises(ValueError):
            repo.user_override_stack_object(con, expected_object_id=None, expected_source=None,
                                            expected_cleared_id=None, now=NOW, **kw)
        assert _ev(con) == przed
