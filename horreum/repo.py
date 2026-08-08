"""JEDNA KLINGA — jedyne drzwi do zapisu domenowego (PLAN §2).

Wzorzec przeniesiony z `custos/commit/mover.py` (jedyny obramkowany dom dla destrukcyjnego
ostrza) i przełożony na ZAPIS DO BAZY: każdy INSERT/UPDATE encji domenowej przechodzi przez
ten moduł, który **w tej samej transakcji** emituje wpis do `event`. Żaden inny moduł nie
wykonuje DML na tabelach domenowych — pilnuje tego statyczny meta-tripwir AST
(`tests/test_repo_safety.py`) od commitu zero (odpowiednik zakazu `os.rename` poza mover.py).

Zasady:
- Tożsamość zmian, nie destrukcja: zmiana stanu = APPEND `event` + zapis wskaźnika, nigdy
  kasacja historii (PLAN §6).
- Zero cichych porażek: nierozstrzygalny config/obiekt → `event(*.review)` (warstwa skanu),
  nigdy ciche zgadywanie.
- `now` podawany jawnie (ISO-8601) — deterministyczne testy, jak `now_fn` w Custosie.
"""
import json
from contextlib import contextmanager
from dataclasses import dataclass

from .resolve._text import norm_alnum          # kierunek repo → resolve (liść; COHESION §2b)
from .resolve.catalog import catalog_canon      # gramatyka katalogowa — CZYSTA, bez assetu (liść)
from .resolve.frames import LIGHT_KINDS         # guard RODZAJU w klindze (S2b) — liść, bez cyklu
from .resolve.objects import (CLEARABLE_OBJECT_SOURCES,  # enum źródeł osi OBIEKT —
                              OBJECT_SOURCES,           # jeden właściciel (S1/S2b)
                              TRANSFERABLE_OBJECT_SOURCES,   # …i przeżywające podmianę (R4)
                              WEAK_OBJECT_SOURCES)
from .resolve.observatory import nearest_site   # kierunek repo → resolve (liść math/re; COHESION §2b)


@contextmanager
def _immediate(con):
    """Transakcja z write-lockiem OD STARTU (`BEGIN IMMEDIATE`) — guard+write atomowo wobec
    równoległego writera (PLAN_gui §2, P1: WAL serializuje writerów, ale NIE zwalnia z atomowości
    czytaj-sprawdź-pisz). Domyślny `with con:` bierze tylko lock przy pierwszym DML, więc SELECT
    guardu i UPDATE mogłyby objąć cudzy commit (TOCTOU). Tu RESERVED lock blokuje innych od razu.
    Używane przez zapisy usera (label/approve/merge/unmerge), gdzie guard MUSI trzymać do UPDATE."""
    con.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        con.rollback()
        raise
    else:
        con.commit()


def emit_event(con, *, actor, verb, target, now, payload=None, reason=None):
    """Dopisz zdarzenie do append-only `event`. Wołane WYŁĄCZNIE z tego modułu, w tej samej
    transakcji co zapis, który opisuje."""
    con.execute(
        "INSERT INTO event(ts, actor, verb, target, payload, reason) VALUES (?, ?, ?, ?, ?, ?)",
        (now, actor, verb, target,
         json.dumps(payload, ensure_ascii=False) if payload is not None else None,
         reason),
    )


def upsert_camera(con, *, model_canon, pixel_um, is_mono, is_mono_source,
                  raw_instrume, now, actor="scan"):
    """Wyłoń kamerę (oś) ze skanu. Tożsamość = `model_canon` (UNIQUE); `pixel_um` to NULLABLE
    WŁAŚCIWOŚĆ (brief §3/R1#3 — po naprawie nagłówków model rozstrzyga tożsamość, piksel bywa
    nieobecny, np. Sony masterflat bez XPIXSZ).

    Nowa → INSERT + `camera.upserted` w tej samej transakcji; (id, True). Istnieje → (id, False),
    a piksel jest UZUPEŁNIANY/PILNOWANY (R2#4 + R3-c1):
      - wiersz ma `pixel_um IS NULL`, przyszła wartość → **CAS jednym statementem**
        (`UPDATE ... WHERE id=? AND pixel_um IS NULL`) + `event(camera.pixel_set)`; rowcount=0
        (równoległy writer wygrał — WAL sankcjonuje GUI+CLI naraz) → re-SELECT i gałąź konfliktu;
      - wiersz ma INNĄ wartość → **STAN `pixel_conflict=1`** (kolejka ze stanu, rama §0) +
        `event(camera.pixel_conflict)` (osobny verb, target `camera:` — R3-c3); przejście stanu
        emitowane RAZ (gating na rowcount). Zdjęcie konfliktu = przyszłe `resolve_camera_pixel` (§7).
    """
    row = con.execute(
        "SELECT id, pixel_um FROM camera WHERE model_canon = ?", (model_canon,)).fetchone()
    if row is None:
        with con:  # atomowo: INSERT camera + INSERT event (albo żadne — rollback)
            cur = con.execute(
                "INSERT INTO camera(model_canon, pixel_um, is_mono, is_mono_source, "
                "raw_instrume, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (model_canon, pixel_um, is_mono, is_mono_source, raw_instrume, now),
            )
            camera_id = cur.lastrowid
            emit_event(
                con, actor=actor, verb="camera.upserted", target=f"camera:{camera_id}",
                now=now,
                payload={"model_canon": model_canon, "pixel_um": pixel_um,
                         "is_mono": is_mono, "is_mono_source": is_mono_source},
            )
        return camera_id, True

    camera_id, existing_px = row["id"], row["pixel_um"]
    if pixel_um is None or existing_px == pixel_um:
        return camera_id, False                       # nic do uzupełnienia / zgodne — no-op

    if existing_px is None:
        with con:  # CAS: uzupełnij TYLKO gdy wciąż NULL (bez lost-update między writerami)
            cur = con.execute(
                "UPDATE camera SET pixel_um = ? WHERE id = ? AND pixel_um IS NULL",
                (pixel_um, camera_id))
            if cur.rowcount:
                emit_event(con, actor=actor, verb="camera.pixel_set",
                           target=f"camera:{camera_id}", now=now,
                           payload={"pixel_um": pixel_um})
        if cur.rowcount:
            return camera_id, False
        existing_px = con.execute(                    # CAS przegrany — kto był szybszy?
            "SELECT pixel_um FROM camera WHERE id = ?", (camera_id,)).fetchone()[0]
        if existing_px == pixel_um:
            return camera_id, False                   # równoległy writer wpisał to samo

    with con:  # rozjazd wartości → STAN pixel_conflict (event raz, na przejściu 0→1)
        cur = con.execute(
            "UPDATE camera SET pixel_conflict = 1 WHERE id = ? AND pixel_conflict = 0",
            (camera_id,))
        if cur.rowcount:
            emit_event(con, actor=actor, verb="camera.pixel_conflict",
                       target=f"camera:{camera_id}", now=now,
                       payload={"pixel_existing": existing_px, "pixel_new": pixel_um})
    return camera_id, False


def upsert_frame(con, *, sha1_data, sha1_data_uncomputable=0, kind, filetype, camera_id,
                 now, actor="scan", kind_source=None):
    """Wyłoń frame po `sha1_data` (tożsamość = odcisk sekcji DANYCH — przeżywa edycję nagłówka/
    rename/move/writeback; brief §2). Istnieje → zwróć (id, False) BEZ zmiany tożsamości — drugie
    wystąpienie to nowa LOKALIZACJA (`add_location`), nie nowy frame. Nowy → INSERT frame +
    `event(frame.observed)` w tej samej transakcji; (id, True).

    `sha1_data_uncomputable=1` = degeneracja: odcisk danych nieobliczalny, `sha1_data` niesie
    sha1 CAŁEGO pliku (lekcja v3 dawcy) — legalne WYŁĄCZNIE dla ścieżki nieznanej (R3-b1).
    `camera_id` może być None (oś nierozstrzygnięta → `flag_camera_review` w warstwie skanu).
    `kind_source` (#2) = prowieniencja rodzaju ('header'|'path'|None) — jawne, nie domyślane.
    Fakty kopii (rozmiar, hashe pliku) mieszkają na location, nie tu (R2#6)."""
    row = con.execute("SELECT id FROM frame WHERE sha1_data = ?", (sha1_data,)).fetchone()
    if row is not None:
        return row[0], False

    with con:  # atomowo: INSERT frame + INSERT event
        cur = con.execute(
            "INSERT INTO frame(sha1_data, sha1_data_uncomputable, kind, kind_source, filetype, "
            "camera_id, first_seen_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (sha1_data, sha1_data_uncomputable, kind, kind_source, filetype, camera_id, now),
        )
        frame_id = cur.lastrowid
        emit_event(
            con, actor=actor, verb="frame.observed", target=f"frame:{frame_id}", now=now,
            payload={"sha1_data": sha1_data, "uncomputable": sha1_data_uncomputable,
                     "kind": kind, "kind_source": kind_source, "filetype": filetype,
                     "camera_id": camera_id},
        )
    return frame_id, True


def add_location(con, *, frame_id, volume, path, drive_letter=None, tier=None, mtime=None,
                 file_sha1=None, header_hash=None, hdu_index=None, compressed=None,
                 size_bytes=None, now, actor="scan"):
    """Dołóż lokalizację frame'a po `UNIQUE(volume, path)` wraz z faktami KOPII (file_sha1/
    header_hash/hdu_index/compressed/size_bytes — brief §2; NULL-e dla XISF/W1). Już znana →
    (id, False) bez eventu i BEZ dotykania faktów (odświeżenie = `refresh_location`, osobny
    kontrakt). Nowa → INSERT + `event(location.added)`; (id, True). `volume` = trwały
    identyfikator wolumenu; placeholder '?' NIE blokuje skanu (to nie tożsamość frame'a, §7.5).
    `drive_letter` to efemeryczny cache wyświetlania."""
    row = con.execute(
        "SELECT id FROM location WHERE volume = ? AND path = ?", (volume, path)).fetchone()
    if row is not None:
        return row[0], False

    with con:  # atomowo: INSERT location + INSERT event
        # FORWARD-GUARD (#13): `unreadable_since` NIE ustawiane tu — DEFAULT NULL (czytelna do
        # dowodu). Ścieżka NIEZNANA-nieczytelna ma już ślad w STANIE: frame-szkielet bez `header`
        # (kubełek `headerless`). Marker znaczy „kopia JEST nieczytelna" (BIEŻĄCY fakt — ostatnia
        # próba odczytu nieudana), NIE „stała się nieczytelna po byciu czytelną": ustawia go WYŁĄCZNIE
        # re-odczyt ZNANEJ ścieżki (`refresh_location_unreadable`). Skutek świadomy: kubełek `unreadable`
        # bywa RÓŻNY między trybami bramy — przy `volume='?'` re-skan oznaczy też kopię nigdy-nie-czytelną,
        # przy bramie ON pominie ją (marker NULL → brama skipuje). Issue zakresuje #13 do re-odczytu, nie tu.
        cur = con.execute(
            "INSERT INTO location(frame_id, volume, drive_letter, path, tier, mtime, "
            "file_sha1, header_hash, hdu_index, compressed, size_bytes, last_verified_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (frame_id, volume, drive_letter, path, tier, mtime,
             file_sha1, header_hash, hdu_index, compressed, size_bytes, now),
        )
        location_id = cur.lastrowid
        emit_event(
            con, actor=actor, verb="location.added", target=f"frame:{frame_id}", now=now,
            payload={"volume": volume, "path": path, "tier": tier},
        )
    return location_id, True


# Kolumny-fakty kopii na location — wspólna lista dla diffu w `refresh_location`. `unreadable_since`
# TU (#13): przejście markera (np. udany odczyt gaszący go przy niezmienionym mtime) samo w sobie
# jest zmianą faktu kopii — bez tego early-return `not changed` nigdy by markera nie zgasił.
# `present` TU (P5/D-V-6): udany re-odczyt DOWODZI obecności, więc powrót kopii (0→1) jest zmianą
# faktu i idzie do payloadu `location.refreshed` — ślad zmartwychwstania bez osobnego czasownika.
# SPOT: każda nazwa z tej krotki MUSI występować w literale UPDATE niżej (pinuje test strukturalny
# `test_presence.py::test_location_facts_pokrywaja_update`) — inaczej diff wykrywa zmianę, której
# UPDATE nie zapisuje, i event leci w nieskończoność co skan.
_LOCATION_FACTS = ("mtime", "file_sha1", "header_hash", "hdu_index", "compressed", "size_bytes",
                   "unreadable_since", "present")


def rebind_location(con, *, location_id, frame_after, now, actor="scan"):
    """PODMIANA TREŚCI pod znaną ścieżką (R3-b1): przepnij `location.frame_id` na nową tożsamość
    + `event(location.rebound)` `{frame_before, frame_after}`. Stary frame ZOSTAJE (append-only,
    historia w eventach) — bez ŻADNEJ lokacji. UWAGA (P5): pass zniknięć takiego frame'a NIE
    podchwyci — działa na LOKACJACH, a tu nie została ani jedna (`vanished_frames` też go wyklucza
    guardem `EXISTS`, `gui/queries.py:516-520`). Licznik `orphan_frames` = osobna, tania decyzja;
    dopóki jej nie ma, osierocone frame'y są widoczne wyłącznie przez `location.rebound`. Już przepięta → False
    (idempotencja). Guard+UPDATE w `_immediate` (TOCTOU wobec równoległego writera)."""
    with _immediate(con):
        row = con.execute(
            "SELECT frame_id FROM location WHERE id = ?", (location_id,)).fetchone()
        if row is None:
            raise ValueError(f"location:{location_id} nie istnieje")
        frame_before = row["frame_id"]
        if frame_before == frame_after:
            return False
        con.execute("UPDATE location SET frame_id = ? WHERE id = ?", (frame_after, location_id))
        emit_event(con, actor=actor, verb="location.rebound", target=f"location:{location_id}",
                   now=now, payload={"frame_before": frame_before, "frame_after": frame_after})
    return True


def mark_superseded(con, *, frame_id, superseded_by, now, actor="supersede"):
    """ZASTĄPIENIE tożsamości (#DR2/R4, D-DR-4): `frame.superseded_by` + `event(frame.superseded)`.
    Jedyna droga zapisu tej kolumny. Dowód zbiera wołający (`supersede.backfill`: replay dziennika
    `location.rebound`; skan: gałąź podmiany treści `scan.py:1248`).

    APPEND-ONLY: klatka ZOSTAJE — z nagłówkiem, kartami i historią. Zmienia się jedno twierdzenie:
    „ta tożsamość jest bieżąca" → „niesie ją dziś klatka N". Droga w drugą stronę istnieje
    i jest jawna (`clear_superseded`), bo powrót treści pod ścieżkę jest zwykłym faktem, nie awarią.

    GUARD ŻYWOTNOŚCI (W8, blokujący): klatka z JAKĄKOLWIEK obecną lokacją NIE jest zastąpiona —
    `frame` ma 1:N `location`, więc ten sam plik potrafi leżeć pod dwiema ścieżkami, a podmiana
    jednej kopii nie czyni drugiej duchem. Bez tego guarda backfill z dziennika oznaczyłby klatki
    ŻYWE pod inną ścieżką, a `object_exposure` przestałby liczyć ich godziny. Zwraca `False`
    (wołający zlicza `alive`), ZERO zapisu.

    KONFLIKT ŁAŃCUCHA (EXPECT): klatka już zastąpiona przez INNĄ tożsamość → `ValueError`, nie
    ciche nadpisanie. Druga podmiana dokłada ogniwo NA NASTĘPCZYNI (A→B, potem B→C); żądanie
    zmiany A→B na A→C znaczy, że wołający pomylił ogniwo — a nadpisanie zgubiłoby wersję środkową.

    Cyklu tu nie sprawdzamy dłuższego niż własny (DDL łapie `superseded_by = id`): pełny obchód
    łańcucha wymaga ZNAJOMOŚCI CAŁEJ mapy, którą ma pass — klinga widzi jedną parę. Podział jak
    przy hamulcu `presence`: klinga broni wiersza, pass broni przebiegu.

    ZWRACA bool: `True` = oznaczono; `False` = klatka żywa ALBO już oznaczona tą samą tożsamością
    (idempotencja powtórnego przebiegu — bez UPDATE i bez eventu, QUIET)."""
    if frame_id == superseded_by:
        raise ValueError(f"frame:{frame_id} nie może zastąpić samej siebie")
    with _immediate(con):
        row = con.execute(
            "SELECT superseded_by FROM frame WHERE id = ?", (frame_id,)).fetchone()
        if row is None:
            raise ValueError(f"frame:{frame_id} nie istnieje")
        if con.execute("SELECT 1 FROM frame WHERE id = ?", (superseded_by,)).fetchone() is None:
            raise ValueError(f"frame:{superseded_by} (następczyni) nie istnieje")
        if row["superseded_by"] == superseded_by:
            return False
        if row["superseded_by"] is not None:
            raise ValueError(
                f"frame:{frame_id} jest już zastąpiona przez frame:{row['superseded_by']}, "
                f"a żądano frame:{superseded_by} — ogniwo dokłada się na następczyni")
        if con.execute(
                "SELECT 1 FROM location WHERE frame_id = ? AND present = 1",
                (frame_id,)).fetchone() is not None:
            return False
        con.execute("UPDATE frame SET superseded_by = ? WHERE id = ?", (superseded_by, frame_id))
        emit_event(con, actor=actor, verb="frame.superseded", target=f"frame:{frame_id}",
                   now=now, payload={"superseded_by": superseded_by})
    return True


@dataclass
class FactTransfer:
    """Co przeszło z klatki zastąpionej na jej następczynię (R4). `object_moved` = przeniesiono
    oś obiektu (także NAGROBEK, który jest werdyktem „ta klatka obiektu NIE ma"); `config_moved`
    = przeniesiono oś sprzętu wskazaną ręką (R1);
    `skipped` = powód pominięcia, gdy nic nie przeszło — GUI ma mówić DLACZEGO, nie milczeć."""
    object_moved: bool = False
    config_moved: bool = False
    skipped: str = ""          # "" = nic nie pominięto (konwencja liczników z `ObjectGesture`)


