r"""Okno ręcznego przypisania obiektu — WYDZIELONE z `gui.app` w S2b.

Powód wydzielenia jest strukturalny, nie porządkowy: od S2b to okno ma DWÓCH wołających — kolejkę
przeglądu (`gui.app`) i pasek Zbiorów (`gui.grid`) — a `grid` nie może sięgnąć do `app` bez cyklu.
Dopóki wołający był jeden, kontraktu okna pilnował guard w `_on_assign` po stronie tego wołającego;
drugie wejście ten układ unieważnia (R-S4-9), więc kontrakt przenosi się TU, do konstruktora.
"""
import unicodedata

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QLabel, QLineEdit, QVBoxLayout,
)

from horreum import resolver
from horreum.gui import facet_model, i18n, queries
from horreum.gui.config_dialog import dopasuj_wysokosc   # wspólny pomocnik okien (AR-176)
from horreum.resolve._text import LITERY_BEZ_ROZKLADU, norm_alnum
from horreum.resolve.catalog import catalog_canon, header_form, xref, xref_aliases
from horreum.resolve.objects import common_name_form, load_own_objects
from horreum.resolve.solar import solar_form

# Ile pozycji listy obiektów naraz. Styl Fusion domyślnie ignoruje `maxVisibleItems` i rozwija
# listę na wysokość ekranu (zmierzone: 1778 px przy kilkuset obiektach); `combobox-popup: 0`
# przełącza go na zwykłą listę z suwakiem, która tę liczbę szanuje.
_POZYCJI_NARAZ = 10
# Pauza w pisaniu, po której nazwa nierozpoznana dostaje czerwone zdanie (odbiór 0.19.0 OB11:
# walidacja na żywo krzyczała przy każdym znaku, zanim człowiek skończył pisać). Wyjście z pola
# i Enter mówią od razu (`AssignObjectDialog.zweryfikuj_nazwe`).
_PAUZA_NAZWY_MS = 500


def bez_diakrytykow(text):
    """`Księżyc` → `Ksiezyc`, `Obłok` → `Oblok`: znaki diakrytyczne złożone do liter bazowych.
    Czysta funkcja, wyłącznie po stronie okna."""
    rozlozone = unicodedata.normalize("NFKD", str(text or "").translate(LITERY_BEZ_ROZKLADU))
    return "".join(z for z in rozlozone if not unicodedata.combining(z))


def klucz_szukania(text):
    """Klucz porównań SZUKAJKI i deduplikacji listy tego okna: `norm_alnum` po złożeniu
    diakrytyków.

    `norm_alnum` zostawia wyłącznie `A-Z0-9`, więc litery z ogonkami po prostu WYCINA: „Księżyc"
    dawało `KSIYC` i nie trafiało aliasu `KSIEZYC`, a „Wielki Obłok Magellana" i „Wielki Oblok
    Magellana" miały różne klucze (`…OBOK…` i `…OBLOK…`), więc lista pokazywała obie formy obok
    siebie. Klucze w bazie (`alias_norm`) i klucz zapisu liczy dalej `norm_alnum` BEZ zmian: ich
    zmiana wymagałaby migracji wszystkich aliasów, a ten klucz służy wyłącznie do porównania
    tego, co okno pokazuje, z tym, co user wpisuje."""
    return norm_alnum(bez_diakrytykow(text))


def nazwy_slownika():
    """`norm_alnum(nazwa)` → nazwa w brzmieniu ze `objects_own.json` (kanon i każde `n`).

    Służy WYŁĄCZNIE do czytelnego pokazania aliasu, który JUŻ jest w `object_alias`: baza trzyma
    tylko `alias_norm` (`LARGEMAGELLANICCLOUD`), a dla wpisów słownika oryginał istnieje w assecie.
    Nie dokłada nowych aliasów. Uszkodzony plik (JSON) ⇒ pusty słownik: pokazujemy wtedy formę
    znormalizowaną, a samą awarię melduje walidacja nazwy (`assign.dictionary_broken`) - drugi
    komunikat o tej samej awarii byłby szumem."""
    try:
        rekordy = load_own_objects()
    except ValueError:
        return {}
    out = {}
    for rec in rekordy:
        for name in (rec.get("c"), *(rec.get("n") or ())):
            if name and norm_alnum(name):
                out.setdefault(norm_alnum(name), str(name))
    return out


