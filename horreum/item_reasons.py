"""POWODY RDZENIA ZAPISU - zdanie PL RAZEM z kodem i parametrami, także po zapisie w bazie: pozycje
gestu „Zmień obiekt…”/„Uzgodnij” (AR-141), warstwa renamu, pisarz karty, cofnięcie, odzysk i zwolnienie
izolacji (AR-148).

Pozycja przebiegu (`pending_object_change`), wpis stagingu karty i renamu (`pending_changes`,
`pending_renames`) i zapis wstrzymany (`withheld_write`) niosły powód wyłącznie jako polską prozę, a okna
zapisu i rdzeń czytają go z bazy - samo i18n okna nie miało z czego złożyć zdania w języku UI. Teraz
każdy powód to `PowodPozycji`: zdanie PL (`str` - CLI, log, testy i sklejenia biorą je jak tekst,
znak w znak jak dotąd) + `code` + `params`. Okno składa z nich zdanie `objchg.item.<kod>`
(`gui.wb_worker.tekst_powodu`); proza bez kodu (wiersz sprzed 0041/0042, tekst systemu, wyjątek
czytnika `scan` spoza `XisfFormatError`) zostaje zdaniem PL. Odmowy czytnika i składacza XISF
(`scan.XisfFormatError.powod`) i reguły karty (`card_rules.CardViolation.reason`) rodzą się z kodem
tam, gdzie rodzi się ich zdanie (AR-158).

DLACZEGO LIŚĆ: powody piszą sterownik zapisu (`writeback`) i klinga (`repo`: wstrzymanie zapisu,
dokończenie, doklejka CAS ręki), a czyta GUI. Repo nie importuje planera (`object_change`), więc
nośnik nie mieszka obok `ZdanieRdzenia` - tu, bez importów projektu i bez SQL. Kodek (`do_bazy` /
`z_bazy`) jest jeden: zapisują go wyłącznie pisarze trójki w `repo` (`_set_object_change_reason_tx`,
`_set_pending_reason_tx`, `_set_rename_reason_tx`, INSERT `withheld_write`), odczytują
`gui.queries.object_change_run_view` i czytelnicy wierszy stagingu w `writeback`.

ZAGNIEŻDŻENIE: powód niższej warstwy jedzie PARAMETREM (`inner`, `detail`, `way`, w `file_not_back`
też `outer`) - `PowodPozycji` (warstwy z kodem) albo zwykły `str` (tekst `OSError` w języku systemu,
wyjątek czytnika bez kodu): jawna granica, zdanie UI wstawia taki tekst znak w znak. Uwagi doklejane za
powodem (`; `, `dopisz`) to lista `notes` - lista powodów, nie sklejona proza. Lista cech
(`features`, `paths`) to parametr rodzaju `list` - okno składa ją po `, `, jak rdzeń.

BŁĘDY SYSTEMU KLASĄ (AR-168, AR-184): jeden właściciel klasyfikacji `OSError` (`powod_systemu`,
`blad_systemu`, sekcja na końcu modułu) dla KAŻDEJ drogi plików - pisarza kart (`writeback` woła go pod
dawną nazwą `_blad_systemu`), projekcji i kopii mastera (`projection`), żniw (`harvest`), wersji stosów
(`stack_variants`), kopii wiodącej (`lead_copy`), planera zmiany obiektu (`object_change`) i wykonawców
GUI. Tu, bo te moduły nie importują pisarza (astropy, klinga plików), a powód z kodem i tak mieszka tutaj.
Błąd BAZY (`sqlite3.Error`) ma bliźniaczego właściciela obok (`powod_bazy`, AR-198) - `blad_systemu`
pyta oba, więc workery odczytu GUI (Dom, Porządki, planer, Pola) mówią klasą także błędem SQLite.
Tu też jedyna konstrukcja `OSError` z kodem Windows i ścieżką (`blad_windows`, AR-259) - dla pisarza kart,
drzwi raportu, kanonizacji korzenia skanu i skryptu kontroli pilotażu.
"""

