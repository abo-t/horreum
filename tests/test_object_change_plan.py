r"""Plan gestu „Zmień obiekt…” i „Uzgodnij pliki…” (AR-17 krok 3, D-1011-5): read-model
(`queries.object_change_rows`, `object_target`, `location_lookup`, `file_object_mismatch_frame_ids`,
wspólna bramka karty `object_card_gate`) i czysty planer (`object_change.plan_object_change`).

Baza w pamięci, drzewo archiwum PRAWDZIWE w `tmp_path` (planer czyta dysk wyłącznie `isdir`/
`listdir`, a NTFS nie rozróżnia wielkości liter jak `R:`). Zero zapisu: test pilnuje i bazy,
i drzewa."""
import os

import pytest

from horreum import db, object_change, repo
from horreum.gui import queries
from horreum.object_change import _nazwa_lightu, _nazwa_stosu, path_key, plan_object_change
from horreum.resolve.catalog import catalog_label
from horreum.scan import Card

NOW = "2026-10-11T12:00:00+00:00"


class _Archiwum:
    """Baza w pamięci + drzewo `ASTRO_` w `tmp_path`; każda klatka ma prawdziwy (pusty) plik."""

    def __init__(self, tmp_path):
        self.root = tmp_path / "ASTRO_"
        self.root.mkdir()
        self.con = db.connect(":memory:")
        db.migrate(self.con)
        self._n = 0

    def sciezka(self, rel):
        return str(self.root / rel)

    def obiekt(self, canon, kind="deep_sky"):
        oid, _ = repo.upsert_object(self.con, canon=canon, catalog=catalog_label(canon), kind=kind,
                                    now=NOW)
        return oid

    def klatka(self, rel, *, canon=None, okind="deep_sky", card="auto", source="header",
               filetype="fits", kind="light", mtime="m1", header_hash="h1", plik=True,
               date_obs="2022-03-21T20:29:01", extra_cards=()):
        """Klatka z jedną obecną kopią pod `rel`. `card="auto"` = forma karty kanonu (karta zgodna),
        None = brak karty `OBJECT`."""
        self._n += 1
        fid, _ = repo.upsert_frame(self.con, sha1_data=f"s{self._n}", kind=kind, filetype=filetype,
                                   camera_id=None, now=NOW)
        if card == "auto":
            card = None if canon is None or filetype == "raw" else self._forma(canon)
        karty = ([Card("OBJECT", 0, card, None, "str", "Name of the object")] if card is not None
                 else []) + list(extra_cards)
        repo.record_header(self.con, frame_id=fid, raw_json="{}", now=NOW, cards=karty or None,
                           date_obs=date_obs, object_raw=card)
        sciezka = self.sciezka(rel)
        if plik:
            os.makedirs(os.path.dirname(sciezka), exist_ok=True)
            open(sciezka, "wb").close()
        repo.add_location(self.con, frame_id=fid, volume="VOL", path=sciezka, mtime=mtime,
                          header_hash=header_hash, now=NOW)
        if canon is not None:
            repo.assign_object(self.con, frame_id=fid, object_id=self.obiekt(canon, okind),
                               object_source=source, now=NOW)
        return fid

    def _forma(self, canon):
        from horreum.resolver import forma_karty_object
        return forma_karty_object(self.con, canon) or canon

    def plan(self, ids, target=None, **kw):
        rows = queries.object_change_rows(self.con, ids, target=target)
        return plan_object_change(rows, target=target, library_root=str(self.root),
                                  location_at=queries.location_lookup(self.con), **kw)

    def drzewo(self):
        return sorted(os.path.relpath(os.path.join(d, n), self.root)
                      for d, dirs, files in os.walk(self.root) for n in dirs + files)


@pytest.fixture
def arch(tmp_path):
    a = _Archiwum(tmp_path)
    yield a
    a.con.close()


def _jedna(plan):
    assert len(plan.items) == 1, (plan.items, plan.skipped)
    return plan.items[0]


def _powody(plan):
    return {s.frame_id: s.reason for s in plan.skipped}


# ═══════════════════════════════════════════════════════════════════ gest „Zmień obiekt…”


def test_zmiana_obiektu_nowy_folder_nazwa_karta_i_kotwice(arch):
    fid = arch.klatka(r"LIGHTS\NGC3034\RC6_2600MC\OSC\NGC3034_x.fits", canon="NGC3034")
    oid = arch.con.execute("SELECT object_id FROM frame WHERE id = ?", (fid,)).fetchone()[0]
    obiektow = arch.con.execute("SELECT count(*) FROM object").fetchone()[0]
    cel = queries.object_target(arch.con, "M 44")                     # nowy obiekt, xref → NGC2632
    assert (cel.canon, cel.catalog, cel.kind, cel.card_form) == ("NGC2632", "NGC", "deep_sky",
                                                                  "NGC 2632")
    plan = arch.plan([fid], target=cel, run_id="R1")
    it = _jedna(plan)
    assert plan.run_id == "R1" and plan.target == cel and not plan.skipped and not plan.warnings
    assert it.new_path == arch.sciezka(r"LIGHTS\NGC2632\RC6_2600MC\OSC\NGC2632_x.fits")
    assert it.mkdirs == (arch.sciezka(r"LIGHTS\NGC2632"), arch.sciezka(r"LIGHTS\NGC2632\RC6_2600MC"),
                         arch.sciezka(r"LIGHTS\NGC2632\RC6_2600MC\OSC"))
    assert (it.card_op, it.card_old, it.card_new) == ("set", "NGC 3034", "NGC 2632")
    assert (it.expected_header_hash, it.expected_mtime) == ("h1", "m1")
    assert it.expected_object == (oid, "header", None) and it.object_change is True
    assert arch.con.execute("SELECT count(*) FROM object").fetchone()[0] == obiektow


