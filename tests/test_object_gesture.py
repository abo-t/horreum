r"""GESTY CZŁOWIEKA NA OSI OBIEKTU — dwie klingi, obie odwracalne (S2b, D-OW-6).

Bramki §4, których właścicielem jest ten plik (człony KLINGI; człony POWIERZCHNI — paska Zbiorów —
mają dom w testach GUI):

  * **14b** — „Cofnij przypisanie" domyka się: `object_id` NULL, NAGROBEK, para eventów, klatka
    wraca do kubełka **i ZOSTAJE tam po kolejnym `Rozwiąż`** — na OBU populacjach (zeznanie
    nagłówka / RAW nazwany ze ŚCIEŻKI). Człon (c) — gaśnięcie nagrobka — siedzi w `test_writeback`,
    bo jego wyzwalaczem jest realny zapis karty do pliku.
  * **14c (b)** — zaznaczenie z kalibracją: przypisane wyłącznie lighty, reszta w OSOBNYM liczniku.
    **To jedyna bramka na ten defekt w repo** — `§5.9` go NIE złapie, bo encje i eventy zgadzają
    się co do sztuki także wtedy, gdy obiekt dostał dark.
  * **14c (c)/(e)** — gest rusza WYŁĄCZNIE źródła słabe: klatki z nagłówka i z regionu zostają.
  * **14c (d)** — `expected_object_id` jako ZAMROŻONY STAN okna: klatka, która w międzyczasie stała
    się czymś innym, jest pomijana jako dryf.
  * **14c (h)** — „Cofnij" POMIJA gotowe obrazy (własny licznik), bo odebranie stosowi obiektu
    rozbraja dobór okna rodowodu.

REGUŁA CZYTANIA LICZNIKÓW: `ObjectGesture` rozbija pominięcia PER FAKT. Test, który sprawdza samo
`skipped`, przechodzi także wtedy, gdy klinga pominęła klatkę z ZUPEŁNIE innego powodu — dlatego
każdy człon niżej pyta o konkretne pole.
"""
from horreum import db, repo, resolver

NOW = "2026-08-03T18:00:00Z"
R = "R:\\ASTRO_"


def _baza(klatki):
    """`klatki` = [(kind, filetype, object_raw|None, ścieżka|None)] → baza 1:1 z jedną obecną kopią.
    Surowy SQL (fikstura, nie ingest) — wzorzec `test_path_rung._baza`."""
    con = db.connect(":memory:")
    db.migrate(con)
    for i, (kind, filetype, raw, path) in enumerate(klatki, start=1):
        con.execute("INSERT INTO frame(id, kind, filetype, sha1_data, first_seen_at) "
                    "VALUES (?, ?, ?, ?, ?)", (i, kind, filetype, f"sha{i}", NOW))
        con.execute("INSERT INTO header(frame_id, object_raw, raw_json) VALUES (?,?,'{}')", (i, raw))
        if path is not None:
            con.execute("INSERT INTO location(frame_id, volume, path, present) "
                        "VALUES (?, 'VOL', ?, 1)", (i, path))
    con.commit()
    return con


def _ev(con, verb):
    return con.execute("SELECT count(*) FROM event WHERE verb = ?", (verb,)).fetchone()[0]


def _stan(con, fid):
    r = con.execute("SELECT object_id, object_source FROM frame WHERE id = ?", (fid,)).fetchone()
    return r["object_id"], r["object_source"]


def _przypisz(con, fids, canon="LMC", **kw):
    return repo.user_assign_object(con, alias_norm=None, canon=canon, catalog=None, kind="own",
                                   frame_ids=fids, now=NOW, **kw)


# ═══════════════════════════════════════════ §4/14c (b) — GUARD RODZAJU STOI W KLINDZE


def test_kalibracja_w_zaznaczeniu_NIE_dostaje_obiektu():
    """Pasek Zbiorów bierze zaznaczenie z WIDOKU, więc wpadną w nie darki i flaty. Obiekt dotyczy
    wyłącznie lightów (memory `horreum-object-resolution-kind-aware`), a `§5.9` tego zapisu nie
    złapie — bilans encji i eventów byłby ZIELONY także dla darka z obiektem."""
    con = _baza([("light", "raw", None, rf"{R}\LIGHTS\LMC\x.ARW"),
                 ("dark", "fits", None, rf"{R}\CALIBRATION\dark\d.fit"),
                 ("flat", "fits", None, rf"{R}\CALIBRATION\flat\f.fit")])
    g = _przypisz(con, [1, 2, 3])
    assert (g.assigned, g.skipped_kind) == (1, 2)
    assert _stan(con, 1)[1] == "user"
    assert _stan(con, 2) == (None, None) and _stan(con, 3) == (None, None)
    assert _ev(con, "object.assigned") == 1        # dwa pominięcia NIE zostawiają śladu w dzienniku