import ctypes
import errno
import json
import os
import sqlite3
import traceback

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
    "xisf_prop_without_card", "xisf_set_missing",
    "xisf_attr_missing", "xisf_not_utf8", "xisf_no_roundtrip", "xisf_unreadable_reader",
    # odmowy czytnika i składacza nagłówka XISF (`scan.XisfFormatError`, AR-158) - zdanie rodzi się
    # w `scan`, pisarz przenosi je do okna przez `_XisfRefusal`
    "xisf_signature", "xisf_no_length", "xisf_no_reserved", "xisf_xml_cut", "xisf_unclosed",
    "xisf_tag_unclosed", "xisf_card_attr_missing", "xisf_card_missing", "xisf_prop_missing",
    "xisf_prop_location", "xisf_prop_empty", "xisf_kw_close_without_open", "xisf_kw_content",
    "xisf_kw_nested", "xisf_kw_unclosed", "xisf_no_cards", "xisf_no_text_template",
    "xisf_template_attrs", "xisf_template_no_name_value", "xisf_template_no_comment",
    "xisf_no_attachment", "xisf_padding_broken", "xisf_no_room",
    # reguły karty FITS 4.0 (`card_rules.CardViolation.reason`, AR-158)
    "card_name", "card_value_chars", "card_comment_chars", "card_value_long", "card_comment_long",
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
    "fb_card_count", "fb_value_not_text", "fb_card_records", "fb_continue",
    "fb_no_room", "free_records", "route_depends",
    # --- błędy systemu klasą (AR-168, `blad_systemu` niżej) i bramka sumy kontrolnej z faktów
    # bazy (AR-167, `card_rules.BRAMKA_SUMY`); region sprzed commitu bez dowodu całego pliku (AR-169)
    "os_denied", "os_missing", "os_no_space", "os_share_lost", "fits_checksum",
    # --- klasa ogólna błędu systemu WYŁĄCZNIE na drodze zapisu dziennika błędów programu (AR-324,
    # `powod_zapisu_dziennika`): kod Windows/errno spoza klas wyżej, surowy tekst w `detail`
    "os_other",
    "undo_region_unproven",
    "undo_newer_write",   # lokacja ma nowszy, niecofnięty zapis - cofnięcie odmawia (AR-318)
    "undo_already_chain",  # zapis wrócił razem ze starszym zapisem tego przebiegu (łańcuch, AR-345)
    # --- bramki celu i zmiany makra (AR-181, `macro.resolve_target`, `_evaluate_change`,
    # `evaluate_manual_change`, `run_macro`/`plan_manual_change`) i powody wyrażenia (`expr.eval_for`)
    "macro_raw", "macro_no_present_copy", "macro_many_copies", "macro_compressed",
    "macro_degenerate", "macro_no_header_hash", "macro_frame_gone", "macro_set_missing",
    "macro_idx_required", "macro_add_exists", "macro_compute", "macro_assign", "macro_not_int",
    "macro_type_mismatch", "macro_manual_many", "macro_manual_not_int", "macro_missing_operand",
    "macro_zero_division",
    # --- pominięcia podglądu renamu i błędy wzoru nazwy (AR-193, `naming.run_rename`,
    # `_resolve_target`, `resolve_dt`, `compose_name`, `_flatgrp_segment`, `validate_template`)
    "rename_no_time_source", "rename_no_datetime", "rename_flat_no_copy", "rename_flat_no_group",
    "rename_flat_empty_group", "rename_flat_many_groups", "rename_no_present_copy",
    "rename_many_copies", "rename_frame_gone", "rename_no_time", "rename_unchanged",
    "rename_collision", "rename_tpl_bad_regex", "rename_tpl_trail_not_last", "rename_tpl_bad_case",
    "rename_tpl_unknown_token", "rename_tpl_bad_level",
    # --- błędy definicji makra i wyrażenia (AR-194, `expr.compile_expr`, `expr._eval`,
    # `macro.MacroDef.from_dict`)
    "expr_empty", "expr_syntax", "expr_bad_const", "expr_store", "expr_call_not_allowed",
    "expr_kwargs", "expr_starred", "expr_bad_node", "macro_def_no_assign", "macro_def_bad_assign",
    "macro_def_bad_op",
    # --- błędy bazy klasą (AR-198, `powod_bazy` niżej) i wydanie obiektu (`projection`, AR-197,
    # AR-200): odmowy klingi wydania i kroki wydania przerwane błędem systemu
    "db_busy", "db_unavailable", "db_full", "db_damaged",
    "proj_root_not_excluded", "proj_first_link", "proj_root_failed", "proj_out_failed",
    "proj_verify_failed", "proj_manifest_failed",
    # --- cofnięcie atomowe z dowodem całego pliku i śladem własnego wyniku (AR-182, `atomic_undo`,
    # `writeback._cofnij_lokacje`, `write_full_header`)
    "undo_already_own", "undo_already_text", "undo_outside_changed", "undo_record_not_saved",
    "undo_own_unproven",
    # --- błąd programu w oknie (AR-209, AR-214, `powod_okna` niżej): EXPECT rdzenia na drodze okna
    # wydania, planera albo zmiany obiektu - surowy tekst `Typ: opis` w `detail`, nie w zdaniu
    "prog_error",
    # --- błąd WEJŚCIA (AR-301, `powod_sciezki_wejscia` niżej): ścieżka wpisana albo wklejona ręką ze
    # znakiem, którego system plików nie przyjmie - zdanie mówi znak, zanim cokolwiek dotknie dysku
    "path_bad_char",
    # --- pliki obok ścieżki po przerwanym cofnięciu atomowym (AR-127, 0045,
    # `writeback._rekoncyliuj_slady`, `writeback._werdykt_wlasciciela`)
    "undo_cut_kept", "undo_files_kept", "undo_files_unknown", "undo_reconcile_failed",
    # --- naprawa manifestu wydania obiektu (AR-213, `projection.repair_manifest`): odmowy zapisu
    # manifestu nad drzewem, które już leży w celu, i błąd odczytu starego manifestu; `busy` mówi
    # też krok manifestu wydania (wspólny protokół `.part`)
    "proj_manifest_incomplete",
    "proj_manifest_damaged", "proj_manifest_foreign", "proj_manifest_changed", "proj_manifest_busy",
    "proj_manifest_unreadable",
    # --- pisarz karty FITS i bramka zakresu podglądu makra (AR-256, `writeback._set_nth`,
    # `macro._evaluate_change`): `set` wystąpienia, którego w nagłówku nie ma - jedna odmowa w obu
    # miejscach; pozostałe odmowy łaty mówią kodami podglądu (`macro_*`)
    "card_idx_missing",
    # --- pisarz karty: liczba nieskończona i liczba, której pole karty FITS nie odtworzy (AR-269,
    # `card_rules` - jedno zdanie dla podglądu i pisarza), operacja spoza `set`/`add` w obu formatach,
    # bajt spoza drukowalnego ASCII w surowym nagłówku FITS (AR-271, każda droga zapisu i cofnięcia)
    "card_value_nonfinite", "card_value_digits", "card_op_unknown", "header_nonprintable",
    # --- odmowa bajtu spoza ASCII przy commicie, gdy status wpisów nie wszedł do bazy (AR-299,
    # `writeback._status_nie_zapisany`): nota za `header_nonprintable`, plik nietknięty
    "pending_status_not_saved",
    # --- granice nagłówka FITS niezgodne z kanonicznym rekordem `END` (AR-174, `writeback._GRANICE_END`):
    # odmowa zapisu w miejscu, drogi atomowej i cofnięcia, plik nietknięty
    "header_end_bounds",
    # --- wzór nazwy z zewnątrz: `re` tokenu `orig` niebędące napisem (AR-368, `naming.validate_template`) - zdanie bez
    # nazwy typu Pythona (dawniej `rename_tpl_bad_regex` z „(NoneType)”)
    "rename_tpl_regex_not_text",
})

