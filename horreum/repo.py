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
                 now, actor="scan"):
    """Wyłoń frame po `sha1_data` (tożsamość = odcisk sekcji DANYCH — przeżywa edycję nagłówka/
    rename/move/writeback; brief §2). Istnieje → zwróć (id, False) BEZ zmiany tożsamości — drugie
    wystąpienie to nowa LOKALIZACJA (`add_location`), nie nowy frame. Nowy → INSERT frame +
    `event(frame.observed)` w tej samej transakcji; (id, True).

    `sha1_data_uncomputable=1` = degeneracja: odcisk danych nieobliczalny, `sha1_data` niesie
    sha1 CAŁEGO pliku (lekcja v3 dawcy) — legalne WYŁĄCZNIE dla ścieżki nieznanej (R3-b1).
    `camera_id` może być None (oś nierozstrzygnięta → `flag_camera_review` w warstwie skanu).
    Fakty kopii (rozmiar, hashe pliku) mieszkają na location, nie tu (R2#6)."""
    row = con.execute("SELECT id FROM frame WHERE sha1_data = ?", (sha1_data,)).fetchone()
    if row is not None:
        return row[0], False

    with con:  # atomowo: INSERT frame + INSERT event
        cur = con.execute(
            "INSERT INTO frame(sha1_data, sha1_data_uncomputable, kind, filetype, camera_id, "
            "first_seen_at) VALUES (?, ?, ?, ?, ?, ?)",
            (sha1_data, sha1_data_uncomputable, kind, filetype, camera_id, now),
        )
        frame_id = cur.lastrowid
        emit_event(
            con, actor=actor, verb="frame.observed", target=f"frame:{frame_id}", now=now,
            payload={"sha1_data": sha1_data, "uncomputable": sha1_data_uncomputable,
                     "kind": kind, "filetype": filetype, "camera_id": camera_id},
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


# Kolumny-fakty kopii na location — wspólna lista dla diffu w `refresh_location`.
_LOCATION_FACTS = ("mtime", "file_sha1", "header_hash", "hdu_index", "compressed", "size_bytes")


def rebind_location(con, *, location_id, frame_after, now, actor="scan"):
    """PODMIANA TREŚCI pod znaną ścieżką (R3-b1): przepnij `location.frame_id` na nową tożsamość
    + `event(location.rebound)` `{frame_before, frame_after}`. Stary frame ZOSTAJE (append-only,
    historia w eventach) — bez lokacji podchwyci go przyszły pass zniknięć. Już przepięta → False
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


def refresh_location(con, *, location_id, frame_id, mtime, file_sha1, header_hash,
                     hdu_index, compressed, size_bytes, now, actor="scan",
                     raw_json=None, cards=None, hot_fields=None, camera_id=None, kind=None):
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

    `hot_fields` = dict kolumn `header` (jak `extract_header`); `camera_id`/`kind` = pochodne
    POLICZONE przez wołającego z nowego dictu (emergencja kamery = osobny, idempotentny
    `upsert_camera` przed wołaniem). Zwraca dict
    `{"facts": bool, "header": bool, "rederived": bool}`. Wymiana `cards` (DELETE+INSERT) to
    jedyna sankcjonowana kasacja: cards są LUSTREM bieżącego zeznania, nie historią —
    historia mieszka w `event`."""
    after = {"mtime": mtime, "file_sha1": file_sha1, "header_hash": header_hash,
             "hdu_index": hdu_index, "compressed": compressed, "size_bytes": size_bytes}
    result = {"facts": False, "header": False, "rederived": False}
    with _immediate(con):
        row = con.execute(
            "SELECT mtime, file_sha1, header_hash, hdu_index, compressed, size_bytes "
            "FROM location WHERE id = ?", (location_id,)).fetchone()
        if row is None:
            raise ValueError(f"location:{location_id} nie istnieje")
        changed = {k: {"before": row[k], "after": after[k]}
                   for k in _LOCATION_FACTS if row[k] != after[k]}
        if not changed:
            return result
        con.execute(
            "UPDATE location SET mtime = ?, file_sha1 = ?, header_hash = ?, hdu_index = ?, "
            "compressed = ?, size_bytes = ?, last_verified_at = ? WHERE id = ?",
            (mtime, file_sha1, header_hash, hdu_index, compressed, size_bytes, now, location_id))
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


def refresh_location_unreadable(con, *, location_id, sha1_data, path, mtime, reason,
                                now, actor="scan"):
    """Znana ścieżka, plik NIECZYTELNY, bajty NIEZMIENIONE (R3-b1): tylko refresh mtime +
    `event(frame.review, „kopia nieczytelna")` — ZERO nowych frame'ów (transient NAS; degeneracja
    tożsamości legalna wyłącznie dla ścieżki NIEZNANEJ). Target `sha1:` po tożsamości frame'a
    lokacji (kotwica joinowalna)."""
    with _immediate(con):
        row = con.execute("SELECT mtime FROM location WHERE id = ?", (location_id,)).fetchone()
        if row is None:
            raise ValueError(f"location:{location_id} nie istnieje")
        if row["mtime"] != mtime:
            con.execute("UPDATE location SET mtime = ?, last_verified_at = ? WHERE id = ?",
                        (mtime, now, location_id))
        emit_event(con, actor=actor, verb="frame.review", target=f"sha1:{sha1_data}", now=now,
                   reason=f"kopia nieczytelna: {reason}", payload={"path": path})


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


def assign_config(con, *, frame_id, config_id, now, actor="grouper"):
    """Przypisz config do frame'a (`frame.config_id`). INWARIANT (DDL §1): `config.camera_id` musi
    == `frame.camera_id` — gwarantuje grouper (config budowany z kamery tego frame'a). Idempotentny:
    już przypisany ten sam config → False bez eventu; inaczej UPDATE + `event(config.assigned)`."""
    row = con.execute("SELECT config_id FROM frame WHERE id = ?", (frame_id,)).fetchone()
    if row is not None and row[0] == config_id:
        return False

    with con:
        con.execute("UPDATE frame SET config_id = ? WHERE id = ?", (config_id, frame_id))
        emit_event(con, actor=actor, verb="config.assigned", target=f"frame:{frame_id}", now=now,
                   payload={"config_id": config_id})
    return True


def flag_config_review(con, *, frame_id, reason, now, actor="grouper"):
    """`frame.config_id` nierozstrzygalny (brak teleskopu/kamery/focratio — np. master bez FOCRATIO,
    W4) → `event(config.review)`. config_id zostaje NULL; ZERO cichego NULL (każdy ma powód)."""
    with con:
        emit_event(con, actor=actor, verb="config.review", target=f"frame:{frame_id}", now=now,
                   reason=reason)


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
    `event(object.aliased)`; (id, True). `source` ∈ {header|catalog_xref|common_name|user}."""
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
    już ustawiona → False bez eventu; inaczej UPDATE + `event(object.assigned)`; True."""
    row = con.execute(
        "SELECT object_id, object_source FROM frame WHERE id = ?", (frame_id,)).fetchone()
    if row is not None and row[0] == object_id and row[1] == object_source:
        return False

    with con:
        con.execute("UPDATE frame SET object_id = ?, object_source = ? WHERE id = ?",
                    (object_id, object_source, frame_id))
        emit_event(con, actor=actor, verb="object.assigned", target=f"frame:{frame_id}", now=now,
                   payload={"object_id": object_id, "object_source": object_source})
    return True


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
    """Backfill kolumny POCHODNEJ `frame.filter_canon` ZBIORCZO (jak `backfill_focratio_norm`):
    jedna transakcja + JEDEN event `filter.backfilled`. `items` = lista `(frame_id, filter_canon)`
    (tylko frame'y z niepustym kanonem; brak filtra zostaje NULL — W2, bez review). Pusta → no-op."""
    items = list(items)
    if not items:
        return
    with con:
        for frame_id, filter_canon in items:
            con.execute("UPDATE frame SET filter_canon = ? WHERE id = ?", (filter_canon, frame_id))
        emit_event(con, actor=actor, verb="filter.backfilled", target="frame:*", now=now,
                   payload={"count": len(items)})


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
    (idempotencja). Inaczej UPDATE + `event(telescope.merged)`."""
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
        con.execute("UPDATE telescope SET merged_into = ? WHERE id = ?", (target_id, source_id))
        emit_event(con, actor=f"user:{uid}", verb="telescope.merged",
                   target=f"telescope:{source_id}", now=now,
                   payload={"source": source_id, "target": target_id})
    return True


def unmerge_telescope(con, *, telescope_id, now, uid="local"):
    """Cofnij scalenie (`merged_into → NULL`) — append-only (nowy event, nie kasacja). Już kanoniczny
    (`merged_into IS NULL`) → `False`. Inaczej UPDATE + `event(telescope.unmerged)` z `{before, after}`
    (`former_target`→None). Dzięki inwariantowi głębokość ≤ 1 wiersz zawsze jest liściem — un-merge
    nie ma „środka łańcucha" do rozplątania."""
    with _immediate(con):
        _, _, merged_into = _telescope_row(con, telescope_id)
        if merged_into is None:
            return False
        con.execute("UPDATE telescope SET merged_into = NULL WHERE id = ?", (telescope_id,))
        emit_event(con, actor=f"user:{uid}", verb="telescope.unmerged",
                   target=f"telescope:{telescope_id}", now=now,
                   payload={"before": merged_into, "after": None})
    return True
