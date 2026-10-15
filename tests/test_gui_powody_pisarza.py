"""Okna zapisu mówią powodem warstwy pisarza karty i renamu w języku UI (AR-148): zdanie wyniku
okien kart („Napraw nagłówek…”, „Zatwierdź ze ścieżki…”), szuflada Zbiorów (cofnięcie kart, cofnięcie
Nazw, gesty izolacji), okno „Zmień obiekt…” (podpowiedź spadku, ostrzeżenia rekoncyliacji renamu).
W EN żadnego polskiego zdania - poza prozą granicy (tekst systemu), której próbki są tu ASCII."""
import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from horreum import db, scan, writeback
from horreum.gui import i18n
from horreum.item_reasons import PowodPozycji

NOW = "2026-10-15T00:00:00+00:00"
_POLSKIE = set("„ąćęłńóśźżĄĆĘŁŃÓŚŹŻ")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def en():
    i18n.set_lang("en")
    yield
    i18n.set_lang("pl")


def _bez_polskiego(tekst):
    return not set(tekst) & _POLSKIE


def test_szczegol_spadku_w_podpowiedzi_i_statusie_mowi_w_jezyku_UI(en):
    """Spadek karty na drogę atomową: szczegół (powód `Fallback` z kodem) schodzi do podpowiedzi
    okien kart i wiersza „Zmień obiekt…” - w EN po angielsku. Falsyfikator: `podziel_powod_spadku`
    oddaje `detail` bez `tekst_powodu` → polski szczegół w podpowiedzi."""
    from horreum.gui.wb_worker import podpowiedz_spadku, status_pozycji
    szczegol = PowodPozycji("plik podmieniony od commitu (rozmiar/st_ino) - cofnięcie atomowe",
                            "fb_replaced_since_commit")
    spadek = PowodPozycji(f"{writeback.PREFIKS_DROGI_ATOMOWEJ}: {szczegol}", "inplace_fallback",
                          detail=szczegol)
    fr = writeback.FileResult(1, "X:/L/a.fits", "applied", spadek,
                              code=writeback.CODE_INPLACE_FALLBACK)
    res = writeback.CommitResult("R", 1, [fr], [], [], [])
    podpowiedz = podpowiedz_spadku(res)
    assert "size/st_ino" in podpowiedz and _bez_polskiego(podpowiedz), podpowiedz
    status, tip = status_pozycji(i18n.t("objchg.st.done"), spadek, writeback.CODE_INPLACE_FALLBACK)
    assert _bez_polskiego(status) and _bez_polskiego(tip) and "size/st_ino" in tip, (status, tip)


def test_zdanie_okna_kart_na_prawdziwej_odmowie_pisarza(en, tmp_path):
    """Prawdziwa odmowa pisarza (nagłówek zmieniony od stagingu, obie drogi zapisu) w zdaniu wyniku
    okien kart - w EN bez polskiego."""
    from test_writeback_inplace import _fits, _loc, _scan_in, _stage
    from horreum.gui.wb_worker import zdanie_commitu_kart
    for inplace in (False, True):
        con = db.open_db(str(tmp_path / f"h{inplace}.db"))
        p = _fits(tmp_path / f"z{inplace}.fits")
        _scan_in(con, p)
        _stage(con, "R", _loc(con, p)["id"], "NGC 6992", "zly-hash")
        res = writeback.commit(con, "R", now=NOW, inplace=inplace)
        (fr,) = res.blocked
        assert fr.reason.code == "header_hash_mismatch", fr.reason
        zdanie, _ = zdanie_commitu_kart(res, "path.cards_applied", w_miejscu=inplace)
        assert "header_hash mismatch" in zdanie and _bez_polskiego(zdanie), zdanie
        con.close()


@pytest.fixture
def widok(qapp, tmp_path):
    """FramesView nad bazą z jednym plikiem FITS (wzorzec `test_gui_grid.wb_view`)."""
    import numpy as np
    from astropy.io import fits
    from horreum.gui.grid import FramesView
    p = tmp_path / "wb.fits"
    hdu = fits.PrimaryHDU(data=np.zeros((4, 4), dtype=np.int16))
    hdu.header["TELESCOP"] = "RC8"
    hdu.header["IMAGETYP"] = "Light"
    hdu.writeto(str(p), overwrite=True)
    con = db.open_db(str(tmp_path / "wb.db"))
    scan.ingest_record(con, scan.scan_file(str(p)), volume="V", now=NOW, summary=scan.ScanSummary())
    v = FramesView(con, now_fn=lambda: NOW)
    yield v, con, p
    con.close()