def transfer_human_facts(con, *, frame_id, now, actor="user:local"):
    """PRZENIESIENIE FAKTÓW CZŁOWIEKA z klatki zastąpionej na następczynię (R4, D-DR-4).

    Przenosimy WYŁĄCZNIE to, czego maszyna nie odtworzy: oś obiektu ze źródła ręki
    (`TRANSFERABLE_OBJECT_SOURCES` — wskazanie palcem, potwierdzenie propozycji ze ścieżki
    i nagrobek `user_cleared`). Nie przenosimy niczego, co wyliczy resolver i grouper — kind,
    kamera, filtr i rozpoznanie z nagłówka wracają same przy najbliższym przebiegu, a przeniesione
    ręcznie byłyby DRUGĄ derywacją tego samego faktu.

    DLACZEGO GEST, A NIE AUTOMAT SKANU (§0 briefu): skan zapisuje OBSERWACJĘ (pod tą ścieżką leży
    inna treść) i to jest fakt. Przeniesienie werdyktu jest OSĄDEM — człowiek stwierdza, że nowy
    plik to nadal to samo zdjęcie tego samego obiektu, a nie inne ujęcie wgrane pod tę nazwę.
    Automat nie ma jak tego rozstrzygnąć i przy pomyłce zamalowałby fakt cudzą decyzją.

    NASTĘPCZYNI NIETKNIĘTA RĘKĄ (guard): przenosimy tylko, gdy jej `object_source IS NULL` — czyli
    gdy NIC o niej dotąd nie orzeczono. Klatka, która ma już własne źródło (nagłówek, xref, region
    albo drugi gest), przemówiła sama i cudzy werdykt nie ma prawa jej nadpisać. Zwraca wtedy
    `skipped='nastepczyni ma wlasne zrodlo'`.

    PARYTET §5.9 UTRZYMANY: przypisanie obiektu emituje `object.assigned` (stan `frame.object_id`
    rośnie o 1, dziennik też), a NAGROBEK — `object.cleared` BEZ `object.assigned`, bo `object_id`
    zostaje NULL i licznik nie drgnął. Emisja „na wszelki wypadek" obu rozjechałaby audyt.

    STARA KLATKA ZOSTAJE NIETKNIĘTA (append-only): jej fakty są historią, nie duplikatem —
    z rachunku godzin i tak wypada przez `superseded_by` (`queries.object_exposure`).

    DRUGA OŚ: RĘCZNY CONFIG (R1, `STICKY_CONFIG_SOURCES`) — i jej guard MUSI brzmieć inaczej niż
    guard obiektu, bo kolumny znaczą co innego. `object_source` niepuste znaczy „coś ją nazwało"
    (także automat), więc pyta się o NIEPUSTOŚĆ. `config_source` zapisuje WYŁĄCZNIE ręka (0015:
    automat zostawia NULL), więc ten sam predykat przepuszczałby zawsze — pytamy zatem o oś
    W CAŁOŚCI: przenosimy, gdy następczyni nie ma ANI werdyktu ręki, ANI configu z nagłówka.
    Klatka, której grouper policzył zestaw z jej WŁASNEGO zeznania, przemówiła sama.

    CO DOŁĄCZY PÓŹNIEJ, świadomie i z powodem: **werdykty rodowodu**
    (`integration_input.excluded`; zmierzona populacja na żywym archiwum: **0**, a pierwszy RAW
    wejdzie do rodowodu dopiero po GO-2 — kod na populację zerową byłby zgadywaniem kształtu).

    Zwraca `FactTransfer`. Idempotentne: powtórzenie po udanym przeniesieniu trafia w guardy obu
    osi (następczyni ma już swoje) i zwraca `skipped` bez zapisu."""
    with _immediate(con):
        stara = con.execute(
            "SELECT superseded_by, object_id, object_source, config_id, config_source "
            "FROM frame WHERE id = ?", (frame_id,)).fetchone()
        if stara is None:
            raise ValueError(f"frame:{frame_id} nie istnieje")
        if stara["superseded_by"] is None:
            raise ValueError(f"frame:{frame_id} nie jest zastąpiona — nie ma dokąd przenosić")
        ma_obiekt = stara["object_source"] in TRANSFERABLE_OBJECT_SOURCES
        # Człon `config_id IS NOT NULL` nie jest nadmiarowy, choć klinga zapisuje oba pola razem:
        # bez niego para (źródło ręki, oś pusta) — gdyby kiedykolwiek powstała — emitowałaby
        # `config.assigned` przy `frame.config_id` dalej NULL, czyli rozjeżdżała parytet `audit.py`
        # o cichy wiersz. Oś obiektu tego członu NIE MA celowo: tam NULL bywa WERDYKTEM (nagrobek).
        ma_config = (stara["config_source"] in STICKY_CONFIG_SOURCES
                     and stara["config_id"] is not None)
        if not ma_obiekt and not ma_config:
            return FactTransfer(skipped="brak faktow czlowieka")
        nowa_id = stara["superseded_by"]
        nowa = con.execute(
            "SELECT kind, camera_id, object_source, config_id, config_source FROM frame "
            "WHERE id = ?", (nowa_id,)).fetchone()
        if nowa is None:
            raise ValueError(f"frame:{nowa_id} (następczyni) nie istnieje")
        obiekt_do_przeniesienia = ma_obiekt and nowa["object_source"] is None
        # ZESTAW PRZECHODZI TYLKO NA KLATKĘ, KTÓRA GO UNIESIE (bramka pakietu 3a, zarzut 4).
        # Docstring twierdził, że kamera obu tożsamości jest ta sama, „bo to ten sam plik" — i to
        # jest ZAŁOŻENIE, nie sprawdzenie: podmieniona treść ma własne zeznanie, więc może przyjść
        # z innym `INSTRUME` albo z innym `IMAGETYP`. Bez tych dwóch warunków przeniesienie
        # zapisywałoby config CUDZEJ kamery (łamiąc inwariant DDL §1 `config.camera_id ==
        # frame.camera_id`) albo zestaw NA KALIBRACJI (łamiąc kind-scoping) — i to klingą, która
        # w obu wypadkach sama sobie zaprzecza.
        from .grouper import NO_TELESCOPE_KINDS          # import odroczony (cykl repo↔grouper)

        kamera_zestawu = None
        if ma_config:
            wiersz = con.execute(
                "SELECT camera_id FROM config WHERE id = ?", (stara["config_id"],)).fetchone()
            kamera_zestawu = wiersz["camera_id"] if wiersz is not None else None
        config_do_przeniesienia = (
            ma_config and nowa["config_source"] is None and nowa["config_id"] is None
            and nowa["kind"] not in NO_TELESCOPE_KINDS
            and kamera_zestawu is not None and nowa["camera_id"] == kamera_zestawu)
        if not obiekt_do_przeniesienia and not config_do_przeniesienia:
            # POWÓD MA BYĆ PRAWDZIWY, nie jeden dla wszystkich odmów: „następczyni ma własne
            # źródło" i „zestaw do niej nie pasuje" to dwa różne stany i dwie różne dalsze drogi
            # (w pierwszym nie ma nic do roboty, w drugim ręka musi wskazać zestaw od nowa).
            nie_pasuje = ma_config and (nowa["config_source"] is None
                                        and nowa["config_id"] is None)
            return FactTransfer(skipped="zestaw nie pasuje do nastepczyni" if nie_pasuje
                                else "nastepczyni ma wlasne zrodlo")

        if obiekt_do_przeniesienia:
            con.execute("UPDATE frame SET object_id = ?, object_source = ? WHERE id = ?",
                        (stara["object_id"], stara["object_source"], nowa_id))
            if stara["object_id"] is None:
                emit_event(con, actor=actor, verb="object.cleared", target=f"frame:{nowa_id}",
                           now=now, payload={"przeniesione_z": frame_id,
                                             "was_source": stara["object_source"]},
                           reason="nagrobek przeniesiony po podmianie pliku")
            else:
                emit_event(con, actor=actor, verb="object.assigned", target=f"frame:{nowa_id}",
                           now=now, payload={"object_id": stara["object_id"],
                                             "object_source": stara["object_source"],
                                             "przeniesione_z": frame_id},
                           reason="fakt ręki przeniesiony po podmianie pliku")
        if config_do_przeniesienia:
            # Zestaw przechodzi TAKI SAM, nie przeliczony: config to iloczyn (teleskop × kamera),
            # a kamera obu tożsamości jest ta sama — to ten sam plik, więc to samo zeznanie EXIF.
            # Przeliczanie iloczynu tutaj byłoby DRUGĄ derywacją tego samego faktu (§0 briefu).
            con.execute("UPDATE frame SET config_id = ?, config_source = ? WHERE id = ?",
                        (stara["config_id"], stara["config_source"], nowa_id))
            emit_event(con, actor=actor, verb="config.assigned", target=f"frame:{nowa_id}",
                       now=now, payload={"config_id": stara["config_id"],
                                         "config_source": stara["config_source"],
                                         "przeniesione_z": frame_id},
                       reason="zestaw wskazany ręką przeniesiony po podmianie pliku")
    return FactTransfer(object_moved=obiekt_do_przeniesienia,
                        config_moved=config_do_przeniesienia)


def clear_superseded(con, *, frame_id, now, actor="scan"):
    """POWRÓT TREŚCI pod ścieżkę (D-DR-4): `superseded_by = NULL` + `event(frame.supersede_cleared)`.
    Klatka nie może być jednocześnie żywa i zastąpiona — a cykl `A → B → A` (edycja i cofnięcie
    edycji w programie graficznym) jest zwykłym gestem człowieka, nie awarią.

    Wołane ze skanu w gałęzi podmiany treści: lokacja wraca na tożsamość, która była oznaczona,
    więc oznaczenie przestało być prawdą w tej samej chwili. Nie gaśnie samo z upływem czasu
    ani przy przebiegu passu — gasi je wyłącznie DOWÓD, czyli ponowny odczyt tej treści z dysku.

    Idempotentne: `superseded_by` już NULL → `False` bez UPDATE i bez eventu."""
    with _immediate(con):
        row = con.execute(
            "SELECT superseded_by FROM frame WHERE id = ?", (frame_id,)).fetchone()
        if row is None:
            raise ValueError(f"frame:{frame_id} nie istnieje")
        if row["superseded_by"] is None:
            return False
        con.execute("UPDATE frame SET superseded_by = NULL WHERE id = ?", (frame_id,))
        emit_event(con, actor=actor, verb="frame.supersede_cleared", target=f"frame:{frame_id}",
                   now=now, payload={"superseded_by_before": row["superseded_by"]})
    return True


def refresh_location(con, *, location_id, frame_id, mtime, file_sha1, header_hash,
                     hdu_index, compressed, size_bytes, unreadable_since, present, now,
                     actor="scan", raw_json=None, cards=None, hot_fields=None, camera_id=None,
                     kind=None):
    """Re-odczyt ZNANEJ `(volume, path)` o NIEZMIENIONEJ tożsamości frame'a — kontrakt pełny
    brief §2 (R1#10 + R2#2/#7 + R3-b), domyka dług „mtime po re-odczycie nieaktualizowany":

    - fakty kopii bez zmian → False-owy wynik, ZERO eventów (idempotentny re-skan);
    - zmiana faktów → UPDATE + JEDEN `event(location.refreshed)` z `{before, after}` pól zmienionych;
    - **zmiana `header_hash` ⇒ ODŚWIEŻENIE ZEZNANIA** (writeback fitsmirror — R2#2): pełny
      re-record `header` (raw_json + WSZYSTKIE pola gorące) + WYMIANA `cards` (R3-b4) + JEDEN
      `event(header.refreshed)` `{header_hash_before, header_hash_after}`; w TEJ SAMEJ transakcji
      przeliczenie pochodnych frame'a (R3-b2): `frame.camera_id`/`kind` z nowego zeznania →
      UPDATE + `event(frame.rederived)` (inaczej config budowany na stęchłej kamerze).
      Zeznanie odświeża OSTATNI re-odczyt (last-read-wins).
    - **`unreadable_since` (#13)**: marker czytelności kopii — jeden z faktów kopii (`_LOCATION_FACTS`),
      więc jego przejście SAMO jest zmianą. Udany odczyt podaje `None` → marker gaśnie (nawet gdy
      pozostałe fakty identyczne, np. wyzdrowienie transientu przy tym samym mtime); rekord nieczytelny
      przez degenerację podaje istniejący/nowy timestamp → marker zostaje/powstaje. Ślad wyzdrowienia
      idzie do payloadu `location.refreshed` jako `{unreadable_since: {before, after}}`. Parametr
      WYMAGANY (bez domyślnego): `None` znaczy „POTWIERDZAM udany odczyt pliku", nie „nie wiem" —
      domyślne `None` byłoby cichym wektorem gaszenia alarmu, gdyby wołający zapomniał go policzyć.
    - **`present` (P5, D-V-6)**: obecność kopii — TEN SAM reżim dowodowy co `unreadable_since`.
      Parametr WYMAGANY: `1` znaczy „POTWIERDZAM, że plik pod tą ścieżką ISTNIEJE" (wołający właśnie
      go zestatował/przeczytał), nie „pewnie jest". Zmartwychwstanie (0→1) jest zmianą faktu, więc
      idzie do payloadu `location.refreshed` — pass obecności nie musi go osobno wykrywać.
      Domyślnej wartości NIE dodawać: przesłanka „każdy wołający właśnie czytał plik" jest prawdziwa
      przez przypadek, nie przez kontrakt (`import_fitsmirror` karmi `ingest_record` z cache'u dawcy).
      Zdejmowanie obecności (1→0) NIE należy tu — to `mark_location_vanished` (dowód nieobecności).

    `hot_fields` = dict kolumn `header` (jak `extract_header`); `camera_id`/`kind` = pochodne
    POLICZONE przez wołającego z nowego dictu (emergencja kamery = osobny, idempotentny
    `upsert_camera` przed wołaniem). Zwraca dict
    `{"facts": bool, "header": bool, "rederived": bool}`. Wymiana `cards` (DELETE+INSERT) to
    jedyna sankcjonowana kasacja: cards są LUSTREM bieżącego zeznania, nie historią —
    historia mieszka w `event`."""
    after = {"mtime": mtime, "file_sha1": file_sha1, "header_hash": header_hash,
             "hdu_index": hdu_index, "compressed": compressed, "size_bytes": size_bytes,
             "unreadable_since": unreadable_since, "present": present}
    result = {"facts": False, "header": False, "rederived": False}
    with _immediate(con):
        row = con.execute(
            "SELECT mtime, file_sha1, header_hash, hdu_index, compressed, size_bytes, "
            "unreadable_since, present FROM location WHERE id = ?", (location_id,)).fetchone()
        if row is None:
            raise ValueError(f"location:{location_id} nie istnieje")
        changed = {k: {"before": row[k], "after": after[k]}
                   for k in _LOCATION_FACTS if row[k] != after[k]}
        if not changed:
            return result
        con.execute(
            "UPDATE location SET mtime = ?, file_sha1 = ?, header_hash = ?, hdu_index = ?, "
            "compressed = ?, size_bytes = ?, unreadable_since = ?, present = ?, "
            "last_verified_at = ? WHERE id = ?",
            (mtime, file_sha1, header_hash, hdu_index, compressed, size_bytes, unreadable_since,
             present, now, location_id))
        emit_event(con, actor=actor, verb="location.refreshed",
                   target=f"location:{location_id}", now=now, payload=changed)
        result["facts"] = True

        if "header_hash" not in changed or raw_json is None:
            return result
        hot = dict(hot_fields or {})
        g = hot.get
        cur = con.execute(
            "UPDATE header SET raw_json = ?, date_obs = ?, exptime = ?, filter_raw = ?, "
            "instrume = ?, telescop = ?, focallen = ?, focratio_raw = ?, xpixsz = ?, ypixsz = ?, "
            "gain = ?, offset_adu = ?, ccd_temp = ?, usblimit = ?, xbinning = ?, ybinning = ?, "
            "bayerpat = ?, ra_deg = ?, dec_deg = ?, object_raw = ? WHERE frame_id = ?",
            (raw_json, g("date_obs"), g("exptime"), g("filter_raw"), g("instrume"),
             g("telescop"), g("focallen"), g("focratio_raw"), g("xpixsz"), g("ypixsz"),
             g("gain"), g("offset_adu"), g("ccd_temp"), g("usblimit"), g("xbinning"),
             g("ybinning"), g("bayerpat"), g("ra_deg"), g("dec_deg"), g("object_raw"),
             frame_id))
        if cur.rowcount == 0:                         # frame bez zeznania (brzeg) → INSERT
            con.execute(
                "INSERT INTO header(frame_id, raw_json, date_obs, exptime, filter_raw, "
                "instrume, telescop, focallen, focratio_raw, xpixsz, ypixsz, gain, offset_adu, "
                "ccd_temp, usblimit, xbinning, ybinning, bayerpat, ra_deg, dec_deg, object_raw) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (frame_id, raw_json, g("date_obs"), g("exptime"), g("filter_raw"), g("instrume"),
                 g("telescop"), g("focallen"), g("focratio_raw"), g("xpixsz"), g("ypixsz"),
                 g("gain"), g("offset_adu"), g("ccd_temp"), g("usblimit"), g("xbinning"),
                 g("ybinning"), g("bayerpat"), g("ra_deg"), g("dec_deg"), g("object_raw")))
        con.execute("DELETE FROM cards WHERE frame_id = ?", (frame_id,))
        if cards:
            _insert_cards(con, frame_id, cards)
        emit_event(con, actor=actor, verb="header.refreshed", target=f"frame:{frame_id}",
                   now=now, payload={"header_hash_before": row["header_hash"],
                                     "header_hash_after": header_hash})
        result["header"] = True

        fr = con.execute("SELECT camera_id, kind FROM frame WHERE id = ?", (frame_id,)).fetchone()
        if (fr["camera_id"], fr["kind"]) != (camera_id, kind):
            con.execute("UPDATE frame SET camera_id = ?, kind = ? WHERE id = ?",
                        (camera_id, kind, frame_id))
            emit_event(con, actor=actor, verb="frame.rederived", target=f"frame:{frame_id}",
                       now=now,
                       payload={"before": {"camera_id": fr["camera_id"], "kind": fr["kind"]},
                                "after": {"camera_id": camera_id, "kind": kind}})
            result["rederived"] = True
    return result


# Prefiks powodu w dzienniku przy oznaczeniu kopii (#13) — JEDEN właściciel frazy. Powierzchnia,
# która sama nazywa się „Kopie nieczytelne", zdejmuje go przy wyświetlaniu (`gui.app._copy_reason`,
# Z6), żeby to diagnoza („ParseError: …") zajmowała kolumnę, nie powtórzony wstęp.
UNREADABLE_REASON_PREFIX = "kopia nieczytelna: "


def refresh_location_unreadable(con, *, location_id, sha1_data, path, mtime, reason,
                                now, actor="scan"):
    """Znana ścieżka, plik NIECZYTELNY, bajty NIEZMIENIONE (R3-b1, #13): refresh mtime + ZNACZNIK
    `unreadable_since` (marker czytelności kopii w STANIE) + `event(frame.review, „kopia
    nieczytelna")` — ZERO nowych frame'ów (transient NAS; degeneracja tożsamości legalna wyłącznie
    dla ścieżki NIEZNANEJ). Target `sha1:` po tożsamości frame'a lokacji (kotwica joinowalna).

    SEMANTYKA MARKERA: znaczy „kopia JEST nieczytelna" (BIEŻĄCY fakt — ostatnia próba odczytu nieudana),
    NIE „stała się nieczytelna po byciu czytelną". Ustawia go re-odczyt ZNANEJ ścieżki, więc przy bramie
    OFF (`volume='?'`) oznaczy też kopię, która NIGDY nie była czytelna (przy bramie ON pominie ją) —
    kubełek `unreadable` bywa RÓŻNY między trybami skanu, świadomie.

    CYKL ŻYCIA MARKERA (#13): `unreadable_since = COALESCE(unreadable_since, now)` — PIERWSZA awaria
    trzyma timestamp (idempotencja: powtórna awaria nie przestawia go). Marker w STANIE robi dwie
    rzeczy: kolejka przeglądu (ze STANU po #12) pokazuje „kopia nieczytelna", a brama przyrostowa
    (`scan._already_scanned`, `unreadable_since IS NULL`) re-czyta oznaczoną kopię aż do wyzdrowienia
    (udany odczyt zgasi marker przez `refresh_location`). Gaśnie WYŁĄCZNIE po udanym odczycie.

    PRZESŁANKA WOŁANIA (P5, D-V-8): **plik ISTNIEJE** — wołający tego dowiódł (zahaszował go albo
    zestatował). Dlatego funkcja ustawia `present = 1`: kopia nieczytelna-ale-obecna to legalny stan
    (marker + obecność), a kopia, której NIE MA, należy do `mark_location_vanished` — nigdy tu.
    Bez tego kopia, która wróciła po zniknięciu i znów padła na odczycie, zostawałaby `present=0`
    z markerem, czyli w hybrydzie zakazanej przez inwariant `present=0 ⇒ unreadable_since IS NULL`.

    ZWRACA bool (czy coś zmieniono). Zmiana zachodzi gdy `mtime` się różni LUB marker jest NULL
    (pierwsze oznaczenie) LUB kopia była oznaczona jako zniknięta (`present=0` → powrót). QUIET:
    powtórna awaria bez zmiany mtime na już-oznaczonej i obecnej kopii = cichy no-op (`False`, BEZ
    eventu) — stan już alarmuje, dziennik bez spamu review co skan."""
    with _immediate(con):
        row = con.execute(
            "SELECT mtime, unreadable_since, present FROM location WHERE id = ?",
            (location_id,)).fetchone()
        if row is None:
            raise ValueError(f"location:{location_id} nie istnieje")
        if row["mtime"] == mtime and row["unreadable_since"] is not None and row["present"]:
            return False                              # powtórna awaria bez zmiany — cichy no-op (QUIET)
        con.execute(
            "UPDATE location SET mtime = ?, last_verified_at = ?, present = 1, "
            "unreadable_since = COALESCE(unreadable_since, ?) WHERE id = ?",
            (mtime, now, now, location_id))
        emit_event(con, actor=actor, verb="frame.review", target=f"sha1:{sha1_data}", now=now,
                   reason=f"{UNREADABLE_REASON_PREFIX}{reason}", payload={"path": path})
    return True


