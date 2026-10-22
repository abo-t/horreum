r"""Okno „Zmień obiekt…” i „Uzgodnij pliki…” - podgląd i wykonanie gestu zmiany obiektu RAZEM
z plikiem (AR-17 krok 3, decyzja `D-1011-5`).

JEDNO OKNO, TRZY WEJŚCIA, JEDEN SILNIK. „Zmień obiekt…” (Zbiory → Obiekt ▾) niesie cel
(`object_change.ObjectTarget`): baza dostaje nowy obiekt ręką, plik jedzie do folderu nowego
obiektu, a karta `OBJECT` dostaje jego formę. „Uzgodnij pliki…” (Porządki → perspektywa „Plik nie
zgadza się z obiektem”) idzie z `target=None`: obiekt w bazie zostaje, plik dogania ten, który
klatka już ma. Plan liczy Qt-wolny `object_change.plan_object_change` nad read-modelem
`queries.object_change_rows`; okno pokazuje DOKŁADNIE ten plan i ten sam obiekt idzie do stagingu
(`repo.stage_object_change`) - podgląd nie jest drugą regułą, tylko tym samym zdaniem
powiedzianym przed kliknięciem. Trzecie wejście (`run_id`, Porządki → „Przerwane zmiany obiektu”,
AR-121) otwiera okno na przebiegu z bazy (`queries.object_change_run_view`) bez planu: lista ze
stanem pozycji, „Dokończ (N)” i „Cofnij” - te same operacje uchwytu co po przerwaniu w oknie.

NAZWA PLIKU (D-1011-6 `O2`): zmienia się wyłącznie człon obiektu na początku nazwy, reszta zostaje
znak w znak - okno mówi tę regułę jedną linijką, bo z listy folderów jej nie widać.

PLAN POZA WĄTKIEM OKNA. Planer czyta dysk (czy cel istnieje, jaką pisownię ma istniejący katalog -
`R:` nie rozróżnia wielkości liter, baza tak), a dysk bywa udziałem SMB: kilkaset pytań o katalogi
na wątku GUI to sekundy martwego okna. `PlanWorker` otwiera własne połączenie po ścieżce bazy
(połączenie nie przechodzi między wątkami); baza bez pliku i testy liczą inline (`off_thread`).

WYKONANIE JEDNĄ OPERACJĄ UCHWYTU (`WritebackRunner`, `_OPS["object_change"]`): rdzeń idzie per
pozycja baza → przeniesienie → karta, „razem albo wcale”. Dwa starty uchwytu zwolniłyby między sobą
mutex „zapis → Dostawa”, więc okno nie składa gestu z kilku operacji. „Cofnij” żyje do zamknięcia
okna (`undo_object_change`, wzorzec okien kart); przebieg leży w bazie, więc cofnięcie przeżywa też
awarię procesu (droga dev poza oknem). Zamknięcie w biegu = żądanie anulowania (`refuse_close`), a po
przerwaniu okno oferuje „Dokończ” tego samego przebiegu obok „Cofnij”.

SZEROKOŚĆ: kanon minimalnego ekranu to 1920×1080 logicznych. Ścieżki archiwum bywają dłuższe niż
ekran, więc lista ich nie zawija ani nie rozpycha okna: ścieżka pod korzeniem archiwum, elizja
ROZRÓŻNIAJĄCA (`elizja_sciezki`: folder obiektu i początek nazwy pliku zostają w kadrze, ginie
środek drzewa), pełna ścieżka w podpowiedzi.

OKNO JEDNORAZOWE: każde wejście buduje nowe okno, więc po `exec` idzie do kasacji (`exec`) - inaczej
każde zamknięte okno zostawałoby dzieckiem gospodarza do końca sesji.
"""
from __future__ import annotations

import ntpath
import re

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QDialog, QHBoxLayout, QHeaderView, QLabel, QProgressBar,
    QPushButton, QStyle, QStyledItemDelegate, QStyleOptionViewItem, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout,
)

from horreum import db, object_change, repo, resolver, writeback
from horreum.gui import i18n, queries
from horreum.gui.i18n_catalog import CATALOG
# Zdania wspólne okien zapisu mieszkają w `wb_worker` (jeden dom: czytelny powód rdzenia, status
# wiersza ze spadkiem na drogę atomową, podział powodu spadku); `grid` importuje go i tak.
# `wb_worker` ciągnie `writeback` (astropy) już tutaj, więc oba stoją na górze - import w funkcji
# niczego by nie odłożył.
from horreum.gui.wb_worker import (EtykietaBledu, WritebackRunner, ZdanieZeSzczegolem,
                                   czytelny_powod,
                                   podziel_powod_spadku, spadek_na_droge_atomowa, status_pozycji,
                                   szczegol_powodu, tekst_powodu, wiersz_szczegolu,
                                   zdanie_wyniku_zapisu)
# Wyjątek planu i odmowa stagingu - jedna reguła wyjątku okna (`powod_okna`): powód klingi z kodem
# (AR-200), błąd systemu albo bazy klasą (AR-184, AR-198), EXPECT rdzenia - błąd programu (AR-209).
from horreum.item_reasons import powod_okna
from horreum.resolve.paths import STACK_KIND, object_folder

# Kolumny listy pozycji: plik dziś, plik po zmianie, karta `OBJECT` stara → nowa i - po biegu
# zapisu albo cofnięcia - status pozycji z wyniku rdzenia (w podglądzie schowana).
_COL_STARA, _COL_NOWA, _COL_KARTA, _COL_STATUS = range(4)
# Lista pominięć: powód (dzieci: ścieżki) i liczba.
_COL_POWOD, _COL_ILE = range(2)
# Wysokość listy pominięć: kilka powodów naraz, reszta za suwakiem - pominięcia nie mogą zabrać
# liście pozycji pionu, bo to ona jest przedmiotem decyzji.
_POMINIECIA_MAX_PX = 150
# Rozmiar startowy okna. Szerokość z zapasem pod kanon 1920 logicznych; resztę dają suwaki
# i elizja, nie rozpychanie.
_START_W, _START_H = 1100, 640
# Status pozycji przebiegu z bazy (wejście z Porządków) → klucz katalogu: ta sama mowa co po biegu.
_STATUS_POZYCJI = {"pending": "objchg.st.pending", "applied": "objchg.st.done",
                   "blocked": "objchg.st.blocked", "failed": "objchg.st.failed",
                   "skipped": "objchg.st.skipped", "undone": "objchg.st.undone"}
# Rozszerzenie XISF: zapis karty w miejscu umie tam DOPISAĆ kartę w rezerwie nagłówka; FITS dopisuje
# w miejscu wyłącznie w zapasie nagłówka (`writeback._fits_inplace_plan`, AR-118), inaczej
# przepisuje cały plik - tę drogę okno przewiduje per pozycja (`drogi_dopisania`, AR-155).
_XISF = ".xisf"
# Rola komórki ścieżki: długość GŁOWY pokazanego tekstu (kategoria i folder obiektu pod korzeniem
# archiwum, `glowa_sciezki`) - delegat elizji (`_ElizjaSciezki`) trzyma ją w kadrze. Komórka bez
# tej roli (powód pominięcia, „bez przeniesienia”) maluje się zwykłą elizją widoku.
_GLOWA_ROLE = Qt.UserRole + 1
# Ile znaków nazwy pliku ma zostać obok głowy - przy mniejszym miejscu głowa ustępuje nazwie.
_MIN_ZNAKOW_NAZWY = 12
_WIELOKROPEK = "…"
# Ile obiektów „Uzgodnij” nagłówek wymienia z nazwy, reszta liczbą.
_OBIEKTOW_W_NAGLOWKU = 3
# Droga dopisania karty FITS BEZ prognozy (AR-155): pozycja spoza `drogi_dopisania` albo lista
# przebiegu z bazy - mówi się ogólnym „zależy od pliku”. Osobny znak, bo `None` znaczy „w miejscu”.
_DROGA_NIEZNANA = object()
def tekst_pominiecia(kod, params, powod):
    """Zdanie pominięcia planera w języku UI: kod (`object_change.SKIP_CODES`) → `objchg.skip.<kod>`
    z parametrami pominięcia; kod bez zdania w katalogu (i pominięcie bez kodu) zostaje przy zdaniu
    rdzenia `powod` (PL). Para stosu niesie pominiętą połowę (kod, parametry, zdanie) - jej zdanie
    też w języku UI. Całość przez `czytelny_powod` (szczegół błędu systemu w parametrze)."""
    klucz = f"objchg.skip.{kod}" if kod else None
    if klucz not in CATALOG:
        return czytelny_powod(powod)
    p = dict(params)
    if kod == "pair":
        p["inner"] = tekst_pominiecia(p.pop("inner_code", None), p.pop("inner_params", ()),
                                      p.get("inner", ""))
    bramka, bramka_params = p.pop("gate", None), p.pop("gate_params", ())
    if bramka and f"objchg.gate.{bramka}" in CATALOG:      # szczegół bramki karty (AR-138)
        p["detail"] = i18n.t(f"objchg.gate.{bramka}", **dict(bramka_params))
    elif bramka and f"objchg.item.{bramka}" in CATALOG:    # bramka z powodem rdzenia (AR-167)
        from horreum.item_reasons import PowodPozycji
        p["detail"] = tekst_powodu(PowodPozycji(p["detail"], bramka, **dict(bramka_params)))
    regula, regula_params = p.pop("rule", None), p.pop("rule_params", ())
    if regula and f"objchg.folder.{regula}" in CATALOG:   # reguła formy folderu (AR-141)
        p["detail"] = i18n.t(f"objchg.folder.{regula}", **dict(regula_params))
    return czytelny_powod(i18n.t(klucz, **p))


# Pominięcia katalogu celu z błędem systemu klasą (AR-183): zdanie mówi klasę w języku UI, a komunikat
# systemu (w języku systemu) - podpowiedź grupy. `dir_unreadable` niesie go w samym zdaniu.
_SZCZEGOL_W_PODPOWIEDZI = frozenset({"dir_denied", "dir_missing", "dir_share_lost", "dir_no_space"})


def podpowiedz_pominiecia(kod, params, zdanie):
    """Podpowiedź grupy pominięć: zdanie grupy, a przy odmowie katalogu z błędem systemu klasą -
    wiersz „Szczegół systemu: …” z surowym tekstem systemu (`wb_worker.wiersz_szczegolu` - ta sama
    reguła zdejmowania `repr` ścieżki co przy powodzie z kodem)."""
    wiersz = wiersz_szczegolu(dict(params).get("detail") if kod in _SZCZEGOL_W_PODPOWIEDZI else None)
    return zdanie + "\n" + wiersz if wiersz else zdanie


def tekst_ostrzezenia(kod, params, tekst):
    """Zdanie ostrzeżenia w języku UI - planera (`object_change.ObjectChangeWarning`) albo
    sterownika zapisu (`object_change.ZdanieRdzenia`): kod → `objchg.warn.<kod>` z parametrami;
    wpis mnogi odmienia się przez parametr `n`. Kod bez zdania w katalogu (i ostrzeżenie bez
    kodu, zwykły `str` rdzenia) zostaje przy zdaniu rdzenia `tekst` (PL). Bez `czytelny_powod` -
    zdanie wyniku przepuszcza przez niego całość."""
    klucz = f"objchg.warn.{kod}" if kod else None
    if klucz not in CATALOG:
        return str(tekst)
    # Parametr-powód z kodem (rekoncyliacja renamu, AR-148) też w języku UI.
    from horreum.item_reasons import PowodPozycji
    p = {k: tekst_powodu(v) if isinstance(v, PowodPozycji) else v for k, v in params}
    if isinstance(CATALOG[klucz]["pl"], dict):
        return i18n.t_plural(klucz, p.pop("n"), **p)
    return i18n.t(klucz, **p)


def lista_obiektow(canons):
    """Obiekty do nagłówka: pierwsze `_OBIEKTOW_W_NAGLOWKU` z nazwy (alfabetycznie), reszta liczbą
    („IC405, NGC3034, Sh2-229 i 9 innych”) - nagłówek nie rośnie z liczbą obiektów zaznaczenia."""
    canons = sorted(canons, key=str.casefold)
    reszta = len(canons) - _OBIEKTOW_W_NAGLOWKU
    return (", ".join(canons[:_OBIEKTOW_W_NAGLOWKU])
            + (i18n.t_plural("objchg.head_objects_more", reszta) if reszta > 0 else ""))