def test_cel_rowny_biezacemu_obiektowi_nie_zmienia_bazy(arch):
    fid = arch.klatka(r"LIGHTS\NGC3034\cam\CLS\a.fits", canon="NGC3031", card="NGC 3031")
    it = _jedna(arch.plan([fid], target=queries.object_target(arch.con, "NGC3031")))
    assert it.object_change is False and it.card_op is None
    assert it.new_path == arch.sciezka(r"LIGHTS\NGC3031\cam\CLS\a.fits")      # nazwa bez obiektu


def test_cel_bez_formy_karty_odmawia_przed_planem(arch):
    zw = arch.obiekt("ZW77", "own")
    repo.add_object_alias(arch.con, alias_norm="ZUPELNIEWYMYSLONA77", object_id=zw, source="user",
                          now=NOW)
    cel = queries.object_target(arch.con, "Zupelnie Wymyslona 77")
    assert cel.canon == "ZW77" and cel.card_form is None
    fid = arch.klatka(r"LIGHTS\M31\cam\a.fits", canon="NGC224")
    with pytest.raises(ValueError, match="bez formy karty"):
        plan_object_change(queries.object_change_rows(arch.con, [fid], target=cel), target=cel,
                           library_root=None, location_at=lambda v, p: frozenset())


def test_object_target_drabina_jak_okno_przypisania(arch):
    arch.obiekt("NGC3034")
    assert queries.object_target(arch.con, "NGC3034").catalog == "NGC"
    lemmon = queries.object_target(arch.con, "Comet Lemmon", alias_norm="COMETLEMMON")
    assert (lemmon.canon, lemmon.kind, lemmon.alias_norm) == ("C/2025 A6 (Lemmon)", "comet",
                                                               "COMETLEMMON")
    assert lemmon.card_form == "C/2025 A6 (Lemmon)"
    assert queries.object_target(arch.con, "zupelnie nic") is None
    assert queries.object_target(arch.con, "  ") is None


def test_wiersze_policzone_dla_innego_celu_to_EXPECT(arch):
    fid = arch.klatka(r"LIGHTS\M31\cam\a.fits", canon="NGC224")
    rows = queries.object_change_rows(arch.con, [fid])
    with pytest.raises(ValueError, match="policzony dla celu"):
        plan_object_change(rows, target=queries.object_target(arch.con, "M33"),
                           library_root=None, location_at=lambda v, p: frozenset())


# ═══════════════════════════════════════════════════════════════════ „Uzgodnij” i kategoria


def test_uzgodnij_przenosi_plik_do_folderu_obiektu_bez_zmiany_bazy(arch):
    fid = arch.klatka(r"LIGHTS\Sh2-229\A140R\B\Sh2-229_x.fits", canon="IC405")
    it = _jedna(arch.plan([fid]))
    assert it.new_path == arch.sciezka(r"LIGHTS\IC405\A140R\B\IC405_x.fits")
    assert it.card_op is None and it.card_new == "IC 405" and it.object_change is False


def test_kategoria_celu_z_rodzaju_obiektu(arch):
    deep = arch.klatka(r"LIGHTS\_SOLAR\Saturn\cam\Saturn_a.fits", canon="Saturn",
                       okind="solar_system")
    kom = arch.klatka(r"LIGHTS\NGC3034\cam\NGC3034_b.fits", canon="NGC3034")
    p1 = arch.plan([deep], target=queries.object_target(arch.con, "NGC7000"))
    assert _jedna(p1).new_path == arch.sciezka(r"LIGHTS\NGC7000\cam\NGC7000_a.fits")
    p2 = arch.plan([kom], target=queries.object_target(arch.con, "C/2023 A3"))
    assert _jedna(p2).new_path == arch.sciezka(
        r"LIGHTS\_COMETS\C2023A3_Tsuchinshan-ATLAS\cam\C2023A3_Tsuchinshan-ATLAS_b.fits")


def test_istniejacy_katalog_w_innej_pisowni_bierze_forme_z_dysku(arch):
    os.makedirs(arch.sciezka(r"LIGHTS\ic405\A140R"))
    fid = arch.klatka(r"LIGHTS\Sh2-229\A140R\B\a.fits", canon="IC405")
    it = _jedna(arch.plan([fid]))
    assert it.new_path == arch.sciezka(r"LIGHTS\ic405\A140R\B\a.fits")
    assert it.mkdirs == (arch.sciezka(r"LIGHTS\ic405\A140R\B"),)


