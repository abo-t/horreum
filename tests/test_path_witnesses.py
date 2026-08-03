r"""Świadkowie ŚCIEŻKI — charakteryzacja przeniesiona na kod po zejściu reguł (S2, §4 wiersz 15).

CO TO ZA TEST. Powstał w S0 jako charakteryzacja TRZECH funkcji z `horreum.gui.app`
(`_witness_folder`/`_witness_filename`/`_path_proposal`) — jedynej reguły ścieżki, jaką repo wtedy
miało i która nie miała ani jednego testu. S2 zeszło dwie reguły ścieżki do JEDNEJ drabiny, więc
plik śledzi ten ruch: pyta dziś `resolve.paths` (czyste funkcje, Qt-wolne) i `resolver.path_proposal`
(reguła dialogu na wspólnej drabinie).

PINY, KTÓRE MIAŁY SIĘ PRZEWRÓCIĆ — ADJUDYKACJA (S0 wypisał je imiennie, S2 rozlicza):

* **cel — PRZEWRÓCONY zgodnie z planem.** `C8_2600MC` nie daje już `C8`: folder SPRZĘTU przestał
  udawać Caldwella, bo drabina w trybie `from_path` nie tnie po `_` (D-OW-2 pkt 5a).
* **koszt — PRZEWRÓCONY, koszt ZMIERZONY = 0.** `NGC4631_PGC42637` przestał dawać `NGC4631`. Ta
  gałąź działała POPRAWNIE (autorem stringa jest akwizycja), więc przed zejściem zmierzono populację
  P-D: 25 klatek bez karty, TRACI propozycję **0** — kryterium 17 przeszło i dopiero to otworzyło
  ujednolicenie.
* **S1/S2 — PRZEWRÓCONE, i to jest CAŁA obietnica paczki.** `LIGHTS\LMC` i `LMC_20230323.ARW` dają
  dziś `LMC` (słownik nazw własnych z S1 + drabina zamiast `catalog_canon`), a `_SOLAR\Moon` —
  `Moon` (reguła kategorii z S2, marker rodzaju z `_KIND_DIRS`). Gdyby te piny były dalej zielone
  na `None`, znaczyłoby to, że LMC nadal nie działa.
* **D-OW-3 — PRZEWRÓCONY 2026-08-03, i to był cel asercji odmowy.** `LIGHTS\Orion` daje dziś
  `Orion`: osobna sesja się odbyła, wariant A wszedł do słownika, kanon obejmuje CAŁĄ populację
  (pas i miecz nie dostają osobnego kanonu — rozróżnia je obiektyw, nie oś obiektu).

REGUŁA ADJUDYKACJI (bez zmian): przewrócenie pinu to STOP i wpis do briefu, nigdy automatyczne
przestemplowanie. Czerwień spoza wypisanych klas znaczy regresję.

Funkcje ŚCIEŻKI są tu czyste (`resolve.paths` — zero Qt, zero DB), więc ich sekcja nie potrzebuje
ani PySide6, ani bazy. Reguła DIALOGU pyta drabinę, więc potrzebuje połączenia (nie Qt)."""
from horreum import db, resolver
from horreum.resolve.paths import filename_tokens, object_folder, object_from_path

R = "R:\\ASTRO_"
NOW = "2026-08-03T10:00:00Z"


def _con():
    """Pusta baza — drabina pyta o aliasy, więc reguła dialogu potrzebuje połączenia. Obiektów
    nie zakładamy: `LMC` ma się rozwiązać ze SŁOWNIKA, nie ze stanu bazy."""
    con = db.connect(":memory:")
    db.migrate(con)
    return con


# ─────────────────────────────────────────────── świadek FOLDERU (czysta funkcja, `resolve.paths`)


def _sprawdz_folder(path, oczekiwany):
    assert object_from_path(path) == oczekiwany


def test_swiadek_folderu_kotwica_po_markerze():
    """Segment ZARAZ PO markerze rodzaju, bez względu na głębokość i wielkość liter."""
    _sprawdz_folder(rf"{R}\LIGHTS\NGC1976\RC8\L\x.fit", "NGC1976")
    _sprawdz_folder(rf"{R}\lights\NGC7635\RC8\Ha\x.fit", "NGC7635")
    _sprawdz_folder(rf"{R}\LIGHTS\Sh2-229\RC8\Ha\x.fit", "Sh2-229")
    # Marker w liczbie POJEDYNCZEJ — `_KIND_DIRS` zna oba warianty, własny literał `LIGHTS` nie.
    # DARMOWY PIN (D-OW-2 pkt 7): dziś różnica na 0 klatkach, jutro cicha luka.
    _sprawdz_folder(rf"X:\ASTRO_\CALIBRATION\2024\Light\LMC\x.ARW", "LMC")


