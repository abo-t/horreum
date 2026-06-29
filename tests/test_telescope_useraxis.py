"""Oś TELESKOP — zapis usera (GUI etap 1, PLAN_gui §7). Jedna klinga z actor=user:<uid>,
inwariant głębokość scalania ≤ 1, semantyka False=idempotencja / ValueError=błąd wołania,
widok telescope_canonical (R2 brak sieroty, R3 liczność po scaleniu)."""
import json

import pytest

from horreum import db, repo

NOW = "2026-06-29T12:00:00"


def _fresh(tmp_path):
    return db.open_db(str(tmp_path / "h.db"))


def _tel(con, f_ratio, focal):
    tid, _ = repo.propose_telescope(con, f_ratio_nominal=f_ratio, focal_nominal=focal, now=NOW)
    return tid


def _events(con, verb=None):
    if verb is None:
        return con.execute("SELECT count(*) FROM event").fetchone()[0]
    return con.execute("SELECT count(*) FROM event WHERE verb=?", (verb,)).fetchone()[0]


# --- label (§7.3) ---

def test_label_nadaje_i_emituje_before_after(tmp_path):
    con = _fresh(tmp_path)
    t = _tel(con, 5.6, 784)
    assert repo.label_telescope(con, telescope_id=t, label="A140R", now=NOW) is True
    assert con.execute("SELECT label FROM telescope WHERE id=?", (t,)).fetchone()["label"] == "A140R"
    ev = con.execute("SELECT actor, target, payload FROM event WHERE verb='telescope.labeled'").fetchone()
    assert ev["actor"] == "user:local" and ev["target"] == f"telescope:{t}"
    assert json.loads(ev["payload"]) == {"before": None, "after": "A140R"}
    con.close()


def test_label_idempotentny_bez_eventu(tmp_path):
    con = _fresh(tmp_path)
    t = _tel(con, 5.6, 784)
    assert repo.label_telescope(con, telescope_id=t, label="A140R", now=NOW) is True
    assert repo.label_telescope(con, telescope_id=t, label="A140R", now=NOW) is False
    assert repo.label_telescope(con, telescope_id=t, label="  A140R  ", now=NOW) is False  # po strip
    assert _events(con, "telescope.labeled") == 1
    con.close()


def test_label_pusty_lub_none_to_ValueError(tmp_path):
    con = _fresh(tmp_path)
    t = _tel(con, 5.6, 784)
    for bad in (None, "", "   "):
        with pytest.raises(ValueError):
            repo.label_telescope(con, telescope_id=t, label=bad, now=NOW)
    assert _events(con, "telescope.labeled") == 0
    con.close()


def test_label_uid_sklada_user_prefix(tmp_path):
    con = _fresh(tmp_path)
    t = _tel(con, 5.6, 784)
    repo.label_telescope(con, telescope_id=t, label="RC8", now=NOW, uid="zdzin")
    actor = con.execute("SELECT actor FROM event WHERE verb='telescope.labeled'").fetchone()["actor"]
    assert actor == "user:zdzin"
    con.close()


# --- approve (§7.3) ---

def test_approve_proposed_to_approved_i_event(tmp_path):
    con = _fresh(tmp_path)
    t = _tel(con, 8.0, 1624)
    assert repo.approve_telescope(con, telescope_id=t, now=NOW) is True
    assert con.execute("SELECT status FROM telescope WHERE id=?", (t,)).fetchone()["status"] == "approved"
    assert repo.approve_telescope(con, telescope_id=t, now=NOW) is False           # idempotent
    ev = con.execute("SELECT payload FROM event WHERE verb='telescope.approved'").fetchone()
    assert json.loads(ev["payload"]) == {"before": "proposed", "after": "approved"}
    assert _events(con, "telescope.approved") == 1
    con.close()


def test_approve_scalonego_to_ValueError_stan_bez_zmiany(tmp_path):
    con = _fresh(tmp_path)
    a, b = _tel(con, 5.6, 784), _tel(con, 5.6, 794)
    repo.merge_telescope(con, source_id=a, target_id=b, now=NOW)
    with pytest.raises(ValueError):
        repo.approve_telescope(con, telescope_id=a, now=NOW)
    assert con.execute("SELECT status FROM telescope WHERE id=?", (a,)).fetchone()["status"] == "proposed"
    assert _events(con, "telescope.approved") == 0
    con.close()