def test_katalog_zaplanowany_przez_pierwsza_pozycje_ma_jedna_pisownie(arch):
    """Dwa pliki z podfolderami `Rig\\Ha` i `rig\\Ha` pod NIEISTNIEJĄCYM folderem obiektu: pierwsza
    pozycja ustala pisownię, druga ją bierze - jedna pisownia w obu ścieżkach, jeden łańcuch
    katalogów (każda pozycja niesie go w całości, bez drugiej pisowni)."""
    a = arch.klatka(r"LIGHTS\A\Rig\Ha\1.fits", canon="NGC224")
    b = arch.klatka(r"LIGHTS\B\rig\Ha\2.fits", canon="NGC224", date_obs="2022-03-22T20:29:01")
    plan = arch.plan([a, b], target=queries.object_target(arch.con, "NGC5"))
    nowe = {i.frame_id: i for i in plan.items}
    katalog = arch.sciezka(r"LIGHTS\NGC5\Rig\Ha")
    assert nowe[a].new_path == katalog + r"\1.fits"
    assert nowe[b].new_path == katalog + r"\2.fits"
    lancuch = (arch.sciezka(r"LIGHTS\NGC5"), arch.sciezka(r"LIGHTS\NGC5\Rig"), katalog)
    assert nowe[a].mkdirs == nowe[b].mkdirs == lancuch


def test_cel_o_folderze_innego_obiektu_jest_odmowiony(arch):
    """Forma folderu komety nie jest różnowartościowa: `(Foo Bar)` i `(Foo_Bar)` dają jeden folder.
    Cel, którego folder ma INNY kanon bazy (bez wielkości liter), planer odmawia - w obu trybach."""
    arch.obiekt("C/2025 A6 (Foo_Bar)", "comet")
    fid = arch.klatka(r"LIGHTS\_COMETS\X\cam\1.ARW", canon="C/2025 A6 (Foo Bar)", okind="comet",
                      filetype="raw", source="comet")
    powody = _powody(arch.plan([fid]))
    assert "C/2025 A6 (Foo_Bar)" in powody[fid] and "do jednego folderu" in powody[fid]
    cel = object_change.ObjectTarget(canon="C/2025 A6 (FOO BAR)", catalog="comet", kind="comet",
                                     alias_norm=None, card_form="x")    # nowy kanon, bez wielkości liter
    assert "C/2025 A6 (Foo_Bar)" in _powody(arch.plan([fid], target=cel))[fid]
    inny = object_change.ObjectTarget(canon="C/2025 A6 (Inna)", catalog="comet", kind="comet",
                                      alias_norm=None, card_form="x")
    assert _jedna(arch.plan([fid], target=inny)).new_path.startswith(
        arch.sciezka(r"LIGHTS\_COMETS\C2025A6_Inna\cam"))


def _drzewo_sh2(arch, filtry=("B", "G", "Ha"), **kw):
    return [arch.klatka(rf"LIGHTS\Sh2-229\A140R\{f}\Sh2-229_{n}.fits", canon="IC405",
                        date_obs=f"2025-10-0{n}T23:00:00", **kw)
            for n, f in enumerate(filtry, start=1)]


def test_plan_mowi_ktore_katalogi_zrodlowe_sterownik_usunie(arch):
    """Całe drzewo `Sh2-229` opróżnione przez „Uzgodnij”: filtry, zestaw i folder obiektu - od
    najgłębszego (wizytacja: „usunięte: 8” na archiwum)."""
    plan = arch.plan(_drzewo_sh2(arch))
    s = arch.sciezka
    assert plan.rmdirs == (s(r"LIGHTS\Sh2-229\A140R\B"), s(r"LIGHTS\Sh2-229\A140R\G"),
                           s(r"LIGHTS\Sh2-229\A140R\Ha"), s(r"LIGHTS\Sh2-229\A140R"),
                           s(r"LIGHTS\Sh2-229"))


def test_katalog_z_plikiem_spoza_bazy_albo_pozycja_pominieta_zostaje(arch):
    b, g, ha = _drzewo_sh2(arch)
    open(arch.sciezka(r"LIGHTS\Sh2-229\A140R\Ha\notatka.txt"), "wb").close()
    s = arch.sciezka
    assert arch.plan([b, g, ha]).rmdirs == (s(r"LIGHTS\Sh2-229\A140R\B"),
                                            s(r"LIGHTS\Sh2-229\A140R\G"))
    os.remove(s(r"LIGHTS\Sh2-229\A140R\Ha\notatka.txt"))
    arch.con.execute("UPDATE location SET mtime = NULL WHERE frame_id = ?", (g,))
    plan = arch.plan([b, g, ha])
    assert g in _powody(plan)
    assert plan.rmdirs == (s(r"LIGHTS\Sh2-229\A140R\B"), s(r"LIGHTS\Sh2-229\A140R\Ha"))
    assert arch.plan([b]).rmdirs == (s(r"LIGHTS\Sh2-229\A140R\B"),)     # nie w planie = zostaje


