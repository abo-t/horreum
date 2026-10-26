"""Motyw GUI (F6, PLAN_ux_redesign §7) — logika Qt-WOLNA: paleta/kolory jako hex-stringi + generator
QSS akcentów. QPalette/QColor SKŁADANE w warstwie widżetów (`app.py`/`grid.py`/`facets.py`) z tych
stałych — ten plik nie importuje PySide6 (test izolacji `test_gui_isolation`, wzorzec `facet_model`).

Dwa motywy: **ciemny (default)** i jasny — oba pełnoprawne, IDENTYCZNY zbiór kluczy (żadna dziura per
motyw; pinowane testem). Kolory stanów gridu (`grid_colors`) i wykluczeń facetów (`facet_colors`) mają
warianty per motyw — pale-tła jasnego byłyby nieczytelne na ciemnej bazie. Granica QSettings łagodna
(`normalize`), silnik fail-fast (`palette_spec`/`grid_colors` podnoszą ValueError na nieznanym motywie)."""
from __future__ import annotations

DEFAULT = "dark"

# QPalette: rola → hex. Klucze = nasze nazwy ról (mapowane na QPalette.ColorRole w `app.py`).
_PALETTE = {
    "dark": {
        "window": "#2B2B2B", "window_text": "#E6E6E6",
        "base": "#1E1E1E", "alt_base": "#262626", "text": "#E6E6E6",
        "button": "#3A3A3A", "button_text": "#E6E6E6", "bright_text": "#FF5555",
        "highlight": "#4A78C8", "highlight_text": "#FFFFFF",
        "tooltip_base": "#3A3A3A", "tooltip_text": "#E6E6E6",
        "link": "#5AA0FF", "placeholder": "#8A8A8A", "disabled_text": "#6E6E6E",
    },
    "light": {
        "window": "#F0F0F0", "window_text": "#1E1E1E",
        "base": "#FFFFFF", "alt_base": "#F6F6F6", "text": "#1E1E1E",
        "button": "#E9E9E9", "button_text": "#1E1E1E", "bright_text": "#B00000",
        "highlight": "#3D7EFF", "highlight_text": "#FFFFFF",
        "tooltip_base": "#FFFFDC", "tooltip_text": "#1E1E1E",
        "link": "#0B61C4", "placeholder": "#9A9A9A", "disabled_text": "#A6A6A6",
    },
}

# Kolory stanów gridu (tła wierszy/nagłówka + szarość braku). Jasny = obecne pale wartości
# (`grid.py` sprzed F6); ciemny = warianty czytelne na bazie #1E1E1E.
_GRID = {
    "dark": {
        # group_bg #3C3C3C: własny akcent belki grupy nad bazą #1E1E1E i odróżnialny od skipped_bg
        # #2C2C2C (wizytator F6 oś B — neutrale zbyt blisko; belka niesie też bold+▸).
        # superseded_bg sepia: klatka ZASTĄPIONA nie jest awarią (czerwień „zniknięte") ani
        # osobliwością do rozstrzygnięcia (błękit „duplikaty") — jest ZAPISEM HISTORII, więc dostaje
        # ton archiwalny. Oś ciepła też ją oddziela od obu neutrali (group_bg\skipped_bg).
        # retired_bg fiolet: klatka WYCOFANA to też zapis historii, ale zamknięty CZYJĄŚ DECYZJĄ,
        # nie faktem o świecie — a ta różnica jest robocza (wycofanie ręka cofa jednym gestem,
        # zastąpienia nie cofa nikt), więc ton ma być odróżnialny od sepii, nie jej odcieniem.
        # missing: szarość BRAKU liczona pod AA 4,5:1 na KAŻDYM tle tego motywu, nie tylko na
        # bazie - ta sama komórka ląduje na siedmiu tłach stanów, a od FC-3 także na belce grupy.
        # Dobór wiąże najciaśniejsze tło (`touched_bg` 4,55:1, `group_bg` 4,64:1); poprzednie
        # #8A8A8A dawało 4,38:1 na alt_base i 3,13:1 na touched_bg. Bramka: `test_theme`.
        "missing": "#A8A8A8", "vanished_bg": "#4A2A2A", "dup_bg": "#22344A",
        "group_bg": "#3C3C3C", "touched_bg": "#274427", "skipped_bg": "#2C2C2C",
        "superseded_bg": "#403524", "retired_bg": "#33294A",
    },
    "light": {
        # Jasny motyw miał tu najgorszą liczbę CAŁEJ palety: #999999 na alt_base to 2,64:1, czyli
        # poniżej nawet AA-large 3:1 - a niesie ją 2364 komórki kalibracji i każdy znacznik `↺`,
        # który bywa jedyną treścią komórki. #666666 daje 5,31:1 na alt_base i 4,52:1 na belce grupy.
        "missing": "#666666", "vanished_bg": "#FFE5E5", "dup_bg": "#E5F0FF",
        "group_bg": "#E4E4E4", "touched_bg": "#E3F6E3", "skipped_bg": "#F2F2F2",
        "superseded_bg": "#F3EBD8", "retired_bg": "#EDE7F6",
    },
}