def test_licznik_rodzaju_jest_ODDZIELNY_od_dryfu():
    """Falsyfikator jednego licznika: gdyby oba pominięcia wpadały do wspólnego „skipped", ekran
    powiedziałby „pominięto 2" i człowiek nie wiedziałby, czy ochrona zadziałała, czy gest chybił."""
    con = _baza([("dark", "fits", None, None),
                 ("light", "raw", None, rf"{R}\LIGHTS\LMC\x.ARW")])
    con.execute("INSERT INTO object(id, canon, kind) VALUES (9, 'CUDZY', 'own')")
    con.execute("UPDATE frame SET object_id = 9, object_source = 'user' WHERE id = 2")
    con.commit()
    g = _przypisz(con, [1, 2])
    assert (g.assigned, g.skipped_kind, g.skipped_drift) == (0, 1, 1)


# ═══════════════════════════════════════════ §4/14c (c)/(d)/(e) — NADPISANIE TYLKO ŹRÓDEŁ SŁABYCH


def test_nazwij_zaznaczenie_rusza_sciezke_a_naglowek_i_region_ZOSTAJA():
    """Gest na zbiorze 250 klatek z regionu + 30 ze ścieżki rusza WYŁĄCZNIE 30 (§4/14c-c/e).
    Nagłówek i region to fakty z pliku i z geometrii — ręka ich nie zamalowuje."""
    con = _baza([("light", "raw", None, rf"{R}\LIGHTS\NGC6960\x.ARW"),
                 ("light", "fits", "NGC6992", rf"{R}\LIGHTS\NGC6992\y.fit"),
                 ("light", "fits", None, rf"{R}\LIGHTS\cos\z.fit")])
    con.execute("INSERT INTO object(id, canon, kind) VALUES (5, 'NGC6960', 'deep_sky')")
    con.execute("INSERT INTO object(id, canon, kind) VALUES (6, 'Veil', 'region')")
    con.execute("UPDATE frame SET object_id = 5, object_source = 'path'   WHERE id = 1")
    con.execute("UPDATE frame SET object_id = 6, object_source = 'header' WHERE id = 2")
    con.execute("UPDATE frame SET object_id = 6, object_source = 'region' WHERE id = 3")
    con.commit()

    g = _przypisz(con, [1, 2, 3], canon="Veil", overwrite_weak=True)
    assert (g.assigned, g.skipped_source) == (1, 2)
    assert _stan(con, 1)[1] == "user"                     # słabe źródło ustąpiło ręce
    assert _stan(con, 2) == (6, "header") and _stan(con, 3) == (6, "region")


def test_nadpisanie_emituje_PARE_verbow():
    """§5.9 człon 3: przepięcie bez `object.unassigned` rozjeżdża bilans DOKŁADNIE o liczbę
    nadpisań — i bramka świeci ZIELONO, bo obie strony liczą to samo za mało."""
    con = _baza([("light", "raw", None, rf"{R}\LIGHTS\NGC6960\x.ARW")])
    con.execute("INSERT INTO object(id, canon, kind) VALUES (5, 'NGC6960', 'deep_sky')")
    con.execute("UPDATE frame SET object_id = 5, object_source = 'path' WHERE id = 1")
    con.commit()
    _przypisz(con, [1], canon="Veil", overwrite_weak=True)
    assert (_ev(con, "object.unassigned"), _ev(con, "object.assigned")) == (1, 1)


def test_expected_object_id_pomija_klatke_ktora_zmienila_obiekt():
    """§4/14c-d: `expected` to ZAMROŻONY STAN z chwili, gdy user patrzył na okno. Bez niego gest
    „przemaluj te klatki z `NGC6960`" nadpisałby też klatkę, która właśnie stała się czymś innym."""
    con = _baza([("light", "raw", None, rf"{R}\LIGHTS\NGC6960\x.ARW"),
                 ("light", "raw", None, rf"{R}\LIGHTS\NGC6960\y.ARW")])
    con.execute("INSERT INTO object(id, canon, kind) VALUES (5, 'NGC6960', 'deep_sky')")
    con.execute("INSERT INTO object(id, canon, kind) VALUES (8, 'INNY', 'own')")
    con.execute("UPDATE frame SET object_id = 5, object_source = 'path' WHERE id = 1")
    con.execute("UPDATE frame SET object_id = 8, object_source = 'path' WHERE id = 2")
    con.commit()
    g = _przypisz(con, [1, 2], canon="Veil", overwrite_weak=True, expected_object_id=5)
    assert (g.assigned, g.skipped_drift) == (1, 1)
    assert _stan(con, 2)[0] == 8                          # klatka spoza oczekiwania NIETKNIĘTA