def mark_location_vanished(con, *, location_id, expected_path, root, run_id, now,
                           actor="presence", forced=False):
    """ZDJĘCIE OBECNOŚCI kopii (P5/#7): `present = 0` + zgaszenie markera + `event(location.vanished)`.
    Jedyna droga zapisu `present=0` w całym pniu — dowód nieobecności zbiera wołający
    (`presence.check`: `os.lstat` → `ENOENT`/`ENOTDIR`; backstop skanu: ten sam test na ścieżce błędu).

    APPEND-ONLY: wiersz `location` ZOSTAJE (tożsamość `sha1_data` frame'a i historia nietknięte) —
    znika wyłącznie twierdzenie „plik pod tą ścieżką jest". Powrót kopii przywraca `present=1`
    przez zwykły re-odczyt (`refresh_location`, D-V-6) — tu nie ma drogi w drugą stronę.

    MARKER GAŚNIE (D-V-5, ratyfikowane 2026-07-22): `unreadable_since = NULL`, stara wartość idzie
    do payloadu. Kubełek `unreadable` to KOLEJKA ROBOTY („przeczytaj tę kopię ponownie") — kopia,
    której nie ma, nie ma czego czytać i wisiałaby w nim bez wyjścia (marker gaśnie WYŁĄCZNIE po
    udanym odczycie). Inwariant całego pnia: `present = 0 ⇒ unreadable_since IS NULL`.

    KOTWICA ANTY-STALE (`expected_path`): pass planuje na migawce, a między planem a zapisem GUI może
    zrobić rename (`relocate_location` zmienia `path` TEGO wiersza) — wtedy ścieżka w bazie wskazuje
    na ISTNIEJĄCY plik i oznaczenie byłoby kłamstwem. Rozjazd → `False` (wołający liczy `drifted`),
    ZERO zapisu. Guard+UPDATE w `_immediate` (TOCTOU wobec równoległego writera).

    ZWRACA bool: `True` = oznaczono; `False` = dryf ścieżki ALBO kopia już nieobecna (idempotencja
    powtórnego przebiegu — bez UPDATE i bez eventu, QUIET)."""
    with _immediate(con):
        row = con.execute(
            "SELECT volume, path, present, unreadable_since FROM location WHERE id = ?",
            (location_id,)).fetchone()
        if row is None:
            raise ValueError(f"location:{location_id} nie istnieje")
        if row["path"] != expected_path:
            return False                              # dryf (rename między planem a zapisem)
        if not row["present"]:
            return False                              # już zniknięta — idempotencja, bez eventu
        con.execute(
            "UPDATE location SET present = 0, unreadable_since = NULL, last_verified_at = ? "
            "WHERE id = ?", (now, location_id))
        emit_event(
            con, actor=actor, verb="location.vanished", target=f"location:{location_id}", now=now,
            payload={"path": row["path"], "volume": row["volume"], "root": root, "run_id": run_id,
                     "unreadable_since_before": row["unreadable_since"], "forced": forced})
    return True


def _insert_cards(con, frame_id, cards):
    """Wstaw lustro kart nagłówka (`executemany`, wewnątrz transakcji wołającego). `cards` =
    iterowalne obiektów z polami keyword/idx/value_raw/value_num/value_type/comment
    (`scan.Card` albo równoważne krotki nazwane importu). Wołane WYŁĄCZNIE z tego modułu."""
    con.executemany(
        "INSERT INTO cards(frame_id, keyword, idx, value_raw, value_num, value_type, comment) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [(frame_id, c.keyword, c.idx, c.value_raw, c.value_num, c.value_type, c.comment)
         for c in cards])


def record_header(con, *, frame_id, raw_json, now, actor="scan", cards=None,
                  date_obs=None, exptime=None, filter_raw=None, instrume=None, telescop=None,
                  focallen=None, focratio_raw=None,
                  xpixsz=None, ypixsz=None, gain=None, offset_adu=None, ccd_temp=None,
                  usblimit=None, xbinning=None, ybinning=None, bayerpat=None,
                  ra_deg=None, dec_deg=None, object_raw=None):
    """Zapisz zeznanie nagłówka (1:1 z frame — `header.frame_id` PRIMARY KEY, więc RAZ na frame).
    `raw_json` = surowy nagłówek 1:1; pola gorące już zrzutowane na typy (`resolve.extract_header`,
    W2/W3); `cards` = pełne lustro EAV nagłówka (None dla XISF do PF-4 / W1). INSERT header +
    `executemany` cards + JEDEN `event(header.recorded)` W TEJ SAMEJ transakcji (brief §4.5 —
    jedno zeznanie = header + cards + jeden event)."""
    with con:  # atomowo: INSERT header + INSERT cards + INSERT event
        con.execute(
            "INSERT INTO header(frame_id, raw_json, date_obs, exptime, filter_raw, instrume, "
            "telescop, focallen, focratio_raw, xpixsz, ypixsz, "
            "gain, offset_adu, ccd_temp, usblimit, xbinning, ybinning, bayerpat, ra_deg, dec_deg, "
            "object_raw) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (frame_id, raw_json, date_obs, exptime, filter_raw, instrume, telescop, focallen,
             focratio_raw, xpixsz, ypixsz, gain, offset_adu,
             ccd_temp, usblimit, xbinning, ybinning, bayerpat, ra_deg, dec_deg, object_raw),
        )
        if cards:
            _insert_cards(con, frame_id, cards)
        emit_event(con, actor=actor, verb="header.recorded", target=f"frame:{frame_id}", now=now)


def flag_frame_review(con, *, sha1, path, reason, now, actor="scan"):
    """Sygnał review pliku z nieczytelnym/nierozpoznanym nagłówkiem (miękkie lądowanie W1) →
    `event(frame.review)`, target `sha1:<sha1>`. DWA wołania (D1):
      - skan: frame-SZKIELET powstał (`kind='unknown'`), ale headera brak — sha1 realny, target
        joinowalny do frame'a; emitowane RAZ (gating na `created` w `ingest_record`);
      - backstop `scan_tree`: wyjątek przed identyfikacją → sha1='?' (tożsamości brak, frame NIE
        powstał) → może się powtórzyć przy re-skanie (brak kotwicy UNIQUE — nieuniknione).
    Wejście do przyszłego import-legacy/review."""
    with con:
        emit_event(con, actor=actor, verb="frame.review", target=f"sha1:{sha1}", now=now,
                   reason=reason, payload={"path": path})


def flag_camera_review(con, *, frame_id, reason, now, actor="scan"):
    """Frame powstał (tożsamość sha1 jest), ale osi KAMERA nie dało się złożyć (brak INSTRUME/XPIXSZ
    — np. Sony master flat) → `event(camera.review)`. `camera_id` zostaje NULL; nie zgadujemy."""
    with con:
        emit_event(con, actor=actor, verb="camera.review", target=f"frame:{frame_id}", now=now,
                   reason=reason)


def flag_kind_unmapped(con, *, frame_id, imagetyp, now, actor="scan"):
    """IMAGETYP niepuste, lecz niezmapowane przez `normalize_kind` (kind=unknown) → sygnał do
    rozszerzenia mapy (`event(kind.unmapped)`). Firsthand 2600 się nie zdarza; mechanizm ma być."""
    with con:
        emit_event(con, actor=actor, verb="kind.unmapped", target=f"frame:{frame_id}", now=now,
                   payload={"imagetyp": imagetyp})


def propose_telescope(con, *, telescop_canon, f_ratio_nominal=None, focal_nominal=None,
                      member_count=None, now, actor="grouper"):
    """Wyłoń teleskop (oś) z nagłówków — `status='proposed'`, `label=NULL` (etykieta/scalanie =
    GUI usera). Tożsamość = `telescop_canon` (TELESCOP.strip(); po naprawie nagłówków 100%,
    8 nazw × 1 ogniskowa — brief §3). Idempotentny po canonie: SELECT po kolumnie
    `UNIQUE COLLATE NOCASE` — to JEDYNY mechanizm foldowania wielkości liter (R2#8; grouper NIE
    folduje w Pythonie); casing wyświetlany = pierwszego wystąpienia. `f_ratio_nominal`/
    `focal_nominal` to nullable WŁAŚCIWOŚCI (audyt/wyświetlanie), nie klucz. Istnieje →
    (id, False) bez eventu; nowy → INSERT + `event(telescope.proposed)`."""
    canon = str(telescop_canon).strip()
    if not canon:
        raise ValueError("telescop_canon pusty — brak TELESCOP to config.review, nie oś")
    row = con.execute(
        "SELECT id FROM telescope WHERE telescop_canon = ?", (canon,)).fetchone()
    if row is not None:
        return row[0], False

    with con:
        cur = con.execute(
            "INSERT INTO telescope(telescop_canon, label, f_ratio_nominal, focal_nominal, "
            "status, created_at) VALUES (?, NULL, ?, ?, 'proposed', ?)",
            (canon, f_ratio_nominal, focal_nominal, now),
        )
        telescope_id = cur.lastrowid
        emit_event(
            con, actor=actor, verb="telescope.proposed", target=f"telescope:{telescope_id}",
            now=now,
            payload={"telescop_canon": canon, "f_ratio_nominal": f_ratio_nominal,
                     "focal_nominal": focal_nominal, "member_count": member_count},
        )
    return telescope_id, True


def propose_config(con, *, telescope_id, camera_id, now, actor="grouper"):
    """Wyłoń config (iloczyn telescope×camera) realnie występujący w skanie — `status='proposed'`.
    Idempotentny po `UNIQUE(telescope_id, camera_id)`: istnieje → (id, False); nowy → INSERT +
    `event(config.proposed)`."""
    row = con.execute(
        "SELECT id FROM config WHERE telescope_id = ? AND camera_id = ?",
        (telescope_id, camera_id),
    ).fetchone()
    if row is not None:
        return row[0], False

    with con:
        cur = con.execute(
            "INSERT INTO config(telescope_id, camera_id, label, status, created_at) "
            "VALUES (?, ?, NULL, 'proposed', ?)",
            (telescope_id, camera_id, now),
        )
        config_id = cur.lastrowid
        emit_event(
            con, actor=actor, verb="config.proposed", target=f"config:{config_id}", now=now,
            payload={"telescope_id": telescope_id, "camera_id": camera_id},
        )
    return config_id, True


CONFIG_SOURCES = frozenset({"user"})
"""Legalne wartości `frame.config_source` — LUSTRO CHECK-a z DDL (`0015_config_source.sql`).

Jedno źródło, bo jest tylko jeden pisarz tej kolumny: RĘKA. Config wyliczony z nagłówka zostaje
NULL i to jest decyzja migracji 0015 (powód tam) — `assign_config` jest idempotentny po
`config_id`, więc zapisywanie „wyliczone" złapałoby wyłącznie klatki akurat ZMIENIAJĄCE config."""

STICKY_CONFIG_SOURCES = CONFIG_SOURCES
"""Źródła osi sprzętu, których PRZEBIEG nie ma prawa nadpisać ani zgłosić do przeglądu (R1b).

ALIAS, nie druga lista — i to jest tu istotne: dziś każde źródło tej kolumny jest gestem
człowieka, więc dwa osobne `frozenset` o tej samej treści rozjechałyby się przy pierwszej zmianie
(SIN-DUP). Rozejdą się dopiero, gdy pojawi się źródło zapisywane przez MASZYNĘ — wtedy ta stała
zostaje wąska, a `CONFIG_SOURCES` rośnie."""


def assign_config(con, *, frame_id, config_id, now, actor="grouper"):
    """Przypisz config do frame'a (`frame.config_id`). INWARIANT (DDL §1): `config.camera_id` musi
    == `frame.camera_id` — gwarantuje grouper (config budowany z kamery tego frame'a). Idempotentny:
    już przypisany ten sam config → False bez eventu; inaczej UPDATE + `event(config.assigned)`.

    GUARD ŹRÓDŁA (R1b): klatka z osią wskazaną RĘKĄ (`config_source` ∈ `STICKY_CONFIG_SOURCES`)
    jest NIETYKALNA dla automatu — zwrot `False`, zero zapisu, zero eventu. Guard stoi TU, a nie
    tylko w pętli groupera, bo to jedyne miejsce, przez które przechodzą OBAJ wołający: przebieg
    i każdy przyszły pisarz osi. Bez niego pierwsze „Przetwórz wszystko" po geście zamalowałoby
    fakt człowieka configiem z nagłówka — a nagłówek RAW-a przez teleskop niesie nazwę OBIEKTYWU
    (E3-3), więc byłby to zapis WPROST fałszywy, nie tylko niechciany.

    Ręka nadpisuje ręką przez `user_assign_config(overwrite=True)` — świadomym drugim gestem."""
    row = con.execute(
        "SELECT config_id, config_source FROM frame WHERE id = ?", (frame_id,)).fetchone()
    if row is not None and row["config_source"] in STICKY_CONFIG_SOURCES:
        return False
    if row is not None and row["config_id"] == config_id:
        return False

    with con:
        con.execute("UPDATE frame SET config_id = ? WHERE id = ?", (config_id, frame_id))
        emit_event(con, actor=actor, verb="config.assigned", target=f"frame:{frame_id}", now=now,
                   payload={"config_id": config_id})
    return True


def unassign_config(con, *, frame_id, now, actor="grouper"):
    """Zdejmij `frame.config_id` z klatki, która NIE należy do osi teleskopu (dark/bias —
    `grouper.NO_TELESCOPE_KINDS`). Potrzebne dla danych sprzed kind-scopingu: darki były przypięte
    do configu zbudowanego z TELESCOP w ich nagłówku, więc bez odpięcia oś liczyłaby je pod cudzą
    optyką na zawsze. Idempotentny: `config_id` już NULL → False bez eventu; inaczej UPDATE +
    `event(config.unassigned)` z poprzednim id w payloadzie (append-only: ślad zostaje).

    ŹRÓDŁO GAŚNIE RAZEM Z OSIĄ (R1, bramka pakietu 3a zarzut 2) — `config_id` i `config_source`
    to JEDNA oś opisana dwoma polami, więc zdjęcie połowy zostawia zdanie bez podmiotu: „ręka
    wskazała zestaw", którego nie ma. Stan `config_id NULL + config_source 'user'` jest przy tym
    NIENAPRAWIALNY z zewnątrz: grouper mija go przez guard lepkości, a gest ręki odmawia
    kalibracji — więc wisiałby na zawsze, czerwieniąc inwariant `§5.16 reka_bez_osi`. Droga do
    niego jest realna: klatka nazwana ręką, a potem przeklasyfikowana na darka (poprawiony
    `IMAGETYP`, `kind_source='path'`). Poprzednie źródło idzie do payloadu — ślad zostaje.

    BRAMKĄ ZOSTAJE SAMO `config_id`, nie para — i to jest wymuszone PARYTETEM, nie wygodą: gdyby
    ta klinga odpinała także klatkę z pustą osią i niepustym źródłem, emitowałaby `config.unassigned`
    przy stanie, który się NIE ZMIENIŁ (klatka bez configu nie jest liczona), czyli rozjeżdżałaby
    `audit.entity_event_parity` o jeden wiersz. Stan `NULL + user` po tej poprawce nie ma już
    PRODUCENTA — a gdyby powstał wstrzyknięciem, łapie go inwariant, nie ta droga."""
    row = con.execute(
        "SELECT config_id, config_source FROM frame WHERE id = ?", (frame_id,)).fetchone()
    if row is None or row["config_id"] is None:
        return False

    with con:
        con.execute(
            "UPDATE frame SET config_id = NULL, config_source = NULL WHERE id = ?", (frame_id,))
        emit_event(con, actor=actor, verb="config.unassigned", target=f"frame:{frame_id}", now=now,
                   payload={"config_id": row["config_id"], "config_source": row["config_source"]},
                   reason="rodzaj bez osi teleskopu (kalibracja)")
    return True


def flag_config_review(con, *, frame_id, reason, now, actor="grouper"):
    """`frame.config_id` nierozstrzygalny (brak teleskopu/kamery/focratio — np. master bez FOCRATIO,
    W4) → `event(config.review)`. config_id zostaje NULL; ZERO cichego NULL (każdy ma powód)."""
    with con:
        emit_event(con, actor=actor, verb="config.review", target=f"frame:{frame_id}", now=now,
                   reason=reason)


@dataclass
class ConfigGesture:
    """Wynik gestu „przypisz zestaw" (R1) — GUI ma powiedzieć „przypisano N z M" I DLACZEGO resztę
    pominięto. Każdy licznik to inny powód odmowy, nie odcienie jednego."""
    assigned: int = 0          # klatki, które REALNIE dostały oś sprzętu z tego gestu
    configs_created: int = 0   # nowe wiersze `config` (iloczyn teleskop × kamera) powołane po drodze
    kind_skip: int = 0         # kalibracja — osi teleskopu nie ma z DEFINICJI (kind-scoping)
    no_camera: int = 0         # bez kamery nie ma czego złożyć w config (inwariant DDL §1)
    occupied: int = 0          # klatka ma już config, a gest nie prosił o nadpisanie
    unchanged: int = 0         # ten sam zestaw tą samą ręką — idempotencja, zero zapisu