# Kody błędu systemu (AR-168): okno dokłada do podpowiedzi surowy tekst systemu (`detail`) - zdanie
# mówi klasę i numer (`os_code`), komunikat systemu jest w języku systemu, nie UI.
OS_REASON_CODES = frozenset({"os_denied", "os_missing", "os_no_space", "os_share_lost", "os_other"})
# Kody błędu bazy klasą (AR-198, `powod_bazy`): zdanie mówi klasę i nazwę błędu SQLite (`db_code`),
# surowy tekst SQLite jedzie w `detail` jak przy systemie.
DB_REASON_CODES = frozenset({"db_busy", "db_unavailable", "db_full", "db_damaged"})
# Kody niosące surowy tekst w `detail` - JEDYNE źródło dla szczegółu w podpowiedzi okna
# (`szczegoly_systemu`, `gui.wb_worker`) i w kolumnie prozowej (`proza_z_diagnoza`).
SYSTEM_REASON_CODES = OS_REASON_CODES | DB_REASON_CODES

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
                     "expected", "needed",
                     # czytnik XISF i reguły karty (AR-158)
                     "attr", "attrs", "char", "name",
                     # błąd systemu klasą (AR-168): „WinError 5” / „Errno 13”
                     "os_code",
                     # błąd bazy klasą (AR-198): „SQLITE_BUSY” - nazwa błędu SQLite
                     "db_code"), "text"),
    **dict.fromkeys(("n", "tries", "winerror", "op_id", "location", "object_id", "rename_id",
                     "commit_id", "before", "after", "free", "length", "limit",
                     # numer wystąpienia karty (AR-256)
                     "idx"), "int"),
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


