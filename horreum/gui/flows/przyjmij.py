"""Strona Dostawy drogi Przyjmij - kontener nad TYM SAMYM `PipelineView`, którym jest Dostawa.

Przyjmij nie jest drugim widokiem Dostawy: wątek etapów, mutex zapisu nagłówków i przyciski zostają
w `PipelineView` (jeden stan ekranu, wzorzec `ZnajdzView` nad `FramesView`), a ta strona dokłada nad
nim panel „Co przyszło”. Panel liczy się ze STANU bazy po przebiegu (`queries.delivery_report` od
znacznika `since` zapisu przebiegu), nie z liczników eventów - liczby skanu (kopie znanych klatek,
pliki bez zmian) bierze z wyniku skanu, bo stan bazy ich nie pamięta. Do pierwszego przebiegu „all”
w tej sesji panel jest ukryty: pusty raport przed dostawą udawałby dostawę bez klatek.

Gest „Przypisz obiekt…” stoi przy wierszu nierozpoznanej nazwy, bo tam człowiek ją widzi. Populacja
i klinga są te same, co w Porządkach (`queries.object_review_frames` → `repo.user_assign_object`),
więc alias zapamiętany tutaj rozpoznaje następną dostawę tym samym szczeblem resolvera. Kubełki bez
nazwy mają naprawę w Porządkach (karta w pliku, ręka na RAW-ach) - ich wiersz prowadzi tam ze
wskazanym kubełkiem, nie na listę zadań, w której trzeba by go dopiero szukać.
"""

from datetime import datetime

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton,
                               QVBoxLayout, QWidget)

from horreum import repo
from horreum.gui import busy, i18n, portfolio, queries
from horreum.gui.assign_dialog import AssignObjectDialog
from horreum.gui.grid import zdanie_pominiec
from horreum.gui.pipeline import _stage_label
from horreum.gui.wb_worker import EtykietaBledu       # zdanie + szczegół awarii etapu (AR-198)
from horreum.resolve._text import norm_alnum

__all__ = ["PrzyjmijView"]

# Ile obiektów i ile nierozpoznanych nazw panel wylicza z imienia. Reszta idzie jednym członem
# „i N innych”: pierwsza dostawa na pustą bazę niesie setki nazw, a panel stoi NAD akcjami Dostawy -
# lista bez sufitu zepchnęłaby je z ekranu.
_WIDOCZNE_OBIEKTY = 8
_WIDOCZNE_NAZWY = 8

# Tagi kubełków kolejki obiektów w Porządkach, do których prowadzą wiersze bez nazwy (te same, które
# niesie kolejka przeglądu osi obiektu). Pusty tag = sama podstrona, bez wskazania kubełka.
TAG_NAMELESS, TAG_NAMELESS_RAW, TAG_NAMELESS_STACKS = "nameless", "nameless_raw", "nameless_stacks"
TAG_PODSTRONA = ""


def godzina_dostawy(since):
    """Godzina startu przebiegu do nagłówka raportu - `HH:MM` w czasie lokalnym. Znacznik pisze
    zegar okna (ISO; z aplikacji UTC ze strefą), a człowiek pamięta dostawę po godzinie na
    zegarku. Znacznik bez strefy (zegar testu) zostaje, jaki jest."""
    chwila = datetime.fromisoformat(since)
    if chwila.tzinfo is not None:
        chwila = chwila.astimezone()
    return chwila.strftime("%H:%M")