def test_rmdirs_planu_to_katalogi_usuniete_przez_sterownik(arch):
    """Zgodność z regułą sterownika: plan „Uzgodnij” → staging → prawdziwy zapis w `tmp_path`;
    katalogi, które zniknęły z dysku, to dokładnie `rmdirs` podglądu."""
    from horreum import scan, writeback
    ids = _drzewo_sh2(arch) + [arch.klatka(r"LIGHTS\Sh2-229\A140R\OIII\Sh2-229_9.fits",
                                           canon="IC405", date_obs="2025-10-09T23:00:00")]
    open(arch.sciezka(r"LIGHTS\Sh2-229\A140R\OIII\notatka.txt"), "wb").close()
    for lid, sciezka in arch.con.execute("SELECT id, path FROM location").fetchall():
        arch.con.execute("UPDATE location SET mtime = ? WHERE id = ?",
                         (scan._mtime_iso(os.stat(sciezka)), lid))
    arch.con.commit()
    plan = arch.plan(ids, run_id="U1")
    assert len(plan.items) == 4 and len(plan.rmdirs) == 3

    def katalogi():
        return {os.path.join(d, n) for d, dirs, _ in os.walk(arch.root) for n in dirs}
    przed = katalogi()
    repo.stage_object_change(arch.con, plan=plan, now=NOW)
    wynik = writeback.commit_object_change(arch.con, "U1", now=NOW)
    assert len(wynik.applied) == 4, wynik
    assert przed - katalogi() == set(plan.rmdirs)
    assert wynik.dirs_removed == len(plan.rmdirs)


def test_sama_zmiana_pisowni_to_brak_ruchu(arch):
    fid = arch.klatka(r"LIGHTS\ngc7000\cam\ngc7000_20220321_202901.FITS", canon="NGC7000")
    assert _powody(arch.plan([fid]))[fid].startswith("bez zmian")
    karta = arch.klatka(r"LIGHTS\ngc7000\cam\NGC7000_20220322_202901.fits", canon="NGC7000",
                        card="NGC7000", date_obs="2022-03-22T20:29:01")
    it = _jedna(arch.plan([karta]))                                  # karta do formy, plik stoi
    assert it.new_path is None and it.mkdirs == () and it.card_op == "set"


# ═══════════════════════════════════════════════════════════════════ pominięcia z powodem


def test_kolizje_we_wsadzie_na_dysku_i_w_bazie(arch):
    a = arch.klatka(r"LIGHTS\A\cam\1.fits", canon="NGC224")
    b = arch.klatka(r"LIGHTS\B\cam\1.fits", canon="NGC224")
    plan = arch.plan([a, b], target=queries.object_target(arch.con, "NGC1"))
    assert not plan.items                                  # ta sama nazwa w jednym katalogu celu
    assert all(r.startswith("kolizja we wsadzie") for r in _powody(plan).values())
    sa = _stos(arch, r"STACKS\A\c\Ha\A_2025-08-23_c_Ha_60s_mono.xisf", canon="NGC253")
    sb = _stos(arch, r"STACKS\B\c\Ha\B_2025-08-23_c_Ha_60s_mono.xisf", canon="NGC254")
    plan = arch.plan([sa, sb], target=queries.object_target(arch.con, "NGC1"))
    assert not plan.items and all(r.startswith("kolizja we wsadzie") for r in _powody(plan).values())

    os.makedirs(arch.sciezka(r"LIGHTS\NGC2\cam"))
    open(arch.sciezka(r"LIGHTS\NGC2\cam\ngc2_x.FITS"), "wb").close()     # bez wielkości liter
    c = arch.klatka(r"LIGHTS\C\cam\NGC224_x.fits", canon="NGC224")
    assert _powody(arch.plan([c], target=queries.object_target(arch.con, "NGC2")))[c].startswith(
        "na dysku stoi już plik")

    d = arch.klatka(r"LIGHTS\D\cam\NGC224_y.fits", canon="NGC224")
    duch = arch.klatka(r"LIGHTS\NGC3\cam\NGC3_y.fits", canon="NGC3", plik=False)
    arch.con.execute("UPDATE location SET present = 0 WHERE frame_id = ?", (duch,))
    assert _powody(arch.plan([d], target=queries.object_target(arch.con, "NGC3")))[d].startswith(
        "w bazie jest inna kopia")


def test_karta_odbita_bramka_zostawia_caly_plik_a_RAW_i_region_jada_bez_karty(arch):
    suma = arch.klatka(r"LIGHTS\X\cam\1.fits", canon="NGC224", card="M 31",
                       extra_cards=[Card("CHECKSUM", 0, "abc", None, "str", None)])
    raw = arch.klatka(r"LIGHTS\X\cam\2.ARW", canon="NGC224", filetype="raw",
                      date_obs="2022-03-25T00:00:00")
    plan = arch.plan([suma, raw], target=queries.object_target(arch.con, "M33"))
    assert "CHECKSUM/DATASUM" in _powody(plan)[suma]
    assert "karta i folder idą razem" in _powody(plan)[suma]
    it = _jedna(plan)
    assert it.frame_id == raw and it.card_op is None and it.card_new is None
    assert it.new_path == arch.sciezka(r"LIGHTS\M33\cam\2.ARW")

    region = arch.klatka(r"LIGHTS\Petla\cam\3.fits", canon="Veil", okind="region", source="region",
                         card=None, date_obs="2022-03-26T00:00:00")
    it = _jedna(arch.plan([region]))
    assert it.card_op is None and it.new_path.startswith(arch.sciezka(r"LIGHTS\Veil\cam"))


