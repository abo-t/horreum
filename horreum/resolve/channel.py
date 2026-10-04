r"""Oś KANAŁU gotowego obrazu - `channel_from_name(nazwa)` → `'R'|'G'|'B'|None` (P4-3).

Czysta funkcja nazwy pliku: zero DB, zero Qt, zero dostępu do plików (wzorzec `resolve/paths.py`).
Zapisuje wynik resolver (`resolver.derive_channels` → klinga `repo.backfill_frame_channel`).

DLACZEGO NAZWA, skoro kanon jest header-primary: kamera kolorowa daje z jednej sesji trzy stosy
kanałów (WBPP integruje każdy osobno), a nagłówek nie mówi, który jest który - `FILTER` niesie filtr
OPTYCZNY (L-Pro, L-eXtreme) albo nic, a pomiary szumu tylko liczbę kanałów obrazu. Jedynym nosicielem
faktu jest nazwa nadana przez WBPP i przeniesiona do archiwum stosów. Kanał to więc POCHODNA
z faktu, który baza już ma (`location.path`) - liczona bez ponownego odczytu pliku.

DWIE KONWENCJE, JEDNA REGUŁA POZYCYJNA (zmierzone `?mode=ro` 2026-10-04 na 321 lokacjach
`master_light`, 78 z kanałem w nazwie, wszystkie kamerą kolorową):
  * WBPP: `masterLight_…_FILTER-NoFilter__B.xisf`, `…_FILTER-LPRO__G_n.xisf`, `…_FILTER-NoFilter_R.xisf`
    (starszy WBPP z jednym podkreślnikiem), `…__B_autocrop.xisf`;
  * archiwum stosów: `NGC1976_2021-11-10_ED120R_294MC_NoFilter_60s_B.xisf`, `…_600s_R_WBPP2.xisf`.
Kanał to JEDNOLITEROWY token `R`/`G`/`B` stojący ZARAZ PO tokenie filtra WBPP (`FILTER-<x>`) albo po
tokenie ekspozycji (`<n>s`). Pozycja jest istotą reguły, nie ozdobą: kamera MONO z filtrem `B` daje
`…_FILTER-B_mono.xisf` i `…_2600MM_B_180s_mono.xisf` - litera stoi tam W MIEJSCU filtra (przed
ekspozycją albo jako wartość `FILTER-`), a po nich idzie `mono`. Goły token `B` gdziekolwiek w nazwie
nadałby kanał każdemu stosowi mono z filtrem niebieskim. `RGB`/`combined_RGB` kanałem nie są
(obraz pełnokolorowy) - token wielo-literowy reguły nie spełnia.
"""
import re

#: Wartości kanału - lustro CHECK-u migracji 0028 (test pinuje równość).
CHANNELS = ("R", "G", "B")

# Kotwica pozycji: token filtra WBPP (`FILTER-<wartość bez podkreślnika>`) albo ekspozycji (`600s`,
# `60.00s`), potem jeden albo dwa podkreślniki, litera kanału i koniec nazwy albo następny token.
# Wielkość liter: WBPP pisze `FILTER-`, ale archiwum nie jest pisane jednym narzędziem - porównanie
# na formie oryginalnej dla litery kanału (`_b` to nie jest konwencja nikogo), bez rozróżnienia dla
# kotwicy.
_CHANNEL_RX = re.compile(r"(?:(?i:filter)-[^_]+|(?<![0-9A-Za-z])\d+(?:\.\d+)?(?i:s))__?([RGB])(?=_|$)")
# Świadek obrazu WIELOKANAŁOWEGO w tej samej nazwie (`…_600s_R_combined_RGB`): litera po ekspozycji
# nie jest wtedy kanałem, tylko początkiem opisu złożenia - kanału nie nadajemy.
_WIELOKANAL_RX = re.compile(r"(?i)(?:^|_)rgb(?=_|$)")


def channel_from_name(name):
    """Kanał z NAZWY pliku (bez katalogu) - `'R'|'G'|'B'` albo `None`, gdy nazwa go nie niesie.

    Rozszerzenie odcinamy przed dopasowaniem, żeby `.xisf` nie udawało następnego tokenu. Kilka
    trafień w jednej nazwie z RÓŻNYMI literami to sprzeczność - `None`, nie zgadywanie."""
    if not name:
        return None
    stem = name.rsplit(".", 1)[0] if "." in name else name
    if _WIELOKANAL_RX.search(stem):                   # `combined_RGB`, `_RGB_`: obraz pełnokolorowy
        return None
    trafienia = {m.group(1) for m in _CHANNEL_RX.finditer(stem)}
    return trafienia.pop() if len(trafienia) == 1 else None


def frame_channel(names):
    """Kanał KLATKI z nazw wszystkich jej kopii - jedna litera albo `None`.

    Klatka bywa pod kilkoma ścieżkami (stary plik WBPP i jego kopia w archiwum stosów, obecna albo
    nie - nazwa jest faktem o obrazie, nie o obecności). Kopie milczące nie głosują; kopie, które
    mówią RÓŻNE kanały, to sprzeczność faktów - `None`, a nie wybór jednej z nich."""
    kanaly = {k for k in (channel_from_name(n) for n in names) if k is not None}
    return kanaly.pop() if len(kanaly) == 1 else None