# ============================================================ BŁĘDY SYSTEMU KLASĄ (AR-168, AR-184)
# Klasa po kodzie Windows (`winerror`), gdy go jest - podklasa
# wyjątku i `errno` CPythona tu kłamią: 53/67 (ścieżka sieciowa) to `FileNotFoundError`, 21 i 32/33
# to `PermissionError`, sieć to EINVAL (mapa zmierzona `OSError(None, 'x', None, kod)`, Python
# 3.13; numery i nazwy: Microsoft Learn, „System Error Codes (0-499)” i „(1000-1299)”). Kod spoza
# tabeli (32/33 zajętość - mówi ją `gui.wb_worker.czytelny_powod`, 1117, 1177…) zostaje tekstem
# systemu. Bez `winerror` (funkcje CRT: `open()`, plik tymczasowy, zapis strumienia, astropy) - po
# `errno`; samo EACCES nie odróżnia odmowy od zajętości (CRT mapuje 32 na 13), zdanie mówi słowa
# systemu z numerem, a surowy tekst jedzie w `detail` (okno: podpowiedź, baza: `reason_args`).
# Do AR-184 sekcja mieszkała w `writeback`; reszta dróg plików sklejała `Typ: opis` sama.
_OS_WINERROR = {
    5: "denied", 19: "denied", 65: "denied",        # ACCESS_DENIED, WRITE_PROTECT, NETWORK_ACCESS_DENIED
    2: "missing", 3: "missing",                     # FILE_NOT_FOUND, PATH_NOT_FOUND
    112: "no_space", 39: "no_space",                # DISK_FULL, HANDLE_DISK_FULL
    # NOT_READY, REM_NOT_LIST, BAD_NETPATH, NETWORK_BUSY, DEV_NOT_EXIST, UNEXP_NET_ERR,
    # NETNAME_DELETED, BAD_NET_NAME, SEM_TIMEOUT, VC_DISCONNECTED, NO_NETWORK, NETWORK_UNREACHABLE,
    # CONNECTION_ABORTED
    **dict.fromkeys((21, 51, 53, 54, 55, 59, 64, 67, 121, 240, 1222, 1231, 1236), "share_lost"),
}
_OS_ERRNO = {errno.EACCES: "denied", errno.EPERM: "denied", errno.ENOENT: "missing",
             errno.ENOSPC: "no_space"}


def _surowy(exc):
    """Surowy tekst wyjątku `Typ: opis` - JEDYNE złożenie (meta-test `tests/test_powody_pisarza.py`):
    `detail` obu klas (`powod_systemu`, `powod_bazy`), tekst spoza klas w `blad_systemu` i `detail`
    błędu programu w `powod_okna` (tam z miejscem w kodzie, `_miejsce_w_kodzie`)."""
    return f"{type(exc).__name__}: {exc}"


_PAKIET = os.path.dirname(os.path.abspath(__file__))     # katalog pakietu `horreum`


def _w_pakiecie(sciezka):
    """Plik ramki śladu jako `horreum/<ścieżka>.py` (ukośnik `/`) albo None - plik spoza pakietu.
    Dwie formy: ścieżka absolutna pod katalogiem pakietu (uruchomienie ze źródeł) i względna od
    `horreum` (exe PyInstallera: `co_filename` = `horreum\\gui\\planner.py`, zmierzone w PYZ wydania).
    Ścieżka absolutna nie wychodzi nigdy - repo jest publiczne, a ścieżka maszyny budującej albo
    profilu użytkownika nie ma czego szukać w UI. Forma względna ma zostać POD `horreum`: człon pusty,
    `.`, `..` albo z dwukropkiem (dysk, `C:`) ją odrzuca - `horreum/../obcy.py` i `horreum/C:/Users/…`
    to nie plik pakietu."""
    if os.path.isabs(sciezka):
        try:
            wzgledna = os.path.relpath(sciezka, _PAKIET)
        except ValueError:                  # inny dysk niż pakiet
            return None
        if wzgledna == os.pardir or wzgledna.startswith(os.pardir + os.sep):
            return None
        return "horreum/" + wzgledna.replace(os.sep, "/")
    czlony = sciezka.replace("\\", "/").split("/")
    if (len(czlony) < 2 or czlony[0] != "horreum"
            or any(c in ("", os.curdir, os.pardir) or ":" in c for c in czlony)):
        return None
    return "/".join(czlony)


