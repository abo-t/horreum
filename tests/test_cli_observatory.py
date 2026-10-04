"""CLI `horreum observatory assign|clear` - stanowisko z ręki (0027): DRY domyślnie (zero zapisu),
`--apply` zapisuje klingą, wybór klatek obowiązkowy (`--frames`/`--path-like`/`--filter-json`,
część wspólna), recepta odwrotu w raporcie. Współrzędne SYNTETYCZNE (repo publiczne)."""
from horreum import cli, db, repo

NOW = "2026-10-04T12:00:00+00:00"


def _seed(tmp_path):
    """Trzy klatki RAW bez GPS: dwie w folderze `LMC`, jedna obok - selektor ścieżki ma je rozdzielić."""
    dbp = tmp_path / "cli.db"
    con = db.open_db(str(dbp))
    ids = []
    for i, folder in enumerate(["LMC", "LMC", "M42"]):
        fid, _ = repo.upsert_frame(con, sha1_data=f"r{i}", kind="light", filetype="raw",
                                   camera_id=None, now=NOW)
        repo.add_location(con, frame_id=fid, volume="V", path=f"X:\\ASTRO\\{folder}\\r{i}.dng",
                          now=NOW)
        ids.append(fid)
    con.close()
    return dbp, ids


def _stan(dbp):
    con = db.open_db(str(dbp))
    out = [tuple(r) for r in con.execute(
        "SELECT observatory_id, observatory_source FROM frame ORDER BY id").fetchall()]
    con.close()
    return out


def test_dry_domyslnie_nic_nie_zapisuje(tmp_path, capsys):
    dbp, _ = _seed(tmp_path)
    rc = cli.main(["observatory", "assign", str(dbp), "--path-like", "%\\LMC\\%",
                   "--lat", "-30.25", "--lon", "170.7", "--name", "Wyjazd"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "DRY" in out and "przypisane (byloby): 2" in out and "NOWE" in out
    assert _stan(dbp) == [(None, None)] * 3


def test_apply_przypisuje_wybrane_i_daje_recepte_odwrotu(tmp_path, capsys):
    dbp, ids = _seed(tmp_path)
    rc = cli.main(["observatory", "assign", str(dbp), "--path-like", "%\\LMC\\%",
                   "--lat", "-30.25", "--lon", "170.7", "--apply"])
    out = capsys.readouterr().out
    assert rc == 0
    stan = _stan(dbp)
    assert stan[0][1] == stan[1][1] == "user" and stan[2] == (None, None)
    recepta = next(l for l in out.splitlines() if "cofniecie:" in l).split("cofniecie: ")[1]
    assert recepta.startswith("horreum observatory clear")
    # recepta wykonana dosłownie (bez nazwy programu) odwraca gest
    import shlex
    argv = shlex.split(recepta, posix=False)[1:]
    argv = [a.strip('"') for a in argv]
    assert cli.main(argv) == 0
    assert _stan(dbp) == [(None, None)] * 3


def test_wybor_obowiazkowy_i_czesc_wspolna(tmp_path, capsys):
    dbp, ids = _seed(tmp_path)
    assert cli.main(["observatory", "assign", str(dbp), "--lat", "1", "--lon", "2"]) == 2
    rc = cli.main(["observatory", "assign", str(dbp), "--path-like", "%\\LMC\\%",
                   "--frames", f"{ids[0]},{ids[2]}", "--lat", "-30.25", "--lon", "170.7",
                   "--apply"])
    assert rc == 0
    assert [s[1] for s in _stan(dbp)] == ["user", None, None]       # część wspólna, nie suma
    capsys.readouterr()


def test_bledne_wspolrzedne_kod_2_bez_zapisu(tmp_path, capsys):
    dbp, ids = _seed(tmp_path)
    rc = cli.main(["observatory", "assign", str(dbp), "--frames", str(ids[0]),
                   "--lat", "95", "--lon", "10", "--apply"])
    assert rc == 2
    assert "zakresem" in capsys.readouterr().out
    assert _stan(dbp) == [(None, None)] * 3


def test_clear_dry_i_klatka_z_gps_zostaje(tmp_path, capsys):
    dbp, ids = _seed(tmp_path)
    con = db.open_db(str(dbp))
    oid, _ = repo.propose_observatory(con, lat=53.4, lon=114.4, now=NOW)
    repo.assign_observatory(con, frame_id=ids[2], observatory_id=oid, now=NOW)   # „z GPS"
    repo.user_assign_observatory(con, frame_ids=ids[:2], observatory_id=oid, now=NOW)
    con.close()
    rc = cli.main(["observatory", "clear", str(dbp), "--frames", ",".join(map(str, ids))])
    out = capsys.readouterr().out
    assert rc == 0 and "cofniete (byloby): 2" in out and "nie reka): 1" in out
    assert [s[1] for s in _stan(dbp)] == ["user", "user", None]
    assert cli.main(["observatory", "clear", str(dbp), "--frames",
                     ",".join(map(str, ids)), "--apply"]) == 0
    assert _stan(dbp) == [(None, None), (None, None), (oid, None)]


def test_wysokosc_istniejacego_stanowiska_zostaje_i_raport_to_mowi(tmp_path, capsys):
    dbp, ids = _seed(tmp_path)
    con = db.open_db(str(dbp))
    repo.user_assign_observatory(con, frame_ids=[ids[0]], lat=-30.25, lon=170.7, elev=900, now=NOW)
    con.close()
    rc = cli.main(["observatory", "assign", str(dbp), "--frames", str(ids[1]), "--lat", "-30.25",
                   "--lon", "170.7", "--elev", "1200", "--apply"])
    out = capsys.readouterr().out
    assert rc == 0 and "istniejace" in out
    assert "ma juz wysokosc 900 m - zostaje (podana 1200 m pominieta)" in out
