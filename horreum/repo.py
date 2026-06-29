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
    """Wyłoń kamerę (oś) ze skanu. Tożsamość = (model_canon, pixel_um) — UNIQUE.

    Istnieje → zwróć (id, False), bez eventu (brak zmiany stanu). Nowa → INSERT + emisja
    `camera.upserted` W TEJ SAMEJ TRANSAKCJI; zwróć (id, True). Encje kamer wyłaniają się
    ze skanu (PLAN §3.6), nie są wymyślane a priori.
    """
    row = con.execute(
        "SELECT id FROM camera WHERE model_canon = ? AND pixel_um = ?",
        (model_canon, pixel_um),
    ).fetchone()
    if row is not None:
        return row[0], False

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


def upsert_frame(con, *, sha1, kind, filetype, size_bytes, camera_id, now, actor="scan"):
    """Wyłoń frame po `sha1` (tożsamość pliku, przeżywa rename/move). Istnieje → zwróć (id, False)
    BEZ zmiany tożsamości — drugie wystąpienie tego samego sha1 to nowa LOKALIZACJA (`add_location`),
    nie nowy frame. Nowy → INSERT frame + `event(frame.observed)` w tej samej transakcji; (id, True).
    `camera_id` może być None (oś nierozstrzygnięta → `flag_camera_review` w warstwie skanu)."""
    row = con.execute("SELECT id FROM frame WHERE sha1 = ?", (sha1,)).fetchone()
    if row is not None:
        return row[0], False

    with con:  # atomowo: INSERT frame + INSERT event
        cur = con.execute(
            "INSERT INTO frame(sha1, kind, filetype, size_bytes, camera_id, first_seen_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (sha1, kind, filetype, size_bytes, camera_id, now),
        )
        frame_id = cur.lastrowid
        emit_event(
            con, actor=actor, verb="frame.observed", target=f"frame:{frame_id}", now=now,
            payload={"sha1": sha1, "kind": kind, "filetype": filetype, "camera_id": camera_id},
        )
    return frame_id, True


def add_location(con, *, frame_id, volume, path, drive_letter=None, tier=None, mtime=None,
                 now, actor="scan"):
    """Dołóż lokalizację frame'a po `UNIQUE(volume, path)`. Już znana → (id, False) bez eventu
    (idempotencja skanu). Nowa → INSERT + `event(location.added)`; (id, True). `volume` = trwały
    identyfikator wolumenu; gdy niedostępny, woła się z placeholderem ('?') — NIE blokuje skanu
    (to nie tożsamość frame'a, §7.5). `drive_letter` to efemeryczny cache wyświetlania."""
    row = con.execute(
        "SELECT id FROM location WHERE volume = ? AND path = ?", (volume, path)).fetchone()
    if row is not None:
        return row[0], False

    with con:  # atomowo: INSERT location + INSERT event
        cur = con.execute(
            "INSERT INTO location(frame_id, volume, drive_letter, path, tier, mtime, "
            "last_verified_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (frame_id, volume, drive_letter, path, tier, mtime, now),
        )
        location_id = cur.lastrowid
        emit_event(
            con, actor=actor, verb="location.added", target=f"frame:{frame_id}", now=now,
            payload={"volume": volume, "path": path, "tier": tier},
        )
    return location_id, True