def user_assign_config(con, *, frame_ids, telescope_id, now, uid="local", overwrite=False):
    """Przypisanie ZESTAWU (teleskop × kamera) GRUPIE klatek GESTEM CZŁOWIEKA (#DR2 R1, D-DR-3).

    Powstało dla populacji, która nie ma jak zeznać: RAW zrobiony PRZEZ TELESKOP nie niesie nazwy
    niczego (`exif.py` mapuje na `TELESCOP` nazwę OBIEKTYWU — E3-3), a plik jest read-only, więc
    droga writebacku, którą naprawia się nagłówek FITS/XISF, jest tu zamknięta NA ZAWSZE. Jedyną
    drogą jest baza — i to ten gest.

    JEDNA TRANSAKCJA `_immediate`, DML inline (jak `user_assign_object`, z tego samego powodu):
    `propose_config` i `assign_config` mają własne `with con:`, więc zawołane wewnątrz zewnętrznej
    transakcji zamknęłyby ją po pierwszej klatce i atomowość grupy pryskała.

    TELESKOP JEST ARGUMENTEM, KAMERA WYNIKA Z KLATKI — i to nie jest wygoda, tylko INWARIANT DDL
    (`config.camera_id == frame.camera_id`, §1). Wołający wskazuje to, czego plik nie wie; reszta
    zestawu stoi w archiwum. Stąd jednostka gestu = FOLDER × KAMERA (D-DR-3): dwa korpusy w jednym
    folderze to dwa configi, bo `config` niesie dokładnie jedną kamerę (`UNIQUE(telescope_id,
    camera_id)`).

    CZTERY ODMOWY, KAŻDA Z WŁASNYM LICZNIKIEM (`ConfigGesture`):
      * **kalibracja** (`grouper.NO_TELESCOPE_KINDS`) — dark i bias powstają przy zamkniętej
        migawce, optyka ich nie opisuje. Guard stoi TU, w klindze, a nie w oknie: to jedyne
        miejsce, przez które przejdzie także każda przyszła powierzchnia (lekcja S2b/§4-14c-b —
        guard postawiony w GUI zostawia drugą drogę otwartą);
      * **brak kamery** — configu nie da się złożyć bez drugiej osi, a zgadywanie łamałoby
        inwariant DDL;
      * **klatka zajęta** — oś już jest, a gest o nadpisanie nie prosił. `overwrite=True` to
        ŚWIADOMY drugi gest człowieka („guard nadpisania jawny", D-DR-3): bez niego pierwsza
        pomyłka ręki byłaby wieczna, z nim — cudzy zapis nie ginie po cichu;
      * **bez zmiany** — ten sam zestaw tą samą ręką: idempotencja, zero DML i zero eventu (kanon
        repo: powtórzony gest nie zaśmieca dziennika).

    PRZEPIĘCIE EMITUJE PARĘ VERBÓW (`config.unassigned` + `config.assigned`), nie sam drugi —
    inaczej parytet `audit.py` („`frame.config_id` == assigned − unassigned") rozjeżdża się
    dokładnie o liczbę nadpisań, a bramka świeci ZIELONO przy zepsutym bilansie (ta sama lekcja,
    co przy nadpisaniu obiektu w `user_assign_object`).

    Zwraca `ConfigGesture`. Klatka nieistniejąca → `ValueError` i ZERO zapisu (cała grupa
    wycofana) — jak w `user_assign_object`: dryf do nieistniejącej tożsamości znaczy, że wołający
    pracuje na nieaktualnej liście, a nie że jedną pozycję da się pominąć."""
    # Import odroczony: `grouper` importuje `repo` (kierunek stały), a ta stała jest wyprowadzana
    # z `calibration.KIND_RECIPE` — SPOT ma jednego właściciela, więc pytamy jego, zamiast wyliczać
    # drugi raz tutaj. Ten sam idiom, co `cli.py` → `supersede`.
    from .grouper import NO_TELESCOPE_KINDS

    g = ConfigGesture()
    with _immediate(con):
        if con.execute("SELECT 1 FROM telescope WHERE id = ?", (telescope_id,)).fetchone() is None:
            raise ValueError(f"telescope:{telescope_id} nie istnieje")
        actor = f"user:{uid}"
        cfg_per_camera = {}                      # kamera → config; jeden SELECT na korpus, nie na klatkę
        for frame_id in frame_ids:
            fr = con.execute(
                "SELECT kind, camera_id, config_id, config_source FROM frame WHERE id = ?",
                (frame_id,)).fetchone()
            if fr is None:
                raise ValueError(f"frame:{frame_id} nie istnieje")
            if fr["kind"] in NO_TELESCOPE_KINDS:
                g.kind_skip += 1
                continue
            if fr["camera_id"] is None:
                g.no_camera += 1
                continue
            # ZESTAW WYSZUKUJEMY, ale POWOŁUJEMY dopiero przy realnym zapisie (bramka pakietu 3a,
            # zarzut 5): `INSERT` przed guardem zajętości zostawiał wiersz `config` i zdarzenie
            # `config.proposed` nawet wtedy, gdy gest nie ruszył ANI JEDNEJ klatki (wyścig: wszystkie
            # dostały zestaw między oknem a zapisem). Osierocony config nie łamie parytetu — łamie
            # obietnicę „zero zmian, gdy nic nie zapisano".
            cfg_id = cfg_per_camera.get(fr["camera_id"])
            if cfg_id is None:
                row = con.execute(
                    "SELECT id FROM config WHERE telescope_id = ? AND camera_id = ?",
                    (telescope_id, fr["camera_id"])).fetchone()
                if row is not None:
                    cfg_id = row["id"]
                    cfg_per_camera[fr["camera_id"]] = cfg_id
            if cfg_id is not None and fr["config_id"] == cfg_id \
                    and fr["config_source"] in STICKY_CONFIG_SOURCES:
                g.unchanged += 1                 # ten sam zestaw tą samą ręką — nic do zapisania
                continue
            if fr["config_id"] is not None and not overwrite:
                g.occupied += 1
                continue
            if cfg_id is None:                   # dopiero TERAZ wiadomo, że zestaw komuś posłuży
                cur = con.execute(
                    "INSERT INTO config(telescope_id, camera_id, label, status, created_at) "
                    "VALUES (?, ?, NULL, 'proposed', ?)",
                    (telescope_id, fr["camera_id"], now))
                cfg_id = cur.lastrowid
                cfg_per_camera[fr["camera_id"]] = cfg_id
                g.configs_created += 1
                emit_event(con, actor=actor, verb="config.proposed", target=f"config:{cfg_id}",
                           now=now, payload={"telescope_id": telescope_id,
                                             "camera_id": fr["camera_id"]})
            if fr["config_id"] is not None:      # PRZEPIĘCIE — para verbów, inaczej parytet kłamie
                emit_event(con, actor=actor, verb="config.unassigned", target=f"frame:{frame_id}",
                           now=now, payload={"config_id": fr["config_id"],
                                             "config_source": fr["config_source"]},
                           reason="zestaw wskazany ręką zastępuje poprzedni")
            con.execute(
                "UPDATE frame SET config_id = ?, config_source = 'user' WHERE id = ?",
                (cfg_id, frame_id))
            emit_event(con, actor=actor, verb="config.assigned", target=f"frame:{frame_id}",
                       now=now, payload={"config_id": cfg_id, "config_source": "user"})
            g.assigned += 1
    return g


# ============================================================ oś OBIEKT + filtr (§Etap 6)

def upsert_object(con, *, canon, catalog, kind, now, actor="resolver"):
    """Wyłoń obiekt (oś) z rozwiązania `object_raw`. Tożsamość = `canon` (UNIQUE, NGC-wins).
    Istnieje → (id, False) bez eventu; nowy → INSERT + `event(object.upserted)` w tej samej
    transakcji; (id, True). Obiekty wyłaniają się z realnych nagłówków (jak kamery), nie a priori."""
    row = con.execute("SELECT id FROM object WHERE canon = ?", (canon,)).fetchone()
    if row is not None:
        return row[0], False

    with con:  # atomowo: INSERT object + INSERT event
        cur = con.execute(
            "INSERT INTO object(canon, catalog, kind) VALUES (?, ?, ?)", (canon, catalog, kind))
        object_id = cur.lastrowid
        emit_event(con, actor=actor, verb="object.upserted", target=f"object:{object_id}",
                   now=now, payload={"canon": canon, "catalog": catalog, "kind": kind})
    return object_id, True


def add_object_alias(con, *, alias_norm, object_id, source, now, actor="resolver"):
    """Zapisz równoważność `alias_norm` → obiekt (audyt „M106 ≡ NGC4258 via catalog_xref"). Po
    `UNIQUE(alias_norm)`: znana → (id, False) bez eventu (idempotencja); nowa → INSERT +
    `event(object.aliased)`; (id, True). `source` ∈ `resolve.objects.ALIAS_SOURCES` — JEDEN
    właściciel enumu; wyliczanka w tym docstringu rozjeżdżała się z DDL-em o `review`, a DDL
    `frame.object_source` rozjeżdżał się z żywą bazą o cztery wartości. `region` w tym zbiorze
    NIE występuje ŚWIADOMIE: kompleks
    rozpoznaje się ze WSPÓŁRZĘDNYCH, więc nie ma nazwy do zapisania jako równoważność — a alias
    z surowego stringa byłby cichym konfliktem, bo ta funkcja zwraca istniejący wiersz po samym
    `alias_norm`, BEZ sprawdzenia `object_id` (zob. `resolve/regions.py`)."""
    row = con.execute("SELECT id FROM object_alias WHERE alias_norm = ?", (alias_norm,)).fetchone()
    if row is not None:
        return row[0], False

    with con:  # atomowo: INSERT object_alias + INSERT event
        cur = con.execute(
            "INSERT INTO object_alias(alias_norm, object_id, source) VALUES (?, ?, ?)",
            (alias_norm, object_id, source))
        alias_id = cur.lastrowid
        emit_event(con, actor=actor, verb="object.aliased", target=f"object:{object_id}",
                   now=now, payload={"alias_norm": alias_norm, "source": source})
    return alias_id, True


def assign_object(con, *, frame_id, object_id, object_source, now, actor="resolver"):
    """Przypisz obiekt do frame'a (`frame.object_id` + `object_source`). Idempotentny: ta sama para
    już ustawiona → False bez eventu; inaczej UPDATE + `event(object.assigned)`; True.

    RE-przypisanie emituje PARĘ `object.unassigned` + `object.assigned` (wzorzec
    `assign_calibration_profile`), payload odpięcia niesie stan SPRZED.

    UWAGA — SAMA PARA RÓWNOŚCI NIE DOMYKA. Bramka `§5.9` liczy dziś
    `count(frame.object_id NOT NULL) == count('object.assigned')` i **nie odejmuje odpięć**
    (`scripts/acceptance_s5.py`, ta sama nota stoi tam od dawna przy przepisie kalibracji), więc
    przepięcie rozjeżdża równość o 1 tak samo jak przed dołożeniem tego verbu. Para jest MATERIAŁEM
    dla poprawionej formuły — `assigned − unassigned` — która wchodzi razem z resztą zmian
    w akceptacji. Do tego czasu czerwień `§5.9` po przepięciu jest ZNANYM brakiem formuły,
    nie regresją: adjudykuj ją przez dodanie odejmowania, nigdy przez podniesienie kotwicy.

    Predykat emisji to `row[0] IS NOT NULL` („obiekt BYŁ"), **nie** `row[0] != object_id`: ta funkcja
    wychodzi wcześnie po PARZE (obiekt, źródło), więc zmiana samego ŹRÓDŁA przy tym samym obiekcie
    (`region` → `alias`, realna po dołożeniu szczebla słownika) dotarłaby tutaj i przy porównaniu
    obiektów wyemitowałaby `assigned` bez `unassigned`. `NULL→A`, `A→B` i `A(src1)→A(src2)`
    domykają się wtedy identycznie."""
    row = con.execute(
        "SELECT object_id, object_source FROM frame WHERE id = ?", (frame_id,)).fetchone()
    if row is not None and row[0] == object_id and row[1] == object_source:
        return False

    with con:
        con.execute("UPDATE frame SET object_id = ?, object_source = ? WHERE id = ?",
                    (object_id, object_source, frame_id))
        if row is not None and row[0] is not None:   # re-przypisanie: ślad zostaje (append-only)
            emit_event(con, actor=actor, verb="object.unassigned", target=f"frame:{frame_id}",
                       now=now, payload={"object_id": row[0], "object_source": row[1]})
        emit_event(con, actor=actor, verb="object.assigned", target=f"frame:{frame_id}", now=now,
                   payload={"object_id": object_id, "object_source": object_source})
    return True


def flag_object_alias_conflicts(con, items, now, actor="resolver"):
    """Nazwy ze słownika obiektów własnych, które są już równoważnością INNEGO obiektu — JEDEN event
    `object.alias_conflict` z listą (kanon passu masowego, jak `flag_object_review_summary`).
    `items` = lista `[alias_norm, object_id_zajmujący, object_id_oczekiwany]`.

    RAPORT, NIE ZAPIS: kolizja znaczy, że człowiek wpisał do assetu nazwę, którą archiwum już wiąże
    z czymś innym — rozstrzyga to człowiek, nie automat. Alias zostaje przy dotychczasowym obiekcie.
    Pusta lista → bez eventu (diff-first: cisza przy braku różnicy)."""
    items = [list(i) for i in items]
    if not items:
        return
    with con:
        emit_event(con, actor=actor, verb="object.alias_conflict", target="object:*", now=now,
                   payload={"count": len(items), "items": items},
                   reason="nazwa ze słownika obiektów własnych zajęta przez inny obiekt")


#: Źródła osi obiektu, które SŁOWNIK obiektów własnych potrafi wyprodukować — wprost (`curated`),
#: przez zasianą przez siebie równoważność (`alias`) albo przez potwierdzoną propozycję ze ŚCIEŻKI
#: (`path`, S2: kanon segmentu bierze się z wpisu słownika, gdy nagłówek milczy). Zbiór jest
#: DOPEŁNIENIEM pytania „co da się odtworzyć bez tego wpisu", nie wyliczanką wartości: nowe źródło
#: wyprodukowane ze słownika dopisujemy TU, inaczej klatki wypadną z odwracalności po cichu.
_SLOWNIKOWE = frozenset({"alias", "curated", "path"})


def retire_alias_and_unassign(con, *, object_id, alias_norms, now, actor="resolver"):
    """Wycofaj równoważności `alias_norms` obiektu i ODEPNIJ klatki, które przez nie dostały obiekt.
    Zwraca `(wycofane, odpięte)`. Druga połowa re-derywacji zasiewu (D-OW-4): edycja assetu jest
    operacją MIGRACYJNĄ, a nie zwykłym re-runem.

    DLACZEGO DWA CZŁONY, NIE JEDEN: samo skasowanie aliasu NIE zdejmuje `object_id` z klatek —
    żaden szczebel resolvera tego nie robi (drabina przypisuje, nigdy nie odpina). Klatki, które
    dostały obiekt przez usuwaną równoważność, zostałyby z nim NA ZAWSZE, a „re-derywowalność"
    byłaby wtedy samą nazwą.

    ODPINANIE IDZIE PO DOPEŁNIENIU, NIE PO WYLICZANCE ŹRÓDEŁ (R-S1-4, odroczone z recenzji S1 do
    czasu, aż źródło `path` powstanie): bierzemy klatki, których kanon da się odtworzyć WYŁĄCZNIE
    z usuwanego wpisu. Dwa rozłączne przypadki:

      * klatka ZEZNAJE — znormalizowane `object_raw` jest jedną z wycofywanych nazw (świadek);
      * klatka NIE ZEZNAJE (`object_raw IS NULL`) — świadka nie ma, więc rozstrzyga źródło
        ∈ `_SLOWNIKOWE` **ORAZ zdjęcie KANONU** obiektu. Po S2 należy tu `path`: 36 klatek LMC nie
        ma ani karty `OBJECT`, ani współrzędnych, więc żaden ze świadków ich nie zafiszkuje — a bez
        tego członu usunięcie `LMC` ze słownika zostawiłoby je przypięte do obiektu, którego słownik
        już nie zna, przy `§5.9` ZIELONEJ (encje i eventy zgodne). Populacja sztandarowa całego
        briefu wypadałaby z odwracalności w segmencie, który ją nazywa.

    STRAŻNIK KANONU NIE JEST OSTROŻNOŚCIĄ — bez niego człon jest ZA SZEROKI: zdjęcie samej nazwy
    potocznej (wpis zostaje) odpinałoby klatki, których kanon dalej się odtwarza. Czyta się go
    wprost: „wpis, z którego ta klatka wzięła nazwę, PRZESTAŁ istnieć I nic innego jej nie nazwie".
    Trzy człony tego zdania, każdy z ceną za brak:
      * kanon wśród kluczy REALNIE wycofanych (nie wśród argumentów) — inaczej wołanie kluczem,
        którego ten obiekt nie zna, odpina, nie wycofując niczego, a następny przebieg przypina
        z powrotem (czysty churn w dzienniku);
      * kanon NIEODTWARZALNY z GRAMATYKI KATALOGOWEJ — wpis o kanonie `NGC7000` wolno zdjąć ze
        słownika, a klatki i tak zachowają nazwę, bo nazywa je gramatyka. Pytamy `catalog_canon`,
        nie całej drabiny: drabina czyta SŁOWNIK, czyli dokładnie ten asset, który właśnie się
        zmienia — klinga pytałaby o stan, który sama migruje, i odpowiedź zależałaby od tego, czyj
        cache jest świeższy. Gramatyka jest czysta i niezmienna w czasie;
      * kanoniczna równoważność, która przeżywa (bo zapisał ją inny szczebel), zostawia klatkę —
        następny przebieg rozwiąże ją tym aliasem, więc odpięcie byłoby stratą bez zysku.

    Klatka tego samego obiektu nazwana z nagłówka, z xref albo z regionu zostaje nietknięta; `user`
    zostaje nietknięty z definicji precedencji.

    `object_source` wraca do NULL, nie do nagrobka: nagrobek jest STICKY i wypadałby z drabiny na
    zawsze, czyli „operacja migracyjna" kasowałaby klatce przyszłość. NULL = powrót do stanu sprzed
    rozwiązania, klatka wraca do kolejki i następny przebieg ma prawo rozwiązać ją na nowo.

    KAŻDY WIERSZ MA WŁASNY EVENT (`object.alias_retired` / `object.unassigned`, payload = stan
    SPRZED). Zbiorczy zbiłby bramkę `§5.9` o N−1: liczy ona encje CO DO SZTUKI wobec emisji, więc
    jeden event na N odpięć sam zapaliłby czerwień. `object` zostaje append-only — kasujemy
    równoważność i przypisanie, nigdy obiekt."""
    keys = tuple(dict.fromkeys(alias_norms))     # bez duplikatów, kolejność stabilna
    if not keys:
        return 0, 0

    # ZAKRES = równoważności ZASIANE (`source='curated'`). Kontrakt publicznej klingi nie może
    # zależeć od tego, że wołający dobrze przefiltrował klucze: bez tego warunku przyszły wołający
    # skasowałby aliasy nauczone RĘKĄ (`source='user'`), które ten mechanizm ma prawo tylko czytać.
    rows = con.execute(
        "SELECT a.id AS aid, a.alias_norm AS key, a.source AS src FROM object_alias a "
        "WHERE a.object_id = ? AND a.source = 'curated'", (object_id,)).fetchall()
    do_wycofania = [r for r in rows if r["key"] in keys]

    # Kandydaci do odpięcia: klatki TEGO obiektu, których kanon MÓGŁ powstać ze słownika. Świadka
    # (`object_raw`) normalizujemy w Pythonie — `norm_alnum` nie ma odpowiednika w SQL, a SELECT
    # w tej warstwie jedzie literałem (meta-tripwir AST).
    kandydaci = con.execute(
        "SELECT f.id AS fid, f.object_source AS src, h.object_raw AS raw FROM frame f "
        "JOIN header h ON h.frame_id = f.id "
        "WHERE f.object_id = ? AND f.object_source IN (SELECT value FROM json_each(?))",
        (object_id, json.dumps(sorted(_SLOWNIKOWE)))).fetchall()
    # Czy WPIS jako taki zniknął: kanon obiektu jest zawsze jednym z kluczy wpisu, więc jego
    # wycofanie znaczy „tego rekordu już nie ma" (albo zmienił kanon). Klatka bez zeznania nie ma
    # innego świadka, więc TO jest jej jedyny strażnik. Dwa doprecyzowania, oba z recenzji diffu:
    #   * liczymy z kluczy REALNIE wycofanych, nie z argumentu — wołanie kluczem, którego ten obiekt
    #     nie ma jako równoważności `curated`, odpinałoby klatki NIE wycofując niczego (alias dalej
    #     wskazuje obiekt, klatki NULL, następny przebieg przypina je z powrotem = czysty churn);
    #   * kanon musi być NIEODTWARZALNY po zmianie assetu. Wpis o kanonie GRAMATYCZNYM (`NGC7000`)
    #     wolno usunąć ze słownika, a klatki i tak zachowają nazwę z gramatyki katalogowej — tam
    #     odpięcie byłoby stratą, bo szczebel ścieżki tylko PROPONUJE i sam ich nie odzyska.
    zdjete = {r["key"] for r in do_wycofania}
    kanon = con.execute("SELECT canon FROM object WHERE id = ?", (object_id,)).fetchone()
    kanon_zdjety = (kanon is not None and norm_alnum(kanon["canon"]) in zdjete
                    and catalog_canon(kanon["canon"]) is None)
    do_odpiecia = [r for r in kandydaci
                   if (kanon_zdjety if r["raw"] is None else norm_alnum(r["raw"]) in keys)]

    if not do_wycofania and not do_odpiecia:
        return 0, 0                              # diff-first: zero różnicy ⇒ zero DML, zero eventu

    with con:
        for r in do_wycofania:
            con.execute("DELETE FROM object_alias WHERE id = ?", (r["aid"],))
            emit_event(con, actor=actor, verb="object.alias_retired",
                       target=f"object:{object_id}", now=now,
                       payload={"alias_norm": r["key"], "source": r["src"]},
                       reason="nazwa zdjęta ze słownika obiektów własnych")
        for r in do_odpiecia:
            con.execute(
                "UPDATE frame SET object_id = NULL, object_source = NULL WHERE id = ?", (r["fid"],))
            emit_event(con, actor=actor, verb="object.unassigned", target=f"frame:{r['fid']}",
                       now=now, payload={"object_id": object_id, "object_source": r["src"]},
                       reason="równoważność wycofana ze słownika")
    return len(do_wycofania), len(do_odpiecia)


