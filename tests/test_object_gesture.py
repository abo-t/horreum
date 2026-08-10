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
  * **14c (h)** — „Cofnij" **OBEJMUJE** gotowe obrazy (D-OW-7): licznik `stacks` mówi, ile ich
    RUSZYŁ, i stoi POZA sumą `skipped`. Dawne brzmienie („POMIJA … bo odebranie stosowi obiektu
    rozbraja dobór okna rodowodu") opisywało PROTEZĘ: pomijanie kupowało ochronę rodowodu ceną
    ślepego zaułka. Od ochrony RANGĄ powód zniknął, więc zniknęło ograniczenie — a to zdanie
    zostało tu jeszcze po tym, jak przestało być prawdą.
  * **14c (h2)** — pominięcia cofnięcia są ROZDZIELONE po przyczynie: „nie było czego cofać"
    (`skipped_nothing`) nie jest tym samym, co „fakt spoza ręki" (`skipped_source`).

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


def test_cofniecie_OBEJMUJE_gotowe_obrazy_i_liczy_je_OSOBNO():
    """§4/14c-h po **D-OW-7** (decyzja Zdzinia 2026-08-03, odwraca R24#7): stos jest w zasięgu OBU
    gestów. Licznik zostaje własny, ale znaczy co innego — „w tym gotowe obrazy", nie „pominięte";
    dlatego stoi POZA sumą `skipped`, inaczej zdanie „cofnięto 2 z 2 · pominięto 1" przeczyłoby
    samo sobie. Ochrona rodowodu zeszła do PRZEBIEGU (`repo.RANGA_ASSERT`), więc pomijanie stosu
    kupowało już tylko ślepy zaułek: „Nazwij" go przepinało, „Cofnij" nie tykało."""
    con = _baza([("master_light", "xisf", None, None), ("light", "raw", None, None)])
    con.execute("INSERT INTO object(id, canon, kind) VALUES (5, 'NGC7000', 'deep_sky')")
    con.execute("UPDATE frame SET object_id = 5, object_source = 'user'")
    con.commit()
    g = repo.clear_object_assignment(con, frame_ids=[1, 2], now=NOW)
    assert (g.assigned, g.stacks, g.skipped) == (2, 1, 0)
    assert _stan(con, 1) == (None, "user_cleared")         # gotowy obraz RUSZONY, z nagrobkiem


def test_nazwanie_liczy_gotowe_obrazy_TYM_SAMYM_licznikiem():
    """Człon LUSTRZANY D-OW-7: skoro stos jest w zasięgu obu gestów, oba muszą o nim mówić — i tą
    samą liczbą. Asymetria licznika wróciłaby tym samym wejściem, którym wróciłaby asymetria gestu."""
    con = _baza([("master_light", "xisf", None, None), ("light", "raw", None, None)])
    g = repo.user_assign_object(con, alias_norm=None, canon="NGC7000", catalog="NGC",
                                kind="deep_sky", frame_ids=[1, 2], now=NOW)
    assert (g.assigned, g.stacks, g.skipped) == (2, 1, 0)


def test_cofniecie_jest_idempotentne():
    """Powtórzony gest → zero zapisu i ZERO nowych eventów (idempotencja jak reszta repo).

    Pominięcie ląduje w `skipped_nothing`, NIE w `skipped_source` (rozdział z S3): klatka już
    cofnięta nie ma czego cofać, a żadnego nagłówka ani regionu przy niej nie ma. Do rozdziału
    oba fakty schodziły do jednego licznika i ekran mówił „z nagłówka/regionu: 1" — komunikat
    o fałszywej przyczynie, z receptą („napraw kartą"), której nie da się wykonać."""
    con = _baza([("light", "raw", None, None)])
    _przypisz(con, [1])
    repo.clear_object_assignment(con, frame_ids=[1], now=NOW)
    ile = con.execute("SELECT count(*) FROM event").fetchone()[0]
    g = repo.clear_object_assignment(con, frame_ids=[1], now=NOW)
    assert (g.assigned, g.skipped_nothing, g.skipped_source, g.skipped) == (0, 1, 0, 1)
    assert con.execute("SELECT count(*) FROM event").fetchone()[0] == ile


def test_cofniecie_ROZROZNIA_brak_obiektu_od_faktu_z_pliku():
    """FALSYFIKATOR ROZDZIAŁU (wizytacja S3) — dwa pominięcia, dwie różne przyczyny, dwie liczby.

    Zmierzone na kopii żywej `pf4`: gest na trzech stosach, z których jeden nie miał obiektu,
    meldował „· z nagłówka/regionu: 1" o klatce bez nagłówka. Sklejenie było w klindze przyznane
    komentarzem („nie ma czego cofać ALBO fakt spoza ręki") — ta sama klasa, którą ta paczka
    zamknęła raz przy `skipped_stack`: kryterium nie ma prawa sklejać dwóch faktów.

    Falsyfikator: zlej oba `continue` z powrotem w jeden → `skipped_nothing` spada do 0."""
    con = _baza([("light", "raw", None, None),          # 1: dostanie obiekt ręką → cofnie się
                 ("light", "raw", "NGC7000", None),     # 2: fakt z pliku — ręka go nie zdejmie
                 ("light", "raw", None, None)])         # 3: nigdy nie miała obiektu
    con.execute("INSERT INTO object(id, canon, catalog, kind) "
                "VALUES (6,'NGC7000','NGC','deep_sky')")
    con.execute("UPDATE frame SET object_id = 6, object_source = 'header' WHERE id = 2")
    con.commit()
    _przypisz(con, [1])
    g = repo.clear_object_assignment(con, frame_ids=[1, 2, 3], now=NOW)
    assert (g.assigned, g.skipped_source, g.skipped_nothing) == (1, 1, 1)
    assert g.skipped == 2                                # suma zna OBA człony
    assert g.skipped_breakdown == [("kind", 0), ("source", 1), ("nothing", 1), ("drift", 0)]


def test_nagrobka_NIE_wskrzesza_gest_bez_jawnego_nadpisania():
    """Kubełkowe „Przypisz obiekt…" (bez `overwrite_weak`) nie ma prawa po cichu odwołać werdyktu:
    zdejmuje go wyłącznie DRUGI świadomy gest — „Przypisz obiekt" albo karta w pliku."""
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


# ═══════════════════════════════════════════ R-S2b-3 — PAMIĘĆ NAGROBKA I DROGA POWROTU


def _pamiec(con, fid):
    return con.execute("SELECT object_cleared_id FROM frame WHERE id = ?", (fid,)).fetchone()[0]


def _przywroc(con, fids, canon="LMC", oczekiwana_pamiec=None):
    """Przywrócenie idzie TĄ SAMĄ klingą, co nadanie (D-OW-2/B: jeden pisarz osi dla każdego gestu
    człowieka) — różni się wyłącznie guardem stanu i tym, skąd bierze kanon."""
    return repo.user_assign_object(con, alias_norm=None, canon=canon, catalog=None, kind="own",
                                   frame_ids=fids, now=NOW, overwrite_weak=True,
                                   expected_source="user_cleared",
                                   expected_cleared_id=oczekiwana_pamiec)


def test_nagrobek_PAMIETA_co_zdjal_a_przypisanie_te_pamiec_gasi():
    """SEDNO ODWRACALNOŚCI (migracja 0017). Do tej paczki nagrobek zapisywał sam FAKT odmowy bez
    jej PRZEDMIOTU, więc masowe cofnięcie nie miało drogi powrotu: odtworzenie stanu sprzed pomyłki
    kosztowało 6-8 interakcji plus pamięć CZŁOWIEKA o tym, co tam stało.

    Trzy przejścia w jednym teście, bo pamięć musi ginąć dokładnie wtedy, gdy ginie nagrobek —
    inaczej zostałaby wskazaniem na obiekt, którego ta klatka już nie odrzuca."""
    con = _baza([("light", "raw", None, rf"{R}\LIGHTS\LMC\a.ARW")])
    _przypisz(con, [1])
    oid = con.execute("SELECT object_id FROM frame WHERE id = 1").fetchone()[0]
    assert _pamiec(con, 1) is None                          # klatka z obiektem niczego nie odrzuca

    repo.clear_object_assignment(con, frame_ids=[1], now=NOW)
    assert _stan(con, 1) == (None, "user_cleared") and _pamiec(con, 1) == oid

    _przypisz(con, [1], overwrite_weak=True)                # …i pamięć gaśnie razem z nagrobkiem
    assert _stan(con, 1)[1] == "user" and _pamiec(con, 1) is None


def test_pamiec_nagrobka_wskazuje_OSTATNI_zdjety_obiekt():
    """FALSYFIKATOR WARIANTU „CZYTAJ Z DZIENNIKA": klatka cofnięta DWUKROTNIE ma dwa zdarzenia
    `object.cleared` o RÓŻNYM `was_object_id`, a payload nie mówi, który jest żywy. Stan mówi —
    bo jest jeden i opisuje TERAZ.

    To ta sama figura, którą repo dostało już trzy razy (pamięć `horreum-review-queue-from-state`):
    read-model liczony ze zdarzeń zamiast ze stanu."""
    con = _baza([("light", "raw", None, rf"{R}\LIGHTS\LMC\a.ARW")])
    _przypisz(con, [1], canon="LMC")
    repo.clear_object_assignment(con, frame_ids=[1], now=NOW)
    _przypisz(con, [1], canon="IC443", overwrite_weak=True)
    repo.clear_object_assignment(con, frame_ids=[1], now=NOW)

    assert _ev(con, "object.cleared") == 2, "dwa zdarzenia — dziennik ma z czego kłamać"
    ic = con.execute("SELECT id FROM object WHERE canon = 'IC443'").fetchone()[0]
    assert _pamiec(con, 1) == ic


def test_cofniecie_MOWI_co_zdjelo_takze_przy_kilku_obiektach():
    """Zdanie po geście podaje kanon — dokładnie jak bliźniacze zdanie nadania. Cofnięcie NIE ma
    bramki jednorodności (ma ją tylko NADANIE, bo tam brak jednego przedmiotu znaczy brak jednej
    nazwy do wpisania), więc jeden gest bywa gestem na kilku obiektach i lista musi być KOMPLETNA,
    a nie „pierwszy napotkany"."""
    con = _baza([("light", "raw", None, rf"{R}\LIGHTS\a.ARW"),
                 ("light", "raw", None, rf"{R}\LIGHTS\b.ARW")])
    _przypisz(con, [1], canon="LMC")
    _przypisz(con, [2], canon="IC443")
    g = repo.clear_object_assignment(con, frame_ids=[1, 2], now=NOW)
    assert sorted(g.canons) == ["IC443", "LMC"] and g.assigned == 2

    # …a gest, który NICZEGO nie zdjął, nie ma prawa nazwać obiektu, którego nie tknął
    assert repo.clear_object_assignment(con, frame_ids=[1, 2], now=NOW).canons == ()


def test_przywrocenie_ODDAJE_obiekt_i_POMIJA_klatke_ktora_nagrobkiem_byc_przestala():
    """GUARD DRYFU JEST W TRANSAKCJI, nie przed nią (`expected_source`). `expected_object_id` jest
    tu martwy Z DEFINICJI — nagrobek ma `object_id IS NULL`, więc jego gałąź się nie wykonuje.

    Falsyfikator: zdejmij `expected_source` z `_przywroc` → klatka 2 (nazwana ręką w międzyczasie)
    zostaje PRZEMALOWANA na cudzy kanon, zamiast policzyć się jako dryf."""
    con = _baza([("light", "raw", None, rf"{R}\LIGHTS\a.ARW"),
                 ("light", "raw", None, rf"{R}\LIGHTS\b.ARW")])
    _przypisz(con, [1, 2], canon="LMC")
    lmc = con.execute("SELECT id FROM object WHERE canon = 'LMC'").fetchone()[0]
    repo.clear_object_assignment(con, frame_ids=[1, 2], now=NOW)
    _przypisz(con, [2], canon="IC443", overwrite_weak=True)     # dryf: 2 przestała być nagrobkiem

    g = _przywroc(con, [1, 2])
    assert (g.assigned, g.skipped_drift) == (1, 1)
    assert _stan(con, 1) == (lmc, "user") and _pamiec(con, 1) is None
    assert con.execute("SELECT canon FROM object WHERE id = ?",
                       (_stan(con, 2)[0],)).fetchone()[0] == "IC443"


def test_guard_pyta_o_TRESC_nagrobka_a_nie_o_jego_ETYKIETE():
    """`expected_source` sprawdza, czy klatka JEST nagrobkiem; `expected_cleared_id` — czy jest
    nagrobkiem TEGO SAMEGO obiektu (bramka pakietu 0810, zarzut B#1).

    Sekwencja `cofnij LMC → nadaj IC443 → cofnij IC443` zostawia tę samą ETYKIETĘ (`user_cleared`)
    przy INNYM przedmiocie, więc przywracanie ze stęchłego odczytu zamalowałoby IC443 starszym
    LMC — po cichu, bo obie strony wyglądają na ekranie identycznie.

    Falsyfikator: zdejmij `expected_cleared_id` z wywołania → `assigned` rośnie do 1, a klatka
    kończy z kanonem `LMC`, którego ręka już raz odrzuciła."""
    con = _baza([("light", "raw", None, rf"{R}\LIGHTS\a.ARW")])
    _przypisz(con, [1], canon="LMC")
    lmc = con.execute("SELECT id FROM object WHERE canon = 'LMC'").fetchone()[0]
    repo.clear_object_assignment(con, frame_ids=[1], now=NOW)   # nagrobek LMC — TO widzi read-model
    assert _pamiec(con, 1) == lmc
    _przypisz(con, [1], canon="IC443", overwrite_weak=True)     # ręka wskazała jednak co innego
    repo.clear_object_assignment(con, frame_ids=[1], now=NOW)   # nagrobek IC443 — ta sama etykieta
    ic = con.execute("SELECT id FROM object WHERE canon = 'IC443'").fetchone()[0]
    assert _pamiec(con, 1) == ic and _stan(con, 1)[1] == "user_cleared"

    g = _przywroc(con, [1], oczekiwana_pamiec=lmc)              # gest ze STĘCHŁEGO odczytu
    assert (g.assigned, g.skipped_drift) == (0, 1)
    assert _pamiec(con, 1) == ic, "nagrobek IC443 nietknięty — zamalowanie byłoby cichą stratą"

    g = _przywroc(con, [1], canon="IC443", oczekiwana_pamiec=ic)   # świeży odczyt przechodzi
    assert g.assigned == 1 and _pamiec(con, 1) is None


def test_przywrocenie_JEST_idempotentne():
    """Drugi klik nie ma czego przywracać: klatka nie jest już nagrobkiem, więc `expected_source`
    liczy ją jako dryf i ZERO nowych eventów. Idempotencja jak reszta repo."""
    con = _baza([("light", "raw", None, rf"{R}\LIGHTS\a.ARW")])
    _przypisz(con, [1], canon="LMC")
    repo.clear_object_assignment(con, frame_ids=[1], now=NOW)
    _przywroc(con, [1])
    przed = con.execute("SELECT count(*) FROM event").fetchone()[0]
    g = _przywroc(con, [1])
    assert (g.assigned, g.skipped_drift) == (0, 1)
    assert con.execute("SELECT count(*) FROM event").fetchone()[0] == przed


def test_suma_gestow_NIE_gubi_rozbicia():
    """`ObjectGesture.__add__` jest JEDYNYM właścicielem składania — przywracanie idzie transakcja
    per OBIEKT, a zdanie po geście jest jedno. Druga siedziba tej sumy (`ConfirmPathObjectsDialog`)
    sumuje ręcznie dwa pola i przez to GUBI rozbicie per fakt; trzecia powtórzyłaby ten błąd.

    Kanony sklejają się bez powtórzeń: ta sama nazwa dwa razy w komunikacie wygląda jak dwa różne
    obiekty."""
    a = repo.ObjectGesture(assigned=2, skipped_kind=1, stacks=1, canons=("LMC",))
    b = repo.ObjectGesture(assigned=3, skipped_drift=4, canons=("IC443", "LMC"))
    s = a + b
    assert (s.assigned, s.skipped_kind, s.skipped_drift, s.stacks) == (5, 1, 4, 1)
    assert s.canons == ("LMC", "IC443")
    assert dict(s.skipped_breakdown)["drift"] == 4 and s.skipped == 5


def test_pamiec_nagrobka_JEDZIE_na_nastepczynie():
    """Werdykt ręki brzmi „to NIE jest X" — bez X zostałoby z niego samo „to nie jest".
    `transfer_human_facts` przenosi więc pamięć razem ze źródłem, w tym samym zapisie.

    To DRUGI powód, dla którego dziennik nie mógł być źródłem prawdy: tamta klinga emituje
    `object.cleared` BEZ klucza `was_object_id`, więc nagrobek przeniesiony miałby ślad
    w dzienniku, ale bez przedmiotu — wyparowałby z obu liczb naraz."""
    con = _baza([("light", "raw", None, rf"{R}\LIGHTS\a.ARW"),
                 ("light", "raw", None, None)])       # następczyni: ta sama ścieżka, nowa treść
    _przypisz(con, [1], canon="LMC")
    lmc = con.execute("SELECT id FROM object WHERE canon = 'LMC'").fetchone()[0]
    repo.clear_object_assignment(con, frame_ids=[1], now=NOW)
    con.execute("UPDATE frame SET superseded_by = 2 WHERE id = 1")
    con.commit()

    repo.transfer_human_facts(con, frame_id=1, now=NOW)
    assert _stan(con, 2) == (None, "user_cleared") and _pamiec(con, 2) == lmc


def test_przywrocenie_ZDEJMUJE_populacje_u_WSZYSTKICH_jej_czytelnikow():
    """Gest zdejmuje stan STICKY, a populację nagrobków liczą TRZY powierzchnie osobno. Bramka pyta
    o każdą, bo rozjazd którejkolwiek przechodziłby na zielono, gdyby pytać o jedną: spis faktów
    ręki, kolejka przeglądu i delta przebiegu."""
    from horreum import audit
    from horreum.gui import queries
    con = _baza([("light", "raw", None, rf"{R}\LIGHTS\a.ARW"),
                 ("light", "raw", None, rf"{R}\LIGHTS\b.ARW")])
    _przypisz(con, [1, 2], canon="LMC")
    repo.clear_object_assignment(con, frame_ids=[1, 2], now=NOW)

    przed = audit.human_facts_census(con)
    assert przed.object_cleared == 2
    assert len(queries.review_frame_ids(con)) == 2
    assert resolver.run_resolver(con, now=NOW).objects_user_cleared == 2

    _przywroc(con, [1, 2])

    po = audit.human_facts_census(con)
    assert po.object_cleared == 0
    # UBYTEK NA OSI NAGROBKÓW NIE JEST NARUSZENIEM „ręki nietykalnej": warunek broni ręki przed
    # WJAZDEM MATERIAŁU, a nie przed drugim gestem tej samej ręki, i dokładnie tak zachowuje się
    # dziś istniejąca droga „Przypisz obiekt" na nagrobku.
    #
    # OŚ `object_hand` STOI, i to jest POMIAR, nie założenie: `TRANSFERABLE_OBJECT_SOURCES` =
    # `STICKY | WEAK`, więc `user_cleared` JUŻ się do niej liczy (docstring `human_facts_census`
    # mówi to wprost: „`object_hand` już go obejmuje jako źródło"). Przywrócenie przenosi klatkę
    # między dwoma RODZAJAMI faktu ręki, a nie z niebytu do faktu — suma faktów ręki się nie
    # rusza. Pierwsza wersja tej bramki twierdziła `+2` i została obalona własnym przebiegiem.
    assert po.object_hand == przed.object_hand == 2
    assert not queries.review_frame_ids(con)
    assert resolver.run_resolver(con, now=NOW).objects_user_cleared == 0
