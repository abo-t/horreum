"""KOPIA WIODĄCA KLATKI - rdzeń gestu „Ta kopia prowadzi" (AR-4, AR-23): `lead_copy`.

Scenariusz z archiwum (masterflat RC8_2600MC, jak w `test_orphan_testimony`): jedna klatka, dwie
kopie o tych samych pikselach - pierwsza wjechała kopia L-Pro (jej głos niesie `header`), druga
mówi CLS. Człowiek wskazuje kopię wiodącą; jego wybór jest faktem ręki (`header.adopted`
z aktorem `user:local`) i żaden kolejny przebieg - skan, Dostawa, etap przejęcia - go nie cofa.
Pliki syntetyczne w `tmp_path` - zero archiwum, zero żywej bazy."""
import json
import os

import pytest

from horreum import audit, db, derive, lead_copy, scan
from horreum.gui import queries
from horreum.resolve.filters import normalize_filter
from horreum.resolve.headers import extract_header

from test_copy_facts import NOW, _xisf
from test_orphan_testimony import _MASTER, _cls, _header, _loc, _lpro, _zniknij

LATER = "2026-10-07T09:00:00+00:00"


def _zdarzenia_po(con, ev):
    return con.execute("SELECT verb, actor, target, payload FROM event WHERE id > ? ORDER BY id",
                       (ev,)).fetchall()


@pytest.fixture
def niezgodne(tmp_path):
    """Klatka o dwóch OBECNYCH kopiach, które mówią różnie; `header` z kopii L-Pro."""
    root = tmp_path / "ARCH"
    a, b = _lpro(root), _cls(root)
    con = db.open_db(str(tmp_path / "h.db"))
    scan.scan_tree(con, root, volume="?", now=NOW)
    fid = _loc(con, a)["frame_id"]
    assert _loc(con, b)["frame_id"] == fid and _header(con, fid)["filter_raw"] == "L-Pro"
    yield con, root, fid, a, b
    con.close()


# ═════════════════════════ menu: kopie do wyboru i to, kto czeka


def test_kopie_do_wyboru_mowia_kto_mowi_i_czym_sie_roznia(niezgodne):
    """Menu dostaje obie obecne kopie w kolejności wjazdu: L-Pro „mówi" (jej głos niesie `header`),
    CLS nie; obie niosą pola rozjazdu z `queries.copy_divergence`. Klatka czeka na decyzję -
    należy do „Kopii niezgodnych"."""
    con, _root, fid, a, b = niezgodne
    assert lead_copy.awaiting_hand(con, fid)
    kopie = lead_copy.lead_copy_choices(con, fid)
    assert [(k.path, k.mowi, k.fakty) for k in kopie] == [(str(a), True, True), (str(b), False, True)]
    assert "FILTER" in kopie[0].rozne and kopie[0].rozne == kopie[1].rozne
    assert kopie[1].fakty_kopii["hdr_filter"] == "CLS"


def test_klatka_zgodna_nie_czeka_na_wskazanie(tmp_path):
    """Dwie kopie o tym samym nagłówku: nic się nie kłóci, zeznanie mówi głosem obecnej kopii -
    gest nie ma tu roboty (`awaiting_hand` fałsz), choć kopie wciąż da się wymienić."""
    root = tmp_path / "ARCH"
    _cls(root, sub="A"), _cls(root, sub="B")
    con = db.open_db(str(tmp_path / "h.db"))
    scan.scan_tree(con, root, volume="?", now=NOW)
    fid = con.execute("SELECT id FROM frame").fetchone()[0]
    assert not lead_copy.awaiting_hand(con, fid)
    assert all(k.mowi for k in lead_copy.lead_copy_choices(con, fid))
    con.close()


# ═════════════════════════ gest: przejęcie, fakt ręki, droga powrotu


