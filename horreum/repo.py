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
    """Sygnał review pliku, którego nagłówka NIE dało się odczytać (miękkie lądowanie W1): frame
    NIE powstaje (zbyt niepewny do wciągnięcia), lecz zeznanie o jego istnieniu (sha1 + ścieżka +
    powód) trafia do `event(frame.review)`. Wejście do przyszłego import-legacy/review."""
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