def flag_object_review_summary(con, items, now, actor="resolver"):
    """Delta obiektu ZBIORCZO — JEDEN `event(object.review_summary)` z licznością per `object_raw`
    (analogicznie do `backfill_focratio_norm`: operacja masowa, bez per-frame zaśmiecania logu).
    `items` = lista `(object_raw, count)` nierozpoznanych light/master_light. Stan (object_id NULL)
    SAM jest deltą — to event audytowy, NIE zapisuje na frame. Kalibracja TU nie trafia (nie ma
    obiektu z definicji). Pusta lista → bez eventu."""
    items = list(items)
    if not items:
        return
    with con:
        emit_event(con, actor=actor, verb="object.review_summary", target="frame:*", now=now,
                   payload={"distinct": len(items), "frames": sum(n for _, n in items),
                            "items": [[raw, n] for raw, n in items]})


def backfill_filter_canon(con, items, now, actor="resolver"):
    """Backfill kolumny POCHODNEJ `frame.filter_canon` ZBIORCZO: jedna transakcja + JEDEN event
    `filter.backfilled`. `items` = lista `(frame_id, filter_canon)` (tylko frame'y z niepustym
    kanonem; brak filtra zostaje NULL — W2, bez review). Zwraca liczbę REALNIE zmienionych wierszy.

    IDEMPOTENTNY (D-0722-1): `WHERE filter_canon IS NOT ?` odsiewa wiersze, które już mają ten
    kanon (`IS NOT` obsługuje NULL — pierwszy backfill przechodzi), a `count` w payloadzie to suma
    `cur.rowcount`, czyli SKUTEK, nie rozmiar wejścia. Zero zmian → ZERO eventu, jak reszta repo
    (`assign_object`, `flag_object_review_summary`). Wcześniej `UPDATE` leciał bezwarunkowo dla
    każdego itemu, a `count = len(items)` — powtórny resolve dopisywał identyczny event z licznikiem
    całej populacji (na `horreum_pf4.db` 7× `count: 12582` przy zerze zmian)."""
    items = list(items)
    if not items:
        return 0
    with con:
        changed = 0
        for frame_id, filter_canon in items:
            cur = con.execute(
                "UPDATE frame SET filter_canon = ? WHERE id = ? AND filter_canon IS NOT ?",
                (filter_canon, frame_id, filter_canon))
            changed += cur.rowcount
        if changed:
            emit_event(con, actor=actor, verb="filter.backfilled", target="frame:*", now=now,
                       payload={"count": changed})
    return changed


# ------------------------------------------------ oś OBIEKT — zapis usera (GUI, #8/P4)

@dataclass(frozen=True)
class ObjectGesture:
    """Wynik GESTU CZŁOWIEKA na osi obiektu — LICZNIKI PER FAKT, nie jedno „skipped" (S2b).

    Do S2b klinga oddawała `(assigned, skipped)`, a gest szedł na kubełek jednorodny. Gest z paska
    Zbiorów bierze DOWOLNE zaznaczenie: mogą w nim być darki, gotowe obrazy i klatki nazwane
    z nagłówka — i każda z tych trzech przyczyn znaczy dla człowieka co INNEGO. Jeden licznik
    kazałby ekranowi powiedzieć „pominięto 40", co jest prawdą bezużyteczną: nie wiadomo, czy to
    ochrona zadziałała, czy gest chybił celu.

    `skipped_drift` to jedyny licznik o TOCTOU (stan zmienił się między oknem a zapisem); pozostałe
    opisują zaznaczenie, które user złożył świadomie."""
    assigned: int = 0          # klatki realnie zapisane (przypisane albo cofnięte)
    skipped_kind: int = 0      # rodzaj poza `LIGHT_KINDS` — kalibracja obiektu nie ma z definicji
    skipped_source: int = 0    # źródło poza zakresem gestu (nagłówek/xref/region — fakt z pliku)
    skipped_nothing: int = 0   # NIE BYŁO CZEGO COFAĆ (`object_id IS NULL`) — osobno od `skipped_source`
                               # (wizytacja S3): jedno pole kazało ekranowi powiedzieć „z nagłówka/
                               # regionu: 1" o klatce, która żadnego nagłówka ani regionu nie miała.
                               # To ta sama klasa, którą ta paczka zamknęła raz przy `skipped_stack`
                               # („kryterium nie ma prawa sklejać dwóch faktów"), a D-OW-7 podniosło
                               # jej trafialność: stos bez obiektu wpadał przedtem do własnego
                               # licznika, a od wejścia stosów w zasięg gestu — właśnie tutaj
    skipped_drift: int = 0     # stan inny niż oczekiwany w chwili zapisu (TOCTOU)
    stacks: int = 0            # …z ZAPISANYCH: ile było gotowych obrazów. NIE jest pominięciem
                               # (D-OW-7: stos jest w zasięgu OBU gestów) i dlatego stoi POZA sumą
                               # `skipped` — to informacja o tym, co gest ruszył, a nie o tym, czego
                               # nie ruszył. Osobno, bo gotowy obraz jest jedyną klatką, przy której
                               # zapis osi może dotknąć rodowodu

    @property
    def skipped(self):
        """Suma pominięć — do zdania „przypisano N z M", gdzie rozbicie idzie osobno.

        Właścicielem listy członów jest TA suma i rozbicie w GUI musi po niej iterować, a nie
        powtarzać wyliczankę: czwarty człon (`skipped_nothing`) dołożony w S3 wszedłby inaczej
        do „z M", a nie do rozbicia — czyli zniknąłby dokładnie tam, gdzie ma tłumaczyć."""
        return (self.skipped_kind + self.skipped_source + self.skipped_nothing
                + self.skipped_drift)

    @property
    def skipped_breakdown(self):
        """Rozbicie pominięć jako [(sufiks klucza i18n, n)] — JEDEN właściciel kolejności i składu.

        GUI powtarzało tę listę literałem, więc każdy nowy człon wpadał do sumy, a z ekranu znikał."""
        return [("kind", self.skipped_kind), ("source", self.skipped_source),
                ("nothing", self.skipped_nothing), ("drift", self.skipped_drift)]


def user_assign_object(con, *, alias_norm, canon, catalog, kind, frame_ids, now, uid="local",
                       object_source="user", expected_object_id=None, overwrite_weak=False):
    """Przypisanie obiektu GRUPIE klatek GESTEM CZŁOWIEKA (#8, D-P4-4) — JEDNA transakcja
    `_immediate`, DML inline (NIE kompozycja `upsert_object`+`add_object_alias`+`assign_object`:
    każda z nich ma własny `with con:` commitujący przy wyjściu — zawołane wewnątrz zewnętrznej
    transakcji zamknęłyby ją po pierwszej i atomowość grupy pryskała).

    Zapis: `INSERT object` (gdy kanon nowy, + `object.upserted`) → `INSERT object_alias`
    (`source='user'`, gdy alias nowy, + `object.aliased`) → `UPDATE frame` per klatka
    (+ `object.assigned`). Alias zapamiętuje nazwę NA PRZYSZŁOŚĆ — nowe klatki z tym `object_raw`
    trafią szczeblem aliasu resolvera (`object_source='alias'`).

    JEDEN PISARZ OSI DLA KAŻDEGO GESTU CZŁOWIEKA (S2, D-OW-2/B) — stąd dwa parametry:

    * `object_source` ∈ `OBJECT_SOURCES`. `user` = ręka wskazała obiekt (pomija całą drabinę
      resolvera). `path` = człowiek POTWIERDZIŁ propozycję ze ścieżki — świadkiem pozostaje
      ścieżka, więc źródło ma to mówić, a nie udawać wskazania palcem. Druga klinga dla propozycji
      dałaby dwóch pisarzy jednej osi i „Cofnij" widziałby tylko jedną z dwóch populacji.
    * `alias_norm=None` = rozpoznanie NIE pochodzi z nazwy zapisywalnej jako równoważność (ta sama
      konwencja, co `ObjectIdentity.alias_norm=None` przy regionie). Segment ścieżki nie trafi
      żadnego przyszłego `object_raw`, więc alias z niego byłby równoważnością do niczego —
      a re-derywacja słownika (zakres `curated`) nigdy by go nie usunęła.

    GUARDY (`ValueError`, zero zapisu): PUSTY `alias_norm` — `""` to nie „brak", tylko `norm_alnum`
    nazwy czysto symbolicznej, a alias "" łapałby KAŻDĄ niealfanumeryczną nazwę (D-P4-2/R#3);
    KONFLIKT aliasu (`alias_norm` istnieje i wskazuje INNY obiekt — domyka pułapkę z
    `resolve/regions.py:18-22`; guard czytany WEWNĄTRZ `_immediate`, TOCTOU); źródło spoza
    `OBJECT_SOURCES` (EXPECT — literówka w źródle jest niewykrywalna po zapisie, a audyt 5b
    zaczerwieniłby się dopiero na całej bazie).

    DRYF GRUPY (R#8): klatki re-SELECTowane w transakcji; klatka, która między dialogiem a zapisem
    dostała `object_id NOT NULL` (resolve z workera / inne przypisanie), jest POMIJANA i zliczana.
    Zwraca `ObjectGesture` — GUI pokazuje „przypisano N z M" plus rozbicie. Idempotencja jak reszta
    repo: powtórzenie tego samego przypisania → wszystkie klatki pominięte, ZERO nowych eventów.

    GUARD RODZAJU STOI TU, NIE W GEŚCIE (S2b, §4/14c-b): od paska Zbiorów zaznaczenie bierze się
    z widoku, więc wpadną w nie darki i flaty. Kalibracja obiektu nie ma z DEFINICJI (memory
    `horreum-object-resolution-kind-aware`), a `§5.9` takiego zapisu NIE złapie — encje i eventy
    zgadzałyby się co do joty. Klinga jest jedynym miejscem, przez które przechodzą OBIE
    powierzchnie (kolejka i pasek), więc guard postawiony wyżej zostawiłby drugą drogę otwartą.

    DWA PARAMETRY „NAZWIJ ZAZNACZENIE" (S2b, D-OW-6) — domyślnie OBA nieaktywne, więc dotychczasowi
    wołający dostają dokładnie dawne zachowanie:

    * `overwrite_weak=True` dopuszcza nadpisanie klatki, KTÓRA JUŻ MA OBIEKT — ale wyłącznie ze
      źródła SŁABEGO (`WEAK_OBJECT_SOURCES`, dziś `path`). Nagłówek, xref i region zostają
      nietknięte: to fakty z pliku i z geometrii, a nie cudza pomyłka do naprawienia. Nadpisanie
      emituje PARĘ verbów, nie samo `object.assigned` (inaczej §5.9 rozjeżdża się cicho).
    * `expected_object_id` to ZAMROŻONY STAN z chwili, gdy user patrzył na okno. Klatka, która
      w międzyczasie trafiła pod inny obiekt, jest pomijana jako dryf — bez tego gest „przemaluj
      te 30 klatek z `NGC6960`" nadpisałby też klatkę, która właśnie stała się czymś innym."""
    if alias_norm is not None and not alias_norm:
        raise ValueError("alias_norm pusty — nazwa bez znaków alfanumerycznych nie może być kluczem")
    if object_source not in OBJECT_SOURCES:
        raise ValueError(f"object_source '{object_source}' spoza OBJECT_SOURCES")
    with _immediate(con):
        row = con.execute("SELECT id FROM object WHERE canon = ?", (canon,)).fetchone()
        object_id = row[0] if row is not None else None
        # Bez klucza nie ma czego sprawdzać ani zapisywać — gałąź aliasu milczy w CAŁOŚCI (nie
        # `SELECT … = NULL`, który po cichu zawsze zwraca pustkę i udawałby „alias wolny").
        existing = None if alias_norm is None else con.execute(
            "SELECT object_id FROM object_alias WHERE alias_norm = ?", (alias_norm,)).fetchone()
        if existing is not None and existing[0] != object_id:
            raise ValueError(
                f"alias '{alias_norm}' wskazuje już object:{existing[0]} — konflikt, zero zapisu")

        actor = f"user:{uid}"
        if object_id is None:
            cur = con.execute(
                "INSERT INTO object(canon, catalog, kind) VALUES (?, ?, ?)",
                (canon, catalog, kind))
            object_id = cur.lastrowid
            emit_event(con, actor=actor, verb="object.upserted", target=f"object:{object_id}",
                       now=now, payload={"canon": canon, "catalog": catalog, "kind": kind})
        if alias_norm is not None and existing is None:
            con.execute(
                "INSERT INTO object_alias(alias_norm, object_id, source) VALUES (?, ?, 'user')",
                (alias_norm, object_id))
            emit_event(con, actor=actor, verb="object.aliased", target=f"object:{object_id}",
                       now=now, payload={"alias_norm": alias_norm, "source": "user"})

        assigned = kind_skip = source_skip = drift = stacks = 0
        for frame_id in frame_ids:
            fr = con.execute(
                "SELECT kind, object_id, object_source FROM frame WHERE id = ?",
                (frame_id,)).fetchone()
            if fr is None:
                raise ValueError(f"frame:{frame_id} nie istnieje")
            if fr["kind"] not in LIGHT_KINDS:
                kind_skip += 1                      # kalibracja: obiektu nie ma z DEFINICJI
                continue
            if fr["object_id"] is not None:
                if not overwrite_weak:
                    drift += 1                      # dryf: klatka zajęta między dialogiem a zapisem
                    continue
                if fr["object_source"] not in WEAK_OBJECT_SOURCES:
                    source_skip += 1                # fakt z pliku/geometrii — ręka go nie zamaluje
                    continue
                if expected_object_id is not None and fr["object_id"] != expected_object_id:
                    drift += 1                      # nie ten obiekt, co user widział w oknie
                    continue
                # PRZEPIĘCIE emituje PARĘ (§5.9, człon 3) — bez `object.unassigned` bilans encji
                # i eventów rozjeżdża się dokładnie o liczbę nadpisań, a bramka świeci ZIELONO.
                emit_event(con, actor=actor, verb="object.unassigned", target=f"frame:{frame_id}",
                           now=now, payload={"object_id": fr["object_id"],
                                             "object_source": fr["object_source"]})
            elif fr["object_source"] is not None and not overwrite_weak:
                # NAGROBEK bez nadpisania: `object_id IS NULL` przy niepustym źródle to werdykt
                # ręki (`user_cleared`). Gest z kubełka nie ma prawa go po cichu wskrzesić —
                # tylko jawne „Nazwij zaznaczenie" (`overwrite_weak`) jest drugim gestem człowieka.
                source_skip += 1
                continue
            con.execute(
                "UPDATE frame SET object_id = ?, object_source = ? WHERE id = ?",
                (object_id, object_source, frame_id))
            emit_event(con, actor=actor, verb="object.assigned", target=f"frame:{frame_id}",
                       now=now, payload={"object_id": object_id, "object_source": object_source})
            assigned += 1
            # Licznik gotowych obrazów jest LUSTREM licznika z `clear_object_assignment` (D-OW-7):
            # skoro stos jest w zasięgu obu gestów, oba muszą o nim mówić. Nazwanie stosu PRZEPINA
            # dobór okna jego rodowodu — user ma prawo wiedzieć, że tego właśnie dotknął, zanim
            # zobaczy w Dostawie „pominięto, zapisany dowód mocniejszy".
            stacks += fr["kind"] == "master_light"
    return ObjectGesture(assigned=assigned, skipped_kind=kind_skip,
                         skipped_source=source_skip, skipped_drift=drift, stacks=stacks)