def policz_plan(con, frame_ids, *, target):
    """Plan gestu dla `frame_ids` → `(ObjectChangePlan, korzeń archiwum | None)`. ZERO ZAPISU.

    Jeden rachunek dla wątku tła i trybu inline: read-model (`queries.object_change_rows`), korzeń
    archiwum (`resolver.library_root_from_db` - kotwica pozycji obiektu w ścieżce), indeks lokacji
    bazy (`queries.location_lookup` - kolizja celu z inną lokacją) i Qt-wolny planer. Read-model
    dostaje cel, bo forma karty i bramka karty zależą od kanonu celu (przy „Uzgodnij" - od
    bieżącego). Korzeń wraca razem z planem, bo okno skraca nim ścieżki."""
    korzen = resolver.library_root_from_db(con)
    rows = queries.object_change_rows(con, list(frame_ids), target=target)
    plan = object_change.plan_object_change(
        rows, target=target, library_root=korzen, location_at=queries.location_lookup(con))
    return plan, korzen


def drogi_dopisania(con, plan):
    """Przewidywana droga KAŻDEGO dopisania karty do FITS w planie (AR-155) → `{location_id:
    powód | None}`: `None` = w miejscu, `fb_no_room` = cały plik przepisany, `route_depends` =
    zależy od pliku. Reguła drogi jest jedna - `writeback.inplace_route` z lustrem kart obecnej
    kopii (`queries.present_copy_card_mirror`); lustro, które nie opisuje tej kopii, daje „zależy
    od pliku”. Pozycje bez dopisania do FITS (podmiana karty, XISF, bez karty) nie wchodzą - ich
    drogi okno nie przewiduje. ZERO ZAPISU, zero dysku - liczone obok planu, na jego wątku."""
    dopisania = [it for it in plan.items
                 if ObjectChangeDialog._dopisanie_fits(it.card_op, it.old_path)]
    if not dopisania:
        return {}
    lustra = queries.present_copy_card_mirror(con, [it.frame_id for it in dopisania])
    return {it.location_id: writeback.inplace_route("fits", "OBJECT", it.card_new, "str", None,
                                                    op="add", cards=lustra.get(it.frame_id))
            for it in dopisania}


def drogi_kart(con, plan):
    """Przewidywana droga KAŻDEGO zapisu karty `OBJECT` w planie (AR-157) → `{location_id: None |
    powód | _DROGA_NIEZNANA}` - nadzbiór `drogi_dopisania`, z którego bierze dopisania do FITS bez
    zmian (AR-155). Reszta tą samą regułą pisarza (`writeback.inplace_route`): XISF (`set`
    i `add`) - w miejscu w rezerwie nagłówka; podmiana karty FITS - z komentarzem karty z lustra
    obecnej kopii (`queries.present_copy_card_mirror`), bo to on decyduje, czy karta zmieści się
    w jednym rekordzie; lustro, które kopii nie opisuje → `_DROGA_NIEZNANA` („zależy od pliku”).
    Znaczniki wierszy czytają drogę wyłącznie dla dopisań FITS (`_tekst_karty`), sumę - wszystkie
    (`sumy_drog`). ZERO ZAPISU, zero dysku."""
    drogi = drogi_dopisania(con, plan)
    podmiany = [it for it in plan.items if it.card_op and it.location_id not in drogi]
    if not podmiany:
        return drogi
    lustra = queries.present_copy_card_mirror(
        con, [it.frame_id for it in podmiany if not it.old_path.lower().endswith(_XISF)])
    for it in podmiany:
        if it.old_path.lower().endswith(_XISF):
            drogi[it.location_id] = writeback.inplace_route("xisf", "OBJECT", it.card_new, "str",
                                                            None, op=it.card_op)
            continue
        lustro = lustra.get(it.frame_id)
        if lustro is None:
            drogi[it.location_id] = _DROGA_NIEZNANA
            continue
        komentarz = next((k[3] for k in lustro if k[0] == "OBJECT"), None)
        drogi[it.location_id] = writeback.inplace_route("fits", "OBJECT", it.card_new, "str",
                                                        komentarz, op=it.card_op)
    return drogi


def recepta_duplikatow():
    """Recepta od klatki z kilkoma obecnymi kopiami do jednej (AR-157) - ten sam tekst, który niesie
    podpowiedź wiersza Porządków „Duplikaty”: wpis `tasks._PODPOWIEDZI_OSI["dup_frames"]` (klucz
    i nazwy przycisków z katalogu) złożony tą samą regułą co wiersz. Import leniwy: moduł Porządków
    ciągnie widoki, a okno potrzebuje go dopiero przy pominięciu `many_copies`."""
    from horreum.gui.tasks import _PODPOWIEDZI_OSI
    klucz, nazwy = _PODPOWIEDZI_OSI["dup_frames"]
    return i18n.t(klucz, **{k: i18n.t(v) for k, v in nazwy.items()})


def sumy_drog(plan, drogi):
    """Suma dróg zapisu kart planu (AR-157, podgląd „Uzgodnij” i „Zmień obiekt…”) → `{"inplace",
    "rewrite", "depends"}`: `None` = w miejscu, `_DROGA_NIEZNANA` albo powód `route_depends` = zależy
    od pliku, każdy inny powód pisarza (`fb_no_room`, `fb_card_too_long`, …) = cały plik przepisany.
    Pozycja bez karty się nie liczy; pozycja z kartą bez prognozy - „zależy od pliku”."""
    sumy = {"inplace": 0, "rewrite": 0, "depends": 0}
    for it in plan.items:
        if not it.card_op:
            continue
        droga = drogi.get(it.location_id, _DROGA_NIEZNANA)
        if droga is None:
            sumy["inplace"] += 1
        elif droga is _DROGA_NIEZNANA or getattr(droga, "code", None) == "route_depends":
            sumy["depends"] += 1
        else:
            sumy["rewrite"] += 1
    return sumy


class PlanWorker(QObject):
    """Plan gestu poza wątkiem okna (wzorzec `DryWorker`/`TeczkiWorker`). Otwiera WŁASNE połączenie
    po `db_path`; tryb inline (`db_path` pusty) dostaje żywe `con` wołającego i biegnie
    synchronicznie. Wynik niesie generację startu - okno odrzuca stale (plan sprzed cofnięcia)."""

    done = Signal(int, object)          # (generacja, (plan, korzeń, drogi zapisu kart))
    # (generacja, powód) - `object`, nie `str`: `Signal(str)` zgubiłby kod `PowodPozycji` (AR-184)
    failed = Signal(int, object)
    finished = Signal()

    def __init__(self, db_path, gen, *, frame_ids, target, con=None):
        super().__init__()
        self._db_path = db_path
        self._con = con
        self._gen = gen
        self._frame_ids = list(frame_ids)
        self._target = target

    @Slot()
    def run(self):
        try:
            self.done.emit(self._gen, self._compute())
        except Exception as exc:        # szczerze na ekran, nie cicha śmierć wątku
            self.failed.emit(self._gen, powod_okna(exc))
        finally:
            self.finished.emit()

    def _compute(self):
        own = bool(self._db_path)
        con = db.connect(self._db_path) if own else self._con
        try:
            plan, korzen = policz_plan(con, self._frame_ids, target=self._target)
            return plan, korzen, drogi_kart(con, plan)
        finally:
            if own:
                con.close()


def sciezka_pod_korzeniem(path, korzen):
    """`R:\\ASTRO_\\LIGHTS\\IC405\\…` → `LIGHTS\\IC405\\…` - ścieżka bez korzenia archiwum, gdy pod
    nim leży (porównanie bez wielkości liter: semantyka `R:`); inaczej bez zmian. Korzeń jest ten sam
    w każdym wierszu, więc niczego nie mówi, a zjada szerokość kolumny."""
    if not path or not korzen:
        return path or ""
    k = korzen.rstrip("\\/")
    if path[:len(k)].casefold() == k.casefold() and path[len(k):len(k) + 1] in ("\\", "/"):
        return path[len(k) + 1:]
    return path


def glowa_sciezki(path, korzen):
    """Długość GŁOWY ścieżki pokazanej pod korzeniem (`sciezka_pod_korzeniem`): kategoria i folder
    obiektu z właściciela pozycji obiektu (`resolve.paths.object_folder` - drzewo lightów, potem
    drzewo stosów) - człon, którym „Po zmianie” różni się od „Plik dziś”. 0 = ścieżka poza
    pozycją obiektu (elizja trzyma wtedy samą nazwę pliku)."""
    if not path:
        return 0
    folder = object_folder(path, "light", korzen) or object_folder(path, STACK_KIND, korzen)
    if not folder:
        return 0
    glowa = sciezka_pod_korzeniem(folder, korzen)
    pokazana = sciezka_pod_korzeniem(path, korzen)
    return len(glowa) if pokazana[:len(glowa)].casefold() == glowa.casefold() else 0


def elizja_sciezki(fm, tekst, szerokosc, glowa=0):
    """Ścieżka skrócona do `szerokosc` px tak, żeby wiersze i kolumny dalej się RÓŻNIŁY. Elizja
    w środku dawała identyczne wiersze („NGC30…GHT_OSC”): ginął człon obiektu i znacznik czasu
    z nazwy pliku, a zostawał wspólny ogon. Pierwszeństwo, od najważniejszego:
      1. nazwa pliku od POCZĄTKU - człon obiektu i data z godziną, tym różnią się wiersze;
      2. głowa `tekst[:glowa]` - kategoria i folder obiektu, tym różni się „Po zmianie”;
      3. środek drzewa (zestaw, filtr) - ginie pierwszy, w miejscu `…`.
    Nazwa, która zaczyna się członem obiektu z głowy (separator członu jak w planerze nazwy,
    `object_change._SEPARATORY_CZLONU`), sama niesie obiekt - przy braku miejsca głowa ustępuje
    nazwie (`…\\NGC3034_20220326_2115…`). Nazwa bez członu (z aparatu) trzyma głowę - całą, a gdy
    się nie mieści, sam folder obiektu (`…\\21P_Giacobini-Zinner\\…\\20181011_dsc…`) - dopóki obok
    zostaje `_MIN_ZNAKOW_NAZWY` znaków nazwy. Tekst, który się mieści, wraca bez zmian."""
    if fm.horizontalAdvance(tekst) <= szerokosc:
        return tekst
    i = max(tekst.rfind("\\"), tekst.rfind("/"))
    if i < 0:
        return fm.elidedText(tekst, Qt.ElideRight, szerokosc)
    sep, plik = tekst[i], tekst[i + 1:]
    glowa = tekst[:min(glowa, i)]
    srodek = tekst[len(glowa):i + 1]          # między głową a nazwą, z separatorami po obu stronach
    znacznik = f"{sep}{_WIELOKROPEK}{sep}"
    miejsce = szerokosc - fm.horizontalAdvance(glowa + plik)
    if miejsce >= fm.horizontalAdvance(znacznik):
        # Cała nazwa i głowa się mieszczą - traci środek drzewa (skrajne separatory zostają).
        return glowa + fm.elidedText(srodek, Qt.ElideMiddle, miejsce) + plik
    token = re.split(r"[\\/]", glowa)[-1] if glowa else ""
    niesie_obiekt = (bool(token) and plik[:len(token)].casefold() == token.casefold()
                     and plik[len(token):len(token) + 1] in object_change._SEPARATORY_CZLONU)
    pominiety = srodek.strip("\\/") != ""
    prefiks = f"{_WIELOKROPEK}{sep}"
    if glowa and not niesie_obiekt:
        # Cała głowa, a gdy się nie mieści - sam folder obiektu (bez kategorii), zanim ustąpi nazwie.
        za_glowa = znacznik if pominiety else sep
        for kandydat in (glowa + za_glowa, f"{_WIELOKROPEK}{sep}{token}{za_glowa}"):
            if (szerokosc - fm.horizontalAdvance(kandydat)
                    >= fm.averageCharWidth() * _MIN_ZNAKOW_NAZWY):
                prefiks = kandydat
                break
    miejsce = szerokosc - fm.horizontalAdvance(prefiks)
    if miejsce <= 0:
        return fm.elidedText(plik, Qt.ElideRight, szerokosc)
    return prefiks + fm.elidedText(plik, Qt.ElideRight, miejsce)


