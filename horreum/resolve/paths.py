r"""Oś OBIEKT — świadek ze ŚCIEŻKI: czyste funkcje pozycji w drzewie archiwum (S2, D-OW-2).

Zero DB, zero Qt, zero dostępu do plików — wzorzec `resolve/recipe.py`. Ten moduł odpowiada na
JEDNO pytanie: **który segment ścieżki stoi na pozycji obiektu**. Czy ten segment cokolwiek NAZYWA,
rozstrzyga drabina nazwy (`resolver.resolve_name`) — tu nie ma ani gramatyki katalogów, ani
słownika, ani aliasu.

DLACZEGO ŚCIEŻKA, skoro kanon jest header-primary: RAW-owy light nie ma jak zeznać o obiekcie
(`resolver.NO_OBJECT_CARD_FILETYPES` — EXIF nie zna `OBJECT` ani RA/DEC), a mimo to leży w drzewie,
które nazwę niesie. Wyjątek jest DOWODOWY (nagłówek milczy strukturalnie), WĄSKI (format bez karty,
bez zeznania, bez obiektu) i SŁABSZY od nagłówka — zmierzone na 13 516 lightach z obiektem: ścieżka
zgadza się z nagłówkiem 12 946 razy, milczy 250, a ROZJEŻDŻA się 320 (w tym 12 semantycznie).
Dlatego szczebel stoi na końcu drabiny i **PROPONUJE, nie zapisuje** (D-OW-2/B).

ŚWIADKIEM JEST FOLDER, NIGDY NAZWA PLIKU (słowo Zdzinia: *„nazwa z folderu ma być wprowadzona do
tych plików, nie nazwa każdego pliku osobno"*). Nazwy plików z lustrzanki (`_7R38821.ARW`,
`_dsc9412.ARW`) milczą STRUKTURALNIE — reguła dwóch zgodnych świadków łapie 31 klatek z 763,
jednoświadkowa 707. Drugi świadek (`filename_tokens`) zostaje wyłącznie dla dialogu „Napraw
nagłówek…", który MUTUJE PLIK i ma prawo żądać potwierdzenia.

DWIE POŁÓWKI JEDNEJ REGUŁY POZYCYJNEJ: **wartości** markera są w `resolve/frames` (`_KIND_DIRS`,
konsumowane przez `kind_dir_segments()` — ta sama mapa, z której bierze się `kind` RAW-a), a
**reguła** (pozycja + kategorie) jest tutaj. Rozdzielenie ich na kod i asset dałoby dwóch
właścicieli jednego faktu, a dwuelementowa taksonomia drzewa skanu nie ma uzasadnienia regexami
zmiennymi w czasie, jakie ma `recipe.py`.
"""
from ._text import path_segments
from .frames import kind_dir_segments

#: Segmenty-KATEGORIE: stoją na pozycji obiektu, ale obiektem nie są — uprawniają zejście o JEDEN
#: poziom niżej. Lista JAWNA, nie limit głębokości ani konwencja `_*`: `_WBPP`/`_Review` to drzewa
#: robocze (skan ich nie widzi), a `_COMETS`/`_SOLAR` to realne lighty. Odtwarza dokładnie
#: 674 (segment po markerze) + 33 (27 Moon + 2 Jupiter + 4 21P) = 707 klatek żywego archiwum.
CATEGORY_DIRS = frozenset({"_SOLAR", "_COMETS"})

# Separator segmentów ma JEDNEGO właściciela (`_text.path_segments`, R-S0-12): dawny
# `_witness_filename` ciął przez `os.path.basename`, więc poza Windows nie rozpoznałby `\`, jego
# bliźniak przez własny regex, a oś RODZAJU przez `Path().parts` — trzy odpowiedzi na jedno pytanie
# „gdzie kończy się segment". „Czyste funkcje ścieżki" wnosiłyby wtedy ukrytą zależność od systemu.


