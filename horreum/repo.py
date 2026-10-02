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
import zlib
from contextlib import contextmanager
from dataclasses import dataclass, replace

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
        frame_id = _insert_frame(
            con, sha1_data=sha1_data, sha1_data_uncomputable=sha1_data_uncomputable, kind=kind,
            kind_source=kind_source, filetype=filetype, camera_id=camera_id, now=now, actor=actor)
    return frame_id, True


def _insert_frame(con, *, sha1_data, sha1_data_uncomputable, kind, kind_source, filetype,
                  camera_id, now, actor):
    """INSERT frame + `event(frame.observed)` BEZ własnej transakcji - trzyma ją wołający
    (`upsert_frame`, `rebind_location_to_identity`). Jeden literał dla obu dróg wyłonienia klatki."""
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
    return frame_id


# FAKTY KOPII Z JEJ NAGŁÓWKA (0021) - kolumny `location` w kolejności literałów SQL tego modułu.
# Słownik `copy_facts` (skład: `scan.copy_header_facts`) niesie DOKŁADNIE te klucze: literał SQL
# wymienia kolumny po nazwie, więc brak klucza byłby cichym NULL-em, a nadmiar - zgubionym faktem.
# `hdr_hash` jest KOTWICĄ (CHECK 0021: NULL albo `== header_hash`) - opis w nagłówku migracji.
COPY_FACTS = ("image_count", "image_roles", "hdr_filter", "hdr_imagetyp", "hdr_object",
              "hdr_telescop", "hdr_instrume", "hdr_exptime", "hdr_xbinning", "hdr_date_obs",
              "hdr_hash")


def _copy_facts_checked(copy_facts):
    """EXPECT na kształcie słownika faktów kopii - jeden strażnik dla trzech pisarzy (dodanie,
    odświeżenie, uzupełnienie). Zwraca słownik z kompletem kluczy; `None` → same NULL-e."""
    if copy_facts is None:
        return dict.fromkeys(COPY_FACTS)
    if set(copy_facts) != set(COPY_FACTS):
        raise ValueError(f"fakty kopii: klucze {sorted(copy_facts)} != {sorted(COPY_FACTS)}")
    return copy_facts


def add_location(con, *, frame_id, volume, path, drive_letter=None, tier=None, mtime=None,
                 file_sha1=None, header_hash=None, hdu_index=None, compressed=None,
                 size_bytes=None, copy_facts=None, now, actor="scan"):
    """Dołóż lokalizację frame'a po `UNIQUE(volume, path)` wraz z faktami KOPII (file_sha1/
    header_hash/hdu_index/compressed/size_bytes — brief §2; `hdu_index`/`compressed` NULL dla XISF,
    wszystkie odciski NULL przy W1). Już znana →
    (id, False) bez eventu i BEZ dotykania faktów (odświeżenie = `refresh_location`, osobny
    kontrakt). Nowa → INSERT + `event(location.added)`; (id, True). `volume` = trwały
    identyfikator wolumenu; placeholder '?' NIE blokuje skanu (to nie tożsamość frame'a, §7.5).
    `drive_letter` to efemeryczny cache wyświetlania.

    `copy_facts` (0021) - fakty z nagłówka TEJ kopii (klucze `COPY_FACTS`); `None` = nie zebrane
    (kolumny NULL, kopię dobierze uzupełnienie). Kotwica `hdr_hash` musi równać się `header_hash`
    - pilnuje tego CHECK w bazie, nie ten kod."""
    row = con.execute(
        "SELECT id FROM location WHERE volume = ? AND path = ?", (volume, path)).fetchone()
    if row is not None:
        return row[0], False

    cf = _copy_facts_checked(copy_facts)
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
            "file_sha1, header_hash, hdu_index, compressed, size_bytes, last_verified_at, "
            "image_count, image_roles, hdr_filter, hdr_imagetyp, hdr_object, hdr_telescop, "
            "hdr_instrume, hdr_exptime, hdr_xbinning, hdr_date_obs, hdr_hash) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (frame_id, volume, drive_letter, path, tier, mtime,
             file_sha1, header_hash, hdu_index, compressed, size_bytes, now,
             *(cf[k] for k in COPY_FACTS)),
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
# `unreadable_kind`/`unreadable_reason` TU (P4-2): rodzaj i powód żyją i gasną RAZEM z markerem
# (CHECK 0019 odbija powód bez markera), więc wyzdrowienie musi je zdjąć tym samym UPDATE-em,
# a ich przejście - jak przejście markera - jest śladem w payloadzie `location.refreshed`.
# SPOT: każda nazwa z tej krotki MUSI występować w literale UPDATE niżej (pinuje test strukturalny
# `test_presence.py::test_location_facts_pokrywaja_update`) — inaczej diff wykrywa zmianę, której
# UPDATE nie zapisuje, i event leci w nieskończoność co skan.
# `COPY_FACTS` TU (0021): liczba/role obrazów i zeznanie nagłówka kopii są faktami KOPII jak odcisk
# nagłówka - ich przejście idzie do tego samego payloadu `location.refreshed`, a zmiana odcisku
# i zmiana faktów lecą JEDNYM UPDATE-em (kotwica `hdr_hash == header_hash`, CHECK 0021).
_LOCATION_FACTS = ("mtime", "file_sha1", "header_hash", "hdu_index", "compressed", "size_bytes",
                   "unreadable_since", "unreadable_kind", "unreadable_reason", "present",
                   *COPY_FACTS)


def rebind_location(con, *, location_id, frame_after, now, actor="scan", inplace_gen=None):
    """PODMIANA TREŚCI pod znaną ścieżką (R3-b1): przepnij `location.frame_id` na nową tożsamość
    + `event(location.rebound)` `{frame_before, frame_after}`. Stary frame ZOSTAJE (append-only,
    historia w eventach) — bez ŻADNEJ lokacji. UWAGA (P5): pass zniknięć takiego frame'a NIE
    podchwyci — działa na LOKACJACH, a tu nie została ani jedna (`vanished_frames` też go wyklucza
    guardem `EXISTS`, `gui/queries.py:516-520`). Licznik `orphan_frames` = osobna, tania decyzja;
    dopóki jej nie ma, osierocone frame'y są widoczne wyłącznie przez `location.rebound`. Już przepięta → False
    (idempotencja). Guard+UPDATE w `_immediate` (TOCTOU wobec równoległego writera).
    `inplace_gen` - generacja dziennika zapisu w miejscu z odczytu skanu (`_refuse_if_newer_inplace`,
    kontrakt jak w `refresh_location`)."""
    with _immediate(con):
        row = con.execute(
            "SELECT frame_id FROM location WHERE id = ?", (location_id,)).fetchone()
        if row is None:
            raise ValueError(f"location:{location_id} nie istnieje")
        _refuse_if_newer_inplace(con, location_id, inplace_gen)
        return _rebind(con, location_id=location_id, frame_before=row["frame_id"],
                       frame_after=frame_after, now=now, actor=actor)


def _rebind(con, *, location_id, frame_before, frame_after, now, actor):
    """UPDATE `location.frame_id` + `event(location.rebound)` BEZ własnej transakcji; ta sama
    tożsamość → False bez zapisu. Wołają ją `rebind_location` i `rebind_location_to_identity`."""
    if frame_before == frame_after:
        return False
    con.execute("UPDATE location SET frame_id = ? WHERE id = ?", (frame_after, location_id))
    emit_event(con, actor=actor, verb="location.rebound", target=f"location:{location_id}",
               now=now, payload={"frame_before": frame_before, "frame_after": frame_after})
    return True