def test_przy_uzgodnij_klatka_bez_formy_karty_pominieta_RAW_nie(arch):
    zw = arch.obiekt("ZW77", "own")
    repo.add_object_alias(arch.con, alias_norm="ZUPELNIEWYMYSLONA77", object_id=zw, source="user",
                          now=NOW)
    fits_ = arch.klatka(r"LIGHTS\Inne\cam\1.fits", canon="ZW77", okind="own",
                        card="Zupelnie Wymyslona 77")
    raw = arch.klatka(r"LIGHTS\Inne\cam\2.ARW", canon="ZW77", okind="own", filetype="raw",
                      date_obs="2022-03-25T00:00:00")
    plan = arch.plan([fits_, raw])
    assert queries.SKIP_FORM_NOT_CANON in _powody(plan)[fits_]
    assert _jedna(plan).frame_id == raw


def test_stan_klatki_mtime_kopie_kalibracja_wycofana_bez_obiektu(arch):
    bez_mtime = arch.klatka(r"LIGHTS\X\cam\1.fits", canon="NGC224", mtime=None)
    dwie = arch.klatka(r"LIGHTS\X\cam\2.fits", canon="NGC224")
    repo.add_location(arch.con, frame_id=dwie, volume="VOL", path=arch.sciezka(r"LIGHTS\Y\c\2.fits"),
                      mtime="m", now=NOW)
    dark = arch.klatka(r"CALIBRATION\darks\d.fits", kind="dark")
    wycofana = arch.klatka(r"LIGHTS\X\cam\3.fits", canon="NGC224")
    arch.con.execute("UPDATE frame SET retired_at = ? WHERE id = ?", (NOW, wycofana))
    bez = arch.klatka(r"LIGHTS\X\cam\4.fits")
    poza = arch.klatka(r"Inne\X\cam\5.fits", canon="NGC224")
    powody = _powody(arch.plan([bez_mtime, dwie, dark, wycofana, bez, poza]))
    assert powody[bez_mtime].startswith("kopia bez mtime")
    assert powody[dwie].startswith("wiele obecnych kopii (2)")
    assert "nie ma obiektu z definicji" in powody[dark]
    assert powody[wycofana] == "klatka wycofana z archiwum"
    assert powody[bez].startswith("klatka bez obiektu")
    assert powody[poza].startswith("plik nie stoi na pozycji obiektu")


def test_cel_w_drzewie_roboczym_jest_niemozliwy_z_konstrukcji(arch):
    fid = arch.klatka(r"_WBPP\proba\LIGHTS\M31\cam\1.fits", canon="NGC224")
    with pytest.raises(AssertionError, match="drzewie roboczym"):
        arch.plan([fid], target=queries.object_target(arch.con, "M33"))


# ═══════════════════════════════════════════════════════════════════ stosy


def _stos(arch, rel, canon="IC405", sha=None):
    return arch.klatka(rel, canon=canon, kind="master_light", filetype="xisf",
                       date_obs="2025-08-23T20:00:00")


def test_stos_zmienia_czlon_obiektu_a_wersja_jedzie_z_oryginalem(arch):
    o = _stos(arch, r"STACKS\IC405\A140R\Ha\IC405_2025-08-23_A140R_Ha_60s_mono_WBPP.xisf")
    v = _stos(arch, r"STACKS\IC405\A140R\Ha\IC405_2025-08-23_A140R_Ha_60s_mono_autocrop_WBPP.xisf")
    repo.link_stack_variant(arch.con, variant_frame_id=v, original_frame_id=o, variant="autocrop",
                            source="user", now=NOW)
    cel = queries.object_target(arch.con, "C/2025 A6")
    for wybor in ([o], [v]):                              # połowa pary wciąga drugą
        plan = arch.plan(wybor, target=cel)
        nowe = {i.frame_id: i.new_path for i in plan.items}
        assert set(nowe) == {o, v} and not plan.skipped
        katalog = arch.sciezka(r"STACKS\C2025A6_Lemmon\A140R\Ha")
        assert nowe[o] == katalog + r"\C2025A6_Lemmon_2025-08-23_A140R_Ha_60s_mono_WBPP.xisf"
        assert nowe[v] == katalog + r"\C2025A6_Lemmon_2025-08-23_A140R_Ha_60s_mono_autocrop_WBPP.xisf"
        assert {i.mkdirs for i in plan.items} == {(arch.sciezka(r"STACKS\C2025A6_Lemmon"),
                                                   arch.sciezka(r"STACKS\C2025A6_Lemmon\A140R"),
                                                   katalog)}


def test_wersja_stosu_w_innym_katalogu_i_polowa_pominieta_to_oba_pominiete(arch):
    o = _stos(arch, r"STACKS\IC405\A140R\Ha\IC405_2025-08-23_A140R_Ha_60s_mono.xisf")
    v = _stos(arch, r"STACKS\IC405\A140R\OIII\IC405_2025-08-23_A140R_Ha_60s_mono_autocrop.xisf")
    repo.link_stack_variant(arch.con, variant_frame_id=v, original_frame_id=o, variant="autocrop",
                            source="user", now=NOW)
    powody = _powody(arch.plan([o], target=queries.object_target(arch.con, "IC1848")))
    assert powody[v].startswith("wersja stosu leży w innym katalogu")
    assert powody[o].startswith("para stosu jedzie razem")


