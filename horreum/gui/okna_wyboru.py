"""Katalog startowy okien wyboru pliku i folderu (AR-370, AR-378) - JEDNA reguła dla każdego `QFileDialog`
w `horreum/gui` (bramka AST `tests/test_okna_wyboru.py`: start każdego okna przychodzi z `katalog_startowy`).
Moduł bez Qt.

DLACZEGO REGUŁA, A NIE NAPIS Z PAMIĘCI. Qt 6.9.2 bierze start, gdy istnieje, jego rodzica, gdy istnieje rodzic
(schodzi tylko o JEDEN poziom), a inaczej katalog ostatnio odwiedzony przez DOWOLNE okno wyboru tego procesu
(`lastVisitedDir`), dopiero na końcu katalog roboczy procesu - w wydaniu onefile katalog uruchomienia
(`qfiledialog.cpp` v6.9.2 `_qt_get_directory`, `QFileDialogArgs`). Zmierzone natywnie: pusty start albo start bez
rodzica po wcześniejszym oknie na X otwiera X, więc „Nowa baza…” po wyborze źródła Dostawy startowała w drzewie
archiwum, a pierwsze okno procesu - przy pliku programu. Kandydat, który istnieje albo ma istniejącego rodzica,
odcina obie drogi; bez takiego kandydata - folder domowy.

SPRAWDZENIE POZA WĄTKIEM OKNA, Z BUDŻETEM. `isdir` na zerwanym udziale stoi do timeoutu klienta SMB - zmierzone
42 129-42 174 ms (UNC nieosiągalnego IP; tyle samo `QFileInfo.exists`, którym Qt sprawdza start), a pamięć negatywna
klienta wygasa po kilku minutach. Sloty Dostawy nie dotykają dysku w wątku okna (AR-31 (3)), więc sondy idą
w wątkach Pythona (demon), a wołający czeka na nie najwyżej `_BUDZET_S` - pod progiem 300 ms, którym repo mierzy
przestój okna. Kandydat bez odpowiedzi w budżecie się nie liczy; jego wątek kończy sam po timeoutcie, a spóźniony
wynik nie ma już czytelnika.

KOLEJNOŚĆ: sondy wszystkich kandydatów ruszają RAZEM; wygrywa pierwszy w kolejności wołającego, który odpowie
„jest” - wołający czeka na kandydatów po kolei, póki budżet trwa; po budżecie - pierwszy w kolejności spośród tych,
które już odpowiedziały „jest”; nikt - folder domowy, bez sondy. Bez priorytetu „lokalne przed sieciowymi”: pamięć
człowieka (ostatnia baza, ostatnie źródło Dostawy na żywym udziale) wygrywa z Dokumentami i folderem domowym.

JEDEN LOT NA ŚCIEŻKĘ, LIMIT LOTÓW. Sonda to `os.path.isdir` jednej ścieżki; rejestr `_LOTY` trzyma sondy w biegu po
kluczu `normcase(normpath)`, więc kolejne okno przy wiszącym udziale (i drugi kandydat z tym samym rodzicem) podpina
się pod żywą sondę zamiast zakładać wątek. Nowych lotów najwyżej `_MAKS_LOTOW` naraz - ścieżka ponad limit zostaje
bez odpowiedzi."""
import os
import threading
import time

# Budżet czekania wołającego na sondy kandydatów (s) - wątek okna stoi najwyżej tyle przed otwarciem okna systemowego.
_BUDZET_S = 0.25
# Sond w biegu naraz: kandydat i jego rodzic to dwie ścieżki, okno ma do trzech kandydatów - limit mieści jedno pełne
# okno przy żywym udziale także wtedy, gdy wcześniejsze okna zostawiły wiszące sondy martwego.
_MAKS_LOTOW = 8
_LOTY = {}
_ZAMEK = threading.Lock()


class Scisly(str):
    """Kandydat ŚCISŁY: liczy się wyłącznie, gdy SAM jest katalogiem - bez reguły rodzica. Folder `OBJECTS` okna
    żniw (`HarvestDialog._pick_start`): jego rodzic, folder roboczy, istnieje, zanim pierwsze wydanie go założy, a start
    w pustym folderze roboczym przegrywałby z ostatnim wyjściem."""


