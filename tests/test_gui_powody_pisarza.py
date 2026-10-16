"""Okna zapisu mówią powodem warstwy pisarza karty i renamu w języku UI (AR-148): zdanie wyniku
okien kart („Napraw nagłówek…”, „Zatwierdź ze ścieżki…”), szuflada Zbiorów (cofnięcie kart, cofnięcie
Nazw, gesty izolacji), okno „Zmień obiekt…” (podpowiedź spadku, ostrzeżenia rekoncyliacji renamu).
W EN żadnego polskiego zdania - poza prozą granicy (tekst systemu), której próbki są tu ASCII."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # przed importem Qt (klasa AR-170)

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
    prawda zapisu, `header_hash_mismatch`). Proza PL też mówi drogę („od commitu”).
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
    assert str(zablokowany.reason) == "nagłówek pliku zmienił się od commitu (header_hash niezgodny)"
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


# ============================ AR-166/167/168/176: powody podglądu, edycji komórki i błędów systemu


@pytest.fixture
def jezyk():
    """Język UI ustawiany w teście (`[pl, en]`), po teście z powrotem PL."""
    yield i18n.set_lang
    i18n.set_lang("pl")


def _widok_nad(qapp, tmp_path, *, suma=False):
    """FramesView nad jednym FITS (`TELESCOP` = RC8), z sumą kontrolną albo bez."""
    import numpy as np
    from astropy.io import fits
    from horreum.gui.grid import FramesView
    p = tmp_path / "wb.fits"
    hdu = fits.PrimaryHDU(data=np.zeros((4, 4), dtype=np.int16))
    hdu.header["TELESCOP"] = "RC8"
    hdu.header["IMAGETYP"] = "Light"
    hdu.writeto(str(p), overwrite=True, checksum=suma)
    con = db.open_db(str(tmp_path / "wb.db"))
    scan.ingest_record(con, scan.scan_file(str(p)), volume="V", now=NOW, summary=scan.ScanSummary())
    v = FramesView(con, now_fn=lambda: NOW)
    v._writeback_async = False
    return v, con, p


def _kolumna(view, keyword):
    from horreum.gui.grid import BASE_COLS
    return len(BASE_COLS) + view.model._kw_off() + view.model._keywords.index(keyword)


def _komunikaty(view):
    out = []
    view.status_message.connect(out.append)
    return out


def _podglad_makra(view, keyword, wartosc):
    """Pasek makra jak człowiek: karta, `set`, wartość, „Podgląd” → podpowiedź komórki podglądu."""
    from PySide6.QtCore import Qt
    bar = view.macro_bar
    bar.asg_kw.setCurrentText(keyword)
    bar.asg_op.setCurrentIndex(0)
    bar.asg_expr.setText(wartosc)
    bar._emit_preview()
    m = view.model
    return m.data(m.index(0, m._preview_col()), Qt.ToolTipRole)


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_podglad_makra_mowi_regule_karty_w_jezyku_UI(qapp, tmp_path, jezyk, lang):
    """AR-167: podpowiedź komórki podglądu makra wstawiała `str` powodu reguły karty - po polsku
    w UI EN, choć powód niesie kod (AR-158). Teraz mówi przez `tekst_powodu`. Falsyfikator:
    `grid_model._preview_cell` bez `tekst_powodu` → polska proza w EN."""
    from horreum import card_rules
    from horreum.gui.wb_worker import tekst_powodu
    jezyk(lang)
    view, con, _p = _widok_nad(qapp, tmp_path)
    tip = _podglad_makra(view, "TELESCOP", "Café")
    regula = card_rules.card_violation("TELESCOP", "Café").reason
    assert tip == i18n.t("grid.preview.skipped_tip", reason=tekst_powodu(regula)), tip
    if lang == "en":
        assert "outside printable ASCII" in tip and _bez_polskiego(tip.replace("é", "")), tip
    else:
        assert str(regula) in tip
    view.close()
    con.close()


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_edycja_komorki_mowi_regule_karty_w_jezyku_UI(qapp, tmp_path, jezyk, lang):
    """AR-167: odmowa edycji komórki (reguła karty) na pasku stanu - w języku UI, PL znak w znak jak
    zdanie reguły. Falsyfikator: `grid._on_cell_edit` bez `tekst_powodu` → polska proza w EN."""
    jezyk(lang)
    view, con, _p = _widok_nad(qapp, tmp_path)
    msg = _komunikaty(view)
    view.model.setData(view.model.index(0, _kolumna(view, "TELESCOP")), "Żuraw")
    assert view._pending_count() == 0
    if lang == "en":
        assert msg[-1].startswith("Cell TELESCOP - not staged: the value of card TELESCOP has "
                                  "the character 'Ż'"), msg[-1]
        assert _bez_polskiego(msg[-1].replace("Ż", "")), msg[-1]
    else:
        assert msg[-1].startswith("Komórka TELESCOP - bez zmiany: wartość karty TELESCOP ma znak")
    view.close()
    con.close()


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_podglad_szuflady_mowi_o_sumie_w_jezyku_UI(qapp, tmp_path, jezyk, lang):
    """AR-166: szuflada Zbiorów zapisywała FITS z sumą drogą atomową (suma niezgodna). Podgląd makra
    pokazuje go jako pominięty z powodem rdzenia w języku UI, staging go nie bierze, edycja komórki
    odmawia tym samym zdaniem. Falsyfikator: zdejmij bramkę sumy z `run_macro` → wpis w szufladzie."""
    from horreum import card_rules
    from horreum.gui.wb_worker import tekst_powodu
    jezyk(lang)
    view, con, p = _widok_nad(qapp, tmp_path, suma=True)
    przed = p.read_bytes()
    tip = _podglad_makra(view, "TELESCOP", "EQ6")
    zdanie = tekst_powodu(card_rules.BRAMKA_SUMY)
    assert tip == i18n.t("grid.preview.skipped_tip", reason=zdanie), tip
    assert zdanie == i18n.t("objchg.item.fits_checksum")
    view.macro_bar._emit_stage()
    assert view._pending_count() == 0
    msg = _komunikaty(view)
    view.model.setData(view.model.index(0, _kolumna(view, "TELESCOP")), "EQ8")
    assert msg[-1] == i18n.t("grid.cell.refused", kw="TELESCOP", reason=zdanie), msg[-1]
    assert view._pending_count() == 0 and p.read_bytes() == przed
    view.close()
    con.close()


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_popraw_optyke_mowi_odmowe_w_jezyku_UI(qapp, tmp_path, jezyk, lang, monkeypatch):
    """AR-167: „Popraw f/ w plikach…” idzie drogą edycji komórki - odmowa (tu: FITS z sumą) w zdaniu
    gestu w języku UI. Falsyfikator: `grid._on_fix_optics` bez `tekst_powodu` → polski powód w EN."""
    from horreum import card_rules
    from horreum.gui import queries as q
    from horreum.gui.wb_worker import tekst_powodu
    jezyk(lang)
    view, con, _p = _widok_nad(qapp, tmp_path, suma=True)
    fid = con.execute("SELECT id FROM frame").fetchone()[0]
    monkeypatch.setattr(q, "optics_fix_targets", lambda con_, ids: [(fid, 7.5, None, None)])
    view.table.selectRow(0)
    msg = _komunikaty(view)
    view._on_fix_optics()
    oczek = i18n.t("grid.optics.skipped",
                   reasons=f"{tekst_powodu(card_rules.BRAMKA_SUMY)} (1)")
    assert msg[-1].endswith(oczek), msg[-1]
    if lang == "en":
        assert _bez_polskiego(msg[-1]), msg[-1]
    view.close()
    con.close()


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_odmowa_dostepu_w_oknach_mowi_w_jezyku_UI_a_system_w_podpowiedzi(jezyk, lang):
    """AR-168: błąd systemu klasą w zdaniu okna kart (cały powód i zagnieżdżony) mówi frazą z numerem
    w języku UI; surowy tekst systemu (w języku systemu) schodzi do podpowiedzi - wspólnej
    `podpowiedz_kart` (okna kart i szuflada) i wiersza „Zmień obiekt…” (`status_pozycji`).
    Falsyfikator: `podpowiedz_kart` bez `podpowiedz_systemu` → brak wiersza systemu."""
    from horreum.gui.wb_worker import podpowiedz_kart, status_pozycji, zdanie_commitu_kart
    jezyk(lang)
    exc = OSError(None, "Odmowa dostępu", r"X:\L\a.fits", 5)
    caly = writeback._blad_systemu(exc)
    zagniezdzony = writeback._backup_nie_powstal(exc)
    surowy = r"PermissionError: [WinError 5] Odmowa dostępu: 'X:\L\a.fits'"   # bez `repr` ścieżki
    for powod in (caly, zagniezdzony):
        res = writeback.CommitResult("r", None, [], [], [writeback.FileResult(1, "X:/L/a.fits",
                                                                              "failed", powod)], [])
        zdanie, _ = zdanie_commitu_kart(res, "path.cards_applied")
        tip = podpowiedz_kart(res)
        assert i18n.t("objchg.item.os_denied", os_code="WinError 5") in zdanie, zdanie
        assert tip == i18n.t("wb.os_detail_tip", detail=surowy), tip
        _status, tip_wiersza = status_pozycji(i18n.t("objchg.st.failed"), powod)
        assert tip_wiersza.endswith("\n" + i18n.t("wb.os_detail_tip", detail=surowy)), tip_wiersza
        if lang == "en":
            assert _bez_polskiego(zdanie), zdanie


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_ogon_przerwanego_cofniecia_mowi_reszte_z_rdzenia(jezyk, lang):
    """AR-176 pkt 4: zdanie przerwanego cofnięcia mówi prawdę rdzenia (`UndoResult.remaining`) i NIE
    obiecuje wyniku: N bez dowodu zakończenia - „N nieprzetworzonych plików wymaga sprawdzenia;
    „Cofnij” ponowi próbę”; zero - „pozostałe pliki nie wymagają cofnięcia”; brak wiedzy (`None`,
    cofnięcie Nazw) - „„Cofnij” ponowi próbę dla pozostałych plików”. „Cofnij” zostaje przy każdym
    przerwaniu. Odmiana 1/2/5/12/22. Falsyfikator: `ogon_cofniecia` bez `remaining` → zdanie bez
    liczby przy 2 i przy zerze."""
    from horreum.gui.wb_worker import ogon_cofniecia
    jezyk(lang)

    def _ogon(remaining):
        return ogon_cofniecia(writeback.UndoResult(1, [], [], [], cancelled=True,
                                                   remaining=remaining), "Cofnij")
    zero, ponow_zero = _ogon(0)
    assert zero.endswith(i18n.t("wb.undo_cancelled_done")) and ponow_zero, zero
    dwa, ponow = _ogon(2)
    assert dwa.endswith(i18n.t_plural("wb.undo_cancelled_check", 2, undo="Cofnij")) and ponow, dwa
    brak, _ = _ogon(None)
    assert brak.endswith(i18n.t("wb.undo_cancelled", undo="Cofnij")), brak
    for zdanie in (zero, dwa, brak):                  # żadnej obietnicy wyniku
        assert "dokończy" not in zdanie and "finishes" not in zdanie, zdanie
    pocz = {"pl": " · cofnięcie przerwano na żądanie - ", "en": " · undo stopped on request - "}[lang]
    kon = {"pl": "; „Cofnij” ponowi próbę", "en": "; “Cofnij” retries"}[lang]
    oczek = {"pl": ["1 nieprzetworzony plik wymaga", "2 nieprzetworzone pliki wymagają",
                    "5 nieprzetworzonych plików wymaga", "12 nieprzetworzonych plików wymaga",
                    "22 nieprzetworzone pliki wymagają"],
             "en": ["1 unprocessed file needs", "2 unprocessed files need",
                    "5 unprocessed files need", "12 unprocessed files need",
                    "22 unprocessed files need"]}[lang]
    sprawdzenie = {"pl": " sprawdzenia", "en": " checking"}[lang]
    assert [i18n.t_plural("wb.undo_cancelled_check", n, undo="Cofnij") for n in (1, 2, 5, 12, 22)] \
        == [pocz + o + sprawdzenie + kon for o in oczek]


# Zapadka powodów w zdaniach GUI (AR-167): parametr `reason=`/`reasons=` w `i18n.t`/`t_plural` idzie
# przez `tekst_powodu`/`czytelny_powod` albo jest tekstem z katalogu. Znane wyjątki - jawnie,
# z kategorią; nowy surowy przypadek = czerwień, naprawiony wyjątek schodzi z listy.
_ZNANE_SUROWE = {
    ("app.py", "_on_save", "reason", "err"): "`plan_kart_naprawy`/`_validate_object_value`: zdania "
                                             "katalogu, reguła karty przez `tekst_powodu`",
    ("app.py", "_sync_preview", "reason", "err"): "jak wyżej (`plan_kart_naprawy`)",
    ("app.py", "_build_ui", "reason", "s['reason']"): "suma per folder - `tekst_powodu` przy "
                                                     "`_split_rows`",
    ("app.py", "_copy_reason", "reason", "diagnoza"): "diagnoza odczytu kopii (skan), nie zapis",
    ("app.py", "zdanie_cofniecia_dopisania", "reason", "powod(wynik.refusal)"): "funkcja lokalna "
                                                                                "- zdanie katalogu",
    ("app.py", "_open_path", "reason", "str(exc) or type(exc).__name__"): "otwarcie bazy, nie zapis",
    ("grid.py", "_on_fix_optics", "reasons",
     "'; '.join((f'{p} ({n})' for p, n in sorted(odmowy.items(), key=lambda pn: -pn[1])))"):
        "klucze odmów przez `tekst_powodu`/katalog wyżej",
    ("grid.py", "_policz_rodowod_kalibracji", "reason", "powod"): "zdanie etapu (katalog)",
    ("grid.py", "_on_lineage_offset", "reason", "powod"): "zdanie etapu (katalog)",
    ("pipeline.py", "_review_line", "reasons", "powody"): "zdania katalogu",
    ("pipeline.py", "_format_presence", "reason", "powod"): "zdania katalogu",
    ("pipeline.py", "_on_source_unreachable", "reason", "powod"): "zdanie katalogu",
    ("planner_model.py", "header_notes", "reason", "rig.reason"): "planer, nie zapis",
}
_OPAKOWANIA = {"tekst_powodu", "czytelny_powod"}


def _surowe_powody_gui():
    """`{(plik, funkcja, parametr, wyrażenie)}` parametrów `reason`/`reasons` w `i18n.t`/`t_plural`
    modułów `horreum/gui`, których wyrażenie nie jest opakowaniem powodu ani wywołaniem katalogu."""
    import ast
    from pathlib import Path
    import horreum.gui as gui
    wynik = set()
    for plik in sorted(Path(gui.__file__).parent.glob("*.py")):
        drzewo = ast.parse(plik.read_text(encoding="utf-8"))
        rodzic = {d: n for n in ast.walk(drzewo) for d in ast.iter_child_nodes(n)}

        def _funkcja(w):
            while w in rodzic:
                w = rodzic[w]
                if isinstance(w, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    return w.name
            return None
        for w in ast.walk(drzewo):
            if not (isinstance(w, ast.Call) and isinstance(w.func, ast.Attribute)
                    and w.func.attr in ("t", "t_plural") and isinstance(w.func.value, ast.Name)
                    and w.func.value.id == "i18n"):
                continue
            for k in w.keywords:
                if k.arg not in ("reason", "reasons"):
                    continue
                v = k.value
                if isinstance(v, ast.Call):
                    nazwa = v.func.attr if isinstance(v.func, ast.Attribute) else getattr(
                        v.func, "id", None)
                    if nazwa in _OPAKOWANIA or nazwa in ("t", "t_plural"):
                        continue
                wynik.add((plik.name, _funkcja(w), k.arg, ast.unparse(v)))
    return wynik


def test_zapadka_powodow_w_zdaniach_GUI():
    """AR-167 (zapadka): każdy parametr `reason=`/`reasons=` zdania GUI mówi przez `tekst_powodu`/
    `czytelny_powod` albo zdaniem katalogu - wyjątki z listy `_ZNANE_SUROWE` z kategorią. Nowe surowe
    miejsce = czerwień (powód z kodem mówiłby po polsku w UI EN), naprawiony wyjątek musi zejść
    z listy. Falsyfikator: `grid._on_cell_edit` z `reason=powod` → nowy wpis spoza listy."""
    znalezione = _surowe_powody_gui()
    nowe = znalezione - set(_ZNANE_SUROWE)
    stare = set(_ZNANE_SUROWE) - znalezione
    assert not nowe, f"surowy powód w zdaniu GUI: {sorted(nowe)}"
    assert not stare, f"wyjątek już naprawiony - zdejmij z listy: {sorted(stare)}"


def _cofniecie_z_odmowa_dostepu():
    """Wynik cofnięcia z błędem systemu klasą (`os_denied`) i surowy tekst jego podpowiedzi."""
    exc = OSError(None, "Odmowa dostępu", r"X:\L\a.fits", 5)
    res = writeback.UndoResult(1, [], [], [writeback.FileResult(1, "X:/L/a.fits", "failed",
                                                                writeback._blad_systemu(exc))])
    return res, i18n.t("wb.os_detail_tip",
                       detail=r"PermissionError: [WinError 5] Odmowa dostępu: 'X:\L\a.fits'")


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_okna_kart_po_cofnieciu_niosa_szczegol_systemu(qapp, tmp_path, jezyk, lang):
    """AR-168: oba okna kart po cofnięciu z błędem systemu zostawiają w podpowiedzi zdania surowy
    tekst systemu (dawniej czyściły ją na ślepo); zdanie w języku UI. Falsyfikator: `_after_undo`
    z `setToolTip("")` → pusta podpowiedź."""
    from horreum.gui.app import ConfirmPathObjectsDialog
    from horreum.gui import queries
    from horreum import resolver
    from test_gui_object_change import _lighty, _okno_naprawy
    jezyk(lang)
    con = db.open_db(str(tmp_path / "k.db"))
    _lighty(tmp_path / "ASTRO_", con, "NGC7635", 1, baza=7)
    res, tip = _cofniecie_z_odmowa_dostepu()
    naprawa = _okno_naprawy(con)
    sciezka = ConfirmPathObjectsDialog(con, proposals=resolver.path_proposals(con),
                                       now_fn=lambda: NOW, db_path=queries.db_path_of(con))
    for dlg in (naprawa, sciezka):
        dlg._after_undo("undo", res)
        assert dlg.status.toolTip() == tip, (type(dlg).__name__, dlg.status.toolTip())
        zdanie = dlg.status.text()
        assert i18n.t("objchg.item.os_denied", os_code="WinError 5") in zdanie, zdanie
        if lang == "en":
            assert _bez_polskiego(zdanie), zdanie
        dlg.reject()
    con.close()


@pytest.mark.parametrize("ogon", ["_after_undo", "_after_undo_rename"])
def test_szuflada_po_cofnieciu_niesie_szczegol_systemu(en, widok, ogon):
    """AR-168: szuflada Zbiorów po cofnięciu kart i Nazw - zdanie w języku UI, a surowy tekst
    systemu w podpowiedzi wyniku (pełne zdanie + wiersz systemu). Falsyfikator: ogon bez
    `podpowiedz_systemu` → podpowiedź równa samemu zdaniu."""
    view, _con, _p = widok
    view._ensure_undo_button()
    res, tip = _cofniecie_z_odmowa_dostepu()
    getattr(view, ogon)(ogon, res)
    tekst = view.drawer.result.text()
    assert "access to the file denied (WinError 5)" in tekst and _bez_polskiego(tekst), tekst
    assert view.drawer.result.toolTip() == tekst + "\n" + tip, view.drawer.result.toolTip()


def test_awaria_calej_operacji_mowi_bledem_systemu_w_jezyku_UI(en, tmp_path, monkeypatch):
    """AR-168: wyjątek całej operacji zapisu (`WritebackWorker.run`) nie idzie już surowym
    `PermissionError: [WinError 5] Odmowa dostępu.` - zdanie klasy w języku UI; wyjątek spoza
    klas zostaje tekstem `Typ: opis`. Sygnał niesie trzy argumenty (op, zdanie, podpowiedź ze
    szczegółem systemu, AR-185) - odbiorca przyjmuje wszystkie trzy, asercja dotyczy zdania.
    Falsyfikator: `run` z `f"{type(exc).__name__}: {exc}"` → polski komunikat systemu w EN."""
    from horreum.gui.wb_worker import WritebackWorker
    sciezka = str(tmp_path / "w.db")
    db.open_db(sciezka).close()
    bledy = []
    for wyjatek, oczek in ((OSError(None, "Odmowa dostępu.", None, 5),
                            "access to the file denied (WinError 5)"),
                           (RuntimeError("w połowie"), "RuntimeError: w połowie")):
        def _pada(c, t, now, pr, sc, wyjatek=wyjatek):
            raise wyjatek
        monkeypatch.setitem(WritebackWorker._OPS, "commit", _pada)
        w = WritebackWorker(sciezka, "commit", "R", now_fn=lambda: NOW)
        w.failed.connect(lambda op, msg, podpowiedz: bledy.append(msg))
        w.run()
        assert bledy[-1] == oczek, bledy


# ============================ AR-181: powody bramek celu i makra w oknach kart i w gridzie

from test_gui_app_object import _okno_sciezki, sciezka_karty  # noqa: E402,F401 - fikstura okna


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_podglad_makra_brak_karty_w_jezyku_UI(qapp, tmp_path, jezyk, lang):
    """Podgląd makra `set` na karcie, której plik nie ma (droga 7 XISF bez `TELESCOP` w archiwum):
    podpowiedź komórki „(pominięto)” mówi powód w języku UI - PL znak w znak jak zdanie makra.
    Falsyfikator: `_evaluate_change` z gołym f-stringiem → „brak karty…” w EN."""
    jezyk(lang)
    view, con, _p = _widok_nad(qapp, tmp_path)
    tip = _podglad_makra(view, "OBSERVER", "Zdzin")
    zdanie = {"pl": "brak karty 'OBSERVER' do modyfikacji (uzyj add)",
              "en": "no card 'OBSERVER' to modify (use add)"}[lang]
    assert tip == i18n.t("grid.preview.skipped_tip", reason=zdanie), tip
    view.close()
    con.close()


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_Napraw_naglowek_lista_pominietych_mowi_bramke_celu_w_jezyku_UI(qapp, tmp_path, jezyk,
                                                                       lang):
    """„Napraw nagłówek…”: klatka z dwiema obecnymi kopiami stoi na liście pominiętych z powodem
    bramki celu w języku UI - kluczem katalogu `repair.skip.item`, nie f-stringiem z pauzą.
    Falsyfikator: element listy z gołym `reason` → „wiele obecnych kopii…” w EN."""
    import os as _os
    from test_gui_object_change import _lighty, _okno_naprawy
    from horreum import repo
    from horreum.gui import queries
    jezyk(lang)
    con = db.open_db(str(tmp_path / "n.db"))
    (p,) = _lighty(tmp_path / "ASTRO_", con, "NGC7635", 1, baza=5)
    fid = con.execute("SELECT frame_id FROM location WHERE path = ?", (str(p),)).fetchone()[0]
    repo.add_location(con, frame_id=fid, volume="V", header_hash="h-kopia", now=NOW,
                      path=str(tmp_path / "kopia" / p.name))
    dlg = _okno_naprawy(con)
    (pozycja,) = [dlg.skipped_list.item(i).text() for i in range(dlg.skipped_list.count())]
    plik = queries.nameless_frames(con)[0]["path"]
    powod = {"pl": "wiele obecnych kopii (2) -- writeback poza v1 (D-W1)",
             "en": "several present copies (2) - writeback outside v1 (D-W1)"}[lang]
    assert pozycja == f"{_os.path.basename(plik)} - {powod}", pozycja
    assert "—" not in pozycja                        # pauza dawnego f-stringu
    dlg.reject()
    con.close()


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_Napraw_naglowek_wszystko_pominiete_mowi_powod_makra_w_jezyku_UI(qapp, tmp_path, jezyk,
                                                                        lang):
    """„Napraw nagłówek…”: grupa, której każda klatka ma już kartę `OBJECT` - prawdziwy klik
    „Zapisz karty” kończy się zdaniem „Nic do zapisu” z powodem makra w języku UI, zero zapisu.
    Falsyfikator: `_on_save` z gołym `skipped[0][1]` → „karta 'OBJECT' juz istnieje…” w EN."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from test_gui_object_change import _niebo
    from horreum.gui import queries
    from horreum.gui.app import RepairHeaderDialog
    jezyk(lang)
    con = db.open_db(str(tmp_path / "w.db"))
    fid = _niebo(con, tmp_path / "ASTRO_", r"LIGHTS\NGC7635\cam\a.fits", obj="xx", ra=None)
    path = con.execute("SELECT path FROM location WHERE frame_id = ?", (fid,)).fetchone()[0]
    przed = open(path, "rb").read()
    dlg = RepairHeaderDialog(con, rows=[{"frame_id": fid, "path": path, "kind": "light"}],
                             db_path=queries.db_path_of(con), now_fn=lambda: NOW)
    dlg._runner.async_ok = False
    dlg.show()
    (g,) = dlg._groups
    if not g["check"].isChecked():
        QTest.mouseClick(g["check"], Qt.LeftButton)
    g["edit"].clear()
    QTest.keyClicks(g["edit"], "NGC 7635")
    QTest.mouseClick(dlg.save_btn, Qt.LeftButton)
    powod = {"pl": "karta 'OBJECT' juz istnieje (uzyj set)",
             "en": "card 'OBJECT' already exists (use set)"}[lang]
    assert dlg.error.text() == i18n.t("repair.err.all_skipped", reason=powod), dlg.error.text()
    assert open(path, "rb").read() == przed
    dlg.reject()
    con.close()


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_Zatwierdz_ze_sciezki_lista_bez_karty_mowi_w_jezyku_UI(sciezka_karty, jezyk, lang):
    """„Zatwierdź ze ścieżki…”: lista „bez karty w pliku” mówi powody bramek celu i makra w języku
    UI (karta pusta już jest, dwie obecne kopie, RAW). Falsyfikator: `reason=powod` bez
    `tekst_powodu` → polska proza makra w EN."""
    jezyk(lang)
    v, con, _pliki, _fid = sciezka_karty
    dlg = _okno_sciezki(v, con)
    try:
        pozycje = sorted(dlg.cards_skipped.item(i).text() for i in range(dlg.cards_skipped.count()))
        powody = {"pl": ["karta 'OBJECT' juz istnieje (uzyj set)",
                         "plik RAW (DSLR) -- Horreum go NIE zapisuje (read-only)",
                         "wiele obecnych kopii (2) -- writeback poza v1 (D-W1)"],
                  "en": ["RAW file (DSLR) - Horreum does NOT write it (read-only)",
                         "card 'OBJECT' already exists (use set)",
                         "several present copies (2) - writeback outside v1 (D-W1)"]}[lang]
        assert pozycje == sorted(i18n.t("path.cards_skipped_item", reason=p, n=1)
                                 for p in powody), pozycje
    finally:
        dlg.reject()