def test_nazwa_stosu_wymienia_wylacznie_czlon_obiektu():
    assert _nazwa_stosu("C2025A6_Lemmon_2025-10-19_A140R_R_15s_mono.xisf", "IC405") == \
        "IC405_2025-10-19_A140R_R_15s_mono.xisf"
    assert _nazwa_stosu("IC405_2025-10-19_A140R_R_15s_mono.xisf", "21P/Giacobini-Zinner") == \
        "21P_Giacobini-Zinner_2025-10-19_A140R_R_15s_mono.xisf"
    nazwa_wbpp = "masterLight_BIN-1_FILTER-Ha.xisf"            # spoza układu - nie niesie obiektu
    assert _nazwa_stosu(nazwa_wbpp, "IC405") == nazwa_wbpp


def test_przeniesienie_czesci_wejsc_stosu_ostrzega(arch):
    lights = [arch.klatka(rf"LIGHTS\M31\cam\L\{i}.fits", canon="NGC224",
                          date_obs=f"2022-03-2{i}T20:00:00") for i in range(1, 4)]
    s = _stos(arch, r"STACKS\M31\cam\L\M31_2022-03-21_cam_L_60s_mono.xisf", canon="NGC224")
    iid, _ = repo.upsert_integration(
        arch.con, master_frame_id=s, integ_hash=None, tool=None, window_start=None, window_end=None,
        declared_rows=None, drizzle_inputs=None, disabled_inputs=None, degenerate=0, ambiguous=0,
        telescope_mismatch=0, unresolved_reason=None, now=NOW)
    for f in lights:
        repo.link_integration(arch.con, integration_id=iid, input_frame_id=f, asserted_by="user",
                              now=NOW)
    cel = queries.object_target(arch.con, "M33")
    plan = arch.plan(lights[:2], target=cel)
    assert len(plan.items) == 2 and len(plan.warnings) == 1
    w = plan.warnings[0]
    assert w.frame_ids == tuple(lights[:2])
    assert "M31_2022-03-21_cam_L_60s_mono.xisf" in w.text and "2 z 3" in w.text
    calosc = arch.plan(lights, target=cel)
    assert not calosc.warnings                                 # cały zbiór wejść - jedna siedziba

    # Regresja żniw: siedziba stosu = JEDEN ogon folderu lightów wszystkich wejść
    # (`harvest._light_tail`, klucz bez wielkości liter). Po przeniesieniu całego zbioru ogon jest
    # jeden (nowy folder obiektu), po przeniesieniu części - dwa (`no_light_seat`), i dokładnie
    # wtedy plan ostrzega.
    from horreum.harvest import _light_tail

    def ogony(plan):
        nowe = {i.frame_id: i.new_path for i in plan.items}
        sciezki = [nowe.get(f) or arch.sciezka(rf"LIGHTS\M31\cam\L\{n}.fits")
                   for n, f in enumerate(lights, start=1)]
        return {tuple(s.lower() for s in _light_tail(p)) for p in sciezki}
    assert ogony(calosc) == {("m33", "cam", "l")}
    assert len(ogony(plan)) == 2


# ═══════════════════════════════════════════════════════════════════ wspólna bramka karty


def _fakty(**kw):
    r = {"n_present": 1, "n_absent": 0, "compressed": None, "degen": 0, "header_hash": "h",
         "unreadable_since": None, "n_cards": 1, "hdr_hash": None, "hdr_rule": None,
         "hdr_object": None, "vtype": "str", "filetype": "fits", "n_sum": 0}
    r.update(kw)
    return r


def test_bramka_karty_dziala_dla_add_set_i_bez_karty():
    def brama(card, form="NGC 7000", **kw):
        return queries.object_card_gate(_fakty(**kw), card=card, form=form, canon="NGC7000",
                                        lookup=lambda k: None)
    assert brama(None, n_cards=0, vtype=None) is None                       # add
    assert brama("Heart") is None                                           # set
    assert brama(None, n_cards=0, vtype=None, filetype="fits", n_sum=1).startswith("FITS z sumą")
    assert brama("NGC7000", n_present=2) == "wiele obecnych kopii (2)"
    assert brama("NGC7000", form=None) == queries.SKIP_FORM_NOT_CANON
    assert brama("NGC7000_M31").startswith("sklejka")
    assert brama("NGC7000_NGC 7000") is None
    assert brama("NGC7000", vtype="int").startswith("karta OBJECT nietekstowa")


def test_pusta_karta_nie_zeznaje_ale_stoi_w_naglowku_a_brak_karty_to_dopisanie(arch):
    pusta = arch.klatka(r"LIGHTS\M31\cam\1.fits", canon="NGC224", card=None,
                        extra_cards=[Card("OBJECT", 0, "", None, "str", None)])
    brak = arch.klatka(r"LIGHTS\M31\cam\2.fits", canon="NGC224", card=None,
                       date_obs="2022-03-22T20:29:01")
    rows = {r["frame_id"]: r for r in queries.object_change_rows(arch.con, [pusta, brak])}
    assert rows[pusta]["card"] is None and rows[pusta]["card_present"] is True
    assert rows[brak]["card_present"] is False
    assert all(r["card_skip"] is None for r in rows.values())
    plan = arch.plan([pusta, brak], target=queries.object_target(arch.con, "M33"))
    karty = {i.frame_id: (i.card_op, i.card_old, i.card_new) for i in plan.items}
    assert karty == {pusta: ("set", None, "M 33"), brak: ("add", None, "M 33")}