def _miejsce_w_kodzie(exc):
    """Miejsce błędu programu w kodzie (AR-237): `horreum/<plik>.py:<linia>` NAJGŁĘBSZEJ ramki śladu,
    która leży w pakiecie, albo None (wyjątek bez śladu - utworzony, nie rzucony, albo ślad świadomie
    ucięty w drodze z wątku tła - i ślad bez ramki pakietu). Ostatnia ramka śladu bez filtra pakietu
    to przy wyjątku biblioteki jej plik ze ścieżką instalacji Pythona (zmierzone:
    `…\\Lib\\json\\decoder.py:361` z profilem użytkownika) - ani nasz kod, ani tekst do UI; najgłębsza
    ramka pakietu to linia `horreum`, która wywołała bibliotekę.

    ŁAŃCUCH WYJĄTKÓW: miejsce bierzemy z PRZYCZYNY ŹRÓDŁOWEJ - `__cause__` (`raise … from`), a bez
    niego `__context__` (wyjątek w handlerze), chyba że kontekst jest wyciszony (`from None`) - bo
    opakowanie mówi, gdzie błąd przepakowano, a nie, gdzie powstał; wyjątek zewnętrzny bywa też bez
    własnego śladu (utworzony z przyczyną, nie rzucony). Przyczyna bez ramki pakietu (rzucona
    i opakowana poza nim) oddaje głos kolejnemu ogniwu ku zewnętrznemu. Cykl w łańcuchu przerywa
    zbiór odwiedzonych."""
    lancuch, odwiedzone = [], set()
    ogniwo = exc
    while ogniwo is not None and id(ogniwo) not in odwiedzone:
        odwiedzone.add(id(ogniwo))
        lancuch.append(ogniwo)
        ogniwo = (ogniwo.__cause__ if ogniwo.__cause__ is not None
                  else None if ogniwo.__suppress_context__ else ogniwo.__context__)
    for ogniwo in reversed(lancuch):                 # od przyczyny źródłowej ku zewnętrznemu
        tb = ogniwo.__traceback__
        for ramka in reversed(traceback.extract_tb(tb) if tb is not None else []):
            plik = _w_pakiecie(ramka.filename)
            if plik is not None:
                return f"{plik}:{ramka.lineno}"
    return None


def powod_systemu(exc, *, ogolna=False):
    """Błąd systemu KLASĄ → `PowodPozycji` (`os_denied`, `os_missing`, `os_no_space`,
    `os_share_lost`: krótka fraza z numerem `os_code`, surowy tekst `Typ: opis` w `detail`) albo
    None - błąd spoza klas, wyjątek nie-`OSError`. Wołający z WŁASNĄ diagnozą spoza klas (czytnik
    żniw, kopia wiodąca) pyta tylko o klasę; reszta bierze `blad_systemu`. Razem z `powod_bazy`
    JEDYNE miejsce rdzenia, w którym tekst wyjątku staje się powodem (meta-test
    `tests/test_powody_pisarza.py`). `ogolna=True` (wyłącznie `powod_zapisu_dziennika`, AR-324):
    `OSError` spoza klas dostaje klasę ogólną `os_other` zamiast None."""
    if not isinstance(exc, OSError):
        return None
    surowy = _surowy(exc)
    kod_win = getattr(exc, "winerror", None)
    if kod_win is not None:
        klasa, os_code = _OS_WINERROR.get(kod_win), f"WinError {kod_win}"
    elif exc.errno is not None:
        klasa, os_code = _OS_ERRNO.get(exc.errno), f"Errno {exc.errno}"
    else:                                   # `OSError("tekst")` - bez numeru; klasa ogólna mówi typ
        klasa, os_code = None, type(exc).__name__
    if klasa == "denied":
        return PowodPozycji(f"odmowa dostępu do pliku ({os_code})", "os_denied",
                            os_code=os_code, detail=surowy)
    if klasa == "missing":
        return PowodPozycji(f"plik albo folder nie istnieje ({os_code})", "os_missing",
                            os_code=os_code, detail=surowy)
    if klasa == "no_space":
        return PowodPozycji(f"brak miejsca na dysku ({os_code})", "os_no_space",
                            os_code=os_code, detail=surowy)
    if klasa == "share_lost":
        return PowodPozycji(f"udział sieciowy albo dysk nie odpowiada ({os_code})",
                            "os_share_lost", os_code=os_code, detail=surowy)
    if ogolna:
        return PowodPozycji(f"błąd systemu plików ({os_code})", "os_other", os_code=os_code, detail=surowy)
    return None