def test_swiadek_folderu_oddaje_SUROWY_segment():
    """Świadek zwraca TEKST FOLDERU, nie kanon — kanon powstaje wyłącznie z drabiny nazwy.
    Bez tego rozdziału każdy folder o dowolnej nazwie zakładałby obiekt."""
    _sprawdz_folder(rf"{R}\LIGHTS\NGC 7635\RC8\Ha\x.fit", "NGC 7635")
    _sprawdz_folder(rf"{R}\LIGHTS\C8_2600MC\OSC\x.fit", "C8_2600MC")


def test_swiadek_folderu_regula_kategorii():
    """`_SOLAR`/`_COMETS` stoją NA pozycji obiektu, ale obiektem nie są — zejście o poziom niżej
    uprawnia JAWNA lista, nie limit głębokości (odtwarza 674 + 33 = 707 klatek archiwum)."""
    _sprawdz_folder(rf"{R}\LIGHTS\_SOLAR\Moon\A7R3\x.ARW", "Moon")
    _sprawdz_folder(rf"{R}\LIGHTS\_COMETS\21P_Giacobini-Zinner\A7R3\x.ARW", "21P_Giacobini-Zinner")
    # Kategoria BEZ zejścia (ostatni katalog) — milczenie, nie sama kategoria jako obiekt.
    _sprawdz_folder(rf"{R}\LIGHTS\_SOLAR\x.ARW", None)


def test_swiadek_folderu_galezie_kontrolne():
    """Gałęzie kotwicy: brak markera, marker jako ostatni katalog, marker kalibracji (dark NIE ma
    obiektu z definicji), marker DWA razy (rozstrzyga PIERWSZY)."""
    _sprawdz_folder(rf"{R}\CALIBRATION\dark\x.fit", None)
    _sprawdz_folder(rf"{R}\LIGHTS\x.fit", None)
    _sprawdz_folder(rf"{R}\_WBPP\LIGHTS\NGC1976\LIGHTS\NGC7635\x.fit", "NGC1976")
    _sprawdz_folder("", None)
    # Separator POSIX obsłużony tak samo jak windowsowy (R-S0-12: „czyste funkcje ścieżki" nie
    # mają wnosić ukrytej zależności od systemu).
    _sprawdz_folder("/mnt/astro/LIGHTS/NGC1976/RC8/x.fit", "NGC1976")


def test_folder_obiektu_to_prefiks_do_segmentu():
    """Powierzchnia potwierdzania pokazuje ŹRÓDŁO propozycji — folder wspólny dla grupy, nie pełną
    ścieżkę pliku (36 klatek LMC leży w jednym katalogu, a różni je tylko nazwa pliku)."""
    assert object_folder(rf"{R}\LIGHTS\LMC\A7R3_105\OSC\x.ARW") == rf"{R}\LIGHTS\LMC"
    assert object_folder(rf"{R}\LIGHTS\_SOLAR\Moon\A7R3\x.ARW") == rf"{R}\LIGHTS\_SOLAR\Moon"
    assert object_folder(rf"{R}\CALIBRATION\dark\x.fit") is None


def test_czlony_nazwy_pliku():
    """Drugi świadek iteruje po członach `_` — i to jest jego RDZEŃ: po rename v2 oznaczenie ląduje
    w ŚRODKU nazwy. Zakaz cięcia z D-OW-2 pkt 5a dotyczy segmentu KATALOGOWEGO, nie tego."""
    assert filename_tokens(rf"{R}\LIGHTS\LMC\A7R3_105\OSC\LMC_20230323.ARW") == ("LMC", "20230323")
    assert filename_tokens(rf"{R}\LIGHTS\NGC7635\RC8\Ha\M42_Ha_0001.fit") == ("M42", "Ha", "0001")
    assert filename_tokens("") == ()


# ─────────────────────────────────────────────── reguła DIALOGU (dwaj świadkowie na drabinie)


def test_propozycja_dialogu_wymaga_DWOCH_zgodnych_swiadkow():
    """Zapis idzie do PLIKU i jest nieodwracalny bez kopii bajtowej, więc dialog żąda zgodnego
    zeznania folderu I nazwy pliku. Szczebel przebiegu tylko PROPONUJE do bazy, więc stać go na
    jednego świadka — to jest różnica ZAMIERZONA, wypisana w teście parytetu."""
    con = _con()
    assert resolver.path_proposal(con, rf"{R}\LIGHTS\NGC7635\RC8\Ha\NGC7635_0001.fit") == "NGC7635"
    # rozjazd świadków → pole puste, decyzja u człowieka
    assert resolver.path_proposal(con, rf"{R}\LIGHTS\NGC7635\RC8\Ha\M42_Ha_0001.fit") is None
    # drugi świadek milczy → brak propozycji (stąd 31 z 763 dla RAW-ów)
    assert resolver.path_proposal(con, rf"{R}\LIGHTS\NGC1976\RC8\L\x.fit") is None