def test_walidacja_nazwy_mowi_naruszenie_nazwy_karty_w_jezyku_UI(en, monkeypatch):
    """`_validate_object_value`: naruszenie NAZWY karty (dla stałej `OBJECT` nieosiągalne, ale
    reguła ma kod) mówi w języku UI, nie surową prozą. Falsyfikator: `return None,
    naruszenie.reason` → polskie zdanie reguły w EN."""
    from horreum import card_rules, writeback
    from horreum.gui.app import _validate_object_value
    naruszenie = card_rules.card_violation("OBJECTNAM", "v", new_card=True)
    monkeypatch.setattr(writeback, "card_violation", lambda *a, **k: naruszenie)
    assert _validate_object_value(None, "M 42") == (
        None, "card name 'OBJECTNAM' breaks the FITS 4.0 rules - up to 8 characters from A-Z, "
              "0-9, '_' and '-'")


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_pusta_komorka_karty_mowi_w_jezyku_UI(qapp, tmp_path, jezyk, lang):
    """Podpowiedź komórki keyworda, której plik tej klatki nie ma: z katalogu (`grid.cell.
    no_card_tip`) - PL „brak karty” znak w znak, EN „no card”. Falsyfikator: literał PL
    w `grid_model._kw_cell`."""
    import numpy as np
    from astropy.io import fits
    from PySide6.QtCore import Qt
    from horreum.gui.grid import FramesView
    jezyk(lang)
    con = db.open_db(str(tmp_path / "c.db"))
    for nazwa, obserwator in (("a.fits", "Zdzin"), ("b.fits", None)):
        hdu = fits.PrimaryHDU(data=np.zeros((4, 4), dtype=np.int16) + (0 if obserwator else 1))
        hdu.header["IMAGETYP"] = "Light"
        if obserwator:
            hdu.header["OBSERVER"] = obserwator
        hdu.writeto(str(tmp_path / nazwa))
        scan.ingest_record(con, scan.scan_file(str(tmp_path / nazwa)), volume="V", now=NOW,
                           summary=scan.ScanSummary())
    view = FramesView(con, now_fn=lambda: NOW)
    m, kol = view.model, _kolumna(view, "OBSERVER")
    tipy = {m.data(m.index(r, kol), Qt.ToolTipRole) for r in range(m.rowCount())}
    assert {"pl": "brak karty", "en": "no card"}[lang] in tipy, tipy
    view.close()
    con.close()