# Czerwień wykluczeń facetów (foreground ⊖). Ciemny = jaśniejsza czerwień, czytelna na dark.
_FACET = {
    "dark": {"exclusion": "#FF6E6E"},
    "light": {"exclusion": "#B00000"},
}

# Akcenty do QSS (złoto spichlerza, zieleń poczekalni-OK, czerwień wykluczeń) i tekst drugorzędny
# (etykiety kryteriów/celu/wyniku — na dark hardcoded #666 byłby nieczytelny, F6 recenzja #3).
# `warn` jest OSOBNY od `gold` (P-C): złoto to akcent MARKI (chipy planera, punkty mapy), bursztyn
# to znaczenie „poszło, ale nie w całości". Wartości dobrane pod AA 4,5 na `base` OBU motywów
# (zmierzone: dark 7,4:1 · light 6,3:1) — `gold` w jasnym ma 2,7:1 i do tekstu się nie nadaje
# (ta sama pułapka co wiz T5 N5 w `planner.use_theme`).
_ACCENT = {
    "dark": {"gold": "#E0A030", "ok_green": "#5FB65F", "exclusion_red": "#FF6E6E",
             "warn": "#F0B040", "secondary_text": "#A8A8A8"},
    "light": {"gold": "#D08000", "ok_green": "#2E7D32", "exclusion_red": "#B00000",
              "warn": "#8A5300", "secondary_text": "#666666"},
}

# Kolory mapy stanowisk (F8 §9 — QPainter scatter na tle konturów NE). `land` = przygaszony kontur
# (TŁO, nie punkt); `site`/`site_selected` = złoto spichlerza + jaśniejsze wyróżnienie zaznaczenia;
# `scale` = tekst drugorzędny (pasek skali + etykiety stanowisk). Warianty per motyw — kontur na
# jasnym tle musi być ciemniejszy niż na ciemnym. IDENTYCZNY zbiór kluczy (pin test_theme).
_MAP = {
    "dark": {"bg": "#1E1E1E", "land": "#505050", "site": "#E0A030",
             "site_selected": "#FF8C1A", "sel_ring": "#7AB0FF", "scale": "#9A9A9A"},
    "light": {"bg": "#FFFFFF", "land": "#BEBEBE", "site": "#D08000",
              "site_selected": "#E85D00", "sel_ring": "#1E5FCC", "scale": "#808080"},
}


# Złota akcja Dostawy („Przyjmij nowe", odbiór 0.19.0 DO6): ciemny bursztyn zamiast szarości przycisku
# Fusion. Tekst biały pod AA 4,5 na KAŻDYM tle stanu (zmierzone: dark 7,48 / 6,33 / 8,95 · light
# 5,33 / 4,88 / 6,33 dla tła / najechania / wciśnięcia), ramka odcina przycisk od okna co najmniej
# 3:1 (WCAG 1.4.11; dark 6,23 na `window`, light 9,12). Ciemny bursztyn na ciemnym oknie sam się nie
# odcina (1,89:1), więc tam granicę niesie złota ramka. Stan wyłączony NIE ma tu kluczy: bierze
# `button`/`disabled_text` palety jak każdy wygaszony przycisk aplikacji - ma wyglądać na nieaktywny,
# nie na przygaszony bursztyn. Bramka: `test_theme`.
# `focus` = ramka fokusu klawiatury (WCAG 2.4.7): arkusz z ramką zdejmuje natywny wskaźnik Fusion.
# Co najmniej 3:1 do tła KAŻDEGO stanu i do okna (dark biel: 7,48 / 6,33 / 8,95, okno 14,16; light
# czerń: 3,94 / 4,30 / 3,32, okno 18,43). Dlatego tła jasnego motywu są o stopień jaśniejsze niż
# `warn`: przy dawnym wciśnięciu `#7A4A00` czerń miała 2,81:1, a jeden kolor ramki nie przejdzie 3:1
# jednocześnie do ciemnego bursztynu i do jasnego okna inaczej niż czernią na jaśniejszym tle.
_ZLOTA_AKCJA = {
    "dark": {"bg": "#7A4A00", "bg_hover": "#8A5300", "bg_pressed": "#6A4000",
             "text": "#FFFFFF", "border": "#E0A030", "focus": "#FFFFFF"},
    "light": {"bg": "#9A5D00", "bg_hover": "#A36200", "bg_pressed": "#8A5300",
              "text": "#FFFFFF", "border": "#5C3800", "focus": "#000000"},
}