class PrzyjmijView(QWidget):
    """Kontener strony Dostawy: panel „Co przyszło” nad `pipeline_view`.

    Sygnały do gospodarza: `status_message(str)` (pasek stanu), `object_axis_changed()` (gest
    przypisał obiekt - widoki osi obiektu, Zbiory i teczki Domu liczą się od nowa), `open_tasks(str)`
    (tag kubełka kolejki obiektów w Porządkach; pusty = sama podstrona). Wejścia gospodarza:
    `set_busy(bool)` (przebieg Dostawy pisze do bazy), `set_writeback_busy(bool)` (zapis nagłówków
    do plików), `odswiez_raport()` (stan mógł się zmienić poza tą stroną)."""

    status_message = Signal(str)
    object_axis_changed = Signal()
    open_tasks = Signal(str)

    def __init__(self, con, pipeline_view, *, now_fn, parent=None):
        super().__init__(parent)
        self.con = con
        self.pipeline_view = pipeline_view
        self._now = now_fn
        self._busy = False
        self._writeback_busy = False
        # Zapis przebiegu „all”, z którego stoi raport, i górna granica jego okna (chwila końca
        # przebiegu tym samym zegarem): przeliczenie po geście nie wciąga klatek NASTĘPNEGO
        # przebiegu (droga „Stosy”, skan trybu zaawansowanego) pod nagłówek tej dostawy.
        self._zapis = None
        self._until = None
        # Odcisk stanu bazy z chwili końca OSTATNIEGO przebiegu Dostawy (każdego etapu - to jego log
        # stoi pod panelem) i godzina jego startu: odcisk inny niż teraz = log mówi o stanie sprzed
        # zmian (AR-99, `_sync_podpis_logu`). `None` - w tej sesji nie było przebiegu.
        self._odcisk_przebiegu = None
        self._godzina_przebiegu = None
        self._wiersze_nazw = []         # pula wierszy nazw - dokładana, nigdy kasowana
        self._build_ui()
        pipeline_view.run_finished.connect(self._on_run_finished)

    # ---------------------------------------------------------------- budowa UI

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        # Odmowa kafla Przyjmij (bieg w toku, zapis nagłówków) - w treści strony, nie tylko na pasku:
        # pasek żyje kilka sekund, a strona z postępem biegu stoi przed oczami do końca biegu (AR-97).
        # Poza `self.panel`, bo panel raportu jest ukryty do pierwszego przebiegu.
        self.lbl_odmowa = QLabel("")
        self.lbl_odmowa.setProperty("role", "warn")
        self.lbl_odmowa.setWordWrap(True)
        self.lbl_odmowa.setVisible(False)
        lay.addWidget(self.lbl_odmowa)
        self.panel = QFrame()
        self.panel.setFrameShape(QFrame.StyledPanel)
        pv = QVBoxLayout(self.panel)
        pv.setContentsMargins(10, 8, 10, 8)
        self.lbl_title = QLabel(i18n.t("intake.title"))
        _f = self.lbl_title.font()
        _f.setBold(True)
        self.lbl_title.setFont(_f)
        pv.addWidget(self.lbl_title)
        # Przebieg, który nie ruszył albo nie doszedł do końca, mówi to PRZED liczbami - zero klatek
        # pod nagłówkiem „Dostawa z …” czytałoby się jak pusta dostawa, a nie jak dostawa, której
        # nie było. Dwie etykiety, bo rola koloru (`theme.ROLES`) jest stałą widżetu.
        self.lbl_warn = EtykietaBledu("")   # ścieżka źródła w „nie ruszyła” łamie się po `\` (AR-279)
        self.lbl_warn.setProperty("role", "warn")
        self.lbl_warn.setWordWrap(True)
        pv.addWidget(self.lbl_warn)
        # Pole z protokołu „zdanie + szczegół” (AR-198): wiersz awarii etapu z szczegółem systemu
        # albo bazy pod kursorem - ten sam, który stoi pod przyciskami Dostawy.
        self.lbl_error = EtykietaBledu("")
        self.lbl_error.setProperty("role", "error")
        self.lbl_error.setWordWrap(True)
        pv.addWidget(self.lbl_error)
        self.lbl_head = QLabel("")
        self.lbl_head.setWordWrap(True)
        pv.addWidget(self.lbl_head)
        self.lbl_objects = QLabel("")
        self.lbl_objects.setWordWrap(True)
        pv.addWidget(self.lbl_objects)
        self.lbl_cal = QLabel("")
        self.lbl_cal.setWordWrap(True)
        pv.addWidget(self.lbl_cal)
        self.lbl_unresolved = QLabel("")
        _f = self.lbl_unresolved.font()
        _f.setBold(True)
        self.lbl_unresolved.setFont(_f)
        pv.addWidget(self.lbl_unresolved)
        self.box_nazwy = QVBoxLayout()
        self.box_nazwy.setContentsMargins(0, 0, 0, 0)
        pv.addLayout(self.box_nazwy)
        # Wiersze prowadzące do Porządków: reszta nazw ponad sufit i trzy kubełki bez nazwy. Stałe,
        # nie z puli - jest ich zawsze tyle samo, różni je wyłącznie widoczność.
        self.row_more = self._wiersz_porzadkow(pv, TAG_PODSTRONA)
        self.row_nameless = self._wiersz_porzadkow(pv, TAG_NAMELESS)
        self.row_nameless_raw = self._wiersz_porzadkow(pv, TAG_NAMELESS_RAW)
        self.row_nameless_stacks = self._wiersz_porzadkow(pv, TAG_NAMELESS_STACKS)
        # Klatki tej dostawy bez obiektu Z DECYZJI RĘKI (nagrobek „Cofnij przypisanie”): nie są
        # robotą do naprawy, ale nie są też rozpoznane - osobne zdanie, żeby „Wszystko rozpoznane”
        # nie stało nad klatką, której obiekt człowiek właśnie zdjął.
        self.lbl_cleared = QLabel("")
        self.lbl_cleared.setWordWrap(True)
        pv.addWidget(self.lbl_cleared)
        self.panel.setVisible(False)
        lay.addWidget(self.panel)
        lay.addWidget(self.pipeline_view, 1)

    def _wiersz_porzadkow(self, parent_lay, tag):
        """Wiersz „zdanie + Porządki” - przycisk niesie tag kubełka, do którego prowadzi."""
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        w.lbl = QLabel("")
        w.btn = QPushButton(i18n.t("nav.porzadki"))
        w.btn.setToolTip(i18n.t("intake.tip.tasks"))
        w.btn.clicked.connect(lambda _c=False, t=tag: self.open_tasks.emit(t))
        h.addWidget(w.lbl)
        h.addWidget(w.btn)
        h.addStretch(1)
        w.setVisible(False)
        parent_lay.addWidget(w)
        return w

    def _wiersz_nazwy(self, i):
        """Wiersz `i` puli nazw - dokładany, gdy go brak. Pula zamiast przebudowy, bo przycisk
        wiersza przelicza raport we własnym `clicked`: kasowanie przycisku w trakcie jego własnego
        sygnału to klasa awarii, którą repo zna z puli chipów Znajdź."""
        while len(self._wiersze_nazw) <= i:
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 0, 0, 0)
            w.lbl = QLabel("")
            w.btn = QPushButton(i18n.t("object.assign_btn"))
            w.btn.raw = None
            w.btn.total = 0
            w.btn.clicked.connect(lambda _c=False, b=w.btn: self._on_assign(b.raw))
            h.addWidget(w.lbl)
            h.addWidget(w.btn)
            h.addStretch(1)
            self.box_nazwy.addWidget(w)
            self._wiersze_nazw.append(w)
        return self._wiersze_nazw[i]

    # ---------------------------------------------------------------- wejścia gospodarza

    def set_busy(self, busy):
        """Przebieg Dostawy pisze do bazy - gest zapisu gaśnie (szczery disabled z powodem)."""
        self._busy = bool(busy)
        self._sync_przyciski()
        self._sync_odmowa()

    def set_writeback_busy(self, busy):
        """Zapis nagłówków do plików w toku - gest gaśnie jak etapy Dostawy (mutex writebacku)."""
        self._writeback_busy = bool(busy)
        self._sync_przyciski()
        self._sync_odmowa()

    def _sync_odmowa(self):
        """Odmowa kafla mówi o zajętości (bieg albo zapis nagłówków) - gaśnie, gdy żadnej już nie ma.
        Zapis nagłówków nie kończy się przebiegiem Dostawy, więc samo `_on_run_finished` zostawiłoby
        zdanie „zapis trwa” nad stroną po jego końcu."""
        if not self._busy and not self._writeback_busy:
            self.lbl_odmowa.setVisible(False)

    def odswiez_raport(self):
        """Przelicz raport ze stanu bazy z TĄ SAMĄ granicą okna - gest na tej stronie, w Porządkach
        albo w Zbiorach zmienia populację „nie rozpoznałem”, a liczby skanu zostają przy przebiegu.
        Bez raportu (żaden przebieg „all” w tej sesji) nic nie robi - poza podpisem logu, który
        dotyczy przebiegu każdego etapu (`_sync_podpis_logu`)."""
        self._sync_podpis_logu()
        if self._zapis is not None:
            self._render()

    def _odcisk_stanu(self):
        """Odcisk bazy tego połączenia (`queries.odcisk_bazy` - jeden właściciel klucza zmiany;
        gesty Zbiorów i tej strony idą przez to połączenie, wątki zapisu widzi `data_version`)."""
        return queries.odcisk_bazy(self.con)

    def _sync_podpis_logu(self):
        """Log przebiegu pod panelem dostaje podpis „Przebieg z HH:MM (stan sprzed Twoich zmian)”,
        gdy stan bazy odszedł od chwili końca przebiegu (AR-99): panel liczy się ze stanu, log jest
        zapisem przebiegu, i bez podpisu dwa sąsiednie zdania przeczyły sobie. Wołane przy każdym
        przeliczeniu raportu - po geście tej strony i przy wejściu na Dostawę (gest w Porządkach
        albo Zbiorach). Podpis raz postawiony zostaje do następnego przebiegu (`_begin_run` widoku
        go zdejmuje); bez zmiany stanu log zostaje bez podpisu."""
        if self._odcisk_przebiegu is not None and self._odcisk_stanu() != self._odcisk_przebiegu:
            self.pipeline_view.naglowek_przebiegu(self._godzina_przebiegu)

    def pokaz_odmowe(self, msg):
        """Odmowa kafla Przyjmij w treści strony - gaśnie z końcem biegu, który ją spowodował."""
        self.lbl_odmowa.setText(msg)
        self.lbl_odmowa.setVisible(True)

    # ---------------------------------------------------------------- raport

    def _on_run_finished(self, zapis):
        """Koniec przebiegu Dostawy (po odświeżeniu widoków gospodarza). Przebieg „all” stawia nowy
        raport; każdy inny etap tylko go przelicza - `Rozwiąż` po naprawie nagłówka zmienia, które
        klatki tej dostawy mają obiekt, ale dostawą nie jest. Odmowa kafla gaśnie: bieg, który ją
        spowodował, właśnie się skończył. Odcisk stanu bierze się TU, po zapisach wątku tła
        i po odświeżeniu widoków gospodarza - od tej chwili zmiana stanu to gest po przebiegu.

        Przebieg, który NIE RUSZYŁ (`refused`: źródło niedostępne, guard serialu), odcisku nie
        dostaje: jego log mówi „nie wykonano” i nie opisuje żadnego stanu, więc podpis „stan sprzed
        Twoich zmian” nad nim byłby nieprawdą - gest po nim podpisu nie stawia."""
        self.lbl_odmowa.setVisible(False)
        if zapis["refused"]:
            self._odcisk_przebiegu = self._godzina_przebiegu = None
            self.pipeline_view.naglowek_przebiegu(None)
        else:
            self._odcisk_przebiegu = self._odcisk_stanu()
            self._godzina_przebiegu = godzina_dostawy(zapis["since"])
        if zapis["stage"] == "all":
            self._zapis = zapis
            self._until = self._now()
        self.odswiez_raport()

    def _render(self):
        zapis = self._zapis
        self.panel.setVisible(True)
        if zapis["refused"]:
            self.lbl_warn.setText(i18n.t("intake.refused", reason=zapis["refused"]))
            self.lbl_warn.setVisible(True)
            self.lbl_error.clear()                   # zdanie i szczegół awarii poprzedniego biegu
            self.lbl_error.setVisible(False)
            for w in (self.lbl_head, self.lbl_objects, self.lbl_cal, self.lbl_unresolved,
                      self.lbl_cleared):
                w.setVisible(False)
            self._pokaz_nazwy([])
            for w in (self.row_more, self.row_nameless, self.row_nameless_raw,
                      self.row_nameless_stacks):
                w.setVisible(False)
            return
        self.lbl_warn.setVisible(bool(zapis["cancelled"]) and not zapis["failed"])
        if zapis["cancelled"]:
            self.lbl_warn.setText(i18n.t("intake.cancelled", stage=_stage_label(zapis["cancelled"])))
        self.lbl_error.setVisible(bool(zapis["failed"]))
        if zapis["failed"]:
            self.lbl_error.ustaw(i18n.t("intake.failed", line=zapis["failed"]), zapis["failed_tip"] or "")
        else:
            self.lbl_error.clear()
        r = queries.delivery_report(self.con, zapis["since"], until=self._until)
        self.lbl_head.setText(self._zdanie_dostawy(zapis, r))
        self.lbl_head.setVisible(True)
        self._pokaz_obiekty(r["objects"])
        self._pokaz_kalibracje(r)
        self._pokaz_nierozpoznane(r)
        self._sync_przyciski()

    def _zdanie_dostawy(self, zapis, r):
        """„Dostawa z HH:MM: N nowych klatek (lighty L · …) · kopie znanych klatek K · bez zmian P”.
        Rozbicie po rodzajach ze stanu bazy (sumuje się do N); kopie znanych klatek i pliki bez zmian
        z wyniku skanu - stan bazy nie pamięta, że plik leżał pod drugą ścieżką ani że skan go
        ominął. Kopie to licznik skanu „nowa ścieżka znanej tożsamości”, nie różnica nowych lokacji
        i nowych klatek: podmiana treści pod znaną ścieżką daje nową klatkę bez nowej lokacji
        i różnica zjadała kopię. Zera milczą; przebieg bez skanu (błąd przed nim) milczy o obu."""
        k = r["by_kind"]
        masters = k.get("master_flat", 0) + k.get("master_dark", 0)
        znane_rodzaje = ("light", "flat", "master_flat", "master_dark", "master_light")
        inne = sum(n for kind, n in k.items() if kind not in znane_rodzaje)
        if r["frames"]:
            rodzaje = [(k.get("light", 0), lambda n: i18n.t("intake.kind.light", n=n)),
                       (k.get("flat", 0), lambda n: i18n.t("intake.kind.flat", n=n)),
                       (masters, lambda n: i18n.t("intake.kind.masters", n=n)),
                       (k.get("master_light", 0), lambda n: i18n.t("intake.kind.stacks", n=n)),
                       (inne, lambda n: i18n.t("intake.kind.other", n=n))]
            czlony = [i18n.t_plural("intake.new", r["frames"]) + " " + i18n.t(
                "intake.kinds", parts=" · ".join(f(n) for n, f in rodzaje if n))]
        else:
            czlony = [i18n.t("intake.nothing_new")]
        scan = zapis["results"].get("scan")
        if scan is not None:
            if scan.locations_new_known:
                czlony.append(i18n.t("intake.copies_known", n=scan.locations_new_known))
            if scan.skipped:
                czlony.append(i18n.t("intake.unchanged", n=scan.skipped))
        return i18n.t("intake.head", time=godzina_dostawy(zapis["since"]), what=" · ".join(czlony))

    def _pokaz_obiekty(self, obiekty):
        items = [i18n.t("intake.object_item", canon=canon, n=n,
                        hours=portfolio.format_hours(hours * 3600))
                 for canon, n, hours in obiekty[:_WIDOCZNE_OBIEKTY]]
        if len(obiekty) > _WIDOCZNE_OBIEKTY:
            items.append(i18n.t_plural("intake.objects_more", len(obiekty) - _WIDOCZNE_OBIEKTY))
        self.lbl_objects.setText(i18n.t("intake.objects", items=" · ".join(items)) if items else "")
        self.lbl_objects.setVisible(bool(items))

    def _pokaz_kalibracje(self, r):
        c = r["cal"]
        czlony = [(c["master_flat"], lambda n: i18n.t("intake.cal.master_flat", n=n)),
                  (c["raw_flat"], lambda n: i18n.t("intake.cal.raw_flat", n=n)),
                  (c["no_flat"], lambda n: i18n.t("intake.cal.no_flat", n=n)),
                  (c["pending"], lambda n: i18n.t("intake.cal.pending", n=n)),
                  (c["master_dark"], lambda n: i18n.t("intake.cal.master_dark", n=n)),
                  (c["no_dark"], lambda n: i18n.t("intake.cal.no_dark", n=n))]
        parts = " · ".join(f(n) for n, f in czlony if n)
        self.lbl_cal.setText(i18n.t("intake.cal", parts=parts) if r["lights"] else "")
        self.lbl_cal.setVisible(bool(r["lights"]))

    def _pokaz_nierozpoznane(self, r):
        """„Nie rozpoznałem: N klatek” i wiersz na nazwę z gestem; kubełki bez nazwy z drogą do
        Porządków. „Wszystko rozpoznane” wyłącznie przy zerze nierozpoznanych I odpiętych ręką,
        a dostawa samych flatów nie ma czego rozpoznawać, więc milczy. Odpięte ręką (nagrobek) nie
        są robotą do naprawy - mówi o nich osobne zdanie, bez gestu."""
        nazwy = r["unresolved"]
        razem = (sum(n for _raw, n, _total in nazwy)
                 + r["nameless"] + r["nameless_raw"] + r["nameless_stacks"])
        if razem:
            self.lbl_unresolved.setText(i18n.t_plural("intake.unresolved_head", razem))
        else:
            self.lbl_unresolved.setText(i18n.t("intake.all_recognized"))
        # Zdanie niesie rolę koloru swojego znaczenia (`theme.ROLES`): robota czeka - ostrzeżenie,
        # komplet - ok. Samo pogrubienie mówiło tylko „ważne”, nie „dobrze” albo „do zrobienia”.
        rola = "warn" if razem else "ok"
        if self.lbl_unresolved.property("role") != rola:
            self.lbl_unresolved.setProperty("role", rola)
            self.lbl_unresolved.style().unpolish(self.lbl_unresolved)   # rola czytana przy polishu
            self.lbl_unresolved.style().polish(self.lbl_unresolved)
        self.lbl_unresolved.setVisible(
            bool(razem or ((r["lights"] or r["stacks"]) and not r["cleared"])))
        self.lbl_cleared.setText(i18n.t_plural("intake.cleared", r["cleared"]) if r["cleared"]
                                 else "")
        self.lbl_cleared.setVisible(bool(r["cleared"]))
        self._pokaz_nazwy(nazwy[:_WIDOCZNE_NAZWY])
        reszta = len(nazwy) - _WIDOCZNE_NAZWY
        self.row_more.lbl.setText(i18n.t_plural("intake.unresolved_more", reszta) if reszta > 0
                                  else "")
        self.row_more.setVisible(reszta > 0)
        for w, n, tekst in (
                (self.row_nameless, r["nameless"],
                 lambda n: i18n.t("intake.nameless", n=n)),
                (self.row_nameless_raw, r["nameless_raw"],
                 lambda n: i18n.t("intake.nameless_raw", n=n)),
                (self.row_nameless_stacks, r["nameless_stacks"],
                 lambda n: i18n.t("intake.nameless_stacks", n=n))):
            w.lbl.setText(tekst(n) if n else "")
            w.setVisible(bool(n))

    def _pokaz_nazwy(self, nazwy):
        for i, (raw, n, total) in enumerate(nazwy):
            w = self._wiersz_nazwy(i)
            tekst = i18n.t("intake.unresolved_row", name=raw, n=n)
            if total > n:
                tekst += i18n.t("intake.unresolved_total", total=total)
            w.lbl.setText(tekst)
            w.btn.raw = raw
            w.btn.total = total
            w.setVisible(True)
        for w in self._wiersze_nazw[len(nazwy):]:
            w.btn.raw = None
            w.setVisible(False)

    def _powod_wygaszenia(self):
        """Zdanie, dla którego gest zapisu jest teraz niewykonalny, albo `None`."""
        if self._busy:
            return i18n.t("intake.assign_busy_tip")
        if self._writeback_busy:
            return i18n.t("intake.assign_writeback_tip")
        return None

    def _sync_przyciski(self):
        """JEDYNY właściciel stanu przycisków „Przypisz obiekt…”: wygaszone w biegu i przy zapisie
        nagłówków, a podpowiedź mówi dlaczego; czynne mówią, ile klatek gest ruszy."""
        powod = self._powod_wygaszenia()
        for w in self._wiersze_nazw:
            w.btn.setEnabled(powod is None)
            w.btn.setToolTip(powod if powod is not None
                             else i18n.t_plural("intake.assign_tip", w.btn.total))

    # ---------------------------------------------------------------- gest

    def _on_assign(self, raw):
        """„Przypisz obiekt…” przy nierozpoznanej nazwie: dialog → JEDNA klinga
        `repo.user_assign_object` → zdanie → raport z tej samej granicy okna.

        Klatki z `queries.object_review_frames` (nazwa to nazwa - ta sama populacja, którą zapisuje
        gest Porządków, także spoza tej dostawy); wiersz nazwał obie liczby, więc dialog z całą
        populacją nie zaskakuje. Bramka pustego klucza PRZED dialogiem, jak w osi obiektu: alias
        z nazwy bez znaków alfanumerycznych łapałby każdą taką nazwę, a dialog asertuje ten kontrakt.
        Okno ma własną pętlę zdarzeń, więc bramki biegu i zapisu nagłówków sprawdzamy jeszcze raz
        po nim - odmowa mówi powód, bo cisza po zatwierdzeniu wyglądałaby na zjedzony klik."""
        if raw is None:
            return
        powod = self._powod_wygaszenia()
        if powod is not None:
            self.status_message.emit(powod)
            return
        if not norm_alnum(raw):
            QMessageBox.warning(self, i18n.t("assign.title"),
                                i18n.t("object.alias_no_alnum", name=raw))
            return
        ids = [r["frame_id"] for r in queries.object_review_frames(self.con, raw)]
        if not ids:                     # nazwa nadana w międzyczasie gdzie indziej
            self.odswiez_raport()
            self.status_message.emit(i18n.t("intake.assign.gone", raw=raw))
            return
        dlg = AssignObjectDialog(self.con, object_raw=raw, frame_count=len(ids), parent=self)
        if dlg.exec() != QDialog.Accepted or dlg.selected is None:
            return
        powod = self._powod_wygaszenia()
        if powod is not None:
            self.status_message.emit(powod)
            return
        canon, catalog, kind, alias_norm = dlg.selected
        try:
            with busy.busy(self.status_message.emit, i18n.t_plural("busy.saving_frames", len(ids))):
                g = repo.user_assign_object(
                    self.con, alias_norm=alias_norm, canon=canon, catalog=catalog, kind=kind,
                    frame_ids=ids, now=self._now())
        except ValueError as e:         # konflikt aliasu / dryf do nieistniejącej klatki
            QMessageBox.warning(self, i18n.t("assign.title"), str(e))
            return
        if alias_norm is not None:
            zdanie = i18n.t("intake.assign.remembered", raw=raw, canon=canon)
        else:
            zdanie = i18n.t_plural("intake.assign.assigned", g.assigned, canon=canon)
        self.odswiez_raport()
        self.object_axis_changed.emit()
        self.status_message.emit(zdanie + zdanie_pominiec(g))