# --- merge / unmerge + inwariant głębokość ≤ 1 (§7.3, §7.4) ---

def test_merge_legalny_ustawia_merged_into_i_event(tmp_path):
    con = _fresh(tmp_path)
    a, b = _tel(con, 5.6, 784), _tel(con, 5.6, 794)
    assert repo.merge_telescope(con, source_id=a, target_id=b, now=NOW) is True
    assert con.execute("SELECT merged_into FROM telescope WHERE id=?", (a,)).fetchone()["merged_into"] == b
    assert repo.merge_telescope(con, source_id=a, target_id=b, now=NOW) is False    # idempotent
    ev = con.execute("SELECT target, payload FROM event WHERE verb='telescope.merged'").fetchone()
    assert ev["target"] == f"telescope:{a}" and json.loads(ev["payload"]) == {"source": a, "target": b}
    assert _events(con, "telescope.merged") == 1
    con.close()


def test_merge_self_to_ValueError(tmp_path):
    con = _fresh(tmp_path)
    a = _tel(con, 5.6, 784)
    with pytest.raises(ValueError):
        repo.merge_telescope(con, source_id=a, target_id=a, now=NOW)
    con.close()


def test_merge_target_nie_kanoniczny_to_ValueError(tmp_path):
    """target już scalony (merged_into≠NULL) → scalać wolno tylko w korzeń."""
    con = _fresh(tmp_path)
    a, b, c = _tel(con, 5.6, 784), _tel(con, 5.6, 794), _tel(con, 8.0, 1624)
    repo.merge_telescope(con, source_id=b, target_id=c, now=NOW)                    # b scalony w c
    with pytest.raises(ValueError):
        repo.merge_telescope(con, source_id=a, target_id=b, now=NOW)                # b nie jest korzeniem
    con.close()


def test_merge_source_z_czlonkami_to_ValueError(tmp_path):
    """source ma członka → łańcuch głębokości 2 niedozwolony (inwariant ≤ 1). Klasyczny anty-cykl:
    a→b, potem próba b→a blokowana, bo b ma członka a."""
    con = _fresh(tmp_path)
    a, b = _tel(con, 5.6, 784), _tel(con, 5.6, 794)
    repo.merge_telescope(con, source_id=a, target_id=b, now=NOW)                    # b ma członka a
    with pytest.raises(ValueError):
        repo.merge_telescope(con, source_id=b, target_id=a, now=NOW)                # cykl → blok
    assert _events(con, "telescope.merged") == 1
    con.close()


def test_multi_merge_A_C_B_C_legalny_glebokosc_1(tmp_path):
    con = _fresh(tmp_path)
    a, b, c = _tel(con, 5.6, 784), _tel(con, 5.6, 794), _tel(con, 5.6, 780)
    assert repo.merge_telescope(con, source_id=a, target_id=c, now=NOW) is True
    assert repo.merge_telescope(con, source_id=b, target_id=c, now=NOW) is True
    # wszyscy pod kanonem c, głębokość 1
    rows = dict(con.execute("SELECT id, canon_id FROM telescope_canonical").fetchall())
    assert rows == {a: c, b: c, c: c}
    con.close()


def test_unmerge_cofa_i_event(tmp_path):
    con = _fresh(tmp_path)
    a, b = _tel(con, 5.6, 784), _tel(con, 5.6, 794)
    repo.merge_telescope(con, source_id=a, target_id=b, now=NOW)
    assert repo.unmerge_telescope(con, telescope_id=a, now=NOW) is True
    assert con.execute("SELECT merged_into FROM telescope WHERE id=?", (a,)).fetchone()["merged_into"] is None
    assert repo.unmerge_telescope(con, telescope_id=a, now=NOW) is False            # już kanoniczny
    ev = con.execute("SELECT payload FROM event WHERE verb='telescope.unmerged'").fetchone()
    assert json.loads(ev["payload"]) == {"before": b, "after": None}
    assert _events(con, "telescope.unmerged") == 1
    con.close()