def test_zaznaczenie_BEZ_zadnego_obiektu_dziala_normalnie():
    """R24#6 — populacja SZTANDAROWA (LMC/Orion) nie ma żadnego `object_id`, więc `expected=None`
    i akcja ma DZIAŁAĆ. Reguła „dwa różne obiekty ⇒ odmowa" nie może jej zablokować."""
    con = _baza([("light", "raw", None, rf"{R}\LIGHTS\LMC\x.ARW"),
                 ("light", "raw", None, rf"{R}\LIGHTS\LMC\y.ARW")])
    g = _przypisz(con, [1, 2], overwrite_weak=True, expected_object_id=None)
    assert (g.assigned, g.skipped) == (2, 0)


# ═══════════════════════════════════════════ §4/14b — „COFNIJ" DOMYKA SIĘ


def test_cofniecie_zostawia_NAGROBEK_i_pare_verbow():
    con = _baza([("light", "raw", None, rf"{R}\LIGHTS\LMC\x.ARW")])
    _przypisz(con, [1])
    g = repo.clear_object_assignment(con, frame_ids=[1], now=NOW)
    assert g.assigned == 1
    assert _stan(con, 1) == (None, "user_cleared")
    assert (_ev(con, "object.unassigned"), _ev(con, "object.cleared")) == (1, 1)


def test_nagrobek_PRZEZYWA_kolejny_Rozwiaz_na_OBU_populacjach():
    """RDZEŃ odwracalności (R15#4). Bez nagrobka najbliższy przebieg przypisałby klatkę PONOWNIE —
    (a) z zeznania nagłówka, (b) z FOLDERU, bo szczebel ścieżki derywuje kanon na nowo. Cofnięcie,
    które cofa się samo przy kolejnym przebiegu, nie jest cofnięciem."""
    con = _baza([("light", "fits", "NGC7000", rf"{R}\LIGHTS\NGC7000\a.fit"),
                 ("light", "raw", None, rf"{R}\LIGHTS\LMC\b.ARW")])
    # (a) klatka Z ZEZNANIEM, którą ręka przypisała po swojemu · (b) RAW nazwany ze ŚCIEŻKI.
    # Obie mają świadka, który odezwie się przy każdym kolejnym przebiegu — i o to w tym pinie chodzi.
    _przypisz(con, [1], canon="COS_INNEGO")
    _przypisz(con, [2])
    repo.clear_object_assignment(con, frame_ids=[1, 2], now=NOW)

    resolver.run_resolver(con, "2026-08-04T00:00:00Z")
    assert _stan(con, 1) == (None, "user_cleared")
    assert _stan(con, 2) == (None, "user_cleared")
    # …a szczebel ścieżki nie proponuje jej NA NOWO: propozycja dla klatki z werdyktem byłaby
    # zaproszeniem do cofnięcia cofnięcia jednym kliknięciem „Zatwierdź wszystko".
    assert all(2 not in p.frame_ids for p in resolver.path_proposals(con))


def test_cofniecie_NIE_rusza_naglowka_xrefu_ani_regionu():
    """§4/14c-e: „Cofnij" na zbiorze z 556 klatkami z nagłówka ma zdjąć ZERO z nich."""
    con = _baza([("light", "fits", "NGC7000", None), ("light", "fits", None, None)])
    con.execute("INSERT INTO object(id, canon, kind) VALUES (5, 'NGC7000', 'deep_sky')")
    con.execute("UPDATE frame SET object_id = 5, object_source = 'header' WHERE id = 1")
    con.execute("UPDATE frame SET object_id = 5, object_source = 'region' WHERE id = 2")
    con.commit()
    g = repo.clear_object_assignment(con, frame_ids=[1, 2], now=NOW)
    assert (g.assigned, g.skipped_source) == (0, 2)
    assert _stan(con, 1) == (5, "header") and _stan(con, 2) == (5, "region")


def test_cofniecie_POMIJA_gotowe_obrazy_wlasnym_licznikiem():
    """§4/14c-h (R24#7): odebranie stosowi `object_id` ROZBRAJA dobór okna rodowodu — najbliższy
    przebieg zobaczyłby stos bez kandydatów i zdegradował dowiedziony rodowód do „brak wejść".
    Licznik jest WŁASNY, bo to ochrona cudzej pracy, a nie ten sam fakt co „nie ma czego cofać"."""
    con = _baza([("master_light", "xisf", None, None), ("light", "raw", None, None)])
    con.execute("INSERT INTO object(id, canon, kind) VALUES (5, 'NGC7000', 'deep_sky')")
    con.execute("UPDATE frame SET object_id = 5, object_source = 'user'")
    con.commit()
    g = repo.clear_object_assignment(con, frame_ids=[1, 2], now=NOW)
    assert (g.assigned, g.skipped_stack, g.skipped_source) == (1, 1, 0)
    assert _stan(con, 1) == (5, "user")                    # gotowy obraz NIETKNIĘTY


