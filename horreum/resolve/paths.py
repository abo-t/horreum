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

DRUGIE DRZEWO, TA SAMA FIGURA (FC-4/D-V-9b, E3-1): gotowe obrazy leżą w układzie
`STACKS\\<OBIEKT>\\<TELESKOP_KAMERA>\\<FILTR>\\plik` i markera rodzaju NIE MAJĄ - kotwicą jest tam
segment `STACKS`, a obiekt stoi BEZPOŚREDNIO po nim. Reguła jest KIND-AWARE: drzewo akwizycji
odpowiada lightowi, drzewo stosów `master_light`owi, kalibracja nie dostaje żadnego. Pytanie
„który segment ścieżki stosu nazywa obiekt" zadają dwie warstwy (kolumna „Obiekt" w GUI i szczebel
ścieżki resolvera), więc odpowiedź mieszka tu, jedna. Zmierzone `?mode=ro` na 193 stosach: segment
po `STACKS` zgadza się z kanonem osi 187 razy, milczy 6 (`Veil` - kanon regionu, drabina nazwy go
nie zna), ROZJEŻDŻA się 0. Rodzic pliku (dawna reguła GUI) trafiał w FILTR 182 razy na 193.
Kotwicą jest biblioteka stosów ARCHIWUM, nie dowolny folder `STACKS` (E5-3): wołający podaje
korzeń archiwum (`library_root`, ustalony z obecnych kopii - `library_root_candidates`), a bez
korzenia świadek drzewa stosów milczy.
"""
import re

from ._text import path_segments
from .frames import kind_dir_segments

#: Segmenty-KATEGORIE: stoją na pozycji obiektu, ale obiektem nie są — uprawniają zejście o JEDEN
#: poziom niżej. Lista JAWNA, nie limit głębokości ani konwencja `_*`: `_WBPP`/`_Review` to drzewa
#: robocze (skan ich nie widzi), a `_COMETS`/`_SOLAR` to realne lighty. Odtwarza dokładnie
#: 674 (segment po markerze) + 33 (27 Moon + 2 Jupiter + 4 21P) = 707 klatek żywego archiwum.
CATEGORY_DIRS = frozenset({"_SOLAR", "_COMETS"})

#: Kotwica drzewa GOTOWYCH OBRAZÓW (porównanie bez wielkości liter, jak marker rodzaju). Kategorie
#: `CATEGORY_DIRS` pod nią NIE działają: w zmierzonym drzewie stosów ich nie ma, a zejście o poziom
#: niżej bez pomiaru byłoby zgadywaniem cudzej konwencji.
STACKS_DIR = "stacks"

#: Rodzaj, któremu odpowiada drzewo stosów - jedyny (droga „Stosy" wpuszcza wyłącznie ten rodzaj).
STACK_KIND = "master_light"

# Separator segmentów ma JEDNEGO właściciela (`_text.path_segments`, R-S0-12): dawny
# `_witness_filename` ciął przez `os.path.basename`, więc poza Windows nie rozpoznałby `\`, jego
# bliźniak przez własny regex, a oś RODZAJU przez `Path().parts` — trzy odpowiedzi na jedno pytanie
# „gdzie kończy się segment". „Czyste funkcje ścieżki" wnosiłyby wtedy ukrytą zależność od systemu.


def _dirs(path):
    """Segmenty KATALOGOWE ścieżki (bez nazwy pliku), puste odsiane."""
    return list(path_segments(path))[:-1]


def _stacks_anchor(dirs, library_root):
    """Indeks segmentu-KOTWICY drzewa stosów w `dirs` albo None.

    Z KORZENIEM ARCHIWUM (`library_root`, reguła `harvest.library_root` - część ścieżki PRZED
    bibliotekami `CALIBRATION`/`STACKS`): kotwicą jest WYŁĄCZNIE segment `STACKS` stojący
    bezpośrednio pod tym korzeniem, ta sama reguła co sito skanu (`scan._stacks_prefix`) i strażnik
    kopii żniw (`projection._assert_archive_library`). Folder `…\\work\\STACKS\\M31` w drzewie roboczym
    nie jest biblioteką stosów, nawet gdy nad nim nie stoi żaden marker rodzaju (E5-3).

    BEZ KORZENIA - MILCZENIE. Folder `STACKS` sam w sobie nie odróżnia biblioteki archiwum od
    folderu roboczego (`…\\work\\STACKS\\M31`), więc świadek bez korzenia nie ma podstawy; korzeń
    ustala `library_root_candidates` (+ `resolver.library_root_from_db`) z obecnych kopii."""
    if not library_root:
        return None
    korzen = [s.strip().lower() for s in path_segments(library_root)]
    n = len(korzen)
    if (len(dirs) > n and [s.strip().lower() for s in dirs[:n]] == korzen
            and dirs[n].strip().lower() == STACKS_DIR):
        return n
    return None


#: Segmenty bibliotek ARCHIWUM stojące bezpośrednio pod jego korzeniem: stosy, lighty (marker rodzaju
#: lightów, `kind_dir_segments()`) i kalibracja (`projection.CALIBRATION_SEGMENT`, tu jako tekst -
#: liść nie importuje klingi plików).
_CALIBRATION_DIR = "calibration"


def library_root_candidates(paths):
    """`{prefiks_bez_wielkości_liter: (forma, ile kopii pod STACKS, czy jest rodzeństwo)}` - kandydaci
    na korzeń archiwum z listy ścieżek. Czysta funkcja.

    Prefiks = część ścieżki PRZED PIERWSZYM od korzenia segmentem biblioteki (`STACKS`, marker lightów,
    `CALIBRATION`). Pierwszy, bo `…\\LIGHTS\\NGC7000\\work\\STACKS\\…` należy do biblioteki lightów,
    a nie zakłada drugiego drzewa stosów. Korzeń jest WIARYGODNY, gdy pod tym samym prefiksem stoją
    `STACKS` i co najmniej jedna inna biblioteka (rodzeństwo) - sam folder `STACKS` niczego nie
    dowodzi. Decyduje wołający (`resolver.library_root_from_db`): najliczniejszy wiarygodny."""
    markers = {k for k, v in kind_dir_segments().items() if v == "light"}
    out = {}
    for p in paths:
        segs = path_segments(p)
        for i, seg in enumerate(segs[:-1]):
            s = seg.strip().lower()
            if s != STACKS_DIR and s != _CALIBRATION_DIR and s not in markers:
                continue
            if i == 0:
                break
            klucz = "\\".join(x.strip().lower() for x in segs[:i])
            forma, n, rodzenstwo = out.get(klucz, ("\\".join(segs[:i]), 0, False))
            out[klucz] = (forma, n + (s == STACKS_DIR), rodzenstwo or s != STACKS_DIR)
            break
    return out


def _object_index(path, kind="light", library_root=None):
    """Indeks segmentu na pozycji obiektu w `_dirs(path)` albo None (helper obu funkcji niżej).

    Kotwicą jest segment, który nadaje klatce RODZAJ (`kind_dir_segments()` zna `light` ORAZ
    `lights`) — nie własny literał `LIGHTS`. Dziś koszt tego rozróżnienia to 0 (763/763 ścieżek
    populacji ma `lights`), jutro byłaby to cicha luka: drzewo z `Light` w liczbie pojedynczej
    przestałoby być nazywane bez jednego czerwonego testu.

    Rodzaj musi być LIGHTEM: `CALIBRATION\\dark\\…` nie ma obiektu z definicji (kind-awareness osi),
    więc segment po markerze darka nie jest kandydatem na nic.

    `kind=STACK_KIND` przełącza kotwicę na `STACKS_DIR` (drzewo gotowych obrazów, docstring
    modułu; którą kotwicę, rozstrzyga `_stacks_anchor` z `library_root`). Każdy inny rodzaj niż
    light i `master_light` milczy: kalibracja obiektu nie ma, więc pytanie o jej pozycję obiektu
    nie ma odpowiedzi innej niż None.

    Pierwszy pasujący marker od korzenia wygrywa - ta sama reguła, co w `kind_from_path`, w drzewie
    lightów. Segment po kotwicy musi być KATALOGIEM: `STACKS\\plik.xisf` milczy, bo nazwa pliku
    świadkiem nie jest (kanon modułu)."""
    dirs = _dirs(path)
    if kind == STACK_KIND:
        i = _stacks_anchor(dirs, library_root)
        return i + 1 if i is not None and i + 1 < len(dirs) else None
    if kind != "light":
        return None
    markers = kind_dir_segments()
    for i, seg in enumerate(dirs):
        if markers.get(seg.strip().lower()) != "light" or i + 1 >= len(dirs):
            continue
        if dirs[i + 1].strip().upper() in CATEGORY_DIRS:
            return i + 2 if i + 2 < len(dirs) else None
        return i + 1
    return None


def object_from_path(path, kind="light", library_root=None):
    """Segment na pozycji obiektu — SUROWY tekst folderu albo None. Czysta funkcja.

    Zwraca ŚWIADKA, nie kanon: `LIGHTS\\NGC 7635\\…` da `'NGC 7635'`, a nie `'NGC7635'`. Kanon
    powstaje WYŁĄCZNIE z drabiny nazwy (`resolver.resolve_name`, `from_path=True`) — nigdy z
    surowego segmentu, inaczej każdy folder o dowolnej nazwie zakładałby obiekt.

    `kind` wybiera DRZEWO (light → marker rodzaju, `master_light` → `STACKS`); domyślny light
    zachowuje kontrakt sprzed drzewa stosów dla wszystkich dotychczasowych wołających.
    `library_root` (korzeń archiwum) zawęża kotwicę drzewa stosów do `STACKS` bezpośrednio pod nim
    (`_stacks_anchor`); w drzewie lightów nie gra.

    None znaczy „ścieżka nie stoi na pozycji obiektu": brak kotwicy, kotwica jako ostatni
    katalog, kategoria bez zejścia, rodzaj bez obiektu. Milczenie jest tu odpowiedzią POPRAWNĄ,
    nie brakiem."""
    i = _object_index(path, kind, library_root)
    return None if i is None else _dirs(path)[i]


def object_folder(path, kind="light", library_root=None):
    """Ścieżka do folderu OBIEKTU (prefiks kończący się na segmencie z `object_from_path`) albo
    None - czym powierzchnia potwierdzania pokazuje ŹRÓDŁO propozycji. `kind` i `library_root`
    jak wyżej.

    Pełna ścieżka pliku byłaby złym dowodem: pozycje są grupowane PO NAZWIE (≈35 na 707 klatek),
    więc user ogląda folder wspólny dla grupy, nie 36 razy ten sam katalog z inną nazwą pliku."""
    i = _object_index(path, kind, library_root)
    if i is None:
        return None
    return "\\".join(_dirs(path)[:i + 1])


# Znaki, których system plików Windows nie przyjmie w nazwie katalogu (plus znaki sterujące) -
# kanon obiektu z takim znakiem nie da się postawić jako folder, więc planer odmawia zamiast ciąć.
_ZAKAZANE_W_SEGMENCIE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def path_after_object_change(path, canon, kind="light", library_root=None):
    """Ścieżka pliku PO zmianie obiektu - segment na pozycji obiektu (`_object_index`) zastąpiony
    kanonem `canon` (`object.canon`), reszta ścieżki znak w znak. Czysta funkcja, zero dysku: planer
    celu gestu „zmień obiekt” (karta `OBJECT` + przeniesienie pliku do folderu obiektu, AR-17
    krok 3); sam gest i mutacja to osobna robota, tu jest tylko odpowiedź „dokąd”.

    TA SAMA REGUŁA POZYCJI co świadek ścieżki (SPOT): drzewo lightów (marker rodzaju, także RAW
    z lustrzanki), zejście o poziom pod kategorią (`CATEGORY_DIRS`: `LIGHTS\\_COMETS\\12P\\…` zmienia
    `12P`, nie `_COMETS`), drzewo stosów (`kind=STACK_KIND`, segment po kotwicy `STACKS` - z
    `library_root` wyłącznie pod korzeniem archiwum). Nazwa pliku zostaje: składa ją `naming`
    (rename), a mieszanie dwóch reguł w jednej funkcji dałoby planer, który zmienia nazwę bez podglądu
    renamu.

    Separatory i forma reszty ścieżki zostają takie, jak przyszły (`R:\\…`, `/mnt/…`, UNC) - cięcie
    tym samym rozdzielnikiem co `path_segments` (R-S0-12), sklejenie z zachowaniem separatorów.

    None = ścieżka nie stoi na pozycji obiektu (kalibracja, układ WBPP, plik wprost pod kotwicą) -
    pliku nie da się przenieść „do folderu obiektu”, bo takiego folderu w jego drzewie nie ma.
    EXPECT: kanon pusty, z białym znakiem na brzegu, `.`/`..` albo ze znakiem zakazanym w nazwie
    katalogu → `ValueError` (cel, którego system plików nie przyjmie, nie powstaje)."""
    i = _object_index(path, kind, library_root)
    if i is None:
        return None
    if (not isinstance(canon, str) or not canon or canon != canon.strip() or canon in (".", "..")
            or _ZAKAZANE_W_SEGMENCIE.search(canon)):
        raise ValueError(f"kanon obiektu nie może być nazwą katalogu: {canon!r}")
    czesci = re.split(r"([\\/]+)", str(path))           # segmenty na pozycjach parzystych
    k = -1
    for j in range(0, len(czesci), 2):
        if czesci[j]:
            k += 1
            if k == i:
                czesci[j] = canon
                break
    return "".join(czesci)


def filter_folder_from_path(path):
    """Segment na pozycji FOLDERU FILTRA w drzewie flatów - SUROWY tekst albo None. Czysta funkcja.

    Układ zmierzony `?mode=ro` 2026-10-07 na 2 336 obecnych lokacjach flatów: zawsze
    `<marker flat>\\<TELESKOP_KAMERA>\\<FILTR>\\plik` (dwa katalogi po markerze, bez wyjątku);
    segment na drugiej pozycji zgadza się z `filter_canon` klatki 1 527 razy, a reszta to kamery
    kolorowe (`OSC`, filtr pusty z definicji) i filtry, których nagłówek nie zna. Kotwicą jest ten
    sam marker, który nadaje rodzaj (`kind_dir_segments()`), pierwszy od korzenia - jak w
    `_object_index`. Marker innego rodzaju niż flat milczy: dark ma jeden katalog po markerze,
    a w drzewie lightów (`LIGHTS\\<OBIEKT>\\…`) głębokość pod obiektem jest mieszana (12 464 × dwa
    katalogi, 1 873 × jeden), więc pozycja filtra byłaby tam zgadywaniem.

    Czyta go porównanie kopii jednej klatki (`gui.queries.copy_divergence`, AR-1) - świadek NAZWY
    kopii, nie fakt filtra klatki: oś filtra prowadzi nagłówek."""
    dirs = _dirs(path)
    markers = kind_dir_segments()
    for i, seg in enumerate(dirs):
        kind = markers.get(seg.strip().lower())
        if kind is None:
            continue
        if kind != "flat" or i + 2 >= len(dirs):
            return None
        return dirs[i + 2]
    return None


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