class _Lot:
    """Jedna sonda `isdir` w biegu albo skończona: `gotowe` - odpowiedź jest, `jest` - wynik (pisany PRZED `gotowe`)."""

    def __init__(self):
        self.gotowe = threading.Event()
        self.jest = False


def _sonda(klucz, sciezka, lot):
    """Wątek sondy: `isdir` (nie rzuca - błąd systemu to „nie ma”), potem `gotowe`, a dopiero PO publikacji wyniku
    wpis rejestru zdjęty - KAŻDĄ drogą. Odwrotna kolejność otwierała okno, w którym lotu nie było już w rejestrze,
    a wyniku jeszcze nie było: drugi wołający zakładał wtedy drugą sondę tej samej ścieżki obok żywego wątku (limit
    lotów liczy wpisy, nie wątki). Lot skończony i jeszcze wpisany oddaje wynik sprzed chwili."""
    try:
        lot.jest = os.path.isdir(sciezka)
    finally:
        lot.gotowe.set()
        with _ZAMEK:
            if _LOTY.get(klucz) is lot:
                del _LOTY[klucz]


def _lot(sciezka):
    """Lot sondy ścieżki: żywy z rejestru albo nowy; `None` - limit lotów pełny."""
    klucz = os.path.normcase(os.path.normpath(sciezka))
    with _ZAMEK:
        lot = _LOTY.get(klucz)
        if lot is not None:
            return lot
        if len(_LOTY) >= _MAKS_LOTOW:
            return None
        lot = _LOTY[klucz] = _Lot()
    try:
        threading.Thread(target=_sonda, args=(klucz, sciezka, lot), name="horreum-start-okna", daemon=True).start()
    except BaseException:
        with _ZAMEK:
            _LOTY.pop(klucz, None)
        raise
    return lot


def _loty_kandydata(kandydat):
    """Sondy, które rozstrzygają kandydata: on sam, a przy zwykłym (nie `Scisly`) także jego rodzic - o ile jest
    inny."""
    if isinstance(kandydat, Scisly):
        return (_lot(kandydat),)
    sciezka = os.path.normpath(kandydat)
    rodzic = os.path.dirname(sciezka)
    if not rodzic or os.path.normcase(rodzic) == os.path.normcase(sciezka):
        return (_lot(kandydat),)
    return (_lot(kandydat), _lot(rodzic))


def _stan(loty):
    """`True` - któraś sonda kandydata odpowiedziała „jest”, `False` - wszystkie „nie ma”, `None` - nie wiadomo (sonda
    w biegu albo bez lotu ponad limit)."""
    if any(lot is not None and lot.gotowe.is_set() and lot.jest for lot in loty):
        return True
    if all(lot is not None and lot.gotowe.is_set() for lot in loty):
        return False
    return None


def katalog_startowy(*kandydaci, budzet_s=_BUDZET_S):
    """Katalog startowy okna wyboru: pierwszy kandydat wołającego, który istnieje albo ma istniejącego rodzica
    (`Scisly` - wyłącznie istniejący), rozstrzygnięty regułą kolejności i budżetu z docstringu modułu; bez takiego -
    folder domowy. Zwraca KANDYDATA, nie jego rodzica: Qt zejdzie o poziom sam, a nazwa nieistniejącego folderu zostaje
    podpowiedzią. Kandydat pusty, `None` albo względny (Qt rozwiązałby go wobec katalogu roboczego procesu) się nie
    liczy."""
    sondy = [(k, _loty_kandydata(k)) for k in kandydaci if isinstance(k, str) and k and os.path.isabs(k)]
    koniec = time.monotonic() + budzet_s
    for k, loty in sondy:
        stan = _stan(loty)
        while stan is None and time.monotonic() < koniec:
            w_biegu = [lot for lot in loty if lot is not None and not lot.gotowe.is_set()]
            if not w_biegu:                # lot ponad limit - odpowiedzi nie będzie, kandydat bez głosu
                break
            # Krótki takt zamiast czekania na jedną sondę: kandydata rozstrzyga też rodzic, który odpowie pierwszy.
            w_biegu[0].gotowe.wait(min(0.005, max(0.0, koniec - time.monotonic())))
            stan = _stan(loty)
        if stan:
            return str(k)
        if stan is None and time.monotonic() >= koniec:
            break                          # budżet minął - dalej czekać nie wolno
    for k, loty in sondy:
        if _stan(loty):
            return str(k)
    return os.path.expanduser("~")