# ═══════════════════════════════════════════════════════════════════ predykat Porządków


def test_predykat_folder_karta_i_bramki(arch):
    folder = arch.klatka(r"LIGHTS\Sh2-229\cam\1.fits", canon="IC405")
    karta = arch.klatka(r"LIGHTS\NGC7000\cam\NGC7000_20220321_202901.fits", canon="NGC7000",
                        card="NGC7000")
    kometa = arch.klatka(r"LIGHTS\_COMETS\C2023A3\cam\3.fits", canon="C/2023 A3 (Tsuchinshan-ATLAS)",
                         okind="comet", source="comet")
    sklejka = arch.klatka(r"LIGHTS\NGC4631\cam\4.fits", canon="NGC4631", card="NGC4631_PGC42637")
    region = arch.klatka(r"LIGHTS\Veil\cam\5.fits", canon="Veil", okind="region", source="region",
                         card=None)
    raw = arch.klatka(r"LIGHTS\NGC891\cam\6.ARW", canon="NGC891", filetype="raw")
    pisownia = arch.klatka(r"LIGHTS\ngc891\cam\7.fits", canon="NGC891")
    dwie = arch.klatka(r"LIGHTS\Zly\cam\8.fits", canon="NGC224")
    repo.add_location(arch.con, frame_id=dwie, volume="VOL", path=arch.sciezka(r"LIGHTS\Q\c\8.fits"),
                      mtime="m", now=NOW)
    zgodna = arch.klatka(r"LIGHTS\M33\cam\9.fits", canon="M33")
    stos = _stos(arch, r"STACKS\IC405\c\Ha\IC405_2025-08-23_c_Ha_60s_mono.xisf")
    przed = arch.con.total_changes
    ids = queries.file_object_mismatch_frame_ids(arch.con)
    assert ids == {folder, karta, kometa}
    assert not {sklejka, region, raw, pisownia, dwie, zgodna, stos} & ids
    assert arch.con.total_changes == przed

    plan = arch.plan(sorted(ids))                              # „Uzgodnij” zamyka wiersz
    assert {i.frame_id for i in plan.items} == ids
    nowe = {i.frame_id: i for i in plan.items}
    assert nowe[karta].new_path is None and nowe[karta].card_op == "set"
    assert nowe[kometa].new_path.startswith(arch.sciezka(r"LIGHTS\_COMETS\C2023A3_Tsuchinshan-ATLAS"))


def test_location_lookup_bez_wielkosci_liter_i_kazdy_present(arch):
    fid = arch.klatka(r"LIGHTS\M31\cam\1.fits", canon="NGC224")
    arch.con.execute("UPDATE location SET present = 0 WHERE frame_id = ?", (fid,))
    lid = arch.con.execute("SELECT id FROM location WHERE frame_id = ?", (fid,)).fetchone()[0]
    lok = queries.location_lookup(arch.con)
    assert lok("VOL", arch.sciezka(r"lights\m31\CAM\1.FITS")) == {lid}
    assert lok("INNY", arch.sciezka(r"LIGHTS\M31\cam\1.fits")) == frozenset()
    assert path_key(r"R:\A\.\b\..\C.fits") == path_key("r:/a/c.FITS")


# ═══════════════════════════════════════════════════════════════════ zero zapisu, styk z „Nazwami”


def test_read_model_i_planer_niczego_nie_zapisuja(arch):
    a = arch.klatka(r"LIGHTS\Sh2-229\cam\1.fits", canon="IC405")
    b = arch.klatka(r"LIGHTS\NGC3034\cam\2.fits", canon="NGC3031", card="NGC 3031")
    drzewo, zmiany = arch.drzewo(), arch.con.total_changes
    queries.file_object_mismatch_frame_ids(arch.con)
    arch.plan([a, b])
    arch.plan([a, b], target=queries.object_target(arch.con, "M 44"))
    assert arch.drzewo() == drzewo and arch.con.total_changes == zmiany


def test_ostatni_gest_reki_niesie_powody_relokacji(arch):
    """Dom rozpoznaje gest zmiany obiektu po `payload.reason` relokacji (`location.renamed`);
    event bez powodu liczy się tylko w czasownikach, a gest bez powodów nie dostaje klucza."""
    ts = "2026-10-11T13:00:00+00:00"
    with arch.con:
        for i, powod in enumerate(("object_change", "object_change", None)):
            repo.emit_event(arch.con, actor="user:local", verb="location.renamed",
                            target=f"location:{i}", now=ts,
                            payload={"before": "a", **({"reason": powod} if powod else {})})
        repo.emit_event(arch.con, actor="user:local", verb="object.assigned", target="frame:1",
                        now=ts, payload={"object_id": 1})
        repo.emit_event(arch.con, actor="user:inny", verb="location.renamed", target="location:9",
                        now=ts, payload={"reason": "object_change_undo"})
        repo.emit_event(arch.con, actor="user:local", verb="location.renamed", target="location:8",
                        now="2026-10-11T12:00:00+00:00", payload={"reason": "object_change_undo"})
    arch.con.execute("UPDATE event SET id = id + 100 WHERE actor = 'user:local' AND ts = ?", (ts,))
    gest = queries.last_hand_gesture(arch.con)
    assert gest == {"ts": ts, "actor": "user:local", "n": 4,
                    "verbs": {"location.renamed": 3, "object.assigned": 1},
                    "reasons": {"location.renamed": {"object_change": 2}}}
    with arch.con:
        repo.emit_event(arch.con, actor="user:local", verb="note.set", target="frame:2",
                        now="2026-10-11T14:00:00+00:00", payload={"text": "x"})
    assert "reasons" not in queries.last_hand_gesture(arch.con)