def test_gest_przejmuje_zeznanie_wskazanej_kopii_i_zostawia_fakt_reki(niezgodne):
    """„Ta kopia prowadzi" na kopii CLS: `header` mówi CLS, pochodne przeliczone (filtr kanoniczny
    z nowego zeznania), JEDNO `header.adopted` z aktorem `user:local` i payloadem „skąd → dokąd".
    Klatka zostaje w „Kopiach niezgodnych" (kopie dalej się różnią), ale ma decyzję ręki - robota
    wiersza gaśnie, a spis faktów ręki rośnie w osi `testimony_hand`. Droga powrotu = kopia L-Pro,
    która mówiła przed gestem."""
    con, _root, fid, a, b = niezgodne
    przed = audit.human_facts_census(con)
    ev = con.execute("SELECT max(id) FROM event").fetchone()[0]
    wynik = lead_copy.lead_copy_gesture(con, _loc(con, b)["id"], LATER)
    assert (wynik.verdict, wynik.frame_id, wynik.path, wynik.back) == (
        "adopted", fid, str(b), (str(a),))
    h = _header(con, fid)
    assert (h["filter_raw"], h["object_raw"], h["exptime"]) == ("CLS", "NGC 6888", 0.205)
    assert con.execute("SELECT filter_canon FROM frame WHERE id = ?", (fid,)).fetchone()[0] == \
        normalize_filter("CLS")
    przejecia = [e for e in _zdarzenia_po(con, ev) if e["verb"] == "header.adopted"]
    assert [(e["actor"], e["target"]) for e in przejecia] == [("user:local", f"frame:{fid}")]
    payload = json.loads(przejecia[0]["payload"])
    assert payload["location_id"] == _loc(con, b)["id"]
    assert payload["changed"]["filter_raw"] == {"before": "L-Pro", "after": "CLS"}
    assert queries.copy_conflict_frame_ids(con) == {fid}
    assert queries.hand_testimony_frame_ids(con, {fid}) == {fid}
    po = audit.human_facts_census(con)
    assert po.testimony_hand == przed.testimony_hand + 1 and not po.spadki(przed)


def test_droga_powrotu_to_ten_sam_gest_na_poprzedniej_kopii(niezgodne):
    """Wybór drugiej kopii przywraca zeznanie sprzed pierwszego gestu, a jego droga powrotu
    wskazuje kopię z pierwszego gestu. Obie decyzje zostają w dzienniku (append-only)."""
    con, _root, fid, a, b = niezgodne
    lead_copy.lead_copy_gesture(con, _loc(con, b)["id"], LATER)
    wynik = lead_copy.lead_copy_gesture(con, _loc(con, a)["id"], LATER)
    assert (wynik.verdict, wynik.back) == ("adopted", (str(b),))
    assert _header(con, fid)["filter_raw"] == "L-Pro"
    assert con.execute("SELECT count(*) FROM event WHERE verb = 'header.adopted' "
                       "AND actor = 'user:local'").fetchone()[0] == 2


def test_kopia_ktora_juz_mowi_zapisuje_sam_wybor_reki_raz(niezgodne):
    """Wskazanie kopii, której głosem klatka już mówi: treść bez zmian, ale WYBÓR jest faktem ręki
    (AR-4) - klinga zapisuje JEDNO `header.adopted` z `changed: {}` i `confirmed: True` i zwraca
    `confirmed`; pochodne nie ruszają (treść ta sama). Powtórny gest na tej samej kopii: `unchanged`,
    ZERO zdarzeń. Spis faktów ręki rośnie w osi `testimony_hand`.
    Falsyfikator: zdejmij gałąź ręki w `repo.adopt_testimony` - werdykt wraca do `unchanged`
    bez zdarzenia, a etap Dostawy może potem przestawić zeznanie bez pytania."""
    con, _root, fid, a, _b = niezgodne
    przed = audit.human_facts_census(con)
    ev = con.execute("SELECT max(id) FROM event").fetchone()[0]
    wynik = lead_copy.lead_copy_gesture(con, _loc(con, a)["id"], LATER)
    assert (wynik.verdict, wynik.back) == ("confirmed", ())
    zdarzenia = _zdarzenia_po(con, ev)
    assert [(e["verb"], e["actor"]) for e in zdarzenia] == [("header.adopted", "user:local")]
    payload = json.loads(zdarzenia[0]["payload"])
    assert (payload["location_id"], payload["changed"], payload["confirmed"]) == (
        _loc(con, a)["id"], {}, True)
    assert _header(con, fid)["filter_raw"] == "L-Pro"
    assert queries.hand_testimony_frame_ids(con, {fid}) == {fid}
    assert audit.human_facts_census(con).testimony_hand == przed.testimony_hand + 1

    ev = con.execute("SELECT max(id) FROM event").fetchone()[0]
    assert lead_copy.lead_copy_gesture(con, _loc(con, a)["id"], LATER).verdict == "unchanged"
    assert _zdarzenia_po(con, ev) == []


