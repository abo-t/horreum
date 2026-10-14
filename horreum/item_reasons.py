"""POWODY POZYCJI gestu „Zmień obiekt…”/„Uzgodnij” (AR-141) - zdanie PL rdzenia RAZEM z kodem
i parametrami, także po zapisie w bazie.

Pozycja przebiegu (`pending_object_change`) niosła powód wyłącznie jako polską prozę, a okno otwierane
z Porządków czyta go z bazy - samo i18n okna nie miało z czego złożyć zdania w języku UI. Teraz każdy
powód pozycji to `PowodPozycji`: zdanie PL (`str` - CLI, log, testy i sklejenia biorą je jak tekst,
znak w znak jak dotąd) + `code` + `params`. Okno składa z nich zdanie `objchg.item.<kod>`
(`gui.wb_worker.tekst_powodu`); proza bez kodu (wiersz sprzed 0041, powód warstwy bez kodu) zostaje
zdaniem PL.

DLACZEGO LIŚĆ: powody piszą sterownik zapisu (`writeback`) i klinga (`repo`: wstrzymanie zapisu,
dokończenie, doklejka CAS ręki), a czyta GUI. Repo nie importuje planera (`object_change`), więc
nośnik nie mieszka obok `ZdanieRdzenia` - tu, bez importów projektu i bez SQL. Kodek (`do_bazy` /
`z_bazy`) jest jeden: zapisuje go wyłącznie `repo._set_object_change_reason_tx`, odczytuje
`gui.queries.object_change_run_view`.

ZAGNIEŻDŻENIE: powód niższej warstwy jedzie PARAMETREM (`inner`, w `file_not_back` też `outer`) -
`PowodPozycji` (renam, izolacja, katalogi, klinga - warstwy z kodem) albo zwykły `str` (pisarz karty,
tekst `OSError` w języku systemu): jawna granica, zdanie UI wstawia taki tekst znak w znak. Uwagi
doklejane za powodem (`; `, `dopisz`) to lista `notes` - lista powodów, nie sklejona proza.
"""

import json

# Kody powodów pozycji - każdy ma zdanie `objchg.item.<kod>` w katalogu okna (PL+EN, test AST), PL
# znak w znak jak zdanie rdzenia. Część kodów nazywa FRAGMENT zdania nadrzędnego (`copies`, `lead_*`),
# a część uwagę doklejaną za powodem (`hand_*`).
ITEM_REASON_CODES = frozenset({
    # sterownik zapisu pozycji (`writeback._zmien_pozycje`)
    "rename_open", "no_location", "copy_gone", "path_moved", "no_mtime_anchor",
    "changed_since_preview", "unreachable", "changed_since_scan", "rename_bounced", "target_taken",
    "header_changed", "db_refused", "copies_changed", "drift_resumed", "drift_resumed_undo", "drift",
    "dir_intent_failed", "dir_create_failed", "dir_unconfirmed", "target_dir_missing", "rename_torn",
    "card_refused", "card_partial", "card_prev_failed", "card_prev_refused", "inplace_fallback",
    "confirmed_from_disk", "file_not_back",
    # cofnięcie pozycji (`writeback._cofnij_pozycje`, `undo_object_change`)
    "undo_card", "undo_file", "undo_before_write", "undo_refused_earlier",
    # izolacja lokacji po nieukończonym zapisie w miejscu (`writeback._powod_izolacji`)
    "isolated_recover", "isolated_finish", "inplace_after_gate",
    # przeniesienie pliku (`writeback.rename_file`, `_rename_pod_straza`, `_przenies_wstecz`)
    "src_missing", "dst_exists", "busy", "torn_other", "returned_intent_left", "torn_db_not",
    "returned", "intent_not_saved", "torn_unknown", "intent_dropped", "target_taken_db",
    "not_on_run_path",
    # odmowy klingi ręki (`repo`, Q6)
    "alias_conflict", "retired_via_xref",
    # zapisy klingi w pozycji (`repo`): doklejka CAS, cofnięcie bazy, zeznanie wstrzymane
    "hand_newer_kept", "undo_hand_newer", "testimony_withheld", "testimony_withheld_undo",
    "copies", "lead_copy", "lead_none", "withheld_completed", "withheld_superseded",
    "hand_newer", "hand_unknown",
    # koperta prozy bez kodu, do której dokleja się nota z kodem (`dopisz`) - granica jawna
    "prose",
})

