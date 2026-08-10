"""Powierzchnia osi SPRZĘTU wskazanej ręką (R1, #DR2) — kubełek „bez zestawu" + okno „Przypisz
zestaw…", sterowane realnym oknem Qt (offscreen) na bazie §8.

Do R1 ten kubełek był POŁOWĄ wiersza informacyjnego z notą „rozwiązywanie w przygotowaniu": ekran
zapowiadał userowi drogę, której nie było. Testy pilnują trzech rzeczy, których brak sprawiłby, że
powierzchnia znów obiecuje więcej, niż dowozi: (1) licznik == długość drążenia, (2) gest zapisuje
TĄ SAMĄ klingą co rdzeń i licznik po nim spada, (3) okno nie pozwala zapisać bez celu i bez
teleskopu.

`importorskip` na poziomie MODUŁU (PLAN_gui §4); `QT_QPA_PLATFORM=offscreen` PRZED importem Qt."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from horreum import db, repo, resolver
from horreum.gui import i18n, queries
from horreum.gui.app import ObjectAxisView
from horreum.gui.config_dialog import AssignConfigDialog

from fixture_s8 import seed_object_axis

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog

UROLE = 0x0100   # Qt.UserRole
# Liczba wyszła z etykiety do CZŁONU DRUGIEGO delegata (bramka pakietu 3a, zarzut 2):
# w członie pierwszym była elidowana bez drogi powrotu, odkąd lista kolejki straciła
# poziomy scrollbar.
SECONDARY = UROLE + 1
NOW = "2026-08-08T10:00:00+00:00"


@pytest.fixture(scope="session")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def view(qapp, tmp_path):
    con = db.open_db(str(tmp_path / "s8_cfg.db"))
    ids = seed_object_axis(con)
    v = ObjectAxisView(con)
    yield v, con, ids
    v.close()
    con.close()


def _wiersz_kubelka(v):
    for r in range(v.review.count()):
        if v.review.item(r).data(UROLE) == "config_review":
            return r, v.review.item(r)
    raise AssertionError("kolejka nie ma kubełka osi sprzętu")


# --- read-model: licznik i lista mówią JEDNO ---

def test_licznik_kubelka_jest_dlugoscia_drazenia(view):
    """Ta równość jest tu bramką, nie ozdobą: kubełek, którego lista pokazuje inną liczbę niż
    wiersz, na którym user kliknął, kłamie o zakresie gestu. Predykat ma dwóch nosicieli
    (`resolver.review_state` po stronie rdzenia, read-model po stronie widoku) i to jest świadome —
    ale wtedy równość musi być PINOWANA (ta sama figura, co kotwica `nameless_raw_lights`)."""
    v, con, ids = view
    assert len(queries.config_review_frames(con)) == resolver.review_state(con).no_config


def test_grupy_sa_projekcja_tej_samej_listy(view):
    """Grupy to PROJEKCJA drążenia (folder × kamera), nie drugi predykat — suma klatek w grupach
    musi się równać liście, inaczej okno pokazuje inny świat niż panel pod nim."""
    v, con, ids = view
    klatki = queries.config_review_frames(con)
    grupy = queries.config_review_groups(con)
    assert sum(g["n_frames"] for g in grupy) == len(klatki)
    assert sorted(fid for g in grupy for fid in g["frame_ids"]) == \
        sorted(r["frame_id"] for r in klatki)


def test_kamera_jest_czescia_klucza_grupy(view):
    """D-DR-3: dwa korpusy w JEDNYM folderze to DWA zestawy, bo `config` niesie dokładnie jedną
    kamerę (`UNIQUE(telescope_id, camera_id)`). Grupa po samym folderze obiecywałaby jeden gest
    tam, gdzie muszą powstać dwa — zmierzone na archiwum: 2 z 36 folderów mają dwa korpusy."""
    v, con, ids = view
    folder = r"R:\ASTRO_\LIGHTS\NGC5194\portable"
    for sha, cam in (("sha-korpus-1", ids["cam1"]), ("sha-korpus-2", ids["cam2"])):
        fid, _ = repo.upsert_frame(con, sha1_data=sha, kind="light", filetype="raw",
                                   camera_id=cam, now=NOW)
        repo.record_header(con, frame_id=fid, raw_json="{}", now=NOW)
        repo.add_location(con, frame_id=fid, volume="TESTVOL",
                          path=os.path.join(folder, f"{sha}.dng"), now=NOW)

    w_folderze = [g for g in queries.config_review_groups(con) if g["folder"] == folder]
    assert len(w_folderze) == 2
    assert {g["camera_id"] for g in w_folderze} == {ids["cam1"], ids["cam2"]}
    assert all(g["n_frames"] == 1 for g in w_folderze)


# --- powierzchnia: wiersz prowadzi, przycisk tłumaczy się sam ---

def test_kubelek_drazy_do_klatek(view):
    v, con, ids = view
    r, _ = _wiersz_kubelka(v)
    v.review.setCurrentRow(r)
    assert v.frames.rowCount() == len(queries.config_review_frames(con))
    assert i18n.t("object.frames_config_review", n=v.frames.rowCount()) == v.frames_label.text()


def test_przycisk_zestawu_zapala_sie_TYLKO_na_swoim_kubelku(view):
    """Szczery disabled: UI nie kłamie. Przycisk osi SPRZĘTU nad kubełkiem osi OBIEKTU byłby
    obietnicą zapisu, którego ta akcja nie zrobi."""
    v, con, ids = view
    r, _ = _wiersz_kubelka(v)
    v.review.setCurrentRow(r)
    assert v.set_config_btn.isEnabled()
    assert v.set_config_btn.toolTip() == i18n.t("object.set_config_tip")

    v.review.clearSelection()
    v._sync_assign_enabled()
    assert not v.set_config_btn.isEnabled()
    assert v.set_config_btn.toolTip() == i18n.t("object.set_config_tip_pick")


def test_pusty_kubelek_nie_prowadzi_nigdzie(view, tmp_path):
    """Jedna reguła dla wszystkich kubełków (wiz T2 N6): zero nie ma dokąd prowadzić, więc wiersz
    jest informacyjny i mówi, KIEDY się zapali."""
    v, con, ids = view
    tel = con.execute("SELECT id FROM telescope LIMIT 1").fetchone()[0]
    repo.user_assign_config(con, frame_ids=[r["frame_id"] for r in queries.config_review_frames(con)
                                            if r["camera_id"] is not None],
                            telescope_id=tel, now="2026-08-08T10:00:00+00:00")
    v.refresh()

    wiersze = [(v.review.item(i).text(), v.review.item(i).data(UROLE))
               for i in range(v.review.count())]
    puste = [(t, tag) for t, tag in wiersze if t.startswith("— bez zestawu")]
    assert puste and all(tag is None for _, tag in puste)


# --- okno: dwa jawne wybory, zero zapisu bez nich ---

def test_okno_wymaga_celu_i_teleskopu(view):
    """Dwa jawne wybory: cel i teleskop. Bez któregokolwiek akcja nie ma prawa być klikalna."""
    v, con, ids = view
    dlg = AssignConfigDialog(con, groups=queries.config_review_groups(con))
    dlg.combo.setCurrentIndex(1)                     # jawne wskazanie teleskopu
    for i in range(dlg.items.count()):               # jawne wskazanie celu
        dlg.items.item(i).setCheckState(Qt.Checked)
    assert dlg.accept_btn.isEnabled()

    dlg.combo.setCurrentIndex(0)                     # odbierz teleskop
    assert not dlg.accept_btn.isEnabled()
    dlg.combo.setCurrentIndex(1)
    for i in range(dlg.items.count()):               # odbierz cel
        dlg.items.item(i).setCheckState(Qt.Unchecked)
    assert not dlg.accept_btn.isEnabled()
    dlg.close()


def test_przelacznik_calosci_dziala_w_OBIE_strony(view):
    """FIRSTHAND ZDZINIA 0808: „otwiera się okno i kilkadziesiąt wierszy zaznaczonych — muszę
    wszystkie odklikać i jeden zostawić". Przy 39 grupach to 38 kliknięć za gest dotyczący jednego
    folderu.

    Domyślny stan ZOSTAJE zaznaczony (przypadek masowy: jedna sesja = jeden teleskop); dochodzi
    droga na skróty w obie strony. Test jedzie w OBIE, bo przełącznik, który tylko odznacza,
    zamienia jeden problem na drugi."""
    v, con, ids = view
    grupy = queries.config_review_groups(con)
    dlg = AssignConfigDialog(con, groups=grupy)

    dlg.check_all.setCheckState(Qt.Unchecked)
    dlg._on_check_all()
    assert all(dlg.items.item(i).checkState() == Qt.Unchecked for i in range(dlg.items.count()))
    assert not dlg.accept_btn.isEnabled(), "bez celu akcja nie ma prawa być klikalna"

    dlg.check_all.setCheckState(Qt.Checked)
    dlg._on_check_all()
    assert all(dlg.items.item(i).checkState() == Qt.Checked for i in range(dlg.items.count()))
    dlg.close()


def test_przelacznik_calosci_odbija_stan_listy(view):
    """Przełącznik jest LUSTREM listy, nie własnym stanem: odznaczenie jednego wiersza z zaznaczonej
    całości ma go wprowadzić w stan pośredni. Bez tego pokazywałby „wszystkie" nad listą, w której
    jednego brakuje — czyli kłamałby o tym, co zrobi zapis."""
    v, con, ids = view
    # DWIE grupy, bo stan pośredni z definicji nie istnieje przy jednej — fikstura osi ma dokładnie
    # jedną, więc test na niej mierzyłby co innego, niż nazywa (zmierzone: `config_review_groups`
    # oddaje 1 wiersz). Dialog czyta grupy jako mapy, więc podajemy je wprost.
    wzor = dict(queries.config_review_groups(con)[0])
    grupy = [dict(wzor, folder="A"), dict(wzor, folder="B")]
    dlg = AssignConfigDialog(con, groups=grupy)

    dlg.check_all.setCheckState(Qt.Checked)
    dlg._on_check_all()
    assert dlg.check_all.checkState() == Qt.Checked

    dlg.items.item(0).setCheckState(Qt.Unchecked)
    assert dlg.check_all.checkState() == Qt.PartiallyChecked

    dlg.items.item(1).setCheckState(Qt.Unchecked)
    assert dlg.check_all.checkState() == Qt.Unchecked, "pusta lista to NIE stan pośredni"
    dlg.close()


def test_grupa_bez_sciezki_i_bez_kamery_wchodzi_ODZNACZONA(view):
    """Bramka pakietu 3a, zarzut 3: grupa `folder=None` zbiera WSZYSTKIE klatki bez obecnej kopii
    z całego archiwum — łączy je brak ścieżki, a nie wspólny sprzęt. Domyślne zaznaczenie kazałoby
    jednym kliknięciem ostemplować jednym teleskopem zbiór, o którym nikt nic nie twierdzi. Ta sama
    reguła dla grupy bez kamery (klinga i tak ją odmówi). Liczba na przycisku ma to odbijać."""
    v, con, ids = view
    grupy = queries.config_review_groups(con)
    dlg = AssignConfigDialog(con, groups=grupy)
    for i, g in enumerate(grupy):
        slaba = g["folder"] is None or g["camera_id"] is None
        assert (dlg.items.item(i).checkState() == Qt.Unchecked) == slaba, g["folder"]
    mocne = sum(g["n_frames"] for g in grupy
                if g["camera_id"] is not None and g["folder"] is not None)
    assert dlg.accept_btn.text() == i18n.t("cfg.assign_btn", n=mocne)
    dlg.close()


def test_gest_zapisuje_i_licznik_spada(view, monkeypatch):
    """Pełna droga: kubełek → okno → klinga → licznik. Dialog podmieniony seamem (wzorzec testów
    „Przypisz obiekt…"), bo sprawdzamy GLUE, nie modalność Qt."""
    v, con, ids = view
    r, _ = _wiersz_kubelka(v)
    v.review.setCurrentRow(r)
    przed = resolver.review_state(con).no_config
    tel = con.execute("SELECT id, telescop_canon FROM telescope LIMIT 1").fetchone()
    cel = [g["frame_ids"] for g in queries.config_review_groups(con)
           if g["camera_id"] is not None][0]

    class _Fake:
        def __init__(self, *a, **k):
            self.selected = (tel["id"], tel["telescop_canon"], cel)

        def exec(self):
            return QDialog.Accepted

    monkeypatch.setattr("horreum.gui.app.AssignConfigDialog", _Fake)
    msgs = []
    v.status_message.connect(msgs.append)
    v._on_set_config()

    assert resolver.review_state(con).no_config == przed - len(cel)
    for fid in cel:
        row = con.execute("SELECT config_id, config_source FROM frame WHERE id=?",
                          (fid,)).fetchone()
        assert row["config_id"] is not None and row["config_source"] == "user"
    assert msgs and str(len(cel)) in msgs[-1] and tel["telescop_canon"] in msgs[-1]


def test_pomylka_reki_MA_DROGE_POWROTNA(view, monkeypatch):
    """Bramka pakietu 3a, zarzut BLOKUJĄCY: po geście klatka wypada z kubełka (`config_id` już nie
    jest NULL), a automat jej nie tknie (guard lepkości) — bez drugiego wiersza pierwsza pomyłka
    ręki byłaby WIECZNA. Test przechodzi całą drogę: gest → wiersz „zestaw wskazany ręką" →
    ZMIANA na inny teleskop."""
    v, con, ids = view
    cel = [g["frame_ids"] for g in queries.config_review_groups(con)
           if g["camera_id"] is not None][0]
    tele = con.execute("SELECT id, telescop_canon FROM telescope ORDER BY id").fetchall()
    zly, dobry = tele[0], tele[1]
    repo.user_assign_config(con, frame_ids=cel, telescope_id=zly["id"], now=NOW)
    v.refresh()

    # 1. wiersz powrotny ISTNIEJE i prowadzi dalej
    wiersz = [(v.review.item(i).text(), v.review.item(i).data(SECONDARY))
              for i in range(v.review.count())
              if v.review.item(i).data(UROLE) == "config_by_hand"]
    assert wiersz and str(len(cel)) in wiersz[0][1]
    assert len(queries.config_by_hand_frames(con)) == len(cel)

    # 2. akcja zapala się nad NIM, a okno wchodzi w trybie ZMIANY (nic nie zaznaczone domyślnie)
    r = next(i for i in range(v.review.count()) if v.review.item(i).data(UROLE) == "config_by_hand")
    v.review.setCurrentRow(r)
    assert v.set_config_btn.isEnabled()
    assert v.set_config_btn.toolTip() == i18n.t("object.set_config_tip_change")
    dlg = AssignConfigDialog(con, groups=queries.config_by_hand_groups(con), change=True)
    assert all(dlg.items.item(i).checkState() == Qt.Unchecked for i in range(dlg.items.count()))
    dlg.close()

    # 3. ZMIANA przechodzi — z `overwrite`, więc klinga nie odmawia „zajęte"
    class _Fake:
        def __init__(self, *a, **k):
            self.selected = (dobry["id"], dobry["telescop_canon"], cel)

        def exec(self):
            return QDialog.Accepted

    monkeypatch.setattr("horreum.gui.app.AssignConfigDialog", _Fake)
    v._on_set_config()
    zestawy = {con.execute("SELECT config_id FROM frame WHERE id=?", (f,)).fetchone()[0]
               for f in cel}
    assert len(zestawy) == 1
    assert con.execute("SELECT telescope_id FROM config WHERE id=?",
                       (zestawy.pop(),)).fetchone()[0] == dobry["id"]


def test_gest_bez_grup_nie_otwiera_okna(view, monkeypatch):
    """Pusty kubełek → zdanie w pasku, ZERO okna. Cisza po kliknięciu byłaby nieodróżnialna
    od zapisu (F-2)."""
    v, con, ids = view
    tel = con.execute("SELECT id FROM telescope LIMIT 1").fetchone()[0]
    repo.user_assign_config(con, frame_ids=[r["frame_id"] for r in queries.config_review_frames(con)
                                            if r["camera_id"] is not None],
                            telescope_id=tel, now="2026-08-08T10:00:00+00:00")

    otwarte = []
    monkeypatch.setattr("horreum.gui.app.AssignConfigDialog",
                        lambda *a, **k: otwarte.append(1))
    msgs = []
    v.status_message.connect(msgs.append)
    v._on_set_config()
    assert not otwarte and msgs[-1] == i18n.t("cfg.err_nothing")


# --- R1-3: okno nie milczy o rodzaju, który odbiega od światła ---

def _klatka_w_folderze(con, ids, *, sha, kind, folder):
    """Klatka z nagłówkiem i kopią w podanym folderze — jednostką gestu jest folder × kamera."""
    fid, _ = repo.upsert_frame(con, sha1_data=sha, kind=kind, filetype="xisf",
                               camera_id=ids["cam1"], now=NOW)
    repo.record_header(con, frame_id=fid, raw_json="{}", now=NOW)
    repo.add_location(con, frame_id=fid, volume="TESTVOL",
                      path=os.path.join(folder, f"{sha}.xisf"), now=NOW)
    return fid


def test_grupa_niesie_rodzaj_ODBIEGAJACY_od_swiatla(view):
    """R1-3: kubełek sprzętu odsiewa WYŁĄCZNIE `NO_TELESCOPE_KINDS` (dark/bias), więc trafia do
    niego każdy inny rodzaj — dziś na archiwum jest to XISF-owy masterflat, którego `IMAGETYP` nie
    dał się zmapować (`kind='unknown'`, 1 z 423). Gest go PRZYJMIE i to jest w porządku (oś opisuje
    optykę, nie rodzaj klatki), ale grupa musi ten fakt NIEŚĆ — inaczej okno pokazuje folder
    z jedną klatką nieodróżnialny od RAW-a z lustrzanki.

    Rodzaj `light` jest domyślnym tłem kubełka, więc go nie wymieniamy: człon ma być SYGNAŁEM
    odchylenia, a nie etykietą na każdym wierszu."""
    v, con, ids = view
    folder = r"R:\ASTRO_\CALIBRATION\masters\flats\A7R3_105\OSC"
    _klatka_w_folderze(con, ids, sha="sha-unknown-1", kind="unknown", folder=folder)
    _klatka_w_folderze(con, ids, sha="sha-light-1", kind="light", folder=folder)

    grupa = next(g for g in queries.config_review_groups(con) if g["folder"] == folder)
    assert grupa["n_frames"] == 2
    assert grupa["other_kinds"] == [("unknown", 1)], "człon liczy odchylenia, nie całą grupę"

    czysty = r"R:\ASTRO_\LIGHTS\NGC7000\portable"
    _klatka_w_folderze(con, ids, sha="sha-light-2", kind="light", folder=czysty)
    swiatlo = next(g for g in queries.config_review_groups(con) if g["folder"] == czysty)
    assert swiatlo["other_kinds"] == [], "grupa z samych lightów nie ma o czym mówić"


def test_wiersz_okna_MOWI_o_rodzaju_i_MILCZY_przy_swietle(view):
    """Falsyfikator w tej samej parze: człon ma się pokazać dokładnie tam, gdzie jest odchylenie.
    Bez drugiej połowy test przeszedłby też dla członu doklejanego bezwarunkowo — a to zamieniłoby
    sygnał w szum na wszystkich 36 grupach archiwum."""
    v, con, ids = view
    folder = r"R:\ASTRO_\CALIBRATION\masters\flats\A7R3_105\OSC"
    _klatka_w_folderze(con, ids, sha="sha-unknown-1", kind="unknown", folder=folder)

    grupy = queries.config_review_groups(con)
    dlg = AssignConfigDialog(con, groups=grupy)
    czlon = i18n.t("cfg.item_kinds", kinds=i18n.t("cfg.kind_count", kind="unknown", n=1))
    for i, g in enumerate(grupy):
        tekst = dlg.items.item(i).text()
        assert (czlon in tekst) == (g["folder"] == folder), g["folder"]
    dlg.close()

# --- bramka pakietu 0810, zarzut 2: bliźniak odsiewa zastąpione tak samo jak jego para ---

def test_lista_od_reki_ODSIEWA_zastapione(view):
    """Para (`config_review_frames`) dostała warunek `superseded_by IS NULL` 0809, z powodem
    zmierzonym na sierocie 15958. Bliźniak go nie dostał - a `transfer_facts` kopiuje config na
    następczynię i NIE zeruje `config_source` poprzedniczki, więc wskazanie ręki niosą OBIE
    tożsamości.

    Bez tego warunku kubełek „zestaw wskazany ręką" liczy JEDEN plik dwa razy, a okno w trybie
    ZMIANY oferuje gest na tożsamości, której roboty przejęła już następczyni - zapis szedłby
    na martwą klatkę.

    Populacja na żywym archiwum: **0**. To tripwir, nie naprawa objawu - stąd falsyfikator
    w drugiej połowie testu, żeby nie był zielony z powodu pustej listy.

    Falsyfikator: zdejmij `AND f.superseded_by IS NULL` → pierwsza asercja czerwienieje."""
    v, con, ids = view
    tel = con.execute("SELECT id FROM telescope LIMIT 1").fetchone()[0]
    klatki = [r["frame_id"] for r in queries.config_review_frames(con) if r["camera_id"] is not None]
    repo.user_assign_config(con, frame_ids=klatki[:1], telescope_id=tel, now=NOW)
    assert [r["frame_id"] for r in queries.config_by_hand_frames(con)] == klatki[:1],         "gest nie wszedł - dalsza część testu mierzyłaby pustą listę"

    con.execute("UPDATE frame SET superseded_by = ? WHERE id = ?", (klatki[1], klatki[0]))
    con.commit()
    assert queries.config_by_hand_frames(con) == [],         "zastąpiona tożsamość dalej oferuje gest, choć jej robotę przejęła następczyni"