def record_header(con, *, frame_id, raw_json, now, actor="scan",
                  date_obs=None, exptime=None, filter_raw=None, instrume=None, telescop=None,
                  focallen=None, focratio_raw=None, focratio_norm=None, focratio_norm_src=None,
                  xpixsz=None, ypixsz=None, gain=None, offset_adu=None, ccd_temp=None,
                  usblimit=None, xbinning=None, ybinning=None, bayerpat=None,
                  ra_deg=None, dec_deg=None, object_raw=None):
    """Zapisz zeznanie nagłówka (1:1 z frame — `header.frame_id` PRIMARY KEY, więc RAZ na frame).
    `raw_json` = surowy nagłówek 1:1; pola gorące już zrzutowane na typy (`resolve.extract_header`,
    W2/W3). INSERT header + `event(header.recorded)` w tej samej transakcji. `focratio_norm`/`src`
    zwykle None tutaj — backfill grouper (§Etap 5)."""
    with con:  # atomowo: INSERT header + INSERT event
        con.execute(
            "INSERT INTO header(frame_id, raw_json, date_obs, exptime, filter_raw, instrume, "
            "telescop, focallen, focratio_raw, focratio_norm, focratio_norm_src, xpixsz, ypixsz, "
            "gain, offset_adu, ccd_temp, usblimit, xbinning, ybinning, bayerpat, ra_deg, dec_deg, "
            "object_raw) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (frame_id, raw_json, date_obs, exptime, filter_raw, instrume, telescop, focallen,
             focratio_raw, focratio_norm, focratio_norm_src, xpixsz, ypixsz, gain, offset_adu,
             ccd_temp, usblimit, xbinning, ybinning, bayerpat, ra_deg, dec_deg, object_raw),
        )
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


def backfill_focratio_norm(con, items, now, actor="grouper"):
    """Backfill kolumny POCHODNEJ `header.focratio_norm`/`_src` PO skanie (§Etap 5) — osobna faza
    UPDATE, NIE przez ścieżkę `record_header` (nie psuje zapisu skanu). `items` = lista
    `(frame_id, focratio_norm, focratio_norm_src)`. Jedna transakcja + JEDEN event zbiorczy
    `header.focratio_backfilled` (operacja masowa — bez zaśmiecania logu per-wiersz)."""
    with con:
        for frame_id, norm, src in items:
            con.execute(
                "UPDATE header SET focratio_norm = ?, focratio_norm_src = ? WHERE frame_id = ?",
                (norm, src, frame_id),
            )
        review = sum(1 for _, norm, _ in items if norm is None)
        emit_event(con, actor=actor, verb="header.focratio_backfilled", target="header:*", now=now,
                   payload={"count": len(items), "review": review})


def propose_telescope(con, *, f_ratio_nominal, focal_nominal, telescop_hint=None,
                      member_count=None, now, actor="grouper"):
    """Wyłoń teleskop (oś) z klastra sygnatur — `status='proposed'`, `label=NULL` (etykieta/scalanie
    = GUI usera, poza plastrem B). Idempotentny po centroidzie `(f_ratio_nominal, focal_nominal)`:
    istnieje → (id, False) bez eventu; nowy → INSERT + `event(telescope.proposed)`."""
    row = con.execute(
        "SELECT id FROM telescope WHERE f_ratio_nominal = ? AND focal_nominal = ?",
        (f_ratio_nominal, focal_nominal),
    ).fetchone()
    if row is not None:
        return row[0], False

    with con:
        cur = con.execute(
            "INSERT INTO telescope(label, f_ratio_nominal, focal_nominal, status, telescop_hint, "
            "created_at) VALUES (NULL, ?, ?, 'proposed', ?, ?)",
            (f_ratio_nominal, focal_nominal, telescop_hint, now),
        )
        telescope_id = cur.lastrowid
        emit_event(
            con, actor=actor, verb="telescope.proposed", target=f"telescope:{telescope_id}",
            now=now,
            payload={"f_ratio_nominal": f_ratio_nominal, "focal_nominal": focal_nominal,
                     "member_count": member_count},
        )
    return telescope_id, True


def flag_telescope_review(con, *, telescope_id, reason, now, actor="grouper"):
    """Klaster podejrzany (rozpiętość wewnętrzna > tolerancja — chaining single-linkage) →
    `event(telescope.review)`. Teleskop powstaje (proposed), lecz oznaczony do przejrzenia."""
    with con:
        emit_event(con, actor=actor, verb="telescope.review", target=f"telescope:{telescope_id}",
                   now=now, reason=reason)


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