def forma_aliasu(alias_norm, pretty=None):
    """JEDYNY właściciel formy aliasu na ekranie (AR-63) - okno „Przypisz obiekt” i podpowiedź
    listwy facetów mówią jednym zdaniem. Najczytelniejsza forma, jaką znamy, bez zmyślania:
      * oznaczenie katalogowe → forma kanoniczna gramatyki (`CALDWELL3` → `C3`, `SH2184` → `Sh2-184`);
      * brzmienie z `pretty` (`formy_aliasow`: słownik obiektów własnych, a za nim karta `OBJECT`);
      * brzmienie z wiedzy o niebie w kodzie: nazwa potoczna (`BODESGALAXY` → „Bode's Galaxy”),
        ciało i token komety (`KSIEZYC` → „Księżyc”, `LEMMON` → „Lemmon”);
      * reszta → sam klucz (alias ręki bez zeznania, np. `MUR`) - żadnego brzmienia nie znamy."""
    return (catalog_canon(alias_norm, split=False) or (pretty or {}).get(alias_norm)
            or common_name_form(alias_norm) or solar_form(alias_norm) or alias_norm)


def formy_aliasow(con):
    """`alias_norm` → forma do pokazania dla KAŻDEGO klucza `object_alias` (AR-15, AR-63). Brzmienia
    z dwóch źródeł już pokazywanych gdzie indziej - słownik obiektów własnych (asset, brzmienie
    ustawione ręką) wygrywa z kartą `OBJECT` (`queries.alias_header_forms`) - a całość przechodzi
    przez `forma_aliasu`, więc listwa dostaje tę samą formę co okno. Klucz zostaje kluczem:
    szukajka i zapis dalej pracują na `alias_norm`."""
    pretty = {**queries.alias_header_forms(con), **nazwy_slownika()}
    klucze = {r[0] for r in con.execute("SELECT alias_norm FROM object_alias")}
    return {**pretty, **{k: forma_aliasu(k, pretty) for k in klucze}}