def clear_object_assignment(con, *, frame_ids, now, uid="local"):
    """COFNIĘCIE przypisania obiektu GESTEM CZŁOWIEKA (S2b, D-OW-6) — druga strona `user_assign_object`.

    ZAKRES = WYŁĄCZNIE ŹRÓDŁA, KTÓRE POSTAWIŁA RĘKA ALBO ŚCIEŻKA (`path`, `user`). Nagłówek, xref
    i region zostają — cofnięcie ma naprawiać POMYŁKĘ CZŁOWIEKA, a nie kasować fakt zapisany
    w pliku. Bez tego zawężenia jeden gest na zbiorze „Veil" zdjąłby 250 klatek rozpoznanych
    z geometrii i 556 z nagłówka, a odtworzenie ich kosztowałoby pełny przebieg.

    NAGROBEK (R15#4) — sedno tego, że cofnięcie NAPRAWDĘ się cofa: samo wyzerowanie `object_id`
    nie wystarcza, bo kanon 707 klatek pochodzi ze ŚCIEŻKI, a szczebel derywuje go na nowo
    z folderu — najbliższy `Rozwiąż` przypisałby klatkę PONOWNIE. Zostawiamy więc
    `object_source='user_cleared'` przy `object_id NULL`; drabina taką klatkę pomija
    (`STICKY_OBJECT_SOURCES`). Nagrobek jest STICKY i gaśnie JEDNYM gestem: writebackiem karty
    `OBJECT` do pliku (`writeback._clear_object_tombstone`) albo kolejnym „Nazwij zaznaczenie".

    GOTOWE OBRAZY SĄ W ZASIĘGU (D-OW-7, decyzja Zdzinia 2026-08-03 — odwraca R24#7): gest obejmuje
    `master_light` tak samo jak lighta, a licznik `stacks` mówi, ile ich ruszył. Odwrócenie wolno
    było zrobić dopiero po tym, jak ochrona rodowodu zeszła DO PRZEBIEGU: R24#7 pomijał stosy, bo
    odebranie `object_id` rozbraja dobór okna (`stacks._window_candidates` pyta o obiekt) i najbliższy
    przebieg degradował dowiedziony rodowód do „brak wejść". Od ochrony RANGĄ (`repo.RANGA_ASSERT`)
    rodowód `history`/`user` przeżywa taki przebieg niezależnie od tego, który gest wyjął klatkę
    z okna — a rodowód `window` przelicza się uczciwie, bo stos bez obiektu okna nie ma z definicji.
    Pomijanie stosu kupowało więc ochronę, której już nie potrzebuje, ceną ŚLEPEGO ZAUŁKA: „Nazwij"
    stos PRZEPINAŁO (rodzaj jest w `LIGHT_KINDS`), a „Cofnij" go nie tykało, więc przepiętego stosu
    nie dało się w GUI naprawić ani cofnąć.

    PARA VERBÓW: `object.unassigned` (co zdjęto) + `object.cleared` (że to WERDYKT, nie brak).
    Dwa, nie jeden, bo pytania są dwa: bilans osi (§5.9) liczy odpięcia, a kolejka przeglądu musi
    umieć pokazać człon „cofnięte ręką" bez zaglądania w payload. Zwraca `ObjectGesture`."""
    actor = f"user:{uid}"
    cleared = kind_skip = source_skip = nothing_skip = stacks = 0
    with _immediate(con):
        for frame_id in frame_ids:
            fr = con.execute(
                "SELECT kind, object_id, object_source FROM frame WHERE id = ?",
                (frame_id,)).fetchone()
            if fr is None:
                raise ValueError(f"frame:{frame_id} nie istnieje")
            if fr["kind"] not in LIGHT_KINDS:
                kind_skip += 1
                continue
            # DWA RÓŻNE FAKTY, DWA LICZNIKI (wizytacja S3): „ta klatka nazwy nie miała" to nie
            # to samo, co „nazwę postawił nagłówek i ręka jej nie zdejmie". Sklejone dawały
            # komunikat o FAŁSZYWEJ PRZYCZYNIE — user czytał „z nagłówka/regionu: 1" przy klatce
            # bez nagłówka, czyli dostawał recepty („napraw kartą"), której nie da się wykonać.
            if fr["object_id"] is None:
                nothing_skip += 1                   # nie ma czego cofać
                continue
            if fr["object_source"] not in CLEARABLE_OBJECT_SOURCES:
                source_skip += 1                    # fakt spoza ręki — nagłówek/xref/region
                continue
            con.execute(
                "UPDATE frame SET object_id = NULL, object_source = 'user_cleared' WHERE id = ?",
                (frame_id,))
            emit_event(con, actor=actor, verb="object.unassigned", target=f"frame:{frame_id}",
                       now=now, payload={"object_id": fr["object_id"],
                                         "object_source": fr["object_source"]})
            emit_event(con, actor=actor, verb="object.cleared", target=f"frame:{frame_id}",
                       now=now, payload={"was_object_id": fr["object_id"],
                                         "was_source": fr["object_source"]})
            cleared += 1
            stacks += fr["kind"] == "master_light"
    return ObjectGesture(assigned=cleared, skipped_kind=kind_skip,
                         skipped_source=source_skip, skipped_nothing=nothing_skip, stacks=stacks)


def clear_object_tombstone(con, *, frame_id, now, actor="user:local"):
    """ZGAŚ nagrobek `user_cleared` — jedyna droga wyjścia z werdyktu ręki poza kolejnym gestem.

    Woła to `writeback` po wpisaniu karty `OBJECT` do pliku (S2b): człowiek powiedział „to nie ten
    obiekt", a potem podał właściwy TAM, GDZIE archiwum trzyma prawdę — w nagłówku. Od tej chwili
    zeznanie istnieje i drabina ma prawo je przeczytać, więc nagrobek traci przedmiot.

    Klatka bez nagrobka → `False` bez zapisu i bez eventu (idempotencja jak reszta repo). Verb jest
    WŁASNY (`object.tombstone_cleared`), nie `object.unassigned`: nic się nie odpina, znika sam
    zakaz — a bramka §5.9 liczy odpięcia i para bez odpowiednika rozjechałaby jej bilans."""
    with _immediate(con):
        row = con.execute(
            "SELECT object_source FROM frame WHERE id = ?", (frame_id,)).fetchone()
        if row is None or row["object_source"] != "user_cleared":
            return False
        con.execute("UPDATE frame SET object_source = NULL WHERE id = ?", (frame_id,))
        emit_event(con, actor=actor, verb="object.tombstone_cleared",
                   target=f"frame:{frame_id}", now=now, payload={"reason": "object_card_written"})
    return True


# ============================================================ oś OBSERWATORIUM (§PLAN_os_obserwatorium)

def propose_observatory(con, *, lat, lon, now, actor="resolver"):
    """Wyłoń stanowisko (oś) z GPS — kotwica idempotencji GEOMETRYCZNA (ANCHOR-PROXIMITY §2b), NIE
    string (GPS nie ma stabilnego klucza-stringa; greedy-od-zera co skan mintowałby duplikaty + churn).
    Dopasuj punkt do ISTNIEJĄCEGO stanowiska ≤ `THRESH_KM` (`nearest_site`, liść `resolve.observatory`)
    i zwróć id DOPASOWANEGO wiersza (**CZŁONKA, jak `propose_telescope` zwraca member-id — NIGDY
    kanonu**; widok `observatory_canonical` roluje licznik pod kanon, więc kolaps-do-kanonu przy
    zapisie jest zbędny i ŁAMAŁBY `unmerge` + robił churn). Trafienie → (id, False) bez eventu.
    Żadne ≤ próg → INSERT seed (`lat`/`lon` ZAMROŻONE = pierwszy punkt regionu, §2b/D4) +
    `event(observatory.proposed)` → (id, True). Stabilny anchor + zwrot member-id ⇒ re-skan zwraca TE
    SAME id ⇒ zero churn, `unmerge` odwracalny. `lat`/`lon` = stopnie dziesiętne (wołający policzył
    `site_coords`; NULL nie dochodzi tu — klatka bez współrzędnych jest poza osią)."""
    rows = con.execute("SELECT id, lat, lon FROM observatory").fetchall()
    hit = nearest_site((lat, lon), [(r["id"], r["lat"], r["lon"]) for r in rows])
    if hit is not None:
        return hit, False                                # dopasowanie do istniejącego (member-id)

    with con:
        cur = con.execute(
            "INSERT INTO observatory(name, lat, lon, elev, status, created_at) "
            "VALUES (NULL, ?, ?, NULL, 'proposed', ?)",
            (lat, lon, now),
        )
        observatory_id = cur.lastrowid
        emit_event(
            con, actor=actor, verb="observatory.proposed", target=f"observatory:{observatory_id}",
            now=now, payload={"lat": lat, "lon": lon})
    return observatory_id, True


def assign_observatory(con, *, frame_id, observatory_id, now, actor="resolver"):
    """Przypisz stanowisko do frame'a (`frame.observatory_id`) — mirror `assign_config`. Idempotentny:
    już przypisany ten sam → `False` bez eventu; inaczej UPDATE + `event(observatory.assigned)`."""
    row = con.execute("SELECT observatory_id FROM frame WHERE id = ?", (frame_id,)).fetchone()
    if row is not None and row[0] == observatory_id:
        return False

    with con:
        con.execute("UPDATE frame SET observatory_id = ? WHERE id = ?", (observatory_id, frame_id))
        emit_event(con, actor=actor, verb="observatory.assigned", target=f"frame:{frame_id}", now=now,
                   payload={"observatory_id": observatory_id})
    return True


def flag_observatory_review_summary(con, items, now, actor="resolver"):
    """GPS OBECNY ale nieparsowalny (śmieć / jedna współrzędna / poza zakresem) ZBIORCZO — JEDEN
    `event(observatory.review_summary)` z licznością per surowa para (jak `flag_object_review_summary`).
    `items` = lista `((lat_raw, lon_raw), count)`. Stan (`observatory_id NULL`) SAM jest deltą — event
    audytowy, NIE zapisuje na frame. Pusta lista → bez eventu (sonda pf4: 0 nieparsowalnych → ten event
    nie powstaje; forward-guard na wypadek śmieciowego GPS w przyszłym wsadzie)."""
    items = list(items)
    if not items:
        return
    with con:
        emit_event(con, actor=actor, verb="observatory.review_summary", target="frame:*", now=now,
                   payload={"distinct": len(items), "frames": sum(n for _, n in items),
                            "items": [[list(pair), n] for pair, n in items]})


# ============================================================ oś TELESKOP — zapis usera (GUI, §PLAN_gui)
#
# Pierwsza warstwa, gdzie `event.actor` ma formę `user:<uid>` (składaną TU, nie po stronie wołającego —
# prefiks `user:` niefalsyfikowalny). Zwrot: goły `bool` (nie tworzą encji). Rozróżnienie semantyki:
# `False` = WYŁĄCZNIE idempotencja (brak realnej zmiany, brak eventu); błąd wołania → `ValueError`.
# Guardy czytane w `_immediate` (atomowo z UPDATE — TOCTOU, P1). `uid` w v1 zawsze "local".


def _telescope_row(con, telescope_id):
    """Wiersz teleskopu albo `ValueError` (błąd wołania — id spoza listy GUI). Zwraca (label, status,
    merged_into)."""
    row = con.execute(
        "SELECT label, status, merged_into FROM telescope WHERE id = ?", (telescope_id,)).fetchone()
    if row is None:
        raise ValueError(f"telescope:{telescope_id} nie istnieje")
    return row["label"], row["status"], row["merged_into"]


def label_telescope(con, *, telescope_id, label, now, uid="local"):
    """Nadaj/zmień etykietę teleskopu (akcja usera). Pusty/None label (po strip) → `ValueError`
    (kasowanie etykiety NIE wchodzi w v1 — to błąd wołania, nie no-op). Ten sam label już ustawiony →
    `False` BEZ eventu (idempotencja). Inaczej UPDATE + `event(telescope.labeled)` z `{before, after}`."""
    if label is None or not str(label).strip():
        raise ValueError("label pusty — kasowanie etykiety nie wchodzi w v1")
    label = str(label).strip()
    with _immediate(con):
        before, _, _ = _telescope_row(con, telescope_id)
        if before == label:
            return False
        con.execute("UPDATE telescope SET label = ? WHERE id = ?", (label, telescope_id))
        emit_event(con, actor=f"user:{uid}", verb="telescope.labeled",
                   target=f"telescope:{telescope_id}", now=now,
                   payload={"before": before, "after": label})
    return True


def approve_telescope(con, *, telescope_id, now, uid="local"):
    """Zatwierdź teleskop (`status='approved'`). GUARD: tylko KANONICZNY (`merged_into IS NULL`) —
    approve scalonego → `ValueError` (nie zatwierdza się czegoś złożonego w inny). Już `approved` →
    `False`. Inaczej UPDATE + `event(telescope.approved)` z `{before, after}` statusu."""
    with _immediate(con):
        _, status, merged_into = _telescope_row(con, telescope_id)
        if merged_into is not None:
            raise ValueError(f"telescope:{telescope_id} jest scalony (merged_into={merged_into}) — "
                             "approve tylko kanonicznego")
        if status == "approved":
            return False
        con.execute("UPDATE telescope SET status = 'approved' WHERE id = ?", (telescope_id,))
        emit_event(con, actor=f"user:{uid}", verb="telescope.approved",
                   target=f"telescope:{telescope_id}", now=now,
                   payload={"before": status, "after": "approved"})
    return True


def merge_telescope(con, *, source_id, target_id, now, uid="local"):
    """Scal teleskop `source` w `target` (akcja usera). INWARIANT GŁĘBOKOŚĆ ≤ 1 (PLAN_gui §3a) —
    GUARDY (`ValueError` przy naruszeniu): `source≠target`; target KANONICZNY (`merged_into IS NULL`);
    source KANONICZNY; source NIE MA członków (`NOT EXISTS merged_into=source`) — inaczej powstałby
    łańcuch głębokości 2. Czyni cykl/łańcuch strukturalnie niemożliwymi (widok `telescope_canonical`
    pozostaje poprawny, ale dane nie schodzą głębiej niż 1). source już `merged_into=target` → `False`
    (idempotencja). Inaczej UPDATE + `event(telescope.merged)`.

    PARK JEDZIE ZA SPRZĘTEM (D-T3-d, dług T4 §10): scalenie mówi „to ten sam teleskop", a `in_park`
    jest zdaniem o SPRZĘCIE, nie o wierszu — więc oznaczenie source'a przechodzi na korzeń, gdy
    korzeń MILCZY (`in_park IS NULL`), osobnym `event(telescope.parked)` z `via: merge:<id>`.
    `sky.park` filtruje `merged_into IS NULL`, więc bez tego przeniesienia scalenie GASIŁO decyzję
    usera po cichu i planer liczył inny park niż oznaczony. PIĄTY GUARD: sprzeczne zdania (1 vs 0)
    → `ValueError` — dwóch zdań usera o tym samym sprzęcie klinga nie rozstrzyga za niego; park
    porządkuje się przed scaleniem (`horreum park --add/--drop`). Zgodne albo milczący source →
    bez ruchu. Wartość source'a ZOSTAJE na jego wierszu (odczyt i tak go pomija), więc `unmerge`
    oddaje wiersz z nietkniętym oznaczeniem."""
    if source_id == target_id:
        raise ValueError("nie można scalić teleskopu w samego siebie")
    with _immediate(con):
        _, _, src_merged = _telescope_row(con, source_id)
        if src_merged == target_id:
            return False                                   # już scalony tam — idempotencja
        if src_merged is not None:
            raise ValueError(f"source telescope:{source_id} już scalony (merged_into={src_merged}) — "
                             "scalać wolno tylko kanoniczny")
        _, _, tgt_merged = _telescope_row(con, target_id)
        if tgt_merged is not None:
            raise ValueError(f"target telescope:{target_id} nie jest kanoniczny "
                             f"(merged_into={tgt_merged}) — scalać wolno tylko w korzeń")
        has_member = con.execute(
            "SELECT 1 FROM telescope WHERE merged_into = ? LIMIT 1", (source_id,)).fetchone()
        if has_member is not None:
            raise ValueError(f"source telescope:{source_id} ma członków — najpierw unmerge "
                             "(inwariant głębokość ≤ 1)")
        src_park = con.execute(
            "SELECT in_park FROM telescope WHERE id = ?", (source_id,)).fetchone()["in_park"]
        tgt = con.execute(
            "SELECT telescop_canon, in_park FROM telescope WHERE id = ?", (target_id,)).fetchone()
        if src_park is not None and tgt["in_park"] is not None and src_park != tgt["in_park"]:
            raise ValueError(
                f"telescope:{source_id} i telescope:{target_id} mają SPRZECZNE zdanie o parku "
                f"(in_park={src_park} vs {tgt['in_park']}) — rozstrzygnij park przed scaleniem "
                "(`horreum park <db> --add/--drop <teleskop>`)")
        con.execute("UPDATE telescope SET merged_into = ? WHERE id = ?", (target_id, source_id))
        emit_event(con, actor=f"user:{uid}", verb="telescope.merged",
                   target=f"telescope:{source_id}", now=now,
                   payload={"source": source_id, "target": target_id})
        if src_park is not None and tgt["in_park"] is None:
            con.execute("UPDATE telescope SET in_park = ? WHERE id = ?", (src_park, target_id))
            emit_event(con, actor=f"user:{uid}", verb="telescope.parked",
                       target=f"telescope:{target_id}", now=now,
                       payload={"telescope": tgt["telescop_canon"], "before": None,
                                "after": src_park, "via": f"merge:{source_id}"})
    return True


def unmerge_telescope(con, *, telescope_id, now, uid="local"):
    """Cofnij scalenie (`merged_into → NULL`) — append-only (nowy event, nie kasacja). Już kanoniczny
    (`merged_into IS NULL`) → `False`. Inaczej UPDATE + `event(telescope.unmerged)` z `{before, after}`
    (`former_target`→None). Dzięki inwariantowi głębokość ≤ 1 wiersz zawsze jest liściem — un-merge
    nie ma „środka łańcucha" do rozplątania.

    PARKU NIE COFA: `merge_telescope` niczego nie skasowało (source trzyma własne `in_park`, korzeń
    dostał swoje), więc rozplątanie oddaje oba wiersze z ich oznaczeniami. Zdejmowanie parku z korzenia
    „bo przyszedł ze scalenia" zgadywałoby, czy user zdążył go w międzyczasie potwierdzić —
    oznaczenie zdejmuje się jawnie (`horreum park --drop`)."""
    with _immediate(con):
        _, _, merged_into = _telescope_row(con, telescope_id)
        if merged_into is None:
            return False
        con.execute("UPDATE telescope SET merged_into = NULL WHERE id = ?", (telescope_id,))
        emit_event(con, actor=f"user:{uid}", verb="telescope.unmerged",
                   target=f"telescope:{telescope_id}", now=now,
                   payload={"before": merged_into, "after": None})
    return True


# ============================================================ oś OBSERWATORIUM — zapis usera (GUI)
#
# Mirror osi teleskopu (label/merge/unmerge) — actor=user:<uid> składany TU (prefiks niefalsyfikowalny).
# Etykieta = kolumna `name` (NIE `label` — tożsamość osi jest GEOMETRYCZNA §2b, `name` to nazwa usera).
# BEZ `approve` (v1: port = merge+unmerge+label; status zostaje 'proposed'). Guardy czytane w `_immediate`
# (atomowo z UPDATE — TOCTOU, P1). `uid` w v1 zawsze "local".


def _observatory_row(con, observatory_id):
    """Wiersz stanowiska albo `ValueError` (błąd wołania — id spoza listy GUI). Zwraca (name, status,
    merged_into)."""
    row = con.execute(
        "SELECT name, status, merged_into FROM observatory WHERE id = ?", (observatory_id,)).fetchone()
    if row is None:
        raise ValueError(f"observatory:{observatory_id} nie istnieje")
    return row["name"], row["status"], row["merged_into"]


def label_observatory(con, *, observatory_id, name, now, uid="local"):
    """Nadaj/zmień NAZWĘ stanowiska (akcja usera — USER-NAZYWA §0). Pusta/None nazwa (po strip) →
    `ValueError` (kasowanie nazwy NIE wchodzi w v1 — błąd wołania, nie no-op). Ta sama nazwa już
    ustawiona → `False` BEZ eventu (idempotencja). Inaczej UPDATE + `event(observatory.named)` z
    `{before, after}`."""
    if name is None or not str(name).strip():
        raise ValueError("name pusty — kasowanie nazwy nie wchodzi w v1")
    name = str(name).strip()
    with _immediate(con):
        before, _, _ = _observatory_row(con, observatory_id)
        if before == name:
            return False
        con.execute("UPDATE observatory SET name = ? WHERE id = ?", (name, observatory_id))
        emit_event(con, actor=f"user:{uid}", verb="observatory.named",
                   target=f"observatory:{observatory_id}", now=now,
                   payload={"before": before, "after": name})
    return True