# Klasa błędu BAZY (AR-198) po głównym kodzie SQLite (`sqlite_errorcode & 0xFF` - kod rozszerzony
# niesie w młodszym bajcie kod główny). Zbiór zmierzony na prawdziwych błędach (SQLite 3.51.1,
# Python 3.13): drugie połączenie przy blokadzie zapisu → BUSY (5), tabela zablokowana w tym samym
# połączeniu → LOCKED (6), brak katalogu bazy → CANTOPEN (14), zapis do bazy `mode=ro` → READONLY
# (8), `max_page_count` → FULL (13), nadpisane strony → CORRUPT (11), śmieci zamiast bazy → NOTADB
# (26); IOERR (10) - zerwany dysk pod otwartą bazą: NIEZWERYFIKOWANE POMIAREM (lokalnie nie do
# wywołania; klasa z dokumentacji SQLite, bez testu i bez mutanta). Poza klasą (tekst SQLite jak dotąd): przerwanie
# zapytania (INTERRUPT - anulowanie wątku tła), ograniczenia (CONSTRAINT - odmowa klingi bazy),
# operacja na zamkniętym połączeniu (`ProgrammingError` bez kodu). Do AR-198 workery odczytu
# (Dom, Porządki, planer, Pola) i okno zmiany obiektu mówiły surowym `OperationalError: …` po
# angielsku w każdym języku UI.
_DB_KLASY = {
    sqlite3.SQLITE_BUSY: "busy", sqlite3.SQLITE_LOCKED: "busy",
    sqlite3.SQLITE_CANTOPEN: "unavailable", sqlite3.SQLITE_IOERR: "unavailable",
    sqlite3.SQLITE_READONLY: "unavailable",
    sqlite3.SQLITE_FULL: "full",
    sqlite3.SQLITE_CORRUPT: "damaged", sqlite3.SQLITE_NOTADB: "damaged",
}


def powod_bazy(exc):
    """Błąd bazy KLASĄ → `PowodPozycji` (`db_busy`, `db_unavailable`, `db_full`, `db_damaged`:
    krótka fraza z nazwą błędu SQLite `db_code`, surowy tekst `Typ: opis` w `detail`) albo None -
    błąd spoza klas, wyjątek nie-`sqlite3.Error`. Bliźniak `powod_systemu` dla silnika bazy."""
    if not isinstance(exc, sqlite3.Error):
        return None
    kod = getattr(exc, "sqlite_errorcode", None)
    klasa = _DB_KLASY.get(kod & 0xFF) if isinstance(kod, int) else None
    db_code = getattr(exc, "sqlite_errorname", None) or type(exc).__name__
    surowy = _surowy(exc)
    if klasa == "busy":
        # Bez „przez inny zapis”: LOCKED to blokada tabeli TEGO SAMEGO połączenia (otwarty kursor),
        # przyczynę mówi nazwa błędu SQLite w nawiasie.
        return PowodPozycji(f"baza zablokowana ({db_code})", "db_busy",
                            db_code=db_code, detail=surowy)
    if klasa == "unavailable":
        return PowodPozycji(f"baza niedostępna do odczytu albo zapisu ({db_code})", "db_unavailable",
                            db_code=db_code, detail=surowy)
    if klasa == "full":
        return PowodPozycji(f"brak miejsca na bazę ({db_code})", "db_full",
                            db_code=db_code, detail=surowy)
    if klasa == "damaged":
        return PowodPozycji(f"plik bazy uszkodzony albo nie jest bazą ({db_code})", "db_damaged",
                            db_code=db_code, detail=surowy)
    return None


def blad_systemu(exc, *, z_typem=True):
    """Powód z wyjątku: błąd systemu klasą (`powod_systemu`), błąd bazy klasą (`powod_bazy`, AR-198)
    albo - błąd spoza klas - tekst wyjątku jak dotąd: `Typ: opis` (`z_typem=False`: `str(exc)`,
    miejsca, które składały powód bez typu). Ten sam tekst co w `detail` klasy, więc kod spoza
    tabeli mówi znak w znak to, co system albo SQLite."""
    powod = powod_systemu(exc) or powod_bazy(exc)
    if powod is not None:
        return powod
    return _surowy(exc) if z_typem else str(exc)


def powod_zapisu_dziennika(exc):
    """Powód porażki ZAPISU dziennika błędów programu (AR-324, linia dziennika w oknie straży
    `gui.app.StrazBledowProgramu`): błąd systemu albo bazy klasą jak wszędzie; `OSError` spoza klas -
    klasa ogólna `os_other` („błąd systemu plików (WinError N)”, surowy tekst w `detail`), żeby zdanie
    mówiło w języku UI, a nie tekstem systemu (zmierzone na prawdziwym `Dziennik.zapisz`: plik w miejscu
    katalogu dziennika - WinError 183, niedozwolona nazwa katalogu - WinError 123); inny wyjątek -
    reguła okna (`powod_okna`, błąd programu z miejscem). Klasa ogólna TYLKO tutaj: w drogach plików
    archiwum kod spoza tabeli zostaje tekstem systemu (`blad_systemu` - zajętość 32/33 rozpoznaje dalej
    `gui.wb_worker.czytelny_powod`)."""
    return powod_systemu(exc, ogolna=True) or powod_bazy(exc) or powod_okna(exc)