class _ElizjaSciezki(QStyledItemDelegate):
    """Delegat kolumn ścieżek: tekst do malowania skraca `elizja_sciezki` do szerokości prostokąta
    tekstu - w malowaniu, nie w `initStyleOption`, bo z opcji liczy się też podpowiedź szerokości
    (wzorzec `grid_model._ElizjaWSrodku`). Tekst pozycji zostaje pełny - kopiuje się, testuje
    i trafia w podpowiedź bez zmian. Komórka bez roli głowy maluje się zwykłą elizją widoku."""

    @staticmethod
    def tekst_w_komorce(option, glowa):
        """Tekst opcji skrócony do szerokości, którą styl da mu w komórce: prostokąt tekstu
        (`SE_ItemViewItemText`) minus margines, który styl odejmuje przy rysowaniu
        (`PM_FocusFrameHMargin` + 1 z każdej strony)."""
        styl = option.widget.style() if option.widget is not None else QApplication.style()
        prostokat = styl.subElementRect(QStyle.SE_ItemViewItemText, option, option.widget)
        margines = styl.pixelMetric(QStyle.PM_FocusFrameHMargin, None, option.widget) + 1
        return elizja_sciezki(option.fontMetrics, option.text,
                              max(0, prostokat.width() - 2 * margines), glowa)

    def paint(self, painter, option, index):
        glowa = index.data(_GLOWA_ROLE)
        if glowa is None:
            super().paint(painter, option, index)
            return
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = self.tekst_w_komorce(opt, glowa)
        styl = opt.widget.style() if opt.widget is not None else QApplication.style()
        styl.drawControl(QStyle.CE_ItemViewItem, opt, painter, opt.widget)


def tekst_postepu(etykieta, done, total, pokazana, glowa=0):
    """Wiersz postępu „N/M · ścieżka” skrócony do szerokości `etykieta` (`elizja_sciezki`).
    Ścieżka i nazwa pliku to jedno długie słowo bez miejsc łamania, więc zawijana etykieta stanu
    rozpychała okno do szerokości nazwy (zmierzone: „Napraw nagłówek…” 680 → 730 px przy nazwie
    komety) - postęp trwa chwilę, pełną ścieżkę niesie lista."""
    prefiks = f"{done}/{total} · "
    fm = etykieta.fontMetrics()
    return prefiks + elizja_sciezki(fm, pokazana or "",
                                    max(etykieta.width() - fm.horizontalAdvance(prefiks), 0), glowa)


def ustaw_sciezke(wiersz, kolumna, path, korzen):
    """Komórka ścieżki: tekst pod korzeniem archiwum, pełna ścieżka w podpowiedzi i rola głowy dla
    delegata elizji (`_ElizjaSciezki`). Pusta ścieżka (lokacji nie ma) - pusta komórka."""
    wiersz.setText(kolumna, sciezka_pod_korzeniem(path, korzen))
    wiersz.setToolTip(kolumna, path or "")
    wiersz.setData(kolumna, _GLOWA_ROLE, glowa_sciezki(path, korzen) if path else None)


def ma_robote(item):
    """Czy pozycja planu cokolwiek zmienia: plik, karta albo obiekt w bazie."""
    return bool(item.new_path or item.card_op or item.object_change)


def inny_katalog(item):
    """Czy przeniesienie zmienia KATALOG pliku (porównanie fizyczne `object_change.path_key`: bez
    wielkości liter, jak `R:`), a nie tylko jego nazwę w tym samym folderze."""
    return (item.new_path is not None
            and object_change.path_key(ntpath.dirname(item.old_path))
            != object_change.path_key(ntpath.dirname(item.new_path)))


def bez_zmian(skip):
    """Pominięcie planu, które jest pozycją BEZ ZMIAN (plik w folderze obiektu, nazwa i karta zgodne),
    a nie odmową - liczy się w „bez zmian”, nie w „pominie”. Rozpoznane po kodzie planera."""
    return skip.code == object_change.SKIP_UNCHANGED


def liczby_planu(plan):
    """Liczby podglądu z planu - te same, które padną na przycisku i w zdaniu przed zapisem.
    Przeniesienie liczy się osobno do innego folderu i jako nowa nazwa w tym samym folderze (człon
    obiektu w nazwie zmienia się także plikowi, który folderu nie zmienia - stos stoi w folderze
    obiektu pod starą nazwą). Katalogi liczone RAZ na ścieżkę (kilka plików jedzie do jednego
    nowego folderu), bez wielkości liter, bo `R:` jej nie rozróżnia."""
    items = plan.items
    bez = sum(1 for s in plan.skipped if bez_zmian(s))
    return {
        "robota": sum(1 for it in items if ma_robote(it)),
        "folder": sum(1 for it in items if inny_katalog(it)),
        "nazwa": sum(1 for it in items if it.new_path and not inny_katalog(it)),
        "karty": sum(1 for it in items if it.card_op),
        "katalogi": len({d.casefold() for it in items for d in it.mkdirs}),
        # Katalogi źródłowe, które po całym planie zostaną puste - sterownik je usunie; mówione
        # przed kliknięciem, bo znikający folder to skutek, którego lista plików nie pokazuje.
        "usunie": len({object_change.path_key(d) for d in plan.rmdirs}),
        "obiekt": sum(1 for it in items if it.object_change),
        "bez_zmian": sum(1 for it in items if not ma_robote(it)) + bez,
        "pominie": len(plan.skipped) - bez,
    }


def tekst_planu(plan):
    """Zdanie podglądu mówiące, CO plan zrobi z plikami - per pozycja, z tych samych pól planu,
    które idą do stagingu (`repo.stage_object_change`: karta tylko przy `card_op`, przeniesienie
    tylko przy `new_path`), a nie ze stałej obietnicy „karta i folder” (odbiór 0.19.0 OB11: podgląd
    RAW-ów obiecywał kartę i przeniesienie). Człony z zerem milczą; pusty tekst = plan bez roboty.

    RAW (`card_read_only`, read-model `NO_OBJECT_CARD_FILETYPES`) karty nie dostaje NIGDY - pisarz
    go nie zapisuje. Przeniesienie RAW-a idzie jak każdego pliku (sterownik `_zmien_pozycje`, krok
    przeniesienia nie pyta o format), więc zdanie RAW mówi, ile z nich zmieni wyłącznie ścieżkę,
    a reszta - tylko wpis w bazie."""
    robota = [it for it in plan.items if ma_robote(it)]
    karty = sum(1 for it in robota if it.card_op)
    ruch = sum(1 for it in robota if it.new_path)
    baza = sum(1 for it in robota if it.object_change and not it.new_path and not it.card_op)
    czlony = []
    if karty:
        czlony.append(i18n.t("objchg.plan.card_form", n=karty, card=plan.target.card_form)
                      if plan.target is not None else i18n.t("objchg.plan.card", n=karty))
    if ruch:
        czlony.append(i18n.t("objchg.plan.move", n=ruch))
    if baza:
        czlony.append(i18n.t("objchg.plan.db_only", n=baza))
    if not czlony:
        return ""
    tekst = i18n.t("objchg.plan.head", parts=" · ".join(czlony))
    raw = [it for it in robota if it.card_read_only]
    if raw:
        jedzie = sum(1 for it in raw if it.new_path)
        tekst += "\n" + (i18n.t("objchg.plan.raw_moved", n=len(raw), moved=jedzie) if jedzie
                         else i18n.t("objchg.plan.raw_db", n=len(raw)))
    return tekst


def zdanie_wyniku_zmiany(res, *, cofniecie=False):
    """Zdanie wyniku przebiegu (`writeback.ObjectChangeResult`) - wspólna gramatyka powierzchni
    zapisu (`wb_worker.zdanie_wyniku_zapisu`: liczba, blokady, błędy, pominięcia, pierwszy powód)
    plus to, czego zwykły commit nie ma:

      * pozycje `applied` z powodem: przy zapisie karta SPADŁA na drogę atomową - liczba zdaniem
        człowieka („cały plik przepisany”, `wb.inplace_fallback`; szczegół rdzenia niesie podpowiedź
        wiersza, `status_pozycji`), każdy inny powód to uwaga (przy cofnięciu np. nowsza decyzja
        ręki w bazie), tak samo uwaga dopisana przez rdzeń za spadkiem - liczba i pierwsza uwaga,
        bo sama liczba zmienionych by to ukryła;
      * katalogi założone i usunięte, katalogi o niepewnej własności (zostają do oka);
      * blokada pliku zmienionego od ostatniego skanu - z receptą (skan w Dostawie, potem ponów);
      * numer przebiegu - po zamknięciu okna jedyny uchwyt do dokończenia albo cofnięcia
        (`horreum object-change finish|undo DB RUN_ID`), jak `commit_id` w oknach kart;
      * ostrzeżenia rdzenia - po kodzie w języku UI (`tekst_ostrzezenia`).
    Całość przechodzi przez `czytelny_powod` (plik zajęty, ścieżki z `repr`)."""
    msg = (zdanie_wyniku_zapisu(res, "objchg.res.undone") if cofniecie
           else zdanie_wyniku_zapisu(res, "objchg.res.applied"))
    z_powodem = [fr for fr in res.applied if fr.reason and fr not in res.withheld]
    atomowe = ([] if cofniecie
               else [fr for fr in z_powodem if spadek_na_droge_atomowa(fr)])
    # Uwagi: powody spoza spadku i to, co rdzeń dopisał ZA spadkiem (kopia pliku sprzed podmiany
    # zostawiona na dysku, nagrobek ręki - `podziel_powod_spadku`, jeden podział z oknami kart).
    uwagi = ([u for u in (podziel_powod_spadku(fr.reason)[1] for fr in atomowe) if u]
             + [tekst_powodu(fr.reason) for fr in z_powodem if fr not in atomowe])
    if cofniecie and res.withheld:                       # AR-82: karta wróciła, zeznanie nie
        msg += " · " + i18n.t_plural("grid.wb.undo_withheld", len(res.withheld))
    if atomowe:
        msg += i18n.t("wb.inplace_fallback", n=len(atomowe))
    if uwagi:
        msg += i18n.t("objchg.res.notes", n=len(uwagi), note=uwagi[0])
    if res.dirs_created or res.dirs_removed:
        msg += i18n.t("objchg.res.dirs", created=res.dirs_created, removed=res.dirs_removed)
    if res.dirs_uncertain:
        msg += i18n.t_plural("objchg.res.dirs_uncertain", res.dirs_uncertain)
    od_skanu = sum(1 for fr in res.blocked if fr.code == writeback.CODE_CHANGED_SINCE_SCAN)
    if od_skanu:
        msg += i18n.t_plural("objchg.res.rescan", od_skanu)
    if res.cancelled:
        msg += i18n.t("wb.cancelled_note")
    msg += i18n.t("objchg.res.run", run_id=res.run_id)
    for ostrzezenie in res.warnings:
        msg += "\n" + tekst_ostrzezenia(getattr(ostrzezenie, "code", None),
                                        getattr(ostrzezenie, "params", ()), ostrzezenie)
    return czytelny_powod(msg)