# Rodzaj wartości każdego parametru powodu (kontrakt kodeka i zdania okna; test AST pilnuje, że
# rdzeń nie podaje parametru spoza tej listy): `text` = tekst (także powód zagnieżdżony, fragment
# zdania) albo None, `int` = liczba całkowita. Parametr spoza listy albo wartość innego rodzaju
# (zapis spoza kodeka) - okno mówi zachowaną prozą (`gui.wb_worker.tekst_powodu`). `notes` osobno:
# krotka powodów.
PARAM_KINDS = {
    **dict.fromkeys(("detail", "inner", "outer", "path", "dir", "src", "dst", "db_path", "in_flight",
                     "intent_detail", "alias", "canon", "target", "text", "status", "commits",
                     "op_kind", "phase", "volume", "copies", "lead"), "text"),
    **dict.fromkeys(("n", "tries", "winerror", "op_id", "location", "object_id", "rename_id",
                     "commit_id"), "int"),
}


def param_ok(nazwa, wartosc):
    """Czy wartość parametru `nazwa` ma rodzaj z `PARAM_KINDS` (bool nie jest liczbą)."""
    rodzaj = PARAM_KINDS.get(nazwa)
    if rodzaj == "text":
        return wartosc is None or isinstance(wartosc, str)
    if rodzaj == "int":
        return isinstance(wartosc, int) and not isinstance(wartosc, bool)
    return False


# Klucze zagnieżdżonego powodu w `reason_args` (JSON). Zwykła wartość parametru nigdy nie jest
# słownikiem, więc słownik z TYMI kluczami to zawsze powód.
_ZDANIE, _KOD, _ARGS = "text", "code", "args"


class PowodPozycji(str):
    """Powód pozycji: zdanie PL (`str`) i jego kod z parametrami (wartości: tekst, liczba, None,
    powód zagnieżdżony albo lista powodów - `notes`). Wzorzec `object_change.ZdanieRdzenia`, osobna
    przestrzeń kluczy (`objchg.item.<kod>`). EXPECT: kod spoza `ITEM_REASON_CODES` → `ValueError`."""

    def __new__(cls, text, code, /, **params):       # `/`: parametr powodu może nazywać się `text`
        if code not in ITEM_REASON_CODES:
            raise ValueError(f"kod powodu pozycji spoza ITEM_REASON_CODES: {code!r}")
        self = super().__new__(cls, text)
        self.code = code
        self.params = tuple(params.items())
        return self

    def __reduce__(self):
        # `copy`/`deepcopy`/`pickle`: dawny protokół `str` odtwarzał obiekt samym tekstem, a `__new__`
        # wymaga kodu - odtworzenie z tekstu, kodu i parametrów (zagnieżdżone powody tą samą drogą).
        return (_odtworz, (str(self), self.code, self.params))


def _odtworz(text, code, params):
    return PowodPozycji(text, code, **dict(params))


class OdmowaZPowodem(ValueError):
    """`ValueError` klingi z powodem pozycji (`powod`) - tekst wyjątku = zdanie PL powodu, więc każdy
    `except ValueError` czyta go jak dotąd, a sterownik zapisu bierze kod z `powod`."""

    def __init__(self, powod):
        super().__init__(str(powod))
        self.powod = powod


def powod_wyjatku(exc):
    """Powód z wyjątku: `PowodPozycji` odmowy klingi albo tekst wyjątku (proza bez kodu)."""
    return getattr(exc, "powod", None) or str(exc)


def dopisz(powod, nota):
    """`powod; nota` - zdanie jak `writeback._dopisz` (puste części pomija), a przy powodzie z kodem
    nota trafia na listę `notes` (okno składa ją w języku UI za zdaniem powodu).

    EXPECT: nota Z KODEM za prozą bez kodu → `ValueError` - sklejenie zgubiłoby kod noty po cichu.
    Wołający, który dokleja do prozy, owija ją najpierw w kopertę `prose` (`PowodPozycji(proza,
    "prose", text=proza)` - jawna granica: proza zostaje prozą, nota mówi w języku UI)."""
    if not nota:
        return powod or None
    if not powod:
        return nota
    if not isinstance(powod, PowodPozycji):
        if isinstance(nota, PowodPozycji):
            raise ValueError(f"nota z kodem {nota.code!r} za prozą bez kodu - kod zginąłby w "
                             f"sklejeniu; owiń prozę w kopertę 'prose'")
        return f"{powod}; {nota}"
    params = dict(powod.params)
    params["notes"] = (*params.get("notes", ()), nota)
    return PowodPozycji(f"{powod}; {nota}", powod.code, **params)