def aliasy_obiektu(canon, alias_norms, pretty=None):
    """Aliasy obiektu DO POKAZANIA na liście okna (decyzja usera 2026-09-26: kto grzebie w nazwach,
    musi widzieć aliasy). Źródła: `object_alias` (`alias_norms`) i równoważność `catalog_xref.json`
    czytana wstecz (`xref_aliases`).

    Każdy alias dostaje formę z `forma_aliasu` (jedyny właściciel, AR-63) - tę samą, którą mówi
    podpowiedź listwy facetów. Aliasy TECHNICZNE odpadają: te, które są zapisem samego kanonu (`NGC4258`, `SH2131`,
    `COLLINDER464` przy `Cr464`) - niczego userowi nie mówią. Duplikaty scala `klucz_szukania`
    (ten sam klucz z bazy i z xref, a także ta sama nazwa z ogonkami i bez nich: „Wielki Obłok
    Magellana" / „Wielki Oblok Magellana" to jedna nazwa w dwóch zapisach). Z dwóch zapisów
    zostaje ten Z OGONKAMI - pełna pisownia nazwy, a wersja bez nich jest jej uproszczeniem.
    Kolejność: oznaczenia katalogowe przed nazwami, potem alfabet."""
    klucz_kanonu = klucz_szukania(canon)
    pretty = pretty or {}
    formy = {}
    for forma in (*xref_aliases(canon),
                  *(forma_aliasu(a, pretty) for a in sorted(alias_norms or ()))):
        klucz = klucz_szukania(forma)
        if klucz and klucz != klucz_kanonu and catalog_canon(forma, split=False) != canon:
            zastana = formy.setdefault(klucz, forma)
            if zastana == bez_diakrytykow(zastana) and forma != bez_diakrytykow(forma):
                formy[klucz] = forma
    return sorted(formy.values(),
                  key=lambda s: (catalog_canon(s, split=False) is None, s.casefold()))


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
    z biblioteki (combo `canon · catalog · aliasy`, zawężane szukajką po kanonie i aliasie) ALBO nowa
    NAZWA rozwiązywana TĄ SAMĄ drabiną, którą pójdzie przebieg - pod polem nazwy zdanie na żywo
    „wpisane → kanon · w nagłówku: forma" (`catalog.header_form`). Świadomie BEZ wolnego tekstu
    jako canon: `object.canon` nie ma deduplikacji semantycznej, a śmieciowego obiektu nic by nie posprzątało. Cofnięcie SAMEGO PRZYPISANIA istnieje od S2b
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

    def __init__(self, con, *, object_raw, frame_count, selection=None, cleared_n=0,
                 preselect_canon=None, parent=None):
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
        # SZUKAJKA LISTY (2026-09-26): wzorzec listwy facetów - pole tekstowe + predykat
        # `facet_model.search_hit` - JEDEN predykat z listwą (C6): oznaczenie katalogowe trafia
        # dokładnie przez kanon i `xref`, reszta podciągiem z DRUGIMI NAZWAMI - a nie edytowalne
        # combo: tamto mieszałoby wpisaną frazę z wyborem celu, a akcja tego okna wymaga JAWNEGO
        # celu. Mapa aliasów do szukania = te z bazy ORAZ formy pokazane na liście (xref wstecz),
        # więc wszystko, co user widzi przy obiekcie, da się też wpisać.
        self.search = QLineEdit()
        self.search.setPlaceholderText(i18n.t("assign.search_placeholder"))
        self.search.setClearButtonEnabled(True)
        lay.addWidget(self.search)
        self.combo = QComboBox()
        # Lista ma SUFIT wysokości: bez `combobox-popup: 0` styl Fusion pomija `maxVisibleItems`
        # i rozwija całą bibliotekę na wysokość ekranu (`_POZYCJI_NARAZ`).
        self.combo.setStyleSheet("QComboBox { combobox-popup: 0; }")
        self.combo.setMaxVisibleItems(_POZYCJI_NARAZ)
        self._objects = queries.library_objects(con)          # bez filtra — pełna biblioteka
        alias_idx = queries.object_alias_index(con)
        pretty = formy_aliasow(con)
        self._aliasy = {o["canon"]: aliasy_obiektu(o["canon"], alias_idx.get(o["canon"]), pretty)
                        for o in self._objects}
        # Siano szukajki: klucze z bazy (`alias_norm`, już bez ogonków) i KLUCZE SZUKANIA form
        # pokazanych na liście - igła przechodzi tę samą bramkę (`_fill_combo`), więc „Księżyc"
        # trafia `KSIEZYC`, a „Obłok" - formę z ogonkiem.
        self._szukaj = {canon: set(alias_idx.get(canon, ())) | {klucz_szukania(a) for a in aliasy}
                        for canon, aliasy in self._aliasy.items()}
        self._fill_combo("")
        # PRESELEKCJA WYBORU, KTÓRY JUŻ PADŁ (firsthand 0810, znalezisko 3). Okno bywa wołane
        # przez skrót „ostatnio użyte": user WSKAZAŁ tam kanon, a okno otwiera się wyłącznie po
        # to, żeby pokazać dysklozurę (ile nagrobków zgaśnie, ile cudzych nazw nadpisze). Bez
        # preselekcji jego wybór przepadał i musiał go powtórzyć w combo — dwie interakcje
        # zmarnowane dokładnie w przypadku, który przy naprawie z kolejki jest REGUŁĄ, nie
        # wyjątkiem (nagrobek albo źródło `path`). Dysklozura zostaje na drodze kliknięcia:
        # preselekcja wypełnia POLE, nie zatwierdza gestu.
        # Kanon spoza biblioteki zostawia combo na pozycji zerowej — okno zachowuje się wtedy
        # dokładnie jak przedtem, zamiast twierdzić wybór, którego nie ma czym pokryć.
        if preselect_canon is not None:
            for i in range(1, self.combo.count()):
                if self.combo.itemData(i)[1] == preselect_canon:
                    self.combo.setCurrentIndex(i)
                    break
        lay.addWidget(self.combo)
        # PUSTY WYNIK SZUKAJKI PROWADZI DO POLA NAZWY (wizytacja: przy „M 44”, którego biblioteka
        # nie ma, lista mówiła tylko „żaden obiekt nie pasuje”, a pole nazwy niżej milczało - user
        # utknął). Fraza bez trafień przechodzi do pola nazwy (`_on_search`), zdanie pod listą mówi,
        # gdzie jest, a zdanie na żywo pod polem - co z nią zrobi zapis (także „założy obiekt”).
        self.search_hint = QLabel("")
        self.search_hint.setWordWrap(True)
        self.search_hint.setProperty("role", "secondary")
        self.search_hint.setVisible(False)
        lay.addWidget(self.search_hint)
        # Fraza, którą okno SAMO wpisało w pole nazwy (None = pole należy do usera): tylko taką
        # wolno zdjąć, gdy szukajka znów trafia, i tylko taką nadpisać nową frazą bez trafień.
        self._przeniesiona = None
        # Nazwa z pola ZAŁOŻY obiekt (kanon spoza bazy) - przycisk mówi to wprost, a Enter
        # z szukajki prowadzi do pola zamiast zapisu (`eventFilter`). `_tekst_akcji` = napis
        # przycisku sprzed trybu zakładania (wołający ustawia własny, np. „Dalej - podgląd…”).
        self._zalozy = False
        self._tekst_akcji = None

        lay.addWidget(QLabel(i18n.t("assign.new_designation")))
        self.designation = QLineEdit()
        self.designation.setPlaceholderText(i18n.t("assign.designation_placeholder"))
        lay.addWidget(self.designation)

        # ZDANIE NA ŻYWO (2026-09-26): „wpisane → kanon Horreum · w nagłówku: forma nagłówka".
        # User widzi, CO zapisze (`M 106` → `NGC4258`) i jak ta nazwa brzmi w karcie `OBJECT`,
        # zanim kliknie. Nazwa nierozpoznana nie dostaje zdania - mówi za nią komunikat błędu.
        self.canon_preview = QLabel("")
        self.canon_preview.setWordWrap(True)
        self.canon_preview.setToolTip(i18n.t("assign.canon_preview_tip"))
        self.canon_preview.setVisible(False)
        lay.addWidget(self.canon_preview)

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
        # NAZWA NIEROZPOZNANA CZERWIENIEJE PO PAUZIE, NIE PRZY ZNAKU (OB11): w trakcie pisania pole
        # jest w stanie neutralnym (OK wygaszony - nazwa jeszcze nie prowadzi do obiektu), a zdanie
        # błędu przychodzi po `_PAUZA_NAZWY_MS` bez klawisza albo od razu po wyjściu z pola
        # i Enterze.
        # `_nierozpoznana` = tekst, o którym timer ma powiedzieć; zmiana pola go podmienia.
        self._nierozpoznana = None
        self._pauza_nazwy = QTimer(self)
        self._pauza_nazwy.setSingleShot(True)
        self._pauza_nazwy.setInterval(_PAUZA_NAZWY_MS)
        self._pauza_nazwy.timeout.connect(self.zweryfikuj_nazwe)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.accept_btn = buttons.button(QDialogButtonBox.Ok)
        self.accept_btn.setText(i18n.t_plural("assign.accept_btn", frame_count))
        # Enter z szukajki albo pola nazwy zatwierdza (AR-98) - jawnie, nie z domysłu
        # `QDialogButtonBox` przy pokazaniu okna; wygaszony OK Entera nie przepuszcza.
        self.accept_btn.setDefault(True)
        # Tekst przycisku z katalogu, nie z Qt (precedens `planner.py`): repo nie wozi QTranslator,
        # więc `Cancel` zostawało po angielsku obok spolszczonego „Przypisz N klatek".
        buttons.button(QDialogButtonBox.Cancel).setText(i18n.t("assign.cancel_btn"))
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self.combo.currentIndexChanged.connect(self._sync_accept_enabled)
        self.designation.textChanged.connect(self._sync_accept_enabled)
        self.designation.editingFinished.connect(self.zweryfikuj_nazwe)   # wyjście z pola, Enter
        # Edycja RĘKĄ (nie `setText` okna) zabiera polu status frazy przeniesionej.
        self.designation.textEdited.connect(self._on_designation_edited)
        self.combo.activated.connect(self._on_combo_activated)
        self.search.textChanged.connect(self._on_search)
        self.search.installEventFilter(self)
        self._sync_accept_enabled()

    def exec(self):
        """Modalny bieg i kasacja okna - wzorzec `object_change_dialog.ObjectChangeDialog.exec`:
        wołający czyta wyłącznie `selected` po `exec`, a odroczona kasacja przychodzi w jego pętli
        zdarzeń, po slocie."""
        try:
            return super().exec()
        finally:
            self.deleteLater()

    def _item_text(self, o):
        """Pozycja listy: `kanon · katalog · aliasy` (`NGC4258  ·  NGC  ·  M106`)."""
        tekst = f"{o['canon']}  ·  {o['catalog'] or '-'}"
        aliasy = self._aliasy.get(o["canon"])
        return f"{tekst}  ·  {', '.join(aliasy)}" if aliasy else tekst

    def _fill_combo(self, text, wybor=True):
        """Przeładuj listę do obiektów trafionych frazą `text` (pusta fraza = cała biblioteka).

        Wybór PRZEŻYWA zawężenie, gdy wybrany obiekt nadal jest na liście; gdy fraza go chowa,
        combo wraca na pozycję zerową - akcja nie może celować w obiekt, którego user nie widzi.
        JEDNO TRAFIENIE = PRESELEKCJA (AR-98): fraza, która zawęża listę do jednego obiektu, już
        wskazała cel - combo staje na nim, OK się zapala, a Enter z szukajki zatwierdza (wizytacja:
        „M106" kosztowało 5 interakcji zamiast 3). Preselekcja jest zwykłym wyborem i podlega tej
        samej regule: szersza fraza, która ją dalej pokazuje, ją zostawia; fraza, która ją chowa,
        cofa combo na zero (albo na nowe jedyne trafienie). Pusta fraza niczego nie preselekcjonuje
        - jedyny obiekt biblioteki to nie jest trafienie szukajki.
        Sygnały zablokowane na czas przeładunku: `clear()` emituje zmianę indeksu dla każdej
        pozycji po drodze, a stan akcji liczy wołający raz, po wszystkim. Zwraca liczbę trafień
        (zero przy niepustej frazie prowadzi do pola nazwy - `_on_search`). `wybor=False` = fraza
        przechodzi do pola nazwy mimo trafień prefiksem (`_on_search`, Z37): combo stoi na zerze -
        pole nazwy i tak nadpisuje listę, a zaznaczony obiekt obok niego kłamałby o celu."""
        wybrany = self.combo.currentData() if wybor else None
        # Igła BEZ OGONKÓW: predykat liczy `norm_alnum`, który litery diakrytyczne wycina,
        # więc złożenie musi nastąpić przed nim (`klucz_szukania`). Predykat zostaje wspólny
        # z listwą facetów; składanie jest własnością tego okna.
        igla = bez_diakrytykow(text)
        trafione = [o for o in self._objects
                    if facet_model.search_hit(igla, o["canon"], self._szukaj) is not None]
        fraza = (text or "").strip()
        self.combo.blockSignals(True)
        try:
            self.combo.clear()
            self.combo.addItem(i18n.t("assign.search_empty", text=fraza)
                               if fraza and not trafione else i18n.t("assign.pick_object"), None)
            indeks = 0
            for o in trafione:
                self.combo.addItem(self._item_text(o), (o["id"], o["canon"], o["catalog"]))
                if wybrany is not None and wybrany[0] == o["id"]:
                    indeks = self.combo.count() - 1
            if indeks == 0 and fraza and len(trafione) == 1 and wybor:
                indeks = 1                                  # jedno trafienie = preselekcja (AR-98)
            self.combo.setCurrentIndex(indeks)
        finally:
            self.combo.blockSignals(False)
        return len(trafione)

    def _bez_dokladnego(self, fraza):
        """Czy fraza to PEŁNE oznaczenie katalogowe (`catalog_canon`), którego obiektu nie ma na
        liście - ani kanonem (przed i po `xref`), ani aliasem (reguła dokładności
        `facet_model.search_hit`). Szukajka pokazuje wtedy obiekty, których kanon zaczyna się od
        frazy („M 1” → M101, M106), a nazwanego obiektu nie ma (Z37)."""
        cc = catalog_canon(fraza, split=False) if fraza else None
        if cc is None:
            return False
        cele, klucz = {cc, xref(cc)}, norm_alnum(cc)
        return not any(o["canon"] in cele or klucz in self._szukaj.get(o["canon"], ())
                       for o in self._objects)

    def _on_search(self, text):
        """Zawężenie listy; fraza BEZ TRAFIEŃ - albo pełne oznaczenie katalogowe bez trafienia
        dokładnego, przy samych trafieniach prefiksem (`_bez_dokladnego`: „M 1” → M101, M106) -
        przechodzi do pola nazwy, jeśli pole jest puste albo niesie poprzednią frazę przeniesioną
        przez okno; wpisu usera okno nie nadpisuje, tylko mówi, gdzie go dać. Trafienia prefiksem
        zostają na liście, ale bez wyboru. Fraza znów z trafieniem dokładnym (albo pusta) zdejmuje
        z pola to, co okno samo tam wpisało. Pole nazwy z treścią nadpisuje wybór z listy, a zdanie
        na żywo pod nim mówi, co zrobi zapis - przeniesiona nazwa jest widoczna, zanim cokolwiek
        pójdzie dalej, a Enter w szukajce przy nazwie, która ZAŁOŻY obiekt, prowadzi do pola nazwy
        zamiast zapisu (`eventFilter`)."""
        fraza = (text or "").strip()
        prefiksem = self._bez_dokladnego(fraza)
        bez_trafien = (self._fill_combo(text, wybor=not prefiksem) == 0 or prefiksem) and bool(fraza)
        if bez_trafien and (not self.designation.text().strip() or self._przeniesiona is not None):
            self._przeniesiona = fraza
            self.designation.setText(fraza)
        elif not bez_trafien and self._przeniesiona is not None:
            self._przeniesiona = None
            self.designation.clear()
        self.search_hint.setText(i18n.t("assign.search_moved") if self._przeniesiona is not None
                                 else i18n.t("assign.search_to_field"))
        self.search_hint.setVisible(bez_trafien)
        self._sync_accept_enabled()

    def _on_designation_edited(self, _text):
        self._przeniesiona = None

    def _on_combo_activated(self, _index):
        """Wybór z listy RĘKĄ zdejmuje z pola nazwy frazę przeniesioną przez okno - inaczej pole
        nadpisałoby obiekt, który człowiek właśnie wskazał (trafienia prefiksem stoją na liście
        obok przeniesionej frazy, Z37). Wpisu usera wybór nie rusza."""
        if self._przeniesiona is not None:
            self._przeniesiona = None
            self.designation.clear()
            self.search_hint.setText(i18n.t("assign.search_to_field"))

    def eventFilter(self, obj, event):
        """ENTER W SZUKAJCE NIE ZAKŁADA OBIEKTU (Z26/Z36, wizytacja natywna: „NGC 1952” + Enter →
        43 klatki przypisane, obiekt założony, alias ręki zapisany). Gdy fraza przeszła do pola
        nazwy, a nazwa nie wskazuje obiektu z bazy (założy nowy albo się nie rozwiązuje), Enter
        z szukajki przenosi fokus do pola nazwy z zaznaczoną treścią - zapis dopiero Enterem
        w polu nazwy albo przyciskiem, który mówi, że założy obiekt. Jedno trafienie listy + Enter
        (AR-98) idzie dalej zwykłą drogą przycisku domyślnego."""
        if (obj is self.search and event.type() == QEvent.KeyPress
                and event.key() in (Qt.Key_Return, Qt.Key_Enter)
                and self._przeniesiona is not None
                and (self._zalozy or not self.accept_btn.isEnabled())):
            self.designation.setFocus()
            self.designation.selectAll()
            return True
        return super().eventFilter(obj, event)

    def _fail(self, msg):
        self.error.setText(msg)
        dopasuj_wysokosc(self)

    _broni_sie_sama = staticmethod(broni_sie_sama)     # funkcja modułowa (R-S2b-12) — jeden właściciel

    def _sync_accept_enabled(self):
        """Akcja wymaga JAWNEGO celu; wpisaną nazwę walidujemy na żywo, żeby disabled miał powód -
        zdanie powodu przychodzi po pauzie w pisaniu albo po wyjściu z pola (`zweryfikuj_nazwe`).

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
            self.canon_preview.setVisible(False)
            self._ustaw_zakladanie(None)
            return self._fail(i18n.t("assign.dictionary_broken"))
        self.accept_btn.setEnabled(valid_name if text else self.combo.currentData() is not None)
        # Nazwa nierozpoznana: zdanie błędu dopiero po pauzie w pisaniu (`zweryfikuj_nazwe`) -
        # każdy znak odkłada je od nowa, nazwa rozpoznana albo puste pole je odwołuje.
        self._nierozpoznana = text if text and not valid_name else None
        if self._nierozpoznana is not None:
            self._pauza_nazwy.start()
        else:
            self._pauza_nazwy.stop()
        # Zdanie na żywo z TEJ SAMEJ tożsamości, którą zapisze `_validate_and_accept`; warunek na
        # zmiennej lokalnej, nie na `isVisible()` (ta sama lekcja, co przy nocie niżej).
        podglad = ident is not None
        self.canon_preview.setVisible(podglad)
        # Kanon, którego baza nie zna, ZAŁOŻY obiekt (klinga zapisu go wstawia) - zdanie mówi to
        # przed kliknięciem. Id po kanonie tą samą frazą co pre-check i klinga
        # (`queries.object_id_by_canon`), nie z listy: obiekt bez klatek jest w bazie, choć lista
        # (`library_objects`, `JOIN frame`) go nie pokazuje.
        nowy = podglad and queries.object_id_by_canon(self.con, ident.canon) is None
        self.canon_preview.setText(
            i18n.t("assign.canon_preview", text=text, canon=ident.canon,
                   header=header_form(ident.canon))
            + (i18n.t("assign.creates_object") if nowy else "")
            if podglad else "")
        self._ustaw_zakladanie(ident.canon if nowy else None)
        # Nota po RODZAJU, nie po pustym katalogu: `catalog IS NULL` mają też obiekty z REGIONU
        # (`Veil`), a nazwanie ich „obiektem własnym" byłoby nieprawdą o pochodzeniu kanonu.
        wlasny = ident is not None and ident.kind == "own"
        # Warunek na LOKALNEJ zmiennej, nie na `isVisible()`: przy niepokazanym oknie ta metoda
        # zwraca False niezależnie od `setVisible` (lekcja STANDING kolejki), więc nota nigdy nie
        # dostałaby treści przed pierwszym wyświetleniem dialogu.
        self.own_note.setVisible(wlasny)
        if wlasny:
            self.own_note.setText(i18n.t("assign.own_object_note", canon=ident.canon))
        # AR-135: wybór z listy starej tożsamości pary `catalog_xref` (`M33` obok żywego `NGC598`)
        # idzie do celu pary - zdanie mówi to przed kliknięciem, tą samą regułą co zapis.
        wybor = self.combo.currentData() if not text else None
        cel = queries.xref_live_target(self.con, wybor[1]) if wybor is not None else None
        if cel is not None:
            self.canon_preview.setVisible(True)
            self.canon_preview.setText(i18n.t("assign.xref_redirect", old=wybor[1],
                                              new=cel["canon"]))
        dopasuj_wysokosc(self)          # okno rośnie do zawiniętych zdań (`config_dialog`)

    def zweryfikuj_nazwe(self):
        """Powiedz TERAZ, że wpisana nazwa jest nierozpoznana - koniec pauzy w pisaniu, wyjście
        z pola albo Enter (OB11). Bez nazwy nierozpoznanej nic nie robi. Publiczna, bo jest też
        deterministyczną drogą testu: wpis `setText` + to wołanie zamiast czekania na timer."""
        self._pauza_nazwy.stop()
        tekst = self.designation.text().strip()
        if self._nierozpoznana is not None and self._nierozpoznana == tekst:
            self._fail(i18n.t("assign.unknown_name", text=self._nierozpoznana))

    def showEvent(self, event):
        super().showEvent(event)
        dopasuj_wysokosc(self)

    def _ustaw_zakladanie(self, canon):
        """Przycisk akcji mówi WPROST, że zapis założy obiekt `canon` („Załóż NGC1952 · Przypisz
        2 klatki”, w wybieraku „… · Dalej - podgląd…”); `None` przywraca napis wołającego."""
        self._zalozy = canon is not None
        if canon is not None:
            if self._tekst_akcji is None:
                self._tekst_akcji = self.accept_btn.text()
            self.accept_btn.setText(i18n.t("assign.create_btn", canon=canon,
                                           action=self._tekst_akcji))
        elif self._tekst_akcji is not None:
            self.accept_btn.setText(self._tekst_akcji)
            self._tekst_akcji = None

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
            # AR-135: stara tożsamość pary `catalog_xref` z ŻYWYM celem → cel pary (jedna reguła
            # z celem gestu „Zmień obiekt…” i skrótem „ostatnio użyte”: `xref_live_target`).
            cel = queries.xref_live_target(self.con, canon)
            if cel is not None:
                canon, catalog = cel["canon"], cel["catalog"]
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
