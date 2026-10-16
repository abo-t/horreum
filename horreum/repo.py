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
import ntpath
import os
import zlib
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, replace
from enum import Enum
from typing import NamedTuple

from .item_reasons import (OdmowaZPowodem,    # powód z kodem (AR-141, AR-148) - liść
                           PowodPozycji, dopisz, dopisz_z_koperta, do_bazy, z_bazy)
from .resolve.paths import path_key           # klucz ścieżki fizycznej - jeden dla podglądu planera
                                                # i straży relokacji (liść `resolve`, bez cyklu)
from .resolve._text import norm_alnum          # kierunek repo → resolve (liść; COHESION §2b)
from .resolve.catalog import catalog_canon      # gramatyka katalogowa — CZYSTA, bez assetu (liść)
from .resolve.catalog import xref               # para katalogowa - strażnik wskrzeszenia (0040)
from .resolve.channel import CHANNELS           # słownik kanału (0028) - liść, bez cyklu
from .resolve.stack import raw_stem             # rdzeń nazwy pliku - alias dawnej nazwy (0034)
from .resolve.frames import (HISTORY_MASTER_KINDS,   # pary przeliczenia rodzaju (AR-96)
                             LIGHT_KINDS)            # guard RODZAJU w klindze (S2b) - liść, bez cyklu
from .resolve.headers import (FAKTY_BIEZACE, FAKTY_DO_DOCIAGNIECIA,   # stan faktów kopii (AR-33)
                              FAKTY_NOWSZE, copy_facts_state,
                              copy_testimony)            # źródło `header` (kopia wiodąca, AR-4)
from .resolve.objects import (CLEARABLE_OBJECT_SOURCES,  # enum źródeł osi OBIEKT —
                              OBJECT_SOURCES,           # jeden właściciel (S1/S2b)
                              STICKY_OBJECT_SOURCES,    # …ręki, nietykalne dla cofnięcia (AR-38)
                              TRANSFERABLE_OBJECT_SOURCES,   # …i przeżywające podmianę (R4)
                              WEAK_OBJECT_SOURCES)
from .resolve.observatory import (nearest_site,    # kierunek repo → resolve (liść math/re; COHESION §2b)
                                  site_coords,       # GPS nagłówka - ta sama reguła co resolver
                                  user_site_coords)  # walidacja współrzędnych ręki (SPOT z oknem i CLI)


@contextmanager
def _immediate(con):
    """Transakcja z write-lockiem OD STARTU (`BEGIN IMMEDIATE`) — guard+write atomowo wobec
    równoległego writera (PLAN_gui §2, P1: WAL serializuje writerów, ale NIE zwalnia z atomowości
    czytaj-sprawdź-pisz). Domyślny `with con:` bierze tylko lock przy pierwszym DML, więc SELECT
    guardu i UPDATE mogłyby objąć cudzy commit (TOCTOU). Tu RESERVED lock blokuje innych od razu.
    Używane przez zapisy usera (label/approve/merge/unmerge), gdzie guard MUSI trzymać do UPDATE.

    Wewnątrz zakresu `atomic` na tym połączeniu NIE otwiera własnej transakcji - dołącza do
    zewnętrznej, która trzyma lock od startu, commit i rollback."""
    if id(con) in _ATOMIC:
        yield
        return
    con.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        con.rollback()
        raise
    else:
        con.commit()


# Połączenia, na których trwa zakres `atomic` - po `id` obiektu, bo `sqlite3.Connection` nie przyjmuje
# atrybutów. Wpis żyje dokładnie tyle, co zakres (połączenie jest wtedy żywe, więc `id` się nie powtórzy).
_ATOMIC = set()


@contextmanager
def atomic(con):
    """JEDNA transakcja (`BEGIN IMMEDIATE`) na kilka zapisów klingi - dla wołającego, którego jeden
    krok domenowy to kilka funkcji tego modułu (wjazd rekordu skanu: kamera, klatka, lokacja,
    zeznanie, flagi). Każda z nich dalej emituje swój event w tej samej transakcji co swój zapis;
    zakres dokłada tylko to, że wszystkie zapisy kroku wchodzą razem albo żaden.

    DLACZEGO: osobne transakcje zostawiały po awarii w połowie stan, którego ponowny odczyt nie leczy
    (P4-8, AR-21): klatka przepięta bez zeznania, nowa klatka bez lokacji albo bez `header`, kamera
    z rozdartego odczytu po odmowie strażnika generacji.

    Wewnątrz zakresu wolno wołać WYŁĄCZNIE funkcje, które biorą transakcję przez `_immediate` albo
    `_tx` - te dołączają do zakresu. Goły `with con:` zatwierdziłby zewnętrzną transakcję w połowie.
    Zagnieżdżony `atomic` dołącza do zewnętrznego."""
    if id(con) in _ATOMIC:
        yield
        return
    with _immediate(con):
        _ATOMIC.add(id(con))
        try:
            yield
        finally:
            _ATOMIC.discard(id(con))


@contextmanager
def _tx(con):
    """`with con:` (transakcja odroczona: lock przy pierwszym DML), która wewnątrz `atomic` dołącza
    do zakresu zewnętrznego zamiast zatwierdzać go w połowie."""
    if id(con) in _ATOMIC:
        yield
        return
    with con:
        yield


def emit_event(con, *, actor, verb, target, now, payload=None, reason=None):
    """Dopisz zdarzenie do append-only `event`. Wołane WYŁĄCZNIE z tego modułu, w tej samej
    transakcji co zapis, który opisuje."""
    con.execute(
        "INSERT INTO event(ts, actor, verb, target, payload, reason) VALUES (?, ?, ?, ?, ?, ?)",
        (now, actor, verb, target,
         json.dumps(payload, ensure_ascii=False) if payload is not None else None,
         reason),
    )


# Tolerancja WZGLĘDNA zgodności piksela matrycy (decyzja Zdzinia 2026-10-05, AR-55: „wszystkie
# wartości w zakresie są poprawne”). EXIF podaje piksel z rozdzielczości płaszczyzny ogniskowej, nie
# z karty katalogowej: SONYA7S 8,469 wobec 8,45 µm (0,2 %) to ta sama matryca; SONYA7RM3 4,62 wobec
# 4,86 (5 %) to sprzeczność prawdziwa i ma zostać konfliktem.
PIXEL_REL_TOLERANCE = 0.006


def pixel_agrees(a, b):
    """Czy dwa zeznania piksela [µm] opisują tę samą matrycę (`PIXEL_REL_TOLERANCE` wobec większej)."""
    return abs(a - b) <= PIXEL_REL_TOLERANCE * max(abs(a), abs(b))


def upsert_camera(con, *, model_canon, pixel_um, is_mono, is_mono_source,
                  raw_instrume, now, actor="scan"):
    """Wyłoń kamerę (oś) ze skanu. Tożsamość = `model_canon` (UNIQUE); `pixel_um` to NULLABLE
    WŁAŚCIWOŚĆ (brief §3/R1#3 — po naprawie nagłówków model rozstrzyga tożsamość, piksel bywa
    nieobecny, np. Sony masterflat bez XPIXSZ).

    Nowa → INSERT + `camera.upserted` w tej samej transakcji; (id, True). Istnieje → (id, False),
    a piksel jest UZUPEŁNIANY/PILNOWANY (R2#4 + R3-c1):
      - piksel wpisany RĘKĄ (`pixel_source='user'`, 0031) → no-op: człowiek wie lepiej niż karta
        i EXIF (AR-55 (3)), więc zeznanie skanu ani go nie zmienia, ani nie stawia konfliktu;
      - zeznanie ZGODNE w tolerancji `PIXEL_REL_TOLERANCE` → no-op (pierwsze zeznanie zostaje);
      - wiersz ma `pixel_um IS NULL`, przyszła wartość → **CAS jednym statementem**
        (`UPDATE ... WHERE id=? AND pixel_um IS NULL`) + `event(camera.pixel_set)`; rowcount=0
        (równoległy writer wygrał — WAL sankcjonuje GUI+CLI naraz) → re-SELECT i gałąź konfliktu;
      - wiersz ma wartość poza tolerancją → **STAN `pixel_conflict=1`** (kolejka ze stanu, rama
        §0) + `event(camera.pixel_conflict)` (osobny verb, target `camera:` — R3-c3); przejście
        stanu emitowane RAZ (gating na rowcount). Zdjęcie konfliktu = `set_camera_pixel` (ręka).
    """
    row = con.execute(
        "SELECT id, pixel_um, pixel_source FROM camera WHERE model_canon = ?",
        (model_canon,)).fetchone()
    if row is None:
        with _tx(con):  # atomowo: INSERT camera + INSERT event (albo żadne - rollback)
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
    if (pixel_um is None or row["pixel_source"] == "user"
            or (existing_px is not None and pixel_agrees(existing_px, pixel_um))):
        return camera_id, False                       # nic do uzupełnienia / ręka / zgodne — no-op

    if existing_px is None:
        with _tx(con):  # CAS: uzupełnij TYLKO gdy wciąż NULL (bez lost-update między writerami)
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
        if existing_px is None or pixel_agrees(existing_px, pixel_um):
            return camera_id, False                   # równoległy writer: zgodnie albo ręka zdjęła

    with _tx(con):  # rozjazd wartości → STAN pixel_conflict (event raz, na przejściu 0→1)
        # CAS na stanie, który porównaliśmy: ręka wpisana albo cofnięta między odczytem a zapisem
        # (GUI + CLI naraz) zmienia `pixel_source` albo `pixel_um`, więc konflikt nie wraca od
        # zeznania skanu i event nie twierdzi o pikselu, którego już nie ma (bramka sol Z2).
        cur = con.execute(
            "UPDATE camera SET pixel_conflict = 1 WHERE id = ? AND pixel_conflict = 0 "
            "AND pixel_source IS NULL AND pixel_um IS ?",
            (camera_id, existing_px))
        if cur.rowcount:
            emit_event(con, actor=actor, verb="camera.pixel_conflict",
                       target=f"camera:{camera_id}", now=now,
                       payload={"pixel_existing": existing_px, "pixel_new": pixel_um})
    return camera_id, False


def set_camera_pixel(con, *, camera_id, pixel_um, now, actor="user"):
    """Piksel matrycy wpisany RĘKĄ (AR-55 (3), 0031): `pixel_um` + `pixel_source='user'` + zdjęty
    konflikt, jedną transakcją z `event(camera.pixel_user_set)`. Payload niesie stan SPRZED wpisu
    (`prev_pixel_um`, `prev_conflict`, `prev_source`) - z niego `clear_camera_pixel` przywraca kamerę.

    Zwraca True przy zmianie, False gdy ręka wpisuje to samo, co już stoi z ręki (QUIET, bez eventu).
    Wartość niedodatnia albo nieznana kamera = `ValueError` (EXPECT - człowiek się pomylił)."""
    if not (isinstance(pixel_um, (int, float)) and pixel_um > 0):
        raise ValueError(f"piksel musi być liczbą dodatnią [µm], jest {pixel_um!r}")
    with _immediate(con):                             # guard + zapis ręki pod jednym lockiem
        row = con.execute(
            "SELECT pixel_um, pixel_conflict, pixel_source FROM camera WHERE id = ?",
            (camera_id,)).fetchone()
        if row is None:
            raise ValueError(f"nie ma kamery camera:{camera_id}")
        if row["pixel_source"] == "user" and row["pixel_um"] == pixel_um:
            return False
        con.execute(
            "UPDATE camera SET pixel_um = ?, pixel_source = 'user', pixel_conflict = 0 WHERE id = ?",
            (pixel_um, camera_id))
        emit_event(con, actor=actor, verb="camera.pixel_user_set", target=f"camera:{camera_id}",
                   now=now, payload={"pixel_um": pixel_um, "prev_pixel_um": row["pixel_um"],
                                     "prev_conflict": row["pixel_conflict"],
                                     "prev_source": row["pixel_source"]})
    return True


def clear_camera_pixel(con, *, camera_id, now, actor="user"):
    """Cofnięcie wpisu ręki: kamera wraca do stanu zapisanego w payloadzie NAJSTARSZEGO eventu
    `camera.pixel_user_set` bieżącej serii wpisów (seria = wpisy od ostatniego
    `camera.pixel_user_cleared`), czyli do stanu sprzed pierwszej ręki - kolejne poprawki ręki nie
    są stanem skanu. Event `camera.pixel_user_cleared` z wartością zdjętą.

    Zwraca True przy zmianie, False gdy piksel nie pochodzi z ręki (QUIET)."""
    with _immediate(con):
        row = con.execute("SELECT pixel_um, pixel_source FROM camera WHERE id = ?",
                          (camera_id,)).fetchone()
        if row is None:
            raise ValueError(f"nie ma kamery camera:{camera_id}")
        if row["pixel_source"] != "user":
            return False
        target = f"camera:{camera_id}"
        first = con.execute(
            "SELECT payload FROM event WHERE target = ? AND verb = 'camera.pixel_user_set' "
            "AND id > COALESCE((SELECT MAX(id) FROM event WHERE target = ? "
            "                   AND verb = 'camera.pixel_user_cleared'), 0) "
            "ORDER BY id LIMIT 1", (target, target)).fetchone()
        if first is None:                             # stan 'user' bez eventu = złamany inwariant
            raise RuntimeError(f"{target}: pixel_source='user' bez eventu camera.pixel_user_set")
        prev = json.loads(first["payload"])
        con.execute(
            "UPDATE camera SET pixel_um = ?, pixel_conflict = ?, pixel_source = ? WHERE id = ?",
            (prev["prev_pixel_um"], prev["prev_conflict"], prev["prev_source"], camera_id))
        emit_event(con, actor=actor, verb="camera.pixel_user_cleared", target=target, now=now,
                   payload={"pixel_um": row["pixel_um"], "restored_pixel_um": prev["prev_pixel_um"],
                            "restored_conflict": prev["prev_conflict"]})
    return True


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

    with _tx(con):  # atomowo: INSERT frame + INSERT event
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
# `hdr_rule` (0025, AR-33) - numer reguły koercji, którą zebrano fakty (`COPY_TESTIMONY_RULE`); jedzie
# w tym samym słowniku, więc każdy z trzech pisarzy stempluje go tym samym zapisem co fakty.
COPY_FACTS = ("image_count", "image_roles", "hdr_filter", "hdr_imagetyp", "hdr_object",
              "hdr_telescop", "hdr_instrume", "hdr_exptime", "hdr_xbinning", "hdr_date_obs",
              "hdr_hash", "hdr_rule")


def _copy_facts_checked(copy_facts):
    """EXPECT na kształcie słownika faktów kopii - jeden strażnik dla trzech pisarzy (dodanie,
    odświeżenie, uzupełnienie). Zwraca słownik z kompletem kluczy; `None` → same NULL-e.

    Kotwica i reguła występują RAZEM (0025): fakty bez numeru reguły wróciłyby do bazy jako „reguła
    nieznana" i sterownik czytałby je ponownie przy każdej dostawie; reguła bez faktów to sprzeczność,
    którą odbija też CHECK 0025."""
    if copy_facts is None:
        return dict.fromkeys(COPY_FACTS)
    if set(copy_facts) != set(COPY_FACTS):
        raise ValueError(f"fakty kopii: klucze {sorted(copy_facts)} != {sorted(COPY_FACTS)}")
    if (copy_facts["hdr_hash"] is None) != (copy_facts["hdr_rule"] is None):
        raise ValueError(f"fakty kopii: kotwica {copy_facts['hdr_hash']!r} bez pary z regułą "
                         f"{copy_facts['hdr_rule']!r}")
    return copy_facts


def add_location(con, *, frame_id, volume, path, drive_letter=None, tier=None, mtime=None,
                 file_sha1=None, header_hash=None, hdu_index=None, compressed=None,
                 size_bytes=None, copy_facts=None, unreadable_since=None, unreadable_kind=None,
                 unreadable_reason=None, now, actor="scan"):
    """Dołóż lokalizację frame'a po `UNIQUE(volume, path)` wraz z faktami KOPII (file_sha1/
    header_hash/hdu_index/compressed/size_bytes — brief §2; `hdu_index`/`compressed` NULL dla XISF,
    wszystkie odciski NULL przy W1). Już znana →
    (id, False) bez eventu i BEZ dotykania faktów (odświeżenie = `refresh_location`, osobny
    kontrakt). Nowa → INSERT + `event(location.added)`; (id, True). `volume` = trwały
    identyfikator wolumenu; placeholder '?' NIE blokuje skanu (to nie tożsamość frame'a, §7.5).
    `drive_letter` to efemeryczny cache wyświetlania.

    `copy_facts` (0021) - fakty z nagłówka TEJ kopii (klucze `COPY_FACTS`); `None` = nie zebrane
    (kolumny NULL, kopię dobierze uzupełnienie). Kotwica `hdr_hash` musi równać się `header_hash`
    - pilnuje tego CHECK w bazie, nie ten kod.

    MARKER NIECZYTELNOŚCI OD PIERWSZEGO ODCZYTU (P4-7, AR-21 (a)): `unreadable_since` + rodzaj
    i powód (P4-2) - wołający podaje je, gdy pierwsza próba odczytu NOWEJ kopii padła (W1). Marker
    znaczy „kopia JEST nieczytelna" (ostatnia próba odczytu nieudana), więc pierwsza porażka jest
    taką samą przesłanką jak każda następna. Do P4-7 marker stawiał wyłącznie re-odczyt znanej
    ścieżki, a skutki były dwa: brama przyrostowa przy tym samym `mtime` pomijała kopię bez markera
    (nikt jej już nie czytał), a szkielet nie niósł rodzaju awarii - kubełek nie mówił, czy winny
    jest dysk, czy parser. Domyślnie `None` - kopia czytelna (dowód odczytu niesie wołający).
    Rodzaj i powód bez markera odbija CHECK 0019."""
    row = con.execute(
        "SELECT id FROM location WHERE volume = ? AND path = ?", (volume, path)).fetchone()
    if row is not None:
        return row[0], False

    cf = _copy_facts_checked(copy_facts)
    with _tx(con):  # atomowo: INSERT location + INSERT event
        cur = con.execute(
            "INSERT INTO location(frame_id, volume, drive_letter, path, tier, mtime, "
            "file_sha1, header_hash, hdu_index, compressed, size_bytes, last_verified_at, "
            "unreadable_since, unreadable_kind, unreadable_reason, "
            "image_count, image_roles, hdr_filter, hdr_imagetyp, hdr_object, hdr_telescop, "
            "hdr_instrume, hdr_exptime, hdr_xbinning, hdr_date_obs, hdr_hash, hdr_rule) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (frame_id, volume, drive_letter, path, tier, mtime,
             file_sha1, header_hash, hdu_index, compressed, size_bytes, now,
             unreadable_since, unreadable_kind, unreadable_reason,
             *(cf[k] for k in COPY_FACTS)),
        )
        location_id = cur.lastrowid
        payload = {"volume": volume, "path": path, "tier": tier}
        if unreadable_since is not None:
            payload["unreadable_kind"] = unreadable_kind
        emit_event(
            con, actor=actor, verb="location.added", target=f"frame:{frame_id}", now=now,
            payload=payload,
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

    WCHŁONIĘCIE SZKIELETU (AR-42) idzie tą samą kolumną, innym czasownikiem: `frame.absorbed`.
    Szkielet (`skeleton_frame_ids`: rodzaj `unknown`, bez zeznania, bez lokacji, bez faktów ręki)
    traci lokację nie przez podmianę treści, tylko dlatego, że plik WYZDROWIAŁ i przeczytany dał
    prawdziwą tożsamość. Ogniwo jest prawdą („plik spod tej ścieżki niesie dziś klatka N") i trzyma
    szkielet poza kubełkami roboty (sieroty, `headerless`) bez nowej kolumny; czasownik mówi
    w dzienniku, że to nie była edycja. Rozstrzyga stan pod lockiem, nie wołający.

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
        verb = "frame.absorbed" if skeleton_frame_ids(con, [frame_id]) else "frame.superseded"
        con.execute("UPDATE frame SET superseded_by = ? WHERE id = ?", (superseded_by, frame_id))
        emit_event(con, actor=actor, verb=verb, target=f"frame:{frame_id}",
                   now=now, payload={"superseded_by": superseded_by})
    return True


def skeleton_frame_ids(con, frame_ids):
    """Które z `frame_ids` są SZKIELETEM BEZ ŚLADU (AR-42) - set[int]. JEDEN właściciel predykatu
    dla klingi (`mark_superseded`: czasownik `frame.absorbed`), passu (`supersede.backfill`: licznik
    `absorbed`) i read-modelu (`absorbed_frame_ids` → perspektywa „Zastąpione").

    Szkielet = klatka z miękkiego lądowania odczytu (W1): rodzaj `unknown`, ustalony bez ręki
    (`kind_source IS NULL`), BEZ zeznania (`header`) i BEZ żadnej lokacji (także nieobecnej - plik,
    który zniknął spod innej ścieżki, może wrócić, więc to jeszcze nie wchłonięcie). BEZ FAKTÓW
    RĘKI: werdykt wycofania, oś obiektu, zestaw i stanowisko wskazane ręką, werdykt rodowodu, uwaga
    klatki (0032) - każdy z nich czyni klatkę czymś więcej niż pustym miejscem po nieudanym odczycie
    i zostawia ją przy zwykłym zastąpieniu (kubełek przeniesienia faktów,
    `supersede.pending_transfer`)."""
    ids = sorted({int(i) for i in frame_ids})
    if not ids:
        return set()
    return {int(r[0]) for r in con.execute(
        "SELECT f.id FROM frame f WHERE f.id IN (SELECT value FROM json_each(?)) "
        "AND f.kind = 'unknown' AND f.kind_source IS NULL AND f.retired_at IS NULL "
        "AND f.object_id IS NULL AND f.object_source IS NULL "
        "AND f.config_id IS NULL AND f.config_source IS NULL "
        "AND f.observatory_id IS NULL AND f.observatory_source IS NULL "
        "AND NOT EXISTS (SELECT 1 FROM header h WHERE h.frame_id = f.id) "
        "AND NOT EXISTS (SELECT 1 FROM location l WHERE l.frame_id = f.id) "
        "AND NOT EXISTS (SELECT 1 FROM integration_input ii WHERE ii.input_frame_id = f.id "
        "                AND ii.asserted_by = 'user') "
        "AND NOT EXISTS (SELECT 1 FROM frame_note n WHERE n.frame_id = f.id)",
        (json.dumps(ids),)).fetchall()}


def absorbed_frame_ids(con):
    """Klatki WCHŁONIĘTE (AR-42): zastąpione (`superseded_by IS NOT NULL`), które są szkieletem bez
    śladu (`skeleton_frame_ids`). Predykat ze STANU, więc obejmuje też ogniwa zapisane przed AR-42
    czasownikiem `frame.superseded` (na `pf4` 2026-10-07: 15629 → 16778). Zwraca set[int]."""
    return skeleton_frame_ids(con, [r[0] for r in con.execute(
        "SELECT id FROM frame WHERE superseded_by IS NOT NULL")])


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
    observatory_moved: bool = False
    """Przeniesiono stanowisko wskazane ręką (0027) - czwarta oś, przechodzi na następczynię
    z osią obserwatorium PUSTĄ (lustro guardu configu: GPS w jej nagłówku to jej własne zeznanie)."""
    lineage_moved: int = 0
    lineage_dropped: int = 0
    """ILE martwych wskaźników rodowodu zdjęto, bo następczyni miała już WŁASNY werdykt (0810).
    Osobno od `lineage_moved`, bo to inna robota i inny skutek: tam werdykt przechodzi, tu znika
    wiersz, który po geście człowieka przestał cokolwiek wskazywać. Sklejenie ich w jedną liczbę
    kazałoby raportowi mówić „przeniesiono", gdy nic nie przeszło."""
    object_kept: bool = False
    """Fakt ręki obiektu ZOSTAŁ na klatce zastąpionej, bo następczyni nie jest lightem (AR-16):
    kalibracja z definicji nie ma obiektu. Osobno od `skipped`, bo inne osie mogły przejść w tym
    samym geście, a raport ma powiedzieć, że werdykt ręki nie przepadł, tylko nie miał dokąd iść."""
    note_moved: bool = False
    """Przeniesiono uwagę klatki (0032) - piąta oś, przechodzi na następczynię BEZ własnej uwagi.
    Klatka, z której przeszła wyłącznie uwaga, też jest przeniesieniem (gest liczy ją w `done`)."""
    calibration_moved: int = 0
    """ILE wskazań kalibratora ręką (`calibration.asserted_by='user'`, E4-5) przeszło na następczynię -
    szósta oś, liczba relacji (dark/flat), nie bit."""
    skipped: str = ""          # "" = nic nie pominięto (konwencja liczników z `ObjectGesture`)


class KlatkaNieJestZastapiona(ValueError):
    """`transfer_human_facts` na klatce, która (już) nie jest zastąpiona - jedyny warunek wejścia
    klingi, który wołający gestu może spotkać bez własnego błędu: skan gasi ogniwo, gdy treść wraca
    pod ścieżkę (`clear_superseded`), także między odczytem gestu a klingą. Osobny typ, żeby gest
    łapał DOKŁADNIE ten przypadek, a każdy inny `ValueError` klingi leciał dalej (AR-41)."""


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

    NASTĘPCZYNI-KALIBRACJA NIE DOSTAJE OBIEKTU (AR-16, guard `LIGHT_KINDS`): podmieniona treść ma
    własne zeznanie `IMAGETYP`, więc light ze źródłem `path` może wrócić jako flat - a klatka
    kalibracyjna z definicji nie ma obiektu i resolver obiektu na niej nie rozstrzyga. Werdykt ręki
    ZOSTAJE wtedy na klatce zastąpionej (tam i tak zostaje, append-only) i raport mówi o tym
    `object_kept`; kubełek `supersede.pending_transfer` tej osi nie liczy, bo gest nie umiałby jej
    opróżnić. Następczyni o rodzaju jeszcze nieustalonym (`unknown`) też nie jest kandydatem -
    gdy przebieg ustali light, kubełek (liczony ze stanu) pokaże parę ponownie.

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

    CZWARTA OŚ: STANOWISKO WSKAZANE RĘKĄ (0027, `STICKY_OBSERVATORY_SOURCES`). Guard brzmi jak przy
    configu i z tego samego powodu: `observatory_source` pisze wyłącznie ręka, więc pytamy o oś
    W CAŁOŚCI - przenosimy, gdy następczyni nie ma ani wskazania ręki, ani stanowiska z GPS swojego
    nagłówka (to drugie jest jej własnym zeznaniem i cudzy werdykt go nie nadpisuje). Oś jest
    KIND-AGNOSTIC, więc ani rodzaj, ani kamera następczyni nie blokują przeniesienia. Oś następczyni
    jest pusta, więc emitujemy samo `observatory.assigned` - nie ma czego odpinać, a para
    rozjechałaby bilans `frame.observatory_id` (wzorzec przeniesienia configu).

    PIĄTA OŚ: UWAGA KLATKI (0032). Guard pyta o oś w całości, jak przy stanowisku: przenosimy, gdy
    następczyni nie ma WŁASNEJ uwagi - jej uwaga jest zdaniem człowieka o tej treści i cudza jej
    nie nadpisuje. Oś jest KIND-AGNOSTIC (uwaga mówi o nocy i o obrazie, także flata: „zmieniony
    flat”). Stara klatka zostaje ze swoją uwagą (append-only), więc spis `notes_hand` rośnie o jeden
    zamiast stać w miejscu. Zapis to `note.set` z `before=None` i `przeniesione_z` - parytet
    `frame_note` czyta ostatni event uwag klatki, więc przeniesiona uwaga bilansuje się jak napisana
    ręką.

    SZÓSTA OŚ: KALIBRATOR WSKAZANY RĘKĄ (E4-5, `calibration.asserted_by='user'`). To RELACJA, nie
    kolumna klatki - więc jak rodowód stosu: wiersz PRZECHODZI (para `calibration.unlinked` na
    starej + `calibration.linked` na następczyni), a nie dubluje się. Guard: następczyni jest lightem,
    ma kamerę mastera (wskazanie ręki z cudzej matrycy byłoby kłamstwem - klinga gestu by go nie
    przyjęła) i nie ma WŁASNEGO wskazania ręki tej relacji; ogniwo automatu następczyni jest
    nadpisywane, bo to dobór, nie werdykt. Wskazanie, które nie pasuje, ZOSTAJE na klatce zastąpionej
    (`skipped='kalibrator nie pasuje do nastepczyni'`, gdy nic innego nie przeszło).

    Zwraca `FactTransfer`. Idempotentne: powtórzenie po udanym przeniesieniu trafia w guardy
    wszystkich osi (następczyni ma już swoje) i zwraca `skipped` bez zapisu."""
    with _immediate(con):
        stara = con.execute(
            "SELECT superseded_by, object_id, object_source, object_cleared_id, "
            "       config_id, config_source, observatory_id, observatory_source "
            "FROM frame WHERE id = ?", (frame_id,)).fetchone()
        if stara is None:
            raise ValueError(f"frame:{frame_id} nie istnieje")
        if stara["superseded_by"] is None:
            raise KlatkaNieJestZastapiona(
                f"frame:{frame_id} nie jest zastąpiona - nie ma dokąd przenosić")
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
        ma_stanowisko = (stara["observatory_source"] in STICKY_OBSERVATORY_SOURCES
                         and stara["observatory_id"] is not None)
        uwaga = con.execute(
            "SELECT body FROM frame_note WHERE frame_id = ?", (frame_id,)).fetchone()
        kalibratory = con.execute(
            "SELECT c.relation AS relation, c.master_frame_id AS master_frame_id, "
            "c.confidence AS confidence, m.camera_id AS m_cam FROM calibration c "
            "JOIN frame m ON m.id = c.master_frame_id "
            "WHERE c.light_frame_id = ? AND c.asserted_by = 'user' ORDER BY c.relation",
            (frame_id,)).fetchall()
        if (not ma_obiekt and not ma_config and not ma_stanowisko and not rodowod
                and uwaga is None and not kalibratory):
            return FactTransfer(skipped="brak faktow czlowieka")
        nowa_id = stara["superseded_by"]
        nowa = con.execute(
            "SELECT kind, camera_id, object_source, config_id, config_source, "
            "       observatory_id, observatory_source FROM frame "
            "WHERE id = ?", (nowa_id,)).fetchone()
        if nowa is None:
            raise ValueError(f"frame:{nowa_id} (następczyni) nie istnieje")
        obiekt_zostaje = ma_obiekt and nowa["kind"] not in LIGHT_KINDS
        obiekt_do_przeniesienia = (ma_obiekt and not obiekt_zostaje
                                   and nowa["object_source"] is None)
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
        stanowisko_do_przeniesienia = (ma_stanowisko and nowa["observatory_source"] is None
                                       and nowa["observatory_id"] is None)
        uwaga_do_przeniesienia = uwaga is not None and con.execute(
            "SELECT 1 FROM frame_note WHERE frame_id = ?", (nowa_id,)).fetchone() is None
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
        # SZÓSTA OŚ - lustro predykatu `supersede.pending_transfer` (kolumna `kalibracja`).
        kal_nowej = {r["relation"]: r for r in con.execute(
            "SELECT relation, master_frame_id, asserted_by FROM calibration "
            "WHERE light_frame_id = ?", (nowa_id,))}
        kal_reki_nowej = {rel for rel, r in kal_nowej.items() if r["asserted_by"] == "user"}
        kalibracja_do_przeniesienia = [
            r for r in kalibratory
            if nowa["kind"] == "light" and r["m_cam"] is not None
            and r["m_cam"] == nowa["camera_id"] and r["relation"] not in kal_reki_nowej]
        if (not obiekt_do_przeniesienia and not config_do_przeniesienia
                and not stanowisko_do_przeniesienia and not uwaga_do_przeniesienia
                and not rodowod_do_przeniesienia and not rodowod_do_zdjecia
                and not kalibracja_do_przeniesienia):
            # POWÓD MA BYĆ PRAWDZIWY, nie jeden dla wszystkich odmów: „następczyni ma własne
            # źródło" i „zestaw do niej nie pasuje" to dwa różne stany i dwie różne dalsze drogi
            # (w pierwszym nie ma nic do roboty, w drugim ręka musi wskazać zestaw od nowa).
            nie_pasuje = ma_config and (nowa["config_source"] is None
                                        and nowa["config_id"] is None)
            if obiekt_zostaje:
                powod = "nastepczyni to kalibracja - obiekt zostaje na zrodle"
            elif nie_pasuje:
                powod = "zestaw nie pasuje do nastepczyni"
            elif any(r["relation"] not in kal_reki_nowej for r in kalibratory):
                powod = "kalibrator nie pasuje do nastepczyni"
            else:
                powod = "nastepczyni ma wlasne zrodlo"
            return FactTransfer(object_kept=obiekt_zostaje, skipped=powod)

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
        if stanowisko_do_przeniesienia:
            con.execute("UPDATE frame SET observatory_id = ?, observatory_source = ? WHERE id = ?",
                        (stara["observatory_id"], stara["observatory_source"], nowa_id))
            emit_event(con, actor=actor, verb="observatory.assigned", target=f"frame:{nowa_id}",
                       now=now, payload={"observatory_id": stara["observatory_id"],
                                         "observatory_source": stara["observatory_source"],
                                         "przeniesione_z": frame_id},
                       reason="stanowisko wskazane ręką przeniesione po podmianie pliku")
        if uwaga_do_przeniesienia:
            con.execute("INSERT INTO frame_note(frame_id, body, updated_at) VALUES (?, ?, ?)",
                        (nowa_id, uwaga["body"], now))
            emit_event(con, actor=actor, verb="note.set", target=f"frame:{nowa_id}",
                       now=now, payload={"before": None, "after": uwaga["body"],
                                         "przeniesione_z": frame_id},
                       reason="uwaga przeniesiona po podmianie pliku")
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
        for r in kalibracja_do_przeniesienia:
            przed = kal_nowej.get(r["relation"])
            if przed is None:
                con.execute(
                    "INSERT INTO calibration(light_frame_id, master_frame_id, relation, "
                    "asserted_by, confidence) VALUES (?, ?, ?, 'user', ?)",
                    (nowa_id, r["master_frame_id"], r["relation"], r["confidence"]))
            else:
                con.execute(
                    "UPDATE calibration SET master_frame_id = ?, asserted_by = 'user', "
                    "confidence = ? WHERE light_frame_id = ? AND relation = ?",
                    (r["master_frame_id"], r["confidence"], nowa_id, r["relation"]))
            con.execute("DELETE FROM calibration WHERE light_frame_id = ? AND relation = ? "
                        "AND asserted_by = 'user'", (frame_id, r["relation"]))
            emit_event(con, actor=actor, verb="calibration.linked", target=f"frame:{nowa_id}",
                       now=now, payload={"relation": r["relation"],
                                         "master_frame_id": r["master_frame_id"],
                                         "asserted_by": "user", "przeniesione_z": frame_id,
                                         **({"before": [przed["master_frame_id"],
                                                        przed["asserted_by"]]}
                                            if przed is not None else {})},
                       reason="kalibrator wskazany ręką przeniesiony po podmianie pliku")
            emit_event(con, actor=actor, verb="calibration.unlinked", target=f"frame:{frame_id}",
                       now=now, payload={"relation": r["relation"],
                                         "master_frame_id": r["master_frame_id"],
                                         "asserted_by": "user", "reason": "transferred",
                                         "przeniesione_na": nowa_id})
    return FactTransfer(object_moved=obiekt_do_przeniesienia,
                        object_kept=obiekt_zostaje,
                        config_moved=config_do_przeniesienia,
                        observatory_moved=stanowisko_do_przeniesienia,
                        note_moved=uwaga_do_przeniesienia,
                        lineage_moved=len(rodowod_do_przeniesienia),
                        lineage_dropped=len(rodowod_do_zdjecia),
                        calibration_moved=len(kalibracja_do_przeniesienia))


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
    frame_ids: tuple = ()          # klatki REALNIE zapisane - recepta odwrotu rusza tylko je

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
    g, zapisane = RetireGesture(), []
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
            zapisane.append(row["id"])
    # Lista lokalna i jedna krotka po pętli: doklejanie krotki per klatkę to O(n²) pod blokadą zapisu.
    return replace(g, frame_ids=tuple(zapisane))


def restore_frames(con, *, frame_ids, now, uid="local"):
    """PRZYWRÓCENIE klatki wycofanej: `retired_at = NULL` + `event(frame.unretired)`.

    DROGA POWROTU jest tu WARUNKIEM, nie ozdobą — wycofanie jest werdyktem CZŁOWIEKA (a nie faktem
    o świecie, jak `superseded_by`), a paczka, która dokłada nieodwracalny gest, wnosi dokładnie
    ten dług, który domyka (grupa G2).

    JEDEN guard, bo jeden warunek ma sens: klatka nie wycofana → `skipped_already`. Obecność kopii
    NIE jest tu powodem pominięcia i to jest sedno — powrót pliku to najczęstszy powód, dla którego
    człowiek sięga po ten gest."""
    g, zapisane = RetireGesture(), []
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
            zapisane.append(row["id"])
    return replace(g, frame_ids=tuple(zapisane))   # jedna krotka po pętli, jak przy wycofaniu


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
      Zeznanie odświeża WYŁĄCZNIE kopia wiodąca (AR-4, `testimony_flows_from`: kotwica ręki,
      jedyna obecna kopia albo jednoznaczne źródło bieżącego `header`). Zmiana nagłówka innej
      kopii zostaje w jej faktach (`location.refreshed`) - rozjazd pokażą „Kopie niezgodne",
      a kopię wiodącą wskaże człowiek. Dawne „ostatni odczyt wygrywa" było automatyczną regułą
      wyboru przy ≥2 obecnych kopiach, której decyzja Zdzinia (2026-09-26) zakazuje.
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
      odcisku nagłówka bez odświeżenia faktów IntegrityError-em. Fakty wiersza reguły NOWSZEJ niż
      reguła wołającego (AR-33) przy tym samym odcisku zostają - jak w `record_copy_facts`.
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
            "hdr_instrume, hdr_exptime, hdr_xbinning, hdr_date_obs, hdr_hash, hdr_rule "
            "FROM location WHERE id = ?", (location_id,)).fetchone()
        if row is None:
            raise ValueError(f"location:{location_id} nie istnieje")
        _refuse_if_newer_inplace(con, location_id, inplace_gen)
        # Faktów kopii nieczytanych (`None`) nie ruszamy: zostają wartościami z wiersza. Tak samo
        # fakty wiersza zebrane regułą NOWSZĄ niż reguła wołającego (AR-33, kontrakt
        # `record_copy_facts`: binarka starsza od bazy niczego nie cofa) - o ile opisują ten sam
        # nagłówek. Po zmianie odcisku fakty wiersza mówią o pliku, którego już nie ma (i CHECK 0021
        # by je odbił), więc jedyną prawdą są fakty wołającego, nawet starszej reguły.
        zachowaj = cf is None or (
            cf["hdr_rule"] is not None and row["hdr_hash"] == header_hash
            and copy_facts_state(row["hdr_hash"], row["hdr_rule"], rule=cf["hdr_rule"])
            == FAKTY_NOWSZE)
        after.update({k: row[k] for k in COPY_FACTS} if zachowaj else cf)
        changed = {k: {"before": row[k], "after": after[k]}
                   for k in _LOCATION_FACTS if row[k] != after[k]}
        if not changed:
            return result
        # KOPIA WIODĄCA LICZONA PRZED zapisem faktów tej lokacji (AR-4): o tym, czy L była źródłem
        # zeznania, mówią jej fakty SPRZED zmiany nagłówka. Po UPDATE porównanie z `header`
        # widziałoby już nowy plik.
        przepisz = ("header_hash" in changed and raw_json is not None
                    and testimony_flows_from(con, frame_id, location_id))
        con.execute(
            "UPDATE location SET mtime = ?, file_sha1 = ?, header_hash = ?, hdu_index = ?, "
            "compressed = ?, size_bytes = ?, unreadable_since = ?, unreadable_kind = ?, "
            "unreadable_reason = ?, present = ?, last_verified_at = ?, "
            "image_count = ?, image_roles = ?, hdr_filter = ?, hdr_imagetyp = ?, hdr_object = ?, "
            "hdr_telescop = ?, hdr_instrume = ?, hdr_exptime = ?, hdr_xbinning = ?, "
            "hdr_date_obs = ?, hdr_hash = ?, hdr_rule = ? WHERE id = ?",
            (mtime, file_sha1, header_hash, hdu_index, compressed, size_bytes, unreadable_since,
             unreadable_kind, unreadable_reason, present, now,
             *(after[k] for k in COPY_FACTS), location_id))
        emit_event(con, actor=actor, verb="location.refreshed",
                   target=f"location:{location_id}", now=now, payload=changed)
        result["facts"] = True

        if not przepisz:
            return result
        result["header"] = True
        result["rederived"] = _rewrite_testimony(
            con, frame_id=frame_id, raw_json=raw_json, cards=cards, hot_fields=hot_fields,
            camera_id=camera_id, kind=kind, now=now, actor=actor, verb="header.refreshed",
            payload={"header_hash_before": row["header_hash"], "header_hash_after": header_hash})
    return result


class KindWitnessStale(Exception):
    """Przeliczenie rodzaju odmówione: stan klatki albo kopii, z której wołający policzył rodzaj,
    zmienił się po odczycie (`rederive_frame_kind`). Nic nie zapisano; ponowny odczyt rozstrzyga."""


def rederive_frame_kind(con, *, frame_id, expected_kind, kind, witnesses, now,
                        actor="rederive-kind"):
    """PRZELICZENIE RODZAJU klatki już w bazie BEZ ZMIANY ODCISKU nagłówka (AR-96). Zwykły przebieg
    rodzaju nie ruszy: brama przyrostowa pomija niezmieniony plik, a `refresh_location` przelicza
    pochodne wyłącznie przy zmianie `header_hash`. Reguła rodzaju urosła (historia integracji,
    `resolve.frames.kind_from_testimony`), plik nie - więc przeliczenie jest osobnym krokiem.

    `witnesses` = `[(location_id, header_hash)]` kopii, z których zeznania wołający policzył `kind`.
    W TEJ SAMEJ transakcji (`_immediate`) zbiór OBECNYCH kopii klatki z ich odciskami nagłówka musi
    być DOKŁADNIE zbiorem świadków (nowa kopia po odczycie mogłaby zeznawać inny rodzaj), a klatka -
    mieć rodzaj `expected_kind`; inaczej `KindWitnessStale` i zero zapisu (skan albo zapis nagłówka
    wyprzedził odczyt). Klatka już z rodzajem `kind` → False, zero
    eventów (idempotencja). Zmiana → UPDATE `frame.kind` + `event(frame.rederived)` z `before/after`
    w kształcie odświeżenia zeznania (`camera_id` bez zmian, obok rodzaju) i listą kopii-świadków.

    Dozwolone są WYŁĄCZNIE pary `HISTORY_MASTER_KINDS` (sub → master tej samej klasy przepisu); inna
    para to błąd wołającego (EXPECT, `ValueError`). Para nie przesuwa żadnej pochodnej zależnej od
    rodzaju (przepis, oś teleskopu, bramka kamery, oś obiektu - docstring mapy), więc klinga pisze
    sam rodzaj; rodowód (`calibrate` + `lineage`) przelicza zwykła droga po przeliczeniu.

    Ręki na osi rodzaju NIE MA: `kind_source` zna wyłącznie `header`/`path`/NULL (0010), więc nie ma
    tu ochrony wiersza `user` - byłaby pozorna. Gdy ręka powstanie, lista DOZWOLONYCH źródeł wchodzi
    do tej klingi razem z nią."""
    if HISTORY_MASTER_KINDS.get(expected_kind) != kind:
        raise ValueError(f"przeliczenie rodzaju {expected_kind!r} -> {kind!r} poza regułą historii")
    if not witnesses:
        raise ValueError("przeliczenie rodzaju bez kopii-świadka")
    with _immediate(con):
        fr = con.execute("SELECT kind, camera_id FROM frame WHERE id = ?", (frame_id,)).fetchone()
        if fr is None:
            raise KindWitnessStale(f"frame:{frame_id} nie istnieje")
        if fr["kind"] == kind:
            return False
        if fr["kind"] != expected_kind:
            raise KindWitnessStale(
                f"frame:{frame_id} ma rodzaj {fr['kind']!r}, odczyt zakładał {expected_kind!r}")
        obecne = {(r["id"], r["header_hash"]) for r in con.execute(
            "SELECT id, header_hash FROM location WHERE frame_id = ? AND present = 1", (frame_id,))}
        if obecne != {(lid, h) for lid, h in witnesses}:
            raise KindWitnessStale(
                f"obecne kopie frame:{frame_id} to nie dokładnie kopie odczytane "
                f"(nowa, zniknięta albo zmieniona po odczycie)")
        con.execute("UPDATE frame SET kind = ? WHERE id = ?", (kind, frame_id))
        emit_event(con, actor=actor, verb="frame.rederived", target=f"frame:{frame_id}", now=now,
                   payload={"before": {"camera_id": fr["camera_id"], "kind": fr["kind"]},
                            "after": {"camera_id": fr["camera_id"], "kind": kind},
                            "locations": sorted(lid for lid, _h in witnesses)})
    return True


def testimony_flows_from(con, frame_id, location_id):
    """Czy zmiana nagłówka lokacji `location_id` ma przepisać zeznanie klatki (AR-4, jedna reguła
    z ręką i bez): klatka bez `header` (nic do ochrony) albo lokacja jest KOPIĄ WIODĄCĄ
    (`lead_location`: kotwica ręki, jedyna obecna kopia, jednoznaczne źródło `header`).
    W każdym innym wypadku zmiana zostaje w faktach kopii, a rozjazd pokazują „Kopie niezgodne".

    To jest BRAMKA WYBORU KOPII, nie dowód stanu zeznania (AR-82): o tym, czy zeznanie klatki
    naprawdę opisuje plik, mówi `testimony_matches`."""
    if con.execute("SELECT 1 FROM header WHERE frame_id = ?", (frame_id,)).fetchone() is None:
        return True
    # Jedyna obecna to także kopia, która właśnie ODŻYWA (`present` 0 → 1 w tym zapisie) przy braku
    # innych obecnych - `lead_location` liczy stan sprzed zapisu, więc tej by nie widział.
    if con.execute("SELECT 1 FROM location WHERE frame_id = ? AND present = 1 AND id <> ?",
                   (frame_id, location_id)).fetchone() is None:
        return True
    return lead_location(con, frame_id) == location_id


def testimony_matches(con, *, frame_id, raw_json, hot_fields, cards):
    """DOWÓD ZEZNANIA (AR-82): czy zeznanie klatki (`header.raw_json`, wszystkie pola gorące
    `_HEADER_HOT` i lustro `cards`) jest DOKŁADNIE tym, co opisuje odczytany nagłówek pliku
    (`raw_json`/`hot_fields`/`cards` z `scan.testimony_of`). Jedno porównanie dla przejęcia
    (`adopt_testimony` - „zeznanie już identyczne”) i dla zapisu karty (`writeback._resync`):
    sukces zapisu to zeznanie zgodne z plikiem, nie samo prawo kopii do przepisania go
    (`testimony_flows_from`). Klatka bez `header` → `False`.

    PORÓWNANIE W SQLITE, NIE W PYTHONIE (bramka bloku A, B7): koercja pól gorących daje `nan` dla
    wartości `'NaN'` (XISF `CCD-TEMP`), a SQLite zapisuje NaN jako NULL - porównanie w Pythonie
    (`nan != None`) uznawało zeznanie za niezgodne zawsze i zapis jedynej kopii wisiał wstrzymany
    na zawsze. Wartości z rekordu idą jako parametry, więc przechodzą tę samą konwersję co przy
    zapisie zeznania; `IS` porównuje NULL z NULL. Lustro kart - tak samo (`_cards_key`)."""
    hot = dict(hot_fields or {})
    zgodne = con.execute(
        "SELECT raw_json = ? AND date_obs IS ? AND exptime IS ? AND filter_raw IS ? "
        "AND instrume IS ? AND telescop IS ? AND focallen IS ? AND focratio_raw IS ? "
        "AND xpixsz IS ? AND ypixsz IS ? AND gain IS ? AND offset_adu IS ? AND ccd_temp IS ? "
        "AND usblimit IS ? AND xbinning IS ? AND ybinning IS ? AND bayerpat IS ? AND ra_deg IS ? "
        "AND dec_deg IS ? AND object_raw IS ? FROM header WHERE frame_id = ?",
        (raw_json, *(hot.get(k) for k in _HEADER_HOT), frame_id)).fetchone()
    if zgodne is None or not zgodne[0]:
        return False
    return _cards_of(con, frame_id) == _cards_key(cards)


def _cards_key(cards):
    """Lustro kart jako posortowana lista krotek - postać porównania `testimony_matches`. Liczba
    `nan` przechodzi w `None`: tak SQLite trzyma NaN w `cards.value_num` (B7)."""
    return sorted((c.keyword, c.idx, c.value_raw,
                   None if c.value_num is not None and c.value_num != c.value_num
                   else c.value_num, c.value_type, c.comment)
                  for c in (cards or ()))


def _cards_of(con, frame_id):
    return sorted(tuple(r) for r in con.execute(
        "SELECT keyword, idx, value_raw, value_num, value_type, comment FROM cards "
        "WHERE frame_id = ?", (frame_id,)).fetchall())


def rewrite_testimony_from_copy(con, *, location_id, frame_id, sha1_data, header_hash, raw_json,
                                cards, hot_fields, camera_id, kind, now, actor="user:local"):
    """JAWNE PRZEPISANIE ZEZNANIA z kopii, którą bramka wyboru (`testimony_flows_from`) wybiera, gdy
    zeznanie nie opisuje jej pliku (AR-82, Z7): po wstrzymanym zapisie odcisk lokacji jest już nowy,
    więc `refresh_location` przy kolejnym odczycie nie widzi zmiany i zeznania nie przepisze - ta
    klinga domyka to w transakcji wołającego (`writeback._resync`, skan przy otwartym wstrzymaniu).

    CAS pod lockiem: lokacja należy do `frame_id`, klatka ma tożsamość `sha1_data`, lokacja jest
    obecna i ma odcisk `header_hash` (rekord jest odczytem tego pliku), a bramka wyboru nadal wybiera
    tę kopię. Rozjazd → `False`, zero zapisu. Przepisanie przez `_rewrite_testimony` (jeden rdzeń
    z odświeżeniem i przejęciem) z eventem `header.refreshed` niosącym kopię i powód. Zwraca `True`
    po przepisaniu."""
    with _immediate(con):
        loc = con.execute(
            "SELECT l.frame_id, l.present, l.header_hash, f.sha1_data FROM location l "
            "JOIN frame f ON f.id = l.frame_id WHERE l.id = ?", (location_id,)).fetchone()
        if (loc is None or loc["frame_id"] != frame_id or loc["sha1_data"] != sha1_data
                or not loc["present"] or loc["header_hash"] != header_hash
                or not testimony_flows_from(con, frame_id, location_id)):
            return False
        _rewrite_testimony(
            con, frame_id=frame_id, raw_json=raw_json, cards=cards, hot_fields=hot_fields,
            camera_id=camera_id, kind=kind, now=now, actor=actor, verb="header.refreshed",
            payload={"location_id": location_id, "header_hash_after": header_hash,
                     "reason": "zeznanie dociągnięte z kopii wiodącej (AR-82)"})
    return True


def hand_lead_location(con, frame_id):
    """KOTWICA RĘKI - kopia wiodąca klatki wskazana gestem, `location_id` albo `None` (AR-4).
    Źródłem jest najnowsze `header.adopted` klatki: aktor `user:*` (gest „Ta kopia prowadzi",
    `lead_copy`) → jego `location_id`; aktor automatu (etap Dostawy) albo brak przejęcia → `None`.
    Ta sama przesłanka co druga droga `gui.queries.hand_testimony_frame_ids`.

    KOTWICA WAŻNA WYŁĄCZNIE, gdy wskazana lokacja jest OBECNA i nadal należy do tej klatki: po
    zniknięciu wybranej kopii (albo przepięciu jej ścieżki na inną klatkę) kotwica nie wskazuje
    pliku, który mógłby mówić - inaczej zablokowałaby odświeżenie jedynej obecnej kopii (zapis
    nagłówka ręką raportowałby sukces, a zeznanie zostałoby stare). Fakt ręki zostaje w dzienniku
    i w osi `testimony_hand`; nieważna kotwica tylko przestaje rozstrzygać o kopii wiodącej."""
    return hand_lead_locations(con, [frame_id]).get(frame_id)


def hand_lead_locations(con, frame_ids):
    """`hand_lead_location` dla wielu klatek JEDNYM zapytaniem - `{frame_id: location_id}`, wyłącznie
    klatki z ważną kotwicą ręki. Jedyny właściciel reguły kotwicy (pojedyncza wersja woła tę):
    podpowiedź ścieżki w Zbiorach pyta o wszystkie klatki z kilkoma kopiami naraz, a zapytanie
    per klatka byłoby N+1 na składzie gridu. Po indeksie `idx_event_target` (target `frame:<id>`
    ze stałego literału `json_each`), jak `gui.queries.hand_testimony_frame_ids`."""
    if not frame_ids:
        return {}
    return {int(r[0]): int(r[1]) for r in con.execute(
        "SELECT CAST(substr(e.target, 7) AS INTEGER), l.id FROM event e "
        "JOIN location l ON l.id = json_extract(e.payload, '$.location_id') "
        "  AND l.frame_id = CAST(substr(e.target, 7) AS INTEGER) AND l.present = 1 "
        "WHERE e.id IN (SELECT MAX(id) FROM event "
        "               WHERE target IN (SELECT 'frame:' || value FROM json_each(?)) "
        "                 AND verb = 'header.adopted' "
        "               GROUP BY target) "
        "  AND e.actor LIKE 'user:%'",
        (json.dumps(sorted(set(frame_ids))),)).fetchall()}


def lead_location(con, frame_id):
    """KOPIA WIODĄCA klatki - `location_id`, z którego głosu ma płynąć zeznanie, albo `None`
    („nie wiadomo" - przy ≥2 obecnych kopiach zeznania nie przepisuje nikt poza człowiekiem, AR-4).

    Kolejność, pierwsza odpowiedź wygrywa:
      1. ważna kotwica ręki (`hand_lead_location`);
      2. JEDYNA obecna kopia - każda reguła wybrałaby ją, więc to nie jest wybór;
      3. ŹRÓDŁO bieżącego `header`: dokładnie jedna obecna kopia, której fakty bieżącej reguły
         (`hdr_hash == header_hash`, `FAKTY_BIEZACE`) równają się `copy_testimony(header)` - ta sama
         derywacja co predykat „Zeznanie z nieobecnej kopii". Odcisku nagłówka `header` nie niesie,
         a fakty kopii są jedynym porównaniem po polach, które da się policzyć z obu stron. Dwie
         pasujące kopie (identyczne zeznania) albo kopia bez faktów = źródła nie da się ustalić
         jednoznacznie → `None`.
    Klatka bez obecnej kopii → `None`."""
    kotwica = hand_lead_location(con, frame_id)
    if kotwica is not None:
        return kotwica
    kopie = con.execute(
        "SELECT id, header_hash, hdr_hash, hdr_rule, hdr_filter, hdr_imagetyp, hdr_object, "
        "hdr_telescop, hdr_instrume, hdr_exptime, hdr_xbinning, hdr_date_obs "
        "FROM location WHERE frame_id = ? AND present = 1 ORDER BY id", (frame_id,)).fetchall()
    if len(kopie) == 1:
        return kopie[0]["id"]
    if not kopie:
        return None
    h = con.execute("SELECT raw_json FROM header WHERE frame_id = ?", (frame_id,)).fetchone()
    if h is None:
        return None
    if any(copy_facts_state(k["hdr_hash"], k["hdr_rule"]) != FAKTY_BIEZACE
           or k["hdr_hash"] != k["header_hash"] for k in kopie):
        return None
    zeznanie = copy_testimony(json.loads(h["raw_json"]))
    zgodne = [k["id"] for k in kopie if all(k[p] == v for p, v in zeznanie.items())]
    return zgodne[0] if len(zgodne) == 1 else None


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
                    camera_id, kind, now, actor, inplace_gen=None, expected_frame_id=None):
    """PRZEJĘCIE ZEZNANIA klatki przez WSKAZANĄ kopię: `header` + `cards` + pochodne frame'a
    (`camera_id`/`kind`) z nagłówka pliku tej kopii, przeczytanego przed chwilą przez wołającego.

    DLACZEGO OSOBNA KLINGA, A NIE `refresh_location`: tamta przepisuje zeznanie wyłącznie przy
    zmianie odcisku nagłówka TEJ lokacji (reguła N-lokacji: pierwsza kopia, potem ta, której nagłówek
    zmienił się ostatnio). Gdy znika kopia, z której zeznanie pochodzi, ocalała kopia ma odcisk bez
    zmian i skan ją pomija - `header` niósłby do końca świata zeznanie pliku, którego nie ma.
    Rdzeń przepisania jest wspólny (`_rewrite_testimony`), różni się tylko przesłanka i ślad.

    KTÓRA KOPIA - ROZSTRZYGA WOŁAJĄCY, NIE KLINGA. Wejście to `location_id` wskazanej kopii i jej
    odczytany rekord; klinga nie zna reguły wyboru. Wołają ją etap Dostawy dla klatek o jednej
    obecnej kopii (`scan.adopt_orphan_testimony`) i gest człowieka „Ta kopia prowadzi" (AR-4,
    `lead_copy.lead_copy_gesture`, aktor `user:local`) przy kopiach, które mówią różnie.

    STRAŻNICY (pod `BEGIN IMMEDIATE`, TOCTOU wobec równoległego skanu):
      * EXPECT: `sha1_data` rekordu (tożsamość liczona regułą skanu, z degeneracją) MUSI równać się
        tożsamości klatki tej lokacji - inaczej wołający przeczytał plik cudzej klatki, a przejęcie
        byłoby kłamstwem. Błąd wołania, nie stan danych → `ValueError`;
      * kopia OBECNA (`present = 1`) i odcisk nagłówka rekordu == `location.header_hash`: plik niesie
        dokładnie ten nagłówek, który baza zna. Inny odcisk = kopia zmieniła się od skanu i należy
        do skanu (odświeży fakty kopii razem z zeznaniem); nieobecna = nie ma czego przejmować.
        Oba → `'drift'`, ZERO zapisu;
      * `expected_frame_id` (gest ręki, Z6): klatka, którą człowiek widział w menu. Skan mógł między
        menu a zapisem przepiąć ścieżkę na inną klatkę - ręka zapisałaby się na klatce, której nikt
        nie wybierał. Rozjazd → `'raced'`, ZERO zapisu;
      * aktor AUTOMATU (nie `user:*`): kandydaturę etapu (jedna obecna kopia, brak ręki) sprawdza
        się tu, pod lockiem, a nie tylko przy wyborze kandydatów - ważna kotwica ręki
        (`hand_lead_location`) albo liczba obecnych kopii ≠ 1 → `'raced'`, ZERO zapisu (AR-4:
        automat nie wybiera między kopiami i nie przegłosowuje ręki).
    Zeznanie już identyczne (`raw_json` i pola gorące bez zmian) → `'unchanged'`, ZERO zapisu i ZERO
    eventu (idempotencja: drugi przebieg nie dopisuje dziennika). WYJĄTEK RĘKI (aktor `user:*`):
    wybór kopii, która już mówi, jest faktem człowieka - `header.adopted` z `changed: {}`
    i `confirmed: True`, bez przepisania treści, zwrot `'confirmed'`; gdy najnowszy zapis zeznania
    to już ręka na tej lokacji i tym odcisku → `'unchanged'` bez zdarzenia.

    Ślad: `event(header.adopted)` na `frame:` z payloadem „skąd → dokąd": `location_id`, `path`
    i odcisk przejmującej kopii oraz `{pole: {before, after}}` pól gorących, które zmieniły wartość.
    `actor` idzie do każdego eventu przejęcia (etap i gest ręki mają się w dzienniku odróżniać).

    `inplace_gen` (astra, 2026-09-27) - generacja dziennika zapisu w miejscu z odczytu wołającego
    (kontrakt jak w `refresh_location`): operacja tej lokacji o większym `id` → `StaleScanRecord`
    w tej transakcji, zero zapisu. Kotwica odcisku sama tego nie łapie - zapis w miejscu przed
    re-synciem zostawia w bazie stary odcisk, a odczyt sprzed zapisu niesie ten sam.

    DOKOŃCZENIE ZAPISU WSTRZYMANEGO (AR-82): przejęcie, potwierdzenie i zeznanie już zgodne to
    dowód, że zeznanie klatki opisuje plik tej kopii - w tej samej transakcji rozliczają się otwarte
    wstrzymania lokacji (`_settle_withheld_tx`). Tak gest „Ta kopia prowadzi” i etap Dostawy
    dokańczają zapis karty, którego zeznanie zostało przy innej kopii.

    ZWRACA `'adopted'` | `'confirmed'` | `'unchanged'` | `'drift'` | `'raced'`."""
    with _immediate(con):
        werdykt, frame_id = _adopt_testimony_tx(
            con, location_id=location_id, sha1_data=sha1_data, header_hash=header_hash,
            raw_json=raw_json, cards=cards, hot_fields=hot_fields, camera_id=camera_id, kind=kind,
            now=now, actor=actor, inplace_gen=inplace_gen, expected_frame_id=expected_frame_id)
        if werdykt in ("adopted", "confirmed", "unchanged"):
            _settle_withheld_tx(con, location_id=location_id, frame_id=frame_id,
                                sha1_data=sha1_data, header_hash=header_hash, testimony_ok=True,
                                now=now, actor=actor)
    return werdykt


def _adopt_testimony_tx(con, *, location_id, sha1_data, header_hash, raw_json, cards, hot_fields,
                        camera_id, kind, now, actor, inplace_gen, expected_frame_id):
    """Ciało `adopt_testimony` w jego transakcji → `(werdykt, frame_id)`; kontrakt tam."""
    hot = dict(hot_fields or {})
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
    frame_id = loc["frame_id"]
    if not loc["present"] or header_hash is None or loc["header_hash"] != header_hash:
        return "drift", frame_id
    if expected_frame_id is not None and frame_id != expected_frame_id:
        return "raced", frame_id
    if not str(actor).startswith("user:"):
        obecne = con.execute("SELECT count(*) FROM location WHERE frame_id = ? AND present = 1",
                             (frame_id,)).fetchone()[0]
        if obecne != 1 or hand_lead_location(con, frame_id) is not None:
            return "raced", frame_id
    before = con.execute(
        "SELECT raw_json, date_obs, exptime, filter_raw, instrume, telescop, focallen, "
        "focratio_raw, xpixsz, ypixsz, gain, offset_adu, ccd_temp, usblimit, xbinning, "
        "ybinning, bayerpat, ra_deg, dec_deg, object_raw FROM header WHERE frame_id = ?",
        (frame_id,)).fetchone()
    changed = {k: {"before": None if before is None else before[k], "after": hot.get(k)}
               for k in _HEADER_HOT
               if (None if before is None else before[k]) != hot.get(k)}
    # „Zeznanie już identyczne” = ten sam dowód co sukces zapisu karty (`testimony_matches`:
    # `raw_json`, pola gorące i lustro `cards`) - rozjechane `cards` przy tym samym `raw_json` to
    # zeznanie do przepisania, nie „bez zmian”.
    if before is not None and testimony_matches(con, frame_id=frame_id, raw_json=raw_json,
                                                hot_fields=hot, cards=cards):
        if not str(actor).startswith("user:"):
            return "unchanged", frame_id
        # WYBÓR RĘKI KOPII, KTÓRA JUŻ MÓWI: treść bez zmian, ale werdykt człowieka jest faktem
        # (AR-4) - bez zdarzenia zeznanie zostałoby „z automatu" i pierwszy przebieg etapu albo
        # odświeżenie innej kopii przestawiłoby je bez pytania. Strażnik idempotencji: najnowszy
        # zapis zeznania tej klatki to już ręka wskazująca TĘ lokację i TEN odcisk → zero
        # zdarzenia. Literał czasowników jak w `gui.queries.hand_testimony_frame_ids`.
        ostatni = con.execute(
            "SELECT actor, verb, json_extract(payload, '$.location_id') AS lid, "
            "       json_extract(payload, '$.header_hash') AS hh "
            "FROM event WHERE target = ? "
            "  AND verb IN ('header.recorded', 'header.refreshed', 'header.adopted') "
            "ORDER BY id DESC LIMIT 1", (f"frame:{frame_id}",)).fetchone()
        if (ostatni is not None and ostatni["verb"] == "header.adopted"
                and str(ostatni["actor"]).startswith("user:")
                and ostatni["lid"] == location_id and ostatni["hh"] == header_hash):
            return "unchanged", frame_id
        emit_event(con, actor=actor, verb="header.adopted", target=f"frame:{frame_id}",
                   now=now, payload={"location_id": location_id, "path": loc["path"],
                                     "header_hash": header_hash, "changed": {},
                                     "confirmed": True})
        return "confirmed", frame_id
    _rewrite_testimony(
        con, frame_id=frame_id, raw_json=raw_json, cards=cards, hot_fields=hot,
        camera_id=camera_id, kind=kind, now=now, actor=actor, verb="header.adopted",
        payload={"location_id": location_id, "path": loc["path"], "header_hash": header_hash,
                 "changed": changed})
    return "adopted", frame_id


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
      * faktów jeszcze nie ma (`hdr_hash IS NULL`) ALBO zebrano je regułą koercji starszą niż ta,
        którą niesie zapis (`hdr_rule` NULL albo mniejszy - 0025, AR-33). Uzupełnienie nie nadpisuje
        tego, co skan zebrał regułą bieżącą (ani nowszą - binarka starsza od bazy niczego nie cofa).
    Ta sama para chroni przed wyścigiem z równoległym skanem (WAL - GUI i CLI naraz).

    Ślad: `location.refreshed` z `{pole: {before, after}}` - ten sam kształt, którym `refresh_location`
    opisuje każdą inną zmianę faktów kopii, a `actor` odróżnia drogę w dzienniku. Przy dociągnięciu
    po zmianie reguły payload niesie przejście `hdr_rule` i dokładnie te pola, które nowy rzut zmienił.

    ZWRACA bool: `True` = zapisano; `False` = odmowa kotwicy (odcisk inny albo fakty bieżącej reguły
    już są) - wtedy ZERO UPDATE i ZERO eventu.

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
            "hdr_telescop, hdr_instrume, hdr_exptime, hdr_xbinning, hdr_date_obs, hdr_hash, "
            "hdr_rule FROM location WHERE id = ?", (location_id,)).fetchone()
        if row is None:
            raise ValueError(f"location:{location_id} nie istnieje")
        _refuse_if_newer_inplace(con, location_id, inplace_gen)
        do_dociagniecia = copy_facts_state(row["hdr_hash"], row["hdr_rule"],
                                           rule=cf["hdr_rule"]) == FAKTY_DO_DOCIAGNIECIA
        if not do_dociagniecia or row["header_hash"] != cf["hdr_hash"]:
            return False
        changed = {k: {"before": row[k], "after": cf[k]} for k in COPY_FACTS if row[k] != cf[k]}
        con.execute(
            "UPDATE location SET image_count = ?, image_roles = ?, hdr_filter = ?, "
            "hdr_imagetyp = ?, hdr_object = ?, hdr_telescop = ?, hdr_instrume = ?, "
            "hdr_exptime = ?, hdr_xbinning = ?, hdr_date_obs = ?, hdr_hash = ?, hdr_rule = ? "
            "WHERE id = ? AND header_hash = ? "
            "  AND (hdr_hash IS NULL OR hdr_rule IS NULL OR hdr_rule < ?)",
            (*(cf[k] for k in COPY_FACTS), location_id, cf["hdr_hash"], cf["hdr_rule"]))
        emit_event(con, actor=actor, verb="location.refreshed",
                   target=f"location:{location_id}", now=now, payload=changed)
    return True


def flag_copy_facts_summary(con, summary, now, actor="backfill:copies"):
    """Przebieg uzupełnienia faktów kopii ZBIORCZO (AR-32) - JEDEN `event(location.copy_facts_summary)`
    na przebieg `scan.backfill_copy_facts`, obok per-lokacyjnych `location.refreshed` z
    `record_copy_facts`. Kanon operacji masowej (`backfill_filter_canon`, `flag_*_review_summary`)
    mówi o jednym zdarzeniu zbiorczym; per-lokacyjne zostają, bo tylko one niosą `{before, after}`
    pól jednej kopii. Zbiorcze niesie to, czego nie ma żaden ślad per kopia: odmowy (`stale`,
    `missing`, `failed`, `elsewhere`, `raced`) ze ścieżkami, `remaining` i przerwanie - raport
    przebiegu ma w dzienniku jedno źródło.

    `summary` = słownik pól `scan.CopyFactsSummary` (wołający podaje `dataclasses.asdict`; repo nie
    importuje `scan`). Audyt, NIE zapis stanu. Przebieg bez kandydatów (`rows == 0`) → ZERO eventu:
    powtórne wywołanie jest no-opem także w dzienniku (wzorzec `backfill_filter_canon`)."""
    if not summary["rows"]:
        return
    with _tx(con):
        emit_event(con, actor=actor, verb="location.copy_facts_summary", target="location:*",
                   now=now, payload=dict(summary))


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
    NIE „stała się nieczytelna po byciu czytelną". Ustawia go re-odczyt ZNANEJ ścieżki (tu) albo już
    pierwszy odczyt nowej kopii (`add_location`, P4-7), więc kubełek `unreadable` jest ten sam przy
    bramie ON i OFF.

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
    with _tx(con):  # atomowo: INSERT header + INSERT cards + INSERT event
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
    with _tx(con):
        emit_event(con, actor=actor, verb="frame.review", target=f"sha1:{sha1}", now=now,
                   reason=reason, payload={"path": path})


def flag_camera_review(con, *, frame_id, reason, now, actor="scan"):
    """Frame powstał (tożsamość sha1 jest), ale osi KAMERA nie dało się złożyć (brak INSTRUME/XPIXSZ
    — np. Sony master flat) → `event(camera.review)`. `camera_id` zostaje NULL; nie zgadujemy."""
    with _tx(con):
        emit_event(con, actor=actor, verb="camera.review", target=f"frame:{frame_id}", now=now,
                   reason=reason)


def flag_kind_unmapped(con, *, frame_id, imagetyp, now, actor="scan"):
    """IMAGETYP niepuste, lecz niezmapowane przez `normalize_kind` (kind=unknown) → sygnał do
    rozszerzenia mapy (`event(kind.unmapped)`). Firsthand 2600 się nie zdarza; mechanizm ma być."""
    with _tx(con):
        emit_event(con, actor=actor, verb="kind.unmapped", target=f"frame:{frame_id}", now=now,
                   payload={"imagetyp": imagetyp})


class Made(str, Enum):
    """Wynik założenia osi (`propose_telescope`, `upsert_object`, `_upsert_object_tx`, 0040): nowy
    wiersz, nagrobek przywrócony do osi, wiersz już żywy. Trzy stany, nie bool - wskrzeszony nagrobek
    nie jest „nowym obiektem” w liczniku przebiegu, a ślad gestu (`made_object_id`) musi go znać.

    `str` (porównanie z `"created"` działa), a `bool()` rzuca `TypeError` (EXPECT): dawny kontrakt
    był boolem „nowy wiersz”, więc wołający z `if created:` albo `sum(...)` liczyłby `EXISTING` jako
    nowy - po cichu. Niech pada głośno."""
    CREATED = "created"
    UNRETIRED = "unretired"
    EXISTING = "existing"

    def __bool__(self):
        raise TypeError(f"wynik założenia osi {self.value!r} nie jest prawdą logiczną - porównaj "
                        "z `Made.CREATED`/`Made.UNRETIRED`/`Made.EXISTING`")


def propose_telescope(con, *, telescop_canon, f_ratio_nominal=None, focal_nominal=None,
                      member_count=None, now, actor="grouper"):
    """Wyłoń teleskop (oś) z nagłówków — `status='proposed'`, `label=NULL` (etykieta/scalanie =
    GUI usera). Tożsamość = `telescop_canon` (TELESCOP.strip(); po naprawie nagłówków 100%,
    8 nazw × 1 ogniskowa — brief §3). Idempotentny po canonie: SELECT po kolumnie
    `UNIQUE COLLATE NOCASE` — to JEDYNY mechanizm foldowania wielkości liter (R2#8; grouper NIE
    folduje w Pythonie); casing wyświetlany = pierwszego wystąpienia. `f_ratio_nominal`/
    `focal_nominal` to nullable WŁAŚCIWOŚCI (audyt/wyświetlanie), nie klucz.

    → `(id, wynik)`, `wynik` ∈ `Made`: `EXISTING` (żywy wiersz, bez eventu), `CREATED` (INSERT +
    `event(telescope.proposed)`), `UNRETIRED` (nazwa należała do nagrobka - wiersz wraca do osi
    z polami ręki sprzed nagrobka + `event(telescope.unretired)`, 0040). Nagrobek nie jest „nowym
    teleskopem” dla licznika przebiegu i nie dostaje drugiego `proposed` (parytet wiersz == proposed).

    WSKRZESZENIE ROZSTRZYGA WARUNKOWY `UPDATE` (`_unretire_telescope_tx`: `WHERE retired_at IS NOT
    NULL`, wynik z `rowcount`), nie odczyt sprzed transakcji: dwóch pisarzy, którzy obaj widzieli
    nagrobek, nie wskrzesi go dwa razy - drugi dostaje `EXISTING` bez zdarzenia. Transakcja `with
    con:` jak dotąd (nie `_immediate`): wołający z otwartą niejawną transakcją (fixture'y z gołym
    SQL-em) nie dostaje „transakcja w transakcji”."""
    canon = str(telescop_canon).strip()
    if not canon:
        raise ValueError("telescop_canon pusty — brak TELESCOP to config.review, nie oś")
    row = con.execute(
        "SELECT id, retired_at FROM telescope WHERE telescop_canon = ?", (canon,)).fetchone()
    if row is not None and row["retired_at"] is None:
        return row[0], Made.EXISTING
    with con:
        if row is not None:
            if _unretire_telescope_tx(con, telescope_id=row[0], now=now, actor=actor,
                                      payload={"telescop_canon": canon,
                                               "member_count": member_count}):
                return row[0], Made.UNRETIRED
            return row[0], Made.EXISTING
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
    return telescope_id, Made.CREATED


def _unretire_telescope_tx(con, *, telescope_id, now, actor, payload):
    """Pod transakcją wołającego: nagrobek teleskopu wraca do osi (`retired_at` NULL) +
    `event(telescope.unretired)` → `True`; wiersz już żywy → `False` bez zdarzenia (wynik
    z `rowcount` warunkowego `UPDATE`, nie z wcześniejszego odczytu). Pola ręki zostają, jakie były -
    nagrobek ich nie zerował."""
    if con.execute("UPDATE telescope SET retired_at = NULL WHERE id = ? AND retired_at IS NOT NULL",
                   (telescope_id,)).rowcount != 1:
        return False
    emit_event(con, actor=actor, verb="telescope.unretired", target=f"telescope:{telescope_id}",
               now=now, payload=payload)
    return True


def _unretire_object_tx(con, *, object_id, canon, now, actor):
    """Pod transakcją wołającego: nagrobek obiektu wraca do osi + `event(object.unretired)` →
    `True`; obiekt już żywy → `False` bez zdarzenia (`rowcount` warunkowego `UPDATE`).

    WYŁĄCZNIE PRZY KANONIE NADAL KANONICZNYM: kanon, który jest dziś kluczem pary `catalog_xref`
    (`M33` po dopisaniu `M33 → NGC598`), nazywa cel pary, nie siebie - wskrzeszenie przywróciłoby
    starą tożsamość obok celu. Wołający, który przyniósł taki kanon, ominął przekierowanie drabiny
    (`queries.object_target`, resolver) → `ValueError`, zero zapisu (EXPECT)."""
    if con.execute("SELECT 1 FROM object WHERE id = ? AND retired_at IS NOT NULL",
                   (object_id,)).fetchone() is None:
        return False                                  # żywy - strażnik pary go nie dotyczy
    cel = xref(canon)
    if cel != canon:
        raise OdmowaZPowodem(PowodPozycji(
            f"obiekt '{canon}' to nagrobek, a jego kanon prowadzi dziś przez parę katalogową do "
            f"'{cel}' - nagrobka nie wskrzeszam, celem jest '{cel}'", "retired_via_xref",
            canon=canon, target=cel))
    if con.execute("UPDATE object SET retired_at = NULL WHERE id = ? AND retired_at IS NOT NULL",
                   (object_id,)).rowcount != 1:
        return False
    emit_event(con, actor=actor, verb="object.unretired", target=f"object:{object_id}", now=now,
               payload={"canon": canon})
    return True


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

    Ręka nadpisuje ręką przez `user_assign_config(overwrite=True)` - świadomym drugim gestem.

    PRZEPIĘCIE EMITUJE PARĘ VERBÓW (`config.unassigned` + `config.assigned`, wzorem `assign_object`
    i ręcznej gałęzi `user_assign_config`), payload odpięcia niesie stan SPRZED. Bez pary parytet
    `audit.entity_event_parity` zawyżał lewą stronę o każde przepięcie na zawsze (event jest
    append-only) - tak powstał historyczny dług dziennika liczony tam członem `legacy`. Przepięcia
    przebiegu są realne: rozdział soczewek RAW (`grouper._soczewki_raw`) przenosi klatki na nowy
    teleskop właśnie tą drogą."""
    row = con.execute(
        "SELECT config_id, config_source FROM frame WHERE id = ?", (frame_id,)).fetchone()
    if row is not None and row["config_source"] in STICKY_CONFIG_SOURCES:
        return False
    if row is not None and row["config_id"] == config_id:
        return False

    with con:
        con.execute("UPDATE frame SET config_id = ? WHERE id = ?", (config_id, frame_id))
        if row is not None and row["config_id"] is not None:   # PRZEPIĘCIE - ślad zostaje
            emit_event(con, actor=actor, verb="config.unassigned", target=f"frame:{frame_id}",
                       now=now, payload={"config_id": row["config_id"],
                                         "config_source": row["config_source"]},
                       reason="przebieg przepina klatkę na inny zestaw")
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
    """`frame.config_id` nierozstrzygalny (brak teleskopu/kamery/focratio - np. master bez FOCRATIO,
    W4) → `event(config.review)`. config_id zostaje NULL; ZERO cichego NULL (każdy ma powód).

    ZDARZENIE TYLKO PRZY WEJŚCIU DO KOLEJKI (AR-88). Przebieg pyta o każdą klatkę bez osi przy każdej
    Dostawie, a dziennik jest append-only - bezwarunkowa emisja dopisywała 424 zdarzenia na przebieg
    bez żadnej zmiany danych. Wejście = klatka nie ma jeszcze `config.review` w BIEŻĄCYM epizodzie,
    czyli późniejszego niż jej ostatnie `config.assigned` albo `config.unassigned` (każde z nich
    zmienia oś, więc otwiera nowy epizod). Idempotentny jak `assign_config`: powód już zapisany →
    False bez eventu; inaczej event i True. Bramka stoi w klindze, nie w pętli groupera, żeby
    obejmowała każdego wołającego.

    Konsumenci liczą ze STANU albo po DISTINCT target (`resolver.review_state`, akceptacja §5.6),
    więc żaden licznik nie drgnie. `audit.config_review_reason_gap` (AR-65) mierzy epizod od
    ostatniego `config.assigned` - granica tej bramki nie jest od niej wcześniejsza, więc pominięty
    event zawsze ma w dzienniku powód, który ta formuła widzi."""
    target = f"frame:{frame_id}"
    if con.execute(
            "SELECT 1 FROM event e WHERE e.verb = 'config.review' AND e.target = ? "
            "AND e.id > COALESCE((SELECT max(a.id) FROM event a "
            "                     WHERE a.verb IN ('config.assigned', 'config.unassigned') "
            "                     AND a.target = ?), 0) LIMIT 1",
            (target, target)).fetchone() is not None:
        return False
    with con:
        emit_event(con, actor=actor, verb="config.review", target=target, now=now, reason=reason)
    return True


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

    @property
    def skipped(self):
        """Suma pominięć - do zdania „przypisano N z M"; liczona Z ROZBICIA, więc człon dołożony do
        `skipped_breakdown` wchodzi do „z M" i do zdania naraz (lekcja `ObjectGesture`)."""
        return sum(n for _, n in self.skipped_breakdown)

    @property
    def skipped_breakdown(self):
        """Rozbicie pominięć jako [(sufiks klucza i18n, n)] - JEDEN właściciel kolejności i składu.
        Do R-S2b-15 sumę i wyliczankę trzymał wołający w GUI, a zdanie drukowało zera."""
        return [("occupied", self.occupied), ("no_camera", self.no_camera),
                ("kind", self.kind_skip), ("unchanged", self.unchanged)]


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
    from .grouper import NO_TELESCOPE_KINDS, refresh_all_optics

    g = ConfigGesture()
    # `atomic`, nie samo `_immediate` (bramka kodu T24, N2): odświeżenie wartości z plików teleskopu
    # źródłowego i docelowego (`refresh_all_optics` → `_tx`) musi dołączyć do TEJ transakcji - goły
    # `with con:` w środku `_immediate` zatwierdziłby gest w połowie.
    with atomic(con):
        cel = con.execute("SELECT retired_at FROM telescope WHERE id = ?",
                          (telescope_id,)).fetchone()
        if cel is None:
            raise ValueError(f"telescope:{telescope_id} nie istnieje")
        if cel["retired_at"] is not None:
            raise ValueError(f"telescope:{telescope_id} to nagrobek - klatek mu nie przypisuję")
        actor = f"user:{uid}"
        zrodla = set()                           # teleskopy, z których klatki wyszły (N2)
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
                zrodla.add(con.execute("SELECT telescope_id FROM config WHERE id = ?",
                                       (fr["config_id"],)).fetchone()[0])
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
        # WARTOŚĆ Z PLIKÓW teleskopu docelowego i źródłowych idzie za klatkami w tej samej transakcji
        # (bramka kodu T24, N2): bez tego Oś i kubełki mówiły modą sprzed przepięcia do najbliższej
        # Dostawy. Jedna derywacja (`grouper.refresh_all_optics`), zdarzenie tylko przy zmianie.
        if g.assigned:
            refresh_all_optics(con, now, actor=actor, telescope_ids={telescope_id} | zrodla)
    return g


# ============================================================ oś OBIEKT + filtr (§Etap 6)

def upsert_object(con, *, canon, catalog, kind, now, actor="resolver"):
    """Wyłoń obiekt (oś) z rozwiązania `object_raw`. Tożsamość = `canon` (UNIQUE, NGC-wins).
    → `(id, wynik)`, `wynik` ∈ `Made`: żywy → `EXISTING` bez eventu; nowy → INSERT +
    `event(object.upserted)` w tej samej transakcji, `CREATED`; nagrobek (0040) → wraca do osi +
    `event(object.unretired)`, `UNRETIRED` (strażnik kanonu: `_unretire_object_tx`). Obiekty
    wyłaniają się z realnych nagłówków (jak kamery), nie a priori. Wskrzeszenie rozstrzyga
    warunkowy `UPDATE` z `rowcount` (`_unretire_object_tx`) - jak w `propose_telescope`: dwóch
    pisarzy nie wskrzesi jednego nagrobka dwa razy."""
    row = con.execute("SELECT id, retired_at FROM object WHERE canon = ?", (canon,)).fetchone()
    if row is not None and row["retired_at"] is None:
        return row[0], Made.EXISTING
    with con:  # atomowo: INSERT/wskrzeszenie + event
        if row is not None:
            if _unretire_object_tx(con, object_id=row[0], canon=canon, now=now, actor=actor):
                return row[0], Made.UNRETIRED
            return row[0], Made.EXISTING
        cur = con.execute(
            "INSERT INTO object(canon, catalog, kind) VALUES (?, ?, ?)", (canon, catalog, kind))
        object_id = cur.lastrowid
        emit_event(con, actor=actor, verb="object.upserted", target=f"object:{object_id}",
                   now=now, payload={"canon": canon, "catalog": catalog, "kind": kind})
    return object_id, Made.CREATED


class AliasWrite(NamedTuple):
    """Wynik `add_object_alias`. `conflict_object_id` niepuste = nazwa należy do INNEGO obiektu
    (zero zapisu) - wołający dostaje konflikt wprost, zamiast cichego „już jest” (AR-135)."""
    alias_id: int
    created: bool
    conflict_object_id: int | None


def add_object_alias(con, *, alias_norm, object_id, source, now, actor="resolver"):
    """Zapisz równoważność `alias_norm` → obiekt (audyt „M106 ≡ NGC4258 via catalog_xref"). Po
    `UNIQUE(alias_norm)`: znana przy TYM obiekcie → `(id, False, None)` bez eventu (idempotencja);
    nowa → INSERT + `event(object.aliased)`; `(id, True, None)`. Znana przy INNYM obiekcie →
    `(id, False, id_tamtego_obiektu)` bez zapisu i bez eventu: KONFLIKT należy do wołającego,
    który zbiera go po unikalnej parze i zgłasza stan raz na przebieg (`resolver`,
    `flag_object_alias_conflict_state`) - zdarzenie per wołanie byłoby historią bez końca, bo
    przebieg woła tę funkcję per klatka. `source` ∈ `resolve.objects.ALIAS_SOURCES` - JEDEN
    właściciel enumu; wyliczanka w tym docstringu rozjeżdżała się z DDL-em o `review`, a DDL
    `frame.object_source` rozjeżdżał się z żywą bazą o cztery wartości. `region` w tym zbiorze
    NIE występuje ŚWIADOMIE: kompleks rozpoznaje się ze WSPÓŁRZĘDNYCH, więc nie ma nazwy do
    zapisania jako równoważność (zob. `resolve/regions.py`)."""
    row = con.execute("SELECT id, object_id FROM object_alias WHERE alias_norm = ?",
                      (alias_norm,)).fetchone()
    if row is not None:
        return AliasWrite(row[0], False, None if row[1] == object_id else row[1])

    with con:  # atomowo: INSERT object_alias + INSERT event
        cur = con.execute(
            "INSERT INTO object_alias(alias_norm, object_id, source) VALUES (?, ?, ?)",
            (alias_norm, object_id, source))
        alias_id = cur.lastrowid
        emit_event(con, actor=actor, verb="object.aliased", target=f"object:{object_id}",
                   now=now, payload={"alias_norm": alias_norm, "source": source})
    return AliasWrite(alias_id, True, None)


class AliasRebind(NamedTuple):
    """Wynik `rebind_object_alias`: czy równoważność przeszła do celu i ile klatek poszło za nią."""
    rebound: bool
    frames: int


def rebind_object_alias(con, *, alias_norm, object_id, expected_object_id, now,
                        actor="resolver"):
    """Przepnij równoważność `alias_norm` z `expected_object_id` na `object_id` RAZEM z klatkami,
    które dostały obiekt z tej równoważności - nazwa, która jest kluczem pary `catalog_xref`, idzie
    do CELU pary (AR-135: para dopisana po fakcie zostawiała alias przy starym obiekcie, a klatki
    z nagłówka szły już do celu). JEDNA transakcja `_immediate`: UPDATE aliasu (`source` staje się
    `catalog_xref`, bo to para niesie teraz równoważność) + `object.alias_rebound` (stan sprzed),
    potem każda klatka `object_source='alias'` starego obiektu, której zeznanie `OBJECT` jest tą
    nazwą, z parą `object.unassigned`/`object.assigned` - jak `assign_object`. Awaria w połowie
    cofa WSZYSTKO: osobne transakcje zostawiały alias przy celu, a klatki przy starym obiekcie na
    zawsze (następny przebieg mija alias, który już wskazuje cel). Liczność aliasów się nie zmienia,
    więc parytet `§5.9` zostaje domknięty.

    CAS W `WHERE`, nie w odczycie przed transakcją: alias przechodzi tylko, gdy nadal wskazuje
    `expected_object_id` i nie jest ręki; klatka - gdy nadal ma stary obiekt ze źródłem `alias`.
    Zwraca `AliasRebind(False, 0)` bez zapisu, gdy: aliasu nie ma, wskazuje inny obiekt, ma
    `source='user'` albo cel jest NAGROBKIEM (0040) lub go nie ma. RĘKA ZOSTAJE: równoważność
    nauczona gestem i klatka ręki są zeznaniem człowieka - wołający zgłasza je jako konflikt, ta
    klinga ich nie rusza także wtedy, gdy wołający przefiltrował źle. Alias na nagrobku przypinałby
    do niego klatki szczeblem aliasu przebiegu, więc nagrobek celem nie jest."""
    with _immediate(con):
        cel = con.execute("SELECT retired_at FROM object WHERE id = ?", (object_id,)).fetchone()
        row = con.execute(
            "SELECT id, source FROM object_alias "
            "WHERE alias_norm = ? AND object_id = ? AND source != 'user'",
            (alias_norm, expected_object_id)).fetchone()
        if cel is None or cel["retired_at"] is not None or row is None:
            return AliasRebind(False, 0)
        if con.execute(
                "UPDATE object_alias SET object_id = ?, source = 'catalog_xref' "
                "WHERE id = ? AND object_id = ? AND source != 'user'",
                (object_id, row["id"], expected_object_id)).rowcount != 1:
            return AliasRebind(False, 0)
        emit_event(con, actor=actor, verb="object.alias_rebound", target=f"object:{object_id}",
                   now=now, payload={"alias_norm": alias_norm, "source": row["source"],
                                     "object_id": expected_object_id,
                                     "next_object_id": object_id},
                   reason="nazwa jest kluczem pary catalog_xref - równoważność idzie do celu pary")
        klatki = 0
        for f in con.execute(
                "SELECT f.id AS fid, h.object_raw AS raw FROM frame f "
                "JOIN header h ON h.frame_id = f.id "
                "WHERE f.object_id = ? AND f.object_source = 'alias' ORDER BY f.id",
                (expected_object_id,)).fetchall():
            if f["raw"] is None or norm_alnum(str(f["raw"])) != alias_norm:
                continue
            if con.execute(
                    "UPDATE frame SET object_id = ? "
                    "WHERE id = ? AND object_id = ? AND object_source = 'alias'",
                    (object_id, f["fid"], expected_object_id)).rowcount != 1:
                continue
            emit_event(con, actor=actor, verb="object.unassigned", target=f"frame:{f['fid']}",
                       now=now, payload={"object_id": expected_object_id, "object_source": "alias"},
                       reason="równoważność nazwy przepięta do celu pary catalog_xref")
            emit_event(con, actor=actor, verb="object.assigned", target=f"frame:{f['fid']}",
                       now=now, payload={"object_id": object_id, "object_source": "alias"})
            klatki += 1
    return AliasRebind(True, klatki)


def flag_object_alias_conflict_state(con, items, now, actor="resolver"):
    """STAN konfliktów nazw osi obiektu po przebiegu - JEDNO zdarzenie
    `object.alias_conflict_state` z pełną listą, emitowane WYŁĄCZNIE przy zmianie stanu wobec
    ostatniego takiego zdarzenia (AR-135). `items` = `[alias_norm, object_id_zajmujący,
    kanon_oczekiwany]`: nazwa, którą drabina daje dziś obiektowi `kanon_oczekiwany`, a równoważność
    w bazie wiąże z innym. Kolejny przebieg z tym samym stanem jest ciszą; zejście do pustej listy
    jest zmianą i niesie `count: 0` (konflikt rozstrzygnięty). Zwraca True, gdy zdarzenie poszło.

    RAPORT, NIE ZAPIS - jak `flag_object_alias_conflicts`: rozstrzyga człowiek (wiersz Porządków
    „Nazwa katalogowa wskazuje inny obiekt”, `gui.queries.xref_reconcile_rows`)."""
    stan = sorted([str(a), int(o), str(c)] for a, o, c in items)
    row = con.execute(
        "SELECT payload FROM event WHERE verb = 'object.alias_conflict_state' "
        "ORDER BY id DESC LIMIT 1").fetchone()
    bylo = json.loads(row[0])["items"] if row is not None and row[0] else []
    if stan == bylo:
        return False
    with con:
        emit_event(con, actor=actor, verb="object.alias_conflict_state", target="object:*",
                   now=now, payload={"count": len(stan), "items": stan},
                   reason="nazwa wskazuje w bazie inny obiekt niż drabina nazwy")
    return True


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
    `filter.backfilled`. `items` = lista `(frame_id, filter_canon)` - kanon albo `None` (świadomy
    brak: nagłówek nie zeznaje filtra, W2, bez review). Zwraca liczbę REALNIE zmienionych wierszy.

    `None` ZERUJE (AR-2, AR-22 (1)). Pochodna ma się dać przeliczyć w obie strony, jak
    `backfill_frame_channel`: zeznanie przejęte z ocalałej kopii bez karty `FILTER` (albo z kartą
    `NoFilter`) zostawiało kanon kopii skasowanej, bo klinga brała wyłącznie kanon niepusty - oś
    mówiła co innego niż zapisany nagłówek (15656: `L-Pro` przy `NoFilter`). Ręki ta kolumna nie
    zna (jedyny pisarz to przebieg), więc zerowanie nie przegłosowuje niczyjego werdyktu.

    IDEMPOTENTNY (D-0722-1): `WHERE filter_canon IS NOT ?` odsiewa wiersze, które już mają ten
    kanon (`IS NOT` obsługuje NULL — pierwszy backfill przechodzi), a `count` w payloadzie to suma
    `cur.rowcount`, czyli SKUTEK, nie rozmiar wejścia. Zero zmian → ZERO eventu, jak reszta repo
    (`assign_object`, `flag_object_review_summary`). Wcześniej `UPDATE` leciał bezwarunkowo dla
    każdego itemu, a `count = len(items)` — powtórny resolve dopisywał identyczny event z licznikiem
    całej populacji (na `horreum_pf4.db` 7× `count: 12582` przy zerze zmian).

    Wyzerowania niosą w payloadzie `cleared` = `[[frame_id, było]]` (klucz tylko, gdy są): kanonu
    sprzed nie da się odtworzyć z nagłówka, który już go nie zeznaje, więc dziennik jest jedynym
    miejscem, gdzie przetrwa."""
    items = list(items)
    if not items:
        return 0
    with con:
        changed = 0
        wyzerowane = []
        for frame_id, filter_canon in items:
            if filter_canon is None:
                bylo = con.execute(
                    "SELECT filter_canon FROM frame WHERE id = ?", (frame_id,)).fetchone()
                if bylo is None or bylo[0] is None:
                    continue
                wyzerowane.append([frame_id, bylo[0]])
            cur = con.execute(
                "UPDATE frame SET filter_canon = ? WHERE id = ? AND filter_canon IS NOT ?",
                (filter_canon, frame_id, filter_canon))
            changed += cur.rowcount
        if changed:
            payload = {"count": changed}
            if wyzerowane:
                payload["cleared"] = wyzerowane
            emit_event(con, actor=actor, verb="filter.backfilled", target="frame:*", now=now,
                       payload=payload)
    return changed


def backfill_frame_channel(con, items, now, actor="resolver"):
    """Kolumna POCHODNA `frame.channel` (0028, P4-3) ZBIORCZO: jedna transakcja + JEDEN event
    `channel.backfilled` na przebieg - kanon `backfill_filter_canon`. `items` = `(frame_id, kanał)`
    dla KAŻDEJ klatki, której kanał przebieg policzył, także `None`: pochodna ma się dać przeliczyć
    w obie strony (kopia przemianowana bez kanału w nazwie zdejmuje fakt, który wcześniej niosła).

    IDEMPOTENTNY: `WHERE channel IS NOT ?` odsiewa wiersze bez zmiany, licznik w payloadzie to SKUTEK
    (`rowcount`), zero zmian → zero eventu. Payload niesie też listę `[frame_id, było, jest]` zmian -
    pochodna liczona z nazwy pliku jest odwracalna wyłącznie wtedy, gdy dziennik pamięta stan PRZED
    (rename potrafi zmienić nazwę, a z nią kanał). Wartość spoza słownika → `ValueError` (EXPECT),
    zanim cokolwiek się zapisze; CHECK 0028 jest drugą linią obrony. Zwraca liczbę zmienionych."""
    items = list(items)
    if not items:
        return 0
    zle = [k for _f, k in items if k is not None and k not in CHANNELS]
    if zle:
        raise ValueError(f"kanał spoza słownika: {zle[0]!r}")
    with con:
        zmiany = []
        for frame_id, kanal in items:
            stary = con.execute("SELECT channel FROM frame WHERE id = ?", (frame_id,)).fetchone()
            if stary is None:
                raise ValueError(f"brak klatki {frame_id}")
            cur = con.execute("UPDATE frame SET channel = ? WHERE id = ? AND channel IS NOT ?",
                              (kanal, frame_id, kanal))
            if cur.rowcount:
                zmiany.append([frame_id, stary[0], kanal])
        if zmiany:
            emit_event(con, actor=actor, verb="channel.backfilled", target="frame:*", now=now,
                       payload={"count": len(zmiany), "changes": zmiany})
    return len(zmiany)


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
    frame_ids: tuple = ()      # klatki REALNIE zapisane (przypisane albo cofnięte) - recepta odwrotu
                               # rusza wyłącznie je, nie całe zaznaczenie: klatka pominięta przez
                               # klingę niesie CUDZĄ, starszą decyzję, której ten gest nie podjął

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
            canons=tuple(kanony),
            frame_ids=self.frame_ids + inny.frame_ids)

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


def _object_target(con, canon, alias_norm):
    """Pod transakcją wołającego: `(object_id | None, alias_znany)` celu gestu ręki - obiekt po
    kanonie (None = jeszcze go nie ma) i czy `alias_norm` już jest w słowniku. Alias wskazujący INNY
    obiekt → `ValueError` (domyka pułapkę z `resolve/regions.py:18-22`), zero zapisu."""
    row = con.execute("SELECT id FROM object WHERE canon = ?", (canon,)).fetchone()
    object_id = row[0] if row is not None else None
    # Bez klucza nie ma czego sprawdzać ani zapisywać - gałąź aliasu milczy w CAŁOŚCI (nie
    # `SELECT … = NULL`, który po cichu zawsze zwraca pustkę i udawałby „alias wolny").
    existing = None if alias_norm is None else con.execute(
        "SELECT object_id FROM object_alias WHERE alias_norm = ?", (alias_norm,)).fetchone()
    if existing is not None and existing[0] != object_id:
        raise OdmowaZPowodem(PowodPozycji(
            f"alias '{alias_norm}' wskazuje już object:{existing[0]} - konflikt, zero zapisu",
            "alias_conflict", alias=alias_norm, object_id=existing[0]))
    return object_id, existing is not None


def _upsert_object_tx(con, *, canon, catalog, kind, alias_norm, actor, now):
    """Pod transakcją wołającego: obiekt celu gestu ręki (`INSERT object` + `object.upserted`, gdy
    kanonu nie ma; nagrobek wraca do osi - `_unretire_object_tx`) i alias wpisanej nazwy
    (`source='user'` + `object.aliased`, gdy nowy) → `(id obiektu, wynik ∈ Made, id aliasu
    założonego TERAZ albo None)` - dwa ostatnie to ślad nagrobka gestu (0040). JEDNO miejsce dla obu
    klingi ręki (`user_assign_object`, `user_override_object`) - druga kopia tej drabiny rozjechałaby
    się o pierwszy dopisany guard. Konflikt aliasu → `ValueError` PRZED pierwszym zapisem
    (`_object_target`)."""
    object_id, alias_znany = _object_target(con, canon, alias_norm)
    wynik = Made.EXISTING
    if object_id is None:
        cur = con.execute(
            "INSERT INTO object(canon, catalog, kind) VALUES (?, ?, ?)",
            (canon, catalog, kind))
        object_id = cur.lastrowid
        wynik = Made.CREATED
        emit_event(con, actor=actor, verb="object.upserted", target=f"object:{object_id}",
                   now=now, payload={"canon": canon, "catalog": catalog, "kind": kind})
    elif _unretire_object_tx(con, object_id=object_id, canon=canon, now=now, actor=actor):
        wynik = Made.UNRETIRED
    alias_id = None
    if alias_norm is not None and not alias_znany:
        alias_id = con.execute(
            "INSERT INTO object_alias(alias_norm, object_id, source) VALUES (?, ?, 'user')",
            (alias_norm, object_id)).lastrowid
        emit_event(con, actor=actor, verb="object.aliased", target=f"object:{object_id}",
                   now=now, payload={"alias_norm": alias_norm, "source": "user"})
    return object_id, wynik, alias_id


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
        actor = f"user:{uid}"
        object_id, _, _ = _upsert_object_tx(con, canon=canon, catalog=catalog, kind=kind,
                                            alias_norm=alias_norm, actor=actor, now=now)

        assigned = kind_skip = source_skip = drift = stacks = 0
        zapisane = []
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
            zapisane.append(frame_id)
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
                         canons=(canon,) if assigned else (), frame_ids=tuple(zapisane))


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
    kanony, cache, zapisane = [], {}, []
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
            zapisane.append(frame_id)
            stacks += fr["kind"] == "master_light"
    return ObjectGesture(assigned=cleared, skipped_kind=kind_skip,
                         skipped_source=source_skip, skipped_nothing=nothing_skip, stacks=stacks,
                         canons=tuple(kanony), frame_ids=tuple(zapisane))


@dataclass(frozen=True)
class ObjectOverride:
    """Jedno nadpisanie obiektu klatki ręką - materiał cofnięcia. `before` = `(object_id,
    object_source, object_cleared_id)` klatki sprzed gestu, odczytane pod blokadą zapisu;
    `object_id` = obiekt, który gest zapisał (źródło `user`); `reason` = gest (`release_object`,
    `object_change`) - trafia do pary verbów gestu i, z dopiskiem `_undo`, do pary jego cofnięcia.
    `made` (∈ `Made`) i `alias_id` = co gest założył PO DRODZE do tej klatki: obiekt nowy albo
    wskrzeszony i alias wpisanej nazwy - materiał śladu przebiegu, z którego cofnięcie zdejmuje
    nagrobkiem to, co gest założył (0040, `apply_object_change_item`)."""
    frame_id: int
    before: tuple
    object_id: int
    reason: str
    made: Made = Made.EXISTING
    alias_id: int | None = None


def user_override_object(con, *, frame_id, canon, expected, now, reason, catalog=None, kind=None,
                         alias_norm=None, uid="local", changes_out=None):
    """JAWNE NADPISANIE OBIEKTU KLATKI RĘKĄ - jedna klinga dla `LIGHT_KINDS` (light i stos), jedna
    transakcja `_immediate` → `'assigned'` · `'unchanged'` · `'drift'`. Gesty: „Przypisz obiekt
    wydania” po żniwach (AR-103, `reason='release_object'`) i „Zmień obiekt…” (AR-17 krok 3,
    `reason='object_change'` - przez `apply_object_change_item`, które w tej samej transakcji
    utrwala stan sprzed).

    DLACZEGO OSOBNA KLINGA: `user_assign_object` nie nadpisuje źródeł z pliku i geometrii
    (`header`/`alias`/`xref`/`region` - poza `WEAK_OBJECT_SOURCES`) ani ręki. Tamtej ochrony nie
    luzujemy: gest kubełka i paska Zbiorów dalej nie zamaluje faktu z pliku. Ta klinga robi to
    pojedynczo na klatce i wyłącznie przy stanie, który człowiek widział - a gest, który ją woła,
    zgadza z nią plik (karta i folder przy zmianie obiektu) albo stos z jego wydaniem.

    CAS NA PEŁNEJ TRÓJCE: `expected` = `(object_id, object_source, object_cleared_id)` z chwili
    podglądu (`stacks.release_object_check`, plan zmiany obiektu), porównane dosłownie (także
    `None`). Sama para obiekt+źródło przeżywa sekwencję „nagrobek X → przypisz Y → zdejmij Y” (znów
    `NULL`/`user_cleared`, ale o INNYM przedmiocie) - bez trzeciego członu stary gest zamalowałby
    nowszą decyzję ręki (ta sama figura, co `expected_cleared_id` w `user_assign_object`). Klatka
    wycofana albo zastąpiona (`retired_at`/`superseded_by`) między podglądem a klikiem to też
    `'drift'` - martwej tożsamości gest nie pisze. Inny stan = zero zapisu i zero eventów. Klatka już
    z obiektem celu (drugi gest, inna droga) = `'unchanged'` bez eventu - ten test idzie PRZED CAS,
    więc powtórzony klik nie mówi „zmieniło się”.

    CEL PO KANONIE (jak `user_assign_object`): obiekt (`catalog`, `kind`) i alias wpisanej nazwy
    (`alias_norm`) powstają W TEJ transakcji i wyłącznie wtedy, gdy klatka naprawdę dostaje obiekt -
    porzucony podgląd i dryf nie zostawiają pustego obiektu. Konflikt aliasu → `ValueError` przed
    oceną klatki (cel jest zły niezależnie od niej), zero zapisu.

    ZAPIS: `UPDATE frame` na `object_source='user'` (pomija drabinę resolvera: przebieg nie cofnie
    ręki) z wyczyszczeniem pamięci nagrobka. Para verbów jak każde przepięcie osi (§5.9):
    `object.unassigned` stanu sprzed (gdy obiekt był) + `object.assigned` z `before` w payloadzie,
    oba z `reason`. `changes_out` (lista) dostaje `ObjectOverride` - stan sprzed z tej samej
    blokady, nie z pamięci ekranu (`restore_object_override`).

    `ValueError` (EXPECT): klatki nie ma, rodzaj spoza `LIGHT_KINDS` (kalibracja obiektu nie ma
    z definicji), pusty `alias_norm`, kanonu nie ma, a cel nie niesie rodzaju, z którego dałoby się
    go założyć."""
    with _immediate(con):
        werdykt, zmiana = _override_object_tx(
            con, frame_id=frame_id, canon=canon, catalog=catalog, kind=kind, alias_norm=alias_norm,
            expected=expected, now=now, actor=f"user:{uid}", reason=reason)
    if zmiana is not None and changes_out is not None:
        changes_out.append(zmiana)
    return werdykt


def _override_object_tx(con, *, frame_id, canon, catalog, kind, alias_norm, expected, now, actor,
                        reason):
    """Rdzeń `user_override_object` BEZ własnej transakcji → `(werdykt, ObjectOverride | None)`.
    Wspólny dla gestu wydania i dla kroku bazy pozycji zmiany obiektu, który w tej samej transakcji
    zapisuje stan sprzed w `pending_object_change` (D-1011-5). Jedna klinga, dwa zakresy."""
    fr = con.execute(
        "SELECT kind, object_id, object_source, object_cleared_id, retired_at, superseded_by "
        "FROM frame WHERE id = ?", (frame_id,)).fetchone()
    if fr is None:
        raise ValueError(f"frame:{frame_id} nie istnieje")
    if fr["kind"] not in LIGHT_KINDS:
        raise ValueError(f"frame:{frame_id} to '{fr['kind']}' - kalibracja obiektu nie ma "
                         "z definicji, nadpisanie dotyczy lightów i stosów")
    if alias_norm is not None and not alias_norm:
        raise ValueError("alias_norm pusty - nazwa bez znaków alfanumerycznych nie może być kluczem")
    znany, _ = _object_target(con, canon, alias_norm)
    if znany is None and kind is None:
        raise ValueError(f"obiekt '{canon}' nie istnieje, a cel nie niesie rodzaju - nie ma z czego "
                         "go założyć")
    if fr["retired_at"] is not None or fr["superseded_by"] is not None:
        return "drift", None
    if znany is not None and fr["object_id"] == znany:
        return "unchanged", None
    before = (fr["object_id"], fr["object_source"], fr["object_cleared_id"])
    if before != tuple(expected):
        return "drift", None
    object_id, made, alias_id = _upsert_object_tx(con, canon=canon, catalog=catalog, kind=kind,
                                                  alias_norm=alias_norm, actor=actor, now=now)
    if fr["object_id"] is not None:
        emit_event(con, actor=actor, verb="object.unassigned", target=f"frame:{frame_id}",
                   now=now, payload={"object_id": fr["object_id"],
                                     "object_source": fr["object_source"], "reason": reason})
    con.execute(
        "UPDATE frame SET object_id = ?, object_source = 'user', object_cleared_id = NULL "
        "WHERE id = ?", (object_id, frame_id))
    emit_event(con, actor=actor, verb="object.assigned", target=f"frame:{frame_id}", now=now,
               payload={"object_id": object_id, "object_source": "user", "reason": reason,
                        "before": {"object_id": before[0], "object_source": before[1],
                                   "object_cleared_id": before[2]}})
    return "assigned", ObjectOverride(frame_id, before, object_id, reason, made, alias_id)


def restore_object_override(con, *, change, now, uid="local"):
    """COFNIĘCIE `user_override_object`: klatka wraca do stanu `change.before` (obiekt i źródło
    z nagłówka, pustka albo nagrobek z pamięcią) → `True`; inaczej `False`.

    CAS pod blokadą na pełnej trójce: przywracamy WYŁĄCZNIE klatkę, która dalej niesie wynik TEGO
    gestu (`change.object_id`, źródło `user`, bez pamięci nagrobka - gest ją wyczyścił). Inny stan
    (nowszy gest, drugie cofnięcie) = `False` bez zapisu i bez eventu - cofnięcie nie nadpisuje
    decyzji, której nie widziało.

    Para verbów lustrem gestu: `object.unassigned` obiektu ręki + `object.assigned` obiektu sprzed
    (gdy był), oba z `reason` gestu i dopiskiem `_undo` - bilans osi (§5.9) domyka się tak samo jak
    przy geście. Źródło sprzed wraca dosłownie: przebieg resolvera i tak przeliczy `header`,
    a nagrobek odzyska pamięć."""
    with _immediate(con):
        return _restore_override_tx(con, change=change, now=now, actor=f"user:{uid}")


def _restore_override_tx(con, *, change, now, actor):
    """Rdzeń `restore_object_override` BEZ własnej transakcji - wspólny dla cofnięcia gestu wydania
    i dla cofnięcia (albo wycofania w biegu) kroku bazy pozycji zmiany obiektu."""
    stary_obiekt, stare_zrodlo, stara_pamiec = change.before
    powod = f"{change.reason}_undo"
    fr = con.execute(
        "SELECT object_id, object_source, object_cleared_id FROM frame WHERE id = ?",
        (change.frame_id,)).fetchone()
    if fr is None or ((fr["object_id"], fr["object_source"], fr["object_cleared_id"])
                      != (change.object_id, "user", None)):
        return False
    emit_event(con, actor=actor, verb="object.unassigned", target=f"frame:{change.frame_id}",
               now=now, payload={"object_id": change.object_id, "object_source": "user",
                                 "reason": powod})
    con.execute(
        "UPDATE frame SET object_id = ?, object_source = ?, object_cleared_id = ? WHERE id = ?",
        (stary_obiekt, stare_zrodlo, stara_pamiec, change.frame_id))
    if stary_obiekt is not None:
        emit_event(con, actor=actor, verb="object.assigned", target=f"frame:{change.frame_id}",
                   now=now, payload={"object_id": stary_obiekt, "object_source": stare_zrodlo,
                                     "reason": powod})
    return True


def clear_object_tombstone(con, *, frame_id, now, actor="user:local", commit_id=None,
                           location_id=None):
    """ZGAŚ nagrobek `user_cleared` — jedyna droga wyjścia z werdyktu ręki poza kolejnym gestem.

    Woła to `writeback` po wpisaniu karty `OBJECT` do pliku (S2b): człowiek powiedział „to nie ten
    obiekt", a potem podał właściwy TAM, GDZIE archiwum trzyma prawdę — w nagłówku. Od tej chwili
    zeznanie istnieje i drabina ma prawo je przeczytać, więc nagrobek traci przedmiot.

    Klatka bez nagrobka → `False` bez zapisu i bez eventu (idempotencja jak reszta repo). Verb jest
    WŁASNY (`object.tombstone_cleared`), nie `object.unassigned`: nic się nie odpina, znika sam
    zakaz — a bramka §5.9 liczy odpięcia i para bez odpowiednika rozjechałaby jej bilans.

    PAMIĘĆ GAŚNIE RAZEM Z NAGROBKIEM (0017): znika zakaz, więc znika też wskazanie na to, czego
    zakaz dotyczył. `CHECK` w DDL i tak nie przepuściłby wiersza bez nagrobka, ale z pamięcią.

    ZGASZENIE PAMIĘTA, CZYM BYŁO (AR-38): `commit_id` i `location_id` = commit i plik, którego
    karta zgasiła nagrobek. Idą do zdarzenia razem z `cleared_id` (pamięć sprzed zgaszenia), żeby
    cofnięcie TEGO commitu umiało nagrobek odtworzyć (`_restore_object_tombstone_tx`)."""
    with _immediate(con):
        return _clear_object_tombstone_tx(con, frame_id=frame_id, now=now, actor=actor,
                                          commit_id=commit_id, location_id=location_id)


def _clear_object_tombstone_tx(con, *, frame_id, now, actor, commit_id=None, location_id=None):
    """Rdzeń `clear_object_tombstone` BEZ własnej transakcji - wspólny dla gestu commitu drogą
    atomową i dla dokończenia zapisu w miejscu (`finish_inplace_op`), które gasi nagrobek w tej
    samej transakcji co faza operacji i statusy stagingu. Jedna klinga, dwa zakresy transakcji.

    Payload niesie `cleared_id` (pamięć gaszonego nagrobka, także `None` dla nagrobka bez pamięci)
    i - gdy gasi commit - `commit_id`/`location_id`. Zdarzenie jest JEDYNYM miejscem, w którym
    zgaszony stan przeżywa: wiersz klatki po zgaszeniu go już nie ma."""
    row = con.execute(
        "SELECT object_source, object_cleared_id FROM frame WHERE id = ?", (frame_id,)).fetchone()
    if row is None or row["object_source"] != "user_cleared":
        return False
    con.execute("UPDATE frame SET object_source = NULL, object_cleared_id = NULL WHERE id = ?",
                (frame_id,))
    payload = {"reason": "object_card_written", "cleared_id": row["object_cleared_id"]}
    if commit_id is not None:
        payload.update(commit_id=int(commit_id), location_id=int(location_id))
    emit_event(con, actor=actor, verb="object.tombstone_cleared",
               target=f"frame:{frame_id}", now=now, payload=payload)
    return True


def confirm_failed_commit_by_scan(con, *, location_id, frame_id, header_hash, testimony_ok, now,
                                  actor="user:local"):
    """SKAN POTWIERDZAJĄCY commit drogą atomową, który skończył się 'failed' po backupie (AR-38 (2)):
    weryfikacja po podmianie albo re-sync padły, więc baza nie przyjęła bajtów, choć mogły trafić
    na dysk. Gdy skan czyta na tej lokacji nagłówek równy `post_hash` backupu tego commitu, plik
    niesie DOKŁADNIE zapisany nagłówek - commit się dokonał i dokańczamy go: wpisy stagingu
    'failed' lokacji w tym przebiegu → 'applied' z powodem potwierdzenia, a gdy któryś wpisał
    `OBJECT` - zgaszenie nagrobka ręki tą samą klingą i z tą samą parą commit/plik co commit
    udany, więc cofnięcie commitu go odtworzy.

    Dawniej karta stała w bazie po skanie, a klatka zostawała `user_cleared` - wyjście tylko przez
    cofnięcie i ponowny commit. Zakres: wyłącznie droga atomowa (`inplace_op_id IS NULL`; zapis
    w miejscu ma własne dokończenie pod izolacją lokacji) i backup, po którym plik podmieniono
    (`unreplaced_at IS NULL`). Przebieg, w którym ten plik ma backupy z WIĘCEJ niż jednego commitu
    (ponowny staging tego samego `run_id`), nie jest potwierdzany: wpisy 'failed' nie niosą
    `commit_id`, więc nie da się powiedzieć, które należą do commitu z pasującym `post_hash`
    (bramka az, kimi Z1) - zostaje droga cofnięcia i ponownego commitu. Wołane przez skan w zakresie
    `atomic` wjazdu rekordu (`_tx` dołącza). Zwraca `commit_id` potwierdzonego commitu albo
    `None` bez zapisu.

    ZEZNANIE (AR-82): `testimony_ok` = dowód skanu, że zeznanie klatki jest odczytanym nagłówkiem
    (`testimony_matches`). Bez niego potwierdzony zapis jest WSTRZYMANY (`withhold_write` z wersją
    decyzji ręki z backupu commitu) zamiast 'applied' z gaszeniem nagrobka. Wpisy już wstrzymane
    (`withheld_id`) tej klingi nie dotyczą - rozlicza je `_settle_withheld_tx`."""
    with _tx(con):
        row = con.execute(
            "SELECT hb.commit_id, hb.id AS backup_id, c.run_id FROM pending_changes p "
            "JOIN commits c ON c.run_id = p.run_id "
            "JOIN header_backups hb ON hb.commit_id = c.id AND hb.location_id = p.location_id "
            "WHERE p.location_id = ? AND p.status = 'failed' AND p.inplace_op_id IS NULL "
            "AND p.withheld_id IS NULL "
            "AND hb.post_hash = ? AND hb.unreplaced_at IS NULL "
            # C1 (AR-64): próba z NIEROZSTRZYGNIĘTĄ podmianą (backup niepotwierdzony, zamiar
            # otwarty) należy do automatu rekoncyliacji - nagłówek N pod ścieżką nie dowodzi, że
            # pod kopią nie leży cudza wersja do oddania.
            "AND hb.pending_since IS NULL "
            "AND NOT EXISTS (SELECT 1 FROM replace_intent ri WHERE ri.backup_id = hb.id "
            "                AND ri.phase <> 'closed') "
            "AND NOT EXISTS (SELECT 1 FROM header_backups hb2 JOIN commits c2 ON c2.id = hb2.commit_id "
            "                WHERE c2.run_id = c.run_id AND hb2.location_id = p.location_id "
            "                AND hb2.commit_id <> hb.commit_id AND hb2.unreplaced_at IS NULL) "
            "LIMIT 1",
            (location_id, header_hash)).fetchone()
        if row is None:
            return None
        commit_id = row["commit_id"]
        wpisy = con.execute(
            "SELECT id, keyword FROM pending_changes WHERE run_id = ? AND location_id = ? "
            "AND status = 'failed' AND inplace_op_id IS NULL AND withheld_id IS NULL",
            (row["run_id"], location_id)).fetchall()
        if not testimony_ok:
            _withhold_write_tx(con, kind="commit", location_id=location_id, commit_id=commit_id,
                               header_hash=header_hash,
                               reason=withheld_reason(con, location_id=location_id,
                                                      commit_id=commit_id),
                               now=now, pending_ids=[w["id"] for w in wpisy],
                               backup_id=row["backup_id"])
            return commit_id
        # Backupu niepotwierdzonego (0030, AR-40) ta klinga NIE rusza: jego jedynym właścicielem jest
        # rekoncyliacja pisarza (`settle_pending_backup`), która pyta o niego PRZED wjazdem rekordu
        # w tej samej transakcji. Dwóch właścicieli zdejmowało stan nawzajem, a CAS rekoncyliacji
        # cofał wtedy cały re-sync jako „cudzą pracę” (bramka astra, A4).
        # Nagrobek - wyłącznie przy wersji decyzji ręki sprzed zapisu (B12): okno między zapisem
        # a skanem bywa dniami, a w nim człowiek mógł wykluczyć obiekt ponownie.
        uwaga = None
        if any(w["keyword"] == "OBJECT" for w in wpisy):
            reka = con.execute("SELECT hand_version FROM header_backups WHERE id = ?",
                               (row["backup_id"],)).fetchone()["hand_version"]
            uwaga = _clear_tombstone_same_hand_tx(con, frame_id=frame_id, hand_version=reka,
                                                  commit_id=commit_id, location_id=location_id,
                                                  now=now, actor=actor)
        powod = PowodPozycji(f"potwierdzone skanem: nagłówek na dysku = zapisany w commicie "
                             f"{commit_id}", "confirmed_by_scan", commit_id=commit_id)
        ids = [w["id"] for w in wpisy]
        con.execute("UPDATE pending_changes SET status = 'applied' "
                    "WHERE id IN (SELECT value FROM json_each(?))", (json.dumps(ids),))
        _set_pending_reason_tx(con, ids, dopisz(powod, uwaga))
    return commit_id


def restore_object_tombstone(con, *, frame_id, commit_id, location_id, now, actor="user:local"):
    """Odtworzenie nagrobka przy cofnięciu commitu drogą atomową (`writeback.undo`) - wołane w
    zakresie `atomic` re-syncu cofnięcia, do którego `_immediate` dołącza. Reguły w rdzeniu."""
    with _immediate(con):
        return _restore_object_tombstone_tx(con, frame_id=frame_id, commit_id=commit_id,
                                            location_id=location_id, now=now, actor=actor)


def _restore_object_tombstone_tx(con, *, frame_id, commit_id, location_id, now,
                                 actor="user:local"):
    """ODTWÓRZ nagrobek ręki zgaszony przez commit `commit_id` na pliku `location_id` (AR-38,
    decyzja Zdzinia: „cofnięcie odtwarza wykluczenie"). BEZ własnej transakcji - woła ją cofnięcie
    w transakcji swojego re-syncu (droga atomowa, `repo.atomic`) albo dokończenia operacji
    cofnięcia w miejscu (`finish_inplace_op`), więc nagrobek wraca razem z bazą opisującą plik
    sprzed commitu albo wcale.

    ŹRÓDŁO: zdarzenie `object.tombstone_cleared` tej klatki z `commit_id` i `location_id` w payloadzie
    (para jest kluczem - jeden commit gasi nagrobek klatki co najwyżej raz, a druga kopia tej samej
    klatki w tym commicie trafia już na klatkę bez nagrobka). Commit sprzed AR-38 takiego zdarzenia
    nie ma → `False`, zero zapisu: cofnięcie zachowuje się jak dawniej. Payload bez klucza
    `cleared_id` to zdarzenie, któremu nie ufamy, więc też `False`.

    BEZ ODTWORZENIA (`False`, zero zapisu):
      * nagrobek tego commitu i pliku już odtworzony (`object.tombstone_restored` z tą parą) -
        powtórzone cofnięcie go nie zdubluje;
      * klatka ma źródło ręki (`STICKY_OBJECT_SOURCES`): ręka przypisała obiekt albo cofnęła go
        ponownie po commicie - jej nowszy werdykt wygrywa, nic się nie zmienia.

    Gdy automat (resolver z karty) zdążył przypiąć obiekt, odpięcie emituje `object.unassigned`
    (parytet §5.9), a odtworzenie - `object.tombstone_restored` z pamięcią i parą commitu."""
    target = f"frame:{frame_id}"
    zgaszenie = con.execute(
        "SELECT payload FROM event WHERE target = ? AND verb = 'object.tombstone_cleared' "
        "AND json_extract(payload, '$.commit_id') = ? "
        "AND json_extract(payload, '$.location_id') = ? ORDER BY id DESC LIMIT 1",
        (target, int(commit_id), int(location_id))).fetchone()
    if zgaszenie is None:
        return False
    zgaszone = json.loads(zgaszenie["payload"])
    if "cleared_id" not in zgaszone:
        return False
    odtworzone = con.execute(
        "SELECT 1 FROM event WHERE target = ? AND verb = 'object.tombstone_restored' "
        "AND json_extract(payload, '$.commit_id') = ? "
        "AND json_extract(payload, '$.location_id') = ? LIMIT 1",
        (target, int(commit_id), int(location_id))).fetchone()
    if odtworzone is not None:
        return False
    fr = con.execute("SELECT object_id, object_source FROM frame WHERE id = ?",
                     (frame_id,)).fetchone()
    if fr is None or fr["object_source"] in STICKY_OBJECT_SOURCES:
        return False
    if fr["object_id"] is not None:
        emit_event(con, actor=actor, verb="object.unassigned", target=target, now=now,
                   payload={"object_id": fr["object_id"], "object_source": fr["object_source"]},
                   reason="tombstone_restored")
    con.execute(
        "UPDATE frame SET object_id = NULL, object_source = 'user_cleared', "
        "object_cleared_id = ? WHERE id = ?",
        (zgaszone["cleared_id"], frame_id))
    emit_event(con, actor=actor, verb="object.tombstone_restored", target=target, now=now,
               payload={"commit_id": int(commit_id), "location_id": int(location_id),
                        "cleared_id": zgaszone["cleared_id"], "was_object_id": fr["object_id"],
                        "was_source": fr["object_source"]})
    return True


# ============================================================ oś OBSERWATORIUM (§PLAN_os_obserwatorium)

OBSERVATORY_SOURCES = frozenset({"user"})
"""Legalne wartości `frame.observatory_source` - LUSTRO CHECK-a z DDL (`0027_observatory_source.sql`).

Jeden pisarz kolumny: RĘKA. Stanowisko wyliczone z GPS nagłówka zostaje NULL - powód w 0027
(ten sam, co przy `CONFIG_SOURCES`)."""

STICKY_OBSERVATORY_SOURCES = OBSERVATORY_SOURCES
"""Źródła osi obserwatorium, których PRZEBIEG nie ma prawa nadpisać. ALIAS, nie druga lista - powód
jak przy `STICKY_CONFIG_SOURCES` (rozejdą się dopiero przy źródle zapisywanym przez maszynę)."""


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
    już przypisany ten sam → `False` bez eventu; inaczej UPDATE + `event(observatory.assigned)`.

    GUARD ŹRÓDŁA (0027): klatka ze stanowiskiem wskazanym RĘKĄ (`observatory_source` ∈
    `STICKY_OBSERVATORY_SOURCES`) jest NIETYKALNA dla automatu - zwrot `False`, zero zapisu, zero
    eventu. Guard stoi TU, nie tylko w pętli resolvera, z powodu jak przy `assign_config`: to jedyne
    miejsce, przez które przechodzi każdy pisarz osi z automatu. Ręka zmienia rękę wyłącznie przez
    `user_assign_observatory(overwrite=True)`.

    PRZEPIĘCIE EMITUJE PARĘ (`observatory.unassigned` + `observatory.assigned`), jak na osiach
    obiektu i configu - inaczej bilans `frame.observatory_id` (`audit.entity_event_parity`) zawyżałby
    emisje o każde przepięcie na zawsze. Dziś przepięcie z automatu wymaga zmiany GPS w nagłówku
    klatki, więc populacja jest znikoma - para kosztuje jeden wiersz dziennika na taki przypadek."""
    row = con.execute(
        "SELECT observatory_id, observatory_source FROM frame WHERE id = ?", (frame_id,)).fetchone()
    if row is not None and row["observatory_source"] in STICKY_OBSERVATORY_SOURCES:
        return False
    if row is not None and row["observatory_id"] == observatory_id:
        return False

    with con:
        if row is not None and row["observatory_id"] is not None:
            emit_event(con, actor=actor, verb="observatory.unassigned", target=f"frame:{frame_id}",
                       now=now, payload={"observatory_id": row["observatory_id"],
                                         "observatory_source": None},
                       reason="GPS nagłówka wskazuje inne stanowisko")
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
    """Wiersz teleskopu albo `ValueError` (błąd wołania - id spoza listy GUI; nagrobek - 0040: osi
    takiego teleskopu nie ma, więc gest ręki go nie zmienia). Zwraca (label, status, merged_into)."""
    row = con.execute(
        "SELECT label, status, merged_into, retired_at FROM telescope WHERE id = ?",
        (telescope_id,)).fetchone()
    if row is None:
        raise ValueError(f"telescope:{telescope_id} nie istnieje")
    if row["retired_at"] is not None:
        raise ValueError(f"telescope:{telescope_id} to nagrobek - gest osi go nie zmienia")
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


# ============================================================ optyka teleskopu: ręka + pliki (AR-128)
#
# Ogniskowa i f/ teleskopu mają dwa miejsca (migracja 0039): `*_nominal` = wartość Z PLIKÓW (pisze
# wyłącznie `refresh_telescope_optics`, wartość liczy `grouper.optics_from_files`), `*_user` = wartość
# RĘKI (pisze wyłącznie gest człowieka). Ręka wygrywa przy każdym odczycie; automat jej nie czyta
# i nie pisze, więc nowa Dostawa nie ma czym jej cofnąć (D-1012-2 `Q13`).
#
# WALIDATORY SĄ WSPÓLNE (bramka planu T24, zarzut 6): każda klinga piszącą ten fakt - setter osi
# i okno „Dopisz nowy…" - woła TĘ SAMĄ funkcję. Druga droga zapisu bez nich wpuściłaby do ręki
# znany błąd pliku (f/200), a ręka wygrywa zawsze, więc błąd stałby się prawdą osi.

TELESCOPE_FOCAL_RANGE_MM = (5.0, 20000.0)
"""Zakres ogniskowej wpisywanej ręką [mm]. Ochrona przed literówką, nie fakt optyczny: najkrótsza
ogniskowa archiwum to 48 mm (zoom), najdłuższa 1600 mm (RC8)."""
TELESCOPE_F_RATIO_RANGE = (0.5, 50.0)
"""Zakres f/ wpisywanej ręką. Odbija znany błąd pliku `FOCRATIO = 200` (26 klatek RC8, 2022-04)."""


def _valid_number(value, lo, hi, what, unit):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not lo <= value <= hi:
        raise ValueError(f"{what} musi być liczbą od {lo:g} do {hi:g}{unit}, jest {value!r}")
    return float(value)


def valid_telescope_focal(focal_mm):
    """Ogniskowa ręki → `float` albo `ValueError` po polsku (jedyny właściciel zakresu)."""
    return _valid_number(focal_mm, *TELESCOPE_FOCAL_RANGE_MM, "ogniskowa", " mm")


def valid_telescope_f_ratio(f_ratio):
    """f/ ręki → `float` albo `ValueError` po polsku (jedyny właściciel zakresu)."""
    return _valid_number(f_ratio, *TELESCOPE_F_RATIO_RANGE, "f/", "")


def valid_telescope_park(in_park):
    """Trójstan parku: 1 = w parku · 0 = jawnie historyczny · `None` = nic nie powiedziano."""
    if in_park not in (0, 1, None):
        raise ValueError(f"in_park={in_park!r} - dozwolone 1 (park) | 0 (historyczny) | None")
    return None if in_park is None else int(in_park)


def valid_telescope_name(con, name):
    """Nazwa NOWEGO teleskopu z ręki → nazwa po `strip` albo `ValueError`.

    Projektowana od zera (bramka planu, uwaga `kimi`): `label_telescope` sprawdza tylko pustość,
    a UNIQUE NOCASE ma wyłącznie `telescop_canon`. Nowa nazwa staje się i kanonem, i etykietą, więc
    nie wolno jej zderzyć ani z kanonem (UNIQUE wybuchłby w środku transakcji), ani z etykietą innego
    teleskopu (dwa wiersze osi wyglądałyby jak jeden). Porównanie bez wielkości liter.

    NAZWA NAGROBKA NIE JEST ZAJĘTA (0040): teleskopu o tej nazwie na osi nie ma, a „Dopisz nowy…”
    pod nią przywraca wiersz nagrobka (`user_assign_config_new_telescope`) zamiast wybuchać na UNIQUE."""
    tekst = str(name or "").strip()
    if not tekst:
        raise ValueError("nazwa teleskopu jest pusta")
    zajety = con.execute(
        "SELECT id FROM telescope WHERE (telescop_canon = ? OR label = ? COLLATE NOCASE) "
        "AND retired_at IS NULL LIMIT 1",
        (tekst, tekst)).fetchone()
    if zajety is not None:
        raise ValueError(f"nazwa „{tekst}” jest już zajęta (telescope:{zajety['id']})")
    return tekst


def _telescope_optics_row(con, telescope_id):
    """Wiersz optyki KANONICZNEGO teleskopu albo `ValueError` (brak wiersza, nagrobek, wiersz scalony -
    optyka scalonego opisywałaby oś, której już nie ma; lustro `set_telescope_park`)."""
    row = con.execute(
        "SELECT focal_nominal, f_ratio_nominal, focal_user, f_ratio_user, merged_into, retired_at "
        "FROM telescope WHERE id = ?", (telescope_id,)).fetchone()
    if row is None:
        raise ValueError(f"telescope:{telescope_id} nie istnieje")
    if row["retired_at"] is not None:
        raise ValueError(f"telescope:{telescope_id} to nagrobek - optyki mu nie zapisuję")
    if row["merged_into"] is not None:
        raise ValueError(f"telescope:{telescope_id} jest scalony (merged_into={row['merged_into']}) "
                         "- optyka tylko dla kanonicznego")
    return row


def set_telescope_focal(con, *, telescope_id, focal_mm, now, uid="local"):
    """Ogniskowa teleskopu wpisana RĘKĄ (`focal_user`) + `event(telescope.focal_user_set)`
    {`after`, `before`, `files`}. Ta sama wartość → `False` bez zdarzenia (QUIET). Pliki
    nietknięte: to zdanie o teleskopie w bazie, nie zapis nagłówków."""
    focal_mm = valid_telescope_focal(focal_mm)
    with _immediate(con):
        row = _telescope_optics_row(con, telescope_id)
        if row["focal_user"] == focal_mm:
            return False
        con.execute("UPDATE telescope SET focal_user = ? WHERE id = ?", (focal_mm, telescope_id))
        emit_event(con, actor=f"user:{uid}", verb="telescope.focal_user_set",
                   target=f"telescope:{telescope_id}", now=now,
                   payload={"after": focal_mm, "before": row["focal_user"],
                            "files": row["focal_nominal"]})
    return True


def clear_telescope_focal(con, *, telescope_id, now, uid="local"):
    """„Przywróć z plików" dla ogniskowej: `focal_user` → NULL + `event(telescope.focal_user_cleared)`
    {`before`}. Wartość z plików (`focal_nominal`) stoi obok nietknięta. Bez ręki → `False`."""
    with _immediate(con):
        row = _telescope_optics_row(con, telescope_id)
        if row["focal_user"] is None:
            return False
        con.execute("UPDATE telescope SET focal_user = NULL WHERE id = ?", (telescope_id,))
        emit_event(con, actor=f"user:{uid}", verb="telescope.focal_user_cleared",
                   target=f"telescope:{telescope_id}", now=now,
                   payload={"before": row["focal_user"], "files": row["focal_nominal"]})
    return True


def set_telescope_f_ratio(con, *, telescope_id, f_ratio, now, uid="local"):
    """f/ teleskopu wpisana RĘKĄ (`f_ratio_user`) + `event(telescope.f_ratio_user_set)` - lustro
    `set_telescope_focal`."""
    f_ratio = valid_telescope_f_ratio(f_ratio)
    with _immediate(con):
        row = _telescope_optics_row(con, telescope_id)
        if row["f_ratio_user"] == f_ratio:
            return False
        con.execute("UPDATE telescope SET f_ratio_user = ? WHERE id = ?", (f_ratio, telescope_id))
        emit_event(con, actor=f"user:{uid}", verb="telescope.f_ratio_user_set",
                   target=f"telescope:{telescope_id}", now=now,
                   payload={"after": f_ratio, "before": row["f_ratio_user"],
                            "files": row["f_ratio_nominal"]})
    return True


def clear_telescope_f_ratio(con, *, telescope_id, now, uid="local"):
    """„Przywróć z plików" dla f/ - lustro `clear_telescope_focal`."""
    with _immediate(con):
        row = _telescope_optics_row(con, telescope_id)
        if row["f_ratio_user"] is None:
            return False
        con.execute("UPDATE telescope SET f_ratio_user = NULL WHERE id = ?", (telescope_id,))
        emit_event(con, actor=f"user:{uid}", verb="telescope.f_ratio_user_cleared",
                   target=f"telescope:{telescope_id}", now=now,
                   payload={"before": row["f_ratio_user"], "files": row["f_ratio_nominal"]})
    return True


def clear_telescope_optics(con, *, telescope_id, now, uid="local"):
    """„Przywróć z plików" (Oś teleskopu): zdejmij rękę OBU pól optyki JEDNĄ transakcją - dwa
    zdarzenia (`*_user_cleared`), każde tylko przy realnej zmianie (bramka kodu T24, N12). Zwraca
    `(ogniskowa_zdjeta, f_zdjeta)`. Błąd w drugim polu wycofuje pierwsze."""
    with atomic(con):
        return (clear_telescope_focal(con, telescope_id=telescope_id, now=now, uid=uid),
                clear_telescope_f_ratio(con, telescope_id=telescope_id, now=now, uid=uid))


def refresh_telescope_optics(con, *, telescope_id, focal, f_ratio, now, actor="grouper"):
    """Wartość Z PLIKÓW (`focal_nominal`, `f_ratio_nominal`) ← wynik `grouper.optics_from_files`.

    Pisze WYŁĄCZNIE kolumny automatu - kolumn ręki nie czyta i nie pisze (ręka wygrywa przy odczycie,
    D-1012-2 `Q13`). `None` = brak zeznań i NIE nadpisuje (RC8R: 1200 bez ani jednej klatki
    z ogniskową). Zmiana → jedno `event(telescope.optics_derived)` {`before`, `after`}; bez zmiany
    zero zdarzeń (drugi przebieg Dostawy jest cichy). `focal` zapisujemy w milimetrach całkowitych -
    tak, jak kolumna była pisana od 0002."""
    with _tx(con):
        row = con.execute(
            "SELECT focal_nominal, f_ratio_nominal FROM telescope WHERE id = ?",
            (telescope_id,)).fetchone()
        if row is None:
            raise ValueError(f"telescope:{telescope_id} nie istnieje")
        nowa_ogn = row["focal_nominal"] if focal is None else int(round(focal))
        nowe_f = row["f_ratio_nominal"] if f_ratio is None else float(f_ratio)
        if (nowa_ogn, nowe_f) == (row["focal_nominal"], row["f_ratio_nominal"]):
            return False
        con.execute("UPDATE telescope SET focal_nominal = ?, f_ratio_nominal = ? WHERE id = ?",
                    (nowa_ogn, nowe_f, telescope_id))
        emit_event(con, actor=actor, verb="telescope.optics_derived",
                   target=f"telescope:{telescope_id}", now=now,
                   payload={"before": {"focal": row["focal_nominal"], "f_ratio": row["f_ratio_nominal"]},
                            "after": {"focal": nowa_ogn, "f_ratio": nowe_f}})
    return True


def user_assign_config_new_telescope(con, *, frame_ids, name, focal_mm, f_ratio=None, in_park=None,
                                     source_telescope_id=None, now, uid="local"):
    """„Dopisz nowy…" (D-1012-2 `Q8`/`Q11`): NOWY teleskop z ręki + przypisanie mu klatek - JEDNA
    transakcja (`atomic`), więc teleskop bez klatek nie powstaje.

    Teleskop w Horreum to fizyczny teleskop z ogniskową, potwierdzony ręką - dlatego wiersz wchodzi od
    razu nazwany i zatwierdzony, z ogniskową (i f/) ręki. KAŻDE zapisane pole ma swoje zdarzenie,
    zapisane CIAŁAMI istniejących gestów osi (dołączają do `atomic`), żeby Historia nowego teleskopu
    była nieodróżnialna od Historii teleskopu nazwanego gest po geście (bramka planu, zarzut 7):
    `telescope.proposed` (aktor `user:<uid>`, `via: add:<źródło>`) → `telescope.labeled` →
    `telescope.approved` → `telescope.focal_user_set` → `telescope.f_ratio_user_set` (tylko przy
    podanej f/) → `telescope.parked` (tylko 0/1 - `None` to brak decyzji, zdarzenia nie ma) → pary
    `config.*` gestu przypisania z nadpisaniem (`user_assign_config(overwrite=True)`) → wartość
    z plików liczona TĄ SAMĄ derywacją co Dostawa (`grouper.optics_from_files`) na przypiętych klatkach.

    Walidacja WSZYSTKICH pól przed pierwszym DML (wspólne walidatory). Zero przypisanych klatek →
    `ValueError` i wycofanie całości. Zwraca `(telescope_id, ConfigGesture)`.

    NAZWA NAGROBKA (0040): wiersz nagrobka wraca do osi (`telescope.unretired` zamiast `proposed` -
    wiersz nie powstaje drugi raz), a pola dostają wartości z okna tymi samymi gestami osi, także f/
    i park pusty (okno pokazuje stan, który gest ma zapisać, nie pola sprzed nagrobka).

    ŚLAD GESTU (`telescope_add`, 0040): teleskop i granice zdarzeń tej transakcji - z nich „Cofnij
    dopisanie” (`undo_new_telescope`) odtwarza stan klatek sprzed gestu i odróżnia zdarzenia gestu
    od późniejszych zdarzeń ręki."""
    focal_mm = valid_telescope_focal(focal_mm)
    f_ratio = None if f_ratio is None else valid_telescope_f_ratio(f_ratio)
    in_park = valid_telescope_park(in_park)
    via = f"add:{source_telescope_id}" if source_telescope_id is not None else "add"
    with atomic(con):
        nazwa = valid_telescope_name(con, name)
        grob = con.execute(
            "SELECT id FROM telescope WHERE telescop_canon = ? AND retired_at IS NOT NULL",
            (nazwa,)).fetchone()
        if grob is None:
            cur = con.execute(
                "INSERT INTO telescope(telescop_canon, label, f_ratio_nominal, focal_nominal, "
                "status, created_at) VALUES (?, NULL, NULL, NULL, 'proposed', ?)", (nazwa, now))
            tid = cur.lastrowid
            emit_event(con, actor=f"user:{uid}", verb="telescope.proposed",
                       target=f"telescope:{tid}",
                       now=now, payload={"telescop_canon": nazwa, "f_ratio_nominal": None,
                                         "focal_nominal": None, "member_count": len(frame_ids),
                                         "via": via})
        else:
            tid = grob["id"]
            _unretire_telescope_tx(con, telescope_id=tid, now=now, actor=f"user:{uid}",
                                   payload={"telescop_canon": nazwa,
                                            "member_count": len(frame_ids), "via": via})
        pierwsze = con.execute("SELECT max(id) FROM event").fetchone()[0]
        label_telescope(con, telescope_id=tid, label=nazwa, now=now, uid=uid)
        approve_telescope(con, telescope_id=tid, now=now, uid=uid)
        set_telescope_focal(con, telescope_id=tid, focal_mm=focal_mm, now=now, uid=uid)
        if f_ratio is not None:
            set_telescope_f_ratio(con, telescope_id=tid, f_ratio=f_ratio, now=now, uid=uid)
        else:                                # nowy wiersz: bez zdarzenia; nagrobek: f/ z okna
            clear_telescope_f_ratio(con, telescope_id=tid, now=now, uid=uid)
        set_telescope_park(con, telescope_id=tid, in_park=in_park, now=now, uid=uid, via=via)
        g = user_assign_config(con, frame_ids=frame_ids, telescope_id=tid, now=now, uid=uid,
                               overwrite=True)
        if not g.assigned:
            raise ValueError("żadna ze wskazanych klatek nie dostała zestawu - teleskop nie powstaje")
        # wartość z plików nowego teleskopu i źródeł odświeżył już `user_assign_config` (N2)
        con.execute(
            "INSERT INTO telescope_add(telescope_id, first_event_id, last_event_id, created_at) "
            "VALUES (?, ?, (SELECT max(id) FROM event), ?)", (tid, pierwsze, now))
    return tid, g


# ============================================================ nagrobek osi (0040, AR-133/AR-137, `Q8`)
#
# „Cofnij” gestu, który ZAŁOŻYŁ obiekt („Zmień obiekt…”) albo teleskop („Dopisz nowy…”), zdejmuje go
# z list wyboru, gdy nie ma klatek ani faktów ręki spoza gestu - nagrobkiem (`retired_at`), nie
# `DELETE`: wiersz, pola ręki i dziennik zostają. Założenie pod tą samą nazwą przywraca wiersz
# (`*.unretired` w pisarzach osi). Jedna klinga dla obu osi, osobny literał SQL na oś.

RETIRE_REFUSALS = ("frames", "cleared_memory", "live_run", "foreign_alias", "merged", "members",
                   "profile", "calibration_fact", "hand_after", "undone", "source_retired")
"""Powody odmowy nagrobka (`retire_orphan`) i cofnięcia dopisania (`undo_new_telescope`) - tokeny,
z których powierzchnia składa zdanie (`object.config_undo_add.refused.<token>`, parytet w testach):
  * `frames` - klatki wskazują encję (teleskop: przez zestaw);
  * `cleared_memory` - nagrobek klatki pamięta ten obiekt (`object_cleared_id`, „Przywróć” by go wołał);
  * `live_run` - inny niecofnięty przebieg „Zmień obiekt…” ma go w pozycji (cofnięcie by go przywróciło);
  * `foreign_alias` - alias spoza gestu (ręka sprzed gestu, słownik, inny przebieg);
  * `merged` / `members` - teleskop scalony albo ze członkami scalenia;
  * `profile` / `calibration_fact` - profil kalibracji albo fakt przepisu klatki wskazuje teleskop;
  * `hand_after` - zdarzenie ręki na teleskopie PO geście (etykieta, park, optyka zmienione później);
  * `undone` - gest już cofnięty (wyłącznie `undo_new_telescope`);
  * `source_retired` - klatka wróciłaby do zestawu teleskopu, który jest już nagrobkiem (późniejszy
    gest przepiął klatki innego dopisania, a tamto cofnięto) - wyłącznie `undo_new_telescope`."""


def _odmowa_nagrobka(con, *, axis, entity_id, trail, frames=True):
    """Pod transakcją wołającego: powód odmowy nagrobka (`RETIRE_REFUSALS`) albo None. `trail` =
    wiersz śladu gestu: przebieg (`object_change_run`) dla obiektu, `telescope_add` dla teleskopu.
    `frames=False` pomija warunek klatek - cofnięcie dopisania pyta o resztę PRZED rozpięciem klatek,
    żeby odmowa nie zostawiała pół-cofnięcia."""
    if axis == "object":
        if frames and con.execute("SELECT 1 FROM frame WHERE object_id = ? LIMIT 1",
                                  (entity_id,)).fetchone() is not None:
            return "frames"
        if con.execute("SELECT 1 FROM frame WHERE object_cleared_id = ? LIMIT 1",
                       (entity_id,)).fetchone() is not None:
            return "cleared_memory"
        if con.execute(
                "SELECT 1 FROM pending_object_change p "
                "JOIN object_change_run r ON r.run_id = p.run_id "
                "WHERE r.run_id <> ? AND r.status <> 'undone' AND ? IN (p.object_id, "
                "      p.before_object_id, p.expected_object_id, p.before_cleared_id, "
                "      p.expected_cleared_id) LIMIT 1",
                (trail["run_id"], entity_id)).fetchone() is not None \
                or con.execute(
                    "SELECT 1 FROM object_change_run WHERE run_id <> ? AND status <> 'undone' "
                    "AND made_object_id = ? LIMIT 1",
                    (trail["run_id"], entity_id)).fetchone() is not None:
            return "live_run"
        for a in con.execute("SELECT id, alias_norm FROM object_alias WHERE object_id = ?",
                             (entity_id,)).fetchall():
            if (a["id"], a["alias_norm"]) != (trail["made_alias_id"], trail["alias_norm"]):
                return "foreign_alias"
        return None
    t = con.execute("SELECT merged_into FROM telescope WHERE id = ?", (entity_id,)).fetchone()
    if t["merged_into"] is not None:
        return "merged"
    if con.execute("SELECT 1 FROM telescope WHERE merged_into = ? LIMIT 1",
                   (entity_id,)).fetchone() is not None:
        return "members"
    if frames and con.execute(
            "SELECT 1 FROM frame f JOIN config c ON c.id = f.config_id "
            "WHERE c.telescope_id = ? LIMIT 1", (entity_id,)).fetchone() is not None:
        return "frames"
    if con.execute("SELECT 1 FROM calibration_profile WHERE telescope_id = ? LIMIT 1",
                   (entity_id,)).fetchone() is not None:
        return "profile"
    if con.execute(
            "SELECT 1 FROM calibration_fact WHERE key = 'telescope_id' "
            "AND CAST(value AS INTEGER) = ? LIMIT 1", (entity_id,)).fetchone() is not None:
        return "calibration_fact"
    # Zdarzenia SAMEGO gestu (`proposed`/`unretired` → `labeled` → `approved` → optyka → `parked`
    # i `config.*`) leżą w granicach śladu i powodem odmowy nie są; ręka PO geście - jest. Wartość
    # z plików (`telescope.optics_derived`) faktem ręki nie jest, choć gest przypięcia klatek innego
    # teleskopu liczy ją z aktorem `user:*` (`user_assign_config` → `refresh_all_optics`).
    if con.execute(
            "SELECT 1 FROM event WHERE target = ? AND actor LIKE 'user:%' AND id > ? "
            "AND verb <> 'telescope.optics_derived' LIMIT 1",
            (f"telescope:{entity_id}", trail["last_event_id"])).fetchone() is not None:
        return "hand_after"
    return None


def _retire_orphan_tx(con, *, axis, entity_id, now, actor, run_id=None, add_id=None):
    """Rdzeń `retire_orphan` BEZ własnej transakcji → powód odmowy (`RETIRE_REFUSALS`) albo None
    (nagrobek postawiony albo encja już nim jest - bez zapisu i bez zdarzenia)."""
    if axis == "object":
        trail = con.execute(
            "SELECT run_id, made_object_id, made_alias_id, alias_norm FROM object_change_run "
            "WHERE run_id = ?", (run_id,)).fetchone()
        if trail is None or trail["made_object_id"] != entity_id:
            raise ValueError(f"przebieg {run_id!r} nie założył object:{entity_id} - nagrobek "
                             "zdejmuje wyłącznie to, co gest założył")
        row = con.execute("SELECT canon, retired_at FROM object WHERE id = ?",
                          (entity_id,)).fetchone()
        if row["retired_at"] is not None:
            return None
        powod = _odmowa_nagrobka(con, axis=axis, entity_id=entity_id, trail=trail)
        if powod is not None:
            return powod
        for a in con.execute("SELECT id, alias_norm, source FROM object_alias WHERE object_id = ?",
                             (entity_id,)).fetchall():
            con.execute("DELETE FROM object_alias WHERE id = ?", (a["id"],))
            emit_event(con, actor=actor, verb="object.alias_retired", target=f"object:{entity_id}",
                       now=now, payload={"alias_norm": a["alias_norm"], "source": a["source"],
                                         "run_id": run_id},
                       reason="nazwa założona gestem zdjęta razem z obiektem po cofnięciu")
        con.execute("UPDATE object SET retired_at = ? WHERE id = ?", (now, entity_id))
        emit_event(con, actor=actor, verb="object.retired", target=f"object:{entity_id}", now=now,
                   payload={"canon": row["canon"], "run_id": run_id})
        return None
    if axis != "telescope":
        raise ValueError(f"oś nagrobka {axis!r} spoza ('object', 'telescope')")
    trail = con.execute("SELECT id, telescope_id, last_event_id FROM telescope_add WHERE id = ?",
                        (add_id,)).fetchone()
    if trail is None or trail["telescope_id"] != entity_id:
        raise ValueError(f"ślad dopisania {add_id!r} nie założył telescope:{entity_id} - nagrobek "
                         "zdejmuje wyłącznie to, co gest założył")
    row = con.execute("SELECT telescop_canon, retired_at FROM telescope WHERE id = ?",
                      (entity_id,)).fetchone()
    if row["retired_at"] is not None:
        return None
    powod = _odmowa_nagrobka(con, axis=axis, entity_id=entity_id, trail=trail)
    if powod is not None:
        return powod
    con.execute("UPDATE telescope SET retired_at = ? WHERE id = ?", (now, entity_id))
    emit_event(con, actor=actor, verb="telescope.retired", target=f"telescope:{entity_id}",
               now=now, payload={"telescop_canon": row["telescop_canon"], "add_id": add_id})
    return None


def retire_orphan(con, *, axis, entity_id, now, uid="local", run_id=None, add_id=None):
    """NAGROBEK OBIEKTU ALBO TELESKOPU, który gest założył (0040, decyzja `Q8`) - jedna transakcja
    `_immediate` → powód odmowy (`RETIRE_REFUSALS`) albo None. Zwykle woła ją cofnięcie gestu
    (`close_object_change_undo`, `undo_new_telescope`) w swojej transakcji przez rdzeń `_tx`.

    `axis='object'` + `run_id` przebiegu „Zmień obiekt…”, który obiekt założył albo wskrzesił
    (`made_object_id`). Warunki: 0 klatek z tym obiektem, 0 nagrobków klatek, które go pamiętają,
    żaden inny niecofnięty przebieg nie ma go w pozycji ani w śladzie, aliasy wyłącznie z tego gestu
    (`made_alias_id` + `alias_norm` przebiegu) - te dostają `object.alias_retired` i znikają, bo
    alias wskazujący nagrobek przypinałby do niego klatki szczeblem aliasu resolvera.

    `axis='telescope'` + `add_id` śladu „Dopisz nowy…”. Warunki: nie scalony i bez członków, 0 klatek
    w jego zestawach, 0 profili kalibracji i faktów przepisu `telescope_id` wskazujących go, żadne
    zdarzenie ręki na nim po geście. Pola ręki zostają (spis ręki nie widzi ubytku).

    Zapis: `retired_at` + `object.retired`/`telescope.retired`. Encja już nagrobkiem → None bez
    zapisu. Ślad, który nie nazywa tej encji → `ValueError` (EXPECT: nagrobek zdejmuje wyłącznie to,
    co gest założył)."""
    with _immediate(con):
        return _retire_orphan_tx(con, axis=axis, entity_id=entity_id, now=now, actor=f"user:{uid}",
                                 run_id=run_id, add_id=add_id)


@dataclass(frozen=True)
class NewTelescopeUndo:
    """Wynik „Cofnij dopisanie” (`undo_new_telescope`). `refusal` (`RETIRE_REFUSALS`) przy
    `restored == kept == 0` = cofnięcie odmówione bez zapisu; przy rozpiętych klatkach = teleskop
    zostaje na osi (np. `frames` - klatki zmienione po geście albo przypięte przebiegiem)."""
    telescope_id: int
    restored: int = 0          # klatki z powrotem w stanie sprzed gestu
    kept: int = 0              # klatki, których zestaw zmienił się po geście - zostają (CAS)
    retired: bool = False      # teleskop zdjęty nagrobkiem
    refusal: str | None = None


def undo_new_telescope(con, *, telescope_id, now, uid="local"):
    """„COFNIJ DOPISANIE” (AR-133, `Q8`) - ostatni niecofnięty gest „Dopisz nowy…” teleskopu,
    JEDNA transakcja `atomic` → `NewTelescopeUndo`.

    Kolejność: (1) warunki nagrobka poza klatkami (scalenie, profil, fakt przepisu, ręka po geście) -
    odmowa = zero zapisu, bo teleskop żyje już poza gestem; (2) PLAN klatek gestu z par `config.*`
    w granicach śladu, bez zapisu: wraca klatka, która dalej niesie zestaw gestu z ręki I nie ma
    żadnego `config.assigned`/`config.unassigned` po geście (CAS wartości nie łapie sekwencji ABA -
    przepięcie i powrót ręką do tego samego zestawu to decyzja późniejsza niż gest); reszta zostaje
    (`kept`) - raport, nie nadpisanie; (3) odmowa `source_retired` bez zapisu, gdy któraś klatka
    wróciłaby do zestawu nagrobka teleskopu (gest A → gest B na tych samych klatkach → cofnij A →
    cofnij B); (4) zapis: para verbów jak każde przepięcie; bez `config.unassigned` w granicach -
    do pustki, a `config.review` wraca wyłącznie wtedy, gdy powód był AKTYWNY przed gestem
    (późniejszy niż ostatnie `config.assigned` klatki sprzed gestu - granica epizodu
    `audit.config_review_reason_gap`); (5) nagrobek teleskopu (`_retire_orphan_tx` - pełne
    warunki, w tym klatki); (6) wartość z plików teleskopów, do których klatki wróciły, tą samą
    derywacją co Dostawa (`grouper.refresh_all_optics`); (7) ślad dostaje `undone_at`. Brak śladu
    gestu dla teleskopu → `ValueError`."""
    from .grouper import refresh_all_optics            # import odroczony - jak `user_assign_config`

    actor = f"user:{uid}"
    with atomic(con):
        trail = con.execute(
            "SELECT id, telescope_id, first_event_id, last_event_id, undone_at FROM telescope_add "
            "WHERE telescope_id = ? ORDER BY id DESC LIMIT 1", (telescope_id,)).fetchone()
        if trail is None:
            raise ValueError(f"telescope:{telescope_id} nie ma śladu gestu „Dopisz nowy…”")
        if trail["undone_at"] is not None:
            return NewTelescopeUndo(telescope_id, refusal="undone")
        powod = _odmowa_nagrobka(con, axis="telescope", entity_id=telescope_id, trail=trail,
                                 frames=False)
        if powod is not None:
            return NewTelescopeUndo(telescope_id, refusal=powod)
        gest = {}                                 # klatka → [zestaw gestu, stan sprzed]
        for e in con.execute(
                "SELECT verb, target, payload FROM event WHERE id BETWEEN ? AND ? "
                "AND verb IN ('config.unassigned', 'config.assigned') AND target LIKE 'frame:%' "
                "ORDER BY id", (trail["first_event_id"], trail["last_event_id"])).fetchall():
            fid = int(e["target"][len("frame:"):])
            ladunek = json.loads(e["payload"])
            wpis = gest.setdefault(fid, [None, (None, None)])
            if e["verb"] == "config.unassigned":
                wpis[1] = (ladunek["config_id"], ladunek.get("config_source"))
            else:
                wpis[0] = ladunek["config_id"]
        powroty, kept = [], 0
        for fid, (cfg, przed) in sorted(gest.items()):
            fr = con.execute("SELECT config_id, config_source FROM frame WHERE id = ?",
                             (fid,)).fetchone()
            if (fr is None or (fr["config_id"], fr["config_source"]) != (cfg, "user")
                    or con.execute(
                        "SELECT 1 FROM event WHERE target = ? AND id > ? "
                        "AND verb IN ('config.assigned', 'config.unassigned') LIMIT 1",
                        (f"frame:{fid}", trail["last_event_id"])).fetchone() is not None):
                kept += 1
                continue
            if przed[0] is not None and con.execute(
                    "SELECT 1 FROM config c JOIN telescope_canonical tc ON tc.id = c.telescope_id "
                    "JOIN telescope t ON t.id IN (tc.id, tc.canon_id) "
                    "WHERE c.id = ? AND t.retired_at IS NOT NULL LIMIT 1",
                    (przed[0],)).fetchone() is not None:
                return NewTelescopeUndo(telescope_id, refusal="source_retired")
            powroty.append((fid, cfg, przed))
        restored = len(powroty)
        zrodla = set()
        for fid, cfg, (stary, stare_zrodlo) in powroty:
            emit_event(con, actor=actor, verb="config.unassigned", target=f"frame:{fid}", now=now,
                       payload={"config_id": cfg, "config_source": "user"},
                       reason="cofnięcie dopisania teleskopu")
            con.execute("UPDATE frame SET config_id = ?, config_source = ? WHERE id = ?",
                        (stary, stare_zrodlo, fid))
            if stary is not None:
                emit_event(con, actor=actor, verb="config.assigned", target=f"frame:{fid}",
                           now=now, payload={"config_id": stary, "config_source": stare_zrodlo},
                           reason="cofnięcie dopisania teleskopu")
                zrodla.add(con.execute("SELECT telescope_id FROM config WHERE id = ?",
                                       (stary,)).fetchone()[0])
                continue
            przeglad = con.execute(
                "SELECT reason FROM event WHERE verb = 'config.review' AND target = ? AND id < ? "
                "AND id > COALESCE((SELECT max(a.id) FROM event a "
                "                   WHERE a.verb = 'config.assigned' AND a.target = ? "
                "                   AND a.id < ?), 0) "
                "ORDER BY id DESC LIMIT 1",
                (f"frame:{fid}", trail["first_event_id"], f"frame:{fid}",
                 trail["first_event_id"])).fetchone()
            if przeglad is not None:
                emit_event(con, actor=actor, verb="config.review", target=f"frame:{fid}",
                           now=now, reason=przeglad["reason"])
        powod = _retire_orphan_tx(con, axis="telescope", entity_id=telescope_id, now=now,
                                  actor=actor, add_id=trail["id"])
        if powod is not None:
            zrodla.add(telescope_id)              # teleskop zostaje z mniejszą liczbą klatek
        if zrodla:
            refresh_all_optics(con, now, actor=actor, telescope_ids=zrodla)
        con.execute("UPDATE telescope_add SET undone_at = ? WHERE id = ?", (now, trail["id"]))
    return NewTelescopeUndo(telescope_id, restored=restored, kept=kept, retired=powod is None,
                            refusal=powod)


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


@dataclass
class ObservatoryGesture:
    """Wynik gestu „Wskaż stanowisko" albo jego cofnięcia - okno i CLI mówią „N z M" I DLACZEGO
    resztę pominięto. Każdy licznik to inny powód, nie odcienie jednego (lekcja `ConfigGesture`).

    Rodzaju klatki gest NIE odsiewa, i to jest różnica wobec osi sprzętu i obiektu: stanowisko jest
    KIND-AGNOSTIC (dark i flat też powstały gdzieś na Ziemi - pamięć osi obserwatorium)."""
    assigned: int = 0           # klatki, które REALNIE dostały stanowisko z ręki
    occupied: int = 0           # klatka ma już stanowisko, a gest nie prosił o nadpisanie
    unchanged: int = 0          # to samo stanowisko tą samą ręką - idempotencja, zero zapisu
    cleared: int = 0            # cofnięcie: klatki, którym zdjęto wskazanie ręki
    not_hand: int = 0           # cofnięcie: stanowisko z GPS nagłówka - ręka go nie zdejmie
    nothing: int = 0            # cofnięcie: klatka bez stanowiska - nie ma czego cofać
    observatory_id: int | None = None   # stanowisko gestu (member-id, jak `propose_observatory`)
    created: bool = False       # gest powołał NOWE stanowisko (w promieniu `THRESH_KM` nie było)
    named: bool = False         # nazwa z gestu trafiła na stanowisko dotąd nienazwane
    name_kept: str | None = None   # stanowisko z promienia miało już INNĄ nazwę - zostaje jego
    elev_set: float | None = None   # wysokość z gestu dopisana stanowisku dotąd bez wysokości
    elev_kept: float | None = None  # stanowisko z promienia miało już INNĄ wysokość - zostaje jego
    frame_ids: tuple = ()       # klatki REALNIE zapisane (nadane albo cofnięte) - recepta odwrotu
    cleared_from: tuple = ()    # cofnięcie: stanowiska, z których zdjęto wskazania (rosnąco)
    cleared_gps: int = 0        # cofnięcie: z tego klatki z GPS - wrócą do stanowiska z pliku


def user_assign_observatory(con, *, frame_ids, now, observatory_id=None, lat=None, lon=None,
                            name=None, elev=None, uid="local", overwrite=False, dry=False):
    """Przypisanie STANOWISKA grupie klatek GESTEM CZŁOWIEKA (`observatory_source='user'`).

    Powstało dla populacji, która nie ma czym zeznać: RAW z lustrzanki bez modułu GPS (LMC, wyjazdy),
    a DNG jest read-only, więc writeback `SITELAT`/`SITELONG` jest zamknięty NA ZAWSZE (0027).

    CEL GESTU: ALBO `observatory_id` (istniejące stanowisko z listy), ALBO `lat`/`lon` podane ręką
    (+ opcjonalnie `name`, `elev`). Współrzędne przechodzą przez TĘ SAMĄ kotwicę geometryczną co
    `propose_observatory` (`nearest_site` ≤ `THRESH_KM`): punkt w promieniu istniejącego stanowiska
    trafia W NIE (member-id) - druga droga do osi nie ma prawa mnożyć duplikatów, które potem trzeba
    scalać. Nowe stanowisko POWOŁUJEMY dopiero przy pierwszym realnym zapisie (wzorzec
    `user_assign_config`, bramka 3a zarzut 5): gest, który nie ruszył żadnej klatki, nie zostawia
    sieroty w osi. Nazwa idzie na stanowisko nowe albo dotąd NIENAZWANE; stanowisko z inną nazwą
    jej nie traci (`name_kept`) - zmiana nazwy ma własny gest (`label_observatory`).

    ODMOWY Z LICZNIKAMI (`ObservatoryGesture`): **zajęta** - klatka ma stanowisko (z GPS albo
    z ręki), a gest nie prosił o nadpisanie; `overwrite=True` to świadomy drugi gest (jak
    `user_assign_config`); **bez zmiany** - to samo stanowisko tą samą ręką (zero DML, zero eventu).

    PRZEPIĘCIE EMITUJE PARĘ (`observatory.unassigned` + `observatory.assigned`) - bilans
    `frame.observatory_id` w `audit.entity_event_parity` liczy odpięcia jako człon odejmowany.

    `dry=True` = ten sam rachunek BEZ zapisu i bez transakcji (podgląd CLI) - jedna pętla, nie dwie
    kopie reguł. Klatka nieistniejąca → `ValueError` i ZERO zapisu (cała grupa wycofana)."""
    if (observatory_id is None) == (lat is None and lon is None):
        raise ValueError("podaj ALBO observatory_id, ALBO lat/lon")
    if observatory_id is not None and (name is not None or elev is not None):
        raise ValueError("name/elev dotyczą stanowiska z współrzędnych, nie wskazanego po id")
    nazwa = str(name).strip() if name is not None and str(name).strip() else None
    actor = f"user:{uid}"
    g = ObservatoryGesture()
    zapisane = []
    with (nullcontext() if dry else _immediate(con)):
        trafienie = None                         # wiersz stanowiska z promienia (do nazwy)
        if observatory_id is not None:
            if con.execute("SELECT 1 FROM observatory WHERE id = ?",
                           (observatory_id,)).fetchone() is None:
                raise ValueError(f"observatory:{observatory_id} nie istnieje")
            cel = observatory_id
        else:
            la, lo, el = user_site_coords(lat, lon, elev)
            rows = con.execute("SELECT id, lat, lon, name, elev FROM observatory").fetchall()
            cel = nearest_site((la, lo), [(r["id"], r["lat"], r["lon"]) for r in rows])
            if cel is not None:
                trafienie = next(r for r in rows if r["id"] == cel)
        g.observatory_id = cel
        for frame_id in frame_ids:
            fr = con.execute("SELECT observatory_id, observatory_source FROM frame WHERE id = ?",
                             (frame_id,)).fetchone()
            if fr is None:
                raise ValueError(f"frame:{frame_id} nie istnieje")
            if cel is not None and fr["observatory_id"] == cel \
                    and fr["observatory_source"] in STICKY_OBSERVATORY_SOURCES:
                g.unchanged += 1
                continue
            if fr["observatory_id"] is not None and not overwrite:
                g.occupied += 1
                continue
            if cel is None and not g.created:    # dopiero TERAZ wiadomo, że stanowisko komuś posłuży
                g.created = True
                if not dry:
                    cur = con.execute(
                        "INSERT INTO observatory(name, lat, lon, elev, status, created_at) "
                        "VALUES (?, ?, ?, ?, 'proposed', ?)", (nazwa, la, lo, el, now))
                    cel = g.observatory_id = cur.lastrowid
                    emit_event(con, actor=actor, verb="observatory.proposed",
                               target=f"observatory:{cel}", now=now,
                               payload={"lat": la, "lon": lo, "elev": el, "name": nazwa,
                                        "observatory_source": "user"})
            g.assigned += 1
            zapisane.append(frame_id)
            if dry:
                continue
            if fr["observatory_id"] is not None:  # PRZEPIĘCIE - para verbów, inaczej bilans kłamie
                emit_event(con, actor=actor, verb="observatory.unassigned",
                           target=f"frame:{frame_id}", now=now,
                           payload={"observatory_id": fr["observatory_id"],
                                    "observatory_source": fr["observatory_source"]},
                           reason="stanowisko wskazane ręką zastępuje poprzednie")
            con.execute("UPDATE frame SET observatory_id = ?, observatory_source = 'user' "
                        "WHERE id = ?", (cel, frame_id))
            emit_event(con, actor=actor, verb="observatory.assigned", target=f"frame:{frame_id}",
                       now=now, payload={"observatory_id": cel, "observatory_source": "user"})
        if trafienie is not None and nazwa is not None and trafienie["name"] != nazwa:
            if trafienie["name"] is not None:
                g.name_kept = trafienie["name"]
            elif g.assigned:                     # „zero zmian, gdy nic nie zapisano" - także nazwy
                g.named = True
                if not dry:
                    con.execute("UPDATE observatory SET name = ? WHERE id = ?", (nazwa, cel))
                    emit_event(con, actor=actor, verb="observatory.named",
                               target=f"observatory:{cel}", now=now,
                               payload={"before": None, "after": nazwa})
        # WYSOKOŚĆ jak nazwa: trafia wyłącznie na stanowisko bez wysokości, a cudza zostaje i gest
        # o tym mówi (`elev_kept`) - wcześniej ginęła po cichu. Atrybut, nie tożsamość (0004 D3).
        if trafienie is not None and el is not None and trafienie["elev"] != el:
            if trafienie["elev"] is not None:
                g.elev_kept = trafienie["elev"]
            elif g.assigned:
                g.elev_set = el
                if not dry:
                    con.execute("UPDATE observatory SET elev = ? WHERE id = ?", (el, cel))
                    emit_event(con, actor=actor, verb="observatory.elevation_set",
                               target=f"observatory:{cel}", now=now,
                               payload={"before": None, "after": el})
    g.frame_ids = tuple(zapisane)
    return g


def clear_observatory_assignment(con, *, frame_ids, now, uid="local", dry=False):
    """COFNIĘCIE wskazania stanowiska RĘKĄ - druga strona `user_assign_observatory`.

    ZAKRES = WYŁĄCZNIE źródło ręki. Stanowisko z GPS nagłówka zostaje (`not_hand`): cofnięcie
    naprawia pomyłkę człowieka, a nie kasuje faktu zapisanego w pliku.

    BEZ NAGROBKA, inaczej niż na osi obiektu - i to jest decyzja, nie przeoczenie. Nagrobek obiektu
    istnieje, bo szczebel ŚCIEŻKI zgaduje kanon i bez zakazu przypisałby klatkę ponownie. Tutaj
    automat nie zgaduje: wylicza stanowisko WYŁĄCZNIE z GPS w nagłówku. Po cofnięciu klatka bez GPS
    wraca do NULL (stan sprzed gestu), a klatka z GPS dostaje przy najbliższym `Rozwiąż` stanowisko
    ze swojego zeznania - czyli dokładnie to, co miała przed nadpisaniem ręką. Cofnięcie ODDAJE oś
    automatowi; zakaz zostawiałby klatkę z GPS bez stanowiska, którego plik dowodzi.

    `observatory.unassigned` z poprzednim stanowiskiem i źródłem w payloadzie (append-only: ślad
    zostaje, ponowne wskazanie odtworzy stan z dziennika). Źródło gaśnie razem z osią - CHECK 0027
    i tak nie przepuściłby ręki bez osi. `dry=True` jak w `user_assign_observatory`."""
    actor = f"user:{uid}"
    g = ObservatoryGesture()
    zapisane, zrodla = [], set()
    with (nullcontext() if dry else _immediate(con)):
        for frame_id in frame_ids:
            fr = con.execute("SELECT observatory_id, observatory_source FROM frame WHERE id = ?",
                             (frame_id,)).fetchone()
            if fr is None:
                raise ValueError(f"frame:{frame_id} nie istnieje")
            if fr["observatory_id"] is None:
                g.nothing += 1
                continue
            if fr["observatory_source"] not in STICKY_OBSERVATORY_SOURCES:
                g.not_hand += 1
                continue
            g.cleared += 1
            zapisane.append(frame_id)
            zrodla.add(fr["observatory_id"])
            gps = con.execute(
                "SELECT (SELECT value_raw FROM cards WHERE frame_id = ? AND keyword = 'SITELAT' "
                "        ORDER BY idx LIMIT 1), "
                "       (SELECT value_raw FROM cards WHERE frame_id = ? AND keyword = 'SITELONG' "
                "        ORDER BY idx LIMIT 1)", (frame_id, frame_id)).fetchone()
            g.cleared_gps += site_coords(gps[0], gps[1]) is not None
            if dry:
                continue
            con.execute("UPDATE frame SET observatory_id = NULL, observatory_source = NULL "
                        "WHERE id = ?", (frame_id,))
            emit_event(con, actor=actor, verb="observatory.unassigned", target=f"frame:{frame_id}",
                       now=now, payload={"observatory_id": fr["observatory_id"],
                                         "observatory_source": fr["observatory_source"]},
                       reason="ręka cofnęła wskazanie stanowiska")
    g.frame_ids = tuple(zapisane)
    g.cleared_from = tuple(sorted(zrodla))
    return g


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


def stage_pending_replacing(con, *, run_id, preview):
    """Dopisz wpis stagingu z EDYCJI KOMÓRKI gridu (AR-61), zastępując oczekujący wpis tej samej karty
    tej samej kopii w tym samym przebiegu. Jedna transakcja: zdjęcie i wstawienie razem albo wcale.

    Zastąpienie, nie dopisanie, bo druga edycja tej samej komórki jest POPRAWKĄ pierwszej, a dwa
    wpisy `set` jednej karty w jednym przebiegu zapisałyby oba po kolei - plik dostałby wartość
    zależną od kolejności, a podgląd pokazywałby tylko ostatnią. Klucz to `(run_id, location_id,
    keyword)` i status `pending`: wpis makra tej samej karty w tym przebiegu też ustępuje edycji
    ręcznej (ostatnie słowo człowieka), a wpisy już rozstrzygnięte przez commit zostają nietknięte.
    `preview` = obiekt z polami `macro.PendingPreview`. Transient - bez eventu, jak `stage_pending`.
    Zwraca `(id nowego wpisu, liczba zastąpionych)`."""
    with con:
        zdjete = con.execute(
            "DELETE FROM pending_changes WHERE run_id = ? AND location_id = ? AND keyword = ? "
            "AND status = 'pending'", (run_id, preview.location_id, preview.keyword)).rowcount
        cur = _insert_pending(con, (run_id, preview.location_id, preview.keyword, preview.idx,
                                    preview.op, preview.old_value, preview.new_value,
                                    preview.new_type, preview.comment,
                                    preview.expected_header_hash))
    return cur.lastrowid, zdjete


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
    """Ustaw status wpisu stagingu ('applied'|'failed'|'skipped'|'blocked') + powód (`PowodPozycji`,
    proza albo `None`). Transient. W zakresie `atomic` dołącza do niego (commit drogą atomową zamyka
    plik jedną transakcją)."""
    with _tx(con):
        con.execute("UPDATE pending_changes SET status = ? WHERE id = ?", (status, pending_id))
        _set_pending_reason_tx(con, [pending_id], reason)


def _set_pending_reason_tx(con, ids, powod):
    """JEDYNY pisarz powodu wpisu stagingu karty (AR-148, meta-test): trójka `reason`/`reason_code`/
    `reason_args` z kodeka `item_reasons.do_bazy` jednym UPDATE dla wpisów `ids` - proza i kod nigdy
    się nie rozjadą (CHECK 0042). `powod` = `PowodPozycji`, proza bez kodu albo `None` (czyści
    trójkę). Pod transakcją wołającego."""
    con.execute("UPDATE pending_changes SET reason = ?, reason_code = ?, reason_args = ? "
                "WHERE id IN (SELECT value FROM json_each(?))",
                (*do_bazy(powod), json.dumps([int(i) for i in ids])))


def clear_pending_for_run(con, run_id):
    """Skasuj staging przebiegu (idempotentne ponowne uruchomienie makra / „Odrzuć" w szufladzie).
    DELETE sankcjonowany: pending_changes to LUSTRO oczekujących zmian, nie historia (historia =
    event). Transient - bez eventu.

    WPISY ZWIĄZANE Z OPERACJĄ ZAPISU W MIEJSCU ZOSTAJĄ (`inplace_op_id` NOT NULL): po zapisie, którego
    dokończenie padło (lokacja w fazie `written`), `finish_inplace` szuka ich po operacji i dopiero
    wtedy oznacza je 'applied' i gasi nagrobek ręki - okno karty porzucające staging po przerwaniu
    zostawiłoby dokończenie bez wpisów (AR-117: oba okna kart piszą dziś w miejscu)."""
    with con:
        con.execute("DELETE FROM pending_changes WHERE run_id = ? AND inplace_op_id IS NULL",
                    (run_id,))


def insert_commit(con, *, run_id, now, summary=None):
    """Utwórz wiersz `commits` (grupuje przebieg do undo). Zwraca commit_id. Transient — wskaźnik
    grupujący, nie event (mutacje plików niosą eventy re-syncu)."""
    with con:
        cur = con.execute(
            "INSERT INTO commits(run_id, applied_at, summary) VALUES (?, ?, ?)",
            (run_id, now, summary))
    return cur.lastrowid


def insert_header_backup(con, *, commit_id, location_id, hdu_index, header_text, post_hash,
                         pending_since=None, pending_rows=None, intent=None):
    """Zapisz backup pełnego nagłówka SPRZED commitu (undo). `post_hash` = header_hash PO commicie
    (kontrola undo). Append-only: nigdy nie kasowany. Transient - bez eventu. Zwraca id backupu
    (`mark_backup_unreplaced`, gdy pisarz potem pliku nie podmieni).

    `pending_since` (0030, AR-40) = chwila utrwalenia backupu drogi atomowej PRZED podmianą: backup
    jest NIEPOTWIERDZONY, dopóki pisarz nie potwierdzi podmiany (`confirm_backup_replaced`, w tej
    samej transakcji co podmiana), straż jej nie odbije (`mark_backup_unreplaced`) albo rekoncyliacja
    z dyskiem nie rozstrzygnie (`settle_pending_backup`). `None` = backup bez tego cyklu (droga
    w miejscu - stan niesie dziennik `inplace_op`).

    `pending_rows` (0030) = wiersze stagingu, które TA próba zapisuje (`pending_changes` z polami
    `id, keyword, idx, op, new_value, new_type, new_comment`): rekoncyliacja potwierdza wyłącznie
    wpisy zgodne z nimi co do `id` i treści, nie wpisy dodane później pod tym samym `run_id`
    (bramka astra, A5).

    `hand_version` (0037, AR-82) = wersja decyzji ręki o obiekcie klatki (`hand_version`) liczona
    w TEJ transakcji - przed pierwszym bajtem zapisu pliku; wstrzymanie zapisu ją dziedziczy.

    `intent` (0038, AR-64) = zamiar podmiany drogi atomowej (obiekt z polami `displaced_path`,
    `return_path`, `prepared_path`, `prepared_sha1`, `prepared_size`) - utrwalony W TEJ transakcji
    co backup, przed pierwszą podmianą (`replace_intent`, faza `prepared`). `None` = droga bez
    podmiany systemowej (w miejscu) albo wołający bez zamiaru (testy, import)."""
    proba = None if pending_rows is None else json.dumps([_wpis_proby(r) for r in pending_rows])
    if intent is not None and pending_since is None:
        raise ValueError("zamiar podmiany bez backupu niepotwierdzonego - nie ma czego rekoncyliować")
    with con:
        reka = _hand_version_of_location(con, location_id)
        cur = con.execute(
            "INSERT INTO header_backups(commit_id, location_id, hdu_index, header_text, post_hash, "
            "pending_since, pending_rows, hand_version) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (commit_id, location_id, hdu_index, header_text, post_hash, pending_since, proba, reka))
        if intent is not None:
            con.execute(
                "INSERT INTO replace_intent(backup_id, displaced_path, return_path, prepared_path, "
                "prepared_sha1, prepared_size, opened_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (cur.lastrowid, intent.displaced_path, intent.return_path, intent.prepared_path,
                 intent.prepared_sha1, intent.prepared_size, pending_since))
    return cur.lastrowid


def replace_intent(con, backup_id):
    """Zamiar podmiany backupu (0038) albo `None` (backup bez zamiaru - reguła dawna)."""
    return con.execute("SELECT * FROM replace_intent WHERE backup_id = ?", (backup_id,)).fetchone()


def atomic_undos(con, backup_id):
    """Ślady cofnięć backupu drogą atomową (0044, AR-182), od najstarszego - pusta lista dla backupu
    cofanego wyłącznie w miejscu albo przed 0044."""
    return con.execute("SELECT * FROM atomic_undo WHERE backup_id = ? ORDER BY id",
                       (backup_id,)).fetchall()


def mark_location_rescan(con, *, location_id, now, reason, actor="user:local"):
    """TRWAŁY ZNACZNIK „PRZECZYTAJ OD NOWA” (AR-64, C7): `location.mtime` → NULL, więc brama
    przyrostowa skanu nie pominie pliku (NULL nie równa się niczemu) - jak przy drodze powrotu
    zapisu w miejscu (`revert_inplace_op`). Ślad `location.rescan_marked` z `mtime` sprzed i powodem.
    Wołane PRZED werdyktem powrotu cudzej wersji: baza mogła przyjąć naszą wersję skanem po śmierci
    procesu, a od werdyktu pod ścieżką stoi cudza."""
    with _immediate(con):
        row = con.execute("SELECT mtime FROM location WHERE id = ?", (location_id,)).fetchone()
        if row is None:
            raise ValueError(f"location:{location_id} nie istnieje")
        if row["mtime"] is None:
            return
        con.execute("UPDATE location SET mtime = NULL WHERE id = ?", (location_id,))
        emit_event(con, actor=actor, verb="location.rescan_marked", target=f"location:{location_id}",
                   now=now, payload={"mtime_before": row["mtime"], "reason": reason})


def mark_intent_returning(con, *, backup_id, displaced_sha1, displaced_size):
    """FAZA `returning` (AR-64, Z11): rekoncyliacja utrwala pełny sha1 i rozmiar wersji innego pisarza
    (B, zastanej pod nazwą kopii) PRZED powrotem jej pod ścieżkę. CAS z `prepared` (inaczej
    `ValueError` - inny proces prowadzi powrót). Transient - bez eventu."""
    with _immediate(con):
        n = con.execute(
            "UPDATE replace_intent SET phase = 'returning', displaced_sha1 = ?, displaced_size = ? "
            "WHERE backup_id = ? AND phase = 'prepared'",
            (displaced_sha1, displaced_size, backup_id)).rowcount
        if n != 1:
            raise ValueError(f"zamiar backupu {backup_id} nie jest w fazie 'prepared'")


def mark_intent_returned(con, *, backup_id):
    """FAZA `returned` (AR-64, Z11): powrót wykonany i sprawdzony pełnym sha1 (pod ścieżką B, pod kopią
    zwrotną N) - zostaje sprzątnięcie kopii zwrotnej i werdykt. CAS z `returning`. Bez eventu."""
    with _immediate(con):
        n = con.execute("UPDATE replace_intent SET phase = 'returned' "
                        "WHERE backup_id = ? AND phase = 'returning'", (backup_id,)).rowcount
        if n != 1:
            raise ValueError(f"zamiar backupu {backup_id} nie jest w fazie 'returning'")


_POLA_PROBY = ("id", "keyword", "idx", "op", "new_value", "new_type", "new_comment")


def _wpis_proby(row):
    """Wpis stagingu jako lista pól `_POLA_PROBY` - tożsamość wpisu próby (A5): `id` i treść."""
    return [row[k] for k in _POLA_PROBY]


def mark_backup_unreplaced(con, *, backup_id, now):
    """BACKUP BEZ PODMIANY (0024, AR-37): pisarz drogi atomowej utrwalił backup, a potem oddał
    wynik bez `backup_text`, bo straż podmiany odbiła `os.replace` - plik nietknięty. Wyjątek przy
    samej podmianie znacznika nie daje (rename mógł zajść mimo błędu). `unreplaced_at` = `now`; cofnięcie commitu taki backup pomija, zamiast meldować
    blokadę o pliku, którego commit nie ruszył. Wiersz już oznaczony zostaje bez zmian (pierwsza
    chwila). Backup sam zostaje (append-only). Transient - bez eventu. Znacznik rozstrzyga też
    backup niepotwierdzony (`pending_since` → NULL, 0030). Zamiar podmiany (0038) w fazie
    `prepared` zamyka się w tej samej transakcji jako `not_replaced` - podmiany nie było (C1)."""
    with con:
        con.execute("UPDATE header_backups SET unreplaced_at = ?, pending_since = NULL "
                    "WHERE id = ? AND unreplaced_at IS NULL", (now, backup_id))
        con.execute("UPDATE replace_intent SET phase = 'closed', outcome = 'not_replaced', "
                    "closed_at = ? WHERE backup_id = ? AND phase = 'prepared'", (now, backup_id))


def confirm_backup_replaced(con, *, backup_id, now):
    """PODMIANA POTWIERDZONA (0030, AR-40): pisarz drogi atomowej woła to w transakcji straży
    podmiany (`guard_file_replace`), zaraz po udanej podmianie systemowej i kontroli pliku
    wypartego - backup przestaje być niepotwierdzony. Zdejmuje też `unreplaced_at`: rekoncyliacja
    innego procesu mogła go postawić w oknie między utrwaleniem backupu a podmianą (widziała na
    dysku nagłówek sprzed commitu), a pisarz wie lepiej - podmiana zaszła. Transient - bez eventu.
    Zamiar podmiany (0038) zamyka się w tej samej transakcji jako `replaced` (C1): otwarty zamiar
    znaczy odtąd wyłącznie „podmiana nierozstrzygnięta”."""
    with _immediate(con):
        con.execute("UPDATE header_backups SET pending_since = NULL, unreplaced_at = NULL "
                    "WHERE id = ?", (backup_id,))
        con.execute("UPDATE replace_intent SET phase = 'closed', outcome = 'replaced', "
                    "closed_at = ? WHERE backup_id = ?", (now, backup_id))


def record_atomic_undo(con, *, backup_id, result_sha1, result_size, result_hash, byte_exact,
                       source_sha1, source_size, displaced_path, prepared_path, now):
    """ŚLAD COFNIĘCIA DROGĄ ATOMOWĄ (0044, AR-182): co cofnięcie backupu położy pod ścieżką (wynik:
    sha1, rozmiar, nagłówek, `byte_exact`), co pod nią zastało (źródło) i jakie pliki może zostawić
    na dysku (kopia wyparta, plik tymczasowy - AR-127). Utrwalany PRZED podmianą (reguła „backup
    przed `os.replace`” z 2026-09-26): ponowienie rozpozna po nim własny wynik także po śmierci
    procesu w oknie podmiany. Dlatego ślad musi być ZATWIERDZONY, zanim plik się ruszy - wołanie
    w otwartej transakcji (np. w zakresie `atomic`, który wycofałby go razem z błędem po podmianie)
    to błąd wołającego (EXPECT, `ValueError`, zero zapisu). Append-only; staging pisarza - bez
    eventu. Zwraca id śladu (`mark_atomic_undo_synced`)."""
    if con.in_transaction:
        raise ValueError("ślad cofnięcia w otwartej transakcji - nie byłby zatwierdzony przed "
                         "podmianą pliku")
    with con:
        cur = con.execute(
            "INSERT INTO atomic_undo(backup_id, result_sha1, result_size, result_hash, byte_exact, "
            "source_sha1, source_size, displaced_path, prepared_path, recorded_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (backup_id, result_sha1, result_size, result_hash,
             None if byte_exact is None else int(bool(byte_exact)), source_sha1, source_size,
             displaced_path, prepared_path, now))
    return cur.lastrowid


def mark_atomic_undo_synced(con, *, undo_id, now):
    """WYNIK COFNIĘCIA WCIĄGNIĘTY (0044, AR-182): baza opisuje plik, który zapisało cofnięcie
    o śladzie `undo_id` - w transakcji re-syncu cofnięcia albo rozliczenia „już cofnięte” (dołącza
    do zakresu `atomic` wołającego). Pierwsza chwila zostaje: ślad już oznaczony → `False` bez zmian;
    oznacza WYŁĄCZNIE wskazany ślad, nigdy starszą próbę z tym samym wynikiem. Bez eventu."""
    with _immediate(con):
        n = con.execute("UPDATE atomic_undo SET synced_at = ? WHERE id = ? AND synced_at IS NULL",
                        (now, undo_id)).rowcount
    return n == 1


def pending_header_backups(con, location_id):
    """Backupy drogi atomowej lokacji NIEPOTWIERDZONE (`pending_since`, 0030): proces zginął albo
    podmiana rzuciła między utrwaleniem backupu a potwierdzeniem. Zbiór pusty w zwykłym biegu, więc
    bramka commitu i cofnięcia kosztuje jedno zapytanie."""
    return con.execute(
        "SELECT hb.id, hb.commit_id, hb.location_id, hb.header_text, hb.post_hash, "
        "       hb.pending_since, c.run_id "
        "FROM header_backups hb JOIN commits c ON c.id = hb.commit_id "
        "WHERE hb.location_id = ? AND hb.pending_since IS NOT NULL ORDER BY hb.id",
        (location_id,)).fetchall()


class BackupAlreadySettled(Exception):
    """Backup przestał być niepotwierdzony między odczytem a rozstrzygnięciem - inny proces
    (pisarz albo rekoncyliacja) zdążył go rozstrzygnąć. Zero zapisu."""


def _zamknij_zamiar(con, *, backup_id, location_id, outcome, kept_paths, now):
    """Zamknięcie zamiaru podmiany (0038) RAZEM z werdyktem backupu - w transakcji wołającego.
    Backup z zamiarem wymaga `outcome` (EXPECT: werdykt ustala automat pełnego sha1, nie nagłówek),
    backup bez zamiaru - nie dopuszcza go. `kept`: zdarzenie `location.displaced_kept` ze
    ścieżkami plików, które zostają na dysku do oka (skan ich nie widzi - sufiks kopii), a pliki
    leżące OBOK ścieżki lokacji idą do `replace_intent.kept_paths` - stan wiersza Porządków (C8)."""
    zamiar = con.execute("SELECT phase FROM replace_intent WHERE backup_id = ?",
                         (backup_id,)).fetchone()
    if zamiar is None:
        if outcome is not None:
            raise ValueError(f"backup {backup_id} bez zamiaru podmiany, a werdykt {outcome!r}")
        return
    if outcome is None or zamiar["phase"] == "closed":
        raise ValueError(f"zamiar backupu {backup_id}: werdykt {outcome!r} przy fazie "
                         f"{zamiar['phase']!r}")
    sciezka = con.execute("SELECT path FROM location WHERE id = ?", (location_id,)).fetchone()
    obok = [s for s in kept_paths if sciezka is None or s != sciezka["path"]]
    con.execute("UPDATE replace_intent SET phase = 'closed', outcome = ?, closed_at = ?, "
                "kept_paths = ? WHERE backup_id = ?",
                (outcome, now, json.dumps(obok if outcome == "kept" else []), backup_id))
    if outcome == "kept":
        emit_event(con, actor="user:local", verb="location.displaced_kept",
                   target=f"location:{location_id}", now=now,
                   payload={"backup_id": backup_id, "paths": list(kept_paths)})


def settle_pending_backup(con, *, backup_id, replaced, now, intent_outcome=None, kept_paths=()):
    """REKONCYLIACJA BACKUPU NIEPOTWIERDZONEGO z dyskiem (0030, AR-40) - JEDNA transakcja, CAS na
    `pending_since IS NOT NULL` (inaczej `BackupAlreadySettled`, zero zapisu). Co jest na dysku,
    rozstrzyga wołający (`writeback`); tu zapisuje się werdykt:

      * `replaced=True` - na dysku leży nagłówek zapisany przez commit (`post_hash`): podmiana
        zaszła. Backup potwierdzony; zwrot = `id` wpisów stagingu TEJ PRÓBY (`pending_rows`: `id`
        i treść, A5), które commit zostawił bez rozstrzygnięcia ('pending' po śmierci procesu,
        'failed' po błędzie samej podmiany); wpis dodany później pod tym samym `run_id` (ponowny
        staging) do zwrotu nie wchodzi - do pliku nie trafił. Wołane w transakcji re-syncu pliku
        (`repo.atomic`) PRZED wjazdem rekordu (CAS odmawia, zanim cokolwiek się stanie); status
        wpisów i nagrobek rozlicza PO wjeździe `settle_backup_attempt` - dopiero wtedy wiadomo, czy
        zeznanie przyjęło zapis (AR-82);
      * `replaced=False` - na dysku nagłówek sprzed commitu: podmiany nie było → `unreplaced_at`
        (cofnięcie pomija), wpisy stagingu bez zmian (ponowny commit je zapisze);
      * `replaced=None` - nagłówek ani jeden, ani drugi (plik zmienił się poza programem):
        NIEROZSTRZYGNIĘTE - backup bez dowodu wykonania nie może cofać (bramka astra, A3: późniejszy
        commit, który zapisze ten sam nagłówek wynikowy, przepuściłby kontrolę `post_hash`
        i cofnięcie tego commitu cofnęłoby tamten). Stąd też `unreplaced_at` - backup zostaje
        w tabeli (append-only), ze zwykłego cofnięcia wypada. Wpisy stagingu bez zmian.
    Transient (backup, staging) bez eventu. Zwraca listę `id` wpisów próby (pustą przy
    `replaced` innym niż `True`).

    ZAMIAR PODMIANY (0038, AR-64): backup z zamiarem zamyka go w TEJ transakcji z werdyktem
    automatu pełnego sha1 (`intent_outcome`; `kept_paths` - pliki zostawione do oka, zdarzenie
    `location.displaced_kept`)."""
    with _immediate(con):
        b = con.execute(
            "SELECT hb.commit_id, hb.location_id, hb.pending_rows, c.run_id FROM header_backups hb "
            "JOIN commits c ON c.id = hb.commit_id "
            "WHERE hb.id = ? AND hb.pending_since IS NOT NULL", (backup_id,)).fetchone()
        if b is None:
            raise BackupAlreadySettled(f"backup {backup_id} nie jest już niepotwierdzony")
        _zamknij_zamiar(con, backup_id=backup_id, location_id=b["location_id"],
                        outcome=intent_outcome, kept_paths=kept_paths, now=now)
        if replaced is not True:
            con.execute("UPDATE header_backups SET pending_since = NULL, unreplaced_at = ? "
                        "WHERE id = ?", (now, backup_id))
            return []
        con.execute("UPDATE header_backups SET pending_since = NULL WHERE id = ?", (backup_id,))
        proba = json.loads(b["pending_rows"] or "[]")
        kandydaci = con.execute(
            "SELECT id, keyword, idx, op, new_value, new_type, new_comment FROM pending_changes "
            "WHERE id IN (SELECT value FROM json_each(?)) AND location_id = ? "
            "AND status IN ('pending', 'failed') AND inplace_op_id IS NULL "
            "AND withheld_id IS NULL",      # B9: wpisy wstrzymane rozlicza wyłącznie `_settle_withheld_tx`
            (json.dumps([w[0] for w in proba]), b["location_id"])).fetchall()
        ids = [r["id"] for r in kandydaci if _wpis_proby(r) in proba]      # id I treść tej próby
        # Wpisy próby są NIEROZSTRZYGNIĘTE do `settle_backup_attempt` po wjeździe: 'failed' po
        # błędzie samej podmiany wraca do 'pending', żeby skan potwierdzający w tej samej
        # transakcji (`confirm_failed_commit_by_scan`) nie rozliczył ich drugi raz (A4).
        con.execute("UPDATE pending_changes SET status = 'pending' "
                    "WHERE id IN (SELECT value FROM json_each(?)) AND status = 'failed'",
                    (json.dumps(ids),))
    return ids


def settle_backup_attempt(con, *, backup_id, pending_ids, testimony_ok, now, withheld_reason=None,
                          actor="user:local"):
    """DRUGA POŁOWA rekoncyliacji backupu potwierdzonego z dysku (AR-40 + AR-82) - wołana w tej
    samej transakcji re-syncu co `settle_pending_backup(replaced=True)`, ale PO wjeździe rekordu,
    gdy wiadomo, czy zeznanie klatki przyjęło zapisany nagłówek (`testimony_ok`, dowód
    `writeback._resync`). `pending_ids` = wpisy tej próby (zwrot `settle_pending_backup`).

      * `testimony_ok=True` - wpisy → 'applied' z powodem potwierdzenia, a gdy któryś wpisał
        `OBJECT` - zgaszenie nagrobka ręki z parą commit/plik (cofnięcie go odtworzy), wyłącznie
        przy wersji decyzji ręki z backupu (`_clear_tombstone_same_hand_tx`, B12);
      * `False` - zapis wstrzymany (`withhold_write`, powód `withheld_reason`): wpisy 'failed'
        z wiązaniem, nagrobek nietknięty. Dawniej oba wypadki dawały 'applied' i zgaszenie.
    Zwraca liczbę rozliczonych wpisów."""
    with _immediate(con):
        b = con.execute("SELECT commit_id, location_id, post_hash, hand_version FROM header_backups "
                        "WHERE id = ?", (backup_id,)).fetchone()
        if b is None:
            raise ValueError(f"backup {backup_id} nie istnieje")
        ids = json.dumps([int(i) for i in pending_ids])
        if not testimony_ok:
            _withhold_write_tx(con, kind="commit", location_id=b["location_id"],
                               commit_id=b["commit_id"], header_hash=b["post_hash"],
                               pending_ids=pending_ids, backup_id=backup_id,
                               reason=withheld_reason, now=now)
            return len(pending_ids)
        wpisy = con.execute("SELECT keyword FROM pending_changes WHERE id IN "
                            "(SELECT value FROM json_each(?))", (ids,)).fetchall()
        # Nagrobek - wyłącznie przy wersji decyzji ręki sprzed zapisu (B12): proces zginął po
        # podmianie, a do rekoncyliacji człowiek mógł wykluczyć obiekt ponownie.
        uwaga = None
        if any(w["keyword"] == "OBJECT" for w in wpisy):
            loc = con.execute("SELECT frame_id FROM location WHERE id = ?",
                              (b["location_id"],)).fetchone()
            uwaga = _clear_tombstone_same_hand_tx(
                con, frame_id=loc["frame_id"], hand_version=b["hand_version"],
                commit_id=b["commit_id"], location_id=b["location_id"], now=now, actor=actor)
        powod = PowodPozycji(f"potwierdzone z dysku: nagłówek na dysku = zapisany w commicie "
                             f"{b['commit_id']} (przerwany przed potwierdzeniem podmiany)",
                             "confirmed_from_disk_cut", commit_id=b["commit_id"])
        con.execute("UPDATE pending_changes SET status = 'applied' "
                    "WHERE id IN (SELECT value FROM json_each(?))", (ids,))
        _set_pending_reason_tx(con, pending_ids, dopisz(powod, uwaga))
    return len(wpisy)


# ============================================================ ZAPIS Z ZEZNANIEM WSTRZYMANYM (0037, AR-82)
# Plik zapisany, a zeznanie klatki (`header`/`cards`) nie przyjęło jego nagłówka, bo głosem klatki
# mówi inna obecna kopia (AR-4). Wiersz `withheld_write` czeka na dokończenie: dowód, że zeznanie
# opisuje plik tej kopii (przejęcie gestem albo Dostawą, pełny odczyt przy kopii wiodącej, ponowny
# re-sync) - wtedy wpisy stagingu 'applied', nagrobek ręki (tylko przy tej samej wersji decyzji
# ręki, co przed zapisem) i pozycja gestu. Pełny odczyt, który dowodzi nowszego stanu lokacji (inny
# nagłówek, inna klatka), zamyka go jako `superseded`; cofnięcie commitu - jako `undone`.


def _hand_version(con, frame_id):
    """WERSJA DECYZJI RĘKI o obiekcie klatki: `id` najnowszego zdarzenia, które ustanowiło nagrobek
    (`object.cleared`, `object.tombstone_restored`), gdy klatka ma `user_cleared`; `0`, gdy klatka
    nagrobka nie ma. Nowsza decyzja człowieka = inna wersja - późne dokończenie zapisu jej nie zgasi
    (Z5). `None` zostaje dla stanu bez wersji: wiersz sprzed 0037 albo nagrobek bez zdarzenia."""
    fr = con.execute("SELECT object_source FROM frame WHERE id = ?", (frame_id,)).fetchone()
    if fr is None or fr["object_source"] != "user_cleared":
        return 0
    return con.execute(
        "SELECT MAX(id) FROM event WHERE target = ? "
        "AND verb IN ('object.cleared', 'object.tombstone_restored')",
        (f"frame:{frame_id}",)).fetchone()[0]


def _hand_version_of_location(con, location_id):
    loc = con.execute("SELECT frame_id FROM location WHERE id = ?", (location_id,)).fetchone()
    return None if loc is None else _hand_version(con, loc["frame_id"])


_POWOD_NOWSZEJ_REKI = PowodPozycji("nowsza decyzja ręki o obiekcie klatki zostaje", "hand_newer")
_POWOD_REKI_NIEZNANEJ = PowodPozycji("wersja decyzji ręki sprzed aktualizacji nieznana - nagrobek "
                                     "zostaje do oka", "hand_unknown")


def _clear_tombstone_same_hand_tx(con, *, frame_id, hand_version, commit_id, location_id, now,
                                  actor):
    """ZGASZENIE NAGROBKA PRZY PÓŹNYM DOKOŃCZENIU ZAPISU `OBJECT` (Z5, B10, B12) - jeden właściciel
    reguły dla trzech dróg: dokończenie wstrzymania (`_settle_withheld_tx`), skan potwierdzający
    commit 'failed' (`confirm_failed_commit_by_scan`) i rekoncyliacja backupu
    (`settle_backup_attempt`). Gasi wyłącznie, gdy wersja decyzji ręki utrwalona przed pierwszym
    bajtem zapisu (`header_backups.hand_version`) jest wersją bieżącą - między zapisem a późnym
    dokończeniem człowiek mógł wykluczyć obiekt ponownie, a automat nie odwołuje nowszej decyzji.
    Zwraca `None` (zgaszone albo klatka bez nagrobka) albo dopisek powodu, czemu nagrobek zostaje:
    nowsza decyzja ręki, albo wersja nieznana (backup sprzed 0037 - prawdy nie da się ustalić)."""
    zrodlo = con.execute("SELECT object_source FROM frame WHERE id = ?",
                         (frame_id,)).fetchone()["object_source"]
    if zrodlo != "user_cleared":
        return None
    if hand_version is None:
        return _POWOD_REKI_NIEZNANEJ
    if _hand_version(con, frame_id) != hand_version:
        return _POWOD_NOWSZEJ_REKI
    _clear_object_tombstone_tx(con, frame_id=frame_id, now=now, actor=actor, commit_id=commit_id,
                               location_id=location_id)
    return None


def clear_tombstone_after_write(con, *, frame_id, backup_id, commit_id, location_id, now,
                                actor="user:local"):
    """Zgaszenie nagrobka po zapisie karty `OBJECT` drogą atomową (`writeback._zapisz_lokacje`,
    w transakcji re-syncu) - wyłącznie przy wersji decyzji ręki z backupu tej próby, utrwalonej
    przed pierwszym bajtem (Z8, `_clear_tombstone_same_hand_tx`). Zwraca `None` albo dopisek
    powodu, czemu nagrobek zostaje."""
    with _immediate(con):
        reka = con.execute("SELECT hand_version FROM header_backups WHERE id = ?",
                           (backup_id,)).fetchone()["hand_version"]
        return _clear_tombstone_same_hand_tx(con, frame_id=frame_id, hand_version=reka,
                                             commit_id=commit_id, location_id=location_id,
                                             now=now, actor=actor)


def withhold_write(con, *, kind, location_id, commit_id, header_hash, reason, now, pending_ids=(),
                   inplace_op_id=None, backup_id=None, actor="user:local", item_note=None):
    """ZAPIS WSTRZYMANY - jedna transakcja (albo transakcja wołającego w `atomic`): wiersz
    `withheld_write` i wpisy stagingu `pending_ids` → 'failed' z `reason` i wiązaniem `withheld_id`.
    Zwraca `id` wstrzymania. Kontrakt pól w `_withhold_write_tx`."""
    with _immediate(con):
        return _withhold_write_tx(con, kind=kind, location_id=location_id, commit_id=commit_id,
                                  header_hash=header_hash, reason=reason, now=now,
                                  pending_ids=pending_ids, inplace_op_id=inplace_op_id,
                                  backup_id=backup_id, actor=actor, item_note=item_note)


def _withhold_write_tx(con, *, kind, location_id, commit_id, header_hash, reason, now,
                       pending_ids=(), inplace_op_id=None, backup_id=None, actor="user:local",
                       item_note=None):
    """Rdzeń `withhold_write` BEZ własnej transakcji.

      * `kind='commit'` wymaga `backup_id` (EXPECT): wersja decyzji ręki przychodzi z backupu,
        utrwalona przed pierwszym bajtem zapisu (Z8) - liczona teraz widziałaby decyzję człowieka
        z okna między zapisem a re-synciem jako starą i dokończenie by ją zgasiło;
        `object_written` = któryś z wpisów wpisał `OBJECT`;
      * `kind='undo'` - bez wpisów, bez nagrobka (cofnięcie odtwarza go samo).
    `item_id` = pozycja gestu „Zmień obiekt”/„Uzgodnij” tej lokacji w przebiegu commitu (jedno
    źródło: `run_id` commitu), żeby dokończenie domknęło też ją. Przy `kind='commit'` pozycja
    dostaje 'failed' z tym samym powodem W TEJ transakcji (B4): status pozycji i wstrzymanie
    powstają razem, więc dokończenie z innego połączenia nie trafi na pozycję jeszcze 'pending',
    a sterownik gestu nie nadpisze potem pozycji już domkniętej. `item_note` = uwaga dopisana
    WYŁĄCZNIE do powodu pozycji (spadek karty na drogę atomową, AR-141): pozycja mówi to samo, co
    wynik sterownika, a wpisy stagingu i wiersz wstrzymania zostają przy `reason`. `actor` = aktor
    zapisu: pod nim skan dociąga później zeznanie przy dokończeniu (B8), nie pod własnym."""
    if kind not in ("commit", "undo"):
        raise ValueError(f"rodzaj wstrzymania {kind!r} spoza ('commit', 'undo')")
    loc = con.execute("SELECT frame_id FROM location WHERE id = ?", (location_id,)).fetchone()
    if loc is None:
        raise ValueError(f"location:{location_id} nie istnieje")
    ids = json.dumps([int(i) for i in pending_ids])
    reka = None
    zapisal_obiekt = 0
    if kind == "commit":
        if backup_id is None:
            raise ValueError("wstrzymanie commitu bez backupu - brak wersji decyzji ręki sprzed zapisu")
        reka = con.execute("SELECT hand_version FROM header_backups WHERE id = ?",
                           (backup_id,)).fetchone()["hand_version"]
        zapisal_obiekt = int(con.execute(
            "SELECT EXISTS (SELECT 1 FROM pending_changes WHERE keyword = 'OBJECT' "
            "AND id IN (SELECT value FROM json_each(?)))", (ids,)).fetchone()[0])
    elif pending_ids:
        raise ValueError("wstrzymanie cofnięcia nie niesie wpisów stagingu")
    item = con.execute(
        "SELECT p.id FROM pending_object_change p JOIN commits c ON c.run_id = p.run_id "
        "WHERE c.id = ? AND p.location_id = ?", (commit_id, location_id)).fetchone()
    # Trójka powodu z kodeka (AR-148): nota cofnięcia czytana z bazy (`open_undo_withheld_for_item`)
    # mówi w języku UI. Ten INSERT to JEDYNY pisarz `withheld_write.reason` (meta-test).
    wid = con.execute(
        "INSERT INTO withheld_write(kind, location_id, frame_id, commit_id, inplace_op_id, item_id, "
        "header_hash, object_written, hand_version, reason, reason_code, reason_args, actor, "
        "opened_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (kind, location_id, loc["frame_id"], commit_id, inplace_op_id,
         None if item is None else item["id"], header_hash, zapisal_obiekt, reka, *do_bazy(reason),
         actor, now)).lastrowid
    con.execute(
        "UPDATE pending_changes SET status = 'failed', withheld_id = ? "
        "WHERE id IN (SELECT value FROM json_each(?))", (wid, ids))
    _set_pending_reason_tx(con, [int(i) for i in pending_ids], reason)
    if item is not None and kind == "commit":
        if con.execute("UPDATE pending_object_change SET status = 'failed' "
                       "WHERE id = ? AND status IN ('pending', 'failed')", (item["id"],)).rowcount:
            _set_object_change_reason_tx(con, item["id"], dopisz(reason, item_note))
    return wid


def _kopie(n):
    """Fragment „N obecnych kopii” z odmianą PL (1 / 2-4 / 5+ / -naście) - kod `copies`, okno odmienia
    go w języku UI z parametru `n` (wpis mnogi `objchg.item.copies`)."""
    if n == 1:
        return PowodPozycji(f"{n} obecną kopię", "copies", n=n)
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return PowodPozycji(f"{n} obecne kopie", "copies", n=n)
    return PowodPozycji(f"{n} obecnych kopii", "copies", n=n)


def withheld_reason(con, *, location_id, commit_id, undo=False):
    """ZDANIE DLA CZŁOWIEKA o zapisie wstrzymanym (jedno źródło dla pisarza i skanu): co leży na
    dysku, czyj głos niesie zeznanie klatki i jak zapis się dokończy. `undo=True` - cofnięcie.
    `PowodPozycji` (AR-141): liczba kopii i głos klatki to powody-fragmenty z kodem, więc okno
    zmiany obiektu składa zdanie w języku UI także z powodu pozycji zapisanego w bazie."""
    loc = con.execute("SELECT frame_id FROM location WHERE id = ?", (location_id,)).fetchone()
    frame_id = loc["frame_id"]
    n = con.execute("SELECT count(*) FROM location WHERE frame_id = ? AND present = 1",
                    (frame_id,)).fetchone()[0]
    wiodaca = lead_location(con, frame_id)
    glos = PowodPozycji("żadna kopia jednoznacznie", "lead_none")
    if wiodaca is not None:
        sciezka = con.execute("SELECT path FROM location WHERE id = ?", (wiodaca,)).fetchone()[0]
        glos = PowodPozycji(f"kopia {sciezka}", "lead_copy", path=sciezka)
    kopie = _kopie(n)
    if undo:
        return PowodPozycji(
            f"nagłówek PRZYWRÓCONY (commit {commit_id}), ale zeznanie klatki NIE wróciło - klatka "
            f"ma {kopie}, a głosem klatki mówi {glos}; dokończy się samo po wskazaniu tej kopii "
            f"(„Ta kopia prowadzi” w Zbiorach) albo gdy zostanie jedyną obecną kopią klatki",
            "testimony_withheld_undo", commit_id=commit_id, copies=kopie, lead=glos)
    return PowodPozycji(
        f"plik ZAPISANY (backup do cofnięcia w commicie {commit_id}), ale zeznanie klatki NIE "
        f"przyjęło zapisu - klatka ma {kopie}, a głosem klatki mówi {glos}; zapis dokończy się "
        f"samo po wskazaniu tej kopii („Ta kopia prowadzi” w Zbiorach) albo gdy zostanie jedyną "
        f"obecną kopią klatki, inaczej „Cofnij”", "testimony_withheld", commit_id=commit_id,
        copies=kopie, lead=glos)


def open_withheld(con, location_id):
    """Otwarte wstrzymania lokacji (indeks częściowy - zwykły przebieg płaci jedno puste zapytanie)."""
    return con.execute(
        "SELECT id, kind, location_id, frame_id, commit_id, item_id, header_hash, object_written, "
        "hand_version, actor FROM withheld_write WHERE location_id = ? AND settled_at IS NULL "
        "ORDER BY id",
        (location_id,)).fetchall()


def location_by_path(con, *, volume, path):
    """`(id, frame_id)` lokacji `(volume, path)`; brak → `ValueError` (EXPECT: wołający właśnie
    wciągnął rekord tej ścieżki)."""
    row = con.execute("SELECT id, frame_id FROM location WHERE volume = ? AND path = ?",
                      (volume, path)).fetchone()
    if row is None:
        raise ValueError(f"lokacja {volume}:{path} nie istnieje")
    return row


def has_failed_atomic_rows(con, location_id):
    """Czy lokacja ma wpisy stagingu drogi atomowej 'failed' bez wstrzymania - kandydatów
    `confirm_failed_commit_by_scan` (skan liczy dowód zeznania tylko przy trafieniu)."""
    return con.execute(
        "SELECT EXISTS (SELECT 1 FROM pending_changes WHERE location_id = ? AND status = 'failed' "
        "AND inplace_op_id IS NULL AND withheld_id IS NULL)", (location_id,)).fetchone()[0] == 1


def open_undo_withheld_for_item(con, item_id):
    """Otwarte wstrzymanie COFNIĘCIA związane z pozycją gestu (`{"id", "reason"}`) albo `None` -
    sterownik cofnięcia gestu czyta je z bazy, więc przeżywa wznowienie po fazie karty. `reason`
    odtworzony z trójki (`item_reasons.z_bazy`, AR-148): z kodem, gdy wiersz go niesie (od 0042),
    inaczej proza."""
    row = con.execute(
        "SELECT id, reason, reason_code, reason_args FROM withheld_write WHERE item_id = ? "
        "AND kind = 'undo' AND settled_at IS NULL ORDER BY id DESC LIMIT 1", (item_id,)).fetchone()
    if row is None:
        return None
    return {"id": row["id"], "reason": z_bazy(row["reason"], row["reason_code"], row["reason_args"])}


def close_withheld_undone(con, *, commit_id, location_id, now):
    """Cofnięcie commitu zamyka jego OTWARTE wstrzymanie na tej lokacji jako `undone` (zeznanie
    nigdy nie przyjęło zapisu, więc nie ma czego z niego cofać) - w transakcji re-syncu cofnięcia,
    PRZED wjazdem rekordu (inaczej rozliczenie skanu nazwałoby je `superseded`). Wpisy stagingu
    zostają 'failed' z dopiskiem. Zwraca `True`, gdy coś zamknięto."""
    with _immediate(con):
        rows = con.execute(
            "SELECT id FROM withheld_write WHERE commit_id = ? AND location_id = ? "
            "AND kind = 'commit' AND settled_at IS NULL", (commit_id, location_id)).fetchall()
        for r in rows:
            _zamknij_wstrzymanie(con, r["id"], "undone", now, _WSTRZYMANIE_COFNIETE)
    return bool(rows)


# Dopiski zamknięcia wstrzymania do powodu wpisów stagingu (AR-148: z kodem - nota w języku UI).
_WSTRZYMANIE_COFNIETE = PowodPozycji("commit cofnięty, zanim zeznanie klatki przyjęło zapis",
                                     "withheld_undone")
_WSTRZYMANIE_INNA_KLATKA = PowodPozycji("zapis zastąpiony: lokacja należy już do innej klatki",
                                        "withheld_other_frame")
_WSTRZYMANIE_NOWSZY_STAN = PowodPozycji("zapis zastąpiony nowszym stanem pliku (inny nagłówek na "
                                        "dysku)", "withheld_newer_header")


def _zamknij_wstrzymanie(con, withheld_id, jak, now, dopisek):
    """Zamknięcie wstrzymania (`jak`) i dopisek do powodu jego wpisów stagingu. Dopisek idzie przez
    kodek, nie sklejeniem w SQL (AR-148): proza i kod wpisu nie mogą się rozjechać - proza wynikowa
    jest ta sama co dawne `COALESCE(reason || '; ', '') || dopisek`, a nota trafia na listę `notes`
    (proza wiersza bez kodu jedzie w kopercie `prose`)."""
    con.execute("UPDATE withheld_write SET settled_at = ?, settled_how = ? WHERE id = ?",
                (now, jak, withheld_id))
    for w in con.execute("SELECT id, reason, reason_code, reason_args FROM pending_changes "
                         "WHERE withheld_id = ?", (withheld_id,)).fetchall():
        powod = z_bazy(w["reason"], w["reason_code"], w["reason_args"])
        _set_pending_reason_tx(con, [w["id"]], dopisz_z_koperta(powod, dopisek))


def _settle_withheld_tx(con, *, location_id, frame_id, sha1_data, header_hash, testimony_ok, now,
                        actor):
    """ROZLICZENIE otwartych wstrzymań lokacji wobec ŚWIEŻEGO ODCZYTU jej pliku - w transakcji
    wołającego, po zapisie zeznania. Wołający: re-sync zapisu (`writeback._resync` przez wjazd
    rekordu), pełny odczyt skanu przy otwartym wstrzymaniu, przejęcie zeznania (`adopt_testimony`).
    `frame_id`/`sha1_data` = klatka i tożsamość odczytanego rekordu, `header_hash` = jego odcisk,
    `testimony_ok` = dowód, że zeznanie klatki jest TYM odczytem (`testimony_matches`).

    Per wstrzymanie, pierwsza odpowiedź wygrywa:
      1. CAS TOŻSAMOŚCI (Z9): wstrzymanie, lokacja i wołający mówią o tej samej klatce, a klatka
         ma tożsamość rekordu - inaczej lokację przepięto (zmiana danych obrazu) → `superseded`;
      2. odcisk odczytu ≠ odcisk zapisu → nowszy stan pliku (kolejny zapis albo zmiana poza
         programem, widziana pełnym odczytem) → `superseded` (Z10); wpisy zostają 'failed';
      3. dowód zeznania → `completed`: wpisy 'applied', pozycja gestu 'failed' → 'applied',
         nagrobek ręki gaśnie WYŁĄCZNIE, gdy wersja decyzji ręki jest ta sama, co przed zapisem
         (Z5/Z8, `_clear_tombstone_same_hand_tx`) - nowsza albo nieznana decyzja człowieka
         zostaje, a powód to mówi;
      4. brak dowodu → zostaje otwarte.
    Zwraca listę `(withheld_id, settled_how)` rozliczonych."""
    loc = con.execute("SELECT frame_id FROM location WHERE id = ?", (location_id,)).fetchone()
    wynik = []
    for w in open_withheld(con, location_id):
        tozsamosc = con.execute("SELECT sha1_data FROM frame WHERE id = ?",
                                (w["frame_id"],)).fetchone()
        if (loc is None or w["frame_id"] != frame_id or loc["frame_id"] != w["frame_id"]
                or tozsamosc is None or tozsamosc["sha1_data"] != sha1_data):
            _zamknij_wstrzymanie(con, w["id"], "superseded", now, _WSTRZYMANIE_INNA_KLATKA)
            _zastap_pozycje(con, w)
            wynik.append((w["id"], "superseded"))
        elif header_hash != w["header_hash"]:
            _zamknij_wstrzymanie(con, w["id"], "superseded", now, _WSTRZYMANIE_NOWSZY_STAN)
            _zastap_pozycje(con, w)
            wynik.append((w["id"], "superseded"))
        elif testimony_ok:
            powod = PowodPozycji("dokończone: zeznanie klatki przyjęło zapisany nagłówek",
                                 "withheld_completed")
            if w["object_written"]:
                powod = dopisz(powod, _clear_tombstone_same_hand_tx(
                    con, frame_id=frame_id, hand_version=w["hand_version"],
                    commit_id=w["commit_id"], location_id=location_id, now=now, actor=actor))
            con.execute("UPDATE withheld_write SET settled_at = ?, settled_how = 'completed' "
                        "WHERE id = ?", (now, w["id"]))
            wpisy = [r["id"] for r in con.execute(
                "SELECT id FROM pending_changes WHERE withheld_id = ? AND status = 'failed'",
                (w["id"],))]
            con.execute("UPDATE pending_changes SET status = 'applied' "
                        "WHERE id IN (SELECT value FROM json_each(?))", (json.dumps(wpisy),))
            _set_pending_reason_tx(con, wpisy, powod)
            if w["item_id"] is not None and w["kind"] == "commit":
                _domknij_pozycje_wstrzymana(con, w["item_id"], powod)
            wynik.append((w["id"], "completed"))
    return wynik


def _zastap_pozycje(con, w):
    """Pozycja gestu, której karta została zastąpiona nowszym stanem pliku: kroki gestu (baza,
    przeniesienie, zapis karty) zaszły, a dokończenie zeznania już nie zajdzie - pozycja przestaje
    być „stanem częściowym” w Porządkach, a powód mówi prawdę o karcie. Cofnięcie przebiegu działa
    dalej jak dla pozycji zapisanej."""
    if w["item_id"] is not None and w["kind"] == "commit":
        _domknij_pozycje_wstrzymana(con, w["item_id"], PowodPozycji(
            "karta zapisana, potem zastąpiona nowszym stanem pliku - zeznanie z niej nie przeszło",
            "withheld_superseded"))


def _domknij_pozycje_wstrzymana(con, item_id, powod):
    """Pozycja gestu 'failed' po wstrzymaniu → 'applied' z powodem (dokończenie albo zastąpienie);
    pozycja w innym stanie zostaje nietknięta. Pod transakcją wołającego."""
    if con.execute("UPDATE pending_object_change SET status = 'applied' "
                   "WHERE id = ? AND status = 'failed'", (item_id,)).rowcount:
        _set_object_change_reason_tx(con, item_id, powod)


def settle_withheld(con, *, location_id, frame_id, sha1_data, header_hash, testimony_ok, now,
                    actor="user:local"):
    """`_settle_withheld_tx` we własnej transakcji (albo w `atomic` wołającego)."""
    with _immediate(con):
        return _settle_withheld_tx(con, location_id=location_id, frame_id=frame_id,
                                   sha1_data=sha1_data, header_hash=header_hash,
                                   testimony_ok=testimony_ok, now=now, actor=actor)


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
    Straż sama NIE pisze do bazy: backup drogi atomowej utrwala wołający WCZEŚNIEJ, własną transakcją
    (kolejność „backup w bazie przed podmianą" zostaje), więc tu nie ma czym się zakleszczyć.
    Zakres jest `atomic`, więc zapis wołającego w ciele (potwierdzenie podmiany
    `confirm_backup_replaced`, AR-40) wchodzi w TĘ SAMĄ transakcję co podmiana."""
    with atomic(con):
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
            "INSERT INTO header_backups(commit_id, location_id, hdu_index, header_text, post_hash, "
            "hand_version) VALUES (?, ?, ?, ?, ?, ?)",
            (commit_id, location_id, hdu_index, header_text, spec.post_hash,
             _hand_version_of_location(con, location_id)))      # 0037: przed pierwszym bajtem
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
    op = con.execute("SELECT id, kind, location_id, commit_id, phase, post_hash FROM inplace_op "
                     "WHERE id = ?", (op_id,)).fetchone()
    if op is None or op["phase"] != phase:
        raise ValueError(f"operacja {op_id} nie jest w fazie {phase!r} "
                         f"({None if op is None else op['phase']}) - nie ma czego zamykać")
    return op


def finish_inplace_op(con, *, op_id, now, testimony_ok, withheld_reason=None,
                      closed_commit_withheld=False, actor="user:local"):
    """DOKOŃCZENIE operacji zapisu w miejscu - JEDNA transakcja (astra, 2026-09-27): faza `written`
    → `synced` (CAS), wpisy stagingu związane z operacją (`pending_changes.inplace_op_id`, 0023) →
    'applied', a gdy któryś z nich wpisał `OBJECT` - zgaszenie nagrobka ręki klatki tej lokacji tą
    samą klingą co commit drogą atomową, wyłącznie przy wersji decyzji ręki z backupu operacji
    (`_clear_tombstone_same_hand_tx`, Z8); inaczej nagrobek zostaje, a powód wpisów mówi czemu.

    Wołane przez pisarza (`writeback._dokoncz`) pod blokadą pliku, PO udanej kontroli danych
    i re-syncu. Dawniej faza, statusy i nagrobek szły trzema osobnymi transakcjami, a dokończenie
    szukało wierszy po statusie 'failed': crash po `written` zostawiał wiersze 'pending' na zawsze.
    Teraz te trzy fakty albo zachodzą razem, albo wcale - i dotyczą DOKŁADNIE wierszy operacji, nie
    wszystkich wierszy przebiegu. Operacja nie w fazie `written` → `ValueError`, zero zapisu.
    Operacja `undo` w tej samej transakcji ODTWARZA nagrobek zgaszony przez cofany commit
    (`_restore_object_tombstone_tx`, AR-38).
    Transient (faza, staging) bez eventu; nagrobek emituje swój. Zwraca `id` założonego
    wstrzymania (AR-82) albo `None`.

    `testimony_ok` (AR-82, wymagany) - dowód re-syncu, że zeznanie klatki przyjęło nagłówek pliku
    (`writeback._resync`). `False`: faza i tak `synced` (plik zgodny, izolacja schodzi), ale zapis
    operacji `commit` jest WSTRZYMANY (`withhold_write`, powód `withheld_reason`, wersja decyzji ręki
    z backupu tej operacji) - wpisy 'failed' z wiązaniem, nagrobek nietknięty; operacja `undo`
    odtwarza nagrobek jak zawsze i zakłada wstrzymanie cofnięcia (nagłówek wrócił, zeznanie nie) -
    chyba że `closed_commit_withheld`: TO cofnięcie zamknęło jako `undone` OTWARTE wstrzymanie
    cofanego commitu (zeznanie nigdy go nie przyjęło, więc nie ma czego z niego cofać). Samo
    istnienie historii wstrzymań (`completed`, `superseded`) tego nie znaczy (B2).

    Wołane w transakcji re-syncu dokończenia (`writeback._dokoncz`, `w_transakcji`, B1): dowód
    zeznania, faza, staging i wstrzymanie wchodzą razem - inne połączenie nie przestawi zeznania
    między dowodem a rozliczeniem."""
    with _immediate(con):
        op = _op_in_phase(con, op_id, "written")
        con.execute("UPDATE inplace_op SET phase = 'synced', reason = NULL, closed_at = ? "
                    "WHERE id = ? AND phase = 'written'", (now, op_id))
        rows = con.execute("SELECT id, keyword FROM pending_changes WHERE inplace_op_id = ?",
                           (op_id,)).fetchall()
        if not testimony_ok and op["kind"] == "commit":
            backup = con.execute(
                "SELECT id FROM header_backups WHERE commit_id = ? AND location_id = ? "
                "ORDER BY id DESC LIMIT 1", (op["commit_id"], op["location_id"])).fetchone()
            return _withhold_write_tx(con, kind="commit", location_id=op["location_id"],
                                      commit_id=op["commit_id"], header_hash=op["post_hash"],
                                      reason=withheld_reason, now=now,
                                      pending_ids=[r["id"] for r in rows], inplace_op_id=op_id,
                                      backup_id=backup["id"], actor=actor)
        wstrzymanie = None
        if not testimony_ok and op["commit_id"] is not None and not closed_commit_withheld:
            wstrzymanie = _withhold_write_tx(
                con, kind="undo", location_id=op["location_id"], commit_id=op["commit_id"],
                header_hash=op["post_hash"], reason=withheld_reason, now=now,
                inplace_op_id=op_id, actor=actor)
        uwaga = None
        if op["kind"] == "commit" and any(r["keyword"] == "OBJECT" for r in rows):
            # Z8: nagrobek gaśnie wyłącznie przy wersji decyzji ręki z backupu tej operacji
            # (utrwalonej przed pierwszym bajtem) - decyzja człowieka z okna zapis → dokończenie
            # zostaje, a powód wpisów to mówi.
            loc = con.execute("SELECT frame_id FROM location WHERE id = ?",
                              (op["location_id"],)).fetchone()
            reka = con.execute(
                "SELECT hand_version FROM header_backups WHERE commit_id = ? AND location_id = ? "
                "ORDER BY id DESC LIMIT 1", (op["commit_id"], op["location_id"])).fetchone()
            uwaga = _clear_tombstone_same_hand_tx(
                con, frame_id=loc["frame_id"], hand_version=None if reka is None else reka[0],
                commit_id=op["commit_id"], location_id=op["location_id"], now=now, actor=actor)
        con.execute("UPDATE pending_changes SET status = 'applied' WHERE inplace_op_id = ?",
                    (op_id,))
        _set_pending_reason_tx(con, [r["id"] for r in rows], uwaga)
        if op["kind"] == "undo" and op["commit_id"] is not None:
            # Cofnięcie w miejscu odtwarza nagrobek zgaszony przez cofany commit (AR-38) - w tej
            # samej transakcji co faza `synced`, więc nie wyprzedzi ani nie zgubi dokończenia.
            loc = con.execute("SELECT frame_id FROM location WHERE id = ?",
                              (op["location_id"],)).fetchone()
            _restore_object_tombstone_tx(con, frame_id=loc["frame_id"], commit_id=op["commit_id"],
                                         location_id=op["location_id"], now=now, actor=actor)
    return wstrzymanie


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
        wpisy = [r["id"] for r in con.execute(
            "SELECT id FROM pending_changes WHERE inplace_op_id = ?", (op_id,))]
        con.execute("UPDATE pending_changes SET status = 'failed' WHERE inplace_op_id = ?",
                    (op_id,))
        _set_pending_reason_tx(con, wpisy, reason)
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
        # Odmowy z kodem (`OdmowaZPowodem` to `ValueError` - wołający łapią jak dotąd, tekst bez
        # zmian), żeby wynik zwolnienia mówił w języku UI (AR-148).
        if row is None or row["phase"] not in INPLACE_ISOLATING_PHASES:
            raise OdmowaZPowodem(PowodPozycji(
                f"operacja {op_id} nie izoluje lokacji - nie ma czego zwalniać",
                "release_refused_db", op_id=op_id))
        oczekiwana = row["phase"] if expect_phase is None else expect_phase
        cur = con.execute("UPDATE inplace_op SET phase = 'released', reason = ?, closed_at = ? "
                          "WHERE id = ? AND phase = ?", (reason, now, op_id, oczekiwana))
        if cur.rowcount != 1:
            raise OdmowaZPowodem(PowodPozycji(
                f"operacja {op_id} jest w fazie {row['phase']}, nie {oczekiwana} - inny proces "
                f"zmienił ją po odczycie, zwolnienia nie ma", "release_phase_changed", op_id=op_id,
                phase=row["phase"], expected=oczekiwana))
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
    INNY wiersz pod tą samą ścieżką FIZYCZNĄ (`path_owner`; anty-clobber w bazie, R3 #3) →
    `ValueError`. Zmiana samej wielkości liter własnej lokacji kolizją nie jest - to ten sam wiersz."""
    row = con.execute(
        "SELECT volume, path FROM location WHERE id = ?", (location_id,)).fetchone()
    if row is None:
        raise ValueError(f"location:{location_id} nie istnieje")
    clash = path_owner(con, volume=row["volume"], path=new_path, location_id=location_id)
    if clash is not None:
        raise OdmowaZPowodem(PowodPozycji(
            f"cel zajęty w bazie: location:{clash} ma już (volume={row['volume']}, {new_path})",
            "target_taken_db", location=clash, volume=row["volume"], path=new_path))
    return row["path"]


def path_owner(con, *, volume, path, location_id):
    """Id INNEJ lokacji woluminu (obecnej albo nie) pod tą samą ścieżką FIZYCZNĄ co `path` → int
    albo None. Ścieżka fizyczna = klucz planera (`object_change.path_key`: separatory jak w systemie,
    bez wielkości liter) - udział `R:` nie rozróżnia `IC405` i `ic405`, a `UNIQUE(volume, path)`
    porównuje binarnie, więc samo `path = ?` przepuszczało drugą lokację tego samego pliku. Lokacja
    nieobecna też się liczy: jej wiersz wróci przy skanie pod tą samą ścieżką.

    Najpierw tani filtr w SQL (koniec ścieżki = nazwa pliku; `LIKE` składa wielkość liter ASCII,
    znak spoza ASCII zastępuje dowolny jeden znak), potem dokładny klucz w Pythonie - filtr jest
    nadzbiorem, decyduje klucz."""
    klucz = path_key(path)
    nazwa = ntpath.basename(ntpath.normpath(str(path)))
    wzor = "%" + "".join("!" + z if z in "!%_" else (z if z.isascii() else "_") for z in nazwa)
    for r in con.execute(
            "SELECT id, path FROM location WHERE volume = ? AND id <> ? AND path LIKE ? ESCAPE '!'",
            (volume, location_id, wzor)):
        if path_key(r["path"]) == klucz:
            return r["id"]
    return None


def _apply_relocation(con, *, location_id, old_path, new_path, now, actor, rename_id=None,
                      reason=None, alias=True, gest=None):
    """UPDATE `location.path` + `location.renamed` pod transakcją wołającego. Rekoncyliacja zamiaru
    (`settle_rename_intent`) dokłada wiersz stagingu do ładunku i powód. `gest` (zmiana obiektu:
    `object_change`, jej cofnięcie: `object_change_undo`) trafia do ładunku jako `reason` - Dom
    opisuje takie zdarzenie jako przeniesienie do folderu obiektu, nie jako zmianę nazwy.

    DAWNA NAZWA LIGHTU ZOSTAJE ALIASEM (`light_name_alias`, źródło `horreum`, AR-108): historia stosu
    zapisuje nazwy lightów z chwili obróbki, więc zmiana nazwy po obróbce odcina rodowód po nazwie -
    tak zgubił się cały zapis przenosin Custos (0/1762 trafień nazwami bieżącymi). Alias powstaje
    PRZED `UPDATE`, z tej samej transakcji co relokacja (`_dopisz_alias_nazwy`: idempotentny, event
    tylko przy nowym wierszu); inne rodzaje klatek i zmiana samego katalogu (rdzeń bez zmian) -
    bez aliasu. `alias=False` - kierunek `undo`: cofnięcie wraca do nazwy, która już jest aliasem
    albo nazwą bieżącą, a nazwa cofana była tranzytowa (żaden program obróbki jej nie widział) -
    jej rdzeń w tabeli tylko zderzałby się z rdzeniami innych klatek."""
    if alias:
        _dopisz_alias_nazwy(con, location_id=location_id, old_path=old_path, new_path=new_path,
                            now=now, actor=actor)
    con.execute("UPDATE location SET path = ? WHERE id = ?", (new_path, location_id))
    payload = {"before": old_path, "after": new_path}
    if rename_id is not None:
        payload["pending_rename"] = rename_id
    if gest is not None:
        payload["reason"] = gest
    emit_event(con, actor=actor, verb="location.renamed", target=f"location:{location_id}",
               now=now, payload=payload, reason=reason)


def _dopisz_alias_nazwy(con, *, location_id, old_path, new_path, now, actor):
    """Pod transakcją wołającego: rdzeń dawnej nazwy lightu → `light_name_alias` (`source='horreum'`)
    → `True`, gdy wiersz powstał. Rdzeń bez zmian albo klatka nie-light → `False` bez zapisu."""
    stary = raw_stem(old_path)
    if not stary or stary == raw_stem(new_path):
        return False
    row = con.execute("SELECT f.id, f.kind FROM location l JOIN frame f ON f.id = l.frame_id "
                      "WHERE l.id = ?", (location_id,)).fetchone()
    if row is None or row["kind"] != "light":
        return False
    cur = con.execute("INSERT OR IGNORE INTO light_name_alias(frame_id, stem, source) "
                      "VALUES (?, ?, 'horreum')", (row["id"], stary))
    if not cur.rowcount:
        return False
    emit_event(con, actor=actor, verb="light_name_alias.added", target=f"frame:{row['id']}",
               now=now, payload={"stem": stary, "source": "horreum", "location_id": location_id})
    return True


@contextmanager
def guard_file_rename(con, *, location_id, new_path, generation, now, actor="user:local",
                      rename_id=None, status=None, reason=None, kierunek=None, gest=None):
    """STRAŻ RELOKACJI (AR-17 (5)): rename pliku lokacji i przepięcie `location.path` w JEDNEJ
    transakcji `BEGIN IMMEDIATE` - bliźniak `guard_file_replace` dla `os.rename`:

      1. `_refuse_inplace_conflict`: operacja izolująca lokację albo operacja o `id` > `generation`
         (zapamiętanej przez wołającego PRZED jego bramką izolacji, dowolnej fazy) → `InplaceConflict`;
      2. anty-clobber w bazie (`_relocation_target`) → `ValueError`;
      3. ciało `with` - `os.rename` pisarza (`writeback.rename_file`);
      4. dopiero po ciele BEZ wyjątku: UPDATE `location.path` + `location.renamed`, przy `rename_id`
         także status wiersza stagingu (`status`, `reason`) i zgaszenie jego zamiaru (`in_flight`),
         COMMIT. Status idzie w tej samej transakcji co relokacja (AR-29 (2)): osobna transakcja
         zostawiała przy awarii wiersz 'pending' przy przeniesionym pliku i bazie, a ponowienie
         widziało nową ścieżkę i mówiło 'blocked'.
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
        # Zamiar zatwierdzony przez wołającego musi dalej być TEN SAM pod blokadą: między jego
        # COMMIT-em a tą transakcją rekoncyliacja innego procesu (skan) mogła go zgasić, a rename
        # bez otwartego zamiaru zostawiłby po śmierci procesu rozjazd bez śladu.
        if rename_id is not None and kierunek is not None:
            zamiar = con.execute("SELECT in_flight FROM pending_renames WHERE id = ?",
                                 (rename_id,)).fetchone()
            if zamiar is None or zamiar["in_flight"] != kierunek:
                raise OdmowaZPowodem(PowodPozycji(
                    f"zamiar renamu {rename_id} zgaszony przez inny proces - renamu nie było, plik "
                    f"nietknięty; odśwież przebieg", "intent_dropped", rename_id=rename_id))
        old_path = _relocation_target(con, location_id, new_path)
        yield
        _apply_relocation(con, location_id=location_id, old_path=old_path, new_path=new_path,
                          now=now, actor=actor, alias=kierunek != "undo", gest=gest)
        if rename_id is not None:
            _zamknij_wiersz_renamu(con, rename_id, status, reason)


def _zamknij_wiersz_renamu(con, rename_id, status, reason):
    """Status wiersza stagingu + zgaszenie zamiaru pod transakcją wołającego."""
    con.execute("UPDATE pending_renames SET status = ?, in_flight = NULL WHERE id = ?",
                (status, rename_id))
    _set_rename_reason_tx(con, rename_id, reason)


def _set_rename_reason_tx(con, rename_id, powod):
    """JEDYNY pisarz powodu wiersza stagingu renamu (AR-148, meta-test): trójka `reason`/
    `reason_code`/`reason_args` z kodeka `item_reasons.do_bazy` jednym UPDATE (CHECK 0042).
    `powod` = `PowodPozycji`, proza bez kodu albo `None`. Pod transakcją wołającego."""
    con.execute("UPDATE pending_renames SET reason = ?, reason_code = ?, reason_args = ? "
                "WHERE id = ?", (*do_bazy(powod), rename_id))


def open_rename_intent(con, *, rename_id, direction):
    """TRWAŁY ZAMIAR RENAMU (AR-29): `in_flight` = kierunek ('commit' old→new, 'undo' new→old),
    zatwierdzony PRZED `os.rename` (`synchronous = FULL` - przeżywa utratę zasilania). Gaśnie razem
    z relokacją w straży (`guard_file_rename`), gdy plik na pewno nie ruszył się z miejsca
    (`drop_rename_intent`) albo w rekoncyliacji (`settle_rename_intent`). Zamiar już otwarty → `ValueError` (EXPECT: wołający
    rekoncyliuje przed próbą, więc drugi zamiar na tym samym wierszu to błąd kolejności).
    Transient - bez eventu (faktem domenowym jest dopiero `location.renamed`)."""
    if direction not in ("commit", "undo"):
        raise ValueError(f"kierunek renamu {direction!r} spoza ('commit', 'undo')")
    with _immediate(con):
        cur = con.execute("UPDATE pending_renames SET in_flight = ? "
                          "WHERE id = ? AND in_flight IS NULL", (direction, rename_id))
        if cur.rowcount != 1:
            raise ValueError(f"wiersz renamu {rename_id} nie istnieje albo ma już otwarty zamiar")


class RenameIntentChanged(Exception):
    """Zamiar renamu albo miejsce pliku zmieniły się między obserwacją wołającego a transakcją
    rozstrzygnięcia - inny proces (kompensacja albo rekoncyliacja) zdążył go rozstrzygnąć. Zero
    zapisu; wołający melduje i zostawia sprawę następnemu przebiegowi (AR-56). Tekst wyjątku =
    zdanie PL powodu, `powod` = ten sam powód z kodem (AR-148, `item_reasons.powod_wyjatku`)."""

    def __init__(self, powod):
        super().__init__(str(powod))
        self.powod = powod


def settle_rename_intent(con, *, rename_id, location_id, status, reason, now, relocate_to=None,
                         actor="user:local", expect_in_flight=None, potwierdz=None):
    """REKONCYLIACJA ZAMIARU (AR-29): w JEDNEJ transakcji opcjonalne przepięcie TEJ SAMEJ lokacji
    na ścieżkę, pod którą plik faktycznie stoi (`relocate_to`; `location.renamed` z powodem - ciągłość
    historii lokacji zostaje), status wiersza stagingu i zgaszenie zamiaru. Cel zajęty w bazie przez
    INNY wiersz (skan zdążył wciągnąć plik jako nową kopię) → `ValueError`, zero zapisu. Rozstrzygnięcie
    (gdzie plik stoi, czy to ten plik) należy do wołającego - `writeback.reconcile_renames`.

    USZEREGOWANIE Z KOMPENSACJĄ (AR-56): obserwacja dysku wołającego wyprzedza tę transakcję, więc
    pod blokadą zapisu bazy dwa warunki: zamiar wciąż otwarty w kierunku, który wołający widział
    (`expect_in_flight`), i `potwierdz()` - ponowne, tanie sprawdzenie dysku (plik wciąż tam, gdzie
    był). Kompensacja renamu (`guard_rename_compensation`) przenosi plik i gasi zamiar w tej samej
    blokadzie, więc albo zdążyła przed nami (warunek pada → `RenameIntentChanged`, zero zapisu),
    albo czeka, aż skończymy."""
    with _immediate(con):
        if expect_in_flight is not None:
            row = con.execute("SELECT in_flight FROM pending_renames WHERE id = ?",
                              (rename_id,)).fetchone()
            if row is None or row["in_flight"] != expect_in_flight:
                raise RenameIntentChanged(PowodPozycji(
                    f"zamiar renamu {rename_id} rozstrzygnięty przez inny proces po obserwacji "
                    f"dysku", "intent_settled_elsewhere", rename_id=rename_id))
        if potwierdz is not None and not potwierdz():
            raise RenameIntentChanged(PowodPozycji(
                f"plik renamu {rename_id} zmienił miejsce po obserwacji dysku", "intent_file_moved",
                rename_id=rename_id))
        if relocate_to is not None:
            old_path = _relocation_target(con, location_id, relocate_to)
            if old_path != relocate_to:
                _apply_relocation(con, location_id=location_id, old_path=old_path,
                                  new_path=relocate_to, now=now, actor=actor, rename_id=rename_id,
                                  reason="dokończenie przerwanego renamu (rekoncyliacja zamiaru)",
                                  alias=expect_in_flight != "undo")
        _zamknij_wiersz_renamu(con, rename_id, status, reason)


def _insert_rename(con, row):
    """JEDEN literał INSERT stagingu renamu dla obu wołających (`stage_rename`, staging zmiany
    obiektu) - jak `_insert_pending`. Bez własnej transakcji: obejmuje ją wołający. Zwraca id."""
    return con.execute(
        "INSERT INTO pending_renames(run_id, location_id, old_path, new_path, expected_mtime, "
        "status) VALUES (?, ?, ?, ?, ?, 'pending')", row).lastrowid


def stage_rename(con, *, run_id, location_id, old_path, new_path, expected_mtime):
    """Dopisz JEDEN wpis stagingu renamu (status 'pending'). Kluczowany LOCATION. Zwraca id wiersza.
    Transient — bez eventu. `expected_mtime` = kotwica anty-stale (mtime pliku przy podglądzie)."""
    with con:
        rename_id = _insert_rename(con, (run_id, location_id, old_path, new_path, expected_mtime))
    return rename_id


def set_rename_status(con, *, rename_id, status, reason=None):
    """Ustaw status wpisu stagingu renamu ('applied'|'failed'|'skipped'|'blocked') + powód. Transient.
    Zamiaru (`in_flight`) NIE rusza - jego cyklem rządzą `open_rename_intent`/`drop_rename_intent`,
    straż relokacji i rekoncyliacja (AR-29)."""
    with con:
        con.execute("UPDATE pending_renames SET status = ? WHERE id = ?", (status, rename_id))
        _set_rename_reason_tx(con, rename_id, reason)


def drop_rename_intent(con, *, rename_id):
    """Zgaś zamiar renamu, gdy plik na pewno nie ruszył się z miejsca (prymityw odmówił, straż
    odbiła, kompensacja wróciła plik na stare miejsce przy bazie po rollbacku). Transient."""
    with con:
        con.execute("UPDATE pending_renames SET in_flight = NULL WHERE id = ?", (rename_id,))


@dataclass
class RenameCompensation:
    """Stan widziany pod blokadą zapisu bazy przez kompensację renamu (`guard_rename_compensation`):
    `path` lokacji i `in_flight` zamiaru. Wołający ustawia `zgas=True`, gdy plik wrócił - zamiar
    gaśnie w tej samej transakcji."""
    path: object
    in_flight: object
    zgas: bool = False


@contextmanager
def guard_rename_compensation(con, *, rename_id, location_id):
    """STRAŻ KOMPENSACJI RENAMU (AR-56): ponowny odczyt bazy, kompensacja pliku i zgaszenie zamiaru
    pod JEDNYM `BEGIN IMMEDIATE`. Wołane przez `writeback._po_awarii_przepiecia` po padzie
    transakcji przepięcia: `os.rename` zaszedł, baza mogła przyjąć przepięcie albo nie.

    Ciało `with` dostaje `RenameCompensation` (ścieżka lokacji i zamiar, przeczytane POD blokadą)
    i samo rozstrzyga: plik wraca (`dst→src`) wyłącznie, gdy baza wciąż wskazuje `src`, a zamiar jest
    otwarty w kierunku tej próby. Wtedy `zgas=True` gasi zamiar w tej samej transakcji. Dawniej
    odczyt `path` i powrót pliku to były dwie chwile: rekoncyliacja innego procesu mogła między nimi
    przepiąć bazę na `dst` i zgasić zamiar, a plik wracał pod `src` - baza i dysk rozjechane bez
    śladu. Rekoncyliacja (`settle_rename_intent`) bierze tę samą blokadę i sprawdza zamiar oraz
    miejsce pliku pod nią, więc obie drogi są uszeregowane. Wyjątek w ciele → rollback, zero zapisu."""
    with _immediate(con):
        loc = con.execute("SELECT path FROM location WHERE id = ?", (location_id,)).fetchone()
        zam = con.execute("SELECT in_flight FROM pending_renames WHERE id = ?",
                          (rename_id,)).fetchone()
        stan = RenameCompensation(None if loc is None else loc["path"],
                                  None if zam is None else zam["in_flight"])
        yield stan
        if stan.zgas:
            con.execute("UPDATE pending_renames SET in_flight = NULL WHERE id = ?", (rename_id,))


def clear_renames_for_run(con, run_id):
    """Skasuj staging renamu przebiegu (ponowny podgląd / „Odrzuć"). DELETE sankcjonowany: lustro
    oczekujących, nie historia (historia = event `location.renamed`). Transient - bez eventu.
    Wiersz z otwartym zamiarem (`in_flight`, AR-29) ZOSTAJE: niesie jedyny ślad renamu, który mógł
    zajść bez przepięcia bazy - zdejmie go dopiero rekoncyliacja."""
    with con:
        con.execute("DELETE FROM pending_renames WHERE run_id = ? AND in_flight IS NULL", (run_id,))


# ------------------------------------------------ ZMIANA OBIEKTU RAZEM Z PLIKIEM (AR-17 krok 3, 0036)
# Księgowość gestu „Zmień obiekt…”/„Uzgodnij” (`object_change_run`, `pending_object_change`, `run_dir`)
# - transient jak staging karty i renamu, BEZ eventów: faktami domenowymi są zmiana obiektu klatki
# (para verbów klingi ręki) i relokacja (`location.renamed`). Sterownik i cofnięcie żyją w `writeback`
# (mutacja plików); tu każdy ich zapis bazy, każdy w swojej transakcji.

_ETAPY_COFNIECIA = (None, "card", "file")     # fazy cofnięcia pozycji przed fazą bazy (0036)


def _katalogi_celu(katalogi, new_path):
    """Czy `katalogi` to kolejne poziomy drogi do katalogu `new_path`, od najpłytszego, z katalogiem
    pliku na końcu: sterownik zakłada wyłącznie je, więc katalog spoza tej drogi (błąd planu) nie
    może przejść stagingu - powstałby na udziale bez żadnego pliku w środku."""
    cel = os.path.normcase(os.path.normpath(os.path.dirname(new_path)))
    poziomy = [os.path.normcase(os.path.normpath(k)) for k in katalogi]
    return (poziomy[-1] == cel
            and all(os.path.dirname(dziecko) == rodzic
                    for rodzic, dziecko in zip(poziomy, poziomy[1:])))


def stage_object_change(con, *, plan, now):
    """STAGING GESTU (D-1011-5) - JEDNA transakcja: przebieg (`object_change_run`: tryb i cel),
    a per pozycja przeniesienie (`pending_renames`, gdy `new_path`), karta `OBJECT`
    (`pending_changes`, gdy `card_op`; kotwica `expected_header_hash`) i sama pozycja
    (`pending_object_change`: CAS ręki, katalogi celu z podglądu). Wiersze `run_dir` NIE - powstają
    w sterowniku, bo zależą od stanu dysku w chwili ruchu. Obiektu i aliasu staging nie zakłada
    (porzucony podgląd nie zostawia pustego obiektu) - robi to klinga ręki przy pierwszej pozycji,
    która obiekt naprawdę dostaje.

    `plan` = `object_change.ObjectChangePlan` (pola czytane po nazwie - repo nie importuje planera).
    EXPECT (`ValueError`, zero zapisu): cel bez formy karty (gest odmawia takiego celu przed planem),
    pozycja zmieniająca obiekt w trybie „Uzgodnij”, operacja karty spoza `set`/`add` albo bez
    wartości, katalogi do założenia bez przeniesienia, CAS ręki nie-trójką. Drugi staging tego samego
    `run_id` → `sqlite3.IntegrityError` (przebieg ma jeden staging)."""
    cel = plan.target
    if cel is not None and not cel.card_form:
        raise ValueError(f"cel '{cel.canon}' bez formy karty OBJECT - gest „karta i folder razem” "
                         "odmawia celu przed planem")
    for it in plan.items:
        if cel is None and it.object_change:
            raise ValueError(f"frame:{it.frame_id} zmienia obiekt w trybie „Uzgodnij” (cel None)")
        if it.card_op not in (None, "set", "add") or (it.card_op is not None and it.card_new is None):
            raise ValueError(f"frame:{it.frame_id}: karta {it.card_op!r} bez wartości albo spoza "
                             "('set', 'add')")
        if it.mkdirs and it.new_path is None:
            raise ValueError(f"frame:{it.frame_id}: katalogi do założenia bez przeniesienia pliku")
        if it.mkdirs and not _katalogi_celu(it.mkdirs, it.new_path):
            raise ValueError(f"frame:{it.frame_id}: katalogi do założenia nie są kolejnymi przodkami "
                             f"katalogu celu {it.new_path} od najpłytszego")
        if len(tuple(it.expected_object)) != 3:
            raise ValueError(f"frame:{it.frame_id}: CAS ręki to trójca (object_id, object_source, "
                             "object_cleared_id)")
    with _immediate(con):
        con.execute(
            "INSERT INTO object_change_run(run_id, mode, canon, catalog, kind, alias_norm, card_form, "
            "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (plan.run_id, "align" if cel is None else "change",
             None if cel is None else cel.canon, None if cel is None else cel.catalog,
             None if cel is None else cel.kind, None if cel is None else cel.alias_norm,
             None if cel is None else cel.card_form, now))
        for it in plan.items:
            rename_id = None
            if it.new_path is not None:
                rename_id = _insert_rename(con, (plan.run_id, it.location_id, it.old_path,
                                                 it.new_path, it.expected_mtime))
            if it.card_op is not None:
                _insert_pending(con, (plan.run_id, it.location_id, "OBJECT",
                                      0 if it.card_op == "set" else None, it.card_op, it.card_old,
                                      it.card_new, "str", None, it.expected_header_hash))
            oczekiwany = tuple(it.expected_object)
            con.execute(
                "INSERT INTO pending_object_change(run_id, frame_id, location_id, old_path, "
                "expected_mtime, object_change, expected_object_id, expected_source, "
                "expected_cleared_id, rename_id, mkdirs) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (plan.run_id, it.frame_id, it.location_id, it.old_path, it.expected_mtime,
                 int(bool(it.object_change)), oczekiwany[0], oczekiwany[1], oczekiwany[2],
                 rename_id, json.dumps(list(it.mkdirs), ensure_ascii=False)))


def apply_object_change_item(con, *, item_id, now, uid="local"):
    """KROK BAZY POZYCJI gestu (D-1011-5 Q1: baza najpierw, per pozycja) - JEDNA transakcja: CAS ręki
    i zmiana obiektu klatki (`_override_object_tx`, `reason='object_change'`) RAZEM z utrwaleniem
    zapisanego obiektu i stanu sprzed w wierszu pozycji (cofnięcie przeżywa awarię procesu, bo stan
    sprzed nie żyje w pamięci okna). Cel (kanon, katalog, rodzaj, alias) z `object_change_run`.

    → `'assigned'` · `'unchanged'` (klatka już ma obiekt celu - baza nietknięta) · `'drift'` (stan
    inny niż w podglądzie albo martwa tożsamość - zero zapisu) · `'none'` (pozycja bez zmiany obiektu:
    „Uzgodnij” albo cel = obiekt bieżący) · `'copies'` (klatka nie ma dokładnie jednej obecnej kopii
    albo nie jest nią kopia pozycji - zero zapisu). Krok zrobiony przed awarią (wiersz niesie
    `object_id`) → `'assigned'` bez zapisu, o ile klatka dalej niesie jego wynik `(object_id, 'user',
    NULL)` i żyje - wtedy ponowienie idzie dalej od pliku; inaczej `'drift'`. `ValueError` klingi
    (konflikt aliasu, klatka spoza `LIGHT_KINDS`) i pozycja nie-oczekująca (EXPECT) - zero zapisu.

    POZYCJA BEZ ZMIANY OBIEKTU TEŻ PYTA O STAN Z PODGLĄDU (sam odczyt, ta sama trójca i ta sama
    martwa tożsamość): plik dogania obiekt, który klatka miała w podglądzie - gdy w międzyczasie
    dostała inny, przeniesienie zawiozłoby go do folderu obiektu, którego klatka już nie ma."""
    with _immediate(con):
        p = con.execute(
            "SELECT p.run_id, p.frame_id, p.location_id, p.object_change, p.object_id, "
            "       p.expected_object_id, p.expected_source, p.expected_cleared_id, p.status, "
            "       r.canon, r.catalog, r.kind, r.alias_norm "
            "FROM pending_object_change p JOIN object_change_run r ON r.run_id = p.run_id "
            "WHERE p.id = ?", (item_id,)).fetchone()
        if p is None:
            raise ValueError(f"pozycja zmiany obiektu {item_id} nie istnieje")
        if p["status"] != "pending":
            raise ValueError(f"pozycja zmiany obiektu {item_id} ma status '{p['status']}' - krok "
                             "bazy dotyczy wyłącznie pozycji oczekującej")
        # JEDNA OBECNA KOPIA, I TO TA Z PODGLĄDU - pod tą samą blokadą co zapis klatki. Ręka zmienia
        # obiekt CAŁEJ klatki, a plik i kartę dostaje tylko kopia pozycji: druga obecna kopia, którą
        # skan dopisał po podglądzie, zostałaby ze starym folderem i kartą przy nowym obiekcie.
        kopie = [r[0] for r in con.execute(
            "SELECT id FROM location WHERE frame_id = ? AND present = 1", (p["frame_id"],))]
        if kopie != [p["location_id"]]:
            return "copies"
        fr = con.execute(
            "SELECT object_id, object_source, object_cleared_id, retired_at, superseded_by "
            "FROM frame WHERE id = ?", (p["frame_id"],)).fetchone()
        martwa = fr is None or fr["retired_at"] is not None or fr["superseded_by"] is not None
        trojca = None if fr is None else (fr["object_id"], fr["object_source"],
                                          fr["object_cleared_id"])
        if not p["object_change"]:
            if martwa or trojca != (p["expected_object_id"], p["expected_source"],
                                    p["expected_cleared_id"]):
                return "drift"
            return "none"
        if p["object_id"] is not None:
            # WZNOWIENIE po awarii: krok bazy zrobiono wcześniej, więc klatka ma dalej nieść JEGO
            # wynik - inaczej plik i karta poszłyby za obiektem, który ręka już zmieniła. Wyniku
            # gestu w bazie nie ma (nowsza decyzja) → pozycja go zapomina, bez przywracania stanu
            # sprzed; martwa tożsamość z wynikiem gestu → dryf, a wynik zostaje dla cofnięcia.
            if trojca != (p["object_id"], "user", None):
                con.execute(
                    "UPDATE pending_object_change SET object_id = NULL, before_object_id = NULL, "
                    "before_source = NULL, before_cleared_id = NULL WHERE id = ?", (item_id,))
                return "drift"
            return "drift" if martwa else "assigned"
        werdykt, zmiana = _override_object_tx(
            con, frame_id=p["frame_id"], canon=p["canon"], catalog=p["catalog"], kind=p["kind"],
            alias_norm=p["alias_norm"],
            expected=(p["expected_object_id"], p["expected_source"], p["expected_cleared_id"]),
            now=now, actor=f"user:{uid}", reason="object_change")
        if zmiana is not None:
            con.execute(
                "UPDATE pending_object_change SET object_id = ?, before_object_id = ?, "
                "before_source = ?, before_cleared_id = ? WHERE id = ?",
                (zmiana.object_id, *zmiana.before, item_id))
            # ŚLAD NAGROBKA (0040): co gest założył po drodze - w TEJ transakcji co `INSERT` albo
            # wskrzeszenie obiektu i aliasu; z niego cofnięcie przebiegu zdejmuje założone.
            if zmiana.made is not Made.EXISTING:
                con.execute("UPDATE object_change_run SET made_object_id = ? WHERE run_id = ?",
                            (zmiana.object_id, p["run_id"]))
            if zmiana.alias_id is not None:
                con.execute("UPDATE object_change_run SET made_alias_id = ? WHERE run_id = ?",
                            (zmiana.alias_id, p["run_id"]))
    return werdykt


def _krok_bazy_pozycji(con, item_id):
    """Pod transakcją wołającego: `(wiersz pozycji, ObjectOverride | None)` - materiał cofnięcia kroku
    bazy pozycji (None = baza tej pozycji nietknięta przez gest)."""
    p = con.execute(
        "SELECT frame_id, object_id, before_object_id, before_source, before_cleared_id, status, "
        "       undo_phase FROM pending_object_change WHERE id = ?", (item_id,)).fetchone()
    if p is None:
        raise ValueError(f"pozycja zmiany obiektu {item_id} nie istnieje")
    if p["object_id"] is None:
        return p, None
    return p, ObjectOverride(p["frame_id"], (p["before_object_id"], p["before_source"],
                                             p["before_cleared_id"]), p["object_id"],
                             "object_change")


def settle_object_change_item(con, *, item_id, status, reason, now, restore=False, uid="local"):
    """ROZLICZENIE POZYCJI w biegu gestu - JEDNA transakcja: status z powodem, a przy `restore=True`
    także wycofanie jej kroku bazy (odmowa przeniesienia albo karty BEZ zapisu = zrobione kroki
    pozycji wracają; plik wraca wcześniej, w `writeback`). Wycofanie idzie CAS-em klingi
    (`_restore_override_tx`): klatka, która nie niesie już wyniku gestu (inny gest zdążył ją
    zmienić), zostaje nietknięta, a powód to mówi. Po wycofaniu - udanym albo odbitym - wiersz nie
    niesie obiektu ani stanu sprzed: w bazie nie ma już wyniku TEGO gestu, więc cofnięcie przebiegu
    nie ma tu czego cofać.

    → `True` (baza wycofana), `False` (CAS odmówił), `None` (nie było czego wycofywać)."""
    if status not in ("applied", "skipped", "blocked", "failed"):
        raise ValueError(f"status pozycji {status!r} spoza ('applied', 'skipped', 'blocked', 'failed')")
    with _immediate(con):
        _, zmiana = _krok_bazy_pozycji(con, item_id)
        wycofano = None
        if restore and zmiana is not None:
            wycofano = _restore_override_tx(con, change=zmiana, now=now, actor=f"user:{uid}")
            if not wycofano:
                if reason and not isinstance(reason, PowodPozycji):
                    # Proza bez kodu (tekst systemu, EXPECT) w kopercie - nota zachowuje kod.
                    reason = PowodPozycji(reason, "prose", text=reason)
                reason = dopisz(reason, _BAZA_NOWSZA_W_BIEGU)
            con.execute(
                "UPDATE pending_object_change SET object_id = NULL, before_object_id = NULL, "
                "before_source = NULL, before_cleared_id = NULL WHERE id = ?", (item_id,))
        con.execute("UPDATE pending_object_change SET status = ? WHERE id = ?", (status, item_id))
        _set_object_change_reason_tx(con, item_id, reason)
    return wycofano


# Uwagi klingi do powodu pozycji (AR-141): wycofanie kroku bazy w biegu i cofnięcie bazy, które
# zastały nowszą decyzję ręki - klatka zostaje przy niej.
_BAZA_NOWSZA_W_BIEGU = PowodPozycji("baza: klatka niesie już nowszą decyzję niż gest - zostaje",
                                    "hand_newer_kept")
_BAZA_NOWSZA_PRZY_COFNIECIU = PowodPozycji("baza: klatka niesie nowszą decyzję niż gest - obiekt "
                                           "zostaje", "undo_hand_newer")


def _set_object_change_reason_tx(con, item_id, powod):
    """JEDYNY pisarz powodu pozycji (AR-141, meta-test): trójka `reason`/`reason_code`/`reason_args`
    z kodeka `item_reasons.do_bazy` jednym UPDATE - proza i kod nigdy się nie rozjadą (CHECK 0041).
    `powod` = `PowodPozycji`, proza bez kodu albo `None` (czyści trójkę). Pod transakcją wołającego."""
    con.execute("UPDATE pending_object_change SET reason = ?, reason_code = ?, reason_args = ? "
                "WHERE id = ?", (*do_bazy(powod), item_id))


def set_object_change_undo_phase(con, *, item_id, phase, reason=None):
    """Faza cofnięcia pozycji (`card` → `file`, 0036) z powodem albo - `phase=None` - sam powód
    zatrzymania przy fazie bieżącej. Faza idzie WYŁĄCZNIE o jeden krok naprzód (EXPECT: cofnięcie
    domyka fazy po kolei, przeskok znaczy błąd wołającego); fazę `db` stawia
    `undo_object_change_db` razem ze statusem `undone`."""
    with _immediate(con):
        row = con.execute("SELECT undo_phase FROM pending_object_change WHERE id = ?",
                          (item_id,)).fetchone()
        if row is None:
            raise ValueError(f"pozycja zmiany obiektu {item_id} nie istnieje")
        if phase is None:
            _set_object_change_reason_tx(con, item_id, reason)
            return
        if (phase not in _ETAPY_COFNIECIA[1:] or row["undo_phase"] not in _ETAPY_COFNIECIA
                or _ETAPY_COFNIECIA.index(phase) != _ETAPY_COFNIECIA.index(row["undo_phase"]) + 1):
            raise ValueError(f"faza cofnięcia {row['undo_phase']!r} → {phase!r} - poza kolejnością "
                             f"{_ETAPY_COFNIECIA}")
        con.execute("UPDATE pending_object_change SET undo_phase = ? WHERE id = ?", (phase, item_id))
        _set_object_change_reason_tx(con, item_id, reason)


def undo_object_change_db(con, *, item_id, now, uid="local"):
    """OSTATNIA FAZA COFNIĘCIA POZYCJI (karta → plik → baza) - JEDNA transakcja: baza wraca do stanu
    sprzed (CAS klingi: wyłącznie klatka, która dalej niesie wynik gestu), wiersz dostaje fazę `db`
    i status `undone`. Klatka z nowszą decyzją ręki zostaje, a powód to mówi; pozycja bez kroku bazy
    („Uzgodnij”, `unchanged`) domyka się bez zapisu klatki. EXPECT: plik pozycji już wrócił (faza
    `file`). → powód dla człowieka albo None."""
    with _immediate(con):
        p, zmiana = _krok_bazy_pozycji(con, item_id)
        if p["undo_phase"] != "file":
            raise ValueError(f"pozycja zmiany obiektu {item_id} w fazie cofnięcia "
                             f"{p['undo_phase']!r} - baza wraca dopiero po pliku")
        uwaga = None
        if zmiana is not None and not _restore_override_tx(con, change=zmiana, now=now,
                                                          actor=f"user:{uid}"):
            uwaga = _BAZA_NOWSZA_PRZY_COFNIECIU
        con.execute("UPDATE pending_object_change SET status = 'undone', undo_phase = 'db' "
                    "WHERE id = ?", (item_id,))
        _set_object_change_reason_tx(con, item_id, uwaga)
    return uwaga


def set_object_change_run_status(con, *, run_id, status):
    """Status przebiegu gestu: `applied` (sterownik doszedł do końca listy pozycji), `undoing`
    (cofnięcie zlecone - sterownik zapisu przebiegu już nie wznowi, ponowienie cofnięcia wznawia
    pozycje), `undone` (cofnięcie domknęło wszystkie pozycje i katalogi). Przebieg nieznany →
    `ValueError` (EXPECT)."""
    with _immediate(con):
        cur = con.execute("UPDATE object_change_run SET status = ? WHERE run_id = ?",
                          (status, run_id))
        if cur.rowcount != 1:
            raise ValueError(f"przebieg zmiany obiektu {run_id} nie istnieje")


def close_object_change_undo(con, *, run_id, now, uid="local"):
    """DOMKNIĘCIE COFNIĘCIA PRZEBIEGU (AR-137, `Q8`) - JEDNA transakcja: status `undone` i nagrobek
    obiektu, który przebieg założył albo wskrzesił (`made_object_id`, `_retire_orphan_tx`). → powód
    odmowy nagrobka (`RETIRE_REFUSALS`) albo None (zdjęty, nic do zdjęcia, przebieg już domknięty).

    Nagrobek pada wyłącznie przy PRZEJŚCIU do `undone`: ponowne domknięcie domkniętego przebiegu nie
    sięga po obiekt, który inny gest mógł w międzyczasie wskrzesić. Odmowa (obiekt ma klatki, alias
    spoza gestu, inny żywy przebieg) zostawia obiekt na osi - to jest zwykły stan, nie błąd cofnięcia.
    Przebieg nieznany → `ValueError` (EXPECT)."""
    with _immediate(con):
        r = con.execute("SELECT status, made_object_id FROM object_change_run WHERE run_id = ?",
                        (run_id,)).fetchone()
        if r is None:
            raise ValueError(f"przebieg zmiany obiektu {run_id} nie istnieje")
        if r["status"] == "undone":
            return None
        con.execute("UPDATE object_change_run SET status = 'undone' WHERE run_id = ?", (run_id,))
        if r["made_object_id"] is None:
            return None
        return _retire_orphan_tx(con, axis="object", entity_id=r["made_object_id"], now=now,
                                 actor=f"user:{uid}", run_id=run_id)


def open_run_dir(con, *, run_id, path, action, now):
    """ZAMIAR mutacji katalogu gestu (0036, D-1011-5 Q3) - zatwierdzony WŁASNĄ transakcją PRZED
    `os.mkdir`/`os.rmdir`, nigdy w straży renamu. Zamiar sprzed awarii, którego mutacja nie zaszła
    (bez `done_at`), wraca jako TEN SAM wiersz - `UNIQUE(run_id, path, action)`, ścieżka bez wielkości
    liter. Wiersza ZAKOŃCZONEGO (`done_at`) nie otwieramy ponownie → `ValueError`, zero zapisu:
    katalog pod tą ścieżką po zakończonej mutacji założył albo opróżnił już ktoś inny, a ponowne
    otwarcie wymazałoby ślad gestu i oddało cudzy katalog do usunięcia. → id wiersza."""
    if action not in ("created", "removed", "restored"):
        raise ValueError(f"akcja katalogu {action!r} spoza ('created', 'removed', 'restored')")
    with _immediate(con):
        row = con.execute("SELECT id, done_at FROM run_dir WHERE run_id = ? AND path = ? "
                          "AND action = ?", (run_id, path, action)).fetchone()
        if row is not None and row["done_at"] is not None:
            raise ValueError(f"katalog {path} ({action}) już zamknięty w tym przebiegu - zamiaru "
                             f"nie otwieramy ponownie")
        if row is not None:
            con.execute("UPDATE run_dir SET opened_at = ? WHERE id = ?", (now, row["id"]))
            return row["id"]
        return con.execute("INSERT INTO run_dir(run_id, path, action, opened_at) "
                           "VALUES (?, ?, ?, ?)", (run_id, path, action, now)).lastrowid


def finish_run_dir(con, *, dir_id, now):
    """Mutacja katalogu zaszła (`done_at`) - po `os.mkdir`/`os.rmdir` albo w rekoncyliacji, gdy dysk
    pokazuje jej skutek. Wiersz już domknięty zostaje bez zmian (pierwsza chwila)."""
    with _immediate(con):
        con.execute("UPDATE run_dir SET done_at = ? WHERE id = ? AND done_at IS NULL",
                    (now, dir_id))


def undo_run_dir(con, *, dir_id, now):
    """Katalog założony przez gest usunięty (`undone_at`) - WYŁĄCZNIE wiersz `created` z `done_at`
    (własność pewna; CHECK 0036 odbija resztę). Wiersz już oznaczony zostaje bez zmian."""
    with _immediate(con):
        con.execute("UPDATE run_dir SET undone_at = ? WHERE id = ? AND action = 'created' "
                    "AND done_at IS NOT NULL AND undone_at IS NULL", (now, dir_id))


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


CALIBRATION_SOURCES = ("horreum", "user", "wbpp")
"""Słownik źródeł ogniwa kalibracji (`calibration.asserted_by`, komentarz DDL `0009`) - jedno źródło
dla obu klingi osi (`link_calibration`, `unlink_calibration`); `0009` nie ma na tej kolumnie CHECK,
więc pilnuje go kod (EXPECT)."""

CALIBRATION_REFUSALS = ("not_light", "not_master", "inactive", "camera", "drift")
"""Tokeny odmowy gestu ręki na osi kalibracji (`KalibratorOdrzucony.token`) - zdanie składa
powierzchnia z katalogu (`grid.lin.cal.refused.<token>`), parytet pilnuje `tests/test_i18n.py`."""

# Źródła ogniwa kalibracji, które przebieg rodowodu wylicza SAM i wolno mu je zdjąć (AR-81). Lista
# DOZWOLONYCH, nie zakazanych: źródło dopisane kiedyś do `0009` (`wbpp` - zeznanie pliku) jest
# chronione, dopóki ktoś świadomie go tu nie wpisze.
CALIBRATION_AUTO_SOURCES = ("horreum",)

_BEZ_OCZEKIWANIA = object()     # `link_calibration(expected=...)` niepodane - automat stanu nie zna


class KalibratorOdrzucony(ValueError):
    """Odmowa gestu ręki na osi kalibracji - stan bazy nie pozwala zapisać wskazania. Osobny typ
    (wzorzec `KlatkaNieJestZastapiona`), żeby powierzchnia łapała DOKŁADNIE odmowę z powodem
    (`token` z `CALIBRATION_REFUSALS`), a każdy inny błąd klingi leciał dalej."""

    def __init__(self, token, message):
        super().__init__(message)
        self.token = token


def _waliduj_wskazanie_kalibratora(con, *, light_frame_id, master_frame_id, relation, row,
                                   expected):
    """Bramka gałęzi `asserted_by='user'` - wołana POD blokadą `link_calibration`, więc to, co
    sprawdza, jest stanem, na który pada zapis. Ręka wskazuje DOWOLNY master (także spoza przepisu),
    ale nie dowolną klatkę: light musi być lightem, kalibrator aktywnym masterem tej klasy (bez
    nagrobka `retired_at`/`superseded_by`), oba z tej samej kamery, a ogniwo w stanie, który
    człowiek widział na ekranie (`expected`: `None` = brak ogniwa, albo `(master, asserted_by)`).
    Dryf między ekranem a bazą to odmowa, nie nadpisanie decyzji, której gest nie widział."""
    if expected is _BEZ_OCZEKIWANIA:
        raise ValueError("gest ręki bez oczekiwanego stanu ogniwa - nie ma czego porównać")
    light = con.execute("SELECT kind, camera_id FROM frame WHERE id = ?",
                        (light_frame_id,)).fetchone()
    if light is None or light["kind"] != "light":
        raise KalibratorOdrzucony("not_light", f"frame:{light_frame_id} nie jest lightem")
    master = con.execute(
        "SELECT kind, camera_id, retired_at, superseded_by FROM frame WHERE id = ?",
        (master_frame_id,)).fetchone()
    if master is None or master["kind"] != f"master_{relation}":
        raise KalibratorOdrzucony("not_master",
                                  f"frame:{master_frame_id} nie jest masterem klasy {relation}")
    if master["retired_at"] is not None or master["superseded_by"] is not None:
        raise KalibratorOdrzucony("inactive", f"frame:{master_frame_id} jest wycofany albo zastąpiony")
    if light["camera_id"] is None or light["camera_id"] != master["camera_id"]:
        raise KalibratorOdrzucony("camera", f"frame:{master_frame_id} z innej kamery niż light")
    stan = None if row is None else (row["master_frame_id"], row["asserted_by"])
    if stan != (None if expected is None else tuple(expected)):
        raise KalibratorOdrzucony("drift", f"ogniwo {relation} lighta {light_frame_id} zmieniło się: "
                                           f"{stan!r} zamiast {expected!r}")


def link_calibration(con, *, light_frame_id, master_frame_id, relation, now,
                     actor="lineage", asserted_by="horreum", confidence="recipe",
                     expected=_BEZ_OCZEKIWANIA):
    """RODOWÓD (C4): powiąż light z egzemplarzem mastera danej klasy — wiersz `calibration`
    + `event(calibration.linked)`. Idempotentny na kluczu UNIQUE(light_frame_id, relation) (0009):
    ten sam kalibrator → False BEZ eventu.

    GEST RĘKI (`asserted_by='user'`, E4-5): człowiek wskazuje dowolny aktywny master tej klasy
    i kamery, także spoza przepisu (`confidence='user'`). Ta gałąź WYMAGA `expected` - stanu ogniwa,
    który człowiek widział - i waliduje go pod blokadą (`_waliduj_wskazanie_kalibratora`); odmowa
    to `KalibratorOdrzucony` z tokenem. `_immediate`, bo guard (SELECT stanu) musi trzymać do
    zapisu: gest pisze z wątku GUI, gdy etap „Rodowód” liczy w tle na własnym połączeniu - lustro
    `link_integration`.

    Gdy dla tej klasy stał JUŻ inny master (doszedł bliższy czasowo w nowym wsadzie) → UPDATE
    + `event(calibration.unlinked)` na starym (ślad append-only) + `.linked` na nowym. To POŻĄDANE
    (lepszy kalibrator), nie regres — idempotencja liczy TYLKO brak zmiany.

    Verb należy do rodowodu: C2 celowo zostawił `calibration.linked/.unlinked` (użył
    `calibration_profile.assigned` dla klatka↔profil), by tej nazwy nie zająć.

    AUTOMAT NIE DEGRADUJE OGNIWA WSKAZANEGO RĘKĄ (E4-2, warunek Zdzinia 0809: „wprowadzanie nowych
    subów albo masterów nie może wpłynąć na wycofanie czegokolwiek już ustawionego ręcznie"). Do
    0809 była to JEDYNA oś rodowodu bez takiej bramki: siostrzana `link_integration` ma
    `RANGA_ASSERT`, `calibration_fact` ma człon `source == 'user'`, a tutaj nowy dark po prostu
    przepinał ogniwo - bezwarunkowym UPDATE-em. Trzymało to wyłącznie na ZERZE populacji (gestu
    ręki na tej osi wtedy nie było), więc pierwszy taki gest łamałby warunek po cichu. Teraz
    warunek trzyma MECHANIZM, a gest jest w panelu „Rodowód” („Wskaż kalibrator…”).

    Pełnej drabiny rang tu NIE MA i to jest świadome: `RANGA_ASSERT` opisuje słownik osi stosów
    (`history`/`window`/`user`), a ta oś ma własny (`horreum`, docelowo `wbpp` — DDL 0009). Dwa
    słowniki w jednym dicie zrobiłyby z kanonu wspólny worek. Pytanie, na które ta bramka odpowiada,
    jest jedno i binarne — „czy ręka już to rozstrzygnęła" — więc kształt jest taki sam, jak
    w `calibration_fact`, i urośnie dopiero razem z drugim nie-ludzkim źródłem."""
    if asserted_by not in CALIBRATION_SOURCES:
        raise ValueError(f"źródło ogniwa kalibracji spoza słownika: {asserted_by!r}")
    if asserted_by == "user" and confidence != "user":
        raise ValueError("wskazanie ręki niesie confidence='user' - inna pewność kłamałaby o źródle")
    with _immediate(con):
        row = con.execute(
            "SELECT id, master_frame_id, asserted_by FROM calibration "
            "WHERE light_frame_id = ? AND relation = ?",
            (light_frame_id, relation)).fetchone()
        if asserted_by == "user":
            _waliduj_wskazanie_kalibratora(con, light_frame_id=light_frame_id,
                                           master_frame_id=master_frame_id, relation=relation,
                                           row=row, expected=expected)
        # IDEMPOTENCJA PYTA O PARĘ (kalibrator, źródło), nie o sam kalibrator - inaczej bramka niżej
        # byłaby NIEOSIĄGALNA: ręka potwierdzająca ten sam master, który wybrał automat, odbijała się
        # od tego `return` i źródło zostawało `horreum`, więc werdykt nie miał jak powstać. Lustro
        # `link_integration`: „podniesienie pewności zostawia ślad".
        if row is not None and (row["master_frame_id"], row["asserted_by"]) == (master_frame_id,
                                                                                asserted_by):
            return False
        if row is not None and row["asserted_by"] == "user" and asserted_by != "user":
            return False
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
                                    "master_frame_id": row["master_frame_id"],
                                    "asserted_by": row["asserted_by"], "reason": "relinked"})
        emit_event(con, actor=actor, verb="calibration.linked",
                   target=f"frame:{light_frame_id}", now=now,
                   payload={"relation": relation, "master_frame_id": master_frame_id,
                            "asserted_by": asserted_by,
                            **({"before": [row["master_frame_id"], row["asserted_by"]]}
                               if row is not None else {})})
    return True


def unlink_calibration(con, *, light_frame_id, relation, allowed, reason, now, actor="lineage",
                       expected_master_frame_id=None):
    """Zdejmij ogniwo kalibracji - `DELETE` wiersza `calibration` + `event(calibration.unlinked)`
    z `asserted_by` zdjętego wiersza i tokenem `reason` w payloadzie. `True` = wiersz zniknął.

    Dwóch wołających, dwie listy DOZWOLONYCH źródeł - i to wołający je podaje, bo pytanie jest
    różne: przebieg rodowodu zdejmuje ogniwo AUTOMATU, dla którego derywacja nie ma już kandydata
    (AR-81, `allowed=CALIBRATION_AUTO_SOURCES`, `reason` = token luki), a gest „Przywróć automat”
    zdejmuje wskazanie RĘKI (`allowed=('user',)`), żeby przebieg odtworzył dobór z przepisu. Lista
    pusta albo źródło spoza `0009` to błąd wołającego (EXPECT), nie cichy brak zapisu.

    `expected_master_frame_id` (gest) - CAS: zdejmujemy wyłącznie ogniwo, które człowiek widział;
    inne = `False` bez zapisu. Brak wiersza albo źródło spoza listy - `False` bez eventu
    (idempotencja: drugi przebieg niczego nie zdejmuje). `_immediate`, bo guard i `DELETE` muszą
    widzieć ten sam stan - lustro `link_calibration`."""
    allowed = tuple(allowed)
    if not allowed or not set(allowed) <= set(CALIBRATION_SOURCES):
        raise ValueError(f"lista źródeł do zdjęcia spoza 0009: {allowed!r}")
    if not reason:
        raise ValueError("zdjęcie ogniwa bez powodu - token jest treścią eventu")
    with _immediate(con):
        row = con.execute(
            "SELECT id, master_frame_id, asserted_by FROM calibration "
            "WHERE light_frame_id = ? AND relation = ?", (light_frame_id, relation)).fetchone()
        if row is None or row["asserted_by"] not in allowed:
            return False
        if expected_master_frame_id is not None and row["master_frame_id"] != expected_master_frame_id:
            return False
        con.execute("DELETE FROM calibration WHERE id = ?", (row["id"],))
        emit_event(con, actor=actor, verb="calibration.unlinked",
                   target=f"frame:{light_frame_id}", now=now,
                   payload={"relation": relation, "master_frame_id": row["master_frame_id"],
                            "asserted_by": row["asserted_by"], "reason": reason})
    return True


def flag_calibration_lineage_summary(con, items, now, actor="lineage", unlinked=None,
                                     hand_inactive=None):
    """Lighty BEZ pokrycia kalibratorem — JEDEN `event(calibration.lineage_summary)` z licznością
    per powód (wzorzec `flag_calibration_review_summary`). Stan (brak wiersza `calibration` dla
    `(light, relation)`) SAM jest deltą; to event audytowy, nie zapis na frame. Wszystko puste →
    bez eventu, więc idempotentny przebieg bez luk nie emituje (jak review_summary).

    `unlinked` (relacja → licznik) to ogniwa automatu zdjęte w TYM przebiegu: bez kandydata (AR-81)
    albo na klatce, która przestała być lightem. `hand_inactive` (relacja → licznik) to STAN:
    wskazania ręki na masterze wycofanym, zastąpionym albo bez obecnej kopii. Każde z nich samo
    wystarcza, żeby event powstał - bez śladu w dzienniku wyglądałyby jak brak roboty."""
    items = list(items)
    if not items and not unlinked and not hand_inactive:
        return
    with con:
        emit_event(con, actor=actor, verb="calibration.lineage_summary", target="frame:*", now=now,
                   payload={"distinct": len(items), "frames": sum(n for _, n in items),
                            "items": [[reason, n] for reason, n in items],
                            "unlinked": dict(unlinked or {}),
                            "hand_inactive": dict(hand_inactive or {})})


# ═══════════════════════════════════════════════ 1.7b RODOWÓD STOSÓW (I-2c, P-I)
# Siostra rodowodu kalibracji, ale o innej tożsamości: tam kluczem był (light, relation), tu
# KLATKA MASTERA (migracja 0012, §4.1 briefu). Wejścia są zbiorem osobno, bo zbiór bywa
# WYLICZONY (okno czasu), a wyliczenie nie ma prawa być kluczem rekordu.

BEZ_ZMIAN = object()
"""Wartość wstrzymująca klingi: „tej kolumny nie ruszaj” - inna niż `None`, które jest faktem (brak)."""


def upsert_integration(con, *, master_frame_id, integ_hash, tool, window_start, window_end,
                       declared_rows, drizzle_inputs, disabled_inputs, degenerate, ambiguous,
                       telescope_mismatch, unresolved_reason, now, actor="stacks",
                       raw_unreferenced=None, creation_time=None, lineage_basis=BEZ_ZMIAN,
                       outside_window=BEZ_ZMIAN, used_rows=BEZ_ZMIAN):
    """Wiersz `integration` dla klatki mastera — `(integration_id, zmienione)`.

    PODSTAWA RODOWODU (migracja 0034, AR-108): `lineage_basis` - na czym stoi ranga `history`
    (`name` / `temp` / `count`, słownik `stacks.LINEAGE_BASES`), `outside_window` - zbiór z nazw
    sięga klatek spoza okna nagłówka, `used_rows` - N werdyktu „plik użył N z M klatek okna”.
    Liczy je WYŁĄCZNIE przebieg rodowodu (`stacks.run_stack_lineage`, podaje wszystkie trzy).
    Domyślne `BEZ_ZMIAN` = „nie ruszaj zapisanej kolumny” (nowy wiersz: NULL / 0 / NULL): wołający,
    który podstawy nie liczy - rodowód z żniw - nie ma prawa jej skasować.

    `raw_unreferenced` (G2-1d, migracja 0020) to UWAGA obok werdyktu, nie drugi werdykt: ile
    RAW-ów przebieg widział i nie umiał umieścić w czasie. Jedzie w TEJ liście pól, bo jest
    wyliczana z bazy co przebieg (lustro `telescope_mismatch`), a nie werdyktem ręki (jak offset).
    Domyślne `None` = „brak uwagi"; CHECK 0020 odbija zero i dubel z `offset_unknown`.

    `creation_time` (AR-10, migracja 0026) to fakt zeznania pliku jak `tool`: `XISF:CreationTime`,
    data stosów sprzed sygnatury integracji. Jedyny wołający (`stacks.run_stack_lineage`) chroni
    go przy nieczytelnym pliku tak samo jak sygnaturę.

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
              "raw_unreferenced": raw_unreferenced, "creation_time": creation_time,
              "lineage_basis": lineage_basis, "outside_window": outside_window,
              "used_rows": used_rows}
    with _immediate(con):
        row = con.execute(
            "SELECT id, integ_hash, tool, window_start, window_end, declared_rows, drizzle_inputs, "
            "disabled_inputs, degenerate, ambiguous, telescope_mismatch, unresolved_reason, "
            "raw_unreferenced, creation_time, lineage_basis, outside_window, used_rows "
            "FROM integration WHERE master_frame_id = ?", (master_frame_id,)).fetchone()
        for k, pusto in (("lineage_basis", None), ("outside_window", 0), ("used_rows", None)):
            if fields[k] is BEZ_ZMIAN:
                fields[k] = pusto if row is None else row[k]
        wartosci = list(fields.values())
        if row is None:
            cur = con.execute(
                "INSERT INTO integration(master_frame_id, created_at, integ_hash, tool, "
                "window_start, window_end, declared_rows, drizzle_inputs, disabled_inputs, "
                "degenerate, ambiguous, telescope_mismatch, unresolved_reason, raw_unreferenced, "
                "creation_time, lineage_basis, outside_window, used_rows) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
            "raw_unreferenced = ?, creation_time = ?, lineage_basis = ?, outside_window = ?, "
            "used_rows = ? WHERE id = ?", [now] + wartosci + [row["id"]])
        emit_event(con, actor=actor, verb="integration.updated",
                   target=f"frame:{master_frame_id}", now=now,
                   payload={"integration_id": row["id"],
                            "before": {k: v[0] for k, v in zmiany.items()},
                            "after": {k: v[1] for k, v in zmiany.items()}})
        return row["id"], True


def record_integration_creation_time(con, *, master_frame_id, creation_time, now, actor="stacks"):
    """Sam `creation_time` (AR-10, 0026) w ISTNIEJĄCEJ głowie integracji - `True`, gdy drgnął.

    Wąska siostra `upsert_integration` dla jedynej gałęzi przebiegu, która głowy nie przepisuje:
    stos z rodowodem chronionym i powodem (`stacks.run_stack_lineage`) zostaje w całości, a jego
    czytelny plik i tak zeznaje datę - bez tej klingi taki stos nigdy by jej nie dostał. Pozostałe
    pola są tam nietykalne, więc pełny upsert nie wchodzi w grę.

    EXPECT: pusta data i brak głowy to błąd wołającego - klinga uzupełnia fakt, nie kasuje go i nie
    zakłada rekordu. Ta sama data → `False` bez eventu; inaczej `integration.updated` z `{before,
    after}` jak w `upsert_integration` (jeden kształt payloadu dla czytelników dziennika)."""
    if not creation_time:
        raise ValueError(f"data stosu {master_frame_id}: pusta {creation_time!r}")
    with _immediate(con):
        row = con.execute("SELECT id, creation_time FROM integration WHERE master_frame_id = ?",
                          (master_frame_id,)).fetchone()
        if row is None:
            raise ValueError(f"data stosu {master_frame_id}: brak głowy integracji")
        if row["creation_time"] == creation_time:
            return False
        con.execute("UPDATE integration SET updated_at = ?, creation_time = ? WHERE id = ?",
                    (now, creation_time, row["id"]))
        emit_event(con, actor=actor, verb="integration.updated",
                   target=f"frame:{master_frame_id}", now=now,
                   payload={"integration_id": row["id"],
                            "before": {"creation_time": row["creation_time"]},
                            "after": {"creation_time": creation_time}})
        return True


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


RANGA_ASSERT = {"window": 0, "history": 1, "harvest": 2, "user": 3}
"""Precedencja zeznania o wejściu stosu — JEDEN właściciel kanonu (`link_integration` ORAZ strażnik
przebiegu w `stacks`). Do S2b liczba żyła jako zmienna lokalna klingi, więc przebieg, który musi
zapytać „czy ZAPISANY rodowód jest mocniejszy od tego, co umiem policzyć TERAZ", nie miał jej skąd
wziąć i odpowiadał wyliczanką wartości — a wyliczanka gubi sąsiednie zeznanie przy każdym nowym
źródle. Rosnąco: `window` (dobór z bieżącego stanu bazy) < `history` (zeznanie pliku potwierdzone
oknem czasu) < `harvest` (zbiór dokładny z żniw - nazwy w historii pliku ↔ lighty, które Horreum sam
wydał; migracja 0033, AR-102) < `user` (werdykt ręki). `harvest` stoi NAD `history`, bo test okna
przy nazwach bez temperatury jest samym licznikiem: okno równej liczności z inną klatką przechodzi go
i bez tej rangi przepisywało zbiór dokładny (D-1011-2)."""


def link_integration(con, *, integration_id, input_frame_id, asserted_by, now, actor="stacks"):
    """Powiąż klatkę wejściową ze stosem — wiersz `integration_input` + `event(integration.linked)`.

    Idempotentny na UNIQUE(integration_id, input_frame_id) z 0012: relacja o tym samym źródle
    → `False` bez eventu. Zmiana źródła (np. kandydat z okna DOWIEDZIONY historią) to UPDATE
    z eventem — podniesienie pewności zostawia ślad.

    PRECEDENCJA `user` > `harvest` > `history` > `window` STOI TU, w klindze, nie w pętli wołającego: pewność
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

    Zdejmuje WYŁĄCZNIE zeznania automatu, które da się przeliczyć (`window`, `history`) - rozstrzygnięcia
    ręki (`user`) i zbioru dokładnego z żniw (`harvest`) automat nie ma prawa cofać. Guard stoi TU,
    bo ostatnią bramką jest klinga, nie pętla, i jest LISTĄ DOZWOLONYCH, nie zakazanych: ranga
    dopisana kiedyś do `RANGA_ASSERT` jest chroniona, dopóki ktoś świadomie jej tu nie wpisze (stos
    mieszany `harvest` + `history` ma minimum równe planowi okna i przechodzi przez `_reconcile`).
    Transakcja przez `_tx`: rodowód z żniw zdejmuje wejścia automatu w zakresie `atomic` razem z resztą
    zapisu stosu, a goły `with con:` zatwierdziłby ten zakres w połowie."""
    with _tx(con):
        cur = con.execute(
            "DELETE FROM integration_input WHERE integration_id = ? AND input_frame_id = ? "
            "AND asserted_by IN ('window', 'history')", (integration_id, input_frame_id))
        if not cur.rowcount:
            return False
        emit_event(con, actor=actor, verb="integration.unlinked",
                   target=f"integration:{integration_id}", now=now,
                   payload={"input_frame_id": input_frame_id})
    return True


@dataclass(frozen=True)
class JudgedInput:
    """Jedna zmiana werdyktu ręki - materiał cofnięcia. `before` = `(asserted_by, excluded)` wiersza
    sprzed gestu albo `None`, gdy wiersza nie było; `excluded` = werdykt, który gest zapisał."""
    input_frame_id: int
    before: object
    excluded: int


def judge_integration_input(con, *, integration_id, input_frame_id, excluded, now, uid="local",
                            changes_out=None):
    """ROZSTRZYGNIĘCIE RĘKĄ (I-2d): człowiek potwierdza kandydata albo go odrzuca —
    `asserted_by='user'` + `excluded` 0/1, `event(integration.judged)`.

    ODRZUCONY WIERSZ ZOSTAJE, nie znika: „ta klatka NIE weszła w ten obraz" jest faktem tak samo
    jak „weszła", a skasowanie go kazałoby automatowi odkrywać ją na nowo przy każdym przebiegu.
    Precedencji broni `link_integration`/`unlink_integration_input` (oba omijają `user`), więc
    werdykt przeżywa kolejne przebiegi rodowodu.

    Idempotentny: ten sam werdykt na tym samym wierszu → `False` bez eventu (przeklikanie w oknie
    nie ma prawa puchnąć dziennika).

    `changes_out` (lista) dostaje `JudgedInput` każdej REALNEJ zmiany - stan sprzed gestu odczytany
    pod tą samą blokadą co zapis, więc „Cofnij” przywraca to, co klinga nadpisała, a nie to, co
    ekran pamiętał (`restore_integration_judgment`). Odczyt z dziennika zdarzeń byłby wyścigiem."""
    excluded = 1 if excluded else 0
    with _immediate(con):
        row = con.execute(
            "SELECT rowid AS rid, asserted_by, excluded FROM integration_input "
            "WHERE integration_id = ? AND input_frame_id = ?",
            (integration_id, input_frame_id)).fetchone()
        if row is not None and (row["asserted_by"], row["excluded"]) == ("user", excluded):
            return False
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
    if changes_out is not None:
        changes_out.append(JudgedInput(
            input_frame_id, None if row is None else (row["asserted_by"], row["excluded"]), excluded))
    return True


def judge_integration_inputs(con, *, integration_id, input_frame_ids, excluded, now, uid="local"):
    """Werdykt ręki na KILKU wejściach jednego stosu - jeden gest = jedna transakcja (`atomic`):
    wszystkie wiersze zapisują się razem albo żaden. Osobne transakcje per wiersz zostawiały po
    awarii w połowie gest częściowo zapisany i bez materiału „Cofnij”. Zwraca listę `JudgedInput`
    realnych zmian (idempotentne powtórzenia nie wchodzą)."""
    zmiany = []
    with atomic(con):
        for fid in input_frame_ids:
            judge_integration_input(con, integration_id=integration_id, input_frame_id=fid,
                                    excluded=excluded, now=now, uid=uid, changes_out=zmiany)
    return zmiany


def restore_integration_judgment(con, *, integration_id, change, now, uid="local"):
    """COFNIĘCIE werdyktu ręki: wiersz wraca do stanu sprzed gestu (`change.before`), a gdy wiersza
    przed gestem nie było - znika. Bez tej klingi „Cofnij” mogło tylko zapisać werdykt przeciwny,
    czyli zostawić `user` tam, gdzie przed gestem decydował automat (`window`/`history`).

    CAS pod blokadą: przywracamy WYŁĄCZNIE wiersz, który dalej niesie werdykt tego gestu
    (`user` + `change.excluded`). Inny stan (nowszy werdykt, przebieg rodowodu, drugie cofnięcie)
    = `False` bez zapisu i bez eventu - cofnięcie nie ma prawa nadpisać decyzji, której nie widziało.
    `event(integration.judgment_restored)` niesie oba stany."""
    with _immediate(con):
        row = con.execute(
            "SELECT rowid AS rid, asserted_by, excluded FROM integration_input "
            "WHERE integration_id = ? AND input_frame_id = ?",
            (integration_id, change.input_frame_id)).fetchone()
        if row is None or (row["asserted_by"], row["excluded"]) != ("user", change.excluded):
            return False
        if change.before is None:
            con.execute("DELETE FROM integration_input WHERE rowid = ?", (row["rid"],))
        else:
            con.execute(
                "UPDATE integration_input SET asserted_by = ?, excluded = ? WHERE rowid = ?",
                (change.before[0], change.before[1], row["rid"]))
        emit_event(con, actor=f"user:{uid}", verb="integration.judgment_restored",
                   target=f"integration:{integration_id}", now=now,
                   payload={"input_frame_id": change.input_frame_id,
                            "undone": {"asserted_by": "user", "excluded": change.excluded},
                            "restored": None if change.before is None else
                            {"asserted_by": change.before[0], "excluded": change.before[1]}})
    return True


def judge_stacks_inputs(con, *, inputs_by_master, excluded, now, uid="local"):
    """Werdykt ręki na wejściach KILKU stosów jednym gestem (AR-178: „Odrzuć nowsze niż obraz we
    wszystkich obrazach") - jedna transakcja (`atomic`) dla wszystkich: gest zapisuje się cały albo
    wcale, więc jedno „Cofnij” ma komplet materiału. `inputs_by_master` = `{master_frame_id:
    input_frame_ids}`; integrację stosu wskazuje jego klatka (UNIQUE z 0012). Każdy stos idzie
    klingą jednego stosu (`judge_integration_inputs`) - zdarzenia, idempotencja i precedencja
    zostają w jednym miejscu. Stos bez wiersza `integration` to błąd wołającego (EXPECT) i wycofuje
    cały gest. Zwraca `[(master_frame_id, integration_id, (JudgedInput, …)), …]` stosów z realną
    zmianą, w kolejności `inputs_by_master`."""
    wynik = []
    with atomic(con):
        for master, ids in inputs_by_master.items():
            row = con.execute("SELECT id FROM integration WHERE master_frame_id = ?",
                              (master,)).fetchone()
            if row is None:
                raise ValueError(f"frame:{master} nie ma wiersza integration")
            zmiany = judge_integration_inputs(con, integration_id=row["id"],
                                              input_frame_ids=list(ids), excluded=excluded,
                                              now=now, uid=uid)
            if zmiany:
                wynik.append((master, row["id"], tuple(zmiany)))
    return wynik


def restore_integration_judgments(con, *, changes, now, uid="local"):
    """COFNIĘCIE gestu werdyktu w JEDNEJ transakcji (`atomic`) - jednego stosu albo zbiorczego
    (AR-178). `changes` = `(integration_id, JudgedInput)` z klingi gestu. Każdy wiersz przechodzi
    CAS `restore_integration_judgment`: wiersz zmieniony po geście (nowszy werdykt, przebieg)
    zostaje, reszta wraca - a awaria w połowie nie zostawia gestu cofniętego częściowo (osobne
    transakcje per wiersz zostawiały). Zwraca liczbę przywróconych wierszy."""
    with atomic(con):
        return sum(restore_integration_judgment(con, integration_id=iid, change=z, now=now,
                                                uid=uid)
                   for iid, z in changes)


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


def record_stack_history(con, *, location_id, hdr_hash, history, now, actor="scan"):
    """HISTORIA STOSU KOPII w bazie (migracja 0034, AR-87) - `True`, gdy wiersz drgnął.

    `history` = `resolve.stack.History` (krotka `(rows, inputs, tool)` + `.created`) z odczytu
    nagłówka, którego odcisk to `hdr_hash`. KOTWICA (CAS): zapis wyłącznie przy
    `location.header_hash == hdr_hash` W TEJ transakcji - odczyt starszy od bieżącego nagłówka
    kopii (zapis w miejscu, skan w międzyczasie) zwraca `False` bez zapisu, bo historia opisywałaby
    nagłówek, którego na kopii już nie ma. Czytelnik (`stacks._plan`) porównuje tę samą kotwicę.

    Idempotentny: ten sam odcisk i ta sama treść → `False` bez eventu (drugi przebieg skanu czy
    uzupełnienia nie puchnie dziennika). Inna treść albo inny odcisk → wiersz i wejścia przepisane
    w całości (wejścia to lustro pliku, nie fakt z własną historią - jak karty `cards`) i JEDEN
    `stack_history.recorded` z odciskami przed/po i liczbami, bez listy wejść (ta leży w tabeli,
    a 3348 ścieżek w dzienniku byłoby balastem).

    Wywoływana wewnątrz `atomic` skanu (`scan._ingest_in_tx`) albo samodzielnie (uzupełnienie,
    odświeżenie w rodowodzie) - `_immediate` dołącza do zakresu zewnętrznego."""
    if not hdr_hash:
        raise ValueError(f"historia stosu location:{location_id} bez odcisku nagłówka")
    rows, inputs, tool = history
    tool = tool or None                      # pusta sygnatura to brak faktu (CHECK 0034)
    created = getattr(history, "created", None) or None
    wejscia = [(location_id, seq, i.path, int(bool(i.enabled)), int(bool(i.has_drizzle)),
                None if i.set_temp_c is None else float(i.set_temp_c))
               for seq, i in enumerate(inputs)]
    with _immediate(con):
        kopia = con.execute("SELECT header_hash FROM location WHERE id = ?",
                            (location_id,)).fetchone()
        if kopia is None:
            raise ValueError(f"historia stosu: location:{location_id} nie istnieje")
        if kopia["header_hash"] != hdr_hash:
            return False
        byl = con.execute("SELECT hdr_hash, declared_rows, tool, creation_time FROM stack_history "
                          "WHERE location_id = ?", (location_id,)).fetchone()
        if byl is not None and (byl["hdr_hash"], byl["declared_rows"], byl["tool"],
                                byl["creation_time"]) == (hdr_hash, rows, tool, created):
            stare = [tuple(r) for r in con.execute(
                "SELECT location_id, seq, path, enabled, has_drizzle, temp_c FROM stack_history_input "
                "WHERE location_id = ? ORDER BY seq", (location_id,))]
            if stare == wejscia:
                return False
        con.execute("DELETE FROM stack_history_input WHERE location_id = ?", (location_id,))
        con.execute(
            "INSERT INTO stack_history(location_id, hdr_hash, declared_rows, tool, creation_time) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(location_id) DO UPDATE SET "
            "hdr_hash = excluded.hdr_hash, declared_rows = excluded.declared_rows, "
            "tool = excluded.tool, creation_time = excluded.creation_time",
            (location_id, hdr_hash, rows, tool, created))
        con.executemany(
            "INSERT INTO stack_history_input(location_id, seq, path, enabled, has_drizzle, temp_c) "
            "VALUES (?, ?, ?, ?, ?, ?)", wejscia)
        emit_event(con, actor=actor, verb="stack_history.recorded", target=f"location:{location_id}",
                   now=now, payload={"before_hdr_hash": byl["hdr_hash"] if byl is not None else None,
                                     "hdr_hash": hdr_hash, "declared_rows": rows,
                                     "inputs": len(wejscia),
                                     "enabled": sum(w[3] for w in wejscia)})
    return True


def clear_stack_history(con, *, location_id, now, actor="scan"):
    """Zdejmij historię stosu z kopii, która przestała nieść stos (0034) - `True`, gdy wiersz był.

    Przepięcie lokacji na treść innego rodzaju (pod ścieżką stosu leży dziś np. light) zostawiało
    wiersz `stack_history` przy `location_id`, który dalej istnieje: czytelnicy go nie widzą (łączą
    przez `kind='master_light'`), ale tabela niosłaby zeznanie o pliku, którego nie ma. Wiersz jest
    lustrem nagłówka, nie faktem z własną historią - DELETE wejść i głowy + `stack_history.cleared`
    z odciskiem, który opisywał. Brak wiersza → `False` bez eventu (skan woła to przy każdym rekordzie
    nie-stosu, więc cisza jest regułą)."""
    with _immediate(con):
        byl = con.execute("SELECT hdr_hash FROM stack_history WHERE location_id = ?",
                          (location_id,)).fetchone()
        if byl is None:
            return False
        con.execute("DELETE FROM stack_history_input WHERE location_id = ?", (location_id,))
        con.execute("DELETE FROM stack_history WHERE location_id = ?", (location_id,))
        emit_event(con, actor=actor, verb="stack_history.cleared", target=f"location:{location_id}",
                   now=now, payload={"hdr_hash": byl["hdr_hash"]})
    return True


LIGHT_ALIAS_SOURCES = ("custos", "horreum")
"""Źródła aliasu nazwy lightu - lustro CHECK-a 0034: `custos` = zapis przenosin dawcy (import
jednorazowy), `horreum` = dawna nazwa przy zmianie nazwy przez Horreum (`_apply_relocation`)."""


def record_light_name_aliases(con, *, aliases, source, now, actor):
    """Wsad aliasów nazw lightów (`light_name_alias`, AR-108) → ile wierszy PRZYBYŁO.

    `aliases` = pary `(frame_id, stem)`; `stem` to rdzeń `resolve.stack.raw_stem` dawnej nazwy.
    EXPECT przed zapisem: źródło ze słownika, rdzeń niepusty i w postaci `raw_stem` (małe litery, bez
    separatora ścieżki - `raw_stem(stem)` NIE jest testem, bo nazwy WBPP niosą kropki, które `splitext`
    uciąłby jak rozszerzenie), klatka istnieje i jest lightem - alias wskazuje wejście stosu, a stos
    nie wchodzi w stos.
    Naruszenie → `ValueError` i zero zapisu (cały wsad w jednej transakcji).

    Idempotentny na `UNIQUE(stem, frame_id)`: powtórka tego samego wsadu → 0 i bez eventu. Wsad
    z przyrostem → JEDEN `light_name_alias.imported` z liczbami (import Custos to dziesiątki tysięcy
    par - event per alias byłby dziennikiem wielkości tabeli; pojedynczy alias z relokacji ma własny
    event w `_dopisz_alias_nazwy`). Ten sam rdzeń przy dwóch klatkach tabela przyjmuje świadomie:
    czytelnik traktuje go jako nazwę niejednoznaczną i odmawia."""
    if source not in LIGHT_ALIAS_SOURCES:
        raise ValueError(f"źródło aliasu {source!r} spoza {LIGHT_ALIAS_SOURCES}")
    pary = sorted({(int(f), s) for f, s in aliases})
    zle = [s for _f, s in pary if not s or s != s.lower() or "/" in s or "\\" in s]
    if zle:
        raise ValueError(f"rdzeń aliasu pusty albo nieznormalizowany: {zle[:5]}")
    with _immediate(con):
        ids = sorted({f for f, _s in pary})
        lighty = {r[0] for r in con.execute(
            "SELECT id FROM frame WHERE kind = 'light' AND id IN (SELECT value FROM json_each(?))",
            (json.dumps(ids),))}
        if set(ids) - lighty:
            raise ValueError(f"alias nazwy przy klatce spoza lightów: {sorted(set(ids) - lighty)[:5]}")
        przed = con.execute("SELECT count(*) FROM light_name_alias").fetchone()[0]
        con.executemany("INSERT OR IGNORE INTO light_name_alias(frame_id, stem, source) "
                        "VALUES (?, ?, ?)", [(f, s, source) for f, s in pary])
        nowe = con.execute("SELECT count(*) FROM light_name_alias").fetchone()[0] - przed
        if nowe:
            emit_event(con, actor=actor, verb="light_name_alias.imported", target="frame:*",
                       now=now, payload={"source": source, "added": nowe, "pairs": len(pary),
                                         "frames": len(ids)})
    return nowe


def keep_stack_versions(con, *, frame_ids, group_key, now, uid="local"):
    """WERDYKT „ZOSTAWIAM WSZYSTKIE" grupy wersji stosów (AR-10, migracja 0026) - ile klatek drgnęło.

    Człowiek ma prawo zostawić kilka integracji tego samego materiału i nigdy do nich nie wracać;
    bez tego zapisu wiersz Porządków „Wersje stosów" nie miał innej drogi do zera niż skasowanie
    pliku poza programem. Wiersz na KAŻDEGO członka grupy, wszystkie z jednym `group_key`
    (identyfikator grupy z chwili gestu, `queries._id_grupy_wersji`) - read-model uznaje grupę za
    rozstrzygniętą, gdy każdy jej obecny członek ma wiersz z tym samym kluczem (powód w 0026).

    Członek z werdyktem INNEJ grupy dostaje klucz bieżącego gestu: gest opisuje grupę, którą człowiek
    właśnie widzi. Idempotentny: klatki z tym samym kluczem → pominięte, bez eventu. EXPECT: pusty
    klucz albo mniej niż dwie klatki to błąd wołającego (grupa ma co najmniej dwa stosy)."""
    ids = sorted({int(i) for i in frame_ids})
    if not group_key or len(ids) < 2:
        raise ValueError(f"werdykt wersji: grupa {group_key!r} z {len(ids)} klatek")
    zmienione = 0
    with _immediate(con):
        przed = {r["frame_id"]: r["group_key"] for r in con.execute(
            "SELECT frame_id, group_key FROM stack_version_kept "
            "WHERE frame_id IN (SELECT value FROM json_each(?))", (json.dumps(ids),))}
        for fid in ids:
            if przed.get(fid) == group_key:
                continue
            con.execute(
                "INSERT INTO stack_version_kept(frame_id, group_key, decided_at) VALUES (?, ?, ?) "
                "ON CONFLICT(frame_id) DO UPDATE SET group_key = excluded.group_key, "
                "decided_at = excluded.decided_at", (fid, group_key, now))
            emit_event(con, actor=f"user:{uid}", verb="stack_versions.kept",
                       target=f"frame:{fid}", now=now,
                       payload={"group_key": group_key, "group_key_before": przed.get(fid),
                                "members": ids})
            zmienione += 1
    return zmienione


def reopen_stack_versions(con, *, frame_ids, now, uid="local"):
    """COFNIĘCIE werdyktu „zostawiam wszystkie" (droga powrotu `keep_stack_versions`) - ile klatek
    drgnęło. Kasuje wiersze werdyktu tych klatek, więc grupa wraca do roboty i do plakietki.

    Kasacja, nie flaga: werdykt jest jedynym faktem wiersza, a jego historia (kto, kiedy, jaki klucz)
    zostaje w dzienniku - event niesie stan sprzed cofnięcia. Klatka bez werdyktu → pominięta bez
    eventu (idempotencja)."""
    ids = sorted({int(i) for i in frame_ids})
    zmienione = 0
    with _immediate(con):
        for r in con.execute(
                "SELECT frame_id, group_key, decided_at FROM stack_version_kept "
                "WHERE frame_id IN (SELECT value FROM json_each(?)) ORDER BY frame_id",
                (json.dumps(ids),)).fetchall():
            con.execute("DELETE FROM stack_version_kept WHERE frame_id = ?", (r["frame_id"],))
            emit_event(con, actor=f"user:{uid}", verb="stack_versions.reopened",
                       target=f"frame:{r['frame_id']}", now=now,
                       payload={"group_key_before": r["group_key"],
                                "decided_at_before": r["decided_at"]})
            zmienione += 1
    return zmienione


STACK_VARIANTS = frozenset({"autocrop"})
"""Słownik rodzajów wariantu kadru stosu - LUSTRO CHECK-a `stack_variant.variant` (0035)."""

RANGA_WARIANTU = {"window": 0, "location": 1, "user": 2}
"""Precedencja świadka pary wariant-oryginał - LUSTRO CHECK-a `stack_variant.source` (0035), jeden
właściciel dla klingi i testów. Rosnąco: `window` (jednoznaczne okno `DATE-OBS`/`DATE-END`/`FILTER`
wśród stosów - zbieżność czasu, nie ślad pochodzenia) < `location` (dawna lokacja oryginału w tym
samym katalogu co autocrop: PixInsight zapisuje przycięcie obok pliku, który przycina) < `user`
(wskazanie ręką)."""


def link_stack_variant(con, *, variant_frame_id, original_frame_id, variant, source, now,
                       original_path=None, actor="stack_variants"):
    """Zapisz relację wariantu kadru (`stack_variant`, 0035) + `event(stack_variant.linked)`. Zwraca
    True, gdy wiersz drgnął.

    STAN OBU KLATEK SPRAWDZANY POD BLOKADĄ: obie aktywne (`retired_at`/`superseded_by` NULL),
    oryginał z OBECNĄ kopią - a gdy wołający zna kopię, przy której zeznanie postawiło parę
    (`original_path`, kopia w `STACKS` z zeznania), to właśnie ta kopia musi być obecna. Oryginał
    skasowany, podmieniony albo wycofany między planem a Dostawą daje odmowę, nie relację do klatki,
    której już nie ma. UNIQUE(oryginał, wariant): drugi autocrop tego samego oryginału to odmowa.

    PRECEDENCJA W KLINDZE, jak `link_integration`: świadka wolno PODNIEŚĆ, nigdy obniżyć - wiersz
    o randze wyższej niż `source` zostaje nietknięty (`False`, bez eventu), więc automat nie
    przepisze ręki ani pary z dawnej lokacji parą z samego okna. Ta sama ranga z inną parą to
    przeliczenie automatu i przechodzi. Pełna ta sama wartość (oryginał, wariant, źródło) → `False`
    bez eventu - drugi przebieg konsumenta zeznań jest ciszą. Event niesie stan PRZED (`before`)
    i PO, więc droga powrotu jest w dzienniku.

    GUARDY (`ValueError`, zero zapisu), wszystkie WEWNĄTRZ `_immediate` (TOCTOU): źródło spoza
    `RANGA_WARIANTU`, wariant spoza `STACK_VARIANTS`, klatka jako wariant samej siebie, któraś
    klatka nie istnieje albo nie jest gotowym obrazem (`master_light`), GŁĘBOKOŚĆ > 1 - oryginał
    jest już czyimś wariantem albo wariant jest już czyimś oryginałem. Łańcuch wariant wariantu
    zrobiłby z dziedziczenia obiektu rekurencję, której resolver nie liczy (bierze obiekt oryginału
    jednym krokiem); pętla przez dwa wiersze byłaby tym samym błędem w krótszej formie."""
    if source not in RANGA_WARIANTU:
        raise ValueError(f"źródło wariantu {source!r} spoza {sorted(RANGA_WARIANTU)}")
    if variant not in STACK_VARIANTS:
        raise ValueError(f"wariant {variant!r} spoza {sorted(STACK_VARIANTS)}")
    if variant_frame_id == original_frame_id:
        raise ValueError(f"klatka {variant_frame_id} nie może być wariantem samej siebie")
    with _immediate(con):
        klatki = {r["id"]: r for r in con.execute(
            "SELECT id, kind, retired_at, superseded_by FROM frame WHERE id IN (?, ?)",
            (variant_frame_id, original_frame_id))}
        for fid in (variant_frame_id, original_frame_id):
            k = klatki.get(fid)
            if k is None or k["kind"] != "master_light":
                raise ValueError(f"klatka {fid} nie jest gotowym obrazem "
                                 f"(kind={k['kind'] if k is not None else None!r})")
            if k["retired_at"] is not None or k["superseded_by"] is not None:
                raise ValueError(f"klatka {fid} wycofana albo zastąpiona")
        if original_path is None:
            kopia = con.execute("SELECT 1 FROM location WHERE frame_id = ? AND present = 1",
                                (original_frame_id,)).fetchone()
        else:
            kopia = con.execute("SELECT 1 FROM location WHERE frame_id = ? AND present = 1 "
                                "AND path = ? COLLATE NOCASE",
                                (original_frame_id, original_path)).fetchone()
        if kopia is None:
            raise ValueError(f"oryginał {original_frame_id} bez obecnej kopii "
                             f"{original_path or ''}".rstrip())
        inny = con.execute("SELECT variant_frame_id FROM stack_variant WHERE original_frame_id = ? "
                           "AND variant = ? AND variant_frame_id <> ?",
                           (original_frame_id, variant, variant_frame_id)).fetchone()
        if inny is not None:
            raise ValueError(f"oryginał {original_frame_id} ma już wariant {variant} "
                             f"(klatka {inny['variant_frame_id']})")
        if con.execute("SELECT 1 FROM stack_variant WHERE variant_frame_id = ?",
                       (original_frame_id,)).fetchone() is not None:
            raise ValueError(f"oryginał {original_frame_id} jest już wariantem innego stosu")
        if con.execute("SELECT 1 FROM stack_variant WHERE original_frame_id = ?",
                       (variant_frame_id,)).fetchone() is not None:
            raise ValueError(f"wariant {variant_frame_id} jest już oryginałem innego wariantu")
        row = con.execute(
            "SELECT original_frame_id, variant, source FROM stack_variant WHERE variant_frame_id = ?",
            (variant_frame_id,)).fetchone()
        przed = dict(row) if row is not None else None
        po = {"original_frame_id": original_frame_id, "variant": variant, "source": source}
        if przed == po:
            return False
        if przed is not None and RANGA_WARIANTU[przed["source"]] > RANGA_WARIANTU[source]:
            return False
        con.execute(
            "INSERT INTO stack_variant(variant_frame_id, original_frame_id, variant, source, "
            "linked_at) VALUES (?, ?, ?, ?, ?) ON CONFLICT(variant_frame_id) DO UPDATE SET "
            "original_frame_id = excluded.original_frame_id, variant = excluded.variant, "
            "source = excluded.source, linked_at = excluded.linked_at",
            (variant_frame_id, original_frame_id, variant, source, now))
        emit_event(con, actor=actor, verb="stack_variant.linked",
                   target=f"frame:{variant_frame_id}", now=now,
                   payload={**po, "before": przed})
    return True


def record_variant_testimony(con, *, path, fingerprint, payload, now, actor="stack_variants"):
    """Wpisz zeznanie pary do kolejki konsumenta (`stack_variant_testimony`, 0035) - True, gdy wiersz
    drgnął. Ten sam odcisk → `False` bez eventu (powtórny skan, powtórne `apply`). Nowy odcisk pod tą
    samą ścieżką (zeznanie przepisane mocniejszym świadkiem) zastępuje treść i ZERUJE rozstrzygnięcie,
    więc konsument przeczyta je jeszcze raz. Event `stack_variant.testimony` niesie odcisk przed i po.
    `payload` to tekst JSON zeznania (konsument nie wraca do pliku na udziale)."""
    if not path or not fingerprint:
        raise ValueError("zeznanie wariantu bez ścieżki albo odcisku")
    with _immediate(con):
        row = con.execute("SELECT fingerprint FROM stack_variant_testimony WHERE path = ?",
                          (path,)).fetchone()
        if row is not None and row["fingerprint"] == fingerprint:
            return False
        con.execute(
            "INSERT INTO stack_variant_testimony(path, fingerprint, payload, recorded_at) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(path) DO UPDATE SET fingerprint = excluded.fingerprint, "
            "payload = excluded.payload, recorded_at = excluded.recorded_at, "
            "consumed_fingerprint = NULL, consumed_at = NULL, outcome = NULL",
            (path, fingerprint, payload, now))
        emit_event(con, actor=actor, verb="stack_variant.testimony", target=f"path:{path}", now=now,
                   payload={"fingerprint": fingerprint,
                            "before": row["fingerprint"] if row is not None else None})
    return True


def settle_variant_testimony(con, *, path, fingerprint, outcome, now, actor="stack_variants"):
    """Zapisz rozstrzygnięcie konsumenta dla zeznania o odcisku `fingerprint` - CAS: zeznanie
    przepisane w międzyczasie (inny odcisk) zostaje nierozstrzygnięte i wróci w następnym przebiegu.
    Zwraca True, gdy wiersz drgnął; event `stack_variant.testimony_settled` z wynikiem."""
    with _immediate(con):
        row = con.execute("SELECT fingerprint, consumed_fingerprint, outcome "
                          "FROM stack_variant_testimony WHERE path = ?", (path,)).fetchone()
        if row is None or row["fingerprint"] != fingerprint:
            return False
        if row["consumed_fingerprint"] == fingerprint and row["outcome"] == outcome:
            return False
        con.execute("UPDATE stack_variant_testimony SET consumed_fingerprint = ?, consumed_at = ?, "
                    "outcome = ? WHERE path = ?", (fingerprint, now, outcome, path))
        emit_event(con, actor=actor, verb="stack_variant.testimony_settled", target=f"path:{path}",
                   now=now, payload={"fingerprint": fingerprint, "outcome": outcome})
    return True


def clear_twin_object(con, *, frame_id, now, actor="resolver"):
    """Odepnij obiekt przejęty od oryginału (`object_source='twin'`), gdy oryginał obiektu już nie ma
    - True, gdy wiersz drgnął. Klinga zdejmuje WYŁĄCZNIE fakt automatu: klatka z innym źródłem
    (ręka, nagrobek, nagłówek, region) zostaje nietknięta (`False`). Event `object.unassigned` ze
    stanem sprzed (parytet `assigned − unassigned` jak w `assign_object`)."""
    with _immediate(con):
        row = con.execute("SELECT object_id, object_source FROM frame WHERE id = ?",
                          (frame_id,)).fetchone()
        if row is None or row["object_source"] != "twin" or row["object_id"] is None:
            return False
        con.execute("UPDATE frame SET object_id = NULL, object_source = NULL WHERE id = ?",
                    (frame_id,))
        emit_event(con, actor=actor, verb="object.unassigned", target=f"frame:{frame_id}", now=now,
                   payload={"object_id": row["object_id"], "object_source": "twin"},
                   reason="oryginał wariantu nie ma już obiektu")
    return True


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


def set_telescope_park(con, *, telescope_id, in_park, now, uid="local", via=None):
    """Wstaw/wyjmij teleskop z PARKU AKTUALNEGO (`telescope.in_park`) — akcja usera (D-T3-d).

    `in_park`: 1 = w parku · 0 = jawnie historyczny · `None` = cofnięcie do „nic nie powiedziano".
    Trójstan jest niesiony do końca, bo `NULL` i `0` znaczą co innego (baza świeża vs park
    przejrzany). GUARD: tylko KANONICZNY teleskop (`merged_into IS NULL`) — park wskazujący wiersz
    scalony w inny opisywałby oś, której już nie ma (lustro `approve_telescope`). Idempotentny:
    ta sama wartość → `False` bez eventu.

    `via` (AR-128) = skąd przyszła decyzja, gdy nie z osi parku - okno „Dopisz nowy…" zapisuje
    `add:<teleskop źródłowy>`; trafia do payloadu, jak `via: merge:<id>` przy scaleniu."""
    in_park = valid_telescope_park(in_park)
    with _immediate(con):
        row = con.execute(
            "SELECT telescop_canon, in_park, merged_into, retired_at FROM telescope WHERE id = ?",
            (telescope_id,)).fetchone()
        if row is None:
            raise ValueError(f"telescope:{telescope_id} nie istnieje")
        if row["retired_at"] is not None:
            raise ValueError(f"telescope:{telescope_id} to nagrobek - park go nie dotyczy")
        if row["merged_into"] is not None:
            raise ValueError(f"telescope:{telescope_id} jest scalony (merged_into="
                             f"{row['merged_into']}) — park tylko dla kanonicznego")
        if row["in_park"] == in_park:
            return False
        con.execute("UPDATE telescope SET in_park = ? WHERE id = ?", (in_park, telescope_id))
        emit_event(con, actor=f"user:{uid}", verb="telescope.parked",
                   target=f"telescope:{telescope_id}", now=now,
                   payload={"telescope": row["telescop_canon"],
                            "before": row["in_park"], "after": in_park,
                            **({"via": via} if via is not None else {})})
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


# ═══════════════════════════════════════════════ 1.10 uwagi klatki (0032, WO-2)
# Jedna krótka notatka człowieka na klatkę („chmury po drugiej”, „zmieniony flat”). Żyje wyłącznie
# w bazie (powód w 0032) i pisze ją wyłącznie ręka - automatu uwag nie ma, więc zdjęcie uwagi
# kasuje wiersz bez nagrobka (precedens `clear_target_plan`), a historię niesie dziennik:
# `note.set` z `{before, after}` i `note.cleared` z `{before}`.

# Najdłuższa uwaga w znakach PO normalizacji. Limit jest decyzją, nie pomiarem (przed 0032 uwag nie
# było czym zmierzyć): uwaga ma się zmieścić w komórce gridu z podpowiedzią i w jednym zdaniu
# o nocy - dłuższy opis należy do dziennika obserwacji, nie do klatki.
NOTE_MAX = 300


def normalize_note(body):
    """Treść uwagi w postaci, którą zapisuje klinga: białe znaki (także nowe linie) zwinięte do
    jednej spacji, bez spacji na brzegach; `None` → pusty napis. JEDNO źródło tej reguły - okno
    uwag liczy nią pustość pola i zgodność z bieżącą uwagą, więc wygaszone „Zapisz” i odmowa
    klingi nie mogą się rozjechać."""
    return " ".join((body or "").split())


@dataclass(frozen=True)
class NoteGesture:
    """Wynik gestu uwag. `changed` = klatki, których uwaga realnie drgnęła (każda ma swój event),
    `unchanged` = klatki zastane w stanie docelowym (idempotencja, bez eventu).

    `before` = uwaga SPRZED gestu dla KAŻDEJ zmienionej klatki (`None` = klatka uwagi nie miała).
    To jest droga powrotu, nie raport: podane do `restore_frame_notes` oddaje stan bajt w bajt,
    także zaznaczeniu mieszanemu (część klatek z uwagą, część bez). Klatek niezmienionych tu nie
    ma - cofnięcie nie ma im czego oddawać."""
    changed: tuple[int, ...]
    unchanged: tuple[int, ...]
    before: dict[int, str | None]


def _note_gesture(con, cel, *, now, actor, reason=None, expected=None):
    """Doprowadź uwagi klatek do stanu `cel` (`{frame_id: treść | None}`) - wspólne ostrze trzech
    gestów. Wołane WEWNĄTRZ transakcji wołającego: stan czytany pod tym samym lockiem, pod którym
    pada zapis (TOCTOU), i jeden `now` na cały gest - wspólny `ts` eventów JEST tożsamością gestu
    w dzienniku (ostatni gest ręki czyta się po `ts`).

    Klatka spoza bazy to błąd wołającego (EXPECT) i pada PRZED pierwszym zapisem: cel gestu to
    zaznaczenie z widoku, więc brak klatki znaczy rozjazd widoku z bazą, a nie stan, o którym gest
    miałby cicho zameldować pominięciem.

    `expected` (`{frame_id: treść | None}`) = GUARD DRYFU pod tym samym lockiem: klatka, której
    bieżąca uwaga nie jest tą oczekiwaną, zostaje `unchanged` bez eventu - zapis z drugiego
    połączenia między odczytem wołającego a tą transakcją jest cudzą, nowszą decyzją."""
    ids = sorted(cel)
    stan = {int(r[0]): r[1] for r in con.execute(
        "SELECT f.id, n.body FROM frame f LEFT JOIN frame_note n ON n.frame_id = f.id "
        "WHERE f.id IN (SELECT value FROM json_each(?))", (json.dumps(ids),))}
    brak = [fid for fid in ids if fid not in stan]
    if brak:
        raise ValueError(f"uwagi: klatek nie ma w bazie: {brak[:10]}")
    zmienione, bez_zmian, przed = [], [], {}
    for fid in ids:
        byla, ma_byc = stan[fid], cel[fid]
        if byla == ma_byc or (expected is not None and byla != expected[fid]):
            bez_zmian.append(fid)
            continue
        if ma_byc is None:
            con.execute("DELETE FROM frame_note WHERE frame_id = ?", (fid,))
            emit_event(con, actor=actor, verb="note.cleared", target=f"frame:{fid}", now=now,
                       payload={"before": byla}, reason=reason)
        else:
            con.execute(
                "INSERT INTO frame_note(frame_id, body, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(frame_id) DO UPDATE SET body = excluded.body, "
                "updated_at = excluded.updated_at", (fid, ma_byc, now))
            emit_event(con, actor=actor, verb="note.set", target=f"frame:{fid}", now=now,
                       payload={"before": byla, "after": ma_byc}, reason=reason)
        zmienione.append(fid)
        przed[fid] = byla
    return NoteGesture(changed=tuple(zmienione), unchanged=tuple(bez_zmian), before=przed)


def set_frame_note(con, *, frame_ids, body, now, uid="local"):
    """USTAW UWAGĘ - ta sama treść na każdej z `frame_ids` (gest na zaznaczeniu). `NoteGesture`.

    Treść przechodzi przez `normalize_note`. Pusta po normalizacji → `ValueError`: zdjęcie uwagi
    jest osobnym gestem (`clear_frame_note`), a pusty zapis udający kasację rozmyłby w dzienniku
    dwa różne zdania człowieka. Dłuższa niż `NOTE_MAX` → `ValueError`. Klatka z identyczną treścią
    → `unchanged` bez eventu (przeklikanie okna nie ma prawa puchnąć dziennika). Zapis to UPSERT,
    a `note.set` niesie `before` także przy nadpisaniu, bo po nim tekstu nie ma skąd wziąć."""
    tekst = normalize_note(body)
    if not tekst:
        raise ValueError("uwaga pusta po normalizacji - do zdjęcia uwagi służy clear_frame_note")
    if len(tekst) > NOTE_MAX:
        raise ValueError(f"uwaga ma {len(tekst)} znaków, limit to {NOTE_MAX}")
    with _immediate(con):
        g = _note_gesture(con, {int(i): tekst for i in frame_ids}, now=now, actor=f"user:{uid}")
    return g


def clear_frame_note(con, *, frame_ids, now, uid="local"):
    """ZDEJMIJ UWAGĘ z każdej z `frame_ids` - kasuje wiersz, `note.cleared` niesie CAŁĄ treść sprzed
    kasacji (odtworzenie jest odczytem dziennika, nie archeologią). Klatka bez uwagi → `unchanged`
    bez eventu. `NoteGesture`."""
    with _immediate(con):
        g = _note_gesture(con, {int(i): None for i in frame_ids}, now=now, actor=f"user:{uid}")
    return g


def restore_frame_notes(con, *, before, expected=None, now, uid="local"):
    """COFNIJ GEST UWAG: doprowadź każdą klatkę z `before` (`NoteGesture.before`) DOKŁADNIE do
    zapisanego tam stanu - `None` zdejmuje uwagę, tekst ją ustawia. Te same czasowniki co gest
    w przód, z `reason="cofnięcie"`: parytet `frame_note` czyta ostatni event uwag klatki, więc
    cofnięcie bilansuje się jak każdy inny zapis, a dziennik mówi, że to nie była nowa decyzja.

    TEKST WRACA BEZ PONOWNEJ NORMALIZACJI i bez limitu: pochodzi z bazy (klinga znormalizowała go
    przy zapisie), a cofnięcie ma oddać bajty, nie ich poprawioną wersję. Pusty albo nie-tekst to
    błąd wołającego (EXPECT) - `ValueError` przed zapisem, zamiast wywrotki na `CHECK` w połowie
    gestu. Klatka już w stanie z `before` → `unchanged` bez eventu, więc drugi klik nic nie pisze.
    Wynik niesie własne `before`, czyli drogę z powrotem do stanu sprzed cofnięcia.

    `expected` (`{frame_id: treść | None}` - stan, który zostawił cofany gest) zamyka okno między
    odczytem wołającego a zapisem: klatka, której uwagę pod `BEGIN IMMEDIATE` zastajemy INNĄ niż
    oczekiwana, zostaje `unchanged` bez eventu (wzór `expected_*` w `user_assign_object`) - inaczej
    cofnięcie nadpisałoby stanem sprzed gestu zapis z drugiego połączenia, którego cofany gest nie
    zrobił. Podane `expected` musi pokrywać każdą klatkę z `before` (EXPECT): klatka bez warunku
    w gescie z warunkami to luka w guardzie, nie świadomy wybór."""
    cel = {}
    for fid, tekst in before.items():
        if tekst is not None and (not isinstance(tekst, str) or not tekst.strip()):
            raise ValueError(f"uwagi: frame:{fid} - stan do przywrócenia {tekst!r} nie jest uwagą")
        cel[int(fid)] = tekst
    oczekiwane = None
    if expected is not None:
        oczekiwane = {int(fid): tekst for fid, tekst in expected.items()}
        brak = sorted(set(cel) - set(oczekiwane))
        if brak:
            raise ValueError(f"uwagi: cofnięcie bez stanu oczekiwanego dla klatek {brak[:10]}")
    with _immediate(con):
        g = _note_gesture(con, cel, now=now, actor=f"user:{uid}", reason="cofnięcie",
                          expected=oczekiwane)
    return g