# Zapadka POMOCNICZA f-stringów w `gui/` (AR-181): pole f-stringu, którego wyrażenie wygląda na
# powód, idzie przez `tekst_powodu`/`czytelny_powod` albo katalog. OGRANICZENIE: powód rozpoznany
# po NAZWIE (`reason`/`powod`, `.reason`/`.refusal`, indeks `[1]` par `skipped`) - ten sam powód
# pod inną nazwą przejdzie, więc to alarm, nie dowód; kompletność czterech ujść okien kart pinują
# testy zachowania wyżej. f-string będący KLUCZEM katalogu (pierwszy argument `i18n.t`) - poza.
_ZNANE_FSTRINGI = {
    ("grid_lineage.py", "_calibration_item_text", "powod"): "zdanie katalogu (`grid.lin.cal.gap.*`)",
}


def _fstringi_z_powodem_gui():
    """`{(plik, funkcja, wyrażenie pola)}` f-stringów `horreum/gui/*.py` z polem-powodem bez
    opakowania (`tekst_powodu`, `czytelny_powod`, `i18n.t`/`t_plural`)."""
    import ast
    from pathlib import Path
    import horreum.gui as gui

    def _powod(v):
        if isinstance(v, ast.Name):
            return "reason" in v.id.lower() or "powod" in v.id.lower()
        if isinstance(v, ast.Attribute):
            return v.attr in ("reason", "powod", "refusal")
        if isinstance(v, ast.Subscript) and isinstance(v.slice, ast.Constant):
            k = v.slice.value
            if isinstance(k, str):
                return "reason" in k or "powod" in k
            return k == 1 and any(s in ast.unparse(v.value).lower() for s in ("skip", "pomin"))
        return False
    wynik = set()
    for plik in sorted(Path(gui.__file__).parent.glob("*.py")):
        drzewo = ast.parse(plik.read_text(encoding="utf-8"))
        rodzic = {d: n for n in ast.walk(drzewo) for d in ast.iter_child_nodes(n)}

        def _funkcja(w):
            while w in rodzic:
                w = rodzic[w]
                if isinstance(w, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    return w.name
            return None

        def _klucz_katalogu(w):
            r = rodzic.get(w)
            return (isinstance(r, ast.Call) and isinstance(r.func, ast.Attribute)
                    and r.func.attr in ("t", "t_plural") and bool(r.args) and r.args[0] is w)
        for w in ast.walk(drzewo):
            if not isinstance(w, ast.JoinedStr) or _klucz_katalogu(w):
                continue
            for c in w.values:
                if not isinstance(c, ast.FormattedValue):
                    continue
                v = c.value
                if isinstance(v, ast.Call):
                    nazwa = v.func.attr if isinstance(v.func, ast.Attribute) else getattr(
                        v.func, "id", None)
                    if nazwa in _OPAKOWANIA or nazwa in ("t", "t_plural"):
                        continue
                if _powod(v):
                    wynik.add((plik.name, _funkcja(w), ast.unparse(v)))
    return wynik


def test_zapadka_powodow_w_fstringach_GUI():
    """AR-181 (zapadka pomocnicza): f-string w `gui/` z polem-powodem bez opakowania = czerwień
    (lista pominiętych „Napraw nagłówek…” składała tak zdanie PL w UI EN); wyjątki z listy
    `_ZNANE_FSTRINGI` z kategorią, naprawiony schodzi z listy. Falsyfikator: element listy
    pominiętych z powrotem jako `f"{…} - {reason}"` → nowy wpis spoza listy."""
    znalezione = _fstringi_z_powodem_gui()
    nowe = znalezione - set(_ZNANE_FSTRINGI)
    stare = set(_ZNANE_FSTRINGI) - znalezione
    assert not nowe, f"surowy powód w f-stringu GUI: {sorted(nowe)}"
    assert not stare, f"wyjątek już naprawiony - zdejmij z listy: {sorted(stare)}"
