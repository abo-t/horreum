"""Katalog i18n (#1) — DANE, SPOT. Jedno kanoniczne źródło każdego stringu UI; `i18n.t`/`t_plural`
czytają stąd. Zero I/O, zero Qt, grepowalny, freeze-czysty (PyInstaller). Kontrybutor dokłada język
dopisując gałąź `"en"`/`"de"`/… przy istniejących kluczach.

Dwa kształty wpisu:
  • prosty (dla `t`):        {"pl": "…", "en": "…"}
  • liczba mnoga (dla `t_plural`): {"pl": {"one","few","many"}, "en": {"one","other"}}

Klucze hierarchiczne per obszar (`menu.*`, `grid.*`, `pipeline.*`, `proj.*`). Formy mnogie niosą `{n}`
w treści (fraza-level: PL odmienia przymiotnik, EN rzeczownik — dlatego cała fraza, nie samo słowo).
Interpolacja: `str.format` (pola `{n}` i nazwane). WARTOŚCI DOMENOWE (kind/filtr/nazwy pól z bazy) NIE
mieszkają tu — tłumaczymy tylko etykiety UI (D-L3, ORDERs TERMS).

Rollout §4 dokłada tu klucze `t()` per plik (app→grid→pipeline→projection→drobne). Dziś katalog niesie
FUNDAMENT: przełącznik języka + skonsolidowane frazy liczby mnogiej (dawne `plural`/`_odmiana`)."""
from __future__ import annotations