# Nazwa obiektu przycisku złotej akcji Dostawy - selektor jej reguły w `qss`.
ZLOTA_AKCJA_OBJECT_NAME = "zlota_akcja"


def normalize(name):
    """Nazwa motywu z QSettings → znany motyw (nieznana/None → DEFAULT). Granica łagodna."""
    return name if name in _PALETTE else DEFAULT


def _spec(table, name):
    if name not in table:
        raise ValueError(f"nieznany motyw: {name!r} (znane: {sorted(_PALETTE)})")
    return dict(table[name])


def palette_spec(name):
    """Rola QPalette → hex dla motywu `name`. ValueError na nieznanym (EXPECT — caller normalizuje)."""
    return _spec(_PALETTE, name)


def grid_colors(name):
    """Kolory stanów gridu → hex.
    Klucze: missing/vanished_bg/dup_bg/group_bg/touched_bg/skipped_bg/superseded_bg/retired_bg."""
    return _spec(_GRID, name)


def facet_colors(name):
    """Kolory facetów → hex. Klucz: exclusion (foreground ⊖)."""
    return _spec(_FACET, name)


def accents(name):
    """Akcenty → hex. Klucze: gold/ok_green/exclusion_red/warn/secondary_text."""
    return _spec(_ACCENT, name)


def map_colors(name):
    """Kolory mapy stanowisk → hex. Klucze: bg/land/site/site_selected/sel_ring/scale (F8)."""
    return _spec(_MAP, name)


def zlota_akcja(name):
    """Kolory złotej akcji Dostawy → hex. Klucze: bg/bg_hover/bg_pressed/text/border/focus (DO6)."""
    return _spec(_ZLOTA_AKCJA, name)


ROLES = {"secondary": "secondary_text", "error": "exclusion_red", "warn": "warn", "ok": "ok_green"}

# Nazwa obiektu przycisku recepty paska stanu - selektor reguły wygaszenia w `qss`.
RECEPTA_OBJECT_NAME = "recepta"


def recepta_wygaszona(name):
    """(kolor tekstu, tło) WYGASZONEJ recepty paska stanu - jeden właściciel, z którego czyta `qss`
    i bramka kontrastu.

    Wygaszona recepta (wariant „potem", blokada po kliknięciu) to ZDANIE DO PRZECZYTANIA, nie martwa
    kontrolka: domyślne `disabled_text` na tle przycisku dawało w ciemnym motywie 1,63:1 (firsthand
    na platformie natywnej). Tekst bierze więc `secondary_text` (AA 4,5:1 na `window` obu motywów),
    a tło jest tłem PASKA (`window`), nie przycisku - wygaszenie mówi ramka przerywana i kursor,
    nie zgaszony kolor liter."""
    return accents(name)["secondary_text"], palette_spec(name)["window"]


# Selektory wskaźnika NIEZAZNACZONEGO pola wyboru (AR-73). Listy z polami wyboru są dziś wyłącznie
# `QListWidget` (okno „Wskaż stanowisko", konfiguracja źródeł, wybór kolumn), więc `QListView`
# wystarcza; drzewa i tabele pól wyboru nie niosą.
WSKAZNIK_CHECKBOX = ("QCheckBox::indicator:unchecked", "QListView::indicator:unchecked")
WSKAZNIK_RADIO = "QRadioButton::indicator:unchecked"
# Selektor ZAZNACZONEGO radia - jedyny stan zaznaczony, który arkusz umie narysować w całości:
# kropkę daje gradient radialny tła, więc znak zaznaczenia nie ginie (ptaszka pola wyboru gradient
# nie narysuje - ten stan maluje dalej Fusion).
WSKAZNIK_RADIO_ZAZNACZONY = "QRadioButton::indicator:checked"


