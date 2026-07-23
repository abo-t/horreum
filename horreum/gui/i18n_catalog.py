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

    # ============================================================ grid.py (rollout §4: grid)

    # --- kolumny bazowe (reszta reużyta: col.path/frame.col.*/object.col.name) ---
    "grid.col.kind": {"pl": "Rodzaj", "en": "Kind"},
    "grid.col.dt_delta": {"pl": "Δh (hdr−nazwa)", "en": "Δh (hdr−name)"},

    # --- operatory filtra (etykieta; klucz-op to DANE) ---
    "grid.op.eq": {"pl": "= równe", "en": "= equal"},
    "grid.op.ne": {"pl": "≠ różne", "en": "≠ not equal"},
    "grid.op.gt": {"pl": "> większe", "en": "> greater"},
    "grid.op.lt": {"pl": "< mniejsze", "en": "< less"},
    "grid.op.ge": {"pl": "≥", "en": "≥"},
    "grid.op.le": {"pl": "≤", "en": "≤"},
    "grid.op.contains": {"pl": "zawiera", "en": "contains"},
    "grid.op.startswith": {"pl": "zaczyna się", "en": "starts with"},
    "grid.op.exists": {"pl": "istnieje", "en": "exists"},
    "grid.op.not_exists": {"pl": "brak wartości", "en": "no value"},

    # --- nazwy perspektyw (WYŚWIETLANIE; tożsamość zostaje w itemData = klucz PRESETS) ---
    "perspective.review": {"pl": "Przegląd", "en": "Review"},
    "perspective.calibration": {"pl": "Kalibracja", "en": "Calibration"},
    "perspective.dups": {"pl": "Duplikaty", "en": "Duplicates"},
    "perspective.vanished": {"pl": "Zniknięte", "en": "Vanished"},
    "perspective.to_review": {"pl": "Do przeglądu", "en": "To review"},

    # --- pusty grid (rozwiązywane w USE-site; stałe _EMPTY_* trzymają KLUCZ) ---
    "grid.empty_filter": {
        "pl": "Brak klatek dla tego filtra — zmień filtr lub perspektywę.",
        "en": "No frames for this filter — change the filter or perspective.",
    },
    "grid.empty_db": {
        "pl": "Baza pusta — przyjmij dostawę (miejsce „Dostawa” w lewym pasku).",
        "en": "Database empty — take a delivery (the „Intake” place in the left bar).",
    },

    # --- kolumna podglądu klingi (makro/rename) ---
    "grid.preview.macro": {"pl": "makro →", "en": "macro →"},
    "grid.preview.name": {"pl": "nazwa →", "en": "name →"},
    "grid.preview.skipped": {"pl": "(pominięto)", "en": "(skipped)"},
    "grid.preview.skipped_tip": {"pl": "pominięto: {reason}", "en": "skipped: {reason}"},
    "grid.preview.owner_macro": {"pl": "makra", "en": "macro"},
    "grid.preview.owner_rename": {"pl": "nazw", "en": "names"},
    "grid.preview.takeover": {
        "pl": "Zdjęto podgląd {other} (druga klinga)",
        "en": "Cleared {other} preview (the other blade)",
    },
    "grid.tip.vanished": {
        "pl": "\n(zniknięta — wszystkie lokalizacje present=0)",
        "en": "\n(vanished — all locations present=0)",
    },
    "grid.tip.dup_locs": {
        "pl": "\n({n} obecnych lokalizacji)", "en": "\n({n} present locations)",
    },

    # --- FilterBuilder ---
    "grid.filter.join": {"pl": "Łącz:", "en": "Join:"},
    "grid.filter.add_cond": {"pl": "+ warunek", "en": "+ condition"},
    "grid.filter.invert": {
        "pl": "Odwróć: pokaż wszystko POZA filtrem",
        "en": "Invert: show everything OUTSIDE the filter",
    },
    "grid.filter.apply": {"pl": "Zastosuj", "en": "Apply"},
    "grid.filter.clear": {"pl": "Wyczyść", "en": "Clear"},

    # --- FieldPanel ---
    "grid.fields.title": {"pl": "Pola (kolumny)", "en": "Fields (columns)"},

    # --- akcje kling (wspólne makro+rename) ---
    "grid.action.preview": {"pl": "Podgląd", "en": "Preview"},
    "grid.action.to_staging": {"pl": "Do stagingu", "en": "To staging"},
    "grid.action.clear_preview": {"pl": "Wyczyść podgląd", "en": "Clear preview"},

    # --- MacroBar ---
    "grid.macro.compute": {"pl": "Oblicz:", "en": "Compute:"},
    "grid.macro.name_ph": {"pl": "nazwa (opc.)", "en": "name (opt.)"},
    "grid.macro.expr_ph": {
        "pl": "wyrażenie, np. FOCALLEN / FOCRATIO",
        "en": "expression, e.g. FOCALLEN / FOCRATIO",
    },
    "grid.macro.assign": {"pl": "Przypisz:", "en": "Assign:"},
    "grid.macro.assign_ph": {
        "pl": "wartość lub wyrażenie, np. round(new, 2)",
        "en": "value or expression, e.g. round(new, 2)",
    },
    "grid.macro.error": {"pl": "Błąd makra: {exc}", "en": "Macro error: {exc}"},
    "grid.macro.no_frames_count": {
        "pl": "Makro: brak widocznych klatek do policzenia",
        "en": "Macro: no visible frames to count",
    },
    "grid.macro.preview_result": {
        "pl": "Podgląd makra: {t} do zapisu, {s} pominięto",
        "en": "Macro preview: {t} to write, {s} skipped",
    },
    "grid.macro.no_frames": {"pl": "Makro: brak widocznych klatek", "en": "Macro: no visible frames"},
    "grid.macro.staging_busy": {
        "pl": "Makro: najpierw zatwierdź/odrzuć staging nazw",
        "en": "Macro: first commit/discard the name staging",
    },
    "grid.macro.staged": {
        "pl": "Do stagingu: {t} zmian, {s} pominięto",
        "en": "To staging: {t} changes, {s} skipped",
    },
    "grid.macro.preview_cleared": {"pl": "Podgląd makra wyczyszczony", "en": "Macro preview cleared"},

    # --- TokenRow (edytor wzoru nazwy): etykieta typu tokenu; klucz-tid to DANE ---
    "grid.token.datetime": {"pl": "data-godzina", "en": "date-time"},
    "grid.token.object": {"pl": "obiekt", "en": "object"},
    "grid.token.kind": {"pl": "rodzaj", "en": "kind"},
    "grid.token.filter": {"pl": "filtr", "en": "filter"},
    "grid.token.exp": {"pl": "ekspozycja", "en": "exposure"},
    "grid.token.disc": {"pl": "znaczek (disc)", "en": "disc mark"},
    "grid.token.folder": {"pl": "folder nadrzędny", "en": "parent folder"},
    "grid.token.orig": {"pl": "fragment starej nazwy", "en": "old-name fragment"},
    "grid.token.level_prefix": {"pl": "poziom ", "en": "level "},
    "grid.token.regex_ph": {
        "pl": "regex fragmentu starej nazwy", "en": "regex of old-name fragment",
    },

    # --- TemplateEditor ---
    "grid.tmpl.title": {"pl": "Wzór nazwy:", "en": "Name pattern:"},
    "grid.tmpl.add_token": {"pl": "+ Token", "en": "+ Token"},
    "grid.tmpl.restore": {"pl": "Przywróć domyślny", "en": "Restore default"},
    "grid.tmpl.empty_hint": {
        "pl": "pusty wzór — dodaj token przyciskiem „+ Token",
        "en": "empty pattern — add a token with the „+ Token” button",
    },

    # --- RenameBar (polityka wsadu + echo daty) ---
    "grid.rename.source": {"pl": "Źródło:", "en": "Source:"},
    "grid.rename.src_filename": {"pl": "nazwa pliku", "en": "file name"},
    "grid.rename.offset": {"pl": "Offset:", "en": "Offset:"},
    "grid.rename.fallback": {"pl": "Fallback na drugie źródło", "en": "Fallback to the other source"},
    "grid.rename.align": {
        "pl": "Wyrównaj do drugiego źródła", "en": "Align to the other source",
    },
    "grid.rename.align_to": {"pl": "Wyrównaj do {other}: {off} h", "en": "Align to {other}: {off} h"},
    "grid.rename.other_fname": {"pl": "czasu z nazw", "en": "time from names"},
    "grid.rename.align_tip": {"pl": "surowa mediana Δ = {median} h", "en": "raw median Δ = {median} h"},
    "grid.rename.align_tip_spread": {"pl": " · rozrzut {spread} h", "en": " · spread {spread} h"},
    "grid.echo.dateobs": {"pl": "DATE-OBS: {ts}", "en": "DATE-OBS: {ts}"},
    "grid.echo.dateobs_none": {"pl": "DATE-OBS: (brak)", "en": "DATE-OBS: (none)"},
    "grid.echo.fname_time": {"pl": "czas z nazwy: {ts}", "en": "time from name: {ts}"},
    "grid.echo.fname_none": {"pl": "czas z nazwy: (brak)", "en": "time from name: (none)"},
    "grid.echo.delta_none": {"pl": "Δ = —", "en": "Δ = —"},
    "grid.echo.no_time_src": {"pl": "brak źródła czasu", "en": "no time source"},
    "grid.echo.delta_subhour": {"pl": "Δ niepełnogodzinna!", "en": "Δ not whole-hour!"},
    "grid.echo.delta": {"pl": "Δ (hdr−nazwa) = {d} h", "en": "Δ (hdr−name) = {d} h"},
    "grid.echo.batch": {
        "pl": "Wsad: {n} klatek ({both} z obu źródeł)",
        "en": "Batch: {n} frames ({both} from both sources)",
    },
    "grid.echo.batch_stats": {
        "pl": "mediana Δ = {med} h · rozrzut {spread} h",
        "en": "median Δ = {med} h · spread {spread} h",
    },
    "grid.echo.no_time_batch": {
        "pl": "brak źródła czasu w wsadzie", "en": "no time source in batch",
    },

    # --- SelectionBar (pasek zbioru) ---
    "grid.sel.proj_tip": {
        "pl": "Materializuj bieżącą perspektywę w drzewo linków/kopii (WBPP feed)",
        "en": "Materialize the current perspective into a tree of links/copies (WBPP feed)",
    },
    "grid.sel.proj_tip_empty": {"pl": "brak klatek w zbiorze", "en": "no frames in the set"},
    "grid.sel.project": {"pl": "Wydaj na stół…", "en": "Serve to table…"},
    "grid.sel.clear_set": {"pl": "× Wyczyść zbiór", "en": "× Clear set"},
    "grid.sel.clear_tip": {
        "pl": "Zdejmij facety i filtr zaawansowany (perspektywa zostaje)",
        "en": "Remove facets and advanced filter (the perspective stays)",
    },
    "grid.sel.fix_headers": {"pl": "Popraw nagłówki…", "en": "Fix headers…"},
    "grid.sel.tidy_names": {"pl": "Uporządkuj nazwy plików…", "en": "Tidy file names…"},
    "grid.sel.save_view": {"pl": "★ Zapisz widok", "en": "★ Save view"},

    # --- StagingDrawer (poczekalnia zmian) ---
    "grid.drawer.empty": {"pl": "Poczekalnia zmian — pusta", "en": "Changes waiting room — empty"},
    "grid.drawer.pending": {"pl": "{n} zmian oczekuje", "en": "{n} changes pending"},
    "grid.drawer.pending_rename": {
        "pl": "{n} zmian nazw oczekuje", "en": "{n} name changes pending",
    },
    "grid.action.cancel": {"pl": "Anuluj", "en": "Cancel"},
    "grid.action.commit": {"pl": "Zatwierdź", "en": "Commit"},
    "grid.action.reject": {"pl": "Odrzuć", "en": "Discard"},
    "grid.action.undo": {"pl": "Cofnij", "en": "Undo"},

    # --- górny pasek: perspektywa/grupowanie ---
    "grid.top.perspective": {"pl": "Perspektywa:", "en": "Perspective:"},
    "grid.top.group_by": {"pl": "Grupuj wg:", "en": "Group by:"},
    "grid.top.no_group": {"pl": "(bez grupowania)", "en": "(no grouping)"},

    # --- perspektywy: zapis/nieznana ---
    "grid.persp.unknown": {"pl": "Nieznana perspektywa: {name}", "en": "Unknown perspective: {name}"},
    "grid.persp.save_title": {"pl": "Zapisz perspektywę", "en": "Save perspective"},
    "grid.persp.save_prompt": {"pl": "Nazwa:", "en": "Name:"},
    "grid.persp.saved": {"pl": "Zapisano perspektywę „{name}”", "en": "Perspective „{name}” saved"},

    # --- projekcja / kryteria zbioru ---
    "grid.proj.no_frames": {
        "pl": "Projekcja: brak widocznych klatek", "en": "Projection: no visible frames",
    },
    "grid.criteria.only_dups": {"pl": "tylko duplikaty", "en": "only duplicates"},
    "grid.criteria.only_review": {"pl": "tylko do przeglądu", "en": "only to review"},
    "grid.criteria.only_vanished": {"pl": "tylko zniknięte", "en": "only vanished"},
    "grid.status.loaded": {
        "pl": "Grid: {frames}, {cols} kolumn-keywordów",
        "en": "Grid: {frames}, {cols} keyword columns",
    },

    # --- writeback (commit/undo/reject; podsumowania składane) ---
    "grid.wb.applied": {"pl": "{n} zapisanych", "en": "{n} applied"},
    "grid.wb.renamed": {"pl": "{n} przemianowanych", "en": "{n} renamed"},
    "grid.wb.restored": {"pl": "{n} przywróconych", "en": "{n} restored"},
    "grid.wb.blocked": {"pl": "{n} zablokowanych", "en": "{n} blocked"},
    "grid.wb.errors": {"pl": "{n} błędów", "en": "{n} errors"},
    "grid.wb.skipped": {"pl": "{n} pominiętych", "en": "{n} skipped"},
    "grid.wb.detail_sep": {"pl": " — {detail}", "en": " — {detail}"},
    "grid.wb.interrupted": {
        "pl": " — przerwano, {n} do dokończenia", "en": " — interrupted, {n} to finish",
    },
    "grid.wb.commit_id": {"pl": "  (commit {id})", "en": "  (commit {id})"},
    "grid.wb.run_id": {"pl": "  (run {id})", "en": "  (run {id})"},
    "grid.wb.committed_label": {
        "pl": "Zatwierdzono: {n} (commit {id})", "en": "Committed: {n} (commit {id})",
    },
    "grid.rename.renamed_label": {"pl": "Przemianowano: {n}", "en": "Renamed: {n}"},
    "grid.wb.error": {"pl": "BŁĄD: {msg}", "en": "ERROR: {msg}"},
    "grid.wb.failed": {
        "pl": "Writeback „{op}” nie powiódł się: {msg}",
        "en": "Writeback „{op}” failed: {msg}",
    },
    "grid.wb.cancelling": {"pl": "Anulowanie… (po bieżącym pliku)", "en": "Cancelling… (after current file)"},
    "grid.wb.status": {"pl": "Writeback: {summary}", "en": "Writeback: {summary}"},
    "grid.wb.undo_status": {"pl": "Undo: {msg}", "en": "Undo: {msg}"},
    "grid.wb.rejected": {"pl": "Odrzucono {n} zmian", "en": "Discarded {n} changes"},
    "grid.rename.staging_busy_tip": {
        "pl": "staging nazw w toku ({n} zmian)", "en": "name staging in progress ({n} changes)",
    },
    "grid.rename.no_count": {
        "pl": "Rename: brak klatek do policzenia", "en": "Rename: no frames to count",
    },
    "grid.rename.error": {"pl": "Rename: {e}", "en": "Rename: {e}"},
    "grid.rename.preview_result": {
        "pl": "Podgląd nazw: {t} do zmiany, {s} pominięto (cel: {target})",
        "en": "Name preview: {t} to change, {s} skipped (target: {target})",
    },
    "grid.rename.no_frames": {"pl": "Rename: brak klatek", "en": "Rename: no frames"},
    "grid.rename.staging_busy": {
        "pl": "Rename: najpierw zatwierdź/odrzuć staging makra",
        "en": "Rename: first commit/discard the macro staging",
    },
    "grid.rename.staged": {
        "pl": "Do stagingu nazw: {t} zmian, {s} pominięto (cel: {target})",
        "en": "To name staging: {t} changes, {s} skipped (target: {target})",
    },
    "grid.rename.preview_cleared": {"pl": "Podgląd nazw wyczyszczony", "en": "Name preview cleared"},
    "grid.rename.status_summary": {"pl": "Rename: {summary}", "en": "Rename: {summary}"},
    "grid.rename.undo_status": {"pl": "Undo nazw: {msg}", "en": "Undo names: {msg}"},
    "grid.rename.rejected": {
        "pl": "Odrzucono {n} zmian nazw", "en": "Discarded {n} name changes",
    },
}
