"""POWODY RDZENIA ZAPISU - zdanie PL RAZEM z kodem i parametrami, także po zapisie w bazie: pozycje
gestu „Zmień obiekt…”/„Uzgodnij” (AR-141), warstwa renamu, pisarz karty, cofnięcie, odzysk i zwolnienie
izolacji (AR-148).

Pozycja przebiegu (`pending_object_change`), wpis stagingu karty i renamu (`pending_changes`,
`pending_renames`) i zapis wstrzymany (`withheld_write`) niosły powód wyłącznie jako polską prozę, a okna
zapisu i rdzeń czytają go z bazy - samo i18n okna nie miało z czego złożyć zdania w języku UI. Teraz
każdy powód to `PowodPozycji`: zdanie PL (`str` - CLI, log, testy i sklejenia biorą je jak tekst,
znak w znak jak dotąd) + `code` + `params`. Okno składa z nich zdanie `objchg.item.<kod>`
(`gui.wb_worker.tekst_powodu`); proza bez kodu (wiersz sprzed 0041/0042, tekst systemu, odmowa czytnika
`scan` i reguły karty `card_rules`) zostaje zdaniem PL.

DLACZEGO LIŚĆ: powody piszą sterownik zapisu (`writeback`) i klinga (`repo`: wstrzymanie zapisu,
dokończenie, doklejka CAS ręki), a czyta GUI. Repo nie importuje planera (`object_change`), więc
nośnik nie mieszka obok `ZdanieRdzenia` - tu, bez importów projektu i bez SQL. Kodek (`do_bazy` /
`z_bazy`) jest jeden: zapisują go wyłącznie pisarze trójki w `repo` (`_set_object_change_reason_tx`,
`_set_pending_reason_tx`, `_set_rename_reason_tx`, INSERT `withheld_write`), odczytują
`gui.queries.object_change_run_view` i czytelnicy wierszy stagingu w `writeback`.

ZAGNIEŻDŻENIE: powód niższej warstwy jedzie PARAMETREM (`inner`, `detail`, `way`, w `file_not_back`
też `outer`) - `PowodPozycji` (warstwy z kodem) albo zwykły `str` (tekst `OSError` w języku systemu,
odmowa czytnika `scan`): jawna granica, zdanie UI wstawia taki tekst znak w znak. Uwagi doklejane za
powodem (`; `, `dopisz`) to lista `notes` - lista powodów, nie sklejona proza. Lista cech
(`features`, `paths`) to parametr rodzaju `list` - okno składa ją po `, `, jak rdzeń.
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
    # --- warstwa pisarza karty i renamu (AR-148) ---
    # fragmenty: drogi wyjścia z izolacji (gest okna + wywołanie rdzenia), cechy rozjazdu pliku
    "way_finish", "way_restore", "way_manual", "way_resume_return", "way_retry", "way_retry_open",
    "way_retry_written", "changed_in_window", "feat_ino", "feat_size", "feat_mtime", "feat_header",
    "feat_sample", "feat_unreadable", "feat_file_size", "feat_header_bytes", "feat_header_hash",
    # pisarz karty: droga atomowa, podmiana systemowa, cofnięcie atomowe
    "verify_read_failed", "verify_mismatch", "replace_copy_missing", "replace_cut_copy_back_failed",
    "replace_cut_both_missing", "return_cut", "return_failed_manual", "third_writer",
    "other_writer_returned", "displaced_unreadable", "confirm_lost_copy_kept",
    "close_failed_copy_left", "copy_not_removed", "comment_cut", "raw_read_only",
    "header_hash_mismatch", "backup_not_saved", "undo_bytes_unverified", "undo_semantic_outside",
    "undo_semantic", "undo_header_changed",
    # pisarz XISF (`_XisfRefusal`)
    "xisf_unreadable", "xisf_many_images", "xisf_no_identity", "xisf_prop_rule", "xisf_prop_mismatch",
    "xisf_card_exists", "xisf_prop_without_card", "xisf_bad_op", "xisf_set_missing",
    "xisf_attr_missing", "xisf_not_utf8", "xisf_no_roundtrip",
    # zapis w miejscu i odzysk rozdartego nagłówka
    "phase_not_saved", "header_moved_before_write", "anchor_mismatch", "journal_not_saved",
    "inplace_cut", "inplace_unfinished", "inplace_verify_failed", "inplace_verify_mismatch",
    "handle_close_failed", "fb_replaced_since_commit", "undo_already_region", "undo_region_changed",
    "inplace_other_file", "not_torn_readable", "not_torn_manual",
    # orkiestracja: kontrola danych, dokończenie, rekoncyliacja backupu, wynik lokacji
    "data_identity_changed", "check_header_other", "check_no_anchor", "check_outside_changed",
    "inplace_after_read", "no_operation", "finish_not_waiting", "finish_newer_op",
    "finish_region_changed", "synced_not_saved", "resync_failed_retry", "check_failed_way_back",
    "backup_reconcile_failed", "backup_still_pending", "backup_confirm_blocked",
    "commit_cut_unproven", "commit_cut_other_returned", "commit_cut_copy_left",
    "commit_cut_return_cut", "commit_cut_return_failed", "backup_changed_during",
    "returned_not_read", "compressed_master", "no_fallback", "replace_unconfirmed",
    "backup_saved_in", "backup_saved_in_isolated", "finish_failed_isolated",
    "finish_failed_isolated_release", "resync_failed",
    # renam: staging, rekoncyliacja zamiarów, cofnięcie
    "rename_undone", "rename_undone_because", "reconcile_failed", "no_location_row",
    "intent_closed_no_location", "disk_silent", "intent_both_names", "intent_no_name",
    "intent_mtime_differs", "intent_sha1_differs", "intent_changed", "intent_target_taken",
    "reconciled_relocated", "reconciled_in_sync", "rename_changed_since_preview",
    "not_on_commit_name", "intent_settled_elsewhere", "intent_file_moved",
    # cofnięcie commitu, odzysk, droga powrotu, zwolnienie izolacji
    "undo_resync_failed", "isolated_suffix", "undo_finish_failed", "undo_not_replaced",
    "undo_open_op", "undo_sync_finished", "undo_already_op", "undo_commit_unfinished",
    "backup_envelope_broken", "undo_partial_isolated", "undo_already", "undo_not_synced",
    "recover_not_open", "recover_closed_meanwhile", "recover_newer_op", "recover_resync_failed",
    "recover_phase_not_saved", "return_not_written", "return_newer_op", "return_region_foreign",
    "return_read_failed", "return_check_passes", "return_resumed", "reverted_rescan",
    "revert_phase_not_saved", "release_file_busy", "release_not_isolating",
    "released_without_lock", "release_refused_db", "release_phase_changed",
    # klinga (`repo`): potwierdzenia wpisów stagingu, dopiski zamknięcia wstrzymania
    "confirmed_by_scan", "confirmed_from_disk_cut", "withheld_undone", "withheld_other_frame",
    "withheld_newer_header",
    # plan zapisu FITS w miejscu: spadek na drogę atomową (`Fallback`), odmowa sumy kontrolnej,
    # przepowiednia drogi w podglądzie (`inplace_route`)
    "fb_card_too_long", "fb_compressed", "checksum_present", "fb_op_kind", "fb_not_text_card",
    "fb_card_present", "fb_card_count", "fb_value_not_text", "fb_card_records", "fb_continue",
    "fb_no_room", "free_records", "route_depends",
})

# Rodzaj wartości każdego parametru powodu (kontrakt kodeka i zdania okna; test AST pilnuje, że
# rdzeń nie podaje parametru spoza tej listy): `text` = tekst (także powód zagnieżdżony, fragment
# zdania) albo None, `int` = liczba całkowita, `list` = lista (krotka) tekstów albo powodów -
# okno składa ją po `, `, jak rdzeń (cechy rozjazdu pliku, ścieżki zostawione do oka). Parametr
# spoza listy albo wartość innego rodzaju (zapis spoza kodeka) - okno mówi zachowaną prozą
# (`gui.wb_worker.tekst_powodu`). `notes` osobno: krotka powodów.
PARAM_KINDS = {
    **dict.fromkeys(("detail", "inner", "outer", "path", "dir", "src", "dst", "db_path", "in_flight",
                     "intent_detail", "alias", "canon", "target", "text", "status", "commits",
                     "op_kind", "phase", "volume", "copies", "lead",
                     # warstwa pisarza karty i renamu (AR-148)
                     "keyword", "copy", "tmp", "change", "way", "error", "prop", "value", "current",
                     "card", "derived", "op", "value_type", "sha1", "mtime", "db_mtime",
                     "expected", "needed"), "text"),
    **dict.fromkeys(("n", "tries", "winerror", "op_id", "location", "object_id", "rename_id",
                     "commit_id", "before", "after", "free"), "int"),
    **dict.fromkeys(("features", "paths", "sums"), "list"),
}


def param_ok(nazwa, wartosc):
    """Czy wartość parametru `nazwa` ma rodzaj z `PARAM_KINDS` (bool nie jest liczbą)."""
    rodzaj = PARAM_KINDS.get(nazwa)
    if rodzaj == "text":
        return wartosc is None or isinstance(wartosc, str)
    if rodzaj == "int":
        return isinstance(wartosc, int) and not isinstance(wartosc, bool)
    if rodzaj == "list":
        return isinstance(wartosc, (list, tuple)) and all(isinstance(v, str) for v in wartosc)
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


def dopisz_z_koperta(powod, nota):
    """`dopisz` dla wołającego, który dokleja do powodu dowolnej warstwy: nota Z KODEM za prozą bez
    kodu (tekst systemu, wiersz bazy sprzed kodów) - proza w kopercie `prose`, kod noty zostaje.
    Jedna reguła dla sterownika zapisu (`writeback._dopisz`) i klingi (`repo`, dopiski wstrzymań)."""
    if powod and isinstance(nota, PowodPozycji) and not isinstance(powod, PowodPozycji):
        powod = PowodPozycji(powod, "prose", text=powod)
    return dopisz(powod, nota)


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
    zbioru kodów), zostaje prozą - zdanie PL jest zawsze. Kod nie-tekst (lista, obiekt JSON, liczba
    z kolumny bez typu) to kształt spoza kodeka - sprawdzany PRZED członkostwem w zbiorze, bo obiekt
    niehaszowalny wywróciłby odczyt `TypeError`."""
    if not isinstance(kod, str):
        raise _Nieodtwarzalny
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