def wskaznik_odznaczony(name):
    """(ramka, wypełnienie) NIEZAZNACZONEGO wskaźnika pola wyboru i radia (AR-73) - jeden właściciel,
    z którego czyta `qss` i bramka kontrastu.

    Fusion rysuje ramkę pustego pola kolorem wyprowadzonym z tła: w ciemnym motywie `#222222` na
    `#1E1E1E` (zmierzone 1,03:1), w jasnym `#BDBDBD` na `#FFFFFF` (1,9:1) - oba poniżej 3:1, które
    WCAG 1.4.11 stawia elementom sterującym. Lista 178 odznaczonych wierszy nie wyglądała przez to
    na listę do zaznaczania. Ramka bierze `secondary_text` (ten sam kolor, którym mówi tekst
    drugorzędny), wypełnienie zostaje `base` jak u Fusion."""
    return accents(name)["secondary_text"], palette_spec(name)["base"]


def wskaznik_zaznaczony(name):
    """(ramka i kropka, wypełnienie) ZAZNACZONEGO radia - jeden właściciel, z którego czyta `qss`
    i bramka kontrastu.

    Po AR-73 pusty wskaźnik dostał jasną ramkę, a zaznaczony został przy ramce Fusion `#222222` na
    `#1E1E1E` (1,03:1): w ciemnym motywie zaznaczone radio wyglądało SŁABIEJ niż puste obok - ekran
    mówił odwrotnie, niż jest. Ramka i kropka biorą `text` (najmocniejszy kolor treści palety, mocniejszy
    od `secondary_text` pustej ramki w obu motywach), wypełnienie `base` jak u pustego."""
    paleta = palette_spec(name)
    return paleta["text"], paleta["base"]


def _qss_wskaznikow(name):
    """Reguły wyłącznie dla stanu `:unchecked`: styl arkusza z ramką rysuje SAM prostokąt bez
    znaku zaznaczenia, więc reguła na `:checked` zgasiłaby ptaszka (bez obrazka go nie ma). Stan
    zaznaczony i częściowy maluje dalej Fusion. Rozmiar 12 px + ramka 1 px = 14 px, czyli metryka
    wskaźnika Fusion - pole nie skacze przy przełączeniu. Wyłączone pole dostaje ramkę
    `disabled_text`, żeby nie udawało aktywnego.

    Reguła na wskaźniku przełącza liczenie rozmiaru pola na arkusz, który gubi margines ramki
    fokusu Fusion: podpowiedź wysokości spadała z 21 do 16 px (zmierzone natywnie, czcionka 16 px),
    czyli każdy rząd pól wyboru ściskał się o 5 px. Wypełnienie 2 + 3 px oddaje dawną wysokość.

    Wyjątek od reguły „tylko `:unchecked`": ZAZNACZONE RADIO (`WSKAZNIK_RADIO_ZAZNACZONY`) - kropkę
    rysuje gradient radialny tła, więc arkusz nie gasi znaku; ramka i kropka z `wskaznik_zaznaczony`,
    mocniejsze od pustej ramki. Ten sam rozmiar 12 + 1 px - radio nie skacze przy przełączeniu."""
    ramka, tlo = wskaznik_odznaczony(name)
    wygaszona = palette_spec(name)["disabled_text"]
    pole = f"border: 1px solid {ramka}; background: {tlo}; width: 12px; height: 12px;"
    znak, tlo_znaku = wskaznik_zaznaczony(name)

    def _kropka(kolor):
        return ("qradialgradient(cx: 0.5, cy: 0.5, radius: 0.5, fx: 0.5, fy: 0.5, "
                f"stop: 0 {kolor}, stop: 0.42 {kolor}, stop: 0.52 {tlo_znaku}, stop: 1 {tlo_znaku})")

    return ("QCheckBox, QRadioButton { padding: 2px 0px 3px 0px; }"
            + ", ".join(WSKAZNIK_CHECKBOX) + f" {{ {pole} }}"
            + f"{WSKAZNIK_RADIO} {{ {pole} border-radius: 7px; }}"
            + ", ".join(s + ":disabled" for s in (*WSKAZNIK_CHECKBOX, WSKAZNIK_RADIO))
            + f" {{ border-color: {wygaszona}; }}"
            + f"{WSKAZNIK_RADIO_ZAZNACZONY} {{ border: 1px solid {znak}; width: 12px; height: 12px; "
            f"border-radius: 7px; background: {_kropka(znak)}; }}"
            + f"{WSKAZNIK_RADIO_ZAZNACZONY}:disabled {{ border-color: {wygaszona}; "
            f"background: {_kropka(wygaszona)}; }}")