def zdanie_paska(res, *, target, n, przed=None, obiekty=(), cofniecie=False, droga=("", "", "")):
    """Zdanie PASKA po zamknięciu okna (odbiór 0.19.0 OB12) - jedno zdanie gestu jak u sąsiadów
    osi obiektu („Przypisz obiekt”, „Cofnij przypisanie”): ile klatek (`n` - z TRWAŁEGO stanu
    pozycji przebiegu, nie z ostatniej tury: „Dokończ” i ponowione cofnięcie sumują się), na jaki
    obiekt, z jakiego albo do jakiego wróciły (`przed` - jeden obiekt z chwili podglądu wszystkich
    liczonych klatek, inaczej None) i droga powrotu (`droga` = (człon zdania, szczegół, polecenie) -
    składa ją okno: Porządki albo polecenie CLI w szczególe pod kursorem, AR-272, i w polu polecenia
    nośnika do „Kopiuj polecenie”, AR-309). Zdanie okna
    (`zdanie_wyniku_zmiany`) mówi pozycjami i numerem przebiegu, a po zamknięciu nie widać już
    listy, do której się odnosi.

    Rozbicie blokad, błędów i pominięć tury `res` z pierwszym powodem bierze tę samą gramatykę co
    okno (`zdanie_wyniku_zapisu`) bez jej członu głównego - liczbę niesie głowa zdania. `res=None`
    (wyjątek workera: wyniku tury nie ma) - sama głowa i droga. `obiekty` = obiekty klatek przy
    „Uzgodnij” (nagłówek okna, `lista_obiektow`). Ze szczegółem → `ZdanieZeSzczegolem`."""
    if target is not None and cofniecie:
        glowa = (i18n.t_plural("objchg.bar.undone_change_to", n, canon=target.canon, old=przed)
                 if przed and przed != target.canon
                 else i18n.t_plural("objchg.bar.undone_change", n, canon=target.canon))
    elif target is not None:
        glowa = (i18n.t_plural("objchg.bar.changed_from", n, old=przed, canon=target.canon)
                 if przed and przed != target.canon
                 else i18n.t_plural("objchg.bar.changed", n, canon=target.canon))
    else:
        glowa = i18n.t_plural("objchg.bar.undone_align" if cofniecie else "objchg.bar.aligned", n)
        if obiekty:
            glowa += i18n.t("objchg.bar.objects", objects=lista_obiektow(obiekty))
    msg = glowa
    if res is not None:
        klucz = "objchg.res.undone" if cofniecie else "objchg.res.applied"
        wynik, glowny = zdanie_wyniku_zapisu(res, klucz), i18n.t(klucz, n=len(res.applied))
        assert wynik.startswith(glowny), (wynik, glowny)
        msg += wynik[len(glowny):]
        if res.cancelled:
            msg += i18n.t("wb.cancelled_note")
    czlon, szczegol, polecenie = droga
    zdanie = czytelny_powod(msg) + czlon
    return ZdanieZeSzczegolem(zdanie, szczegol, polecenie=polecenie) if szczegol else zdanie


def zdanie_odmowy_stagingu(exc):
    """Odmowa stagingu planu (`repo.stage_object_change`) → `(zdanie, szczegół)` pola błędu okna
    (AR-200) - ta sama reguła wyjątku okna co plan (`item_reasons.powod_okna`, AR-209). Odmowa
    klingi z powodem (`OdmowaZPowodem`) i błąd bazy (`sqlite3.Error` - klasę ma jeden właściciel)
    mówią powodem w języku UI, szczegół systemu idzie pod kursor (`wiersz_systemu`). Goły
    `ValueError` to inwariant planu (EXPECT w klindze - błąd programu `prog_error`): zdanie
    stagingu „plan niespójny z regułami zapisu” w języku UI, surowy tekst inwariantu z typem
    w szczególe technicznym. Inny wyjątek (`TypeError`, `KeyError` - błąd programu, ale nie inwariant
    planu) - zdanie błędu programu, bez obietnicy, że winny jest plan."""
    powod = powod_okna(exc)
    if getattr(powod, "code", None) == "prog_error" and isinstance(exc, ValueError):
        return (i18n.t("objchg.err.stage", msg=i18n.t("objchg.err.stage_plan")),
                szczegol_powodu(powod))
    # Szczegół: system i numer operacji z drogą wyjścia (AR-281 - zdanie mówi gest, nie numer).
    return i18n.t("objchg.err.stage", msg=tekst_powodu(powod)), szczegol_powodu(powod)


def ruszyl_cokolwiek(res):
    """Czy przebieg zostawił coś do cofnięcia. `failed` liczy się także: błąd pozycji bywa
    rozjazdem po częściowym kroku (plik przeniesiony, karta nie). Katalogi - wyłącznie gdy zostały
    założone ponad te, które ten sam przebieg sprzątnął (odmowa po założeniu katalogu zostawia
    przebieg bez zmian na dysku, a „Cofnij” byłoby obietnicą bez pokrycia)."""
    return bool(res.applied or res.failed or res.withheld or res.commit_ids
                or res.dirs_created > res.dirs_removed)


