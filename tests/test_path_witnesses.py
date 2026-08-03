"""Test CHARAKTERYZACYJNY trzech funkcji ścieżki (`_witness_folder`/`_witness_filename`/
`_path_proposal`, dziś w `horreum.gui.app`) — segment S0 briefu obiektów własnych.

CO TO ZA TEST. Nie opisuje zachowania POŻĄDANEGO, tylko **dzisiejsze**. Te trzy funkcje są jedyną
regułą ścieżki, jaką repo ma, i do tej pory nie miały ani jednego testu — a segment S2 tej samej
paczki ma je zejść do wspólnej drabiny (`resolve_name`). Bez pinów przed zmianą nie da się
odróżnić „reguła zeszła zgodnie z planem" od „reguła po cichu przestała działać dla klas, o których
nikt nie pomyślał". Charakteryzacja jest tu bramką ryzyka dla P-D (dialog „Napraw nagłówek…").

DWA PINY MAJĄ SIĘ PRZEWRÓCIĆ W S2 — są oznaczone `PIN_DO_PRZEWROCENIA` i tylko one:

* `C8_2600MC → 'C8'` — folder SPRZĘTU czytany jako Caldwell 8. To defekt, który S2 zamyka zakazem
  cięcia po `_` na pozycji obiektu (D-OW-2 pkt 5a). Przewrócenie tego pinu jest CELEM.
* `NGC4631_PGC42637 → 'NGC4631'` — ta sama gałąź cięcia, ale tutaj działa POPRAWNIE (autorem
  stringa jest akwizycja). Przewróci się w gałęzi ujednolicenia i wtedy dialog straci propozycję
  dla tego firsthandu — dlatego przed GO na S2 mierzymy koszt na populacji P-D (§4 wiersz 17).

Każdy inny czerwony pin z tego pliku znaczy regresję, nie postęp.

`importorskip` na poziomie MODUŁU: funkcje są CZYSTE (`re` + `os.path` + `catalog_canon`, zero Qt),
ale mieszkają w module, który bez PySide6 się nie zaimportuje. Po S2 plik przenosi się na Qt-wolny
`resolve/paths.py` i ten import znika."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from horreum.gui.app import _path_proposal, _witness_filename, _witness_folder

R = "R:\\ASTRO_"


@pytest.mark.parametrize("path, oczekiwany", [
    # Kotwica: segment PO `LIGHTS`, bez względu na głębokość i wielkość liter.
    (rf"{R}\LIGHTS\NGC1976\RC8\L\x.fit", "NGC1976"),
    (rf"{R}\lights\NGC7635\RC8\Ha\x.fit", "NGC7635"),
    (rf"{R}\LIGHTS\Sh2-229\RC8\Ha\x.fit", "Sh2-229"),
    # Gołe oznaczenie Caldwella na pozycji obiektu ZOSTAJE przyjęte — na tej pozycji folder `C8`
    # naprawdę oznacza katalog, a nie sprzęt. S2 tego nie zmienia (gwarancję daje POZYCJA).
    (rf"{R}\LIGHTS\C8\OSC\x.fit", "C8"),
    (rf"{R}\LIGHTS\C11\OSC\x.fit", "C11"),
    # PIN_DO_PRZEWROCENIA (S2, cel): folder SPRZĘTU cięty po `_` daje oznaczenie katalogu.
    (rf"{R}\LIGHTS\C8_2600MC\OSC\x.fit", "C8"),
    # PIN_DO_PRZEWROCENIA (S2, koszt): tu cięcie działa POPRAWNIE — to firsthand, dla którego
    # gałąź powstała.
    (rf"{R}\LIGHTS\NGC4631_PGC42637\RC8_2600MC\L\x.fit", "NGC4631"),
    # Nazwy spoza gramatyki katalogów — `None` jest tu ODPOWIEDZIĄ POPRAWNĄ, nie brakiem.
    # To dokładnie populacja, dla której powstaje słownik nazw własnych (S1).
    (rf"{R}\LIGHTS\LMC\A7R3_105\OSC\x.ARW", None),
    (rf"{R}\LIGHTS\Orion\A7S1_070\OSC\x.ARW", None),
    # Bez kotwicy `LIGHTS` funkcja milczy — także dla drzew, które mają obiekt na innej pozycji
    # (`_SOLAR\Moon`). Regułę kategorii wnosi dopiero S2.
    (rf"{R}\_SOLAR\Moon\A7R3\x.ARW", None),
    (rf"{R}\CALIBRATION\dark\x.fit", None),
    ("", None),
])
def test_charakteryzacja_swiadek_folderu(path, oczekiwany):
    assert _witness_folder(path) == oczekiwany


@pytest.mark.parametrize("path, oczekiwany", [
    # Człon parsujący się katalogowo, NIE prefiks — po rename v2 oznaczenie ląduje w środku nazwy.
    (rf"{R}\LIGHTS\NGC7635\RC8\Ha\NGC7635_0001.fit", "NGC7635"),
    (rf"{R}\LIGHTS\NGC7635\RC8\Ha\M42_Ha_0001.fit", "M42"),
    # Nazwy plików z lustrzanki milczą strukturalnie — i to jest powód, dla którego reguła S2 stoi
    # na JEDNYM świadku (zmierzone: dwaj zgodni świadkowie łapią 31 z 763 klatek RAW).
    (rf"{R}\LIGHTS\LMC\A7R3_105\OSC\_7R38821.ARW", None),
    (rf"{R}\LIGHTS\Orion\A7S1_070\OSC\_dsc9412.ARW", None),
    # Nazwa własna w stemie też milczy — bo świadek pyta gramatyki katalogów, nie drabiny nazw.
    # Po S1 (słownik) i ujednoliceniu z S2 ta odpowiedź się zmieni; dziś jest `None`.
    (rf"{R}\LIGHTS\LMC\A7R3_105\OSC\LMC_20230323.ARW", None),
    ("", None),
])
def test_charakteryzacja_swiadek_nazwy_pliku(path, oczekiwany):
    assert _witness_filename(path) == oczekiwany


@pytest.mark.parametrize("path, oczekiwany", [
    # Propozycja = KONIUNKCJA dwóch zgodnych świadków.
    (rf"{R}\LIGHTS\NGC7635\RC8\Ha\NGC7635_0001.fit", "NGC7635"),
    # Propozycja NIE jest normalizowana przez `xref`: zgodne `M42` zostaje `M42`, nie `NGC1976`.
    # Fakt wart pinu, bo drabina nazwy (S2) normalizuje — i to jest jedna z różnic, które test
    # parytetu (§4 wiersz 16) ma wypisać JAWNIE, zamiast wykryć jako niespodziankę.
    (rf"{R}\LIGHTS\M42\RC8\Ha\M42_0001.fit", "M42"),
    # Rozjazd świadków zostawia pole puste — ścieżka jest DOWODEM, nie prawdą.
    (rf"{R}\LIGHTS\NGC7635\RC8\Ha\M42_Ha_0001.fit", None),
    # Milczenie drugiego świadka wystarcza, żeby propozycji nie było — stąd 31 z 763 dla RAW-ów.
    (rf"{R}\LIGHTS\NGC1976\RC8\L\x.fit", None),
    (rf"{R}\LIGHTS\LMC\A7R3_105\OSC\LMC_20230323.ARW", None),
])
def test_charakteryzacja_propozycja_ze_sciezki(path, oczekiwany):
    assert _path_proposal(path) == oczekiwany