@pytest.mark.parametrize("ogon", ["_after_undo", "_after_undo_rename"])
def test_szuflada_cofniecie_kart_i_Nazw_mowi_powodem_w_jezyku_UI(en, widok, monkeypatch, ogon):
    """Szuflada Zbiorów: ogon cofnięcia kart i cofnięcia Nazw dokleja pierwszy powód błędu/blokady
    - w EN po angielsku. Falsyfikator: `detail=detail.reason` bez `tekst_powodu` → polskie zdanie."""
    view, _con, p = widok
    view._ensure_undo_button()
    wynik = []
    monkeypatch.setattr(view.drawer, "set_result", wynik.append)
    monkeypatch.setattr(view.drawer, "set_count", lambda n, result=None: wynik.append(result))
    powod = PowodPozycji("plik nie stoi na nazwie z commitu", "not_on_commit_name")
    zablokowany = writeback.FileResult(1, str(p), "blocked", powod)
    getattr(view, ogon)(ogon, writeback.UndoResult(commit_id=1, restored=[], blocked=[zablokowany],
                                                   failed=[]))
    (msg,) = [m for m in wynik if m]
    assert "the file is not at the name from the commit" in msg and _bez_polskiego(msg), msg


def test_szuflada_cofniecie_na_PRAWDZIWYM_undo_mowi_prawde_drogi_cofniecia(en, widok, monkeypatch):
    """Cofnięcie atomowe porównuje nagłówek na dysku z nagłówkiem zapisanym przez COMMIT, więc jego
    odmowa (`undo_header_changed`) mówi w EN „changed since the commit”, nie „since staging” (to
    prawda zapisu, `header_hash_mismatch`). Proza PL obu: „header_hash mismatch” znak w znak.
    Falsyfikator: cofnięcie oddaje kod zapisu → szuflada w EN mówi „since staging”."""
    from astropy.io import fits
    from horreum import repo
    view, con, p = widok
    view._ensure_undo_button()
    loc = con.execute("SELECT id, header_hash FROM location").fetchone()
    repo.stage_pending(con, run_id="R", location_id=loc["id"], keyword="OBJECT", idx=0, op="set",
                       old_value=None, new_value="NGC 6992", new_type="str", new_comment=None,
                       expected_header_hash=loc["header_hash"])
    res = writeback.commit(con, "R", now=NOW)
    assert res.applied and res.commit_id, res
    fits.setval(str(p), "TELESCOP", value="Inny")                 # cudza zmiana po commicie
    undo = writeback.undo(con, res.commit_id, now=NOW)
    (zablokowany,) = undo.blocked
    assert zablokowany.reason.code == "undo_header_changed", zablokowany.reason
    assert str(zablokowany.reason) == "header_hash mismatch"
    wynik = []
    monkeypatch.setattr(view.drawer, "set_result", wynik.append)
    monkeypatch.setattr(view.drawer, "set_count", lambda n, result=None: wynik.append(result))
    view._after_undo("_after_undo", undo)
    (msg,) = [m for m in wynik if m]
    assert "changed since the commit" in msg and "since staging" not in msg, msg
    assert _bez_polskiego(msg), msg


def test_gest_izolacji_w_Zbiorach_mowi_powodem_w_jezyku_UI(en):
    """Pasek gestu izolacji (Dokończ / Przywróć / Zwolnij): pierwszy powód odmowy - w EN po
    angielsku, z nazwą gestu w języku UI. Falsyfikator: `detail=powod.reason` bez `tekst_powodu`."""
    from horreum.gui.grid_model import _zdanie_gestu_zapisu
    from horreum.gui.wb_worker import InplaceGestureResult
    powod = PowodPozycji(f"operacja 3 nie jest otwarta (synced) - odzysk dotyczy wyłącznie "
                         f"przerwanego zapisu", "recover_not_open", op_id=3, phase="synced")
    msg = _zdanie_gestu_zapisu("recover_torn", InplaceGestureResult(
        [writeback.FileResult(1, "X:/L/a.fits", "blocked", powod)]))
    assert "recovery applies only to an interrupted write" in msg and _bez_polskiego(msg), msg


def test_ostrzezenie_rekoncyliacji_renamu_mowi_w_jezyku_UI(en):
    """Ostrzeżenie gestu „Zmień obiekt…” z rekoncyliacji przerwanych renamów (dawniej goły f-string
    PL) ma kod `rename_reconcile`, a powód rekoncyliacji jako parametr - w EN po angielsku.
    Falsyfikator: `tekst_ostrzezenia` bez `tekst_powodu` na parametrze-powodzie."""
    from horreum.gui.object_change_dialog import tekst_ostrzezenia
    from horreum.object_change import ZdanieRdzenia
    powod = PowodPozycji("plik pod obiema nazwami (X:/a / X:/b) - zamiar zostaje, rozstrzyga "
                         "człowiek", "intent_both_names", src="X:/a", dst="X:/b")
    ostrzezenie = ZdanieRdzenia(f"X:/a: {powod}", "rename_reconcile", path="X:/a", detail=powod)
    zdanie = tekst_ostrzezenia(ostrzezenie.code, ostrzezenie.params, ostrzezenie)
    assert zdanie == ("X:/a: the file is under both names (X:/a / X:/b) - the intent stays, a "
                      "person decides"), zdanie
    i18n.set_lang("pl")
    assert tekst_ostrzezenia(ostrzezenie.code, ostrzezenie.params, ostrzezenie) == str(ostrzezenie)