def rebind_location_to_identity(con, *, location_id, sha1_data, sha1_data_uncomputable=0, kind,
                                filetype, camera_id, now, actor="scan", kind_source=None,
                                inplace_gen=None):
    """PODMIANA TREŚCI jedną transakcją (AR-31): wyłonienie klatki nowej tożsamości (kontrakt
    `upsert_frame`) + przepięcie lokacji (kontrakt `rebind_location`). Zwraca
    `(frame_id, created)`.

    DLACZEGO RAZEM: strażnik generacji (`_refuse_if_newer_inplace`) siedzi w transakcji przepięcia.
    Klatka wyłoniona OSOBNĄ transakcją przed nim zostawała po `StaleScanRecord` w bazie, a ponowienie
    skanu widziało ją jako istniejącą (`created=False`) i nie nagrywało zeznania - klatka bez
    `header` na stałe (także w następnych przebiegach). Tu strażnik stoi PRZED zapisem, a odmowa
    cofa całość, więc ponowienie widzi `created=True` uczciwie."""
    with _immediate(con):
        row = con.execute(
            "SELECT frame_id FROM location WHERE id = ?", (location_id,)).fetchone()
        if row is None:
            raise ValueError(f"location:{location_id} nie istnieje")
        _refuse_if_newer_inplace(con, location_id, inplace_gen)
        frame = con.execute("SELECT id FROM frame WHERE sha1_data = ?", (sha1_data,)).fetchone()
        created = frame is None
        frame_id = _insert_frame(
            con, sha1_data=sha1_data, sha1_data_uncomputable=sha1_data_uncomputable, kind=kind,
            kind_source=kind_source, filetype=filetype, camera_id=camera_id, now=now,
            actor=actor) if created else frame[0]
        _rebind(con, location_id=location_id, frame_before=row["frame_id"],
                frame_after=frame_id, now=now, actor=actor)
    return frame_id, created


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
    = przeniesiono oś sprzętu wskazaną ręką (R1); `lineage_moved` = ILE werdyktów rodowodu stosu
    przeszło na następczynię (0809, warunek Zdzinia) — liczba, nie bit, bo jedna klatka bywa
    wejściem wielu obrazów i raport ma powiedzieć ILU;
    `skipped` = powód pominięcia, gdy nic nie przeszło — GUI ma mówić DLACZEGO, nie milczeć."""
    object_moved: bool = False
    config_moved: bool = False
    lineage_moved: int = 0
    lineage_dropped: int = 0
    """ILE martwych wskaźników rodowodu zdjęto, bo następczyni miała już WŁASNY werdykt (0810).
    Osobno od `lineage_moved`, bo to inna robota i inny skutek: tam werdykt przechodzi, tu znika
    wiersz, który po geście człowieka przestał cokolwiek wskazywać. Sklejenie ich w jedną liczbę
    kazałoby raportowi mówić „przeniesiono", gdy nic nie przeszło."""
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

    TRZECIA OŚ: WERDYKTY RODOWODU STOSU (0809, warunek Zdzinia „wprowadzanie nowych subów albo
    masterów nie może wpłynąć na wycofanie czegokolwiek już ustawionego ręcznie"). Przenosimy
    wiersze `integration_input` ze źródłem `user`, w których zastąpiona klatka jest **WEJŚCIEM** —
    czyli werdykt „ten sub wszedł w ten obraz" albo „NIE wszedł" (`excluded`). Bez tego edycja
    RAW-a (jedyna droga, którą klatka bywa zastępowana) zostawiała potwierdzenie ręki na tożsamości
    bez pliku, a obraz tracił wejście, którego nikt nie cofnął.

    ROLA MASTERA ŚWIADOMIE POZA PRZENIESIENIEM — i to jest granica, nie przeoczenie. Gdy zastąpiona
    klatka jest GŁOWĄ integracji (`integration.master_frame_id`), zostaje nią nadal: ponownie
    zapisany master to NOWE PRZETWORZENIE, a nie ten sam obraz (dwa flow archiwum: wersje obróbki
    jednej sesji są osobnymi obrazami). Przepięcie głowy byłoby OSĄDEM, którego nikt nie wydał —
    tym samym, przed którym broni §0 briefu.

    WIERSZ PRZECHODZI, NIE DUBLUJE SIĘ. `integration_input` jest z założenia WSKAŹNIKIEM bieżącego
    dopasowania, a historia zostaje w dzienniku (§4.2, `unlink_integration_input`) — więc stary
    wiersz znika z pary `integration.unlinked` + `.linked`, zamiast zostać jako drugi rekord o tym
    samym subie. Zostawienie obu dałoby dokładnie ten defekt, który zgłosił Zdzin 0809: powierzchnia
    roboty oferująca wiersz o pliku, którego nie ma. To NIE łamie append-only osi obiektu i sprzętu
    — tam klatka zastąpiona zostaje nietknięta, bo tam kolumna opisuje KLATKĘ, a nie relację.

    GUARD LUSTRZANY DO DWÓCH POZOSTAŁYCH: pomijamy integrację, w której następczyni ma JUŻ własny
    werdykt ręki — przemówiła sama i cudzy werdykt nie ma prawa jej nadpisać. Wiersz automatu
    (`window`/`history`) następczyni jest natomiast PODNOSZONY do `user`, bo to nie werdykt,
    tylko dopasowanie — ta sama precedencja, co w `RANGA_ASSERT`.

    …ALE POMINIĘCIE NIE ZNACZY „ZOSTAW" (`lineage_dropped`). Stary wskaźnik w takiej integracji
    jest ZDEJMOWANY, bo inaczej nie ma z niego żadnego wyjścia: przeniesienie go omija,
    `unlink_integration_input` omija `user`, a `pending_transfer` wyrzuca parę z kubełka. Stos
    liczyłby wtedy wejście klatki BEZ PLIKU na zawsze, a panel Rodowód pokazywałby wiersz z pustą
    ścieżką — ten sam defekt, który Zdzin zgłosił 0809 na osi obiektu („widzę plik bez ścieżki").
    Zdjęcie jest bezpieczne, bo o TEJ SAMEJ treści człowiek wypowiedział się drugi raz, po stronie
    następczyni; historia obu wypowiedzi zostaje w dzienniku.

    Zwraca `FactTransfer`. Idempotentne: powtórzenie po udanym przeniesieniu trafia w guardy trzech
    osi (następczyni ma już swoje) i zwraca `skipped` bez zapisu."""
    with _immediate(con):
        stara = con.execute(
            "SELECT superseded_by, object_id, object_source, object_cleared_id, "
            "       config_id, config_source "
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
        # Pytamy o rolę WEJŚCIA, nie głowy — patrz granica w docstringu.
        rodowod = con.execute(
            "SELECT integration_id, excluded FROM integration_input "
            "WHERE input_frame_id = ? AND asserted_by = 'user' ORDER BY integration_id",
            (frame_id,)).fetchall()
        if not ma_obiekt and not ma_config and not rodowod:
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
        # Integracje, w których następczyni ma JUŻ własny werdykt ręki — jej zdanie zostaje.
        wlasne = {r["integration_id"] for r in con.execute(
            "SELECT integration_id FROM integration_input "
            "WHERE input_frame_id = ? AND asserted_by = 'user'", (nowa_id,))}
        rodowod_do_przeniesienia = [r for r in rodowod if r["integration_id"] not in wlasne]
        # …a STARY wskaźnik w takiej integracji trzeba ZDJĄĆ, nie zostawić (bramka pakietu 3a,
        # zarzut 1 — jedyny POWAŻNY, który przeżył adjudykację co do kodu). Zostawiony był stanem
        # BEZ WYJŚCIA: przeniesienie go omija (następczyni ma swoje), `unlink_integration_input`
        # omija `user`, a `pending_transfer` wyrzuca parę z kubełka — więc stos liczyłby wejście
        # klatki BEZ PLIKU na zawsze, a panel Rodowód pokazywał wiersz z pustą ścieżką. To jest
        # co do joty defekt, który Zdzin zgłosił 0809 („widzę plik bez ścieżki"), tyle że na innej
        # osi. Zdjęcie jest tu bezpieczne i jedyne sensowne: `integration_input` to WSKAŹNIK
        # bieżącego dopasowania (§4.2), a bieżącym dopasowaniem jest następczyni — o tej samej
        # treści człowiek wypowiedział się drugi raz i to jego zdanie zostaje.
        rodowod_do_zdjecia = [r for r in rodowod if r["integration_id"] in wlasne]
        if (not obiekt_do_przeniesienia and not config_do_przeniesienia
                and not rodowod_do_przeniesienia and not rodowod_do_zdjecia):
            # POWÓD MA BYĆ PRAWDZIWY, nie jeden dla wszystkich odmów: „następczyni ma własne
            # źródło" i „zestaw do niej nie pasuje" to dwa różne stany i dwie różne dalsze drogi
            # (w pierwszym nie ma nic do roboty, w drugim ręka musi wskazać zestaw od nowa).
            nie_pasuje = ma_config and (nowa["config_source"] is None
                                        and nowa["config_id"] is None)
            return FactTransfer(skipped="zestaw nie pasuje do nastepczyni" if nie_pasuje
                                else "nastepczyni ma wlasne zrodlo")

        if obiekt_do_przeniesienia:
            # PAMIĘĆ NAGROBKA JEDZIE Z NIM (0017), w tym samym `UPDATE`, co źródło: przeniesienie
            # ma oddać następczyni CAŁY werdykt ręki, a werdykt brzmi „to nie jest X" — bez `X`
            # zostałoby z niego samo „to nie jest". Dla klatki z obiektem kolumna jest NULL-em
            # i przechodzi NULL-em, więc jeden zapis obsługuje obie gałęzie (`CHECK` w DDL i tak
            # nie przepuściłby pamięci przy niepustym `object_id`).
            con.execute("UPDATE frame SET object_id = ?, object_source = ?, "
                        "object_cleared_id = ? WHERE id = ?",
                        (stara["object_id"], stara["object_source"],
                         stara["object_cleared_id"], nowa_id))
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
        for r in rodowod_do_przeniesienia:
            iid = r["integration_id"]
            # Kwalifikator `excluded.` to PSEUDO-TABELA upserta SQLite, nie nasza kolumna o tej
            # samej nazwie — zbieżność nazw jest niefortunna, ale wartość bierzemy z wiersza
            # WSTAWIANEGO, czyli z werdyktu klatki zastąpionej.
            con.execute(
                "INSERT INTO integration_input(integration_id, input_frame_id, asserted_by, "
                "excluded) VALUES (?, ?, 'user', ?) "
                "ON CONFLICT(integration_id, input_frame_id) DO UPDATE SET asserted_by = 'user', "
                "excluded = excluded.excluded",
                (iid, nowa_id, r["excluded"]))
            con.execute(
                "DELETE FROM integration_input WHERE integration_id = ? AND input_frame_id = ?",
                (iid, frame_id))
            emit_event(con, actor=actor, verb="integration.linked", target=f"integration:{iid}",
                       now=now, payload={"input_frame_id": nowa_id, "asserted_by": "user",
                                         "excluded": r["excluded"], "przeniesione_z": frame_id},
                       reason="werdykt rodowodu przeniesiony po podmianie pliku")
            emit_event(con, actor=actor, verb="integration.unlinked", target=f"integration:{iid}",
                       now=now, payload={"input_frame_id": frame_id,
                                         "przeniesione_na": nowa_id})
        for r in rodowod_do_zdjecia:
            iid = r["integration_id"]
            con.execute(
                "DELETE FROM integration_input WHERE integration_id = ? AND input_frame_id = ?",
                (iid, frame_id))
            emit_event(con, actor=actor, verb="integration.unlinked", target=f"integration:{iid}",
                       now=now, payload={"input_frame_id": frame_id, "nastepczyni": nowa_id},
                       reason="następczyni ma własny werdykt — stary wskaźnik nic nie wskazuje")
    return FactTransfer(object_moved=obiekt_do_przeniesienia,
                        config_moved=config_do_przeniesienia,
                        lineage_moved=len(rodowod_do_przeniesienia),
                        lineage_dropped=len(rodowod_do_zdjecia))


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


@dataclass(frozen=True)
class RetireGesture:
    """Wynik GESTU WYCOFANIA/PRZYWRÓCENIA klatki (D-OW-3/R2) — liczniki PER POWÓD, wzorem
    `ObjectGesture`.

    Jeden licznik „pominięto N" byłby prawdą bezużyteczną: zaznaczenie z paska Zbiorów bywa
    mieszane, a cztery powody znaczą dla człowieka co INNEGO — „ochrona zadziałała, bo plik żyje"
    to zupełnie inna wiadomość niż „to już było wycofane"."""
    done: int = 0                  # klatki realnie wycofane albo przywrócone
    skipped_present: int = 0       # ma OBECNĄ kopię — plik żyje, więc robota jest prawdziwa
    skipped_no_location: int = 0   # bez ŻADNEJ lokacji (sierota po `rebind_location`) — inny stan
    skipped_superseded: int = 0    # zastąpiona: jej sprawę zamknęła NASTĘPCZYNI, nie ta ręka
    skipped_already: int = 0       # już w docelowym stanie (idempotencja)

    @property
    def skipped(self):
        """Suma pominięć — właścicielem składu jest TA suma, żeby nowy człon nie wpadał do „z M"
        i nie znikał z rozbicia (lekcja `ObjectGesture.skipped`)."""
        return (self.skipped_present + self.skipped_no_location + self.skipped_superseded
                + self.skipped_already)

    @property
    def skipped_breakdown(self):
        """Rozbicie jako [(sufiks klucza i18n, n)] — JEDEN właściciel kolejności i składu."""
        return [("present", self.skipped_present), ("no_location", self.skipped_no_location),
                ("superseded", self.skipped_superseded), ("already", self.skipped_already)]


def _retire_verdict(row):
    """Który powód pomijania łapie tę klatkę przy WYCOFANIU — albo None, gdy wolno ją wycofać.

    JEDEN właściciel kolejności guardów. Kolejność JEST regułą, tak jak przy tłowaniu gridu:
    `superseded` bije `no_location`, bo klatka zastąpiona jest sierotą Z WYJAŚNIENIEM (jej treść
    niesie następczyni), a sierota bez ogniwa to otwarte pytanie — zlanie ich w jeden powód
    kazałoby ekranowi powiedzieć „bez lokalizacji" o klatce, o której wiadomo wszystko."""
    if row["retired_at"] is not None:
        return "skipped_already"
    if row["superseded_by"] is not None:
        return "skipped_superseded"
    if row["n_locations"] == 0:
        return "skipped_no_location"
    if row["n_present"] > 0:
        return "skipped_present"
    return None


def _retire_rows(con, frame_ids):
    """Stan klatek potrzebny obu gestom, czytany JEDNYM literałem WEWNĄTRZ transakcji (TOCTOU).

    Klatki spoza bazy po prostu nie wracają — gest opisuje to, co zastał, a nie to, o co pytał."""
    return con.execute(
        "SELECT f.id, f.retired_at, f.superseded_by, "
        "       (SELECT COUNT(*) FROM location l WHERE l.frame_id = f.id) AS n_locations, "
        "       (SELECT COUNT(*) FROM location l WHERE l.frame_id = f.id AND l.present = 1) "
        "           AS n_present "
        "FROM frame f WHERE f.id IN (SELECT value FROM json_each(?))",
        (json.dumps([int(i) for i in frame_ids]),)).fetchall()


def retire_frames(con, *, frame_ids, now, uid="local"):
    """WYCOFANIE klatek gestem człowieka (D-OW-3/R2): `frame.retired_at` + `event(frame.retired)`.

    Zamyka sprawę klatki, której PLIK ZNIKNĄŁ Z DYSKU. Do tej klingi jedynym wyjściem była kasacja
    wierszy (C3) — czyli utrata nagłówka, kart, rodowodu i werdyktów ręki. Wycofana klatka wypada
    z kubełków ROBOCZYCH, a **zostaje w archiwum i w godzinach**: została naświetlona naprawdę,
    a następczyni, która by te godziny przejęła, nie ma (inaczej niż przy `superseded_by`).

    CZTERY POWODY POMIJANIA, nie wyjątek (`_retire_verdict`) — cel gestu to ZAZNACZENIE z widoku,
    więc wpadną w nie klatki żywe. Guard obecnej kopii jest tym samym guardem, którym broni się
    `mark_superseded`: gest, który ukrywa klatkę z żywym plikiem, chowa realną robotę.

    ⚠️ GUARD NIE JEST OSTATNIM SŁOWEM ŚWIATA, tylko chwilą zapisu. Plik może wrócić na dysk PO
    commicie — zwykłym re-skanem (`refresh_location` zapala `present = 1`). Powstaje wtedy stan
    sprzeczny „wycofana, a kopia obecna" i tej sprzeczności **nie gasimy automatycznie**: byłoby to
    cofnięcie gestu ręki przez wjazd materiału (warunek stały „ręka nietykalna"). Ma być GŁOŚNA —
    liczy ją `audit.retire_invariants` (§5.17) i pokazuje własny, AKCYJNY wiersz Porządków.

    Idempotencja jak reszta repo: powtórzenie → wszystkie klatki w `skipped_already`, zero eventów.
    Payload niesie OSTATNIE ZNANE ŚCIEŻKI: po wycofaniu żaden kubełek ich nie pokaże, a „gdzie ten
    plik leżał" jest jedynym pytaniem, które człowiek zada po fakcie."""
    g = RetireGesture()
    with _immediate(con):
        for row in _retire_rows(con, frame_ids):
            powod = _retire_verdict(row)
            if powod is not None:
                g = replace(g, **{powod: getattr(g, powod) + 1})
                continue
            paths = [r["path"] for r in con.execute(
                "SELECT path FROM location WHERE frame_id = ? ORDER BY id", (row["id"],))]
            con.execute("UPDATE frame SET retired_at = ? WHERE id = ?", (now, row["id"]))
            emit_event(con, actor=f"user:{uid}", verb="frame.retired",
                       target=f"frame:{row['id']}", now=now, payload={"paths": paths})
            g = replace(g, done=g.done + 1)
    return g


def restore_frames(con, *, frame_ids, now, uid="local"):
    """PRZYWRÓCENIE klatki wycofanej: `retired_at = NULL` + `event(frame.unretired)`.

    DROGA POWROTU jest tu WARUNKIEM, nie ozdobą — wycofanie jest werdyktem CZŁOWIEKA (a nie faktem
    o świecie, jak `superseded_by`), a paczka, która dokłada nieodwracalny gest, wnosi dokładnie
    ten dług, który domyka (grupa G2).

    JEDEN guard, bo jeden warunek ma sens: klatka nie wycofana → `skipped_already`. Obecność kopii
    NIE jest tu powodem pominięcia i to jest sedno — powrót pliku to najczęstszy powód, dla którego
    człowiek sięga po ten gest."""
    g = RetireGesture()
    with _immediate(con):
        for row in _retire_rows(con, frame_ids):
            if row["retired_at"] is None:
                g = replace(g, skipped_already=g.skipped_already + 1)
                continue
            con.execute("UPDATE frame SET retired_at = NULL WHERE id = ?", (row["id"],))
            emit_event(con, actor=f"user:{uid}", verb="frame.unretired",
                       target=f"frame:{row['id']}", now=now,
                       payload={"retired_at_before": row["retired_at"]})
            g = replace(g, done=g.done + 1)
    return g


def refresh_location(con, *, location_id, frame_id, mtime, file_sha1, header_hash,
                     hdu_index, compressed, size_bytes, unreadable_since, unreadable_kind,
                     unreadable_reason, present, now,
                     actor="scan", raw_json=None, cards=None, hot_fields=None, camera_id=None,
                     kind=None, copy_facts=None, inplace_gen=None):
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
    - **`unreadable_kind`/`unreadable_reason` (P4-2)**: rodzaj (`'io'|'parse'`) i diagnoza bieżącej
      awarii - TEN SAM reżim dowodowy co marker i dlatego też WYMAGANE: udany odczyt podaje `None`/`None`
      („potwierdzam, że nie ma czego tłumaczyć"), degeneracja podaje rodzaj i tekst z rekordu. Gasną
      RAZEM z markerem (CHECK 0019 odbija powód bez markera), a ich przejście idzie do payloadu
      `location.refreshed` tak samo jak przejście markera. Nazwy z prefiksem, bo `kind` niżej to
      rodzaj KLATKI z nowego zeznania - inna oś.
    - **`present` (P5, D-V-6)**: obecność kopii — TEN SAM reżim dowodowy co `unreadable_since`.
      Parametr WYMAGANY: `1` znaczy „POTWIERDZAM, że plik pod tą ścieżką ISTNIEJE" (wołający właśnie
      go zestatował/przeczytał), nie „pewnie jest". Zmartwychwstanie (0→1) jest zmianą faktu, więc
      idzie do payloadu `location.refreshed` — pass obecności nie musi go osobno wykrywać.
      Domyślnej wartości NIE dodawać: przesłanka „każdy wołający właśnie czytał plik" jest prawdziwa
      przez przypadek, nie przez kontrakt (`import_fitsmirror` karmi `ingest_record` z cache'u dawcy).
      Zdejmowanie obecności (1→0) NIE należy tu — to `mark_location_vanished` (dowód nieobecności).
    - **`copy_facts` (0021)**: liczba/role obrazów i zeznanie nagłówka TEJ kopii (klucze `COPY_FACTS`)
      - wołający, który przeczytał plik, podaje je zawsze (także same NULL-e przy nagłówku
      nieczytelnym). `None` znaczy „faktów kopii NIE czytałem" i zostawia je, jakie są - to NIE jest
      cichy wektor zwietrzenia, bo kotwica `hdr_hash == header_hash` (CHECK 0021) odbija zmianę
      odcisku nagłówka bez odświeżenia faktów IntegrityError-em.
    - **`inplace_gen`** (astra, 2026-09-27): generacja dziennika zapisu w miejscu, którą skan
      zapamiętał PRZED bramką izolacji (`inplace_generation`). Operacja tej lokacji o większym `id`
      → `StaleScanRecord` w TEJ SAMEJ transakcji co zapis, zero zapisu: odczyt mógł trafić w zapis
      w toku albo go wyprzedzić, a spóźniony zapis faktów przywróciłby stan, który pisarz zmienia.
      `None` = wołający nie jest skanem (re-sync pisarza, import) - bez sprawdzenia.

    `hot_fields` = dict kolumn `header` (jak `extract_header`); `camera_id`/`kind` = pochodne
    POLICZONE przez wołającego z nowego dictu (emergencja kamery = osobny, idempotentny
    `upsert_camera` przed wołaniem). Zwraca dict
    `{"facts": bool, "header": bool, "rederived": bool}`. Wymiana `cards` (DELETE+INSERT) to
    jedyna sankcjonowana kasacja: cards są LUSTREM bieżącego zeznania, nie historią —
    historia mieszka w `event`."""
    after = {"mtime": mtime, "file_sha1": file_sha1, "header_hash": header_hash,
             "hdu_index": hdu_index, "compressed": compressed, "size_bytes": size_bytes,
             "unreadable_since": unreadable_since, "unreadable_kind": unreadable_kind,
             "unreadable_reason": unreadable_reason, "present": present}
    cf = None if copy_facts is None else _copy_facts_checked(copy_facts)
    result = {"facts": False, "header": False, "rederived": False}
    with _immediate(con):
        row = con.execute(
            "SELECT mtime, file_sha1, header_hash, hdu_index, compressed, size_bytes, "
            "unreadable_since, unreadable_kind, unreadable_reason, present, "
            "image_count, image_roles, hdr_filter, hdr_imagetyp, hdr_object, hdr_telescop, "
            "hdr_instrume, hdr_exptime, hdr_xbinning, hdr_date_obs, hdr_hash "
            "FROM location WHERE id = ?", (location_id,)).fetchone()
        if row is None:
            raise ValueError(f"location:{location_id} nie istnieje")
        _refuse_if_newer_inplace(con, location_id, inplace_gen)
        # Faktów kopii nieczytanych (`None`) nie ruszamy: zostają wartościami z wiersza.
        after.update(cf if cf is not None else {k: row[k] for k in COPY_FACTS})
        changed = {k: {"before": row[k], "after": after[k]}
                   for k in _LOCATION_FACTS if row[k] != after[k]}
        if not changed:
            return result
        con.execute(
            "UPDATE location SET mtime = ?, file_sha1 = ?, header_hash = ?, hdu_index = ?, "
            "compressed = ?, size_bytes = ?, unreadable_since = ?, unreadable_kind = ?, "
            "unreadable_reason = ?, present = ?, last_verified_at = ?, "
            "image_count = ?, image_roles = ?, hdr_filter = ?, hdr_imagetyp = ?, hdr_object = ?, "
            "hdr_telescop = ?, hdr_instrume = ?, hdr_exptime = ?, hdr_xbinning = ?, "
            "hdr_date_obs = ?, hdr_hash = ? WHERE id = ?",
            (mtime, file_sha1, header_hash, hdu_index, compressed, size_bytes, unreadable_since,
             unreadable_kind, unreadable_reason, present, now,
             *(after[k] for k in COPY_FACTS), location_id))
        emit_event(con, actor=actor, verb="location.refreshed",
                   target=f"location:{location_id}", now=now, payload=changed)
        result["facts"] = True

        if "header_hash" not in changed or raw_json is None:
            return result
        result["header"] = True
        result["rederived"] = _rewrite_testimony(
            con, frame_id=frame_id, raw_json=raw_json, cards=cards, hot_fields=hot_fields,
            camera_id=camera_id, kind=kind, now=now, actor=actor, verb="header.refreshed",
            payload={"header_hash_before": row["header_hash"], "header_hash_after": header_hash})
    return result


# Pola gorące `header` w kolejności literału niżej - JEDNA lista dla przepisania zeznania i dla
# payloadu przejęcia (`adopt_testimony` opisuje, które z nich zmieniło wartość).
_HEADER_HOT = ("date_obs", "exptime", "filter_raw", "instrume", "telescop", "focallen",
               "focratio_raw", "xpixsz", "ypixsz", "gain", "offset_adu", "ccd_temp", "usblimit",
               "xbinning", "ybinning", "bayerpat", "ra_deg", "dec_deg", "object_raw")


def _rewrite_testimony(con, *, frame_id, raw_json, cards, hot_fields, camera_id, kind, now,
                       actor, verb, payload):
    """RDZEŃ PRZEPISANIA ZEZNANIA klatki - wspólny dla odświeżenia po zmianie odcisku nagłówka
    (`refresh_location`, `header.refreshed`) i dla przejęcia zeznania ocalałej kopii
    (`adopt_testimony`, `header.adopted`). Dwie kopie tego ciągu rozjechałyby się przy pierwszej
    nowej kolumnie `header`: jedna droga pisałaby ją, druga zostawiała stęchłą.

    Wołane WEWNĄTRZ transakcji wołającego. Pełny re-record `header` (raw_json + WSZYSTKIE pola
    gorące; frame bez zeznania → INSERT), WYMIANA `cards` (lustro bieżącego zeznania, nie historia),
    event `verb` z `payload`, a po nim przeliczenie pochodnych frame'a (`camera_id`/`kind` →
    `frame.rederived`) - kolejność zdarzeń jest ta sama, co przed wydzieleniem. Zwraca bool:
    czy pochodne się zmieniły."""
    hot = dict(hot_fields or {})
    g = hot.get
    cur = con.execute(
        "UPDATE header SET raw_json = ?, date_obs = ?, exptime = ?, filter_raw = ?, "
        "instrume = ?, telescop = ?, focallen = ?, focratio_raw = ?, xpixsz = ?, ypixsz = ?, "
        "gain = ?, offset_adu = ?, ccd_temp = ?, usblimit = ?, xbinning = ?, ybinning = ?, "
        "bayerpat = ?, ra_deg = ?, dec_deg = ?, object_raw = ? WHERE frame_id = ?",
        (raw_json, *(g(k) for k in _HEADER_HOT), frame_id))
    if cur.rowcount == 0:                         # frame bez zeznania (brzeg) → INSERT
        con.execute(
            "INSERT INTO header(frame_id, raw_json, date_obs, exptime, filter_raw, "
            "instrume, telescop, focallen, focratio_raw, xpixsz, ypixsz, gain, offset_adu, "
            "ccd_temp, usblimit, xbinning, ybinning, bayerpat, ra_deg, dec_deg, object_raw) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (frame_id, raw_json, *(g(k) for k in _HEADER_HOT)))
    con.execute("DELETE FROM cards WHERE frame_id = ?", (frame_id,))
    if cards:
        _insert_cards(con, frame_id, cards)
    emit_event(con, actor=actor, verb=verb, target=f"frame:{frame_id}", now=now, payload=payload)

    fr = con.execute("SELECT camera_id, kind FROM frame WHERE id = ?", (frame_id,)).fetchone()
    if (fr["camera_id"], fr["kind"]) == (camera_id, kind):
        return False
    con.execute("UPDATE frame SET camera_id = ?, kind = ? WHERE id = ?",
                (camera_id, kind, frame_id))
    emit_event(con, actor=actor, verb="frame.rederived", target=f"frame:{frame_id}", now=now,
               payload={"before": {"camera_id": fr["camera_id"], "kind": fr["kind"]},
                        "after": {"camera_id": camera_id, "kind": kind}})
    return True


def adopt_testimony(con, *, location_id, sha1_data, header_hash, raw_json, cards, hot_fields,
                    camera_id, kind, now, actor, inplace_gen=None):
    """PRZEJĘCIE ZEZNANIA klatki przez WSKAZANĄ kopię: `header` + `cards` + pochodne frame'a
    (`camera_id`/`kind`) z nagłówka pliku tej kopii, przeczytanego przed chwilą przez wołającego.

    DLACZEGO OSOBNA KLINGA, A NIE `refresh_location`: tamta przepisuje zeznanie wyłącznie przy
    zmianie odcisku nagłówka TEJ lokacji (reguła N-lokacji: pierwsza kopia, potem ta, której nagłówek
    zmienił się ostatnio). Gdy znika kopia, z której zeznanie pochodzi, ocalała kopia ma odcisk bez
    zmian i skan ją pomija - `header` niósłby do końca świata zeznanie pliku, którego nie ma.
    Rdzeń przepisania jest wspólny (`_rewrite_testimony`), różni się tylko przesłanka i ślad.

    KTÓRA KOPIA - ROZSTRZYGA WOŁAJĄCY, NIE KLINGA. Wejście to `location_id` wskazanej kopii i jej
    odczytany rekord; klinga nie zna reguły wyboru. Dziś woła ją etap Dostawy dla klatek o jednej
    obecnej kopii (`scan.adopt_orphan_testimony`), jutro gest człowieka „ta kopia prowadzi" (AR-4)
    przy kopiach, które mówią różnie - bez zmiany tej funkcji.

    STRAŻNICY (pod `BEGIN IMMEDIATE`, TOCTOU wobec równoległego skanu):
      * EXPECT: `sha1_data` rekordu (tożsamość liczona regułą skanu, z degeneracją) MUSI równać się
        tożsamości klatki tej lokacji - inaczej wołający przeczytał plik cudzej klatki, a przejęcie
        byłoby kłamstwem. Błąd wołania, nie stan danych → `ValueError`;
      * kopia OBECNA (`present = 1`) i odcisk nagłówka rekordu == `location.header_hash`: plik niesie
        dokładnie ten nagłówek, który baza zna. Inny odcisk = kopia zmieniła się od skanu i należy
        do skanu (odświeży fakty kopii razem z zeznaniem); nieobecna = nie ma czego przejmować.
        Oba → `'drift'`, ZERO zapisu.
    Zeznanie już identyczne (`raw_json` i pola gorące bez zmian) → `'unchanged'`, ZERO zapisu i ZERO
    eventu (idempotencja: drugi przebieg nie dopisuje dziennika).

    Ślad: `event(header.adopted)` na `frame:` z payloadem „skąd → dokąd": `location_id`, `path`
    i odcisk przejmującej kopii oraz `{pole: {before, after}}` pól gorących, które zmieniły wartość.
    `actor` idzie do każdego eventu przejęcia (etap i gest ręki mają się w dzienniku odróżniać).

    `inplace_gen` (astra, 2026-09-27) - generacja dziennika zapisu w miejscu z odczytu wołającego
    (kontrakt jak w `refresh_location`): operacja tej lokacji o większym `id` → `StaleScanRecord`
    w tej transakcji, zero zapisu. Kotwica odcisku sama tego nie łapie - zapis w miejscu przed
    re-synciem zostawia w bazie stary odcisk, a odczyt sprzed zapisu niesie ten sam.

    ZWRACA `'adopted'` | `'unchanged'` | `'drift'`."""
    hot = dict(hot_fields or {})
    with _immediate(con):
        loc = con.execute(
            "SELECT l.frame_id, l.path, l.present, l.header_hash, f.sha1_data "
            "FROM location l JOIN frame f ON f.id = l.frame_id WHERE l.id = ?",
            (location_id,)).fetchone()
        if loc is None:
            raise ValueError(f"location:{location_id} nie istnieje")
        _refuse_if_newer_inplace(con, location_id, inplace_gen)
        if loc["sha1_data"] != sha1_data:
            raise ValueError(f"location:{location_id}: tożsamość rekordu {sha1_data!r} != "
                             f"tożsamość klatki {loc['sha1_data']!r} - to nie jest ta klatka")
        if not loc["present"] or header_hash is None or loc["header_hash"] != header_hash:
            return "drift"
        frame_id = loc["frame_id"]
        before = con.execute(
            "SELECT raw_json, date_obs, exptime, filter_raw, instrume, telescop, focallen, "
            "focratio_raw, xpixsz, ypixsz, gain, offset_adu, ccd_temp, usblimit, xbinning, "
            "ybinning, bayerpat, ra_deg, dec_deg, object_raw FROM header WHERE frame_id = ?",
            (frame_id,)).fetchone()
        changed = {k: {"before": None if before is None else before[k], "after": hot.get(k)}
                   for k in _HEADER_HOT
                   if (None if before is None else before[k]) != hot.get(k)}
        if before is not None and before["raw_json"] == raw_json and not changed:
            return "unchanged"
        _rewrite_testimony(
            con, frame_id=frame_id, raw_json=raw_json, cards=cards, hot_fields=hot,
            camera_id=camera_id, kind=kind, now=now, actor=actor, verb="header.adopted",
            payload={"location_id": location_id, "path": loc["path"], "header_hash": header_hash,
                     "changed": changed})
    return "adopted"


def record_copy_facts(con, *, location_id, copy_facts, now, actor="backfill:copies",
                      inplace_gen=None):
    """UZUPEŁNIENIE faktów kopii z jej nagłówka (0021) dla wiersza sprzed migracji - droga
    `scan.backfill_copy_facts`, która czyta SAM nagłówek pliku, bez haszowania całości (550 plików
    XISF to 108,9 GB treści, a nagłówki czytają się w sekundy).

    DWIE KOTWICE W JEDNYM WARUNKU (CAS pod `BEGIN IMMEDIATE`): zapis zachodzi wyłącznie, gdy
      * odcisk przeczytanego nagłówka (`copy_facts['hdr_hash']`) jest równy `header_hash` wiersza -
        plik niesie DOKŁADNIE ten nagłówek, który baza zna. Inny odcisk znaczy, że kopia zmieniła się
        na dysku od ostatniego skanu; wtedy fakty należą do skanu, który odświeży też `header`
        klatki, `cards` i pochodne - uzupełnienie nie ma prawa go wyprzedzić częściową prawdą;
      * `hdr_hash IS NULL` - faktów jeszcze nie ma. Uzupełnienie nie nadpisuje tego, co zebrał skan.
    Ta sama para chroni przed wyścigiem z równoległym skanem (WAL - GUI i CLI naraz).

    Ślad: `location.refreshed` z `{pole: {before, after}}` - ten sam kształt, którym `refresh_location`
    opisuje każdą inną zmianę faktów kopii, a `actor` odróżnia drogę w dzienniku.

    ZWRACA bool: `True` = zapisano; `False` = odmowa kotwicy (odcisk inny albo fakty już są) - wtedy
    ZERO UPDATE i ZERO eventu.

    `inplace_gen` (astra, 2026-09-27) - generacja dziennika zapisu w miejscu zapamiętana przez
    sterownik PRZED bramką izolacji (kontrakt jak w `refresh_location`): operacja tej lokacji o
    większym `id` → `StaleScanRecord` w tej transakcji, zero zapisu. Kotwica odcisku sama tego nie
    łapie: pisarz, którego re-sync jeszcze nie przeszedł, zostawia w bazie stary odcisk, a odczyt
    sprzed zapisu niesie ten sam."""
    cf = _copy_facts_checked(copy_facts)
    if cf["hdr_hash"] is None:
        raise ValueError("uzupełnienie faktów kopii bez odcisku nagłówka - nie ma czego kotwiczyć")
    with _immediate(con):
        row = con.execute(
            "SELECT header_hash, image_count, image_roles, hdr_filter, hdr_imagetyp, hdr_object, "
            "hdr_telescop, hdr_instrume, hdr_exptime, hdr_xbinning, hdr_date_obs, hdr_hash "
            "FROM location WHERE id = ?", (location_id,)).fetchone()
        if row is None:
            raise ValueError(f"location:{location_id} nie istnieje")
        _refuse_if_newer_inplace(con, location_id, inplace_gen)
        if row["hdr_hash"] is not None or row["header_hash"] != cf["hdr_hash"]:
            return False
        changed = {k: {"before": row[k], "after": cf[k]} for k in COPY_FACTS if row[k] != cf[k]}
        con.execute(
            "UPDATE location SET image_count = ?, image_roles = ?, hdr_filter = ?, "
            "hdr_imagetyp = ?, hdr_object = ?, hdr_telescop = ?, hdr_instrume = ?, "
            "hdr_exptime = ?, hdr_xbinning = ?, hdr_date_obs = ?, hdr_hash = ? "
            "WHERE id = ? AND hdr_hash IS NULL AND header_hash = ?",
            (*(cf[k] for k in COPY_FACTS), location_id, cf["hdr_hash"]))
        emit_event(con, actor=actor, verb="location.refreshed",
                   target=f"location:{location_id}", now=now, payload=changed)
    return True


# Prefiks powodu w dzienniku przy oznaczeniu kopii (#13) - JEDEN właściciel frazy. Od P4-2 żyje
# WYŁĄCZNIE w `event.reason`: kolumna `location.unreadable_reason` niesie samą diagnozę („Typ: opis"),
# bo powierzchnia i tak nazywa się „Kopie nieczytelne", a prefiks w stanie trzeba by zdejmować przy
# każdym odczycie.
UNREADABLE_REASON_PREFIX = "kopia nieczytelna: "


def refresh_location_unreadable(con, *, location_id, sha1_data, path, mtime, reason, kind,
                                now, actor="scan", inplace_gen=None):
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

    RODZAJ I POWÓD (P4-2): `kind` (`'io'` - system nie oddał bajtów, `'parse'` - bajty przyszły, parser
    nagłówka odmówił, `'db'` - błąd bazy po naszej stronie) i `reason` („Typ: opis") idą do kolumn
    `unreadable_kind`/`unreadable_reason`, żeby powierzchnia umiała powiedzieć, KTÓRA to sytuacja,
    zamiast oskarżać plik. Klasyfikuje wołający, w miejscu, gdzie żyje obiekt wyjątku
    (`scan.unreadable_kind_of`) - tu nie ma czego zgadywać z tekstu. `kind=None` jest legalne: rodzaj
    nieznany - wiersz sprzed 0019 ALBO wyjątek bez kodu systemu, którego nie dało się rozstrzygnąć.
    ASYMETRIA CZASU, świadoma: marker trzyma PIERWSZĄ awarię, a rodzaj i powód opisują OSTATNIĄ próbę.
    Marker znaczy „kopia JEST nieczytelna" - bieżący fakt - więc przyczyna ma być bieżąca: przyczyna
    sprzed tygodnia przy dzisiejszym timeoucie SMB odesłałaby usera do złego winnego.

    ZMIANA SAMEJ DIAGNOZY przy stojącym alarmie (ten sam mtime, marker jest, kopia obecna) to zmiana
    FAKTU, więc UPDATE - ale bez drugiego `frame.review`: dziennik już alarmuje o tej kopii, a review
    co zmianę tekstu wyjątku byłoby spamem, którego QUIET zakazuje. Ślad idzie jako
    `location.refreshed` `{unreadable_kind: {before, after}, unreadable_reason: {...}}` (tylko pola
    zmienione) - ten sam kształt, którym `refresh_location` opisuje fakty kopii. Każdy inny zapis
    (pierwsze oznaczenie, nowy mtime, powrót po zniknięciu) podnosi alarm `frame.review`, który
    niesie diagnozę w `reason` (z prefiksem) i rodzaj w payloadzie - dziennik zostaje kompletny także
    wtedy, gdy stan przestawi się kolejną próbą.

    ZWRACA bool: czy podniesiono ALARM (nowy `frame.review`) - to jedyne, co wołający liczy
    (`summary.frame_review`). Alarm zachodzi, gdy `mtime` się różni LUB marker jest NULL (pierwsze
    oznaczenie) LUB kopia była oznaczona jako zniknięta (`present=0` → powrót). `False` znaczy albo
    cichy no-op (powtórna awaria z tą samą diagnozą - BEZ eventu, stan już alarmuje), albo zapis
    samej diagnozy ze śladem `location.refreshed` - licznik review nie ma wtedy rosnąć.

    `inplace_gen` - generacja dziennika zapisu w miejscu z odczytu skanu (kontrakt jak
    w `refresh_location`): plik czytany w trakcie zapisu w miejscu nie dostaje markera."""
    with _immediate(con):
        row = con.execute(
            "SELECT mtime, unreadable_since, unreadable_kind, unreadable_reason, present "
            "FROM location WHERE id = ?", (location_id,)).fetchone()
        if row is None:
            raise ValueError(f"location:{location_id} nie istnieje")
        _refuse_if_newer_inplace(con, location_id, inplace_gen)
        alarm_stoi = (row["mtime"] == mtime and row["unreadable_since"] is not None
                      and row["present"])
        diagnoza = {k: {"before": row[k], "after": v}
                    for k, v in (("unreadable_kind", kind), ("unreadable_reason", reason))
                    if row[k] != v}
        if alarm_stoi and not diagnoza:
            return False                              # powtórna awaria bez zmiany — cichy no-op (QUIET)
        con.execute(
            "UPDATE location SET mtime = ?, last_verified_at = ?, present = 1, "
            "unreadable_since = COALESCE(unreadable_since, ?), unreadable_kind = ?, "
            "unreadable_reason = ? WHERE id = ?",
            (mtime, now, now, kind, reason, location_id))
        if alarm_stoi:                                # sama diagnoza - ślad faktu, nie drugi alarm
            emit_event(con, actor=actor, verb="location.refreshed",
                       target=f"location:{location_id}", now=now, payload=diagnoza)
            return False
        emit_event(con, actor=actor, verb="frame.review", target=f"sha1:{sha1_data}", now=now,
                   reason=f"{UNREADABLE_REASON_PREFIX}{reason}",
                   payload={"path": path, "unreadable_kind": kind})
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
    Od P4-2 inwariant obejmuje rodzaj i powód: `present = 0 ⇒ unreadable_kind IS NULL AND
    unreadable_reason IS NULL` - gasną tym samym UPDATE-em co marker (CHECK 0019 i tak odbiłby
    zgaszenie samego markera), a stare wartości idą do payloadu obok `unreadable_since_before`.

    KOTWICA ANTY-STALE (`expected_path`): pass planuje na migawce, a między planem a zapisem GUI może
    zrobić rename (`relocate_location` zmienia `path` TEGO wiersza) — wtedy ścieżka w bazie wskazuje
    na ISTNIEJĄCY plik i oznaczenie byłoby kłamstwem. Rozjazd → `False` (wołający liczy `drifted`),
    ZERO zapisu. Guard+UPDATE w `_immediate` (TOCTOU wobec równoległego writera).

    ZWRACA bool: `True` = oznaczono; `False` = dryf ścieżki ALBO kopia już nieobecna (idempotencja
    powtórnego przebiegu — bez UPDATE i bez eventu, QUIET)."""
    with _immediate(con):
        row = con.execute(
            "SELECT volume, path, present, unreadable_since, unreadable_kind, unreadable_reason "
            "FROM location WHERE id = ?", (location_id,)).fetchone()
        if row is None:
            raise ValueError(f"location:{location_id} nie istnieje")
        if row["path"] != expected_path:
            return False                              # dryf (rename między planem a zapisem)
        if not row["present"]:
            return False                              # już zniknięta — idempotencja, bez eventu
        con.execute(
            "UPDATE location SET present = 0, unreadable_since = NULL, unreadable_kind = NULL, "
            "unreadable_reason = NULL, last_verified_at = ? WHERE id = ?", (now, location_id))
        emit_event(
            con, actor=actor, verb="location.vanished", target=f"location:{location_id}", now=now,
            payload={"path": row["path"], "volume": row["volume"], "root": root, "run_id": run_id,
                     "unreadable_since_before": row["unreadable_since"],
                     "unreadable_kind_before": row["unreadable_kind"],
                     "unreadable_reason_before": row["unreadable_reason"], "forced": forced})
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
    domykają się wtedy identycznie.

    PRZEGŁOSOWANIE POTWIERDZENIA ZE ŚCIEŻKI (E5-1) NIESIE ŚLAD W TEJ SAMEJ TRANSAKCJI. Gdy klatka
    schodzi ze źródła SŁABEGO (`WEAK_OBJECT_SOURCES`) na źródło automatu, `object.unassigned`
    dostaje `reason` i dwa klucze stanu PO (`next_object_id`, `next_object_source`). To jest
    jedyny dowód przejścia, który czyta spis faktów ręki (`audit.path_to_header_since`):
    zapisany w CHWILI przepięcia, atomowo z nim - przerwany przebieg nie gubi śladu klatek już
    przepiętych, a późniejsze przepięcie nagłówek→nagłówek ani odpięcie słownikowe
    (`retire_alias_and_unassign`) tych kluczy nie mają, więc nie udają przejścia. Osobnego verbu
    nie ma: para już jest, a trzecie zdarzenie per klatka byłoby drugim zapisem tego samego faktu."""
    row = con.execute(
        "SELECT object_id, object_source FROM frame WHERE id = ?", (frame_id,)).fetchone()
    if row is not None and row[0] == object_id and row[1] == object_source:
        return False

    with con:
        con.execute("UPDATE frame SET object_id = ?, object_source = ? WHERE id = ?",
                    (object_id, object_source, frame_id))
        if row is not None and row[0] is not None:   # re-przypisanie: ślad zostaje (append-only)
            przed = {"object_id": row[0], "object_source": row[1]}
            powod = None
            if row[1] in WEAK_OBJECT_SOURCES and object_source not in WEAK_OBJECT_SOURCES:
                przed.update(next_object_id=object_id, next_object_source=object_source)
                powod = "nagłówek przegłosował potwierdzenie ze ścieżki (header-primary)"
            emit_event(con, actor=actor, verb="object.unassigned", target=f"frame:{frame_id}",
                       now=now, payload=przed, reason=powod)
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
    skipped_no_memory: int = 0 # NAGROBEK BEZ PAMIĘCI (baza-dawca sprzed 0017) - osobno od
                               # `skipped_nothing` (FC-6), bo to inna przyczyna o innej recepcie:
                               # „nie było czego przywrócić" mówi, że klatka nagrobkiem nie jest,
                               # a ten licznik - że jest, tylko nie pamięta, co ręka zdjęła, więc
                               # ręką nic tu się nie naprawi. Liczy go wyłącznie przywracanie
                               # (`queries.restore_targets`); klingi zostawiają go na zerze
    skipped_drift: int = 0     # stan inny niż oczekiwany w chwili zapisu (TOCTOU)
    skipped_failed: int = 0    # NIE ZAPISANO, BO KLINGA ODMÓWIŁA (`ValueError`: konflikt aliasu,
                               # klatka spoza bazy) - osobno od `skipped_drift`, bo odmowa nie
                               # znaczy, że stan się zmienił: przy konflikcie aliasu nic się nie
                               # ruszyło. Liczy go wyłącznie WOŁAJĄCY gestu wielotransakcyjnego
                               # (przywracanie w Zbiorach, zatwierdzanie ze ścieżki): transakcja,
                               # która padła, i te, do których pętla już nie doszła; klingi
                               # zostawiają go na zerze
    stacks: int = 0            # …z ZAPISANYCH: ile było gotowych obrazów. NIE jest pominięciem
                               # (D-OW-7: stos jest w zasięgu OBU gestów) i dlatego stoi POZA sumą
                               # `skipped` — to informacja o tym, co gest ruszył, a nie o tym, czego
                               # nie ruszył. Osobno, bo gotowy obraz jest jedyną klatką, przy której
                               # zapis osi może dotknąć rodowodu
    canons: tuple = ()         # KANONY, których gest DOTKNĄŁ — do zdania „…: NGC 7023". Krotka,
                               # bo dataclass jest `frozen` (lista byłaby mutowalnym stanem we
                               # wnętrzu niemutowalnego wyniku). Zdanie nadania zna kanon od
                               # wołającego (sam go wybrał); zdanie COFNIĘCIA nie ma go skąd wziąć
                               # inaczej niż od klingi — i przez to milczało o tym, co zdjęło

    def __add__(self, inny):
        """Suma dwóch gestów — JEDEN właściciel składania, tak jak `skipped_breakdown` jest jedynym
        właścicielem rozbicia.

        Potrzebna, odkąd jeden gest człowieka bywa N transakcjami: przywracanie idzie klingą per
        GRUPA (obiekt × zaznaczenie), a zdanie po geście jest jedno. Druga siedziba tej sumy
        (`ConfirmPathObjectsDialog._on_confirm`) do R-S2b-13 sumowała ręcznie `assigned`
        i `skipped`, więc GUBIŁA rozbicie per fakt: user dostawał „przypisano 30 z 40" bez zdania,
        dlaczego dziesięć zostało - dziś składa `+=` jak przywracanie. Trzecia siedziba powtórzyłaby
        ten błąd, a czwarta powtórzyłaby go po raz kolejny - dlatego składanie ma dom w klasie,
        nie u wołających.

        Kanony sklejają się BEZ POWTÓRZEŃ i w porządku pierwszego wystąpienia: to nazwy do zdania,
        a nie zbiór do liczenia - powtórzony kanon w komunikacie wygląda jak dwa różne obiekty.
        ⛔ PORZĄDEK DO ZDANIA ROZSTRZYGA `gui.grid._lista_kanonow`, nie ta metoda: tutaj zostaje
        wyłącznie deduplikacja. Dwie klingi tej samej pary gestów zbierają nazwy inaczej (ta -
        w kolejności klatek, `restore_targets` - alfabetycznie), więc obcięcie „trzy plus reszta"
        pokazywało rozłączne trójki jednego zbioru; naprawa siedzi w warstwie zdania i sortowanie
        tutaj byłoby jej drugą siedzibą (FC-7)."""
        if not isinstance(inny, ObjectGesture):
            return NotImplemented
        kanony = list(self.canons) + [c for c in inny.canons if c not in self.canons]
        return ObjectGesture(
            assigned=self.assigned + inny.assigned,
            skipped_kind=self.skipped_kind + inny.skipped_kind,
            skipped_source=self.skipped_source + inny.skipped_source,
            skipped_nothing=self.skipped_nothing + inny.skipped_nothing,
            skipped_no_memory=self.skipped_no_memory + inny.skipped_no_memory,
            skipped_drift=self.skipped_drift + inny.skipped_drift,
            skipped_failed=self.skipped_failed + inny.skipped_failed,
            stacks=self.stacks + inny.stacks,
            canons=tuple(kanony))

    @property
    def skipped(self):
        """Suma pominięć — do zdania „przypisano N z M", gdzie rozbicie idzie osobno.

        Właścicielem listy członów jest TA suma i rozbicie w GUI musi po niej iterować, a nie
        powtarzać wyliczankę: czwarty człon (`skipped_nothing`) dołożony w S3 wszedłby inaczej
        do „z M", a nie do rozbicia — czyli zniknąłby dokładnie tam, gdzie ma tłumaczyć."""
        return (self.skipped_kind + self.skipped_source + self.skipped_nothing
                + self.skipped_no_memory + self.skipped_drift + self.skipped_failed)

    @property
    def skipped_breakdown(self):
        """Rozbicie pominięć jako [(sufiks klucza i18n, n)] — JEDEN właściciel kolejności i składu.

        GUI powtarzało tę listę literałem, więc każdy nowy człon wpadał do sumy, a z ekranu znikał."""
        return [("kind", self.skipped_kind), ("source", self.skipped_source),
                ("nothing", self.skipped_nothing), ("no_memory", self.skipped_no_memory),
                ("drift", self.skipped_drift), ("failed", self.skipped_failed)]


def user_assign_object(con, *, alias_norm, canon, catalog, kind, frame_ids, now, uid="local",
                       object_source="user", expected_object_id=None, overwrite_weak=False,
                       expected_source=None, expected_cleared_id=None):
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
    Przy `object_source='path'` dryfem jest też klatka, której PRZESŁANKA propozycji przestała
    zachodzić (nagłówek zaczął zeznawać, brak wiersza `header`, wycofanie, zastąpienie).

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
      te 30 klatek z `NGC6960`" nadpisałby też klatkę, która właśnie stała się czymś innym.
    * `expected_source` to RODZEŃSTWO powyższego dla klatek BEZ obiektu — i istnieje, bo tamten
      przy nagrobku jest martwy Z DEFINICJI: `object_id IS NULL`, więc jego gałąź się nie wykonuje.
      Wołający, który przywraca cofnięte przypisanie, żąda `expected_source='user_cleared'`
      i wtedy klatka, która przestała być nagrobkiem między odczytem a zapisem, liczy się jako
      dryf. Bez tego jedyną obroną byłby filtr w read-modelu — czyli POZA transakcją, obrona
      słabsza niż u obu sąsiednich gestów tej samej osi.
    * `expected_cleared_id` domyka tamten do PARY (bramka pakietu 0810): `expected_source` pyta
      o ETYKIETĘ stanu („czy to nadal nagrobek"), a ten o jego TREŚĆ („czy nagrobek nadal odrzuca
      TEN obiekt"). Sama etykieta przeżywa sekwencję `cofnij X → przywróć → nadaj Y → cofnij Y`,
      więc bez tego członu przywracanie ze stęchłego odczytu zamalowałoby Y starszym X — i to
      po cichu, bo obie strony wyglądają na ekranie identycznie. Dziś populacja jest zerowa
      (handler jest synchroniczny, a `busy.repaint` doręcza zdarzenia z `ExcludeUserInputEvents`,
      więc drugiego pisarza w obrębie procesu nie ma), ale guard kosztuje jedno porównanie
      w kolumnie, którą ta pętla i tak już czyta."""
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
                "SELECT kind, object_id, object_source, object_cleared_id FROM frame WHERE id = ?",
                (frame_id,)).fetchone()
            if fr is None:
                raise ValueError(f"frame:{frame_id} nie istnieje")
            if fr["kind"] not in LIGHT_KINDS:
                kind_skip += 1                      # kalibracja: obiektu nie ma z DEFINICJI
                continue
            if object_source == "path":
                # POTWIERDZENIE PROPOZYCJI ŚCIEŻKI PYTA PONOWNIE O JEJ PRZESŁANKĘ, w tej transakcji.
                # Propozycja (`resolver.path_proposals`) powstała z „nagłówek milczy, klatka żywa";
                # między oknem a zapisem re-skan mógł wczytać kartę `OBJECT` (writeback z drugiej
                # powierzchni), a wycofanie/zastąpienie zdjąć klatkę z roboty. Zapis nazwy z FOLDERU
                # nad zeznaniem PLIKU odwracałby header-primary, więc taka klatka jest DRYFEM - tym
                # samym kanałem co zajęcie między oknem a zapisem. Nagrobek łapie gałąź niżej
                # (`source_skip`), a `object_id` - gałąź dryfu; tu tylko to, czego klinga nie czytała.
                # Zakres = WYŁĄCZNIE źródło `path`: ręka (`user`) wolno nazwać klatkę mimo zeznania.
                przeslanka = con.execute(
                    "SELECT h.frame_id AS hid, h.object_raw AS raw, f.retired_at AS ret, "
                    "       f.superseded_by AS sup "
                    "FROM frame f LEFT JOIN header h ON h.frame_id = f.id WHERE f.id = ?",
                    (frame_id,)).fetchone()
                if (przeslanka["hid"] is None or przeslanka["raw"] is not None
                        or przeslanka["ret"] is not None or przeslanka["sup"] is not None):
                    drift += 1
                    continue
            if expected_source is not None and fr["object_source"] != expected_source:
                drift += 1                          # nie ten stan, co widział read-model wołającego
                continue
            if (expected_cleared_id is not None
                    and fr["object_cleared_id"] != expected_cleared_id):
                # GUARD PYTA O TREŚĆ NAGROBKA, NIE O JEGO ETYKIETĘ (bramka pakietu 0810, zarzut B#1).
                # `expected_source='user_cleared'` sprawdza, że klatka JEST nagrobkiem — ale nie,
                # że jest nagrobkiem TEGO SAMEGO obiektu, którego widział read-model wołającego.
                # Sekwencja `cofnij X → przywróć → nadaj Y → cofnij Y` zostawia tę samą etykietę
                # przy INNYM przedmiocie, więc przywracanie ze stęchłego odczytu zamalowałoby Y
                # starszym X — po cichu, bo obie strony wyglądają identycznie. `expected_object_id`
                # tej dziury nie zatka: przy nagrobku jest martwy z definicji (`object_id IS NULL`).
                drift += 1
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
                # tylko jawne „Przypisz obiekt" (`overwrite_weak`) jest drugim gestem człowieka.
                source_skip += 1
                continue
            # PAMIĘĆ NAGROBKA GAŚNIE W TYM SAMYM `UPDATE` (migracja 0017): klatka przestaje
            # cokolwiek odrzucać, więc wskazanie na odrzucony obiekt traci przedmiot. Nie jest to
            # uprzejmość wobec czytelników — `CHECK` w DDL odbija zapis, który by o tym zapomniał.
            con.execute(
                "UPDATE frame SET object_id = ?, object_source = ?, object_cleared_id = NULL "
                "WHERE id = ?",
                (object_id, object_source, frame_id))
            emit_event(con, actor=actor, verb="object.assigned", target=f"frame:{frame_id}",
                       now=now, payload={"object_id": object_id, "object_source": object_source})
            assigned += 1
            # Licznik gotowych obrazów jest LUSTREM licznika z `clear_object_assignment` (D-OW-7):
            # skoro stos jest w zasięgu obu gestów, oba muszą o nim mówić. Nazwanie stosu PRZEPINA
            # dobór okna jego rodowodu — user ma prawo wiedzieć, że tego właśnie dotknął, zanim
            # zobaczy w Dostawie „pominięto, zapisany dowód mocniejszy".
            stacks += fr["kind"] == "master_light"
    # Kanon wraca w wyniku TYLKO gdy coś zapisano: gest, który nic nie ruszył, nie ma prawa
    # powiedzieć „…: NGC 7023" o klatkach, których nie tknął. Wołający-pojedynczy kanon i tak zna
    # (sam go wybrał), ale wołający-pętla (przywracanie) składa zdanie z sumy N gestów i musi go
    # dostać STĄD, bo grupy różnią się obiektem.
    return ObjectGesture(assigned=assigned, skipped_kind=kind_skip,
                         skipped_source=source_skip, skipped_drift=drift, stacks=stacks,
                         canons=(canon,) if assigned else ())


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
    `OBJECT` do pliku (`clear_object_tombstone`, wołane z `writeback`) albo kolejnym „Przypisz
    obiekt". Trzecią drogą jest PRZYWRÓCENIE (R-S2b-3) — też przez „Przypisz obiekt", bo pisarz
    osi jest jeden; różni się wyłącznie tym, że kanon bierze z pamięci nagrobka, a nie z okna.

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
    umieć pokazać człon „cofnięte ręką" bez zaglądania w payload. Zwraca `ObjectGesture`.

    NAGROBEK PAMIĘTA, CO ZDJĄŁ (migracja 0017, R-S2b-3) — `object_cleared_id` zapisywane w TYM
    SAMYM `UPDATE`, co samo źródło. Bez tego cofnięcie zapisywało FAKT odmowy bez jej PRZEDMIOTU,
    więc masowy gest na 120 klatkach nie miał drogi powrotu: odtworzenie stanu sprzed pomyłki
    kosztowało 6-8 interakcji PLUS pamięć człowieka o tym, co tam stało. Pamięć jest STANEM, nie
    zapisem w dzienniku, bo pytanie „co ta klatka odrzuciła" dotyczy JEJ, a nie historii — a skan
    `event` łamie się przy drugim cofnięciu tej samej klatki i przy nagrobku przeniesionym
    (`transfer_human_facts` emituje ten verb bez `was_object_id`).

    KANONY W WYNIKU: zdanie po geście podaje, co zdjęto — dokładnie jak bliźniacze zdanie nadania
    („Nazwano … : NGC 7023"). Kanon czytamy przez CACHE `object_id → canon`, a nie zapytaniem per
    klatka: pętla robi już jeden `SELECT` na klatkę, a zaznaczenie bywa liczone w tysiącach."""
    actor = f"user:{uid}"
    cleared = kind_skip = source_skip = nothing_skip = stacks = 0
    kanony, cache = [], {}
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
                "UPDATE frame SET object_id = NULL, object_source = 'user_cleared', "
                "object_cleared_id = ? WHERE id = ?",
                (fr["object_id"], frame_id))
            if fr["object_id"] not in cache:
                wiersz = con.execute("SELECT canon FROM object WHERE id = ?",
                                     (fr["object_id"],)).fetchone()
                cache[fr["object_id"]] = wiersz["canon"] if wiersz is not None else None
            kanon = cache[fr["object_id"]]
            if kanon is not None and kanon not in kanony:
                kanony.append(kanon)
            emit_event(con, actor=actor, verb="object.unassigned", target=f"frame:{frame_id}",
                       now=now, payload={"object_id": fr["object_id"],
                                         "object_source": fr["object_source"]})
            emit_event(con, actor=actor, verb="object.cleared", target=f"frame:{frame_id}",
                       now=now, payload={"was_object_id": fr["object_id"],
                                         "was_source": fr["object_source"]})
            cleared += 1
            stacks += fr["kind"] == "master_light"
    return ObjectGesture(assigned=cleared, skipped_kind=kind_skip,
                         skipped_source=source_skip, skipped_nothing=nothing_skip, stacks=stacks,
                         canons=tuple(kanony))


def clear_object_tombstone(con, *, frame_id, now, actor="user:local"):
    """ZGAŚ nagrobek `user_cleared` — jedyna droga wyjścia z werdyktu ręki poza kolejnym gestem.

    Woła to `writeback` po wpisaniu karty `OBJECT` do pliku (S2b): człowiek powiedział „to nie ten
    obiekt", a potem podał właściwy TAM, GDZIE archiwum trzyma prawdę — w nagłówku. Od tej chwili
    zeznanie istnieje i drabina ma prawo je przeczytać, więc nagrobek traci przedmiot.

    Klatka bez nagrobka → `False` bez zapisu i bez eventu (idempotencja jak reszta repo). Verb jest
    WŁASNY (`object.tombstone_cleared`), nie `object.unassigned`: nic się nie odpina, znika sam
    zakaz — a bramka §5.9 liczy odpięcia i para bez odpowiednika rozjechałaby jej bilans.

    PAMIĘĆ GAŚNIE RAZEM Z NAGROBKIEM (0017): znika zakaz, więc znika też wskazanie na to, czego
    zakaz dotyczył. `CHECK` w DDL i tak nie przepuściłby wiersza bez nagrobka, ale z pamięcią."""
    with _immediate(con):
        return _clear_object_tombstone_tx(con, frame_id=frame_id, now=now, actor=actor)


def _clear_object_tombstone_tx(con, *, frame_id, now, actor):
    """Rdzeń `clear_object_tombstone` BEZ własnej transakcji - wspólny dla gestu commitu drogą
    atomową i dla dokończenia zapisu w miejscu (`finish_inplace_op`), które gasi nagrobek w tej
    samej transakcji co faza operacji i statusy stagingu. Jedna klinga, dwa zakresy transakcji."""
    row = con.execute(
        "SELECT object_source FROM frame WHERE id = ?", (frame_id,)).fetchone()
    if row is None or row["object_source"] != "user_cleared":
        return False
    con.execute("UPDATE frame SET object_source = NULL, object_cleared_id = NULL WHERE id = ?",
                (frame_id,))
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


def _insert_pending(con, row):
    """JEDEN literał INSERT stagingu dla obu wołających (kimi Z4) - nowa kolumna `pending_changes`
    zmienia się tu raz. Bez własnej transakcji: obejmuje ją wołający. Zwraca kursor."""
    return con.execute(
        "INSERT INTO pending_changes(run_id, location_id, keyword, idx, op, old_value, "
        "new_value, new_type, new_comment, expected_header_hash, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')", row)


def stage_pending(con, *, run_id, location_id, keyword, idx, op, old_value, new_value,
                  new_type, new_comment, expected_header_hash):
    """Dopisz JEDEN wpis stagingu (status 'pending'). Kluczowany LOCATION (fizyczny plik). Zwraca id
    wiersza. Transient - bez eventu. `expected_header_hash` = kotwica anty-stale (R#7)."""
    with con:
        cur = _insert_pending(con, (run_id, location_id, keyword, idx, op, old_value, new_value,
                                    new_type, new_comment, expected_header_hash))
    return cur.lastrowid


def stage_pending_many(con, *, run_id, previews):
    """Dopisz komplet wpisów stagingu JEDNĄ transakcją - wsad (ujednolicenie karty `OBJECT`, O5:
    ~7,5 tys. wierszy) zamiast tysięcy osobnych commitów `stage_pending`. `previews` = obiekty
    z polami `macro.PendingPreview`. Wszystko albo nic: przerwany staging nie zostawia połowy
    przebiegu. Transient - bez eventu. Zwraca liczbę wpisów."""
    with con:
        for p in previews:
            _insert_pending(con, (run_id, p.location_id, p.keyword, p.idx, p.op, p.old_value,
                                  p.new_value, p.new_type, p.comment, p.expected_header_hash))
    return len(previews)


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


# ============================================================ DZIENNIK ZAPISU W MIEJSCU (0022, O5/Q8)
# `inplace_op` = faza operacji zapisu nagłówka w miejscu i zarazem izolacja lokacji od skanu (opis
# w `0022_inplace_op.sql`). Pisze WYŁĄCZNIE pisarz `writeback` (pod blokadą pliku) przez te funkcje.
# Staging zapisu (backup, commit, faza) jest transient - bez eventu; zdarzeniem jest dopiero gest
# człowieka (zwolnienie izolacji) i mutacja pliku opisana przez re-sync.

# DWA ZBIORY FAZ, każdy z jednym znaczeniem (astra, 2026-09-27 - dawniej jeden zbiór niósł oba):
#   * OTWARTE (`INPLACE_OPEN_PHASES`) = zapis mógł zostawić nagłówek ROZDARTY: odzysk
#     (`writeback.recover_torn`) dozwolony, wiersz Porządków „Plik po przerwanym zapisie", strażnik
#     DDL `uq_inplace_op_otwarta` (jedna otwarta operacja na lokację).
#   * IZOLUJĄCE (`INPLACE_ISOLATING_PHASES`) = otwarte + `written`: plik zapisany i zweryfikowany
#     przez klienta, ale kontrola danych i re-sync bazy jeszcze się nie udały. Lokacja jest wyłączona
#     ze skanu (`scan._isolated`) i z każdej innej mutacji pliku (`writeback`), a zwolnić ją może
#     tylko dokończenie (`writeback.finish_inplace` → `synced`), odzysk albo ręka
#     (`release_inplace_op`). Dawniej izolacja znikała na `written` PRZED re-synciem, więc porażka
#     re-syncu zostawiała lokację skanowi, który mógł ją przepiąć na nową klatkę.
# `recovered` jest końcowa: odzysk zapisuje ją dopiero po udanym re-syncu (do tej chwili operacja
# zostaje `unverified`, a ponowiony odzysk jest bezpieczny - region stary to też stan pośredni),
# a droga powrotu z `written` (`revert_inplace_op`) - po przywróceniu starego regionu, razem ze
# zwolnieniem lokacji do pełnego skanu (kontrola danych nie przeszła, więc re-sync nie ma kotwicy).
INPLACE_OPEN_PHASES = ("writing", "unverified")
INPLACE_ISOLATING_PHASES = (*INPLACE_OPEN_PHASES, "written")
_INPLACE_PHASES = ("writing", "unverified", "written", "synced", "recovered", "released")


class StaleScanRecord(Exception):
    """Rekord skanu jest STARSZY niż operacja zapisu w miejscu tej lokacji: skan zapamiętał
    generację (`inplace_generation`) przed bramką izolacji, a przed zapisem faktów kopii pojawiła się
    operacja o większym `id`. Plik mógł zostać przeczytany w trakcie zapisu albo przed nim - fakty
    z takiego odczytu przywróciłyby stan, który pisarz właśnie zmienia. Skan liczy to jak izolację
    (pominięcie), BEZ markera nieczytelności: plik niczym nie zawinił."""


def inplace_generation(con):
    """GENERACJA dziennika zapisu w miejscu = największe `inplace_op.id` (0, gdy pusto). `id` rośnie
    monotonicznie, więc to zegar bez zegara: operacja zaczęta po odczycie generacji ma `id` większe.
    Skan czyta ją PRZED bramką izolacji i podaje do klingi faktów kopii (`refresh_location`,
    `refresh_location_unreadable`, `rebind_location`, `rebind_location_to_identity`), która w tej
    samej transakcji co zapis odmawia rekordowi starszemu od operacji (`StaleScanRecord`)."""
    return con.execute("SELECT COALESCE(MAX(id), 0) FROM inplace_op").fetchone()[0]


def _refuse_if_newer_inplace(con, location_id, generation):
    """Strażnik generacji wołany WEWNĄTRZ transakcji zapisu: operacja zapisu w miejscu tej lokacji
    o `id` > `generation` → `StaleScanRecord`. `generation=None` = wołający nie jest skanem
    (re-sync pisarza, import) - bez sprawdzenia; własny re-sync pisarza nie odrzuca sam siebie."""
    if generation is None:
        return
    if con.execute("SELECT 1 FROM inplace_op WHERE location_id = ? AND id > ? LIMIT 1",
                   (location_id, generation)).fetchone() is not None:
        raise StaleScanRecord(f"location:{location_id} ma operację zapisu w miejscu nowszą niż "
                              f"odczyt skanu (generacja {generation})")


def isolating_inplace_op(con, location_id):
    """Operacja zapisu w miejscu, która IZOLUJE lokację (`INPLACE_ISOLATING_PHASES`), albo `None`.
    Jedna bramka przed każdą mutacją pliku lokacji (`writeback`) i przed otwarciem nowej operacji
    (`begin_inplace_commit`/`begin_inplace_undo`)."""
    return con.execute(
        "SELECT id, kind, phase, commit_id FROM inplace_op WHERE location_id = ? "
        "AND phase IN (SELECT value FROM json_each(?)) ORDER BY id DESC LIMIT 1",
        (location_id, json.dumps(list(INPLACE_ISOLATING_PHASES)))).fetchone()


def _refuse_if_isolated(con, location_id):
    op = isolating_inplace_op(con, location_id)
    if op is not None:
        raise ValueError(f"location:{location_id} ma operację zapisu w miejscu {op['id']} "
                         f"w fazie {op['phase']} - nowej operacji nie zaczynam")


class InplaceConflict(Exception):
    """Podmiana pliku drogą atomową (`os.replace`) trafiła na operację zapisu w miejscu tej lokacji:
    izolującą albo zaczętą po odczycie pliku, z którego powstał plik tymczasowy
    (`guard_file_replace`). `op` = wiersz operacji (`id`, `kind`, `phase`, `commit_id`) - wołający
    buduje z niego powód odmowy. Plik nietknięty."""

    def __init__(self, op):
        super().__init__(f"operacja zapisu w miejscu {op['id']} ({op['kind']}, faza {op['phase']})")
        self.op = op


@contextmanager
def guard_file_replace(con, *, location_id, generation):
    """STRAŻ PODMIANY drogi atomowej (astra, 2026-09-27): `BEGIN IMMEDIATE`, w nim sprawdzenie, że
    lokacja nie ma operacji izolującej (`isolating_inplace_op`) ani operacji o `id` większym niż
    `generation` (zapamiętanej przez wołającego PRZED jego bramką izolacji), i dopiero wtedy ciało
    `with` - `os.replace` pisarza - a po nim `COMMIT`. Operacja na lokacji → `InplaceConflict`,
    ciało się nie wykonuje.

    DLACZEGO TRANSAKCJA, a nie samo sprawdzenie: bramka izolacji commitu i `os.replace` to dwie
    chwile, a między nimi (plik tymczasowy, backup) zapis w miejscu mógł zacząć się, zapisać plik
    i zostać `written` - podmiana starłaby jego bajty, a commit atomowy zgłosiłby 'applied'. Straż
    trzyma blokadę zapisu bazy przez całą podmianę, a `begin_inplace_commit`/`begin_inplace_undo`
    biorą ją też (`BEGIN IMMEDIATE`), więc otwarcie operacji i podmiana są uszeregowane: operacja
    zaczęta przed strażą ma większe `id` niż generacja i odbija podmianę, zaczęta po niej czeka.
    Straż NIE pisze do bazy: backup drogi atomowej utrwala wołający WCZEŚNIEJ, własną transakcją
    (kolejność „backup w bazie przed podmianą" zostaje), więc tu nie ma czym się zakleszczyć."""
    with _immediate(con):
        _refuse_inplace_conflict(con, location_id, generation)
        yield


def _refuse_inplace_conflict(con, location_id, generation):
    """Sprawdzenie straży mutacji pliku (`guard_file_replace`, `guard_file_rename`) wołane WEWNĄTRZ
    ich transakcji: operacja izolująca lokację albo operacja o `id` > `generation` (dowolnej fazy,
    także zakończona) → `InplaceConflict`. `generation=None` = sama izolacja."""
    op = isolating_inplace_op(con, location_id)
    if op is None and generation is not None:
        op = con.execute(
            "SELECT id, kind, phase, commit_id FROM inplace_op WHERE location_id = ? "
            "AND id > ? ORDER BY id DESC LIMIT 1", (location_id, generation)).fetchone()
    if op is not None:
        raise InplaceConflict(op)


def _inplace_op_values(location_id, commit_id, kind, spec, now):
    return (location_id, commit_id, kind, spec.fmt, spec.region_offset, len(spec.old_region),
            zlib.compress(spec.old_region, 9), zlib.compress(spec.new_region, 9),
            spec.write_start, spec.write_end, spec.file_size, spec.file_ino, spec.pre_hash,
            spec.post_hash, spec.anchor_sha1, now)


_INSERT_INPLACE_OP = (
    "INSERT INTO inplace_op(location_id, commit_id, kind, fmt, region_offset, region_length, "
    "old_region_z, new_region_z, write_start, write_end, file_size, file_ino, pre_hash, "
    "post_hash, anchor_sha1, phase, started_at) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'writing', ?)")


def begin_inplace_commit(con, *, run_id, commit_id, location_id, hdu_index, header_text, spec,
                         now, pending_ids=()):
    """JEDNA transakcja przed pierwszym bajtem zapisu w miejscu (commit): wiersz `commits` (gdy
    `commit_id` None), backup nagłówka do undo, operacja `inplace_op` w fazie `writing` (z kotwicą
    `spec.anchor_sha1`, 0023) i WIĄZANIE wpisów stagingu `pending_ids` z operacją
    (`pending_changes.inplace_op_id`). Wszystko albo nic - backup bez operacji zostawiłby zapis bez
    izolacji, operacja bez backupu - bez undo, operacja bez wiązania - wiersze, których dokończenie
    nie znajdzie. `spec` = obiekt z polami `writeback.OpSpec`. Zwraca `(commit_id, op_id)`.
    Lokacja z operacją izolującą (`isolating_inplace_op`) → `ValueError`, zero zapisu: to ostatni
    szaniec bramki pisarza, w tej samej transakcji co wstawienie operacji. Wiązanie dotyka wyłącznie
    wierszy 'pending' TEJ lokacji; inna liczba niż `pending_ids` → `ValueError` (EXPECT: staging
    zmienił się pod pisarzem), zero zapisu. Wiersz 'pending' z wiązaniem do operacji ZAMKNIĘTEJ
    (przerwa przed zapisem → odzysk, zwolnienie ręką) wiąże się na nowo - to legalne ponowienie;
    wiązania do operacji izolującej tu nie ma, bo taką lokację odbija `_refuse_if_isolated` wyżej."""
    ids = [int(i) for i in pending_ids]
    with _immediate(con):
        _refuse_if_isolated(con, location_id)
        if commit_id is None:
            commit_id = con.execute(
                "INSERT INTO commits(run_id, applied_at, summary) VALUES (?, ?, ?)",
                (run_id, now, f"run {run_id}")).lastrowid
        con.execute(
            "INSERT INTO header_backups(commit_id, location_id, hdu_index, header_text, post_hash) "
            "VALUES (?, ?, ?, ?, ?)",
            (commit_id, location_id, hdu_index, header_text, spec.post_hash))
        op_id = con.execute(_INSERT_INPLACE_OP,
                            _inplace_op_values(location_id, commit_id, "commit", spec, now)).lastrowid
        if ids:
            n = con.execute(
                "UPDATE pending_changes SET inplace_op_id = ? WHERE id IN "
                "(SELECT value FROM json_each(?)) AND location_id = ? AND status = 'pending'",
                (op_id, json.dumps(ids), location_id)).rowcount
            if n != len(set(ids)):
                raise ValueError(f"operacja {op_id}: związano {n} z {len(set(ids))} wpisów "
                                 f"stagingu lokacji {location_id} - staging zmienił się pod "
                                 f"pisarzem, zapisu nie zaczynam")
    return commit_id, op_id


def begin_inplace_undo(con, *, commit_id, location_id, spec, now):
    """Operacja `inplace_op` rodzaju `undo` w fazie `writing` - przed pierwszym bajtem cofnięcia
    w miejscu. Materiałem cofnięcia jest backup commitu, więc nowego backupu nie ma. Zwraca op_id.
    Lokacja z operacją izolującą → `ValueError`, zero zapisu (jak `begin_inplace_commit`)."""
    with _immediate(con):
        _refuse_if_isolated(con, location_id)
        return con.execute(_INSERT_INPLACE_OP,
                           _inplace_op_values(location_id, commit_id, "undo", spec, now)).lastrowid


def inplace_op_phase(con, op_id):
    """Bieżąca faza operacji (albo `None`, gdy jej nie ma) - pisarz czyta ją POD BLOKADĄ pliku,
    żeby decyzja o odzysku i dokończeniu nie opierała się na odczycie sprzed blokady."""
    row = con.execute("SELECT phase FROM inplace_op WHERE id = ?", (op_id,)).fetchone()
    return None if row is None else row["phase"]


def newer_inplace_op(con, *, location_id, op_id):
    """Czy lokacja ma operację zapisu w miejscu PÓŹNIEJSZĄ niż `op_id` (dowolnej fazy). Odzysk
    i dokończenie operacji odmawiają wtedy: plik mógł dostać nowszy, poprawny zapis."""
    return con.execute("SELECT 1 FROM inplace_op WHERE location_id = ? AND id > ? LIMIT 1",
                       (location_id, op_id)).fetchone() is not None


def set_inplace_op_phase(con, *, op_id, phase, now, reason=None, expect_phase=None):
    """Przejście fazy operacji (`written`/`unverified`/`synced`/`recovered`). `closed_at` stawia
    każda faza poza `writing`. Transient - bez eventu (mutację pliku opisuje re-sync).

    `expect_phase` (CAS): przejście zachodzi WYŁĄCZNIE z tej fazy; inna faza w bazie (drugi proces
    zdążył ją zmienić) → `ValueError`, zero zapisu. Pisarz podaje ją przy każdym przejściu pod
    blokadą pliku, więc spóźnione drugie wywołanie nie przestawi fazy cudzej decyzji."""
    if phase not in _INPLACE_PHASES:
        raise ValueError(f"nieznana faza operacji w miejscu: {phase!r}")
    with con:
        if expect_phase is None:
            cur = con.execute("UPDATE inplace_op SET phase = ?, reason = ?, closed_at = ? "
                              "WHERE id = ?", (phase, reason, now, op_id))
        else:
            cur = con.execute("UPDATE inplace_op SET phase = ?, reason = ?, closed_at = ? "
                              "WHERE id = ? AND phase = ?", (phase, reason, now, op_id,
                                                             expect_phase))
        if cur.rowcount != 1:
            raise ValueError(f"operacja {op_id}: przejście do {phase!r} nie zaszło (oczekiwana "
                             f"faza {expect_phase!r})")


def _op_in_phase(con, op_id, phase):
    """Wiersz operacji w fazie `phase` (pod transakcją wołającego) albo `ValueError`."""
    op = con.execute("SELECT id, kind, location_id, phase FROM inplace_op WHERE id = ?",
                     (op_id,)).fetchone()
    if op is None or op["phase"] != phase:
        raise ValueError(f"operacja {op_id} nie jest w fazie {phase!r} "
                         f"({None if op is None else op['phase']}) - nie ma czego zamykać")
    return op


def finish_inplace_op(con, *, op_id, now, actor="user:local"):
    """DOKOŃCZENIE operacji zapisu w miejscu - JEDNA transakcja (astra, 2026-09-27): faza `written`
    → `synced` (CAS), wpisy stagingu związane z operacją (`pending_changes.inplace_op_id`, 0023) →
    'applied' bez powodu, a gdy któryś z nich wpisał `OBJECT` - zgaszenie nagrobka ręki klatki tej
    lokacji tą samą klingą co commit drogą atomową (`_clear_object_tombstone_tx`).

    Wołane przez pisarza (`writeback._dokoncz`) pod blokadą pliku, PO udanej kontroli danych
    i re-syncu. Dawniej faza, statusy i nagrobek szły trzema osobnymi transakcjami, a dokończenie
    szukało wierszy po statusie 'failed': crash po `written` zostawiał wiersze 'pending' na zawsze.
    Teraz te trzy fakty albo zachodzą razem, albo wcale - i dotyczą DOKŁADNIE wierszy operacji, nie
    wszystkich wierszy przebiegu. Operacja nie w fazie `written` → `ValueError`, zero zapisu.
    Transient (faza, staging) bez eventu; nagrobek emituje swój. Zwraca liczbę oznaczonych wpisów."""
    with _immediate(con):
        op = _op_in_phase(con, op_id, "written")
        con.execute("UPDATE inplace_op SET phase = 'synced', reason = NULL, closed_at = ? "
                    "WHERE id = ? AND phase = 'written'", (now, op_id))
        rows = con.execute("SELECT keyword FROM pending_changes WHERE inplace_op_id = ?",
                           (op_id,)).fetchall()
        con.execute("UPDATE pending_changes SET status = 'applied', reason = NULL "
                    "WHERE inplace_op_id = ?", (op_id,))
        if op["kind"] == "commit" and any(r["keyword"] == "OBJECT" for r in rows):
            loc = con.execute("SELECT frame_id FROM location WHERE id = ?",
                              (op["location_id"],)).fetchone()
            _clear_object_tombstone_tx(con, frame_id=loc["frame_id"], now=now, actor=actor)
    return len(rows)


def revert_inplace_op(con, *, op_id, now, reason, expect_phase="written", actor="user:local"):
    """DROGA POWROTU z fazy izolującej z NIEUDANĄ kontrolą danych - JEDNA transakcja, wołana przez
    pisarza (`writeback.recover_torn`) pod blokadą pliku, PO przywróceniu starego regionu w miejscu:
    faza `expect_phase` → `recovered` z powodem (CAS), wpisy stagingu związane z operacją → 'failed'
    z tym samym powodem (zmiana NIE weszła do pliku) i ZWOLNIENIE lokacji do pełnego skanu.

    `expect_phase` = faza, którą pisarz przeczytał pod blokadą: `written` (zapis zweryfikowany,
    kontrola danych nie przeszła) albo faza OTWARTA (`writing`/`unverified` - odzysk przywrócił stary
    region, a kontrola danych po nim nie przechodzi, AR-17 (6)). Obie drogi kończą się tak samo, bo
    w obu baza nie ma kotwicy, wobec której wciągnięcie pliku byłoby dowodem.

    ZWOLNIENIE = `location.mtime` → NULL. Brama przyrostowa skanu (`scan._already_scanned`) pomija
    plik wyłącznie przy równości `(volume, path, mtime)`, a NULL nie równa się niczemu - następny
    skan przeczyta plik w całości i opisze go od nowa (`ingest_record`), zamiast ufać faktom
    kopii, które opisywały plik sprzed zmiany poza nagłówkiem. Ten sam brak `mtime` odbija kolejny
    zapis w miejscu przed skanem (kotwica pisarza nie zgadza się z `mtime` → pełny odczyt → sha1 inny
    niż w bazie → 'blocked'). Mutacja stanu lokacji niesie ślad `location.writeback_reverted` z
    fazą i `mtime` przed oraz powodem. Faza izolująca inna niż `expect_phase` (drugi proces zdążył
    ją zmienić) albo `expect_phase` spoza faz izolujących → `ValueError`, zero zapisu."""
    if expect_phase not in INPLACE_ISOLATING_PHASES:
        raise ValueError(f"powrót dotyczy wyłącznie faz izolujących, nie {expect_phase!r}")
    with _immediate(con):
        op = _op_in_phase(con, op_id, expect_phase)
        con.execute("UPDATE inplace_op SET phase = 'recovered', reason = ?, closed_at = ? "
                    "WHERE id = ? AND phase = ?", (reason, now, op_id, expect_phase))
        con.execute("UPDATE pending_changes SET status = 'failed', reason = ? "
                    "WHERE inplace_op_id = ?", (reason, op_id))
        loc = con.execute("SELECT mtime FROM location WHERE id = ?",
                          (op["location_id"],)).fetchone()
        con.execute("UPDATE location SET mtime = NULL WHERE id = ?", (op["location_id"],))
        emit_event(con, actor=actor, verb="location.writeback_reverted",
                   target=f"location:{op['location_id']}", now=now,
                   payload={"inplace_op": op_id, "phase_before": expect_phase,
                            "mtime": {"before": loc["mtime"], "after": None}},
                   reason=reason)


def release_inplace_op(con, *, op_id, now, reason, expect_phase=None, actor="user:local"):
    """JAWNE ZWOLNIENIE izolacji lokacji ręką (Q8): operacja izolująca (`INPLACE_ISOLATING_PHASES`,
    także `written` czekająca na re-sync) → `released`, lokacja wraca do zwykłego skanu. Gest
    człowieka po własnym rozstrzygnięciu (np. plik przywrócony z pełnej kopii) - stąd zdarzenie
    `location.writeback_released` z powodem. Operacja nieizolująca → `ValueError`.

    CAS FAZY (jak `set_inplace_op_phase`): `expect_phase` = faza, którą wołający przeczytał pod
    blokadą pliku (`writeback.release_isolation`); inna faza w bazie (drugi proces zdążył ją
    zmienić - pisarz przestawił `writing` na `written`, odzysk zamknął operację) → `ValueError`
    z obiema fazami, zero zapisu. `None` = faza przeczytana tu, w tej samej transakcji
    `BEGIN IMMEDIATE`. UPDATE niesie warunek fazy tak czy tak, więc zwolnienie nigdy nie przestawi
    fazy, której wołający nie widział."""
    with _immediate(con):
        row = con.execute("SELECT location_id, phase FROM inplace_op WHERE id = ?",
                          (op_id,)).fetchone()
        if row is None or row["phase"] not in INPLACE_ISOLATING_PHASES:
            raise ValueError(f"operacja {op_id} nie izoluje lokacji - nie ma czego zwalniać")
        oczekiwana = row["phase"] if expect_phase is None else expect_phase
        cur = con.execute("UPDATE inplace_op SET phase = 'released', reason = ?, closed_at = ? "
                          "WHERE id = ? AND phase = ?", (reason, now, op_id, oczekiwana))
        if cur.rowcount != 1:
            raise ValueError(f"operacja {op_id} jest w fazie {row['phase']}, nie {oczekiwana} - "
                             f"inny proces zmienił ją po odczycie, zwolnienia nie ma")
        emit_event(con, actor=actor, verb="location.writeback_released",
                   target=f"location:{row['location_id']}", now=now,
                   payload={"inplace_op": op_id, "phase_before": row["phase"]}, reason=reason)


# ============================================================ RENAME "Nazwy z faktów" (krok "nazwy")
# relocate_location = FAKT DOMENOWY (mutacja pliku na dysku), emituje event — inaczej niż staging.
# Staging renamu (pending_renames) = transient (bez eventu), jak staging writebacku. Rename NIE tyka
# bajtów → `sha1_data`/`file_sha1`/`header_hash` NIEZMIENNE; ta sama location, nowy path (R2 #1: NIGDY
# `ingest_record`, bo nowa ścieżka mintowałaby DRUGĄ location, starą zostawiając sierotą).


def relocate_location(con, *, location_id, new_path, now, actor="user:local"):
    """RENAME fizycznego pliku w modelu: UPDATE `location.path` IN-PLACE + `event(location.renamed)`.
    Przepięcie BEZ straży izolacji: commit i cofnięcie renamu idą `guard_file_rename`, która
    obejmuje rename i to samo przepięcie jedną transakcją (AR-17 (5)); pisarz tej funkcji dziś nie
    woła - wołają ją wyłącznie testy (PLIK→DB, T8). NIE re-sync/ingest -
    tożsamość frame przeżywa (rename nie tyka danych). ANTY-CLOBBER W BAZIE (R3 #3): brak INNEGO wiersza
    `location(volume, new_path)` — inaczej UPDATE łamie `UNIQUE(volume, path)` PO renamie = rozjazd
    plik↔DB → `ValueError` (commit oznaczy 'blocked'). Guard+UPDATE w `_immediate` (TOCTOU wobec
    równoległego writera). Idempotentny: `path` już == `new_path` → `False` bez eventu."""
    with _immediate(con):
        old_path = _relocation_target(con, location_id, new_path)
        if old_path == new_path:
            return False
        _apply_relocation(con, location_id=location_id, old_path=old_path, new_path=new_path,
                          now=now, actor=actor)
    return True


def _relocation_target(con, location_id, new_path):
    """Pod transakcją wołającego: bieżąca `path` lokacji. Brak lokacji albo cel zajęty w bazie przez
    INNY wiersz `(volume, new_path)` (anty-clobber w bazie, R3 #3) → `ValueError`."""
    row = con.execute(
        "SELECT volume, path FROM location WHERE id = ?", (location_id,)).fetchone()
    if row is None:
        raise ValueError(f"location:{location_id} nie istnieje")
    clash = con.execute(
        "SELECT id FROM location WHERE volume = ? AND path = ? AND id <> ?",
        (row["volume"], new_path, location_id)).fetchone()
    if clash is not None:
        raise ValueError(
            f"cel zajęty w bazie: location:{clash['id']} ma już (volume={row['volume']}, "
            f"{new_path})")
    return row["path"]


def _apply_relocation(con, *, location_id, old_path, new_path, now, actor):
    """UPDATE `location.path` + `location.renamed` pod transakcją wołającego."""
    con.execute("UPDATE location SET path = ? WHERE id = ?", (new_path, location_id))
    emit_event(con, actor=actor, verb="location.renamed", target=f"location:{location_id}",
               now=now, payload={"before": old_path, "after": new_path})


@contextmanager
def guard_file_rename(con, *, location_id, new_path, generation, now, actor="user:local"):
    """STRAŻ RELOKACJI (AR-17 (5)): rename pliku lokacji i przepięcie `location.path` w JEDNEJ
    transakcji `BEGIN IMMEDIATE` - bliźniak `guard_file_replace` dla `os.rename`:

      1. `_refuse_inplace_conflict`: operacja izolująca lokację albo operacja o `id` > `generation`
         (zapamiętanej przez wołającego PRZED jego bramką izolacji, dowolnej fazy) → `InplaceConflict`;
      2. anty-clobber w bazie (`_relocation_target`) → `ValueError`;
      3. ciało `with` - `os.rename` pisarza (`writeback.rename_file`);
      4. dopiero po ciele BEZ wyjątku: UPDATE `location.path` + `location.renamed`, COMMIT.
    Wyjątek w ciele (rename nie zaszedł) → rollback, zero zapisu w bazie.

    DLACZEGO TRANSAKCJA OBEJMUJE RENAME: bramka izolacji w `writeback.commit_renames` i `os.rename`
    to dwie chwile, a między nimi zapis w miejscu mógł otworzyć operację, zapisać nagłówek i zostać
    `written` (izolowana) albo `synced` - rename przeniósłby plik izolowany albo plik, którego
    nagłówek (a więc nazwa z faktów) zmienił się od podglądu. `begin_inplace_commit`
    i `begin_inplace_undo` biorą tę samą blokadę zapisu bazy, więc otwarcie operacji i relokacja są
    uszeregowane: operacja zaczęta przed strażą odbija rename, a zaczęta po jej COMMIT zastaje
    bazę po przepięciu ścieżki. Anty-clobber sprawdzony pod tą samą blokadą gwarantuje, że UPDATE
    po udanym renamie nie trafi na `UNIQUE(volume, path)`."""
    with _immediate(con):
        _refuse_inplace_conflict(con, location_id, generation)
        old_path = _relocation_target(con, location_id, new_path)
        yield
        _apply_relocation(con, location_id=location_id, old_path=old_path, new_path=new_path,
                          now=now, actor=actor)


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
    `calibration_profile.assigned` dla klatka↔profil), by tej nazwy nie zająć.

    AUTOMAT NIE DEGRADUJE OGNIWA WSKAZANEGO RĘKĄ (E4-2, warunek Zdzinia 0809: „wprowadzanie nowych
    subów albo masterów nie może wpłynąć na wycofanie czegokolwiek już ustawionego ręcznie"). Do
    0809 była to JEDYNA oś rodowodu bez takiej bramki: siostrzana `link_integration` ma
    `RANGA_ASSERT`, `calibration_fact` ma człon `source == 'user'`, a tutaj nowy dark po prostu
    przepinał ogniwo — bezwarunkowym UPDATE-em. Trzymało to wyłącznie na ZERZE populacji (dziś
    `calibration` z `asserted_by='user'`: 0, bo gestu ręki na tej osi jeszcze nie ma), więc
    pierwszy taki gest łamałby warunek po cichu. Teraz warunek trzyma MECHANIZM.

    Pełnej drabiny rang tu NIE MA i to jest świadome: `RANGA_ASSERT` opisuje słownik osi stosów
    (`history`/`window`/`user`), a ta oś ma własny (`horreum`, docelowo `wbpp` — DDL 0009). Dwa
    słowniki w jednym dicie zrobiłyby z kanonu wspólny worek. Pytanie, na które ta bramka odpowiada,
    jest jedno i binarne — „czy ręka już to rozstrzygnęła" — więc kształt jest taki sam, jak
    w `calibration_fact`, i urośnie dopiero razem z drugim nie-ludzkim źródłem."""
    row = con.execute(
        "SELECT id, master_frame_id, asserted_by FROM calibration "
        "WHERE light_frame_id = ? AND relation = ?",
        (light_frame_id, relation)).fetchone()
    # IDEMPOTENCJA PYTA O PARĘ (kalibrator, źródło), nie o sam kalibrator — inaczej bramka niżej
    # byłaby NIEOSIĄGALNA: ręka potwierdzająca ten sam master, który wybrał automat, odbijała się
    # od tego `return` i źródło zostawało `horreum`, więc werdykt nie miał jak powstać. Lustro
    # `link_integration`: „podniesienie pewności zostawia ślad".
    if row is not None and (row["master_frame_id"], row["asserted_by"]) == (master_frame_id,
                                                                            asserted_by):
        return False
    if row is not None and row["asserted_by"] == "user" and asserted_by != "user":
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
            # `.unlinked` TYLKO przy realnej zmianie kalibratora (bramka pakietu 3a, zarzut 8).
            # Od 0810 idempotencja pyta o PARĘ (kalibrator, źródło), więc istnieje nowa ścieżka:
            # ręka potwierdza ten sam master, który wybrał automat. Bezwarunkowa emisja robiła
            # z tego w dzienniku bezsensowne przepięcie `X → X` i milczała o jedynej rzeczy,
            # która się zmieniła.
            if row["master_frame_id"] != master_frame_id:
                emit_event(con, actor=actor, verb="calibration.unlinked",
                           target=f"frame:{light_frame_id}", now=now,
                           payload={"relation": relation,
                                    "master_frame_id": row["master_frame_id"]})
        emit_event(con, actor=actor, verb="calibration.linked",
                   target=f"frame:{light_frame_id}", now=now,
                   payload={"relation": relation, "master_frame_id": master_frame_id,
                            "asserted_by": asserted_by})
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
                       telescope_mismatch, unresolved_reason, now, actor="stacks",
                       raw_unreferenced=None):
    """Wiersz `integration` dla klatki mastera — `(integration_id, zmienione)`.

    `raw_unreferenced` (G2-1d, migracja 0020) to UWAGA obok werdyktu, nie drugi werdykt: ile
    RAW-ów przebieg widział i nie umiał umieścić w czasie. Jedzie w TEJ liście pól, bo jest
    wyliczana z bazy co przebieg (lustro `telescope_mismatch`), a nie werdyktem ręki (jak offset).
    Domyślne `None` = „brak uwagi"; CHECK 0020 odbija zero i dubel z `offset_unknown`.

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
              "telescope_mismatch": telescope_mismatch, "unresolved_reason": unresolved_reason,
              "raw_unreferenced": raw_unreferenced}
    wartosci = list(fields.values())
    with _immediate(con):
        row = con.execute(
            "SELECT id, integ_hash, tool, window_start, window_end, declared_rows, drizzle_inputs, "
            "disabled_inputs, degenerate, ambiguous, telescope_mismatch, unresolved_reason, "
            "raw_unreferenced "
            "FROM integration WHERE master_frame_id = ?", (master_frame_id,)).fetchone()
        if row is None:
            cur = con.execute(
                "INSERT INTO integration(master_frame_id, created_at, integ_hash, tool, "
                "window_start, window_end, declared_rows, drizzle_inputs, disabled_inputs, "
                "degenerate, ambiguous, telescope_mismatch, unresolved_reason, raw_unreferenced) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
            "degenerate = ?, ambiguous = ?, telescope_mismatch = ?, unresolved_reason = ?, "
            "raw_unreferenced = ? WHERE id = ?", [now] + wartosci + [row["id"]])
        emit_event(con, actor=actor, verb="integration.updated",
                   target=f"frame:{master_frame_id}", now=now,
                   payload={"integration_id": row["id"],
                            "before": {k: v[0] for k, v in zmiany.items()},
                            "after": {k: v[1] for k, v in zmiany.items()}})
        return row["id"], True


UTC_OFFSET_MAX_MIN = 840
"""Sufit odniesienia czasu w minutach — fizyczny zakres zegarów świata (UTC−12…UTC+14).

Nie jest to ostrożność na wyrost: bez niego literówka w geście (`600` zamiast `60`) zapisywała się
cicho i zamieniała receptę R2 w ślepy zaułek — stos meldował potem `no_candidates`, bo kandydaci
lądowali dziesięć godzin poza oknem, i nic nie wskazywało przyczyny."""


def set_integration_offset(con, *, master_frame_id, utc_offset_min, now, uid="local"):
    """Wskaż ODNIESIENIE CZASU stosu GESTEM CZŁOWIEKA (#DR2 R2, D-DR-1) — `True`, gdy drgnęło.

    Trójstan wprost z 0016: `None` = nieznane · `0` = UTC · liczba = minuty. ZNAK trzyma się jednej
    umowy w całym repo: **`lokalny = UTC + offset`**, więc kandydat wraca do odniesienia mastera
    przez ODJĘCIE (IC443 `+60`, LMC `+120` — zmierzone zgodnością `mm:ss` przy różnicy pełnych
    godzin). Konsumentem jest wyłącznie `stacks._in_window`.

    DLACZEGO OSOBNA KLINGA, A NIE POLE W `upsert_integration`: tamta pisze LITERALNĄ listę pól przy
    każdym przebiegu rodowodu, bo przepisuje głowę integracji z tego, co przebieg WYLICZYŁ. Offset
    nie jest wyliczony — jest werdyktem człowieka o zegarze aparatu, a jedynym świadkiem jest okno
    mastera. Wpuszczenie go do tamtej listy oznaczałoby, że pierwszy „Przetwórz wszystko" po geście
    zdejmuje fakt z powrotem do NULL (lustro lekcji R1b, gdzie automat zamalowywał ręczny config).
    Rozdział pisarzy JEST tu mechanizmem, nie stylem — pinuje go bramka G2-12.

    ODMOWA DLA STOSU, KTÓREGO NIE MA: `master_frame_id` bez wiersza `integration` → `ValueError`
    (błąd wołania, nie no-op). Wiersz integracji powstaje przy pierwszym przebiegu rodowodu także
    dla stosu bez wejść (kanon 0012 pkt 3), więc każdy stos, który powierzchnia w ogóle pokazuje,
    ma go już założony — brak wiersza znaczy, że pytamy o klatkę, która stosem nie jest.

    IDEMPOTENCJA: ta sama wartość → `False`, zero DML i zero eventu. Rozróżniamy przy tym `NULL`
    od `0` po stronie porównania (`is None`), bo w Pythonie `0 == False` — a to są dwa RÓŻNE
    werdykty: „nie wiem" i „to jest UTC".

    DWIE BRAMY NA WEJŚCIU, obie z bramki pakietu (zarzuty 4 i 5), obie zamykają drogę do zapisu,
    którego nie da się odróżnić od poprawnego:

    * **`bool` NIE JEST liczbą minut**, choć `isinstance(True, int)` jest prawdą. Bez tego członu
      `utc_offset_min=False` zapisywało się jako `0`, czyli jako werdykt „to jest UTC" — dokładnie
      ta kolizja `0 == False`, którą akapit wyżej deklaruje rozróżniać. Rozróżnialiśmy ją wszędzie
      poza wejściem;
    * **zakres ±840 minut** = fizyczny sufit zegarów świata (UTC−12…UTC+14). Odsiewa wartości
      spoza skali — `6000`, `-2000`, minuty pomylone z sekundami. **CZEGO NIE ŁAPIE I TRZEBA
      TO WIEDZIEĆ:** literówki dającej wartość FIZYCZNIE MOŻLIWĄ (`600` zamiast `60` to dziesięć
      godzin, czyli legalna strefa). Taki zapis przejdzie i stos zamelduje potem `no_candidates`
      zamiast `offset_unknown`. Zakres jest więc bramką na NONSENS, nie na pomyłkę — jedyną realną
      obroną przed tą drugą jest propozycja podana wprost w oknie (`stacks.propose_offset_minutes`)
      i to, że gest da się powtórzyć. **Mocniejszy wariant to CHECK w DDL** (baza jako ostatnia
      bramka słownika, kanon 0012/0015); tu wystarcza klinga, bo jest jedynym pisarzem tej
      kolumny — CHECK dołożyć przy najbliższej migracji dotykającej `integration`."""
    if isinstance(utc_offset_min, bool) or (
            utc_offset_min is not None and not isinstance(utc_offset_min, int)):
        raise ValueError("utc_offset_min musi być liczbą całkowitą minut albo None")
    if utc_offset_min is not None and abs(utc_offset_min) > UTC_OFFSET_MAX_MIN:
        raise ValueError(
            f"utc_offset_min poza zakresem zegarów świata (±{UTC_OFFSET_MAX_MIN} min): "
            f"{utc_offset_min}")
    with _immediate(con):
        row = con.execute(
            "SELECT id, utc_offset_min FROM integration WHERE master_frame_id = ?",
            (master_frame_id,)).fetchone()
        if row is None:
            raise ValueError(f"frame:{master_frame_id} nie ma wiersza integration")
        before = row["utc_offset_min"]
        if before is None and utc_offset_min is None:
            return False
        if before is not None and utc_offset_min is not None and before == utc_offset_min:
            return False
        # `updated_at` idzie razem z wartością (bramka pakietu, zarzut 8): głowa integracji DRGA
        # gestem człowieka, więc znacznik modyfikacji, który zostawał z ostatniego PRZEBIEGU,
        # pokazywał czas sprzed zmiany. Ślad w dzienniku był, kolumna kłamała.
        con.execute("UPDATE integration SET utc_offset_min = ?, updated_at = ? WHERE id = ?",
                    (utc_offset_min, now, row["id"]))
        emit_event(con, actor=f"user:{uid}", verb="integration.offset_set",
                   target=f"frame:{master_frame_id}", now=now,
                   payload={"integration_id": row["id"], "before": before,
                            "after": utc_offset_min})
    return True


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