def merge_observatory(con, *, source_id, target_id, now, uid="local"):
    """Scal stanowisko `source` w `target` (akcja usera — user rozstrzyga granice, np. klastry
    <2×`THRESH_KM`, D4). INWARIANT GŁĘBOKOŚĆ ≤ 1 — te same 4 GWARDY co `merge_telescope` (`ValueError`
    przy naruszeniu): `source≠target`; target KANONICZNY (`merged_into IS NULL`); source KANONICZNY;
    source NIE MA członków (inaczej łańcuch głębokości 2). Czyni cykl/łańcuch strukturalnie niemożliwymi.
    source już `merged_into=target` → `False` (idempotencja). Inaczej UPDATE + `event(observatory.merged)`."""
    if source_id == target_id:
        raise ValueError("nie można scalić stanowiska w samo siebie")
    with _immediate(con):
        _, _, src_merged = _observatory_row(con, source_id)
        if src_merged == target_id:
            return False                                   # już scalony tam — idempotencja
        if src_merged is not None:
            raise ValueError(f"source observatory:{source_id} już scalony (merged_into={src_merged}) — "
                             "scalać wolno tylko kanoniczny")
        _, _, tgt_merged = _observatory_row(con, target_id)
        if tgt_merged is not None:
            raise ValueError(f"target observatory:{target_id} nie jest kanoniczny "
                             f"(merged_into={tgt_merged}) — scalać wolno tylko w korzeń")
        has_member = con.execute(
            "SELECT 1 FROM observatory WHERE merged_into = ? LIMIT 1", (source_id,)).fetchone()
        if has_member is not None:
            raise ValueError(f"source observatory:{source_id} ma członków — najpierw unmerge "
                             "(inwariant głębokość ≤ 1)")
        con.execute("UPDATE observatory SET merged_into = ? WHERE id = ?", (target_id, source_id))
        emit_event(con, actor=f"user:{uid}", verb="observatory.merged",
                   target=f"observatory:{source_id}", now=now,
                   payload={"source": source_id, "target": target_id})
    return True


def unmerge_observatory(con, *, observatory_id, now, uid="local"):
    """Cofnij scalenie (`merged_into → NULL`) — append-only (nowy event, nie kasacja). Już kanoniczny
    (`merged_into IS NULL`) → `False`. Inaczej UPDATE + `event(observatory.unmerged)` z `{before, after}`.
    Dzięki inwariantowi głębokość ≤ 1 wiersz zawsze jest liściem — bez „środka łańcucha" do rozplątania;
    klatki wracają pod członka (widok `observatory_canonical` je rozdziela)."""
    with _immediate(con):
        _, _, merged_into = _observatory_row(con, observatory_id)
        if merged_into is None:
            return False
        con.execute("UPDATE observatory SET merged_into = NULL WHERE id = ?", (observatory_id,))
        emit_event(con, actor=f"user:{uid}", verb="observatory.unmerged",
                   target=f"observatory:{observatory_id}", now=now,
                   payload={"before": merged_into, "after": None})
    return True


# ============================================================ STAGING WRITEBACKU (krok 4, transient)
# Zapis do tabel stagingu (pending_changes/commits/header_backups) — DML, więc mieszka TU (jedna
# klinga DB, meta-test AST). WYJĄTEK od reguły „każdy zapis emituje event": staging to TRANSIENT
# BOOKKEEPING (nie encja domenowa, nie historia) — fakt domenowy writebacku (mutacja pliku) opisują
# eventy `location.refreshed`/`header.refreshed`/`frame.rederived` emitowane przez `refresh_location`
# w re-syncu po zapisie (actor="user:local"). Emisja eventu per wiersz stagingu = szum łamiący
# append-only (R#1). Każda funkcja owija `with con:` → COMMITUJE od razu: writeback woła je między
# `os.replace` a `ingest_record` (którego `refresh_location` bierze `BEGIN IMMEDIATE`), więc żadna
# otwarta transakcja nie może wisieć (inaczej „transaction within a transaction").


def stage_pending(con, *, run_id, location_id, keyword, idx, op, old_value, new_value,
                  new_type, new_comment, expected_header_hash):
    """Dopisz JEDEN wpis stagingu (status 'pending'). Kluczowany LOCATION (fizyczny plik). Zwraca id
    wiersza. Transient — bez eventu. `expected_header_hash` = kotwica anty-stale (R#7)."""
    with con:
        cur = con.execute(
            "INSERT INTO pending_changes(run_id, location_id, keyword, idx, op, old_value, "
            "new_value, new_type, new_comment, expected_header_hash, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')",
            (run_id, location_id, keyword, idx, op, old_value, new_value, new_type, new_comment,
             expected_header_hash))
    return cur.lastrowid


def set_pending_status(con, *, pending_id, status, reason=None):
    """Ustaw status wpisu stagingu ('applied'|'failed'|'skipped'|'blocked') + powód. Transient."""
    with con:
        con.execute("UPDATE pending_changes SET status = ?, reason = ? WHERE id = ?",
                    (status, reason, pending_id))


def clear_pending_for_run(con, run_id):
    """Skasuj staging przebiegu (idempotentne ponowne uruchomienie makra / „Odrzuć" w szufladzie).
    DELETE sankcjonowany: pending_changes to LUSTRO oczekujących zmian, nie historia (historia =
    event). Transient — bez eventu."""
    with con:
        con.execute("DELETE FROM pending_changes WHERE run_id = ?", (run_id,))


def insert_commit(con, *, run_id, now, summary=None):
    """Utwórz wiersz `commits` (grupuje przebieg do undo). Zwraca commit_id. Transient — wskaźnik
    grupujący, nie event (mutacje plików niosą eventy re-syncu)."""
    with con:
        cur = con.execute(
            "INSERT INTO commits(run_id, applied_at, summary) VALUES (?, ?, ?)",
            (run_id, now, summary))
    return cur.lastrowid


def insert_header_backup(con, *, commit_id, location_id, hdu_index, header_text, post_hash):
    """Zapisz backup pełnego nagłówka SPRZED commitu (undo). `post_hash` = header_hash PO commicie
    (kontrola undo). Append-only: nigdy nie kasowany. Transient — bez eventu."""
    with con:
        con.execute(
            "INSERT INTO header_backups(commit_id, location_id, hdu_index, header_text, post_hash) "
            "VALUES (?, ?, ?, ?, ?)",
            (commit_id, location_id, hdu_index, header_text, post_hash))


# ============================================================ RENAME "Nazwy z faktów" (krok "nazwy")
# relocate_location = FAKT DOMENOWY (mutacja pliku na dysku), emituje event — inaczej niż staging.
# Staging renamu (pending_renames) = transient (bez eventu), jak staging writebacku. Rename NIE tyka
# bajtów → `sha1_data`/`file_sha1`/`header_hash` NIEZMIENNE; ta sama location, nowy path (R2 #1: NIGDY
# `ingest_record`, bo nowa ścieżka mintowałaby DRUGĄ location, starą zostawiając sierotą).


def relocate_location(con, *, location_id, new_path, now, actor="user:local"):
    """RENAME fizycznego pliku w modelu: UPDATE `location.path` IN-PLACE + `event(location.renamed)`.
    Wołane przez `writeback.commit_renames` PO udanym `os.rename` (PLIK→DB, T8). NIE re-sync/ingest —
    tożsamość frame przeżywa (rename nie tyka danych). ANTY-CLOBBER W BAZIE (R3 #3): brak INNEGO wiersza
    `location(volume, new_path)` — inaczej UPDATE łamie `UNIQUE(volume, path)` PO renamie = rozjazd
    plik↔DB → `ValueError` (commit oznaczy 'blocked'). Guard+UPDATE w `_immediate` (TOCTOU wobec
    równoległego writera). Idempotentny: `path` już == `new_path` → `False` bez eventu."""
    with _immediate(con):
        row = con.execute(
            "SELECT volume, path FROM location WHERE id = ?", (location_id,)).fetchone()
        if row is None:
            raise ValueError(f"location:{location_id} nie istnieje")
        volume, old_path = row["volume"], row["path"]
        if old_path == new_path:
            return False
        clash = con.execute(
            "SELECT id FROM location WHERE volume = ? AND path = ? AND id <> ?",
            (volume, new_path, location_id)).fetchone()
        if clash is not None:
            raise ValueError(
                f"cel zajęty w bazie: location:{clash['id']} ma już (volume={volume}, {new_path})")
        con.execute("UPDATE location SET path = ? WHERE id = ?", (new_path, location_id))
        emit_event(con, actor=actor, verb="location.renamed", target=f"location:{location_id}",
                   now=now, payload={"before": old_path, "after": new_path})
    return True


def stage_rename(con, *, run_id, location_id, old_path, new_path, expected_mtime):
    """Dopisz JEDEN wpis stagingu renamu (status 'pending'). Kluczowany LOCATION. Zwraca id wiersza.
    Transient — bez eventu. `expected_mtime` = kotwica anty-stale (mtime pliku przy podglądzie)."""
    with con:
        cur = con.execute(
            "INSERT INTO pending_renames(run_id, location_id, old_path, new_path, expected_mtime, "
            "status) VALUES (?, ?, ?, ?, ?, 'pending')",
            (run_id, location_id, old_path, new_path, expected_mtime))
    return cur.lastrowid


def set_rename_status(con, *, rename_id, status, reason=None):
    """Ustaw status wpisu stagingu renamu ('applied'|'failed'|'skipped'|'blocked') + powód. Transient."""
    with con:
        con.execute("UPDATE pending_renames SET status = ?, reason = ? WHERE id = ?",
                    (status, reason, rename_id))


def clear_renames_for_run(con, run_id):
    """Skasuj staging renamu przebiegu (ponowny podgląd / „Odrzuć"). DELETE sankcjonowany: lustro
    oczekujących, nie historia (historia = event `location.renamed`). Transient — bez eventu."""
    with con:
        con.execute("DELETE FROM pending_renames WHERE run_id = ?", (run_id,))


# ------------------------------------------------ oś KALIBRACJI — przepis + fakty (C2, #6)

def record_calibration_fact(con, *, frame_id, key, value, source, now, actor):
    """Zapisz fakt przepisu dla POJEDYNCZEJ klatki (`calibration_fact`) + `event(calibration.fact)`.
    Idempotentny: ten sam `(frame_id, key)` o tej samej wartości i źródle → False BEZ eventu.

    Trzyma WYŁĄCZNIE fakty, których w nagłówku NIE MA (`source` ∈ {'path','user'}) — zeznania nie
    kopiujemy, czytamy je wprost (D-C-2). Fakt ze ŚCIEŻKI zapisujemy RAZ, przy pierwszym rozpoznaniu:
    rename mastera usuwa `_G100_O21_10_` ze ścieżki, więc re-derywacja po cichu przepięłaby klatkę
    do innego przepisu. Wpis usera NADPISUJE wcześniejszy fakt ze ścieżki (precedencja D-C-1);
    odwrotnie NIE — ścieżka nie rusza tego, co podał człowiek."""
    text = None if value is None else str(value)
    row = con.execute(
        "SELECT value, source FROM calibration_fact WHERE frame_id = ? AND key = ?",
        (frame_id, key)).fetchone()
    if row is not None:
        if row[0] == text and row[1] == source:
            return False
        if row[1] == "user" and source != "user":       # człowiek bije ścieżkę (D-C-1)
            return False
    with con:
        con.execute(
            "INSERT INTO calibration_fact(frame_id, key, value, source, actor, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(frame_id, key) DO UPDATE SET "
            "value = excluded.value, source = excluded.source, actor = excluded.actor, "
            "created_at = excluded.created_at",
            (frame_id, key, text, source, actor, now))
        emit_event(con, actor=actor, verb="calibration.fact", target=f"frame:{frame_id}", now=now,
                   payload={"key": key, "value": text, "source": source})
    return True


def upsert_calibration_profile(con, *, profile_key, recipe_class, camera_id, xbinning,
                               exptime=None, set_temp_c=None, gain=None, offset_adu=None,
                               telescope_id=None, filter_canon=None, now, actor="calibration"):
    """Wyłoń przepis po `profile_key` (klasa równoważności nastaw). Istnieje → `(id, False)` BEZ
    zmiany; nowy → INSERT + `event(calibration_profile.proposed)` → `(id, True)`.

    Klucz nie zawiera NULL-i: komplet faktów swojej klasy jest warunkiem istnienia wiersza (CHECK
    w 0008 tego pilnuje). Klatka bez kompletu NIE dostaje profilu — trafia do `review_summary`,
    bo sentinel w kluczu zlewałby DWA mastery o RÓŻNYCH nieznanych nastawach w jeden przepis."""
    row = con.execute("SELECT id FROM calibration_profile WHERE profile_key = ?",
                      (profile_key,)).fetchone()
    if row is not None:
        return row[0], False
    with con:
        cur = con.execute(
            "INSERT INTO calibration_profile(profile_key, recipe_class, camera_id, xbinning, "
            "exptime, set_temp_c, gain, offset_adu, telescope_id, filter_canon, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (profile_key, recipe_class, camera_id, xbinning, exptime, set_temp_c, gain,
             offset_adu, telescope_id, filter_canon, now))
        pid = cur.lastrowid
        emit_event(con, actor=actor, verb="calibration_profile.proposed",
                   target=f"calibration_profile:{pid}", now=now,
                   payload={"profile_key": profile_key, "recipe_class": recipe_class})
    return pid, True


def assign_calibration_profile(con, *, frame_id, profile_id, now, actor="calibration"):
    """Przypisz przepis do klatki (`frame.calibration_profile_id`). Idempotentny: ten sam profil →
    False bez eventu; inaczej UPDATE + `event(calibration_profile.assigned)`.

    Verb jest CELOWO `calibration_profile.assigned`, nie `calibration.assigned`: tabela `calibration`
    (0002) znaczy „light skalibrowany masterem" i ta nazwa należy do rodowodu (C4)."""
    row = con.execute("SELECT calibration_profile_id FROM frame WHERE id = ?", (frame_id,)).fetchone()
    if row is not None and row[0] == profile_id:
        return False
    with con:
        con.execute("UPDATE frame SET calibration_profile_id = ? WHERE id = ?",
                    (profile_id, frame_id))
        if row is not None and row[0] is not None:      # re-przypisanie: ślad zostaje (append-only)
            emit_event(con, actor=actor, verb="calibration_profile.unassigned",
                       target=f"frame:{frame_id}", now=now, payload={"profile_id": row[0]})
        emit_event(con, actor=actor, verb="calibration_profile.assigned",
                   target=f"frame:{frame_id}", now=now, payload={"profile_id": profile_id})
    return True


def flag_calibration_review_summary(con, items, now, actor="calibration"):
    """Klatki kalibracyjne BEZ kompletu przepisu — JEDEN `event(calibration.review_summary)`
    z licznością per powód (wzorzec `flag_object_review_summary`). Stan (`calibration_profile_id`
    NULL) SAM jest deltą; to event audytowy, nie zapis na frame. Pusta lista → bez eventu.

    Emitowany JUŻ w C2, nie dopiero w C4: „brak jest widoczny" nie może opierać się na module,
    który powstanie dwa segmenty później."""
    items = list(items)
    if not items:
        return
    with con:
        emit_event(con, actor=actor, verb="calibration.review_summary", target="frame:*", now=now,
                   payload={"distinct": len(items), "frames": sum(n for _, n in items),
                            "items": [[reason, n] for reason, n in items]})


def link_calibration(con, *, light_frame_id, master_frame_id, relation, now,
                     actor="lineage", asserted_by="horreum", confidence="recipe"):
    """RODOWÓD (C4): powiąż light z egzemplarzem mastera danej klasy — wiersz `calibration`
    + `event(calibration.linked)`. Idempotentny na kluczu UNIQUE(light_frame_id, relation) (0009):
    ten sam kalibrator → False BEZ eventu.

    Gdy dla tej klasy stał JUŻ inny master (doszedł bliższy czasowo w nowym wsadzie) → UPDATE
    + `event(calibration.unlinked)` na starym (ślad append-only) + `.linked` na nowym. To POŻĄDANE
    (lepszy kalibrator), nie regres — idempotencja liczy TYLKO brak zmiany.

    Verb należy do rodowodu: C2 celowo zostawił `calibration.linked/.unlinked` (użył
    `calibration_profile.assigned` dla klatka↔profil), by tej nazwy nie zająć."""
    row = con.execute(
        "SELECT id, master_frame_id FROM calibration WHERE light_frame_id = ? AND relation = ?",
        (light_frame_id, relation)).fetchone()
    if row is not None and row["master_frame_id"] == master_frame_id:
        return False
    with con:
        if row is None:
            con.execute(
                "INSERT INTO calibration(light_frame_id, master_frame_id, relation, asserted_by, "
                "confidence) VALUES (?, ?, ?, ?, ?)",
                (light_frame_id, master_frame_id, relation, asserted_by, confidence))
        else:
            con.execute(
                "UPDATE calibration SET master_frame_id = ?, asserted_by = ?, confidence = ? "
                "WHERE id = ?", (master_frame_id, asserted_by, confidence, row["id"]))
            emit_event(con, actor=actor, verb="calibration.unlinked",
                       target=f"frame:{light_frame_id}", now=now,
                       payload={"relation": relation, "master_frame_id": row["master_frame_id"]})
        emit_event(con, actor=actor, verb="calibration.linked",
                   target=f"frame:{light_frame_id}", now=now,
                   payload={"relation": relation, "master_frame_id": master_frame_id})
    return True


def flag_calibration_lineage_summary(con, items, now, actor="lineage"):
    """Lighty BEZ pokrycia kalibratorem — JEDEN `event(calibration.lineage_summary)` z licznością
    per powód (wzorzec `flag_calibration_review_summary`). Stan (brak wiersza `calibration` dla
    `(light, relation)`) SAM jest deltą; to event audytowy, nie zapis na frame. Pusta lista → bez
    eventu, więc idempotentny przebieg bez luk nie emituje (jak review_summary)."""
    items = list(items)
    if not items:
        return
    with con:
        emit_event(con, actor=actor, verb="calibration.lineage_summary", target="frame:*", now=now,
                   payload={"distinct": len(items), "frames": sum(n for _, n in items),
                            "items": [[reason, n] for reason, n in items]})


# ═══════════════════════════════════════════════ 1.7b RODOWÓD STOSÓW (I-2c, P-I)
# Siostra rodowodu kalibracji, ale o innej tożsamości: tam kluczem był (light, relation), tu
# KLATKA MASTERA (migracja 0012, §4.1 briefu). Wejścia są zbiorem osobno, bo zbiór bywa
# WYLICZONY (okno czasu), a wyliczenie nie ma prawa być kluczem rekordu.