CATALOG = {
    # --- przełącznik języka (menu &Widok) -----------------------------------------------------
    "lang.restart_note": {
        "pl": "Zmieniono język — zadziała po ponownym uruchomieniu.",
        "en": "Language changed — it will take effect after a restart.",
    },

    # --- grid „Zbiory": licznik zbioru / zaznaczenia / celu renamu ----------------------------
    "grid.frames": {
        "pl": {"one": "{n} klatka", "few": "{n} klatki", "many": "{n} klatek"},
        "en": {"one": "{n} frame", "other": "{n} frames"},
    },
    "grid.selected": {
        "pl": {"one": "{n} zaznaczona", "few": "{n} zaznaczone", "many": "{n} zaznaczonych"},
        "en": {"one": "{n} selected", "other": "{n} selected"},
    },
    "grid.visible": {
        "pl": {"one": "{n} widoczna", "few": "{n} widoczne", "many": "{n} widocznych"},
        "en": {"one": "{n} visible", "other": "{n} visible"},
    },

    # --- dialog projekcji „Wydaj na stół" -----------------------------------------------------
    "proj.create_copies": {
        "pl": {"one": "Utwórz {n} kopię", "few": "Utwórz {n} kopie", "many": "Utwórz {n} kopii"},
        "en": {"one": "Create {n} copy", "other": "Create {n} copies"},
    },
    "proj.create_links": {
        "pl": {"one": "Utwórz {n} link", "few": "Utwórz {n} linki", "many": "Utwórz {n} linków"},
        "en": {"one": "Create {n} link", "other": "Create {n} links"},
    },
    "proj.files_no_size": {
        "pl": {"one": "(+{n} plik bez rozmiaru)", "few": "(+{n} pliki bez rozmiaru)",
               "many": "(+{n} plików bez rozmiaru)"},
        "en": {"one": "(+{n} file without size)", "other": "(+{n} files without size)"},
    },
    "proj.plan_tree_folders": {
        "pl": {"one": "{n} folder kategorii", "few": "{n} foldery kategorii",
               "many": "{n} folderów kategorii"},
        "en": {"one": "{n} category folder", "other": "{n} category folders"},
    },

    # --- raport dostawy (pipeline): sekcja zniknięć -------------------------------------------
    "pipeline.marked_copies": {
        "pl": {"one": "{n} kopię", "few": "{n} kopie", "many": "{n} kopii"},
        "en": {"one": "{n} copy", "other": "{n} copies"},
    },
    "pipeline.frames_lost_last": {
        "pl": {"one": "{n} klatka straciła ostatnią kopię",
               "few": "{n} klatki straciły ostatnią kopię",
               "many": "{n} klatek straciło ostatnią kopię"},
        "en": {"one": "{n} frame lost its last copy",
               "other": "{n} frames lost their last copy"},
    },
    "pipeline.vanished_still_present": {
        "pl": {"one": "Zniknęła {n} kopia — baza wciąż twierdzi, że jest.",
               "few": "Zniknęły {n} kopie — baza wciąż twierdzi, że są.",
               "many": "Zniknęło {n} kopii — baza wciąż twierdzi, że są."},
        "en": {"one": "{n} copy vanished — the database still claims it is present.",
               "other": "{n} copies vanished — the database still claims they are present."},
    },

    # ============================================================ app.py (rollout §4: app)

    # --- generyczne nagłówki/etykiety współdzielone między osiami (SPOT) ---
    "col.id": {"pl": "ID", "en": "ID"},
    "col.status": {"pl": "Status", "en": "Status"},
    "col.frames": {"pl": "Klatki", "en": "Frames"},
    "col.path": {"pl": "Ścieżka", "en": "Path"},

    # --- akcje/komunikaty scalania wspólne osi teleskopu i obserwatorium ---
    "action.merge": {"pl": "Scal", "en": "Merge"},
    "action.unmerge": {"pl": "Cofnij scalenie", "en": "Undo merge"},
    "axis.history": {"pl": "Historia (audyt):", "en": "History (audit):"},
    "axis.pick_target": {"pl": "— wybierz cel —", "en": "— pick target —"},
    "axis.merge_failed": {"pl": "Nie scalono: {e}", "en": "Not merged: {e}"},
    "axis.unmerge_failed": {"pl": "Nie cofnięto: {e}", "en": "Not undone: {e}"},
    "axis.merged": {"pl": "Scalono #{src} → #{tgt}.", "en": "Merged #{src} → #{tgt}."},
    "axis.unmerged": {"pl": "Cofnięto scalenie #{mid}.", "en": "Merge undone #{mid}."},

    # --- oś TELESKOP ---
    "axis.tel.col.canon": {"pl": "Nagłówek", "en": "Header"},
    "axis.tel.col.label": {"pl": "Etykieta", "en": "Label"},
    "axis.tel.col.fratio": {"pl": "f/", "en": "f/"},
    "axis.tel.col.focal": {"pl": "Ogniskowa", "en": "Focal length"},
    "axis.tel.active": {"pl": "Aktywne teleskopy (kanoniczne)", "en": "Active telescopes (canonical)"},
    "axis.tel.approve": {"pl": "Zatwierdź", "en": "Approve"},
    "axis.tel.merge_into": {"pl": "Scal zaznaczony w:", "en": "Merge selected into:"},
    "axis.tel.merged_under": {"pl": "Scalone pod tym teleskopem:", "en": "Merged under this telescope:"},
    "axis.tel.empty_status": {
        "pl": "Brak teleskopów na osi — uruchom grupowanie (horreum group).",
        "en": "No telescopes on the axis — run grouping (horreum group).",
    },
    "axis.tel.label_rejected": {"pl": "Etykieta odrzucona: {e}", "en": "Label rejected: {e}"},
    "axis.tel.label_saved": {"pl": "Etykieta zapisana.", "en": "Label saved."},
    "axis.tel.label_unchanged": {"pl": "Etykieta bez zmian.", "en": "Label unchanged."},
    "axis.tel.approve_failed": {"pl": "Nie zatwierdzono: {e}", "en": "Not approved: {e}"},
    "axis.tel.approved": {"pl": "Zatwierdzono.", "en": "Approved."},
    "axis.tel.already_approved": {"pl": "Już zatwierdzony.", "en": "Already approved."},
    "axis.tel.already_merged": {"pl": "Już scalony.", "en": "Already merged."},
    "axis.tel.already_canonical": {"pl": "Już kanoniczny.", "en": "Already canonical."},
    "window.telescope_axis": {"pl": "Horreum — oś teleskopu", "en": "Horreum — telescope axis"},

    # --- oś OBSERWATORIUM ---
    "obs.col.name": {"pl": "Nazwa", "en": "Name"},
    "obs.col.lat": {"pl": "Szerokość", "en": "Latitude"},
    "obs.col.lon": {"pl": "Długość", "en": "Longitude"},
    "axis.obs.active": {"pl": "Aktywne stanowiska (kanoniczne)", "en": "Active sites (canonical)"},
    "axis.obs.empty_note": {
        "pl": "Brak stanowisk — uruchom rozwiązywanie (resolve) na skanie z GPS.",
        "en": "No sites — run resolve on a scan with GPS.",
    },
    "axis.obs.merge_into": {"pl": "Scal zaznaczone w:", "en": "Merge selected into:"},
    "axis.obs.merged_under": {"pl": "Scalone pod tym stanowiskiem:", "en": "Merged under this site:"},
    "axis.obs.open_osm": {"pl": "Otwórz w OpenStreetMap…", "en": "Open in OpenStreetMap…"},
    "axis.obs.empty_status": {
        "pl": "Brak stanowisk na osi — uruchom rozwiązywanie (horreum resolve).",
        "en": "No sites on the axis — run resolve (horreum resolve).",
    },
    "axis.obs.select_for_map": {
        "pl": "Zaznacz stanowisko, by otworzyć mapę.",
        "en": "Select a site to open the map.",
    },
    "axis.obs.name_rejected": {"pl": "Nazwa odrzucona: {e}", "en": "Name rejected: {e}"},
    "axis.obs.name_saved": {"pl": "Nazwa zapisana.", "en": "Name saved."},
    "axis.obs.name_unchanged": {"pl": "Nazwa bez zmian.", "en": "Name unchanged."},
    "axis.obs.already_merged": {"pl": "Już scalone.", "en": "Already merged."},
    "axis.obs.already_canonical": {"pl": "Już kanoniczne.", "en": "Already canonical."},

    # --- oś OBIEKT + filtr + kolejka przeglądu ---
    "object.col.name": {"pl": "Obiekt", "en": "Object"},
    "object.col.catalog": {"pl": "Katalog", "en": "Catalog"},
    "frame.col.sha": {"pl": "sha1 danych", "en": "data sha1"},
    "frame.col.telescope": {"pl": "Teleskop", "en": "Telescope"},
    "frame.col.camera": {"pl": "Kamera", "en": "Camera"},
    "frame.col.filter": {"pl": "Filtr", "en": "Filter"},
    "frame.col.date": {"pl": "Data", "en": "Date"},
    "frame.col.present": {"pl": "Obecny", "en": "Present"},
    "copy.col.volume": {"pl": "Wolumen", "en": "Volume"},
    "copy.col.present": {"pl": "Obecna", "en": "Present"},
    "copy.col.marked": {"pl": "Oznaczona", "en": "Marked"},
    "filter.telescope": {"pl": "Teleskop:", "en": "Telescope:"},
    "filter.filter": {"pl": "Filtr:", "en": "Filter:"},
    "filter.all": {"pl": "(wszystkie)", "en": "(all)"},
    "common.yes": {"pl": "tak", "en": "yes"},
    "common.no": {"pl": "nie", "en": "no"},
    "object.library": {"pl": "Biblioteka (obiekty)", "en": "Library (objects)"},
    "object.lib_empty": {
        "pl": "Brak obiektów dla tego filtra — zmień filtr lub rozwiąż (resolve).",
        "en": "No objects for this filter — change the filter or resolve.",
    },
    "object.review_queue": {"pl": "Kolejka przeglądu", "en": "Review queue"},
    "object.assign_btn": {"pl": "Przypisz obiekt…", "en": "Assign object…"},
    "object.frames_of_object": {"pl": "Klatki obiektu", "en": "Object frames"},
    "object.frames_review": {"pl": "Klatki do przeglądu: {name}", "en": "Frames to review: {name}"},
    "object.empty_status": {
        "pl": "Brak obiektów dla tego filtra — zeskanuj i rozwiąż (horreum resolve) lub zmień filtr.",
        "en": "No objects for this filter — scan and resolve (horreum resolve) or change the filter.",
    },
    "object.review_item": {"pl": "{name}  ·  {n} klatek", "en": "{name}  ·  {n} frames"},
    "object.unreadable_line": {"pl": "— kopie nieczytelne: {n}", "en": "— unreadable copies: {n}"},
    "object.review_info": {
        "pl": "— config-review: {config}  ·  bez nagłówka: {headerless}  (rozwiązywanie w przygotowaniu)",
        "en": "— config-review: {config}  ·  headerless: {headerless}  (resolution in preparation)",
    },
    "object.no_path": {"pl": "(brak ścieżki)", "en": "(no path)"},
    "object.unreadable_title": {"pl": "Kopie nieczytelne ({n})", "en": "Unreadable copies ({n})"},
    "object.no_location": {"pl": "(brak lokalizacji)", "en": "(no location)"},
    "object.assigned_report": {
        "pl": "Przypisano {assigned} z {total} klatek → {canon}.",
        "en": "Assigned {assigned} of {total} frames → {canon}.",
    },
    "object.assigned_skipped": {
        "pl": " ({n} pominięte — zajęte między dialogiem a zapisem)",
        "en": " ({n} skipped — taken between dialog and write)",
    },
    "object.alias_no_alnum": {
        "pl": "Nazwa „{name}” nie ma znaków alfanumerycznych — nie może być zapamiętanym aliasem.",
        "en": "Name „{name}” has no alphanumeric characters — it cannot be a remembered alias.",
    },

    # --- dialog „Przypisz obiekt" ---
    "assign.title": {"pl": "Przypisz obiekt", "en": "Assign object"},
    "assign.group_head": {
        "pl": {"one": "Grupa „{name}” — {n} klatka.", "few": "Grupa „{name}” — {n} klatki.",
               "many": "Grupa „{name}” — {n} klatek."},
        "en": {"one": "Group „{name}” — {n} frame.", "other": "Group „{name}” — {n} frames."},
    },
    "assign.alias_remembered": {
        "pl": "Alias zostanie zapamiętany: nowe klatki z tą nazwą przypisze resolver.",
        "en": "The alias will be remembered: the resolver will assign new frames with this name.",
    },
    "assign.catalog_note": {
        "pl": "Ta nazwa rozwiązuje się katalogowo — katalog bije alias: nowe klatki "
              "z tą nazwą przypisze nagłówek, zapamiętany alias dotyczy tej grupy.",
        "en": "This name resolves via the catalog — the catalog beats the alias: the header "
              "will assign new frames with this name, the remembered alias applies to this group.",
    },
    "assign.existing_object": {"pl": "Istniejący obiekt:", "en": "Existing object:"},
    "assign.pick_object": {"pl": "— wybierz obiekt —", "en": "— pick object —"},
    "assign.new_designation": {
        "pl": "albo nowe oznaczenie katalogowe (wypełnione nadpisuje wybór z listy):",
        "en": "or a new catalog designation (if filled, it overrides the list selection):",
    },
    "assign.designation_placeholder": {"pl": "np. IC 1795", "en": "e.g. IC 1795"},
    "assign.accept_btn": {
        "pl": {"one": "Przypisz {n} klatkę", "few": "Przypisz {n} klatki",
               "many": "Przypisz {n} klatek"},
        "en": {"one": "Assign {n} frame", "other": "Assign {n} frames"},
    },
    "assign.unknown_designation": {
        "pl": "Nie rozpoznaję oznaczenia katalogowego: „{text}”.",
        "en": "Unrecognized catalog designation: „{text}”.",
    },
    "assign.pick_or_designate": {
        "pl": "Wybierz istniejący obiekt albo podaj oznaczenie katalogowe.",
        "en": "Pick an existing object or enter a catalog designation.",
    },
    "assign.alias_conflict": {
        "pl": "Alias dla tej nazwy wskazuje już obiekt „{target}” — wybierz go z listy.",
        "en": "The alias for this name already points to object „{target}” — pick it from the list.",
    },

    # --- MainWindow: menu, nawigacja, dialogi plików ---
    "menu.file": {"pl": "&Plik", "en": "&File"},
    "menu.open_db": {"pl": "Otwórz bazę…", "en": "Open database…"},
    "menu.new_db": {"pl": "Nowa baza…", "en": "New database…"},
    "menu.view": {"pl": "&Widok", "en": "&View"},
    "menu.theme.dark": {"pl": "Ciemny", "en": "Dark"},
    "menu.theme.light": {"pl": "Jasny", "en": "Light"},
    "nav.dostawa": {"pl": "Dostawa", "en": "Intake"},
    "nav.zbiory": {"pl": "Zbiory", "en": "Collections"},
    "nav.porzadki": {"pl": "Porządki", "en": "Housekeeping"},
    "nav.porzadki_count": {"pl": "Porządki ({n})", "en": "Housekeeping ({n})"},
    "main.no_db": {
        "pl": "Brak bazy — otwórz lub utwórz bazę (menu Plik).",
        "en": "No database — open or create one (File menu).",
    },
    "main.db_loaded": {"pl": "Baza: {path}", "en": "Database: {path}"},
    "dialog.open_db_title": {"pl": "Otwórz bazę Horreum", "en": "Open Horreum database"},
    "dialog.open_db_filter": {
        "pl": "Bazy SQLite (*.db *.sqlite);;Wszystkie pliki (*)",
        "en": "SQLite databases (*.db *.sqlite);;All files (*)",
    },
    "dialog.new_db_title": {"pl": "Nowa baza Horreum", "en": "New Horreum database"},
    "dialog.new_db_filter": {"pl": "Bazy SQLite (*.db)", "en": "SQLite databases (*.db)"},
}