def test_propozycja_dialogu_NIE_normalizuje_przez_xref():
    """Do PLIKU idzie konwencja USERA (D-PD-9), a nie kanon bazy: zgodne `M42` zostaje `M42`,
    choć drabina nazwy mapuje je na `NGC1976`. Druga z dwóch różnic wypisanych jawnie w §4/16."""
    con = _con()
    assert resolver.path_proposal(con, rf"{R}\LIGHTS\M42\RC8\Ha\M42_0001.fit") == "M42"


def test_PIN_PRZEWROCONY_cel_folder_sprzetu_nie_udaje_katalogu():
    """PIN_PRZEWROCONY(cel): `C8_2600MC` dawał `C8` (Caldwell 8). Po zejściu reguł — cisza."""
    con = _con()
    assert object_from_path(rf"{R}\LIGHTS\C8_2600MC\OSC\C8_0001.fit") == "C8_2600MC"
    assert resolver.path_proposal(con, rf"{R}\LIGHTS\C8_2600MC\OSC\C8_0001.fit") is None
    # …a GOŁE oznaczenie na pozycji obiektu ZOSTAJE przyjęte: gwarancję daje POZYCJA w drzewie,
    # nie filtrowanie tokenów (D-OW-2 pkt 5a — inaczej `M45` straciłoby 10 realnych klatek).
    assert resolver.path_proposal(con, rf"{R}\LIGHTS\C8\OSC\C8_0001.fit") == "C8"


def test_PIN_PRZEWROCONY_koszt_dwuczlonowe_oznaczenie_milczy():
    """PIN_PRZEWROCONY(koszt): `NGC4631_PGC42637` dawał `NGC4631` i ta gałąź działała POPRAWNIE.
    Zejście ją zamyka — koszt zmierzony PRZED wdrożeniem na populacji P-D wyniósł 0 z 25."""
    con = _con()
    assert resolver.path_proposal(
        con, rf"{R}\LIGHTS\NGC4631_PGC42637\RC8_2600MC\L\NGC4631_0001.fit") is None


def test_PIN_PRZEWROCONY_S1_nazwa_wlasna_dostaje_DWOCH_swiadkow():
    """PIN_PRZEWROCONY(S1): `LMC` nie należy do żadnej gramatyki katalogowej, więc do S1 milczał
    KAŻDY świadek. Dziś folder i stem zgadzają się co do kanonu — czego archiwum nie miało ani razu."""
    con = _con()
    assert resolver.path_proposal(
        con, rf"{R}\LIGHTS\LMC\A7R3_105\OSC\LMC_20230323.ARW") == "LMC"


def test_PIN_PRZEWROCONY_D_OW_3_Orion_dostaje_kanon():
    """PIN_PRZEWROCONY(D-OW-3, 2026-08-03): rozmowa się odbyła, wariant A wszedł do słownika.
    Poprzednik tego pinu asertował ODMOWĘ właśnie po to, żeby dopisanie `Orion` bez tej rozmowy
    przewróciło baterię. Kanon jest JEDEN na całą populację — folder obiektywu leży PONIŻEJ pozycji
    obiektu, więc świadek ścieżki i tak go nie widzi; kadr niesie oś sprzętu, nie oś obiektu."""
    con = _con()
    assert resolver.path_proposal(con, rf"{R}\LIGHTS\Orion\A7S1_070\OSC\Orion_0001.ARW") == "Orion"
    assert resolver.path_proposal(con, rf"{R}\LIGHTS\Orion\A7S1_050\OSC\Orion_0002.ARW") == "Orion"


def test_PIN_nazwa_spoza_KAZDEGO_szczebla_dalej_milczy():
    """Zastępca poprzedniego pinu: rolę „nazwa, której nie zna nikt" przejmuje folder ad-hoc.
    Bez tego wiersza dopisanie `Orion` skasowałoby JEDYNY dowód, że drabina umie powiedzieć NIE —
    a pin, który nie może się zaczerwienić, nie jest pinem."""
    con = _con()
    assert resolver.path_proposal(
        con, rf"{R}\LIGHTS\ProbaObiektywu\A7S1_070\OSC\x.ARW") is None