def _dirs(path):
    """Segmenty KATALOGOWE ścieżki (bez nazwy pliku), puste odsiane."""
    return list(path_segments(path))[:-1]


def _object_index(path):
    """Indeks segmentu na pozycji obiektu w `_dirs(path)` albo None (helper obu funkcji niżej).

    Kotwicą jest segment, który nadaje klatce RODZAJ (`kind_dir_segments()` zna `light` ORAZ
    `lights`) — nie własny literał `LIGHTS`. Dziś koszt tego rozróżnienia to 0 (763/763 ścieżek
    populacji ma `lights`), jutro byłaby to cicha luka: drzewo z `Light` w liczbie pojedynczej
    przestałoby być nazywane bez jednego czerwonego testu.

    Rodzaj musi być LIGHTEM: `CALIBRATION\\dark\\…` nie ma obiektu z definicji (kind-awareness osi),
    więc segment po markerze darka nie jest kandydatem na nic.

    Pierwszy pasujący marker od korzenia wygrywa — ta sama reguła, co w `kind_from_path`."""
    dirs = _dirs(path)
    markers = kind_dir_segments()
    for i, seg in enumerate(dirs):
        if markers.get(seg.strip().lower()) != "light" or i + 1 >= len(dirs):
            continue
        if dirs[i + 1].strip().upper() in CATEGORY_DIRS:
            return i + 2 if i + 2 < len(dirs) else None
        return i + 1
    return None


def object_from_path(path):
    """Segment na pozycji obiektu — SUROWY tekst folderu albo None. Czysta funkcja.

    Zwraca ŚWIADKA, nie kanon: `LIGHTS\\NGC 7635\\…` da `'NGC 7635'`, a nie `'NGC7635'`. Kanon
    powstaje WYŁĄCZNIE z drabiny nazwy (`resolver.resolve_name`, `from_path=True`) — nigdy z
    surowego segmentu, inaczej każdy folder o dowolnej nazwie zakładałby obiekt.

    None znaczy „ścieżka nie stoi na pozycji obiektu": brak markera rodzaju, marker jako ostatni
    katalog, kategoria bez zejścia. Milczenie jest tu odpowiedzią POPRAWNĄ, nie brakiem."""
    i = _object_index(path)
    return None if i is None else _dirs(path)[i]


def object_folder(path):
    """Ścieżka do folderu OBIEKTU (prefiks kończący się na segmencie z `object_from_path`) albo
    None — czym powierzchnia potwierdzania pokazuje ŹRÓDŁO propozycji.

    Pełna ścieżka pliku byłaby złym dowodem: pozycje są grupowane PO NAZWIE (≈35 na 707 klatek),
    więc user ogląda folder wspólny dla grupy, nie 36 razy ten sam katalog z inną nazwą pliku."""
    i = _object_index(path)
    if i is None:
        return None
    return "\\".join(_dirs(path)[:i + 1])


def filename_tokens(path):
    """Człony STEMU nazwy pliku — jednostka iteracji DRUGIEGO świadka (dialog „Napraw nagłówek…").

    Rozdzielnikiem jest `_` i to jest RDZEŃ tego świadka, nie niedopatrzenie: po rename v2
    oznaczenie ląduje w ŚRODKU nazwy (`naming.DEFAULT_TEMPLATE` stawia na pierwszej pozycji
    `datetime`), więc prefiks jest martwy. Zakaz cięcia po `_` z D-OW-2 pkt 5a dotyczy segmentu
    KATALOGOWEGO na pozycji obiektu, gdzie `C8_2600MC` udawałby Caldwella — tutaj cięcie jest
    jedyną drogą do oznaczenia.

    Basename liczony TYM SAMYM rozdzielnikiem co reszta modułu (R-S0-12), nie `os.path.basename`."""
    segs = path_segments(path)
    if not segs:
        return ()
    stem = segs[-1].rsplit(".", 1)[0]
    return tuple(t for t in stem.split("_") if t)