def blad_windows(err, path):
    """Błąd wywołania Windows (`GetLastError`) jako `OSError` z kodem i ŚCIEŻKĄ (AR-242, AR-259) -
    JEDYNA konstrukcja w pakiecie i skryptach (pisarz kart, drzwi raportu, `scan.canonize_root`,
    kontrola pilotażu). `ctypes.WinError(err)` dawało `[WinError 5] Odmowa dostępu.` bez nazwy pliku,
    więc przy wsadzie szczegół nie mówił, który plik padł. Podklasę i `errno` CPython wylicza
    z `winerror` tak samo jak dla `ctypes.WinError` (klasa `powod_systemu` bez zmian); tekst systemu
    bez kropki końcowej, jak w wyjątkach CPythona, za nim `: 'ścieżka'`. Tylko Windows
    (`ctypes.FormatError`)."""
    return OSError(None, ctypes.FormatError(err).rstrip(" .\r\n"), path, err)


def powod_okna(exc):
    """Powód wyjątku drogi okna (wątek tła albo gest) - JEDNA reguła dla okien wydania, planera i
    zmiany obiektu (AR-209, AR-214): odmowa z powodem (`OdmowaZPowodem.powod`, `ProjectionAbort.powod`)
    → ten powód; błąd systemu albo bazy (`OSError`, `sqlite3.Error`) → klasa albo tekst systemu
    (`blad_systemu`); każdy inny wyjątek to EXPECT rdzenia (goły `ValueError`, `AssertionError`,
    `KeyError`) - błąd programu `prog_error` z surowym tekstem `Typ: opis` w `detail` (szczegół pod
    kursorem, nie w zdaniu). Użycie API bazy wbrew kontraktowi (`ProgrammingError` - np. operacja
    na zamkniętym połączeniu, `InterfaceError`) to też EXPECT, nie stan bazy: błąd programu, nie
    surowy angielski tekst SQLite w zdaniu.

    MIEJSCE W KODZIE (AR-237): `detail` błędu programu kończy się ` @ horreum/<plik>.py:<linia>`
    (`_miejsce_w_kodzie`), gdy ślad je zna - samo `KeyError: 'x'` nie mówi, gdzie szukać, a pakiet
    nie ma logów. Wołający liczą powód w handlerze `except` (także w wątku tła), więc ślad jest pełny,
    a do okna jedzie gotowy tekst. Klasy systemu i bazy miejsca nie dostają: ich `detail` idzie
    też do bazy i do zeznań (`proza_z_diagnoza`)."""
    powod = getattr(exc, "powod", None)
    if powod:
        return powod
    if (isinstance(exc, (OSError, sqlite3.Error))
            and not isinstance(exc, (sqlite3.ProgrammingError, sqlite3.InterfaceError))):
        return blad_systemu(exc)
    miejsce = _miejsce_w_kodzie(exc)
    detail = _surowy(exc) + (f" @ {miejsce}" if miejsce else "")
    return PowodPozycji("błąd programu - szczegół w podpowiedzi", "prog_error", detail=detail)


# Znaki, których ścieżka Windows nie przyjmie (AR-301) - zbiór ZMIERZONY `os.stat` (Python 3.13): NUL daje
# `ValueError: embedded null character`, U+0001..U+001F i `< > " | ? *` - `OSError` WinError 123 (nazwa
# niepoprawna). Poza zbiorem: `:` w środku (WinError 3 - brak, zdanie „nie istnieje” jest prawdą), spacja
# i kropka na końcu, U+007F (brak).
_ZNAKI_NIEDOZWOLONE = frozenset(map(chr, range(32))) | frozenset('<>"|?*')
# Przedrostki przestrzeni nazw Win32 (`\\?\C:\…`, `\\.\…`) - ich `?` i `.` to składnia, nie znak nazwy.
_PRZEDROSTKI_WIN32 = ("\\\\?\\", "\\\\.\\")