class ObjectChangeDialog(QDialog):
    """Podgląd i wykonanie gestu zmiany obiektu (`target`) albo uzgodnienia plików (`target=None`)
    na klatkach `frame_ids` - albo (`run_id`) wznowienie przerwanego przebiegu z bazy: wtedy cel
    i klatki bierze z przebiegu (`queries.object_change_run_view`), a `frame_ids`/`target` nie
    przychodzą. Przebieg, którego nie ma, to błąd wołającego (EXPECT) - wiersz Porządków liczy
    z tej samej bazy.

    Enter NIE uruchamia gestu: przyciskiem domyślnym jest „Zamknij” (zapis do plików idzie wyłącznie
    świadomym kliknięciem).

    Cel z formą karty `None` (karta z formą nie prowadzi z powrotem do obiektu - kanon znany tylko
    z aliasu) jest ODMOWĄ PRZED PLANEM - obietnica
    „karta i folder razem” nie ma czym się spełnić. Odmowę mówi wołający (wybór celu), tu stoi
    asercja: okno z takim celem to błąd kolejności (EXPECT).

    `changed` = zapis albo cofnięcie doszło do skutku (gospodarz odświeża zbiór i Porządki);
    `busy_changed` = okno pisze do plików (mutex drugiej powierzchni, D-PD-3). `summary` = zdanie
    PASKA ostatniego biegu (`zdanie_paska`: ile klatek, na jaki obiekt, droga powrotu) - po
    zamknięciu okna gospodarz kładzie je na pasek; zdanie wyniku w oknie (`status`) mówi pozycjami
    i numerem przebiegu. Okno zamknięte bez biegu zostawia `summary` puste - pasek milczy."""

    changed = Signal()
    busy_changed = Signal(bool)

    def __init__(self, con, *, frame_ids=None, target=None, run_id=None, now_fn, db_path=None,
                 off_thread=True, parent=None):
        super().__init__(parent)
        przebieg = None
        if run_id is not None:
            assert frame_ids is None and target is None, (
                "wznowienie przebiegu bierze klatki i cel z bazy, nie od wołającego")
            przebieg = queries.object_change_run_view(con, run_id)
            assert przebieg is not None, f"brak przebiegu zmiany obiektu {run_id!r}"
            frame_ids, target = przebieg["frame_ids"], przebieg["target"]
        assert target is None or target.card_form is not None, (
            "cel bez formy karty OBJECT - gest odmawia go przed planem (wołający)")
        self.con = con
        self._frame_ids = list(frame_ids)
        self._target = target
        # „Uzgodnij” nie zmienia obiektu w bazie, więc nagłówek nazywa obiekty, które klatki już
        # mają (read-model gridu, sam SQL - bez dysku na wątku okna).
        self._obiekty = ([] if target is not None else sorted(
            {r["object_canon"] for r in queries.base_rows(con, self._frame_ids)
             if r["object_canon"]}))
        self._przebieg = przebieg        # wejście z Porządków: przebieg z bazy, bez planu
        self._zamknij_po_planie = None   # wynik zamknięcia odłożony do końca planu w biegu
        self._now = now_fn
        self._db_path = db_path if db_path is not None else queries.db_path_of(con)
        self._off_thread = off_thread
        self._plan = None
        self._korzen = None
        self._drogi = {}             # location_id → przewidywana droga dopisania karty FITS
        self._gen = 0
        self._plan_worker = None
        self._plan_thread = None
        self._run_id = None          # przebieg ze stagingu - cel „Cofnij” i „Dokończ”
        self._do_cofniecia = False   # przebieg coś zmienił, a cofnięcie jeszcze nie przeszło
        self._domkniety = False      # plan wykonany - drugi zapis nie ma czego robić do „Cofnij”
        self._pozostalo = 0          # pozycje nieprzetworzone po przerwaniu (droga „Dokończ”)
        # Przebieg `staged` do domknięcia - „Dokończ” także przy zerze czekających (awaria po
        # ostatniej pozycji, przed domknięciem przebiegu: `can_finish` read-modelu).
        self._dokonczenie = False
        # Stan przerwanego przebiegu, o którym mówi nagłówek i opis okna z Porządków: `staged`
        # (zapis do dokończenia), `undoing` (cofanie przerwane), `failed` (pozycja z błędem) albo
        # None (przebieg domknięty albo okno liczy nowy plan) - `_opisz_stan`.
        self._stan_przebiegu = None
        self._status_wiersza = {}    # location_id → (status, podpowiedź) - z bazy albo z biegu
        self._w_biegu = 0            # z iloma pozycjami ruszył ostatni bieg zapisu
        # LISTA PO BIEGU MÓWI O WYNIKU, NIE O PLANIE: `_wynik_na_liscie` = lista pokazuje wynik
        # zapisu albo cofnięcia (status per wiersz), a nowy plan liczy się dopiero na prośbę
        # („Policz plan ponownie”) - inaczej powody blokad znikałyby razem ze starym planem.
        # `_jest` = gdzie okno wie, że plik stoi (location_id → ścieżka), po każdym biegu z wyniku.
        self._wynik_na_liscie = False
        self._jest = {}
        self._wiersze = {}           # location_id → wiersz listy pozycji
        self._pipeline_busy = False
        self._po_exec = False        # `exec` wrócił - okno do kasacji, gdy wolne (`_zwolnij_gdy_wolne`)
        self._zwolnione = False      # `deleteLater` już zlecone
        self.summary = ""
        self._przebieg_tury = None   # przebieg ostatniej tury zapisu albo cofnięcia (zdanie paska)
        self._runner = WritebackRunner(self._db_path, now_fn=now_fn, parent=self)
        self._runner.async_ok = off_thread
        self._runner.busy_changed.connect(self.busy_changed)
        # Koniec biegu w trybie wątku dochodzi PO slocie wyniku (sprzątanie wątku), więc stan akcji
        # liczy się jeszcze raz, gdy uchwyt naprawdę jest wolny.
        self._runner.busy_changed.connect(lambda zajety: zajety or self._sync_akcji())
        self.setWindowTitle(i18n.t("objchg.title_change") if target is not None
                            else i18n.t("objchg.title_align"))
        self._build_ui()
        self.resize(_START_W, _START_H)
        if przebieg is not None:
            self._wczytaj_przebieg(przebieg)
        else:
            self._licz_plan()

    @property
    def frame_ids(self):
        """Klatki okna - z zaznaczenia albo (wejście z Porządków) z przebiegu w bazie."""
        return tuple(self._frame_ids)

    # ---------------------------------------------------------------- budowa UI
    def _build_ui(self):
        lay = QVBoxLayout(self)
        self.head = QLabel("")
        self.head.setWordWrap(True)
        lay.addWidget(self.head)
        self.opis = QLabel("")
        self.opis.setWordWrap(True)
        self.opis.setProperty("role", "secondary")
        lay.addWidget(self.opis)
        self._opisz_stan()
        # Co TEN plan zrobi z plikami (`tekst_planu`, OB11): ile kart, ile przeniesień, ile samych
        # wpisów w bazie i zdanie o RAW-ach - widoczne przy planie, jak liczby i suma dróg.
        self.plan_note = QLabel("")
        self.plan_note.setWordWrap(True)
        self.plan_note.setVisible(False)
        lay.addWidget(self.plan_note)
        # Reguła nazwy (D-1011-6 `O2`) - z listy folderów jej nie widać, a decyduje, czy nazwa
        # pliku się zmieni.
        self.name_rule = QLabel(i18n.t("objchg.name_rule"))
        self.name_rule.setWordWrap(True)
        self.name_rule.setProperty("role", "secondary")
        lay.addWidget(self.name_rule)

        self.items_tree = QTreeWidget()
        self.items_tree.setColumnCount(4)
        self._naglowki(po_biegu=False)
        self.items_tree.setRootIsDecorated(False)
        self.items_tree.setUniformRowHeights(True)
        self.items_tree.setSelectionMode(QAbstractItemView.NoSelection)
        # ELIZJA, NIE ZAWIJANIE: o tym, gdzie plik leży, mówi folder obiektu, a o tym, który to
        # plik - początek nazwy (człon obiektu, data z godziną). Kolumny ścieżek skraca delegat
        # rozróżniający (`elizja_sciezki`); reszta komórek zwykłą elizją w środku.
        self.items_tree.setTextElideMode(Qt.ElideMiddle)
        self._elizja = _ElizjaSciezki(self)
        for kolumna in (_COL_STARA, _COL_NOWA):
            self.items_tree.setItemDelegateForColumn(kolumna, self._elizja)
        hdr = self.items_tree.header()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(_COL_STARA, QHeaderView.Stretch)
        hdr.setSectionResizeMode(_COL_NOWA, QHeaderView.Stretch)
        # Karta: szerokość z treści, ale z sufitem (`_dopasuj_karte`) - kolumna karty nie zjada
        # ścieżek ani statusu (AR-118: pełne zdanie dopisania w każdym wierszu FITS zabierało przy
        # `ResizeToContents` 869 z 1100 px).
        hdr.setSectionResizeMode(_COL_KARTA, QHeaderView.Interactive)
        hdr.setSectionResizeMode(_COL_STATUS, QHeaderView.Stretch)
        self.items_tree.setColumnHidden(_COL_STATUS, True)
        lay.addWidget(self.items_tree, 1)
        # Pełne zdanie o dopisaniu karty do FITS RAZ pod listą (w komórkach krótki znacznik, zdanie
        # w ich podpowiedzi) - widoczne, gdy plan ma choć jedną taką pozycję (`_wypelnij`).
        self.card_note = QLabel("")
        self.card_note.setWordWrap(True)
        self.card_note.setProperty("role", "secondary")
        self.card_note.setVisible(False)
        lay.addWidget(self.card_note)

        self.warnings = QLabel("")
        self.warnings.setWordWrap(True)
        self.warnings.setProperty("role", "warn")
        self.warnings.setVisible(False)
        lay.addWidget(self.warnings)

        self.skipped_head = QLabel("")
        self.skipped_head.setVisible(False)
        lay.addWidget(self.skipped_head)
        self.skipped_tree = QTreeWidget()
        self.skipped_tree.setColumnCount(2)
        self.skipped_tree.setHeaderLabels([i18n.t("objchg.col.reason"), i18n.t("objchg.col.n")])
        self.skipped_tree.setUniformRowHeights(True)
        self.skipped_tree.setSelectionMode(QAbstractItemView.NoSelection)
        self.skipped_tree.setTextElideMode(Qt.ElideMiddle)
        self.skipped_tree.setItemDelegateForColumn(_COL_POWOD, self._elizja)   # ścieżki pod powodem
        shdr = self.skipped_tree.header()
        shdr.setStretchLastSection(False)
        shdr.setSectionResizeMode(_COL_POWOD, QHeaderView.Stretch)
        shdr.setSectionResizeMode(_COL_ILE, QHeaderView.ResizeToContents)
        self.skipped_tree.itemExpanded.connect(lambda _it: self._dopasuj_pominiecia())
        self.skipped_tree.itemCollapsed.connect(lambda _it: self._dopasuj_pominiecia())
        self.skipped_tree.setVisible(False)
        lay.addWidget(self.skipped_tree)
        # Droga dla klatek z kilkoma obecnymi kopiami (AR-157): pod pominięciami, gdy któreś ma kod
        # `many_copies` - ta sama recepta co podpowiedź wiersza „Duplikaty” (`recepta_duplikatow`).
        self.copies_hint = QLabel("")
        self.copies_hint.setWordWrap(True)
        self.copies_hint.setProperty("role", "secondary")
        self.copies_hint.setVisible(False)
        lay.addWidget(self.copies_hint)

        self.counts = QLabel("")
        self.counts.setWordWrap(True)
        lay.addWidget(self.counts)
        # Suma dróg zapisu kart planu (AR-157): ile w miejscu, ile pełnym przepisaniem pliku, ile
        # zależy od pliku - przed kliknięciem, tak jak liczby; widoczna, gdy plan pisze karty.
        self.routes = QLabel("")
        self.routes.setWordWrap(True)
        self.routes.setProperty("role", "secondary")
        self.routes.setVisible(False)
        lay.addWidget(self.routes)
        self.bar = QProgressBar()
        self.bar.setVisible(False)
        lay.addWidget(self.bar)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.status)
        self.error = EtykietaBledu("")      # szczegół systemu awarii znika z następnym zdaniem (AR-185)
        self.error.setProperty("role", "error")
        self.error.setWordWrap(True)
        lay.addWidget(self.error)

        actions = QHBoxLayout()
        self.action_btn = QPushButton("")
        # Złota akcja okna: WAGA, nie kolor (wzorzec okien kart).
        _f = self.action_btn.font(); _f.setBold(True); self.action_btn.setFont(_f)
        self.action_btn.clicked.connect(self._on_action)
        actions.addWidget(self.action_btn)
        self.undo_btn = QPushButton(i18n.t("objchg.undo_btn"))
        self.undo_btn.setVisible(False)
        self.undo_btn.clicked.connect(self._on_undo)
        actions.addWidget(self.undo_btn)
        actions.addStretch(1)
        self.close_btn = QPushButton(i18n.t("objchg.close_btn"))
        self.close_btn.clicked.connect(self.reject)
        actions.addWidget(self.close_btn)
        lay.addLayout(actions)
        # ENTER NIE PISZE DO PLIKÓW: `QDialog` robi przycisk z fokusem domyślnym (`autoDefault`),
        # więc Enter po kliknięciu w listę uruchamiałby gest. Domyślny jest „Zamknij”.
        for btn in (self.action_btn, self.undo_btn):
            btn.setAutoDefault(False)
            btn.setDefault(False)
        self.close_btn.setDefault(True)

    def _naglowki(self, *, po_biegu):
        """Nagłówki listy: w podglądzie „Plik dziś / Po zmianie”, po biegu „Było / Jest / Status” -
        lista po biegu opisuje, co SIĘ STAŁO, a nie, co miało się stać."""
        if po_biegu:
            etykiety = [i18n.t("objchg.col.was"), i18n.t("objchg.col.is"),
                        i18n.t("objchg.col.card"), i18n.t("objchg.col.status")]
        else:
            etykiety = [i18n.t("objchg.col.old"), i18n.t("objchg.col.new"),
                        i18n.t("objchg.col.card"), i18n.t("objchg.col.status")]
        self.items_tree.setHeaderLabels(etykiety)

    def _opisz_stan(self):
        """Nagłówek i opis okna mówią o tym, co zrobią przyciski TERAZ (wizytacja W1/W2): przerwany
        przebieg z Porządków ma nagłówek „Przerwany przebieg…” i opis drogi wyjścia ze swojego
        stanu (`staged` - „Dokończ” albo „Cofnij”, `undoing` - „Cofnij” dokończy cofanie, `failed` -
        „Cofnij” cofa cały przebieg); przebieg domknięty albo nowy plan na tych klatkach - zwykły
        nagłówek gestu. Wołane z `_sync_akcji`, więc nadąża za każdym biegiem i planem.

        Nagłówek „Uzgodnij” NAZYWA obiekty klatek (`lista_obiektow`) - bez tego mówił „z obiektem,
        który już mają”, nie mówiąc z jakim. Numer przebiegu (32 znaki) nie stoi w nagłówku: niesie
        go wiersz stanu pod listą, gdzie da się go zaznaczyć i skopiować (uchwyt CLI)."""
        # Nagłówek „Zmień obiekt…” nie obiecuje karty: o karcie mówi zdanie planu (`tekst_planu`) -
        # RAW jej nie dostanie (OB11), a forma karty stoi tam przy liczbie plików, które ją dostaną.
        n = len(self._frame_ids)
        obiekty = (i18n.t_plural("objchg.head_objects", len(self._obiekty),
                                 objects=lista_obiektow(self._obiekty))
                   if self._target is None and self._obiekty else "")
        if self._stan_przebiegu is not None:
            head = (i18n.t_plural("objchg.head_resume_change", n, canon=self._target.canon)
                    if self._target is not None
                    else i18n.t_plural("objchg.head_resume_align", n) + obiekty)
            opis = i18n.t({"staged": "objchg.explain_resume",
                           "undoing": "objchg.explain_resume_undoing",
                           "failed": "objchg.explain_resume_failed"}[self._stan_przebiegu])
        elif self._target is not None:
            head = i18n.t_plural("objchg.head_change", n, canon=self._target.canon)
            opis = i18n.t("objchg.explain_change")
        else:
            head = i18n.t_plural("objchg.head_align", n) + obiekty
            opis = i18n.t("objchg.explain_align")
        self.head.setText(head)
        self.opis.setText(opis)

    # ---------------------------------------------------------------- plan (wątek tła albo inline)
    def _licz_plan(self):
        """Zamów plan na BIEŻĄCYM stanie (otwarcie okna, po cofnięciu). Nowa generacja odrzuca
        wynik planu, który mógłby jeszcze wisieć w drodze."""
        self._gen += 1
        self._plan = None
        self._wynik_na_liscie = False
        self._stan_przebiegu = None        # nowy plan na tych klatkach - nie przebieg z Porządków
        self.error.clear()
        # Faza planu w wierszu LICZB, nie w zdaniu wyniku: plan po cofnięciu liczy się, gdy zdanie
        # cofnięcia ma jeszcze stać - liczby i tak zastąpi wynik planu.
        self.counts.setText(i18n.t("objchg.planning"))
        self.routes.setVisible(False)              # suma dróg należy do planu, który się liczy
        self.copies_hint.setVisible(False)         # zdanie o kopiach też - mówi o pominięciach planu
        self.plan_note.setVisible(False)           # i zdanie o tym, co plan zrobi z plikami
        worker = PlanWorker(self._db_path, self._gen, frame_ids=self._frame_ids,
                            target=self._target,
                            con=None if (self._off_thread and self._db_path) else self.con)
        worker.done.connect(self._on_plan_done)
        worker.failed.connect(self._on_plan_failed)
        self._plan_worker = worker
        if self._off_thread and self._db_path:
            self._plan_thread = QThread(self)
            worker.moveToThread(self._plan_thread)
            self._plan_thread.started.connect(worker.run)
            worker.finished.connect(self._plan_thread.quit)
            self._plan_thread.finished.connect(self._cleanup_plan_thread)
            self._sync_akcji()
            self._plan_thread.start()
        else:
            try:
                worker.run()                    # inline: done/failed lecą direct = synchronicznie
            finally:
                self._plan_worker = None
            self._sync_akcji()

    def _cleanup_plan_thread(self):
        # wait() PRZED thread.deleteLater() - ten sam deadlock GIL × ~QThread co w
        # `WritebackRunner._cleanup` (komentarz tam).
        if self._plan_thread is None:
            return
        self._plan_worker.deleteLater(); self._plan_thread.wait(); self._plan_thread.deleteLater()
        self._plan_worker = None; self._plan_thread = None
        if self._zamknij_po_planie is not None:
            # Zamknięcie zażądane w trakcie planu (okno już schowane) - wątek skończył, więc teraz;
            # okno po `exec` czekało na ten wątek z kasacją (`_zwolnij_gdy_wolne`).
            wynik, self._zamknij_po_planie = self._zamknij_po_planie, None
            self.done(wynik)
            self._zwolnij_gdy_wolne()
            return
        self._sync_akcji()

    @Slot(int, object)
    def _on_plan_done(self, gen, payload):
        if gen != self._gen:
            return                              # plan sprzed nowszego zamówienia
        self._plan, self._korzen, self._drogi = payload
        self._wypelnij()
        self._sync_akcji()

    @Slot(int, object)
    def _on_plan_failed(self, gen, powod):
        """Wyjątek planu (`PlanWorker`, `powod_okna`): błąd systemu albo bazy klasą w języku UI
        (`tekst_powodu`), surowy tekst systemu pod kursorem (`wiersz_systemu`, AR-184); EXPECT
        planera (goły `ValueError`, `AssertionError`) - błąd programu w języku UI, proza rdzenia
        w szczególe technicznym (AR-209)."""
        if gen != self._gen:
            return
        self.counts.setText("")
        self.error.ustaw(i18n.t("objchg.err.plan", msg=tekst_powodu(powod)),
                         szczegol_powodu(powod))          # system + numer operacji (AR-281)
        self._sync_akcji()

    def _kolumna_po_zmianie(self, sciezki):
        """„Po zmianie” bez ani jednej ścieżki (same „bez przeniesienia” - zmiana karty i bazy
        w miejscu) bierze szerokość swojej treści, a resztę dostaje „Plik dziś”; inaczej obie
        kolumny ścieżek dzielą szerokość po równo. Po biegu „Jest” zawsze niesie ścieżki."""
        self.items_tree.header().setSectionResizeMode(
            _COL_NOWA, QHeaderView.Stretch if sciezki else QHeaderView.ResizeToContents)

    def _wypelnij(self):
        """Plan → lista pozycji, ostrzeżenia, pominięcia (pogrupowane po powodzie) i liczby."""
        plan = self._plan
        self.items_tree.clear()
        self._naglowki(po_biegu=False)
        self.items_tree.setColumnHidden(_COL_STATUS, True)
        self._kolumna_po_zmianie(any(it.new_path for it in plan.items))
        self._wiersze = {}
        self._status_wiersza = {}       # nowy plan: wiersze bez historii biegu
        self._jest = {it.location_id: it.old_path for it in plan.items}
        self.plan_note.setText(tekst_planu(plan))
        self.plan_note.setVisible(bool(self.plan_note.text()))
        for it in plan.items:
            droga = self._drogi.get(it.location_id, _DROGA_NIEZNANA)
            w = QTreeWidgetItem(["", "", self._tekst_karty(it.card_op, it.card_old, it.card_new,
                                                           it.old_path, droga,
                                                           tylko_odczyt=it.card_read_only)])
            ustaw_sciezke(w, _COL_STARA, it.old_path, self._korzen)
            if it.new_path:
                ustaw_sciezke(w, _COL_NOWA, it.new_path, self._korzen)
            else:
                w.setText(_COL_NOWA, i18n.t("objchg.no_move"))
                w.setToolTip(_COL_NOWA, i18n.t("objchg.no_move"))
            if it.mkdirs:
                w.setToolTip(_COL_NOWA, (it.new_path or "") + "\n"
                             + i18n.t("objchg.mkdirs_tip", dirs="\n".join(it.mkdirs)))
            self._podpowiedz_karty(w, it.card_op, it.old_path, droga)
            w.setData(_COL_STARA, Qt.UserRole, it.frame_id)
            self.items_tree.addTopLevelItem(w)
            self._wiersze[it.location_id] = w
        self._dopasuj_karte()
        # Zdanie ogólne pod listą - wyłącznie dla dopisań, których drogi lustro nie przewidziało;
        # przewidziana droga stoi przy swojej pozycji (AR-155).
        self.card_note.setText(i18n.t("objchg.card_add_fits"))
        self.card_note.setVisible(any(
            self._dopisanie_fits(it.card_op, it.old_path)
            and self._rodzaj_drogi(self._drogi.get(it.location_id, _DROGA_NIEZNANA)) is None
            for it in plan.items))

        ostrzezenia = [tekst_ostrzezenia(o.code, o.params, o.text) for o in plan.warnings]
        self.warnings.setText("\n".join(ostrzezenia))
        self.warnings.setVisible(bool(ostrzezenia))

        self.skipped_tree.clear()
        grupy = {}
        # Pozycje „bez zmian” planer oddaje jako pominięcia, ale odmową nie są - stoją w liczbach
        # („bez zmian: N”), a lista pominięć niesie wyłącznie to, czego gest NIE zrobi z powodu.
        pominiete = [s for s in plan.skipped if not bez_zmian(s)]
        for s in pominiete:                          # zdanie w języku UI (kod pominięcia)
            grupy.setdefault(tekst_pominiecia(s.code, s.params, s.reason), []).append(s)
        # Najliczniejszy powód na górze - 300 plików z jednym powodem to jeden wiersz, nie 300.
        for powod, lista in sorted(grupy.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            g = QTreeWidgetItem([powod, str(len(lista))])
            g.setToolTip(_COL_POWOD, podpowiedz_pominiecia(lista[0].code, lista[0].params, powod))
            for s in lista:
                d = QTreeWidgetItem(["", ""])
                ustaw_sciezke(d, _COL_POWOD, s.path, self._korzen)
                g.addChild(d)
            self.skipped_tree.addTopLevelItem(g)
        self.skipped_head.setText(i18n.t_plural("objchg.skipped_head", len(pominiete)))
        self.skipped_head.setVisible(bool(pominiete))
        self.skipped_tree.setVisible(bool(pominiete))
        self._dopasuj_pominiecia()
        wiele_kopii = any(s.code == "many_copies" for s in pominiete)
        self.copies_hint.setText(i18n.t("objchg.many_copies_hint", recipe=recepta_duplikatow())
                                 if wiele_kopii else "")
        self.copies_hint.setVisible(wiele_kopii)
        self.counts.setText(i18n.t("objchg.counts", **liczby_planu(plan)))
        self.counts.setToolTip(i18n.t("objchg.rmdirs_tip", dirs="\n".join(plan.rmdirs))
                               if plan.rmdirs else "")
        self.routes.setText(i18n.t("objchg.routes", **sumy_drog(plan, self._drogi)))
        self.routes.setVisible(any(it.card_op for it in plan.items))
        self.counts.setVisible(True)

    def _wczytaj_przebieg(self, przebieg):
        """Wejście z Porządków (AR-121): lista z bazy w mowie listy po biegu - „Było” = ścieżka
        z podglądu, „Jest” = gdzie lokacja stoi teraz, status pozycji z powodem; karta = wpis
        stagingu tego przebiegu (pozycja bez wpisu kartą nie płaciła - kolumna milczy); pozycja
        czekająca mówi, DOKĄD pojedzie plik - na tym człowiek decyduje o zapisie. Stan akcji jak po
        przerwanym biegu w oknie: „Dokończ” przy przebiegu `staged` (z liczbą czekających, także
        przy zerze), „Cofnij” cofa cały przebieg. Planu nie ma - świeży liczy się dopiero po
        pełnym cofnięciu („Policz plan ponownie”, na klatkach przebiegu)."""
        self._run_id = przebieg["run_id"]
        self._pozostalo = przebieg["pending"]
        self._dokonczenie = przebieg["can_finish"]
        self._stan_przebiegu = {"staged": "staged", "undoing": "undoing"}.get(przebieg["status"],
                                                                              "failed")
        self._do_cofniecia = True
        self._domkniety = True
        self._wynik_na_liscie = True
        self._korzen = resolver.library_root_from_db(self.con)
        self._naglowki(po_biegu=True)
        self.items_tree.setColumnHidden(_COL_STATUS, False)
        self._kolumna_po_zmianie(True)
        for it in przebieg["items"]:
            if it["status"] == "pending" and it["new_path"]:
                stan = i18n.t("objchg.st.pending_to",
                              path=sciezka_pod_korzeniem(it["new_path"], self._korzen))
            else:
                stan = i18n.t(_STATUS_POZYCJI[it["status"]])
            status, tip = status_pozycji(stan, it["reason"], z_bazy=True)
            self._status_wiersza[it["location_id"]] = (status, tip)
            # RAW mówi „format tylko do odczytu” także na liście przebiegu z Porządków (OB11).
            karta = (self._tekst_karty(it["card_op"], it["card_old"], it["card_new"],
                                       it["old_path"]) if it["card_op"]
                     else i18n.t("objchg.card_read_only") if it["card_read_only"] else "")
            w = QTreeWidgetItem(["", "", karta, status])
            ustaw_sciezke(w, _COL_STARA, it["old_path"], self._korzen)
            ustaw_sciezke(w, _COL_NOWA, it["path"], self._korzen)
            w.setToolTip(_COL_STATUS, tip)
            self._podpowiedz_karty(w, it["card_op"], it["old_path"])
            w.setData(_COL_STARA, Qt.UserRole, it["frame_id"])
            self.items_tree.addTopLevelItem(w)
            self._wiersze[it["location_id"]] = w
            self._jest[it["location_id"]] = it["path"]
        self._dopasuj_karte()
        self.counts.setVisible(False)
        self.routes.setVisible(False)          # przebieg z bazy mówi stan, nie prognozę
        self.plan_note.setVisible(False)
        self.status.setText(i18n.t("objchg.res.run", run_id=self._run_id).lstrip(" ·"))
        self._sync_akcji()

    def _pokaz_wynik(self, res, *, cofniecie):
        """Wynik biegu (`ObjectChangeResult`) na liście: „Było” = gdzie plik stał przed biegiem,
        „Jest” = gdzie stoi po nim (ścieżka z wyniku rdzenia), „Status” = co się stało z pozycją
        i dlaczego. Dopasowanie po `location_id` - jedyna tożsamość pozycji wspólna dla planu
        i wyniku. Pozycja, której wynik nie zna, zachowuje swój ostatni status: „Dokończ” niesie
        w wyniku wyłącznie pozycje, które czekały, a te zapisane przed przerwaniem (poprzedni bieg
        albo przebieg z Porządków) „nie ruszonymi” nie są (bramka, kimi). „Nie ruszona” zostaje
        dla pozycji bez historii - bieg przerwany przed nią. Liczby podglądu mówiły w czasie
        przyszłym, więc po biegu chowają się (czas przeszły niesie zdanie wyniku), a nagłówek
        pominięć przechodzi w czas przeszły."""
        if cofniecie:
            statusy = {"applied": "objchg.st.undone", "blocked": "objchg.st.blocked",
                       "failed": "objchg.st.failed", "skipped": "objchg.st.skipped"}
        else:
            statusy = {"applied": "objchg.st.done", "blocked": "objchg.st.blocked",
                       "failed": "objchg.st.failed", "skipped": "objchg.st.skipped",
                       "withheld": "objchg.st.withheld"}
        wyniki = {fr.location_id: (klucz, fr) for klucz, lista in (
            ("applied", res.applied), ("blocked", res.blocked), ("failed", res.failed),
            ("skipped", res.skipped),
            ("withheld", [] if cofniecie else res.withheld)) for fr in lista}
        self._naglowki(po_biegu=True)
        self.items_tree.setColumnHidden(_COL_STATUS, False)
        self._kolumna_po_zmianie(True)
        for lid, w in self._wiersze.items():
            bylo = self._jest.get(lid, "")
            klucz, fr = wyniki.get(lid, (None, None))
            jest = (fr.path or bylo) if fr is not None else bylo
            self._jest[lid] = jest
            if klucz:
                status, tip = status_pozycji(i18n.t(statusy[klucz]), fr.reason, fr.code)
            else:
                nietkniety = i18n.t("objchg.st.untouched")
                status, tip = self._status_wiersza.get(lid) or (nietkniety, nietkniety)
            self._status_wiersza[lid] = (status, tip)
            ustaw_sciezke(w, _COL_STARA, bylo, self._korzen)
            ustaw_sciezke(w, _COL_NOWA, jest, self._korzen)
            w.setText(_COL_STATUS, status)
            w.setToolTip(_COL_STATUS, tip)
        self.counts.setVisible(False)
        self.routes.setVisible(False)         # prognoza dróg też - drogę pliku mówi teraz jego status
        self.warnings.setVisible(False)       # ostrzeżenia planera mówią w czasie przyszłym, jak liczby
        self.card_note.setVisible(False)      # zdanie podglądu; drogę pliku mówi teraz jego status
        self.plan_note.setVisible(False)      # zapowiedź planu - czas przeszły niesie zdanie wyniku
        pominiete = sum(g.childCount() for g in (self.skipped_tree.topLevelItem(i)
                                                 for i in range(self.skipped_tree.topLevelItemCount())))
        self.skipped_head.setText(i18n.t_plural("objchg.skipped_head_done", pominiete))

    def _dopasuj_pominiecia(self):
        """Lista pominięć HUGGUJE swoje wiersze (z sufitem `_POMINIECIA_MAX_PX`): jeden powód to
        jeden wiersz, a domyślna podpowiedź drzewa (~190 px) zabierała liście pozycji pion, którego
        ta potrzebuje. Rozwinięcie powodu liczy wysokość od nowa (pliki pod nim mają być widać),
        a wiele plików dostaje suwak pod sufitem. Wiersze są równe (`setUniformRowHeights`), więc
        liczba widocznych wierszy razy wysokość jednego wystarcza."""
        t = self.skipped_tree
        wiersz = t.sizeHintForRow(0) if t.sizeHintForRow(0) > 0 else t.fontMetrics().height() + 4
        widoczne = sum(1 + (g.childCount() if g.isExpanded() else 0)
                       for g in (t.topLevelItem(i) for i in range(t.topLevelItemCount())))
        h = t.header().sizeHint().height() + widoczne * wiersz + 2 * t.frameWidth() + 4
        t.setFixedHeight(min(_POMINIECIA_MAX_PX, h))

    # Sufit kolumny karty: część szerokości okna. Reszta należy do ścieżek (podgląd) i statusu
    # (po biegu) - o tym, który plik i co się z nim stało, mówią one, nie karta.
    _KARTA_MAX_UDZIAL = 0.34

    def _dopasuj_karte(self):
        """Kolumna karty = szerokość najdłuższej treści (wiersze i nagłówek) z sufitem
        `_KARTA_MAX_UDZIAL` szerokości okna; dłuższa karta elizuje się, pełna treść jest
        w podpowiedzi komórki. Liczone z metryki fontu listy, nie z `sizeHintForColumn` - ten
        widzi tylko wiersze w polu widoku, a lista wypełnia się także przed pokazaniem okna."""
        t = self.items_tree
        fm = t.fontMetrics()
        teksty = [t.topLevelItem(i).text(_COL_KARTA) for i in range(t.topLevelItemCount())]
        teksty.append(t.headerItem().text(_COL_KARTA))
        tresc = max(fm.horizontalAdvance(x) for x in teksty) + 3 * fm.averageCharWidth()
        t.setColumnWidth(_COL_KARTA, min(tresc, int(self.width() * self._KARTA_MAX_UDZIAL)))

    @staticmethod
    def _dopisanie_fits(card_op, path):
        """Pozycja DOPISUJE kartę do FITS - jej droga zapisu zależy od zapasu nagłówka
        (`drogi_dopisania`, `_tekst_karty`)."""
        return card_op == "add" and not path.lower().endswith(_XISF)

    @staticmethod
    def _rodzaj_drogi(droga):
        """Przewidziana droga dopisania (`drogi_dopisania`) → `"inplace"` (w miejscu), `"rewrite"`
        (cały plik przepisany) albo None - zależy od pliku: lustro nie rozstrzyga albo prognozy nie
        ma (przebieg z bazy mówi stan historyczny, nie prognozę)."""
        if droga is None:
            return "inplace"
        if droga is _DROGA_NIEZNANA:
            return None
        return "rewrite" if getattr(droga, "code", None) == "fb_no_room" else None

    def _podpowiedz_karty(self, w, card_op, path, droga=_DROGA_NIEZNANA):
        """Podpowiedź komórki karty: jej pełna treść, a przy dopisaniu do FITS także pełne zdanie
        o drodze zapisu (w komórce stoi krótki znacznik) - przewidzianej dla tej pozycji albo
        ogólne „zależy od pliku”. `droga` jak w `_tekst_karty`."""
        tekst = w.text(_COL_KARTA)
        if self._dopisanie_fits(card_op, path):
            rodzaj = self._rodzaj_drogi(droga)
            if rodzaj == "inplace":
                zdanie = i18n.t("objchg.card_add_fits_inplace")
            elif rodzaj == "rewrite":
                zdanie = i18n.t("objchg.card_add_fits_rewrite", reason=tekst_powodu(droga))
            else:
                zdanie = i18n.t("objchg.card_add_fits")
            tekst = f"{tekst}\n{zdanie}"
        w.setToolTip(_COL_KARTA, tekst)

    @staticmethod
    def _tekst_karty(card_op, card_old, card_new, path, droga=_DROGA_NIEZNANA, tylko_odczyt=False):
        """Karta `OBJECT` pozycji: stara → nowa, albo stan bez zmiany (karta już w formie albo
        format bez karty - RAW, `tylko_odczyt` z pozycji planu: komórka mówi, że format jest tylko
        do odczytu, a nie gołe „bez karty”). DOPISANIE karty do FITS niesie KRÓTKI znacznik drogi
        zapisu (AR-155) z prognozy pozycji `droga` (`drogi_dopisania`): „w miejscu” (`None` -
        nagłówek ma wolny rekord za `END`), „cały plik przepisany” (`fb_no_room` - pełny ostatni blok bez
        pustej karty) albo ogólne „dopisanie karty” (`objchg.card_add_fits_short`), gdy lustro kart
        nie rozstrzyga albo prognozy nie ma (`_DROGA_NIEZNANA` - domyślnie; przebieg z bazy pokazuje
        stan historyczny, nie prognozę). Pełne zdanie stoi w podpowiedzi komórki, a ogólne
        (`objchg.card_add_fits`) raz pod listą - tylko dla pozycji „zależy od pliku”. Ostatnie
        słowo ma pisarz na pliku (plik zmieniony od skanu, odmowa reguły karty) - drogę, którą
        plik naprawdę poszedł, podaje zdanie wyniku. Pełne zdanie w każdym wierszu zabierało
        kolumnie ścieżek szerokość (zmierzone natywnie przy 1100 px okna)."""
        if card_op is None:
            if tylko_odczyt:            # RAW: karty nie zapisujemy z definicji formatu (OB11)
                return i18n.t("objchg.card_read_only")
            return (i18n.t("objchg.card_kept", value=repr(card_old)) if card_old
                    else i18n.t("objchg.card_none"))
        stara = repr(card_old) if card_old is not None else i18n.t("objchg.card_absent")
        tekst = i18n.t("objchg.card_change", old=stara, new=repr(card_new))
        if ObjectChangeDialog._dopisanie_fits(card_op, path):
            rodzaj = ObjectChangeDialog._rodzaj_drogi(droga)
            tekst += i18n.t({"inplace": "objchg.card_add_fits_inplace_short",
                             "rewrite": "objchg.card_add_fits_rewrite_short"}.get(
                                 rodzaj, "objchg.card_add_fits_short"))
        return tekst

    # ---------------------------------------------------------------- stan akcji
    def _wolny(self):
        return (not self._runner.is_busy and not self._pipeline_busy
                and self._plan_thread is None)

    def _sync_akcji(self):
        """Przycisk akcji mówi, ILE pozycji pójdzie do zapisu - szczery disabled przy zerze, w biegu
        planu, zapisu i etapu Dostawy. Po przerwaniu przebiegu ta sama akcja DOKAŃCZA go (pozycje
        nieprzetworzone czekają w bazie jako oczekujące; przebieg `staged` bez czekających też -
        sterownik go domknie), a po udanym zapisie milczy do „Cofnij”. Okno przebiegu z Porządków,
        w którym nie ma czego dokańczać (cofanie przerwane, pozycja z błędem, przebieg domknięty),
        chowa przycisk akcji: zostaje „Cofnij” i „Zamknij”, a martwy „Zmień obiekt” nie udaje drogi
        (wizytacja W2). Nagłówek i opis nadążają za stanem (`_opisz_stan`)."""
        wolny = self._wolny()
        self.action_btn.setVisible(not (self._przebieg is not None and self._run_id is not None
                                        and not (self._pozostalo or self._dokonczenie)))
        if self._pozostalo or self._dokonczenie:
            self.action_btn.setText(i18n.t("objchg.finish_btn", n=self._pozostalo)
                                    if self._pozostalo else i18n.t("objchg.finish_btn_bare"))
            self.action_btn.setEnabled(wolny)
            self.action_btn.setToolTip("")
        elif self._wynik_na_liscie and self._run_id is None:
            # Lista niesie wynik biegu, a przebiegu do cofnięcia nie ma (cofnięty albo nic nie
            # zmienił) - następnym krokiem jest świeży plan na dzisiejszym stanie.
            self.action_btn.setText(i18n.t("objchg.replan_btn"))
            self.action_btn.setEnabled(wolny)
            self.action_btn.setToolTip("")
        else:
            n = liczby_planu(self._plan)["robota"] if self._plan is not None else 0
            # Licznik mówi, ile ZOSTAŁO do zapisania - po wykonaniu liczba znika razem z sensem
            # drugiego kliknięcia (lekcja okna „Napraw nagłówek…”).
            licznik = bool(n) and not self._domkniety
            if self._target is not None:
                tekst = (i18n.t("objchg.action_change", n=n) if licznik
                         else i18n.t("objchg.action_change_bare"))
            else:
                tekst = (i18n.t("objchg.action_align", n=n) if licznik
                         else i18n.t("objchg.action_align_bare"))
            self.action_btn.setText(tekst)
            self.action_btn.setEnabled(wolny and licznik)
            self.action_btn.setToolTip(
                "" if n or self._plan is None or self._domkniety else i18n.t("objchg.nothing_tip"))
        self.undo_btn.setVisible(self._do_cofniecia)
        self.undo_btn.setEnabled(wolny)
        if self._przebieg is not None:
            self._opisz_stan()

    def set_pipeline_busy(self, busy):
        """Etap Dostawy w biegu → akcje zapisu gasną (okno modalne, poza `set_busy` widoku).

        PO ZBOCZU busy → wolne plan liczy się od nowa, o ile okno nie ma przebiegu (nic w biegu, nic
        do dokończenia ani cofnięcia): etap mógł przeskanować pliki z listy i podgląd sprzed niego
        obiecywałby kotwice, które zapis odbije. Przebiegu nie ruszamy - jego stan niesie baza."""
        bylo = self._pipeline_busy
        self._pipeline_busy = bool(busy)
        if (bylo and not busy and self._run_id is None and not self._runner.is_busy
                and self._plan_thread is None and not self._wynik_na_liscie):
            self._licz_plan()
            return
        self._sync_akcji()

    # ---------------------------------------------------------------- zapis
    def _on_action(self):
        """Staging planu z podglądu i JEDNA operacja uchwytu. Po przerwaniu - ten sam przebieg
        od pierwszej nieprzetworzonej pozycji, bez drugiego stagingu (rdzeń odtwarza go z bazy)."""
        if not self._wolny():
            return
        self.error.clear()
        if self._wynik_na_liscie and self._run_id is None and not self._pozostalo:
            self._licz_plan()                   # „Policz plan ponownie” - zapis dopiero z planu
            return
        if self._pozostalo or self._dokonczenie:
            total = self._pozostalo             # 0: sterownik tylko domknie przebieg `staged`
        else:
            if self._plan is None or self._domkniety or not liczby_planu(self._plan)["robota"]:
                return
            # Staging na wątku okna: jedna transakcja na wierszach planu, bez dysku. Odmowa
            # klingi (`ValueError`), błąd bazy (`sqlite3.Error`: zajęta, drugi staging tego
            # przebiegu) i błąd programu zostawiają okno z powodem i zero zapisu - transakcja
            # wycofuje się cała na każdym wyjątku (`repo._immediate`), więc wyjątek nie ucieka ze slotu.
            try:
                repo.stage_object_change(self.con, plan=self._plan, now=self._now())
            except Exception as e:
                self.error.ustaw(*zdanie_odmowy_stagingu(e))
                return
            self._run_id = self._plan.run_id
            total = len(self._plan.items)
        self._domkniety = True
        self._w_biegu = total
        self._zacznij_ture(self._run_id)
        self._begin_progress(total)
        self._runner.start("object_change", self._run_id, on_progress=self._on_progress,
                           on_done=self._after_commit, on_failed=self._on_failed)

    def _begin_progress(self, total):
        """Pasek na czas zapisu i cofnięcia; `total=0` = nieokreślony (cofnięcie nie zna liczby
        z góry). Akcje gasną do końca biegu."""
        self.bar.setRange(0, total)
        self.bar.setValue(0)
        self.bar.setVisible(True)
        self.action_btn.setEnabled(False)
        self.undo_btn.setEnabled(False)

    def _on_progress(self, done, total, path, status):
        if self.bar.maximum() != total:
            self.bar.setRange(0, total)
        self.bar.setValue(done)
        self.status.setText(tekst_postepu(self.status, done, total,
                                          sciezka_pod_korzeniem(path, self._korzen),
                                          glowa_sciezki(path, self._korzen)))

    def _after_commit(self, op, res):
        """Wynik przebiegu: lista z wynikiem per wiersz, zdanie, „Cofnij”, gdy cokolwiek się
        zmieniło, i „Dokończ” po przerwaniu (pozycje nieprzetworzone)."""
        self.bar.setVisible(False)
        self.status.setText(zdanie_wyniku_zmiany(res))
        self._pokaz_wynik(res, cofniecie=False)
        self._wynik_na_liscie = True
        self._do_cofniecia = self._do_cofniecia or ruszyl_cokolwiek(res)
        przetworzone = (len(res.applied) + len(res.blocked) + len(res.failed) + len(res.skipped)
                        + len(res.withheld))
        if res.cancelled:
            # „Dokończ (N)” liczy pozycje, których przerwany bieg nie dotknął - z liczby, z którą
            # ten bieg ruszył (cały plan albo reszta po poprzednim przerwaniu).
            self._pozostalo = max(self._w_biegu - przetworzone, 0)
        else:
            self._pozostalo = 0
        # Przerwany bieg zostawia przebieg `staged` (sterownik domyka go wyłącznie na końcu listy);
        # bieg do końca - domknięty, a pozycja z błędem zostawia stan częściowy do cofnięcia.
        self._dokonczenie = res.cancelled
        self._stan_przebiegu = ("staged" if res.cancelled else "failed" if res.failed else None)
        if not self._do_cofniecia and not self._pozostalo:
            # Przebieg niczego nie zmienił (same blokady i pominięcia): nie ma czego cofać ani
            # dokańczać. Lista zostaje z powodami blokad, a akcja proponuje świeży plan na
            # dzisiejszym stanie zamiast martwego przycisku.
            self._run_id = None
            self._domkniety = False
        self.summary = self._zdanie_paska(res, cofniecie=False)   # po stanie: droga powrotu z niego
        self.changed.emit()
        self._sync_akcji()

    def _zacznij_ture(self, run_id):
        """Start tury zapisu albo cofnięcia: przebieg tury zapamiętany na zdanie paska (stan okna
        `_run_id` po turze bywa już zgaszony), a zdanie paska poprzedniej tury zdjęte - tura, która
        padnie wyjątkiem, nie zostawi na pasku cudzego wyniku (OB12, Z4)."""
        self._przebieg_tury = run_id
        self.summary = ""

    def _zdanie_paska(self, res, *, cofniecie):
        """Zdanie paska po zamknięciu okna (`zdanie_paska`, OB12) z TRWAŁEGO stanu przebiegu tury
        (`queries.object_change_run_view`), nie z wyniku ostatniej tury: liczba pozycji `applied`
        (zapis) albo `undone` (cofnięcie) sumuje „Dokończ” i ponowione cofnięcie, a obiekt z chwili
        podglądu (`before_canon`, zapisany przy stagingu) daje „z X” i „wróciło do X” także przy
        wznowieniu z Porządków, gdy baza ma już nowy obiekt. `res=None` - wyjątek workera.

        DROGA POWROTU: przebieg na liście Porządków (`interrupted_object_change_runs` - ten sam
        predykat co ich wiersz: przerwany także przed pierwszą pozycją, cofanie niedomknięte,
        pozycja w błędzie) → Porządki, bez względu na to, czy tura coś zmieniła. Przebieg domknięty,
        który zostawił coś do cofnięcia, po zamknięciu okna cofa wyłącznie CLI po numerze -
        polecenie stoi w SZCZEGÓLE zdania pod kursorem paska (AR-272: pełna ścieżka bazy w pasku ginęła
        w elizji razem z numerem), a w zdaniu krótki człon."""
        run_id = self._przebieg_tury
        widok = queries.object_change_run_view(self.con, run_id)
        assert widok is not None, f"brak przebiegu zmiany obiektu {run_id!r}"
        liczone = [it for it in widok["items"]
                   if it["status"] == ("undone" if cofniecie else "applied")]
        stare = {it["before_canon"] for it in liczone}
        przed = next(iter(stare)) if len(stare) == 1 else None
        droga = ("", "", "")
        if run_id in queries.interrupted_object_change_runs(self.con):
            droga = (i18n.t("objchg.bar.tasks", nav=i18n.t("nav.porzadki"),
                            row=i18n.t("tasks.object_change_interrupted")), "", "")
        elif self._run_id is not None and self._do_cofniecia and self._db_path:
            polecenie = i18n.t("objchg.cli_undo", db=self._db_path, run_id=run_id)
            droga = (i18n.t("objchg.bar.undo_short", copy=i18n.t("wb.copy_command")),
                     i18n.t("objchg.bar.undo_cli", run_id=run_id, cli=polecenie), polecenie)
        return zdanie_paska(res, target=self._target, n=len(liczone), przed=przed,
                            obiekty=self._obiekty, cofniecie=cofniecie, droga=droga)

    def _on_failed(self, op, msg, podpowiedz):
        """Wyjątek workera. Przebieg jest w bazie, więc okno bierze stan stamtąd, nie z pamięci:
        po wyjątku ZAPISU „Cofnij” zostaje (cofnięcie przy niczym do zrobienia mówi „0”), a „Dokończ”
        stoi, dopóki przebieg jest `staged` (liczy pozycje, które w bazie wciąż czekają - także
        zero, gdy wyjątek padł po ostatniej pozycji); po wyjątku COFNIĘCIA dokańczać nie ma czego
        (cofnięty przebieg zapisu nie wznawia), zostaje ponowienie „Cofnij”. Szczegół systemu
        (`podpowiedz`, AR-185) - pod kursorem pola błędu; następne zdanie go zdejmuje."""
        self.bar.setVisible(False)
        if self._run_id is not None:
            self._do_cofniecia = True
            if op == "object_change":
                widok = queries.object_change_run_view(self.con, self._run_id)
                self._pozostalo, self._dokonczenie = widok["pending"], widok["can_finish"]
                self._stan_przebiegu = "staged" if widok["can_finish"] else "failed"
            else:
                self._pozostalo, self._dokonczenie = 0, False
                self._stan_przebiegu = "undoing"
        self.error.ustaw(i18n.t("grid.wb.error", msg=czytelny_powod(msg))
                         + (i18n.t("objchg.res.run", run_id=self._run_id) if self._run_id else ""),
                         podpowiedz)
        if self._przebieg_tury is not None:
            # Wyniku tury nie ma - pasek mówi z utrwalonego widoku przebiegu: ile pozycji naprawdę
            # zmienionych (albo cofniętych) i droga przez Porządki (Z4).
            self.summary = self._zdanie_paska(None, cofniecie=op != "object_change")
        self._sync_akcji()
        self.changed.emit()

    # ---------------------------------------------------------------- cofnięcie (okno do zamknięcia)
    def _on_undo(self):
        if self._run_id is None or not self._wolny():
            return
        self.error.clear()
        self._zacznij_ture(self._run_id)
        self._begin_progress(0)
        self._runner.start("undo_object_change", self._run_id, on_progress=self._on_progress,
                           on_done=self._after_undo, on_failed=self._on_failed)

    def _after_undo(self, op, res):
        """Wynik cofnięcia na liście (Było / Jest / Status per wiersz) i w zdaniu. Cofnięcie, które
        czegoś nie cofnęło (blokada, błąd), zostawia „Cofnij” - ponowienie wznawia pierwszą
        niedomkniętą fazę pozycji (rdzeń). Pełne cofnięcie zużywa przebieg: „ponownie” to świeży
        plan i nowy przebieg („Policz plan ponownie”), nie powtórka starego."""
        self.bar.setVisible(False)
        self.status.setText(zdanie_wyniku_zmiany(res, cofniecie=True))
        self._pokaz_wynik(res, cofniecie=True)
        self._wynik_na_liscie = True
        niedomkniete = bool(res.blocked or res.failed or res.cancelled)
        self._do_cofniecia = niedomkniete
        self._pozostalo = 0          # po cofnięciu „Dokończ” przebiegu nie ma już czego dokańczać
        self._dokonczenie = False
        self._stan_przebiegu = "undoing" if niedomkniete else None
        if not niedomkniete:
            self._run_id = None
            self._domkniety = False
        self.summary = self._zdanie_paska(res, cofniecie=True)
        self.changed.emit()
        self._sync_akcji()

    # ---------------------------------------------------------------- zamknięcie
    def done(self, r):
        """KAŻDA droga zamknięcia przechodzi tędy. W biegu zapisu okno ZOSTAJE (`refuse_close`:
        wątek zapisu jest dzieckiem okna, a raport przerwania musi mieć dokąd trafić).

        PLAN W BIEGU: okno znika od razu, a zamyka się, gdy wątek planu skończy
        (`_cleanup_plan_thread`). Czekanie tu na wątek zamroziłoby okno na czas odczytu katalogów
        po SMB (bez limitu), a zabicie go pod kasowanym rodzicem to twardy abort. Wynik planu, który
        jeszcze przyjdzie, idzie do kosza (nowa generacja). Schowanie kończy `exec` gospodarza przy
        żywym wątku - dlatego kasacja okna czeka na wątek (`_zwolnij_gdy_wolne`)."""
        if self._runner.refuse_close(self.error.setText):
            return
        if self._plan_thread is not None:
            self._gen += 1
            self._zamknij_po_planie = r
            self.hide()
            return
        super().done(r)

    def exec(self):
        """Modalny bieg okna i jego KASACJA, gdy wolne (`_zwolnij_gdy_wolne`). Każde wejście buduje
        nowe okno z rodzicem-gospodarzem, więc bez kasacji każde zamknięte okno zostawało dzieckiem
        gospodarza (z wątkami i uchwytem zapisu) do końca sesji. `deleteLater`, nie
        `WA_DeleteOnClose`: gospodarz czyta okno PO `exec` (`summary`, zdanie stanu), a odroczona
        kasacja przychodzi w pętli zdarzeń gospodarza, po jego slocie.

        `exec` wraca TAKŻE przy żywym wątku planu: zamknięcie w trakcie planu chowa okno (`done`),
        a ukrycie modalnego okna kończy pętlę `exec` (Qt: `setVisible(false)` → `exit`). Kasacja
        z dzieckiem `QThread` w biegu to `qFatal` („Destroyed while thread is still running”), więc
        okno czeka na koniec wątku - kasuje je wtedy `_cleanup_plan_thread`; do tego czasu wątek
        zbiera gospodarz przy wyjściu (`zatrzymaj_pola`). Wzorzec
        `harvest_dialog.HarvestDialog._zwolnij_gdy_wolne`."""
        try:
            return super().exec()
        finally:
            self._po_exec = True
            self._zwolnij_gdy_wolne()

    def _zwolnij_gdy_wolne(self):
        """Okno po `exec` bez żywego wątku (plan, zapis) kasuje się samo (`deleteLater`); z wątkiem
        w biegu - robi to sprzątanie wątku planu. Raz na okno. Okno bez `exec` (testy, osadzenie)
        nie kasuje się samo."""
        if (self._po_exec and not self._zwolnione and self._plan_thread is None
                and not self._runner.is_busy):
            self._zwolnione = True
            self.deleteLater()

    def zatrzymaj_pola(self):
        """Okno znika razem z gospodarzem (zamknięcie aplikacji, przełączenie bazy -
        `MainWindow._zatrzymaj_watki_widokow` woła tę metodę po nazwie): ZBIERZ wątek planu, zanim
        rodzic go skasuje - `QThread` niszczony w biegu to twardy abort. Planer nie ma punktu
        przerwania (odczyt katalogów po SMB), więc czekanie bez limitu żyje tu, poza gestem
        człowieka. Generacja w górę: wynik, który zdążył wyjść z wątku, nie dotknie okna.
        Idempotentne."""
        self._gen += 1
        watek, worker = self._plan_thread, self._plan_worker
        if watek is None:
            return
        self._plan_thread = self._plan_worker = None
        watek.quit()
        worker.deleteLater()
        while not watek.wait(100):
            pass
        watek.deleteLater()