def _przepisz_naglowek(path, *, filtr, obiekt, exptime):
    """Zmiana nagłówka kopii na dysku przy tych samych pikselach (tożsamość klatki bez zmian)."""
    _xisf(path, _MASTER + (("FILTER", f"'{filtr}'"), ("OBJECT", f"'{obiekt}'"),
                           ("EXPTIME", exptime)), payload=b"\x05" * 32)
    st = os.stat(path)
    os.utime(path, (st.st_atime, st.st_mtime + 60))


def test_zmiana_naglowka_INNEJ_kopii_nie_przestawia_wyboru_reki(niezgodne):
    """AR-4 wobec „ostatni odczyt wygrywa" (`repo.refresh_location`): po wskazaniu kopii CLS zmiana
    nagłówka kopii L-Pro na dysku odświeża WYŁĄCZNIE jej fakty kopii (rozjazd pokazują „Kopie
    niezgodne"), a zeznanie klatki zostaje głosem CLS. Spis faktów ręki (`--baseline`) bez ubytku.
    Falsyfikator: zdejmij strażnika `hand_lead_location` z `refresh_location` - `header` przejdzie
    na `Inny`, a oś `testimony_hand` spadnie."""
    con, root, fid, a, b = niezgodne
    lead_copy.lead_copy_gesture(con, _loc(con, b)["id"], LATER)
    po_gescie = audit.human_facts_census(con)
    _przepisz_naglowek(a, filtr="L-Pro", obiekt="Inny", exptime="0.2")
    scan.scan_tree(con, root, volume="?", now=LATER)
    assert _loc(con, a)["hdr_object"] == "Inny", "fakty kopii idą za plikiem"
    h = _header(con, fid)
    assert (h["filter_raw"], h["object_raw"]) == ("CLS", "NGC 6888")
    assert fid in queries.copy_conflict_frame_ids(con)
    assert not audit.human_facts_census(con).spadki(po_gescie)


def test_zmiana_naglowka_WYBRANEJ_kopii_plynie_do_zeznania(niezgodne):
    """Druga połowa: zmiana nagłówka kopii wskazanej ręką dalej odświeża zeznanie klatki (to jej
    głos), a wybór trwa - spis faktów ręki bez ubytku, kolejna zmiana innej kopii dalej go nie
    rusza."""
    con, root, fid, a, b = niezgodne
    lead_copy.lead_copy_gesture(con, _loc(con, b)["id"], LATER)
    po_gescie = audit.human_facts_census(con)
    _przepisz_naglowek(b, filtr="CLS", obiekt="NGC 6888", exptime="0.21")
    scan.scan_tree(con, root, volume="?", now=LATER)
    assert _header(con, fid)["exptime"] == 0.21
    assert not audit.human_facts_census(con).spadki(po_gescie)
    _przepisz_naglowek(a, filtr="L-Pro", obiekt="Inny", exptime="0.2")
    scan.scan_tree(con, root, volume="?", now=LATER)
    assert _header(con, fid)["filter_raw"] == "CLS"


def test_bez_reki_zeznanie_plynie_tylko_z_kopii_zrodlowej(niezgodne):
    """AR-4 bez ręki: przy ≥2 obecnych kopiach nie ma automatycznej reguły wyboru - dawne
    „ostatni odczyt wygrywa" przepisywało zeznanie na kopię, której nagłówek zmienił się ostatnio.
    Zmiana kopii, która NIE jest źródłem `header` (CLS), zostaje w jej faktach; zmiana kopii
    źródłowej (L-Pro, jedyna o faktach równych zeznaniu) płynie do zeznania.
    Falsyfikator: wróć do bezwarunkowego przepisania w `refresh_location` - `header` przejdzie na
    `Inny CLS`."""
    con, root, fid, a, b = niezgodne
    _przepisz_naglowek(b, filtr="CLS", obiekt="Inny CLS", exptime="0.205")
    scan.scan_tree(con, root, volume="?", now=LATER)
    assert _loc(con, b)["hdr_object"] == "Inny CLS"
    assert _header(con, fid)["object_raw"] == "FlatWizard", "nie-źródło nie przepisuje zeznania"
    _przepisz_naglowek(a, filtr="L-Pro", obiekt="Inny", exptime="0.2")
    scan.scan_tree(con, root, volume="?", now=LATER)
    assert _header(con, fid)["object_raw"] == "Inny", "źródło przepisuje"