def test_canonical_brak_sieroty_po_serii_merge_unmerge(tmp_path):
    """R2: każdy wiersz ma canon_id w widoku; po unmerge wraca jako własny canon; żaden merged_into
    nie wskazuje na nie-korzeń (głębokość ≤ 1)."""
    con = _fresh(tmp_path)
    a, b, c = _tel(con, 5.6, 784), _tel(con, 5.6, 794), _tel(con, 5.6, 780)
    repo.merge_telescope(con, source_id=a, target_id=c, now=NOW)
    repo.merge_telescope(con, source_id=b, target_id=c, now=NOW)
    repo.unmerge_telescope(con, telescope_id=a, now=NOW)
    rows = dict(con.execute("SELECT id, canon_id FROM telescope_canonical").fetchall())
    assert rows == {a: a, b: c, c: c}                                              # a wrócił, brak sieroty
    assert con.execute("SELECT count(*) FROM telescope_canonical").fetchone()[0] == 3
    # żaden merged_into nie celuje w wiersz, który sam jest scalony (nie-korzeń)
    bad = con.execute("SELECT count(*) FROM telescope t JOIN telescope p ON t.merged_into = p.id "
                      "WHERE p.merged_into IS NOT NULL").fetchone()[0]
    assert bad == 0
    con.close()


def test_R3_licznik_klatek_po_scaleniu_kolizja_kamery_i_config_null(tmp_path):
    """R3: liczność po canon_id przez config→frame; kolizja kamery (2 configi tej samej kamery pod
    scalanymi teleskopami) sumuje się pod kanonem; frame z config_id NULL poza sumą; unmerge rozdziela."""
    con = _fresh(tmp_path)
    cam, _ = repo.upsert_camera(con, model_canon="ASI2600MM", pixel_um=3.76, is_mono=1,
                                is_mono_source="model", raw_instrume="x", now=NOW)
    a, b = _tel(con, 5.6, 784), _tel(con, 5.6, 794)
    cfg_a, _ = repo.propose_config(con, telescope_id=a, camera_id=cam, now=NOW)
    cfg_b, _ = repo.propose_config(con, telescope_id=b, camera_id=cam, now=NOW)   # ta sama kamera

    def _frame(sha, cfg):
        fid, _ = repo.upsert_frame(con, sha1=sha, kind="light", filetype="fits", size_bytes=1,
                                   camera_id=cam, now=NOW)
        if cfg is not None:
            repo.assign_config(con, frame_id=fid, config_id=cfg, now=NOW)
        return fid

    for s in ("a1", "a2"):
        _frame(s, cfg_a)                                  # 2 klatki pod A
    for s in ("b1", "b2", "b3"):
        _frame(s, cfg_b)                                  # 3 klatki pod B
    _frame("nullcfg", None)                               # 1 klatka bez configu (review) — poza sumą

    count_sql = ("SELECT tc.canon_id, COUNT(fr.id) n FROM telescope_canonical tc "
                 "JOIN config c ON c.telescope_id = tc.id "
                 "JOIN frame fr ON fr.config_id = c.id GROUP BY tc.canon_id")

    before = dict(con.execute(count_sql).fetchall())
    assert before == {a: 2, b: 3}                         # NULL-config nie liczony

    repo.merge_telescope(con, source_id=a, target_id=b, now=NOW)
    after = dict(con.execute(count_sql).fetchall())
    assert after == {b: 5}                                # suma pod kanonem b (kolizja kamery)

    repo.unmerge_telescope(con, telescope_id=a, now=NOW)
    assert dict(con.execute(count_sql).fetchall()) == {a: 2, b: 3}   # rozdzielenie po unmerge
    con.close()


def test_nieistniejacy_telescope_to_ValueError(tmp_path):
    con = _fresh(tmp_path)
    for call in (lambda: repo.label_telescope(con, telescope_id=999, label="X", now=NOW),
                 lambda: repo.approve_telescope(con, telescope_id=999, now=NOW),
                 lambda: repo.unmerge_telescope(con, telescope_id=999, now=NOW)):
        with pytest.raises(ValueError):
            call()
    con.close()