def qss(name):
    """Arkusz stylów akcentów dla motywu: własność `role` etykiety → kolor z `ROLES` (widżet pisze
    `setProperty("role","error")` zamiast inline `color:`). Rola jest CZYTANA PRZY POLISHU — etykieta,
    która zmienia rolę w locie, musi przejść `unpolish`/`polish`; robi to `grid._set_role` (kropka
    poczekalni ● / ○ i flaga panelu daty). Arkusz idzie na `QApplication`, więc przełączenie motywu
    przemalowuje sam.

    PRZYCISK-PRZEŁĄCZNIK MUSI BYĆ WIDOCZNY, gdy jest wciśnięty (wiz #5). Fusion maluje `:checked`
    różnicą, którą ZMIERZONO na 17/255 kanału (średnia 9) — `isChecked()` mówiło `True`, a oko nie
    widziało nic. Ramka w kolorze złota daje sygnał niezależny od tła i od motywu; dotyczy
    WSZYSTKICH przełączników paska zbioru („Rodowód…", „Popraw nagłówki…", „Uporządkuj nazwy…"),
    bo to jedna klasa kontrolki, nie trzy osobne przypadki.

    ZŁOTA AKCJA DOSTAWY (DO6) dostaje kolor i wagę pisma z reguły po nazwie obiektu, nie arkuszem widżetu:
    arkusz aplikacji przełącza motyw sam, a wysokość zostaje przy widżecie (AR-347)."""
    a = accents(name)
    tekst, tlo = recepta_wygaszona(name)
    return "".join(
        f'QLabel[role="{role}"] {{ color: {a[key]}; }}' for role, key in ROLES.items()
    ) + (f'QPushButton:checked {{ border: 2px solid {a["gold"]}; font-weight: bold; }}') + (
        f'QToolButton#{RECEPTA_OBJECT_NAME}:disabled {{ color: {tekst}; background: {tlo}; '
        f'border: 1px dashed {tekst}; padding: 2px 4px; }}') + _qss_zlotej_akcji(name) + (
        _qss_wskaznikow(name))


def _qss_zlotej_akcji(name):
    """Reguła złotej akcji Dostawy: tło, tekst i ramka z `zlota_akcja`, najechanie i wciśnięcie tym
    samym bursztynem jaśniej i ciemniej. Wyłączona bierze tło przycisku i `disabled_text` palety -
    wygląda jak każdy wygaszony przycisk, a nie jak bursztyn, który da się kliknąć. Ramka i wypełnienie
    nie zmieniają grubości między stanami, więc przycisk nie skacze.

    FOKUS KLAWIATURY ma własną regułę, bo arkusz z ramką zdejmuje natywny wskaźnik Fusion: zmienia
    WYŁĄCZNIE kolor ramki (ta sama grubość 1 px), więc rozmiar stoi. Kolejność reguł niesie
    pierwszeństwo przy równej szczegółowości: `:hover`/`:pressed` ruszają tylko tło, `:focus` tylko
    ramkę, a `:disabled` stoi OSTATNI i nadpisuje ramkę - wyłączony przycisk nie świeci fokusem.
    Promień 5 px = sylwetka narożnika przycisku Fusion, zmierzona maską pikseli rogu na tle okna.

    POGRUBIENIE W TEJ SAMEJ REGULE (AR-347, decyzja CEO), jak `QPushButton:checked` w `qss`: waga idzie za nazwą
    obiektu, więc za akcentem przy każdym przepolerowaniu i zmianie motywu. `setFont` przy widżecie przegrywał
    z arkuszem - `QStyleSheetStyle` zapamiętuje font z pierwszego polerowania i przywraca go przy `unpolish`
    (Qt 6.9.2), więc gest powodu był złoty bez pogrubienia, a „Przyjmij nowe” zostawało pogrubione."""
    z = zlota_akcja(name)
    paleta = palette_spec(name)
    sel = f"QPushButton#{ZLOTA_AKCJA_OBJECT_NAME}"
    return (f"{sel} {{ background: {z['bg']}; color: {z['text']}; border: 1px solid {z['border']}; "
            f"font-weight: bold; border-radius: 5px; padding: 3px 6px; }}"
            f"{sel}:hover {{ background: {z['bg_hover']}; }}"
            f"{sel}:pressed {{ background: {z['bg_pressed']}; }}"
            f"{sel}:focus {{ border-color: {z['focus']}; }}"
            f"{sel}:disabled {{ background: {paleta['button']}; color: {paleta['disabled_text']}; "
            f"border-color: {paleta['disabled_text']}; }}")
