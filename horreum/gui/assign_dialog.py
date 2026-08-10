r"""Okno ręcznego przypisania obiektu — WYDZIELONE z `gui.app` w S2b.

Powód wydzielenia jest strukturalny, nie porządkowy: od S2b to okno ma DWÓCH wołających — kolejkę
przeglądu (`gui.app`) i pasek Zbiorów (`gui.grid`) — a `grid` nie może sięgnąć do `app` bez cyklu.
Dopóki wołający był jeden, kontraktu okna pilnował guard w `_on_assign` po stronie tego wołającego;
drugie wejście ten układ unieważnia (R-S4-9), więc kontrakt przenosi się TU, do konstruktora.
"""
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QLabel, QLineEdit, QVBoxLayout,
)

from horreum import resolver
from horreum.gui import i18n, queries
from horreum.resolve._text import norm_alnum


def broni_sie_sama(text):
    """Czy drabina rozwiąże tę nazwę BEZ aliasu. `lookup` zawsze pusty, więc alias nie ma głosu.

    Uszkodzony słownik ⇒ `False`: nie wiemy, czy nazwa broni się sama, więc ani nie obiecujemy
    noty, ani nie odbieramy klucza. Sam błąd melduje `_sync_accept_enabled` — tu byłby drugim
    komunikatem o tej samej awarii."""
    try:
        return resolver.resolve_name(lambda _key: None, text)[0] is not None
    except ValueError:
        return False


def alias_key(object_raw, canon):
    """Klucz równoważności dla gestu ręki — TRZY PRZYPADKI, JEDEN WŁAŚCICIEL.

    Reguła mieszkała w metodzie okna, dopóki okno było jedyną drogą do `repo.user_assign_object`.
    R-S2b-12 dołożyło drugą (skrót „ostatnio użyte" w menu Zbiorów, który okna nie otwiera), więc
    reguła musiała wyjść wyżej — inaczej skrót miałby WŁASNĄ kopię i pierwsza korekta rozjechałaby
    zapisy z dwóch powierzchni (SIN-DUP na kluczu, którego konflikt pilnuje guard w repo).

      1. **zeznanie JEST** → `norm_alnum(object_raw)`; alias zapamiętuje nazwę z nagłówka NA
         PRZYSZŁOŚĆ („FlatWizard" → M42) i tego nie wolno stracić;
      2. **brak zeznania, nazwa SPOZA gramatyki** (`LMC`) → `norm_alnum(kanon)`; jedyna droga,
         którą przyszły nagłówek z tą nazwą trafi ten obiekt;
      3. **brak zeznania, nazwa Z gramatyki** (`NGC7635`) → BRAK klucza (`None`). Alias z kanonu
         byłby samozwrotny: gramatyka katalogowa stoi w drabinie NAD aliasem, więc nikt nigdy
         o taki klucz nie zapyta, a diff-first słownika by go nie usunął (`source='user'`).

    Przypadek 2 vs 3 rozstrzyga WŁAŚCICIEL DRABINY, nie jeden jej szczebel (`broni_sie_sama`).
    Dyskryminator na samym `catalog_canon` łapał JEDEN z czterech szczebli i wywracał przy tym
    odwracalność, którą S2 dopiero co zbudował (R-S1-4): ręka na kanonie SŁOWNIKA zakładała alias
    `source='user'`, przez co `sync_own_aliases` nie zasiewał już własnego, a
    `retire_alias_and_unassign` — który wycofuje WYŁĄCZNIE `curated` — przestawał widzieć kanon
    jako zdjęty."""
    if object_raw is not None:
        return norm_alnum(object_raw)
    if broni_sie_sama(canon):
        return None
    return norm_alnum(canon) or None