def _do_slownika(wartosc):
    if isinstance(wartosc, PowodPozycji):
        return {_ZDANIE: str(wartosc), _KOD: wartosc.code,
                _ARGS: {k: _do_slownika(v) for k, v in wartosc.params}}
    if isinstance(wartosc, str):
        return str(wartosc)
    if isinstance(wartosc, (list, tuple)):
        return [_do_slownika(v) for v in wartosc]
    if wartosc is None or isinstance(wartosc, (bool, int, float)):
        return wartosc
    raise TypeError(f"parametr powodu pozycji nie do zapisu: {type(wartosc).__name__}")


class _Nieodtwarzalny(Exception):
    """Kształt `reason_args` spoza kodeka - odczyt spada na prozę `reason`."""


def _ze_slownika(wartosc):
    """Wartość parametru z JSON-a. Słownik to WYŁĄCZNIE powód zagnieżdżony `{text, code, args}` -
    każdy inny kształt (obcy słownik, tekst/argumenty złego typu) jest nie do odtworzenia."""
    if isinstance(wartosc, dict):
        if set(wartosc) != {_ZDANIE, _KOD, _ARGS} or not isinstance(wartosc[_ZDANIE], str):
            raise _Nieodtwarzalny
        return _odbuduj(wartosc[_ZDANIE], wartosc[_KOD], wartosc[_ARGS])
    if isinstance(wartosc, list):
        return tuple(_ze_slownika(v) for v in wartosc)
    if wartosc is None or isinstance(wartosc, (str, bool, int, float)):
        return wartosc
    raise _Nieodtwarzalny


def _odbuduj(zdanie, kod, args):
    """Powód z części albo `_Nieodtwarzalny`. Kod, którego ten program nie zna (baza po zmianie
    zbioru kodów), zostaje prozą - zdanie PL jest zawsze."""
    if kod not in ITEM_REASON_CODES:
        return zdanie
    if not isinstance(args, dict):
        raise _Nieodtwarzalny
    params = {k: _ze_slownika(v) for k, v in args.items()}
    if not isinstance(params.get("notes", ()), tuple):
        raise _Nieodtwarzalny                        # uwagi to zawsze lista powodów
    return PowodPozycji(zdanie, kod, **params)


def z_czesci(zdanie, kod, args):
    """Powód z części: `None` (brak powodu), zdanie bez kodu (proza) albo `PowodPozycji`. TOTALNE
    (AR-141): kształt parametrów spoza kodeka (zapis serwisowy, inny program na tym samym numerze
    schematu) to zachowana proza `zdanie`, nigdy wyjątek w oknie."""
    if zdanie is None or kod is None:
        return zdanie
    try:
        return _odbuduj(zdanie, kod, args)
    except _Nieodtwarzalny:
        return zdanie


def do_bazy(powod):
    """Trójka kolumn pozycji `(reason, reason_code, reason_args)`: `None` → trzy NULL, proza bez
    kodu → sama proza, `PowodPozycji` → zdanie, kod i parametry jako obiekt JSON (zagnieżdżone
    powody rekurencyjnie - `json.dumps` podklasy `str` zapisałby goły tekst i zgubił kod)."""
    if powod is None:
        return None, None, None
    if not isinstance(powod, PowodPozycji):
        return str(powod), None, None
    args = {k: _do_slownika(v) for k, v in powod.params}
    return str(powod), powod.code, json.dumps(args, ensure_ascii=False, sort_keys=True)


def z_bazy(reason, reason_code, reason_args):
    """Odwrotność `do_bazy` - wiersz pozycji → powód (`None`, proza albo `PowodPozycji`). JSON
    uszkodzony albo nie-obiekt → proza `reason` (odczyt totalny, jak `z_czesci`)."""
    if reason_args is None:
        return z_czesci(reason, reason_code, None)
    try:
        args = json.loads(reason_args)
    except (TypeError, ValueError):
        return reason
    return z_czesci(reason, reason_code, args)