# ═══════════════════════════════════════════════════════════════════ nazwa pliku (D-1011-6 `O2`)


def test_nazwa_lightu_wymienia_wylacznie_czlon_obiektu():
    """Człon obiektu na początku nazwy → token kanonu celu, reszta znak w znak - także `FLATGRP_…`
    i `OSC`, które wzór „Nazw” zmieniał albo gubił (wizytacja bs W1 W2)."""
    archiwum = "NGC3034_20220326_201500_LIGHT_FLATGRP_NOFLAT_OSC_30s_.fits"
    assert _nazwa_lightu(archiwum, ("NGC3034",), "NGC2632") == \
        "NGC2632_20220326_201500_LIGHT_FLATGRP_NOFLAT_OSC_30s_.fits"
    assert _nazwa_lightu("Sh2-229_x.fits", ("Sh2-229", "IC405"), "IC405") == "IC405_x.fits"
    assert _nazwa_lightu("ngc3034_x.fits", ("NGC3034",), "NGC2632") == "NGC2632_x.fits"
    assert _nazwa_lightu("IC342 20181011_dsc3351.dng", ("IC342",), "NGC1") == \
        "NGC1 20181011_dsc3351.dng"                          # nazwa z lustrzanki: spacja


def test_nazwa_lightu_bez_czlonu_obiektu_zostaje():
    for nazwa in ("20181011_dsc3322.dng", "_DSC6180.ARW", "NGC30345_x.fits", "NGC3034.fits",
                  "M63 20181003_dsc3087.dng"):
        assert _nazwa_lightu(nazwa, ("NGC3034", "NGC5055"), "NGC2632") == nazwa


def test_nazwa_lightu_kometa_najdluzszy_czlon_i_idempotencja():
    """Forma komety dłuższa od folderu: pierwszy gest dokłada nazwę, drugi już nie dubluje."""
    kometa = "C/2023 A3 (Tsuchinshan-ATLAS)"
    raz = _nazwa_lightu("C2023A3_20240101.fits", ("C2023A3", "C2023A3_Tsuchinshan-ATLAS"), kometa)
    assert raz == "C2023A3_Tsuchinshan-ATLAS_20240101.fits"
    assert _nazwa_lightu(raz, ("C2023A3_Tsuchinshan-ATLAS",), kometa) == raz
    assert _nazwa_lightu(raz, ("C2023A3",), kometa) == raz          # folder krótszy niż nazwa
    assert _nazwa_lightu(raz, ("C2023A3_Tsuchinshan-ATLAS",), "NGC1") == "NGC1_20240101.fits"


def test_stary_czlon_z_obiektu_w_bazie_gdy_folder_inny(arch):
    """Plik w folderze innego obiektu niosący w nazwie obiekt z bazy: człon z bazy też jest stary."""
    fid = arch.klatka(r"LIGHTS\Q\cam\NGC224_x.fits", canon="NGC224")
    it = _jedna(arch.plan([fid], target=queries.object_target(arch.con, "M33")))
    assert it.new_path == arch.sciezka(r"LIGHTS\M33\cam\M33_x.fits")


def test_proba_fali_10_b_i_c_bez_ruchu_pliku(arch):
    """(b) karta `NGC 3031` w folderze `NGC3034` → `NGC 3034`: plik stoi, nazwa ta sama, karta
    i baza się zmieniają; (c) Saturn → Saturn bez zmian (kod `SKIP_UNCHANGED`, nie odmowa)."""
    b = arch.klatka(r"LIGHTS\NGC3034\ED120R_2600MM\L\NGC3034_20220321_202901_L.fits",
                    canon="NGC3031", card="NGC 3031")
    it = _jedna(arch.plan([b], target=queries.object_target(arch.con, "NGC 3034")))
    assert it.new_path is None and it.card_op == "set" and it.object_change is True
    c = arch.klatka(r"LIGHTS\_SOLAR\Saturn\A140R_2600MC\Saturn_20250907_193535.fits",
                    canon="Saturn", okind="solar_system")
    plan = arch.plan([c], target=queries.object_target(arch.con, "Saturn"))
    assert not plan.items
    assert [(s.frame_id, s.code) for s in plan.skipped] == [(c, object_change.SKIP_UNCHANGED)]


def test_odmowa_nie_niesie_kodu_bez_zmian(arch):
    fid = arch.klatka(r"LIGHTS\X\cam\1.fits", canon="NGC224", mtime=None)
    assert [s.code for s in arch.plan([fid]).skipped] == [None]