def powod_sciezki_wejscia(sciezka):
    """Ścieżka WPISANA ręką (pole okna) ze znakiem spoza `_ZNAKI_NIEDOZWOLONE` → `PowodPozycji`
    `path_bad_char` (pierwszy taki znak w `char`: drukowalny wprost, sterujący jako `U+0009`), inaczej None.

    DLACZEGO GRANICA WEJŚCIA, A NIE ROZPOZNANIE WYJĄTKU (AR-301): `ValueError` „embedded null character”
    rzuca każda funkcja `os.*` dla KAŻDEGO tekstu z NUL-em - ścieżki z bazy, z nagłówka, z ustawień - a tam
    to błąd programu albo danych (`powod_okna` mówi go `prog_error`, EXPECT). Człowiek wprowadza ścieżkę
    w jedno pole (wyjście żniw - pozostałe przychodzą z okna wyboru systemu), więc pole pyta TU, zanim
    ścieżka dotknie dysku; NUL, który mimo to doszedł do `os.stat`, to pominięta walidacja, czyli błąd
    programu. Klawiatura znaku sterującego nie wpisze, wklejenie - tak (zmierzone na `QLineEdit`)."""
    tresc = sciezka
    for przedrostek in _PRZEDROSTKI_WIN32:
        if tresc.startswith(przedrostek):
            tresc = tresc[len(przedrostek):]
            break
    for znak in tresc:
        if znak in _ZNAKI_NIEDOZWOLONE:
            pokaz = znak if znak.isprintable() else f"U+{ord(znak):04X}"
            return PowodPozycji(f"ścieżka zawiera niedozwolony znak: {pokaz}", "path_bad_char",
                                char=pokaz)
    return None


def szczegoly_systemu(powod) -> list[str]:
    """Surowe teksty systemu i bazy (`detail`) błędów klasą (`SYSTEM_REASON_CODES`) w drzewie
    powodu (parametry-powody, listy, uwagi) - w kolejności zdania."""
    if not isinstance(powod, PowodPozycji):
        return []
    if powod.code in SYSTEM_REASON_CODES:
        return [dict(powod.params)["detail"]]
    wynik = []
    for _nazwa, wartosc in powod.params:
        for w in (wartosc if isinstance(wartosc, (list, tuple)) else (wartosc,)):
            wynik += szczegoly_systemu(w)
    return wynik


def proza_z_diagnoza(powod):
    """Powód do KOLUMNY PROZOWEJ (bez `reason_args`: `inplace_op.reason`) i do zeznania w pliku
    (`harvest` - `_ZNIWA_*.json`) - zdanie PL, a gdy w powodzie jest błąd systemu klasą, za nim
    surowy tekst systemu (`zdanie - Typ: opis`), żeby diagnoza nie zginęła razem z kodem (AR-168).
    `None` → `None`."""
    if powod is None:
        return None
    szczegoly = szczegoly_systemu(powod)
    return " - ".join([str(powod), *szczegoly]) if szczegoly else str(powod)


# Kody ODMOWY REKONCYLIACJI zamiaru renamu (AR-323): powody, z którymi `writeback.reconcile_renames` zwraca
# 'blocked' (`_rozstrzygnij_zamiar`, `_dysk_milczy`, gałąź `except` w `reconcile_renames`) i które
# `repo.note_rename_intent_refusal` kładzie na wiersz zamiaru. PO CO ZBIÓR: wiersz z otwartym zamiarem niesie
# też powód samej próby renamu - `torn_db_not`, `returned_intent_left`, powody 'blocked' pisarza (porażka
# zgaszenia zamiaru przed renamem połknięta w `_rename_pod_straza`) - a `status` tych dwóch nie rozróżnia
# (zapis odmowy statusu nie zmienia). Szuflada mówi „rekoncyliacja odmówiła” wyłącznie dla kodu z tego zbioru;
# inny kod na wierszu z zamiarem to próba, której rekoncyliacja jeszcze nie rozstrzygała. Zbiór jest rozłączny
# z każdym innym kodem powodu `writeback` i `repo` (pisarz renamu, `rename_file`, wyjątki repo) - pilnuje
# `tests/test_writeback_rekoncyliacja_powod.py` (AST: zbiór == kody 'blocked' rekoncyliacji).
KODY_ODMOWY_REKONCYLIACJI = frozenset({
    "disk_silent", "intent_both_names", "intent_no_name", "intent_mtime_differs",
    "intent_sha1_differs", "intent_changed", "intent_target_taken", "reconcile_failed",
})


# Kody odmowy rekoncyliacji PRZEJŚCIOWEJ (AR-347): dysk nie odpowiedział, zamiar zmienił się pod rekoncyliacją,
# rekoncyliacja padła - zamiar rozstrzygnie NASTĘPNA rekoncyliacja (każdy zapis nazw, skan, CLI), nie człowiek.
# Podzbiór `KODY_ODMOWY_REKONCYLIACJI`; reszta tamtego zbioru to odmowy, które rozstrzyga człowiek - szuflada mówi
# przy nich drogę per kod (`gui.grid.FramesView._DROGI_ODMOWY_NAZW`), a przy tych obietnicę rekoncyliacji.
KODY_PRZEJSCIOWE_REKONCYLIACJI = frozenset({"disk_silent", "intent_changed", "reconcile_failed"})