def test_bez_reki_i_bez_jednoznacznego_zrodla_nic_sie_nie_przepisuje(tmp_path):
    """Dwie kopie mówiące TO SAMO (obie pasują do `header`): źródła nie da się wskazać
    jednoznacznie, więc zmiana jednej z nich nie przepisuje zeznania - kopie się rozjeżdżają,
    a „Kopie niezgodne" oddają klatkę człowiekowi."""
    root = tmp_path / "ARCH"
    a, _b = _cls(root, sub="A"), _cls(root, sub="B")
    con = db.open_db(str(tmp_path / "h.db"))
    scan.scan_tree(con, root, volume="?", now=NOW)
    fid = _loc(con, a)["frame_id"]
    _przepisz_naglowek(a, filtr="CLS", obiekt="Inny", exptime="0.205")
    scan.scan_tree(con, root, volume="?", now=LATER)
    assert _header(con, fid)["object_raw"] == "NGC 6888"
    assert fid in queries.copy_conflict_frame_ids(con)
    con.close()


def test_kotwica_reki_po_zniknieciu_wybranej_kopii_nie_blokuje_jedynej_obecnej(niezgodne):
    """Z5: kotwica ręki ważna tylko, gdy wskazana kopia jest obecna. Wybrana CLS znika, ocalała
    L-Pro jest jedyną obecną - zmiana jej nagłówka (np. zapis ręką i re-sync) ma płynąć do
    zeznania, a nie zostać zablokowana przez kotwicę na pliku, którego nie ma."""
    con, root, fid, a, b = niezgodne
    lead_copy.lead_copy_gesture(con, _loc(con, b)["id"], LATER)
    _zniknij(con, b)
    _przepisz_naglowek(a, filtr="L-Pro", obiekt="Inny", exptime="0.2")
    scan.scan_tree(con, root, volume="?", now=LATER)
    assert _header(con, fid)["object_raw"] == "Inny"


def test_etap_automatu_odmawia_pod_lockiem_przy_dwoch_kopiach_albo_rece(niezgodne):
    """Z7: klinga sama sprawdza kandydaturę automatu w swojej transakcji - aktor spoza ręki przy
    ≥2 obecnych kopiach albo przy ważnej kotwicy ręki dostaje `raced`, zero zapisu."""
    from horreum import repo
    con, _root, fid, a, b = niezgodne
    rec = scan.scan_file(str(b))
    sha1, _ = scan._record_identity(rec)

    def _przejmij(aktor):
        return repo.adopt_testimony(
            con, location_id=_loc(con, b)["id"], sha1_data=sha1, header_hash=rec.header_hash,
            raw_json=json.dumps(rec.header, ensure_ascii=False), cards=rec.cards,
            hot_fields=extract_header(rec.header), camera_id=None, kind="master_flat",
            now=LATER, actor=aktor)
    ev = con.execute("SELECT max(id) FROM event").fetchone()[0]
    assert _przejmij("adopt") == "raced"
    assert _zdarzenia_po(con, ev) == [] and _header(con, fid)["filter_raw"] == "L-Pro"
    # Jedna obecna kopia, ale z ważną kotwicą ręki: automat też odmawia.
    lead_copy.lead_copy_gesture(con, _loc(con, b)["id"], LATER)       # kotwica ręki na CLS
    _zniknij(con, a)
    ev = con.execute("SELECT max(id) FROM event").fetchone()[0]
    assert _przejmij("adopt") == "raced"
    assert _zdarzenia_po(con, ev) == []


def test_gest_na_klatce_innej_niz_z_menu_odmawia(niezgodne):
    """Z6: skan przepiął ścieżkę na inną klatkę między menu a zapisem - gest niesie klatkę z menu,
    rozjazd = `raced`, zero zapisu (ręka nie trafia w klatkę, której człowiek nie wybierał)."""
    con, _root, fid, _a, b = niezgodne
    ev = con.execute("SELECT max(id) FROM event").fetchone()[0]
    wynik = lead_copy.lead_copy_gesture(con, _loc(con, b)["id"], LATER, expected_frame_id=fid + 999)
    assert wynik.verdict == "raced"
    assert _zdarzenia_po(con, ev) == []
    assert lead_copy.lead_copy_gesture(con, _loc(con, b)["id"], LATER,
                                       expected_frame_id=fid).verdict == "adopted"