def test_cofniecie_jest_idempotentne():
    """Powtórzony gest → zero zapisu i ZERO nowych eventów (idempotencja jak reszta repo)."""
    con = _baza([("light", "raw", None, None)])
    _przypisz(con, [1])
    repo.clear_object_assignment(con, frame_ids=[1], now=NOW)
    ile = con.execute("SELECT count(*) FROM event").fetchone()[0]
    g = repo.clear_object_assignment(con, frame_ids=[1], now=NOW)
    assert (g.assigned, g.skipped_source) == (0, 1)
    assert con.execute("SELECT count(*) FROM event").fetchone()[0] == ile


def test_nagrobka_NIE_wskrzesza_gest_bez_jawnego_nadpisania():
    """Kubełkowe „Przypisz obiekt…" (bez `overwrite_weak`) nie ma prawa po cichu odwołać werdyktu:
    zdejmuje go wyłącznie DRUGI świadomy gest — „Nazwij zaznaczenie" albo karta w pliku."""
    con = _baza([("light", "raw", None, None)])
    _przypisz(con, [1])
    repo.clear_object_assignment(con, frame_ids=[1], now=NOW)
    g = _przypisz(con, [1], canon="INNY")
    assert (g.assigned, g.skipped_source) == (0, 1)
    assert _stan(con, 1) == (None, "user_cleared")
    assert _przypisz(con, [1], canon="INNY", overwrite_weak=True).assigned == 1


# ═══════════════════════════════════════════ NAGROBEK — gaśnięcie (człon repo; wpięcie w writeback)


def test_zgaszony_nagrobek_wraca_pod_drabine():
    """Obietnica członu (c): po zgaszeniu klatka jest znowu ZWYKŁA — kolejny przebieg rozwiązuje ją
    z zeznania. Falsyfikator: gdyby gaszenie zerowało samo pole bez eventu, bramka §5.9 straciłaby
    ślad zmiany, której nikt nie zgłosił."""
    con = _baza([("light", "fits", "NGC7000", None)])
    _przypisz(con, [1], canon="COS_INNEGO")               # ręka nadpisała zeznanie…
    repo.clear_object_assignment(con, frame_ids=[1], now=NOW)   # …i sama się z tego wycofała

    assert repo.clear_object_tombstone(con, frame_id=1, now=NOW) is True
    assert _stan(con, 1) == (None, None)
    assert _ev(con, "object.tombstone_cleared") == 1
    resolver.run_resolver(con, "2026-08-04T00:00:00Z")
    assert _stan(con, 1)[1] == "header"                   # drabina znowu ją widzi


def test_gaszenie_nagrobka_ktorego_nie_ma_jest_cisza():
    con = _baza([("light", "raw", None, None)])
    _przypisz(con, [1])
    assert repo.clear_object_tombstone(con, frame_id=1, now=NOW) is False
    assert _ev(con, "object.tombstone_cleared") == 0
    assert _stan(con, 1)[1] == "user"                      # cudze źródło NIETKNIĘTE


# ═══════════════════════════════════════════ §4/11 — BILANS OSI PO OBU GESTACH


def test_parytet_encji_i_eventow_przezywa_oba_gesty():
    """§5.9 człony (2) i (3) dla NOWYCH gestów: klatki z obiektem == przypisania − odpięcia,
    a PRZEPIĘCIE emituje parę. Falsyfikator jest w samej konstrukcji — gdyby nadpisanie źródła
    słabego emitowało samo `object.assigned`, lewa strona zostałaby w tyle DOKŁADNIE o liczbę
    nadpisań, a bramka i tak świeciłaby zielono, gdyby liczyła tylko jedną stronę."""
    from horreum import audit
    con = _baza([("light", "raw", None, rf"{R}\LIGHTS\NGC6960\a.ARW"),
                 ("light", "raw", None, rf"{R}\LIGHTS\NGC6960\b.ARW"),
                 ("dark", "fits", None, None)])
    _przypisz(con, [1, 2, 3], canon="NGC6960")            # dark odpada guardem rodzaju
    oid = con.execute("SELECT object_id FROM frame WHERE id = 1").fetchone()[0]
    _przypisz(con, [1], canon="Veil", overwrite_weak=True, expected_object_id=oid)
    con.execute("UPDATE frame SET object_source = 'path' WHERE id = 2")
    con.commit()
    repo.clear_object_assignment(con, frame_ids=[2], now=NOW)

    rows = {p.name: p for p in audit.entity_event_parity(con)}
    assert rows["frame.object_id"].ok, rows["frame.object_id"]
    assert rows["object"].ok and rows["object_alias"].ok
    assert audit.object_source_audit(con).ok               # `user_cleared` JEST w enumie