def upsert_integration(con, *, master_frame_id, integ_hash, tool, window_start, window_end,
                       declared_rows, drizzle_inputs, disabled_inputs, degenerate, ambiguous,
                       telescope_mismatch, unresolved_reason, now, actor="stacks"):
    """Wiersz `integration` dla klatki mastera — `(integration_id, zmienione)`.

    Idempotentny na UNIQUE(master_frame_id) z 0012: identyczny komplet faktów → `False` BEZ eventu
    (drugi przebieg nie ma prawa puchnąć dziennika). Inaczej INSERT `integration.recorded` albo
    UPDATE `integration.updated` z `{before, after}` SAMYCH zmienionych pól — payload ma mówić,
    co drgnęło, a nie powtarzać cały wiersz (UPDATE idzie po wszystkich kolumnach, bo SQL zostaje
    LITERAŁEM; to dwie różne rzeczy i tylko payload jest kanałem dla człowieka).

    Wiersz powstaje TAKŻE, gdy wejść nie znamy (`unresolved_reason` niepuste): „to jest stos,
    ale nie wiem z czego" jest faktem wartym zapisania, a jego brak byłby milczeniem nie do
    odróżnienia od „jeszcze nie liczyliśmy".

    `_immediate`, bo guard (SELECT stanu) musi trzymać do zapisu — droga „Stosy" bywa wołana
    równolegle z GUI na tej samej bazie."""
    fields = {"integ_hash": integ_hash, "tool": tool, "window_start": window_start,
              "window_end": window_end, "declared_rows": declared_rows,
              "drizzle_inputs": drizzle_inputs, "disabled_inputs": disabled_inputs,
              "degenerate": degenerate, "ambiguous": ambiguous,
              "telescope_mismatch": telescope_mismatch, "unresolved_reason": unresolved_reason}
    wartosci = list(fields.values())
    with _immediate(con):
        row = con.execute(
            "SELECT id, integ_hash, tool, window_start, window_end, declared_rows, drizzle_inputs, "
            "disabled_inputs, degenerate, ambiguous, telescope_mismatch, unresolved_reason "
            "FROM integration WHERE master_frame_id = ?", (master_frame_id,)).fetchone()
        if row is None:
            cur = con.execute(
                "INSERT INTO integration(master_frame_id, created_at, integ_hash, tool, "
                "window_start, window_end, declared_rows, drizzle_inputs, disabled_inputs, "
                "degenerate, ambiguous, telescope_mismatch, unresolved_reason) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [master_frame_id, now] + wartosci)
            iid = cur.lastrowid
            emit_event(con, actor=actor, verb="integration.recorded",
                       target=f"frame:{master_frame_id}", now=now,
                       payload={"integration_id": iid, **fields})
            return iid, True
        zmiany = {k: [row[k], v] for k, v in fields.items() if row[k] != v}
        if not zmiany:
            return row["id"], False
        con.execute(
            "UPDATE integration SET updated_at = ?, integ_hash = ?, tool = ?, window_start = ?, "
            "window_end = ?, declared_rows = ?, drizzle_inputs = ?, disabled_inputs = ?, "
            "degenerate = ?, ambiguous = ?, telescope_mismatch = ?, unresolved_reason = ? "
            "WHERE id = ?", [now] + wartosci + [row["id"]])
        emit_event(con, actor=actor, verb="integration.updated",
                   target=f"frame:{master_frame_id}", now=now,
                   payload={"integration_id": row["id"],
                            "before": {k: v[0] for k, v in zmiany.items()},
                            "after": {k: v[1] for k, v in zmiany.items()}})
        return row["id"], True


RANGA_ASSERT = {"window": 0, "history": 1, "user": 2}
"""Precedencja zeznania o wejściu stosu — JEDEN właściciel kanonu (`link_integration` ORAZ strażnik
przebiegu w `stacks`). Do S2b liczba żyła jako zmienna lokalna klingi, więc przebieg, który musi
zapytać „czy ZAPISANY rodowód jest mocniejszy od tego, co umiem policzyć TERAZ", nie miał jej skąd
wziąć i odpowiadał wyliczanką wartości — a wyliczanka gubi sąsiednie zeznanie przy każdym nowym
źródle. Rosnąco: `window` (dobór z bieżącego stanu bazy) < `history` (zeznanie pliku) < `user`
(werdykt ręki)."""


def link_integration(con, *, integration_id, input_frame_id, asserted_by, now, actor="stacks"):
    """Powiąż klatkę wejściową ze stosem — wiersz `integration_input` + `event(integration.linked)`.

    Idempotentny na UNIQUE(integration_id, input_frame_id) z 0012: relacja o tym samym źródle
    → `False` bez eventu. Zmiana źródła (np. kandydat z okna DOWIEDZIONY historią) to UPDATE
    z eventem — podniesienie pewności zostawia ślad.

    PRECEDENCJA `user` > `history` > `window` STOI TU, w klindze, nie w pętli wołającego: pewność
    wolno PODNIEŚĆ, nigdy obniżyć. Dotyczy to obu szczebli i z tego samego powodu — relacji
    rozstrzygniętej ręką automat nie ma prawa zdegradować do kandydata, a relacji DOWIEDZIONEJ
    zeznaniem pliku nie ma prawa zdegradować przebieg, który tego zeznania akurat nie przeczytał
    (plik na odłączonym dysku). Bez tego guardu jeden przebieg bez zamontowanego archiwum cofałby
    dowód po cichu — to ta sama reguła, którą oś obiektu trzyma przez `object_source='user'`.

    `_immediate`, bo guard (SELECT stanu) musi trzymać do zapisu: panel „Rodowód" pisze werdykt
    ręki z wątku GUI, gdy droga „Stosy" liczy w tle na własnym połączeniu. Bez locka SELECT widzi
    stan sprzed werdyktu i nadpisuje go kandydatem — albo trafia na `UNIQUE` i wywala etap."""
    with _immediate(con):
        row = con.execute(
            "SELECT rowid AS rid, asserted_by FROM integration_input "
            "WHERE integration_id = ? AND input_frame_id = ?",
            (integration_id, input_frame_id)).fetchone()
        if row is not None and (RANGA_ASSERT.get(row["asserted_by"], 0)
                                >= RANGA_ASSERT.get(asserted_by, 0)):
            return False
        if row is None:
            con.execute(
                "INSERT INTO integration_input(integration_id, input_frame_id, asserted_by) "
                "VALUES (?, ?, ?)", (integration_id, input_frame_id, asserted_by))
        else:
            con.execute("UPDATE integration_input SET asserted_by = ? WHERE rowid = ?",
                        (asserted_by, row["rid"]))
        emit_event(con, actor=actor, verb="integration.linked",
                   target=f"integration:{integration_id}", now=now,
                   payload={"input_frame_id": input_frame_id, "asserted_by": asserted_by,
                            **({"before": row["asserted_by"]} if row is not None else {})})
    return True


def unlink_integration_input(con, *, integration_id, input_frame_id, now, actor="stacks"):
    """Zdejmij wejście, którego bieżące dopasowanie już nie wskazuje — `event(integration.unlinked)`.

    RECONCILE w modelu append-only (§4.2 briefu): wiersz relacji jest WSKAŹNIKIEM bieżącego
    dopasowania, więc znika z tabeli, a jego historia zostaje w dzienniku — dokładnie jak przy
    `calibration.unlinked`, gdzie doskan podstawia bliższego mastera.

    Wołający MUSI pominąć relacje `asserted_by='user'` — automat nie ma prawa cofać rozstrzygnięcia
    ręki. Guard stoi TU (`AND asserted_by <> 'user'`), bo ostatnią bramką jest klinga, nie pętla."""
    with con:
        cur = con.execute(
            "DELETE FROM integration_input WHERE integration_id = ? AND input_frame_id = ? "
            "AND asserted_by <> 'user'", (integration_id, input_frame_id))
        if not cur.rowcount:
            return False
        emit_event(con, actor=actor, verb="integration.unlinked",
                   target=f"integration:{integration_id}", now=now,
                   payload={"input_frame_id": input_frame_id})
    return True


def judge_integration_input(con, *, integration_id, input_frame_id, excluded, now, uid="local"):
    """ROZSTRZYGNIĘCIE RĘKĄ (I-2d): człowiek potwierdza kandydata albo go odrzuca —
    `asserted_by='user'` + `excluded` 0/1, `event(integration.judged)`.

    ODRZUCONY WIERSZ ZOSTAJE, nie znika: „ta klatka NIE weszła w ten obraz" jest faktem tak samo
    jak „weszła", a skasowanie go kazałoby automatowi odkrywać ją na nowo przy każdym przebiegu.
    Precedencji broni `link_integration`/`unlink_integration_input` (oba omijają `user`), więc
    werdykt przeżywa kolejne przebiegi rodowodu.

    Idempotentny: ten sam werdykt na tym samym wierszu → `False` bez eventu (przeklikanie w oknie
    nie ma prawa puchnąć dziennika)."""
    row = con.execute(
        "SELECT rowid AS rid, asserted_by, excluded FROM integration_input "
        "WHERE integration_id = ? AND input_frame_id = ?",
        (integration_id, input_frame_id)).fetchone()
    excluded = 1 if excluded else 0
    if row is not None and (row["asserted_by"], row["excluded"]) == ("user", excluded):
        return False
    with _immediate(con):
        if row is None:
            con.execute(
                "INSERT INTO integration_input(integration_id, input_frame_id, asserted_by, "
                "excluded) VALUES (?, ?, 'user', ?)", (integration_id, input_frame_id, excluded))
        else:
            con.execute(
                "UPDATE integration_input SET asserted_by = 'user', excluded = ? WHERE rowid = ?",
                (excluded, row["rid"]))
        emit_event(con, actor=f"user:{uid}", verb="integration.judged",
                   target=f"integration:{integration_id}", now=now,
                   payload={"input_frame_id": input_frame_id, "excluded": excluded,
                            "before": None if row is None else
                            {"asserted_by": row["asserted_by"], "excluded": row["excluded"]}})
    return True


def flag_stack_lineage_summary(con, items, now, actor="stacks", kept_unread=0, kept_frames=(),
                               kept_proven=0):
    """Stosy BEZ zapisanych wejść — JEDEN `event(integration.lineage_summary)` z licznością per
    powód (wzorzec `flag_calibration_lineage_summary`). Stan (`unresolved_reason` niepuste) SAM
    jest deltą; pusty materiał → bez eventu.

    `kept_unread` (stosy, których rodowodu przebieg ŚWIADOMIE nie ruszył, bo nie przeczytał pliku)
    wchodzi do payloadu i SAM wystarcza, żeby event powstał: masowa decyzja „nie dotykam N gotowych
    rodowodów" jest faktem o przebiegu, a bez śladu w dzienniku wyglądałaby jak brak roboty.
    `kept_frames` niesie ICH KLATKI — sam licznik jest receptą bez adresu, bo stanu pominiętych nie
    da się odróżnić od stanu przeliczonych (głowy nietknięte, żadnego markera w tabeli).

    `kept_proven` (S2b) liczy DRUGI powód pominięcia i dlatego jest osobną liczbą: rodowód, którego
    przebieg nie ruszył, bo ZAPISANE zeznanie jest MOCNIEJSZE od tego, co umiał policzyć teraz
    (`RANGA_ASSERT`) — plik był czytelny, więc „nie przeczytałem" byłoby nieprawdą o przyczynie.
    Zlanie obu w `kept_unread` kazałoby człowiekowi szukać odłączonego dysku przy stosie, który
    leży na dysku i ma się dobrze."""
    items = list(items)
    if not items and not kept_unread and not kept_proven:
        return
    with con:
        emit_event(con, actor=actor, verb="integration.lineage_summary", target="frame:*", now=now,
                   payload={"distinct": len(items), "frames": sum(n for _, n in items),
                            "items": [[reason, n] for reason, n in items],
                            "kept_unread": kept_unread,
                            "kept_proven": kept_proven,
                            "kept_frames": list(kept_frames)})


# ═══════════════════════════════════════════════ 1.8 kuratela celów + park (planer T4)
# Dwa pola UŻYTKOWNIKA o PRZYSZŁOŚCI (co chcę sfotografować, czym będę fotografował). Reszta bazy
# zeznaje przeszłość, więc żadnego z nich nie da się zderywować — `max(date_obs)` wskazałby jako
# „aktualny" teleskop, którego user nie używa (D-0731-12). Zapis wyłącznie z ręki, `actor=user:<uid>`.

def _target_plan_row(con, canon):
    """Wiersz kuratelii jako dict albo `None`. Osobno, bo czytają go OBIE funkcje zapisu (payload
    eventu musi nieść stan SPRZED zmiany — także przy kasacji, gdzie po fakcie nie ma go skąd wziąć)."""
    row = con.execute(
        "SELECT canon, status, priority, note, created_at, updated_at "
        "FROM target_plan WHERE canon = ?", (canon,)).fetchone()
    return None if row is None else dict(row)


def set_target_plan(con, *, canon, status, priority=None, note=None, now, uid="local"):
    """Oznacz cel katalogu (`status`/`priority`/`note`) — akcja usera, klucz = KANON KATALOGU.

    Kanon MUSI być zwalidowany wobec assetu przez wołającego (`targets.resolve_plan_canon`) — repo
    nie czyta plików katalogu, a wiersz na literówce nigdy nie spotkałby celu. Słownik statusów
    trzyma CHECK w DDL (0011), nie kod: baza jest ostatnią bramką i przeżyje każdą powierzchnię.
    Idempotentny: ten sam komplet trzech pól → `False` BEZ eventu (przeklikanie w GUI nie ma prawa
    puchnąć dziennika). Inaczej INSERT albo UPDATE + `event(target_plan.set)` z `{before, after}`
    — `before=None` odróżnia założenie od zmiany."""
    if not str(canon or "").strip():
        raise ValueError("kanon pusty — kuratela bez celu nie ma sensu")
    canon = str(canon).strip()
    with _immediate(con):
        before = _target_plan_row(con, canon)
        after = {"canon": canon, "status": status, "priority": priority, "note": note}
        if before is not None and all(before[k] == after[k] for k in ("status", "priority", "note")):
            return False
        if before is None:
            con.execute(
                "INSERT INTO target_plan (canon, status, priority, note, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)", (canon, status, priority, note, now, now))
        else:
            con.execute(
                "UPDATE target_plan SET status = ?, priority = ?, note = ?, updated_at = ? "
                "WHERE canon = ?", (status, priority, note, now, canon))
        emit_event(con, actor=f"user:{uid}", verb="target_plan.set",
                   target=f"target_plan:{canon}", now=now,
                   payload={"before": before, "after": after})
    return True


def clear_target_plan(con, *, canon, now, uid="local"):
    """Zdejmij oznaczenie celu — KASUJE wiersz. Zwraca `True`, gdy było co kasować.

    DELETE na tabeli TRWAŁEJ jest tu świadomym precedensem (dotąd kasowały się wyłącznie tabele
    stagingu): `target_plan` znaczy „bieżąca lista życzeń", nie „historia życzeń". Nagrobek
    (`status` pusty) zmusiłby KAŻDY odczyt do filtrowania i zamienił małą tabelę w archiwum stanów.
    Historia nie ginie — `event(target_plan.cleared)` niesie CAŁY wiersz sprzed kasacji, więc
    odtworzenie jest odczytem dziennika, nie archeologią."""
    canon = str(canon or "").strip()
    with _immediate(con):
        before = _target_plan_row(con, canon)
        if before is None:
            return False
        con.execute("DELETE FROM target_plan WHERE canon = ?", (canon,))
        emit_event(con, actor=f"user:{uid}", verb="target_plan.cleared",
                   target=f"target_plan:{canon}", now=now, payload={"before": before})
    return True


def set_telescope_park(con, *, telescope_id, in_park, now, uid="local"):
    """Wstaw/wyjmij teleskop z PARKU AKTUALNEGO (`telescope.in_park`) — akcja usera (D-T3-d).

    `in_park`: 1 = w parku · 0 = jawnie historyczny · `None` = cofnięcie do „nic nie powiedziano".
    Trójstan jest niesiony do końca, bo `NULL` i `0` znaczą co innego (baza świeża vs park
    przejrzany). GUARD: tylko KANONICZNY teleskop (`merged_into IS NULL`) — park wskazujący wiersz
    scalony w inny opisywałby oś, której już nie ma (lustro `approve_telescope`). Idempotentny:
    ta sama wartość → `False` bez eventu."""
    if in_park not in (0, 1, None):
        raise ValueError(f"in_park={in_park!r} — dozwolone 1 (park) | 0 (historyczny) | None")
    with _immediate(con):
        row = con.execute(
            "SELECT telescop_canon, in_park, merged_into FROM telescope WHERE id = ?",
            (telescope_id,)).fetchone()
        if row is None:
            raise ValueError(f"telescope:{telescope_id} nie istnieje")
        if row["merged_into"] is not None:
            raise ValueError(f"telescope:{telescope_id} jest scalony (merged_into="
                             f"{row['merged_into']}) — park tylko dla kanonicznego")
        if row["in_park"] == in_park:
            return False
        con.execute("UPDATE telescope SET in_park = ? WHERE id = ?", (in_park, telescope_id))
        emit_event(con, actor=f"user:{uid}", verb="telescope.parked",
                   target=f"telescope:{telescope_id}", now=now,
                   payload={"telescope": row["telescop_canon"],
                            "before": row["in_park"], "after": in_park})
    return True


# ═══════════════════════════════════════════════ 1.9 perspektywy (nazwane widoki, I-1 / D-P-I-3)
# Perspektywa = nazwany komplet {filtr + kolumny + grupowanie + facety}, którym user ogląda Zbiory.
# Mieszkała w rejestrze użytkownika (D-B); D-P-I-3 odwróciło tę decyzję ŚWIADOMIE: nazwany widok
# jest własnością ARCHIWUM, nie komputera — jedzie z bazą na laptop i przeżywa reinstalację.
# Rejestr zostaje własnością BIURKA (progi planera, ostatnie katalogi) i to nie jest niekonsekwencja,
# tylko granica: „czym patrzę na archiwum" vs „jak mam ustawione to okno".

def save_perspective(con, *, name, spec, now, uid="local"):
    """Zapisz nazwaną perspektywę — `(id, verb)`; `verb=None`, gdy nic się nie zmieniło.

    KOLIZJA NAZW JEST UPSERTEM JAWNYM, NIGDY CICHĄ PODMIANĄ (F9 recenzji). Perspektywa wędruje
    z bazą, więc ta sama nazwa potrafi przyjechać z drugiej maszyny z INNĄ treścią — a wtedy
    „zapisano" bez słowa o nadpisaniu byłoby komunikatem o czymś, co się nie stało. Stąd dwa
    czasowniki: `perspective.saved` (nowa) i `perspective.overwritten` (z `before`/`after`).

    Idempotentny: identyczna specyfikacja pod tą samą nazwą → `verb=None` bez eventu. To nie jest
    kosmetyka dziennika — na tym stoi jednorazowy import z rejestru (`grid._import_settings_
    perspectives`), który przy każdym starcie okna woła tę funkcję dla wszystkich znanych nazw.

    `spec` idzie przez `json.dumps` z `sort_keys`, bo porównanie „czy się zmieniła" jest
    porównaniem TEKSTU — bez stabilnej kolejności kluczy ten sam widok potrafiłby wyglądać na
    zmieniony i puchnąć dziennik przy każdym starcie."""
    name = str(name or "").strip()
    if not name:
        raise ValueError("perspektywa bez nazwy — nazwa JEST tożsamością tego wiersza")
    text = json.dumps(spec, sort_keys=True, ensure_ascii=False)
    with _immediate(con):
        row = con.execute("SELECT id, spec_json FROM saved_query WHERE name = ?",
                          (name,)).fetchone()
        if row is None:
            cur = con.execute(
                "INSERT INTO saved_query(name, spec_json, created_at) VALUES (?, ?, ?)",
                (name, text, now))
            emit_event(con, actor=f"user:{uid}", verb="perspective.saved",
                       target=f"perspective:{name}", now=now, payload={"spec": spec})
            return cur.lastrowid, "perspective.saved"
        if row["spec_json"] == text:
            return row["id"], None
        con.execute("UPDATE saved_query SET spec_json = ?, updated_at = ? WHERE id = ?",
                    (text, now, row["id"]))
        emit_event(con, actor=f"user:{uid}", verb="perspective.overwritten",
                   target=f"perspective:{name}", now=now,
                   payload={"before": row["spec_json"], "after": spec})
    return row["id"], "perspective.overwritten"


# USUWANIA PERSPEKTYWY TU NIE MA — i to jest decyzja, nie przeoczenie. Powierzchnia nigdy go nie
# miała (rejestr też nie dawał drogi z okna), a pisarz bez ekranu byłby kodem dla nikogo. Dług
# nazwany w kolejce: kasowanie ma sens dopiero razem z listą perspektyw do zarządzania, a to jest
# ekran, nie funkcja.