def test_zeznanie_z_nieobecnej_kopii_przy_dwoch_ocalalych(tmp_path):
    """Droga „do człowieka" wiersza „Zeznanie z nieobecnej kopii": źródło `header` (L-Pro) znika,
    ocalały CLS i OSC. Gest na OSC: klatka mówi OSC i wypada z predykatu; drogi powrotu gestem nie
    ma (poprzedni głos należał do kopii, której już nie ma - `back` puste)."""
    root = tmp_path / "ARCH"
    a, _b = _lpro(root), _cls(root)
    c = _xisf(root / "C_OSC" / "m.xisf", _MASTER + (("FILTER", "'OSC'"),), payload=b"\x05" * 32)
    con = db.open_db(str(tmp_path / "h.db"))
    scan.scan_tree(con, root, volume="?", now=NOW)
    fid = _loc(con, a)["frame_id"]
    _zniknij(con, a)
    assert queries.orphan_testimony_frame_ids(con) == {fid} and lead_copy.awaiting_hand(con, fid)
    assert not any(k.mowi for k in lead_copy.lead_copy_choices(con, fid))
    wynik = lead_copy.lead_copy_gesture(con, _loc(con, c)["id"], LATER)
    assert (wynik.verdict, wynik.back) == ("adopted", ())
    assert _header(con, fid)["filter_raw"] == "OSC"
    assert queries.orphan_testimony_frame_ids(con) == set()
    con.close()


def test_odmowy_nic_nie_zapisuja(niezgodne):
    """Kopia nieobecna według bazy → `absent`; plik zniknął z dysku przed passem obecności →
    `failed` z diagnozą odczytu. W obu ZERO zdarzeń."""
    con, _root, fid, a, b = niezgodne
    ev = con.execute("SELECT max(id) FROM event").fetchone()[0]
    os.remove(b)
    wynik = lead_copy.adopt_lead_copy(con, location_id=_loc(con, b)["id"], now=LATER)
    assert wynik.verdict == "failed" and wynik.reason and wynik.frame_id == fid
    _zniknij(con, a)
    ev = con.execute("SELECT max(id) FROM event").fetchone()[0]
    assert lead_copy.adopt_lead_copy(con, location_id=_loc(con, a)["id"],
                                     now=LATER).verdict == "absent"
    assert _zdarzenia_po(con, ev) == []
    with pytest.raises(ValueError):
        lead_copy.adopt_lead_copy(con, location_id=999_999, now=LATER)


# ═════════════════════════ ręka nietykalna


def test_kolejny_skan_i_dostawa_nie_cofaja_wyboru_czlowieka(niezgodne):
    """Warunek AR-4: wybór człowieka przeżywa każdy przebieg bez nowego faktu z pliku - ponowny
    skan drzewa, cały ogon Dostawy (fakty kopii, etap przejęcia, pochodne) i - po zniknięciu
    wskazanej kopii - etap przejęcia zeznania, który przy zeznaniu z ręki oddaje klatkę
    człowiekowi zamiast przepisać ją głosem ocalałej kopii L-Pro. Spis faktów ręki bez ubytku."""
    con, root, fid, a, b = niezgodne
    lead_copy.lead_copy_gesture(con, _loc(con, b)["id"], LATER)
    po_gescie = audit.human_facts_census(con)
    scan.scan_tree(con, root, volume="?", now=LATER)
    list(derive.adopt_and_derive(con, str(root), LATER, derive_always=True))
    assert _header(con, fid)["filter_raw"] == "CLS"
    _zniknij(con, b)
    dla_etapu, dla_czlowieka = queries.orphan_testimony_routes(con)
    assert fid not in dla_etapu and fid in dla_czlowieka
    s = scan.adopt_orphan_testimony(con, now=LATER)
    assert (s.rows, s.adopted) == (0, 0)
    list(derive.adopt_and_derive(con, None, LATER, derive_always=True))
    assert _header(con, fid)["filter_raw"] == "CLS"
    assert not audit.human_facts_census(con).spadki(po_gescie)


def test_spis_faktow_reki_bez_osi_zeznania_czyta_sie_jako_zero():
    """Odniesienie `human-facts --json` sprzed tej osi nie ma klucza `testimony_hand` - wczytuje się
    jako 0, więc może ukryć wyłącznie WZROST, nigdy ubytek (kontrakt `offset_hand`)."""
    stare = {"object_hand": 1, "object_cleared": 0, "config_hand": 0, "lineage_inputs": 0,
             "lineage_excluded": 0, "calibration_facts": 0, "calibration_links": 0}
    assert audit.HumanFacts(**stare).testimony_hand == 0
    assert "testimony_hand" in audit.HumanFacts(**stare).counts