class AssignObjectDialog(QDialog):
    """Dialog ręcznego przypisania obiektu grupie review (#8, P4, D-P4-3): wybór ISTNIEJĄCEGO obiektu
    z biblioteki (combo `canon · catalog`) ALBO nowa NAZWA rozwiązywana TĄ SAMĄ drabiną, którą pójdzie
    przebieg. Świadomie BEZ wolnego tekstu jako canon: `object.canon` nie ma deduplikacji semantycznej,
    a śmieciowego obiektu nic by nie posprzątało. Cofnięcie SAMEGO PRZYPISANIA istnieje od S2b
    („Obiekt ▾ → Cofnij przypisanie" w Zbiorach); sprzątanie osieroconego OBIEKTU to osobna sprawa
    i czeka na ekran Porządków (`retired_at`, nie `DELETE`).

    TRZY WEJŚCIA, JEDNO OKNO: grupa Z ZEZNANIEM (`object_raw` z nagłówka), grupa BEZ NIEGO
    (kubełek RAW — format nie ma karty `OBJECT`, więc zeznania nie ma z definicji, nie z braku)
    oraz ZAZNACZENIE z paska Zbiorów (S2b, `selection` = read-model `selection_object_state`).
    Trzeciego NIE WOLNO opisywać zdaniem drugiego, choć oba wchodzą z `object_raw=None`: zaznaczenie
    bywa FITS-ami Z kartą `OBJECT` i klatkami, które kanon JUŻ mają — a to okno pyta wtedy o
    nadpisanie cudzej nazwy i musi to powiedzieć wprost. `frame_count` = ile klatek gest REALNIE
    ruszy (`namable`), nie ile jest zaznaczonych: etykieta akcji obiecywała 8 przy 4 do zapisania.

    WALIDACJA STOI NA `resolver.name_resolves`, KANON NA `resolve_name` (S4, D-OW-2 pkt 5): walidator
    zwraca `bool`, więc sam kanonu nie da, a dawna gałąź liczyła go przez `catalog_canon`→`xref` —
    dla `LMC` dałoby to `canon=None` i naruszenie `NOT NULL`. Pytanie brzmi „czy przebieg rozpozna
    tę nazwę", a odpowiedzi twierdzące są cztery: gramatyka katalogowa, nazwa potoczna, słownik
    obiektów własnych i alias. `catalog`/`kind` biorą się z tej samej tożsamości — dla wpisu słownika
    z jego rekordu (`catalog` bywa NULL, `kind='own'`), nie z zaszytego `deep_sky`.

    KLUCZ ALIASU JEST TRZYPRZYPADKOWY (R16#2) — i to okno jest jego JEDYNYM właścicielem, bo dopiero
    tu znana jest wybrana nazwa:
      1. **zeznanie JEST** → `norm_alnum(object_raw)`; alias zapamiętuje nazwę z nagłówka NA
         PRZYSZŁOŚĆ („FlatWizard" → M42) i tego nie wolno stracić;
      2. **brak zeznania, nazwa SPOZA gramatyki** (`LMC`) → `norm_alnum(kanon)`; to jedyna droga,
         którą przyszły nagłówek z tą nazwą trafi ten obiekt;
      3. **brak zeznania, nazwa Z gramatyki** (`NGC7635` na RAW-ach) → **BRAK klucza** (`None`).
         Alias z kanonu byłby samozwrotny: gramatyka katalogowa stoi w drabinie NAD aliasem, więc
         nikt nigdy o taki klucz nie zapyta, a diff-first słownika go nie usunie (`source='user'`).
         To najczęstszy realny gest S4 — do S4 kończył się twardym `ValueError` z `repo` i
         komunikatem o „nazwie bez znaków alfanumerycznych", czyli kłamstwem o przyczynie.

    Pre-check konfliktu aliasu (`alias_target` — UX; ostateczny guard w `repo.user_assign_object`,
    TOCTOU) idzie na TYM SAMYM kluczu, którego użyje zapis, więc liczy się PO walidacji nazwy,
    a nie w konstruktorze. Wynik walidacji ląduje w `self.selected` = `(canon, catalog, kind,
    alias_norm)` (`kind=None` dla obiektu istniejącego — repo go nie INSERTuje, więc pole
    nieużywane; `alias_norm=None` = przypadek trzeci)."""

    def __init__(self, con, *, object_raw, frame_count, selection=None, cleared_n=0, parent=None):
        super().__init__(parent)
        # KONTRAKT PILNOWANY OD ŚRODKA (R-S4-9, odesłane z adjudykacji S4 i domknięte tutaj).
        # `object_raw` o wartości `""` NIE jest tym samym co `None`: przypadek 1 zwróci wtedy pusty
        # klucz aliasu, a `repo.user_assign_object` odrzuci go `ValueError`-em o „pustym aliasie" —
        # komunikatem kłamiącym o przyczynie. Do S4 bronił przed tym guard w `_on_assign` JEDNEGO
        # wołającego; od S2b wołających jest dwóch, więc obrona z zewnątrz przestała wystarczać.
        # Poprawką NIE jest `norm_alnum(...) or None` — to zmieniłoby semantykę na „brak klucza"
        # tam, gdzie klucz miał zostać ZAPAMIĘTANY (przypadek 1 uczy nazwy z nagłówka na przyszłość).
        # Asercja pyta o KLUCZ, nie o białe znaki: bronimy przypadku 1, a on liczy klucz przez
        # `norm_alnum`. Predykat `strip()` przepuszczał `"---"` — zeznanie realne w archiwum, po
        # którym klucz jest pusty tak samo jak po `""`, a klinga rzuca ValueError-em o „nazwie bez
        # znaków alfanumerycznych", czyli kłamstwem o przyczynie. Guard w `gui.app` łapał to dla
        # JEDNEGO wołającego tym samym `norm_alnum` — dwa predykaty na jeden kontrakt to dwóch
        # właścicieli, a właśnie ich mnożenie było powodem wydzielenia okna.
        assert object_raw is None or norm_alnum(object_raw), (
            "object_raw bez znaków alfanumerycznych to nie 'brak zeznania' — "
            "podaj None dla grupy bez karty")
        self.con = con
        self.object_raw = object_raw
        self.selected = None
        self.setWindowTitle(i18n.t("assign.title"))
        lay = QVBoxLayout(self)

        if selection is not None:
            # ZAZNACZENIE to nie „grupa bez zeznania" — i pomylenie ich było kłamstwem w chwili
            # decyzji o nadpisaniu: pasek Zbiorów woła to okno z `object_raw=None`, więc nagłówek
            # mówił „N klatek bez nazwy w metadanych (format bez karty OBJECT)" o klatkach, które
            # nazwę MAJĄ (ze ścieżki) i bywają FITS-ami z kartą `OBJECT`. Zdanie składamy z tego
            # samego read-modelu, który wygasza kontrolkę — jeden właściciel faktu o zaznaczeniu.
            head_text = i18n.t_plural("assign.selection_head", frame_count)
            if selection["overwrite"]:
                head_text += "\n" + i18n.t_plural("assign.selection_overwrite",
                                                  selection["overwrite"])
            pominie = selection["n"] - frame_count
            if pominie:
                head_text += "\n" + i18n.t_plural("assign.selection_skip", pominie)
        elif object_raw is None:
            # Grupa bez zeznania: nagłówek nie ma nazwy do zacytowania, a obietnica „alias zostanie
            # zapamiętany" byłaby nieprawdziwa dla przypadku trzeciego — mówimy więc, skąd bierze
            # się grupa, i zostawiamy naukę aliasu przy nazwie, która ją realnie dostaje.
            head_text = i18n.t_plural("assign.group_head_nameless", frame_count)
        else:
            head_text = (i18n.t_plural("assign.group_head", frame_count, name=object_raw)
                         + "\n" + i18n.t("assign.alias_remembered"))
        # NADPISANIE WŁASNEGO WERDYKTU MÓWI SIĘ W OKNIE, NIE W TOOLTIPIE (wizytacja S3). Zapis
        # z kubełka „cofnięte ręką" jedzie z `overwrite_weak=True`, czyli świadomie gasi nagrobek —
        # a jedyne ostrzeżenie mieszkało w tooltipie przycisku, który pojawia się po ~700 ms
        # najechania i którego user klikający wprost z wiersza nigdy nie zobaczy. Ostrzeżenie ma
        # stać na DRODZE KLIKNIĘCIA, w chwili decyzji. Liczba z parametru, nie z literału: jej
        # właścicielem jest read-model wołającego (ta sama reguła, co przy odmowie konfliktu).
        if cleared_n:
            head_text += "\n" + i18n.t_plural("assign.cleared_warning", cleared_n)
        self.head = QLabel(head_text)
        self.head.setWordWrap(True)
        lay.addWidget(self.head)
        # Drabina BEZ szczebla aliasu (`lookup` zawsze pusty) — i to jest tu ZAMIERZONE: alias
        # dopiero powstanie z tego gestu, więc pytanie brzmi „czy nazwa broni się sama". Pytamy
        # jednak WŁAŚCICIELA drabiny, nie własnej kompozycji: nowy szczebel trafia tę notę
        # automatycznie, zamiast po cichu ją ominąć. Grupa bez zeznania nie ma czego pytać.
        if object_raw is not None and self._broni_sie_sama(object_raw):
            note = QLabel(i18n.t("assign.catalog_note"))
            note.setWordWrap(True)
            lay.addWidget(note)

        lay.addWidget(QLabel(i18n.t("assign.existing_object")))
        self.combo = QComboBox()
        self.combo.addItem(i18n.t("assign.pick_object"), None)
        self._objects = queries.library_objects(con)          # bez filtra — pełna biblioteka
        for o in self._objects:
            self.combo.addItem(f"{o['canon']}  ·  {o['catalog'] or '—'}",
                               (o["id"], o["canon"], o["catalog"]))
        lay.addWidget(self.combo)

        lay.addWidget(QLabel(i18n.t("assign.new_designation")))
        self.designation = QLineEdit()
        self.designation.setPlaceholderText(i18n.t("assign.designation_placeholder"))
        lay.addWidget(self.designation)

        # Nazwa spoza katalogów wygląda w bibliotece INACZEJ (kolumna „Katalog" zostaje pusta) —
        # i to jest stan poprawny, nie brak danych. Nota mówi to ZANIM user kliknie, żeby pusta
        # komórka po zapisie nie czytała się jak zgubione pole.
        self.own_note = QLabel("")
        self.own_note.setWordWrap(True)
        self.own_note.setVisible(False)
        lay.addWidget(self.own_note)

        self.error = QLabel("")
        self.error.setProperty("role", "error")     # kolor z motywu (P-C) — sztywny #b00020 był ślepy na dark
        self.error.setWordWrap(True)
        lay.addWidget(self.error)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.accept_btn = buttons.button(QDialogButtonBox.Ok)
        self.accept_btn.setText(i18n.t_plural("assign.accept_btn", frame_count))
        # Tekst przycisku z katalogu, nie z Qt (precedens `planner.py`): repo nie wozi QTranslator,
        # więc `Cancel` zostawało po angielsku obok spolszczonego „Przypisz N klatek".
        buttons.button(QDialogButtonBox.Cancel).setText(i18n.t("assign.cancel_btn"))
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self.combo.currentIndexChanged.connect(self._sync_accept_enabled)
        self.designation.textChanged.connect(self._sync_accept_enabled)
        self._sync_accept_enabled()

    def _fail(self, msg):
        self.error.setText(msg)

    _broni_sie_sama = staticmethod(broni_sie_sama)     # funkcja modułowa (R-S2b-12) — jeden właściciel

    def _sync_accept_enabled(self):
        """Akcja wymaga JAWNEGO celu; wpisaną nazwę walidujemy na żywo, żeby disabled miał powód.

        Pytamy `resolver.name_resolves` — TĘ SAMĄ bramkę, co okno „Napraw nagłówek…". Dawne
        `catalog_canon` odpowiadało na węższe pytanie („czy to oznaczenie katalogowe") i odrzucało
        nazwy, które przebieg rozwiązuje bez wahania: `LMC` ze słownika, `Moon` z drabiny solar,
        nazwę potoczną, nazwę nauczoną wcześniej aliasem."""
        text = self.designation.text().strip()
        self.error.clear()                                  # wejście się zmieniło → stary błąd nieaktualny
        try:
            valid_name = resolver.name_resolves(self.con, text) if text else False
            ident = (resolver.resolve_name(resolver.alias_lookup(self.con), text)[0]
                     if valid_name else None)
        except ValueError:
            # SŁOWNIK OBIEKTÓW WŁASNYCH JEST PLIKIEM CZŁOWIEKA, a jego edycja to operacja wspierana:
            # literówka w assecie ma zostać ZGŁOSZONA, nie wywalić okno tracebackiem przy naciśnięciu
            # klawisza. Ta sama reguła, co w `queries.review_queue` — od S4 dialog też czyta drabinę,
            # więc dziedziczy jej tryb awarii. Akcja gaśnie: nie wiemy, czy nazwa się rozwiąże.
            self.accept_btn.setEnabled(False)
            self.own_note.setVisible(False)
            return self._fail(i18n.t("assign.dictionary_broken"))
        self.accept_btn.setEnabled(valid_name if text else self.combo.currentData() is not None)
        if text and not valid_name:
            self._fail(i18n.t("assign.unknown_name", text=text))
        # Nota po RODZAJU, nie po pustym katalogu: `catalog IS NULL` mają też obiekty z REGIONU
        # (`Veil`), a nazwanie ich „obiektem własnym" byłoby nieprawdą o pochodzeniu kanonu.
        wlasny = ident is not None and ident.kind == "own"
        # Warunek na LOKALNEJ zmiennej, nie na `isVisible()`: przy niepokazanym oknie ta metoda
        # zwraca False niezależnie od `setVisible` (lekcja STANDING kolejki), więc nota nigdy nie
        # dostałaby treści przed pierwszym wyświetleniem dialogu.
        self.own_note.setVisible(wlasny)
        if wlasny:
            self.own_note.setText(i18n.t("assign.own_object_note", canon=ident.canon))

    def _alias_key(self, canon):
        """Klucz równoważności dla TEGO gestu — reguła i jej uzasadnienie: `alias_key` (moduł).
        Okno wnosi tu wyłącznie własny kontekst (`object_raw`), a nie drugą kopię reguły."""
        return alias_key(self.object_raw, canon)

    def _validate_and_accept(self):
        """Waliduj wybór; poprawny → `self.selected` + accept, błąd → nota i dialog zostaje."""
        text = self.designation.text().strip()
        if text:
            # Kanon i pola obiektu z WŁAŚCICIELA drabiny, nie z własnej kompozycji: `name_resolves`
            # wyżej powiedziało „tak" tą samą funkcją, więc `None` tutaj znaczyłoby, że oba wołania
            # odpowiadają różnie na jedno pytanie (EXPECT — nota, zero zapisu).
            try:
                ident, _ = resolver.resolve_name(resolver.alias_lookup(self.con), text)
            except ValueError:
                return self._fail(i18n.t("assign.dictionary_broken"))
            if ident is None:
                return self._fail(i18n.t("assign.unknown_name", text=text))
            canon, catalog, kind = ident.canon, ident.catalog, ident.kind
        else:
            selected = self.combo.currentData()
            if selected is None:
                return self._fail(i18n.t("assign.pick_or_designate"))
            _, canon, catalog = selected
            kind = None                                   # obiekt istnieje — repo nie INSERTuje
        # Id po KANONIE, tą samą frazą co klinga (`queries.object_id_by_canon`), nie z biblioteki:
        # `library_objects` ma `JOIN frame`, więc obiekt bez klatek dla niej nie istnieje i pre-check
        # meldowałby konflikt tam, gdzie zapis przechodzi bez mrugnięcia.
        object_id = queries.object_id_by_canon(self.con, canon)
        alias_norm = self._alias_key(canon)
        if alias_norm is not None:
            target = queries.alias_target(self.con, alias_norm)
            if target is not None and target != object_id:
                target_canon = next((o["canon"] for o in self._objects if o["id"] == target), target)
                return self._fail(i18n.t("assign.alias_conflict", target=target_canon))
        self.selected = (canon, catalog, kind, alias_norm)
        self.accept()
