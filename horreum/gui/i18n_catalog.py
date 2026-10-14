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

    # --- stanowisko Z RĘKI (0027): okno „Wskaż stanowisko…" i przyciski widoku stanowisk ---
    "obshand.btn_assign": {"pl": "Wskaż stanowisko…", "en": "Assign site…"},
    # AR-74: przycisk niesie licznik - ta sama liczba co wiersz Porządków „Klatki bez stanowiska".
    "obshand.btn_assign_n": {"pl": "Wskaż stanowisko… ({n})", "en": "Assign site… ({n})"},
    "obshand.btn_assign_tip": {
        "pl": "Klatki bez GPS i bez wskazania ręki. Dark i bias (z masterami) są poza liczbą - "
              "nie widzą nieba, więc stanowisko ich nie opisuje.",
        "en": "Frames without GPS and without a hand assignment. Darks and biases (with masters) "
              "are not counted - they see no sky, so a site does not describe them."},
    "obshand.btn_change": {"pl": "Zmień wskazanie…", "en": "Change assignment…"},
    "obshand.btn_clear": {"pl": "Cofnij wskazanie…", "en": "Undo assignment…"},
    "obshand.title": {"pl": "Wskaż stanowisko klatkom bez GPS",
                      "en": "Assign a site to frames without GPS"},
    "obshand.title_change": {"pl": "Zmień stanowisko wskazane ręką",
                             "en": "Change a hand-assigned site"},
    "obshand.title_clear": {"pl": "Cofnij wskazanie stanowiska", "en": "Undo a site assignment"},
    # Nagłówki okien niosą GOTOWE frazy liczebne (`dlg.n_*` przez `t_plural`) - dwie liczby w jednym
    # zdaniu nie dają się odmienić jednym `t_plural`, a „1 folderów” kłamie gramatyką.
    "obshand.head": {
        "pl": "{folders} · {frames} bez stanowiska (nagłówek bez GPS). Zaznacz foldery zdjęte "
              "w jednym miejscu i wskaż stanowisko.",
        "en": "{folders} · {frames} without a site (no GPS in the header). Check the folders "
              "shot at one place and pick the site."},
    "obshand.head_change": {
        "pl": "{folders} · {frames} ze stanowiskiem wskazanym ręką. Zaznacz te, którym zmieniasz "
              "stanowisko.",
        "en": "{folders} · {frames} with a hand-assigned site. Check the ones whose site you "
              "change."},
    "obshand.head_clear": {
        "pl": "{folders} · {frames} ze stanowiskiem wskazanym ręką. Cofnięcie oddaje oś "
              "automatowi: klatka z GPS wróci do stanowiska z pliku przy najbliższym „Rozwiąż”, "
              "klatka bez GPS - do „bez stanowiska”.",
        "en": "{folders} · {frames} with a hand-assigned site. Undo hands the axis back to "
              "automation: a frame with GPS returns to its file's site on the next “Resolve”, "
              "a frame without GPS returns to “no site”."},
    "obshand.check_all": {"pl": "Zaznacz / odznacz wszystkie", "en": "Check / uncheck all"},
    "handlist.filter_ph": {"pl": "Filtruj listę - fragment ścieżki, np. LMC 2024 (Enter zaznacza)",
                           "en": "Filter the list - part of the path, e.g. LMC 2024 (Enter checks)"},
    "handlist.filter_tip": {
        "pl": "Każde słowo musi wystąpić w wierszu, wielkość liter bez znaczenia. Zapis obejmuje "
              "tylko wiersze widoczne i zaznaczone; ukryte zachowują zaznaczenie i wracają po "
              "wyczyszczeniu frazy. Enter zaznacza kolejny pasujący wiersz; "
              "„Zaznacz / odznacz wszystkie” działa na wierszach widocznych.",
        "en": "Every word must appear in the row, case-insensitive. Saving covers only visible "
              "checked rows; hidden rows keep their check and return when the filter is cleared. "
              "Enter checks the next matching row; “Check / uncheck all” acts on visible rows."},
    "handlist.filter_empty": {"pl": "Żaden wiersz nie pasuje do „{q}”.",
                              "en": "No row matches “{q}”."},
    "obshand.item": {"pl": "{folder}  ·  {frames}  ·  {kinds}",
                     "en": "{folder}  ·  {frames}  ·  {kinds}"},
    "dlg.n_folders": {
        "pl": {"one": "{n} folder", "few": "{n} foldery", "many": "{n} folderów"},
        "en": {"one": "{n} folder", "other": "{n} folders"}},
    "dlg.n_groups": {
        "pl": {"one": "{n} grupa", "few": "{n} grupy", "many": "{n} grup"},
        "en": {"one": "{n} group", "other": "{n} groups"}},
    "dlg.n_frames": {
        "pl": {"one": "{n} klatka", "few": "{n} klatki", "many": "{n} klatek"},
        "en": {"one": "{n} frame", "other": "{n} frames"}},
    "obshand.kind_count": {"pl": "{kind} ({n})", "en": "{kind} ({n})"},
    "obshand.now_set": {"pl": "dziś: {site}", "en": "now: {site}"},
    "obshand.now_mixed": {"pl": "dziś: różne stanowiska", "en": "now: several sites"},
    "obshand.no_folder": {"pl": "(bez kopii na dysku)", "en": "(no copy on disk)"},
    "obshand.pick_existing": {"pl": "Istniejące stanowisko", "en": "Existing site"},
    "obshand.pick_new": {"pl": "Nowe ze współrzędnych (stopnie dziesiętne)",
                         "en": "New from coordinates (decimal degrees)"},
    "obshand.pick_site": {"pl": "- wybierz stanowisko -", "en": "- pick a site -"},
    "obshand.lat": {"pl": "Szerokość (-90..90, południe ujemna):",
                    "en": "Latitude (-90..90, south negative):"},
    "obshand.lon": {"pl": "Długość (-180..180, zachód ujemna):",
                    "en": "Longitude (-180..180, west negative):"},
    "obshand.name": {"pl": "Nazwa (opcjonalnie):", "en": "Name (optional):"},
    "obshand.elev": {"pl": "Wysokość m n.p.m. (opcjonalnie):", "en": "Elevation in m (optional):"},
    "obshand.near_note": {
        "pl": "Punkt w promieniu {km} km od istniejącego stanowiska trafi w nie - bez duplikatu.",
        "en": "A point within {km} km of an existing site joins it - no duplicate."},
    "obshand.assign_btn": {"pl": "Przypisz zaznaczone ({n})", "en": "Assign selected ({n})"},
    "obshand.clear_btn": {"pl": "Cofnij zaznaczone ({n})", "en": "Undo selected ({n})"},
    "obshand.cancel_btn": {"pl": "Anuluj", "en": "Cancel"},
    "obshand.err_nothing": {"pl": "Nic nie zaznaczono - zero zapisu.",
                            "en": "Nothing checked - nothing written."},
    "obshand.err_no_site": {"pl": "Wybierz stanowisko z listy albo podaj współrzędne.",
                            "en": "Pick a site from the list or enter coordinates."},
    "obshand.err_coords": {"pl": "Współrzędne odrzucone: {e}", "en": "Coordinates rejected: {e}"},
    "obshand.nothing": {"pl": "Brak klatek bez stanowiska - każda ma GPS albo wskazanie ręki "
                              "(dark i bias stanowiska nie potrzebują).",
                        "en": "No frames without a site - each has GPS or a hand assignment "
                              "(darks and biases need no site)."},
    "obshand.nothing_hand": {"pl": "Brak klatek ze stanowiskiem wskazanym ręką.",
                             "en": "No frames with a hand-assigned site."},
    # Zdania po geście: odmiana przez `t_plural` na liczbie wszystkich klatek gestu („z 1 klatki",
    # „z 5 klatek"), człony pominięć i skutków WYŁĄCZNIE przy liczbie > 0 (wzorzec
    # `grid.zdanie_pominiec`); kropkę stawia wołający na końcu całego zdania.
    "obshand.assigned_report": {
        "pl": {"one": "Stanowisko {site}: przypisano {assigned} z {n} klatki",
               "few": "Stanowisko {site}: przypisano {assigned} z {n} klatek",
               "many": "Stanowisko {site}: przypisano {assigned} z {n} klatek"},
        "en": {"one": "Site {site}: assigned {assigned} of {n} frame",
               "other": "Site {site}: assigned {assigned} of {n} frames"}},
    "obshand.created": {"pl": " · nowe stanowisko", "en": " · new site"},
    "obshand.skip_occupied": {
        "pl": {"one": " · {n} klatka miała już stanowisko", "few": " · {n} klatki miały już stanowisko",
               "many": " · {n} klatek miało już stanowisko"},
        "en": {"one": " · {n} frame already had a site", "other": " · {n} frames already had a site"}},
    "obshand.skip_unchanged": {
        "pl": {"one": " · {n} klatka bez zmiany", "few": " · {n} klatki bez zmiany",
               "many": " · {n} klatek bez zmiany"},
        "en": {"one": " · {n} frame unchanged", "other": " · {n} frames unchanged"}},
    "obshand.name_kept": {"pl": " · stanowisko ma już nazwę „{name}” - zostaje",
                          "en": " · the site already has the name “{name}” - it stays"},
    "obshand.elev_set": {"pl": " · wysokość {elev} m dopisana do stanowiska",
                         "en": " · elevation {elev} m added to the site"},
    "obshand.elev_kept": {"pl": " · stanowisko ma już wysokość {elev} m - zostaje",
                          "en": " · the site already has elevation {elev} m - it stays"},
    "obshand.undo_hint": {"pl": ". Odwrót: ten widok, „Cofnij wskazanie…”",
                          "en": ". To revert: this view, “Undo assignment…”"},
    "obshand.cleared_report": {
        "pl": {"one": "Cofnięto wskazanie stanowiska: {cleared} z {n} klatki",
               "few": "Cofnięto wskazanie stanowiska: {cleared} z {n} klatek",
               "many": "Cofnięto wskazanie stanowiska: {cleared} z {n} klatek"},
        "en": {"one": "Site assignment undone: {cleared} of {n} frame",
               "other": "Site assignment undone: {cleared} of {n} frames"}},
    "obshand.clear_not_hand": {
        "pl": {"one": " · {n} klatka ma stanowisko z GPS, nie z ręki",
               "few": " · {n} klatki mają stanowisko z GPS, nie z ręki",
               "many": " · {n} klatek ma stanowisko z GPS, nie z ręki"},
        "en": {"one": " · {n} frame has its site from GPS, not by hand",
               "other": " · {n} frames have their site from GPS, not by hand"}},
    "obshand.clear_nothing": {
        "pl": {"one": " · {n} klatka bez stanowiska", "few": " · {n} klatki bez stanowiska",
               "many": " · {n} klatek bez stanowiska"},
        "en": {"one": " · {n} frame without a site", "other": " · {n} frames without a site"}},
    "obshand.clear_gps": {
        "pl": {"one": ". {n} klatka z GPS wróci do stanowiska z pliku po „Rozwiąż”",
               "few": ". {n} klatki z GPS wrócą do stanowiska z pliku po „Rozwiąż”",
               "many": ". {n} klatek z GPS wróci do stanowiska z pliku po „Rozwiąż”"},
        "en": {"one": ". {n} frame with GPS returns to its file's site after “Resolve”",
               "other": ". {n} frames with GPS return to their file's site after “Resolve”"}},
    "obshand.clear_no_site": {
        "pl": {"one": ". {n} klatka wróciła do „bez stanowiska”",
               "few": ". {n} klatki wróciły do „bez stanowiska”",
               "many": ". {n} klatek wróciło do „bez stanowiska”"},
        "en": {"one": ". {n} frame went back to “no site”",
               "other": ". {n} frames went back to “no site”"}},
    "obshand.site_empty": {"pl": ". Stanowisko {site} zostaje bez klatek",
                           "en": ". Site {site} stays without frames"},
    "obshand.site_label": {"pl": "#{id} {name}", "en": "#{id} {name}"},
    "pipeline.fmt.resolve_obs_hand": {
        "pl": "  ⚠ stanowisko z ręki inne niż GPS nagłówka: {n} klatek (ręka zostaje)",
        "en": "  ⚠ hand-assigned site differs from header GPS: {n} frames (hand stays)"},
    "axis.obs.already_merged": {"pl": "Już scalone.", "en": "Already merged."},
    "axis.obs.already_canonical": {"pl": "Już kanoniczne.", "en": "Already canonical."},

    # --- oś OBIEKT + filtr + kolejka przeglądu ---
    "object.col.name": {"pl": "Obiekt", "en": "Object"},
    # STANY KOMÓRKI „Obiekt" (R-S3-4) — kolumna mówi, CZYM jest to, co pokazuje. Każdy tooltip
    # niesie RECEPTĘ, nie samą diagnozę: gdzie się TĘ nazwę poprawia. Wspólne „to nie jest
    # przypisany obiekt" byłoby prawdziwe i nie dawałoby nikomu drogi dalej.
    # Klucze składa `grid._OBJECT_STATE_TIPS`; parytet z tą mapą pinuje bramka w `test_i18n`.
    # NAGROBEK MA TRZY ZDANIA, NIE JEDNO (FC-1) - bo komórka pokazuje raz obiekt ZDJĘTY RĘKĄ
    # (pamięć z migracji 0017), a raz nazwę z NAGŁÓWKA (nagrobek bez pamięci, baza-dawca sprzed
    # tej migracji). Wspólne zdanie byłoby w drugim przypadku fałszem o werdykcie ręki, a to
    # dokładnie ten fałsz, który paczka odwracalności miała usunąć. Wybiera `grid._cleared_tip`;
    # w `_OBJECT_STATE_TIPS` (bramka parytetu stanów) stoi wariant BAZOWY.
    "grid.cell.object_cleared_tip": {
        "pl": "Przypisanie COFNIĘTE ręką - pokazana nazwa to obiekt, który ręka ZDJĘŁA (baza go "
              "pamięta), a nie obiekt przypisany; przebieg tej klatki nie tknie. "
              "Wróć do niego: Obiekt ▾ → „Przywróć cofnięte przypisanie”.",
        "en": "Assignment UNDONE by hand - the name shown is the object your hand REMOVED (the "
              "database remembers it), not an assigned object; the resolver will skip this frame. "
              "Go back: Object ▾ → “Restore undone assignment”."},
    "grid.cell.object_cleared_raw_tip": {
        "pl": "Przypisanie COFNIĘTE ręką - pokazana nazwa to obiekt, który ręka ZDJĘŁA (baza go "
              "pamięta), a nie obiekt przypisany; przebieg tej klatki nie tknie. "
              "Nagłówek pliku niesie: {raw}. "
              "Wróć do niego: Obiekt ▾ → „Przywróć cofnięte przypisanie”.",
        "en": "Assignment UNDONE by hand - the name shown is the object your hand REMOVED (the "
              "database remembers it), not an assigned object; the resolver will skip this frame. "
              "The file header carries: {raw}. "
              "Go back: Object ▾ → “Restore undone assignment”."},
    "grid.cell.object_cleared_nomem_tip": {
        "pl": "Przypisanie COFNIĘTE ręką, BEZ zapamiętanego obiektu (nagrobek z bazy sprzed "
              "migracji pamięci) - pokazana nazwa, jeśli jest, pochodzi z nagłówka pliku, nie "
              "z werdyktu ręki. „Przywróć cofnięte przypisanie” nie ma tu czego odtworzyć; "
              "obiekt wskazuje się ręką (Obiekt ▾ → „Przypisz obiekt…”).",
        "en": "Assignment UNDONE by hand, with NO remembered object (a tombstone from a database "
              "predating the memory migration) - the name shown, if any, comes from the file "
              "header, not from your verdict. “Restore undone assignment” has nothing to restore "
              "here; point at the object by hand (Object ▾ → “Assign object…”)."},
    "grid.cell.object_kind_tip": {
        "pl": "Kalibracja nie ma obiektu z DEFINICJI — to surowa nazwa z nagłówka pliku "
              "(kamera wpisuje tam cel sesji także darkom i flatom), a nie przypisany obiekt.",
        "en": "Calibration has no object BY DEFINITION — this is the raw name from the file "
              "header (the camera writes the session target into darks and flats too), not an "
              "assigned object."},
    "grid.cell.object_raw_tip": {
        "pl": "Nazwa z nagłówka pliku, NIEROZPOZNANA — obiekt nie jest przypisany. "
              "Poprawia się ją w PLIKU (Porządki → „Napraw nagłówek…”) albo wskazuje ręką "
              "(Obiekt ▾ → „Przypisz obiekt…”).",
        "en": "Name from the file header, UNRECOGNISED — no object is assigned. Fix it in the "
              "FILE (Tasks → “Fix header…”) or point at it by hand (Object ▾ → “Assign "
              "object…”)."},
    "grid.cell.object_hint_tip": {
        "pl": "PODPOWIEDŹ Z FOLDERU, nie nazwa obiektu — tyle mówi ścieżka gotowego obrazu. "
              "Nazwy plików generuje WBPP i nie niosą tożsamości; nadaj ją "
              "(Obiekt ▾ → „Przypisz obiekt…”).",
        "en": "HINT FROM THE FOLDER, not an object name — this is what the finished image's path "
              "says. WBPP generates the file names and they carry no identity; assign one "
              "(Object ▾ → “Assign object…”)."},
    # Stos w drzewie STACKS: tu folder NIESIE nazwę (segment po STACKS), a szczebel ścieżki ma dla
    # niej propozycję - zdanie o WBPP byłoby nieprawdą i odsyłało do drogi dłuższej niż istniejąca.
    "grid.cell.object_hint_stacks_tip": {
        "pl": "PODPOWIEDŹ Z FOLDERU OBIEKTU, jeszcze nie przypisany obiekt - stos leży w drzewie "
              "STACKS, więc nazwę niesie folder zaraz po STACKS. Gdy program tę nazwę zna, czeka "
              "ona na Twoje potwierdzenie: Porządki → Klatki bez obiektu → „…z tego ze ścieżki” → "
              "Zatwierdź ze ścieżki…; gdy nie zna, nadaj ją (Obiekt ▾ → „Przypisz obiekt…”).",
        "en": "HINT FROM THE OBJECT FOLDER, not yet an assigned object - the stack sits in the "
              "STACKS tree, so the folder right after STACKS carries the name. If the program "
              "knows that name, it awaits your confirmation: Housekeeping → Frames without object "
              "→ “…of which from path” → Confirm from path…; if not, assign one "
              "(Object ▾ → “Assign object…”)."},
    "object.col.catalog": {"pl": "Katalog", "en": "Catalog"},
    "object.col.hours": {"pl": "Godziny", "en": "Hours"},
    "frame.col.sha": {"pl": "sha1 danych", "en": "data sha1"},
    "frame.col.telescope": {"pl": "Teleskop", "en": "Telescope"},
    "frame.col.camera": {"pl": "Kamera", "en": "Camera"},
    "frame.col.filter": {"pl": "Filtr", "en": "Filter"},
    "frame.col.date": {"pl": "Data", "en": "Date"},
    "frame.col.present": {"pl": "Obecny", "en": "Present"},
    "copy.col.volume": {"pl": "Wolumen", "en": "Volume"},
    "copy.col.present": {"pl": "Obecna", "en": "Present"},
    "copy.col.marked": {"pl": "Oznaczona", "en": "Marked"},
    "copy.col.reason": {"pl": "Powód", "en": "Reason"},
    "copy.no_reason": {"pl": "—", "en": "—"},
    # P4-2: rodzaj awarii stoi PRZED diagnozą, bo to on mówi, gdzie szukać winy - samo „kopia
    # nieczytelna" oskarżało plik i wysyłało na dysk po zdrowy plik, gdy zawiódł dostęp.
    "copy.reason_io": {"pl": "dysk/dostęp: {reason}", "en": "disk/access: {reason}"},
    "copy.reason_parse": {"pl": "nagłówek nie przechodzi parsera: {reason}",
                          "en": "header fails the parser: {reason}"},
    # P4-2: trzeci rodzaj nie jest faktem o pliku - zawiódł zapis albo brama po naszej stronie.
    "copy.reason_db": {"pl": "baza danych: {reason}", "en": "database: {reason}"},
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
    # Wygaszony przycisk tłumaczy się SAM (wiz #12): trzy drogi naprawy bezimiennej klatki (karta
    # w pliku / ręka / żadna) były w kolejce niewidoczne — widać było jedną i drugą wygaszoną.
    "object.assign_tip": {
        "pl": "Wskaż, co ta nazwa z nagłówka oznacza — alias zapamięta ją na przyszłość",
        "en": "Say what this header name means — the alias remembers it for the future",
    },
    # RAW: droga naprawy jest JEDNA i to ta — format nie ma karty, więc „Napraw nagłówek…" nigdy
    # się tu nie odezwie. Tooltip mówi, czego okno oczekuje, bo grupa nie ma nazwy do zacytowania.
    "object.assign_tip_raw": {
        "pl": "Format nie ma karty OBJECT — nazwij te klatki ręką (np. LMC albo NGC 7635)",
        "en": "The format has no OBJECT card — name these frames by hand (e.g. LMC or NGC 7635)",
    },
    "object.assign_tip_card": {
        "pl": "Dla tego kubełka naprawą jest karta OBJECT w PLIKU — użyj „Napraw nagłówek…”",
        "en": "For this bucket the fix is the OBJECT card in the FILE — use “Repair header…”",
    },
    "object.assign_tip_pick": {
        "pl": "Zaznacz najpierw pozycję kolejki przeglądu",
        "en": "Select a review queue entry first",
    },
    "object.frames_of_object": {"pl": "Klatki obiektu", "en": "Object frames"},
    "object.frames_review": {"pl": "Klatki do przeglądu: {name}", "en": "Frames to review: {name}"},
    "object.empty_status": {
        "pl": "Brak obiektów dla tego filtra — zeskanuj i rozwiąż (horreum resolve) lub zmień filtr.",
        "en": "No objects for this filter — scan and resolve (horreum resolve) or change the filter.",
    },
    # WIERSZ KOLEJKI JEST TRÓJCZŁONOWY (R-S3-3, `rows.TwoPartDelegate`): nazwa | liczba | adnotacja.
    # Do R-S3-10 liczba jechała w tekście jedną formą („NGC7023 · 1 klatek") — stąd `t_plural`.
    "object.review_count": {
        "pl": {"one": "{n} klatka", "few": "{n} klatki", "many": "{n} klatek"},
        "en": {"one": "{n} frame", "other": "{n} frames"},
    },
    # CZŁON „cofnięte ręką" (S3/R-S2b-1). Klatka, której zdjąłeś nazwę, wraca do TEGO SAMEGO
    # kubełka — bo przeglądu wymaga tak samo jak nietknięta — ale wraca z INNĄ historią: to Twój
    # werdykt, nie brak zeznania. Bez tego rozróżnienia pozycja wyglądała identycznie, a akcja
    # ręki po cichu jej nie tykała (klinga chroni werdykt przed przypadkowym wskrzeszeniem).
    #
    # DO R-S3-3 RÓŻNICOWNIKIEM BYŁY DWA SZARE SŁOWA NA KOŃCU OBCINANEJ LINII — bez ikony, bez
    # koloru, a lista obcina poziomo, więc przy wąskim oknie ginęły pierwsze. Odtąd znacznik `↺`
    # stoi na POCZĄTKU wiersza (widoczny zanim cokolwiek się utnie), a te dwa słowa jadą CZŁONEM
    # TRZECIM delegata — własną kolumną przy prawej krawędzi, ze stałym brzegiem.
    "object.review_cleared_mark": {"pl": "cofnięte ręką", "en": "undone by hand"},
    "object.nameless_raw_cleared_line": {
        "pl": "— bez nazwy, format bez karty (RAW)",
        "en": "— nameless, format has no card (RAW)"},
    "object.frames_review_cleared": {
        "pl": "Klatki z cofniętym przypisaniem: {name}",
        "en": "Frames with the assignment undone: {name}"},
    "object.frames_nameless_raw_cleared": {
        "pl": "Klatki z cofniętym przypisaniem — format bez karty OBJECT ({n})",
        "en": "Frames with the assignment undone — format has no OBJECT card ({n})",
    },
    # Tooltip mówi wprost, że to DRUGI gest człowieka — bo tylko taki gasi nagrobek. Bez tego
    # zdania user nie wie, czym ten przycisk różni się od tego samego przycisku kubełek wyżej.
    "object.assign_tip_cleared": {
        "pl": "Sam cofnąłeś tu nazwę — przypisanie ręką nadpisze ten werdykt",
        "en": "You undid the name here — assigning by hand overrides that verdict",
    },
    # WIERSZE KUBEŁKÓW SĄ TRÓJCZŁONOWE JAK RESZTA KOLEJKI (zarzut 2 bramki pakietu): etykieta
    # niesie SAMĄ nazwę, liczba idzie w człon drugi (`object.review_count`, odmieniona), a droga
    # naprawy i „cofnięte ręką" w człon trzeci. Do tej poprawki liczba siedziała w członie
    # PIERWSZYM - czyli w tym, który delegat ELIDUJE - a lista straciła poziomy scroll, więc
    # jedyna treść tych wierszy ucinała się bez drogi powrotu.
    "object.nameless_line": {"pl": "— bez nazwy w nagłówku",
                             "en": "— no name in header"},
    # R-S3-1: te dwa wiersze to lustro pary RAW-owej wyżej. Klatka trafia tu, gdy nazwę ZDJĄŁEŚ,
    # a nagłówek o obiekcie milczy (nazwa przyszła z regionu\ścieżki\xref) — werdykt człowieka,
    # nie brak wiedzy. Człon dopisany po myślniku, jak w obu wierszach, które go już miały.
    "object.nameless_cleared_line": {
        "pl": "— bez nazwy w nagłówku", "en": "— no name in header"},
    "object.nameless_stacks_cleared_line": {
        "pl": "— bez nazwy, gotowe stosy", "en": "— nameless, finished stacks"},
    # RAW/DSLR: format nie zna karty OBJECT, więc te klatki czekają na RĘCZNE przypisanie —
    # dlatego wiersz mówi DROGĘ naprawy, nie sam objaw (kubełek wyżej otwiera okno zapisu karty,
    # ten nie ma czego otworzyć).
    "object.nameless_raw_line": {"pl": "— bez nazwy, format bez karty (RAW)",
                                 "en": "— nameless, format has no card (RAW)"},
    # Droga naprawy = ADNOTACJA (człon trzeci), bo tym te kubełki się od siebie różnią.
    "object.mark_by_hand": {"pl": "do przypisania ręcznie", "en": "assign by hand"},
    "object.mark_by_card": {"pl": "do naprawy kartą", "en": "repair with a card"},
    "object.mark_to_confirm": {"pl": "do potwierdzenia", "en": "to confirm"},
    # Gotowe stosy: od D-0802-1 droga naprawy jest ta sama co u lightów (karta OBJECT do pliku),
    # więc wiersz przestał zapowiadać read-only i nazywa POPULACJĘ — tym różni się od kubełka
    # wyżej, nie drogą.
    "object.nameless_stacks_line": {
        "pl": "— bez nazwy, gotowe stosy", "en": "— nameless, finished stacks"},
    # Ścieżka PROPONUJE (D-OW-2/B): wiersz stoi POD kubełkiem RAW, bo opisuje jego PODZBIÓR —
    # drogę wyjścia, nie nową populację. Dwie liczby, bo jednostką przeglądu jest NAZWA, a jednostką
    # skutku KLATKA; sama liczba klatek kazałaby userowi myśleć, że czeka go 707 decyzji.
    # Dwie liczby zostają RAZEM w członie drugim: jednostką przeglądu jest NAZWA, a jednostką
    # skutku KLATKA - rozdzielenie ich między człony kazałoby czytać wiersz od środka.
    "object.path_proposed_line": {
        "pl": "— …z tego ze ścieżki", "en": "— …of which from path"},
    # Odmiana przez `t_plural` po liczbie NAZW; człon klatek (`{frames}`) podaje wołający już
    # odmieniony (`object.review_count`) - „1 nazw / 1 klatek" czytało się jak błąd.
    "object.path_proposed_count": {
        "pl": {"one": "{n} nazwa / {frames}", "few": "{n} nazwy / {frames}",
               "many": "{n} nazw / {frames}"},
        "en": {"one": "{n} name / {frames}", "other": "{n} names / {frames}"}},
    "object.path_proposed_broken": {
        "pl": "— ze ścieżki: NIE POLICZONO · słownik obiektów własnych ma błąd "
              "(objects_own.json) — popraw plik i odśwież",
        "en": "— from path: NOT COUNTED · the own-objects dictionary has an error "
              "(objects_own.json) — fix the file and refresh"},
    "object.frames_path_proposed": {
        "pl": "Klatki z propozycją ze ścieżki ({n})", "en": "Frames proposed from path ({n})"},
    "object.confirm_path_btn": {"pl": "Zatwierdź ze ścieżki…", "en": "Confirm from path…"},
    "object.confirm_path_tip": {
        "pl": "Ścieżka proponuje nazwę — zapis następuje dopiero po Twoim potwierdzeniu",
        "en": "The path proposes a name — nothing is written until you confirm"},
    "object.confirm_path_tip_pick": {
        "pl": "Zaznacz w kolejce pozycję „…z tego ze ścieżki”",
        "en": "Select the “…of which from path” entry in the queue"},
    "path.title": {"pl": "Zatwierdź nazwy ze ścieżki", "en": "Confirm names from path"},
    # UI NIE KŁAMIE — i to zdanie jest tego probierzem, bo od S2b prawda się ZMIENIŁA. Do S2b
    # mówiło „powierzchnia cofania dochodzi w kolejnym kroku", co było wtedy faktem; po S2b ta sama
    # ostrożność stała się kłamstwem w drugą stronę — droga odwrotu ISTNIEJE i user ma o niej
    # wiedzieć, zanim zatwierdzi 707 klatek. Zdanie mówi więc, GDZIE jej szukać.
    # O3 krok 1 (2026-09-26): gest pisze też kartę `OBJECT` do PLIKÓW tam, gdzie plik na to
    # pozwala - dawne „zapis idzie do BAZY, nie do plików" stało się nieprawdą.
    # Liczby zdania odmieniają się przez `t_plural` (`path.head_count`, `grid.frames`) - „1 nazw ·
    # 1 klatek" czytało się jak błąd; reszta zdania jest wspólna dla każdej liczby.
    "path.head_count": {
        "pl": {"one": "{n} nazwa · {frames}", "few": "{n} nazwy · {frames}",
               "many": "{n} nazw · {frames}"},
        "en": {"one": "{n} name · {frames}", "other": "{n} names · {frames}"}},
    "path.head": {
        "pl": "{count}. Nazwa pochodzi z FOLDERU na pozycji obiektu; "
              "zapis idzie do BAZY, a tam, gdzie plik na to pozwala, także jako karta OBJECT "
              "do PLIKU - nagłówek i folder powiedzą to samo. Odznacz to, czego nie chcesz "
              "zapisać; zatwierdzone cofniesz w Zbiorach przez „Obiekt ▾ → Cofnij przypisanie”, "
              "karty - przyciskiem „Cofnij karty” do zamknięcia okna.",
        "en": "{count}. The name comes from the FOLDER at the object "
              "position; the write goes to the DATABASE and, where the file allows it, also as an "
              "OBJECT card into the FILE - the header and the folder will say the same. Uncheck "
              "whatever you do not want written; confirmed names can be undone in Frames via "
              "“Object ▾ → Undo assignment”, cards - with “Undo cards” until the window closes."},
    "path.card_item": {"pl": "do pliku: OBJECT = {value} · {n} z {total}",
                       "en": "into file: OBJECT = {value} · {n} of {total}"},
    "path.card_item_none": {"pl": "tylko baza - plik bez karty",
                            "en": "database only - no card in the file"},
    "path.cards_skipped_head": {
        "pl": "Bez karty w pliku, tylko potwierdzenie w bazie ({n}) - powód i liczba klatek:",
        "en": "No card in the file, database confirmation only ({n}) - reason and frame count:"},
    "path.cards_skipped_item": {"pl": "{reason}: {n}", "en": "{reason}: {n}"},
    "path.card_skip.invalid": {
        "pl": "wartość {value} łamie reguły karty FITS ({reason})",
        "en": "value {value} breaks the FITS card rules ({reason})"},
    "path.card_skip.no_roundtrip": {
        "pl": "nagłówek „{value}” nie wróciłby do kanonu {canon} - karta przeniosłaby klatkę",
        "en": "header „{value}” would not resolve back to canon {canon} - the card would move "
              "the frame"},
    "path.undo_cards_btn": {"pl": "Cofnij karty", "en": "Undo cards"},
    "path.cards_applied": {"pl": "karty OBJECT zapisane w plikach: {n}",
                           "en": "OBJECT cards written to files: {n}"},
    # Po „Cofnij karty" baza zostaje przy folderze, a pliki wracają bez karty - zdanie mówi to
    # i drogę powrotu (C2): „Zatwierdź" dopisze karty ponownie.
    "path.cards_restored_note": {
        "pl": " - klatki zostają nazwane z folderu (w bazie), pliki są bez karty; "
              "„Zatwierdź” dopisze karty ponownie.",
        "en": " - frames stay named from the folder (in the database), files have no card; "
              "„Confirm” writes the cards again."},
    # Straż zamknięcia okna w biegu zapisu do plików (C1, `WritebackRunner.refuse_close`).
    "wb.close_refused": {
        "pl": "Zapis do plików trwa - przerywam po bieżącym pliku. Okno zamkniesz, gdy zapis się "
              "zatrzyma i pokaże wynik.",
        "en": "Writing to files is in progress - stopping after the current file. You can close "
              "the window once the write stops and shows its result."},
    "wb.cancelled_note": {"pl": " - przerwano na żądanie", "en": " - stopped on request"},
    "path.item": {"pl": "{canon}  ·  {frames}", "en": "{canon}  ·  {frames}"},
    "path.new_badge": {"pl": "NOWA w bazie", "en": "NEW in the database"},
    "path.known_badge": {"pl": "kanon znany", "en": "canon known"},
    "path.confirm_btn": {"pl": "Zatwierdź wszystko", "en": "Confirm all"},
    "path.confirm_btn_n": {"pl": "Zatwierdź zaznaczone ({n})", "en": "Confirm selected ({n})"},
    "path.close_btn": {"pl": "Zamknij", "en": "Close"},
    "path.err.nothing": {"pl": "Nic nie zaznaczono — zero zapisu.",
                         "en": "Nothing selected — nothing written."},
    # R-S2b-13: zdanie nie ma już własnego ogona pominięć („N pominięte - zajęte między oknem
    # a zapisem" mówiło to samo o darku i o klatce zajętej w międzyczasie). Człony rozbicia
    # dokleja `grid.zdanie_pominiec` - te same, co w zdaniach Zbiorów - więc zdanie kończy się BEZ
    # KROPKI: „klatek. · kalibracja: 1" byłoby drugą gramatyką w jednym zdaniu.
    # `{n}` = pozycje, które przeszły klingę (nie zaznaczone: po odmowie reszta nie doszła).
    # `{of_total}` = `path.of_total` (dopełniacz po „z" odmieniony po wszystkich klatkach).
    "path.done": {
        "pl": {"one": "Zatwierdzono {n} nazwę · przypisano {assigned} {of_total}",
               "few": "Zatwierdzono {n} nazwy · przypisano {assigned} {of_total}",
               "many": "Zatwierdzono {n} nazw · przypisano {assigned} {of_total}"},
        "en": {"one": "Confirmed {n} name · assigned {assigned} {of_total}",
               "other": "Confirmed {n} names · assigned {assigned} {of_total}"}},
    "path.of_total": {
        "pl": {"one": "z {n} klatki", "few": "z {n} klatek", "many": "z {n} klatek"},
        "en": {"one": "of {n} frame", "other": "of {n} frames"}},
    "object.unreadable_line": {"pl": "— kopie nieczytelne", "en": "— unreadable copies"},
    # KUBEŁEK OSI SPRZĘTU (R1) — do tej pory był POŁOWĄ wiersza informacyjnego z notą
    # „rozwiązywanie w przygotowaniu". Nota była uczciwa i dlatego musiała zniknąć razem z drogą:
    # od R1 gest istnieje, więc wiersz prowadzi do klatek i niesie własną akcję. Jednostką pozycji
    # jest KLATKA (tak liczy `resolver.review_state`), a jednostką GESTU folder × kamera — dlatego
    # zdanie mówi „klatek", a okno pokazuje foldery.
    "object.config_review_line": {
        "pl": "— bez zestawu (teleskop × kamera)",
        "en": "— without a setup (telescope × camera)"},
    "object.config_review_info_empty": {
        "pl": "Ten kubełek jest pusty — każda klatka na osi teleskopu ma zestaw. Wiersz zapali "
              "się, gdy pojawi się plik, który o sprzęcie nie zeznaje (typowo RAW z lustrzanki).",
        "en": "This bucket is empty — every frame on the telescope axis has a setup. The row will "
              "light up once a file appears that does not testify about hardware (typically DSLR RAW)."},
    "object.frames_config_review": {
        "pl": "Klatki bez zestawu ({n})", "en": "Frames without a setup ({n})"},
    # DRUGA POŁOWA kubełka sprzętu — droga POWROTNA dla pomyłki ręki (bramka pakietu 3a, zarzut 1).
    # Bez niej klatka po geście wypadała z kubełka i nie było jak jej już dotknąć: automat odmawia
    # (guard lepkości), a okno otwiera się z kubełka, w którym jej nie ma.
    "object.config_by_hand_line": {
        "pl": "— zestaw wskazany ręką", "en": "— setup indicated by hand"},
    "object.frames_config_by_hand": {
        "pl": "Klatki z zestawem wskazanym ręką ({n})",
        "en": "Frames with a setup indicated by hand ({n})"},
    "object.set_config_tip_change": {
        "pl": "ZMIEŃ zestaw wskazany wcześniej ręką — zaznacz w oknie tylko te foldery, "
              "które mają się zmienić. Zapis idzie do BAZY.",
        "en": "CHANGE a setup you indicated earlier by hand — in the dialog check only the folders "
              "that should change. The write goes to the DATABASE."},
    "cfg.title_change": {"pl": "Zmień zestaw (teleskop × kamera)",
                         "en": "Change setup (telescope × camera)"},
    "cfg.head_change": {
        "pl": "{folders} · {frames} - wszystkie mają zestaw wskazany PRZEZ CIEBIE. "
              "Zaznacz tylko te, które chcesz zmienić: zapis NADPISZE poprzednie wskazanie. "
              "Wchodzą odznaczone, żeby jedna poprawka nie przestemplowała reszty.",
        "en": "{folders} · {frames} - all have a setup indicated BY YOU. Check only "
              "the ones you want to change: the write OVERWRITES the previous indication. They "
              "start unchecked so that one fix does not re-stamp the rest."},
    "cfg.now_set": {"pl": "dziś: {telescope}", "en": "now: {telescope}"},
    "object.set_config_btn": {"pl": "Przypisz zestaw…", "en": "Assign setup…"},
    "object.set_config_tip": {
        "pl": "Wskaż TELESKOP dla folderów, które o sprzęcie nie zeznają — kamerę bierzemy "
              "z klatki. Zapis idzie do BAZY, nie do plików (RAW jest read-only).",
        "en": "Point out the TELESCOPE for folders that do not testify about hardware — the camera "
              "comes from the frame. The write goes to the DATABASE, not the files (RAW is read-only)."},
    "object.set_config_tip_pick": {
        "pl": "Zaznacz w kolejce pozycję „bez zestawu (teleskop × kamera)”",
        "en": "Select the “without a setup (telescope × camera)” entry in the queue"},
    "object.review_info": {
        "pl": "— bez nagłówka  (rozwiązywanie w przygotowaniu)",
        "en": "— headerless  (resolution in preparation)",
    },
    # ---- okno „Przypisz zestaw…" (R1)
    "cfg.check_all": {"pl": "Zaznacz / odznacz wszystkie",
                      "en": "Check / uncheck all"},
    "cfg.title": {"pl": "Przypisz zestaw (teleskop × kamera)", "en": "Assign setup (telescope × camera)"},
    "cfg.head": {
        "pl": "{folders} · {frames}. Kamerę zna plik; wskazać trzeba TELESKOP. "
              "Jednostką jest FOLDER × KAMERA, bo jeden zestaw niesie dokładnie jedną kamerę. "
              "Zapis idzie do BAZY, nie do plików — RAW jest read-only.",
        "en": "{folders} · {frames}. The file knows the camera; the TELESCOPE is what "
              "you must point out. The unit is FOLDER × CAMERA, because one setup carries exactly "
              "one camera. The write goes to the DATABASE, not the files — RAW is read-only."},
    "cfg.item": {"pl": "{folder}  ·  {camera}  ·  {frames}",
                 "en": "{folder}  ·  {camera}  ·  {frames}"},
    "cfg.no_folder": {"pl": "(bez kopii na dysku)", "en": "(no copy on disk)"},
    "cfg.no_camera": {"pl": "(kamera nieznana)", "en": "(camera unknown)"},
    # RODZAJ ODBIEGAJĄCY OD ŚWIATŁA (R1-3) — człon pokazywany WYŁĄCZNIE przy odchyleniu, więc
    # zdanie nie musi tłumaczyć, czym jest `light`: na wszystkich pozostałych wierszach go nie ma.
    # Token rodzaju surowy, jak w facecie „Rodzaj" (`facet_kinds` oddaje `kind` bez tłumaczenia)
    # — jeden słownik nazw rodzajów, nie dwa.
    "cfg.item_kinds": {"pl": "  ·  rodzaj: {kinds}", "en": "  ·  kind: {kinds}"},
    "cfg.kind_count": {"pl": "{kind} ({n})", "en": "{kind} ({n})"},
    "cfg.header_says": {"pl": "nagłówek mówi: {telescop}", "en": "header says: {telescop}"},
    "cfg.header_silent": {"pl": "nagłówek milczy o sprzęcie", "en": "header is silent about hardware"},
    "cfg.telescope": {"pl": "Teleskop (Twoje wskazanie):", "en": "Telescope (your indication):"},
    "cfg.pick_telescope": {"pl": "— wybierz teleskop —", "en": "— pick a telescope —"},
    "cfg.park_badge": {"pl": "w parku", "en": "in park"},
    "cfg.assign_btn": {"pl": "Przypisz zaznaczone ({n})", "en": "Assign selected ({n})"},
    "cfg.cancel_btn": {"pl": "Anuluj", "en": "Cancel"},
    "cfg.err_nothing": {"pl": "Nic nie zaznaczono — zero zapisu.",
                        "en": "Nothing selected — nothing written."},
    "cfg.err_no_telescope": {"pl": "Wskaż teleskop — kamerę zna plik, tego nie zgadujemy.",
                             "en": "Point out a telescope — the file knows the camera, this we do not guess."},
    # Ostrzeżenie NAZYWA DROGĘ NAPRAWY, nie tylko odmowę (bramka pakietu 3a, zarzut 8): kubełek
    # złożony wyłącznie z klatek bez kamery dawał okno z wiecznie wygaszonym zatwierdzeniem i bez
    # słowa o tym, gdzie tę kamerę załatwić — a to inna oś (skan), nie ten gest.
    "cfg.no_camera_warning": {
        "pl": "{skipped}: bez kamery nie ma z czego złożyć zestawu. "
              "Kamera przychodzi z zeznania pliku (INSTRUME/XPIXSZ) — to osobna oś: napraw "
              "nagłówek albo przeskanuj ponownie, potem wróć tutaj.",
        "en": "{skipped}: without a camera there is nothing to build a setup from. "
              "The camera comes from the file's testimony (INSTRUME/XPIXSZ) — a separate axis: "
              "repair the header or re-scan, then come back here."},
    "cfg.no_camera_skipped": {
        "pl": {"one": "{n} klatka zostanie pominięta", "few": "{n} klatki zostaną pominięte",
               "many": "{n} klatek zostanie pominiętych"},
        "en": {"one": "{n} frame will be skipped", "other": "{n} frames will be skipped"}},
    # Zdanie gestu zestawu MÓWI GRAMATYKĄ OSI OBIEKTU (R-S2b-15): bez kropki, bo człony pominięć
    # dokleja `grid.zdanie_pominiec` z prefiksem `grid.sel.config_skip_`; odmienione przez `{n}` =
    # wszystkie klatki gestu („z 1 klatki", „z 5 klatek").
    "object.config_assigned_none": {
        "pl": "Zestaw {telescope}: nic nie przypisano",
        "en": "Setup {telescope}: nothing assigned"},
    "object.config_assigned_report": {
        "pl": {"one": "Przypisano zestaw {telescope} → {assigned} z {n} klatki",
               "few": "Przypisano zestaw {telescope} → {assigned} z {n} klatek",
               "many": "Przypisano zestaw {telescope} → {assigned} z {n} klatek"},
        "en": {"one": "Assigned setup {telescope} → {assigned} of {n} frame",
               "other": "Assigned setup {telescope} → {assigned} of {n} frames"}},
    # NASTĘPNY TAKT NAZWANY, nie domyślony (wzorzec taktu 3 z „Napraw nagłówek…"): oś sprzętu
    # działa natychmiast (facety, filtr), ale dobór rodowodu stosów czyta teleskop kandydata —
    # więc jeśli te klatki są materiałem gotowego obrazu, rodowód trzeba przeliczyć. Zdanie mówi
    # GDZIE; przycisku tu nie ma, bo na dzisiejszym archiwum nie miałby czego zmienić (wszystkie
    # 3367 wejść rodowodu to FITS-y), a obietnica bez skutku jest gorsza od wskazania drogi.
    # Kropka na CZELE: zamyka zdanie raportu, które kończy się bez niej (człony pominięć).
    "object.config_next_step": {
        "pl": ". Rodowód gotowych obrazów przelicz w Dostawie („Policz rodowód”), gdy te klatki "
              "są materiałem stosu.",
        "en": ". Recompute stack lineage in Delivery (“Compute lineage”) if these frames are stack "
              "material."},
    # --- człony pominięć gestu ZESTAWU (`repo.ConfigGesture.skipped_breakdown`, R-S2b-15) ---
    # Prefiks `grid.sel.config_skip_` + sufiks z rozbicia; frazy odmieniane przez liczbę klatek
    # (`zdanie_pominiec(odmiana=True)`). Zero nie jest drukowane - człon pojawia się, gdy jest powód.
    "grid.sel.config_skip_occupied": {
        "pl": {"one": " · {n} klatka miała już zestaw",
               "few": " · {n} klatki miały już zestaw",
               "many": " · {n} klatek miało już zestaw"},
        "en": {"one": " · {n} frame already had a setup",
               "other": " · {n} frames already had a setup"}},
    "grid.sel.config_skip_no_camera": {
        "pl": {"one": " · {n} klatka bez kamery",
               "few": " · {n} klatki bez kamery",
               "many": " · {n} klatek bez kamery"},
        "en": {"one": " · {n} frame without a camera",
               "other": " · {n} frames without a camera"}},
    "grid.sel.config_skip_kind": {
        "pl": {"one": " · {n} klatka kalibracyjna",
               "few": " · {n} klatki kalibracyjne",
               "many": " · {n} klatek kalibracyjnych"},
        "en": {"one": " · {n} calibration frame",
               "other": " · {n} calibration frames"}},
    "grid.sel.config_skip_unchanged": {
        "pl": {"one": " · {n} klatka bez zmiany",
               "few": " · {n} klatki bez zmiany",
               "many": " · {n} klatek bez zmiany"},
        "en": {"one": " · {n} frame unchanged",
               "other": " · {n} frames unchanged"}},
    # WYTŁUMACZENIA WIERSZY INFORMACYJNYCH (F-2) — tooltip + odpowiedź na klik. Każde mówi DWIE
    # rzeczy: czego wiersz jest opisem i dlaczego nie prowadzi dalej. Bez nich klik w wiersz nie
    # dawał żadnej reakcji, co dla użytkownika jest nieodróżnialne od zawieszenia aplikacji.
    "object.review_info_generic": {
        "pl": "To wiersz informacyjny — pokazuje liczbę, nie prowadzi do klatek.",
        "en": "This is an informational row — it shows a count, it does not lead to frames."},
    # Zdanie ZWĘŻONE w R1 z dwóch osi do jednej — bo oś sprzętu przestała być „w przygotowaniu"
    # i dostała własny wiersz z akcją. Zostaje wyłącznie klatka bez nagłówka: tu naprawą jest
    # ponowny odczyt pliku (skan), a nie decyzja w kolejce, więc wiersz nadal nie ma dokąd prowadzić.
    "object.review_info_why": {
        "pl": "Licznik INNEJ osi: klatek bez nagłówka (plik nieczytelny przy skanie). "
              "Tu nie ma dokąd prowadzić — naprawą jest ponowny odczyt pliku, nie decyzja w kolejce.",
        "en": "A counter for a DIFFERENT axis: headerless frames (the file was unreadable during "
              "the scan). There is nowhere to go from here — the fix is re-reading the file, not "
              "a decision in this queue."},
    "object.nameless_info_empty": {
        "pl": "Ten kubełek jest pusty — każda klatka z nagłówkiem ma nazwę obiektu. "
              "Wiersz zapali się i zacznie prowadzić do klatek, gdy pojawi się pierwsza bez niej.",
        "en": "This bucket is empty — every frame with a header has an object name. "
              "The row will light up and lead to frames once the first one appears without it."},
    "object.unreadable_info_empty": {
        "pl": "Żadna kopia nie jest oznaczona jako nieczytelna — nie ma czego pokazać.",
        "en": "No copy is marked unreadable — there is nothing to show."},
    # P4-2: rozbicie kubełka po RODZAJU awarii. Jednostką są KOPIE (nie klatki jak w liczniku
    # wiersza) i fraza mówi to wprost, bo tylko liczba kopii sumuje się do drążenia - klatka
    # z dwiema kopiami może mieć dwa rodzaje. „Baza" = błąd bazy po naszej stronie, nie fakt
    # o pliku. „Bez kodu awarii" = kopie oznaczone przed 0019 albo wyjątek bez kodu systemu,
    # którego nie dało się rozstrzygnąć. Fraza NIE brzmi „rodzaj nieznany": raport Dostawy stawia
    # to rozbicie w jednej linii z powodem „rodzaj nieznany" (`pipeline.reason.kind_unknown`), który
    # mówi o rodzaju KLATKI - dwa różne fakty jednym słowem czytały się jak jeden.
    "object.unreadable_kinds": {"pl": "kopie: {parts}", "en": "copies: {parts}"},
    "object.unreadable_kind_io": {"pl": "dysk/dostęp {n}", "en": "disk/access {n}"},
    "object.unreadable_kind_parse": {"pl": "nagłówek {n}", "en": "header {n}"},
    "object.unreadable_kind_db": {"pl": "baza {n}", "en": "database {n}"},
    "object.unreadable_kind_unknown": {"pl": "bez kodu awarii {n}", "en": "no failure code {n}"},
    "object.path_proposed_broken_info": {
        "pl": "Propozycji ze ścieżki NIE POLICZONO, bo słownik obiektów własnych "
              "(objects_own.json) ma błąd — wiersz nie udaje zera i nie prowadzi nigdzie, "
              "bo nie ma dokąd. Popraw plik i odśwież.",
        "en": "Path proposals were NOT COUNTED because the own-objects dictionary "
              "(objects_own.json) has an error — the row does not fake a zero and leads nowhere, "
              "because there is nowhere to lead. Fix the file and refresh."},
    "object.no_path": {"pl": "(brak ścieżki)", "en": "(no path)"},
    "object.unreadable_title": {"pl": "Kopie nieczytelne ({n})", "en": "Unreadable copies ({n})"},
    "object.no_location": {"pl": "(brak lokalizacji)", "en": "(no location)"},
    # R-S2b-13: bez kropki i bez własnego ogona pominięć - człony rozbicia dokleja
    # `grid.zdanie_pominiec`, ten sam dom, co zdań Zbiorów (powód przy `path.done`).
    "object.assigned_report": {
        "pl": {"one": "Przypisano {assigned} z {n} klatki → {canon}",
               "few": "Przypisano {assigned} z {n} klatek → {canon}",
               "many": "Przypisano {assigned} z {n} klatek → {canon}"},
        "en": {"one": "Assigned {assigned} of {n} frame → {canon}",
               "other": "Assigned {assigned} of {n} frames → {canon}"}},
    "object.assign_nothing": {
        "pl": "Nic nie zaznaczono w panelu klatek — zero zapisu.",
        "en": "Nothing selected in the frames panel — nothing written.",
    },
    "object.alias_no_alnum": {
        "pl": "Nazwa „{name}” nie ma znaków alfanumerycznych — nie może być zapamiętanym aliasem.",
        "en": "Name “{name}” has no alphanumeric characters - it cannot be a remembered alias.",
    },
    "object.frames_nameless": {
        "pl": "Klatki bez nazwy w nagłówku ({n})", "en": "Frames with no name in header ({n})",
    },
    "object.frames_nameless_raw": {
        "pl": "Klatki bez nazwy — format bez karty OBJECT ({n})",
        "en": "Frames with no name — format has no OBJECT card ({n})",
    },
    "object.frames_nameless_cleared": {
        "pl": "Klatki z cofniętym przypisaniem — bez nazwy w nagłówku ({n})",
        "en": "Frames with the assignment undone — no name in header ({n})",
    },
    "object.frames_nameless_stacks_cleared": {
        "pl": "Gotowe stosy z cofniętym przypisaniem ({n})",
        "en": "Finished stacks with the assignment undone ({n})",
    },
    "object.frames_nameless_stacks": {
        "pl": "Gotowe stosy bez nazwy w nagłówku ({n})",
        "en": "Finished stacks with no name in header ({n})",
    },

    # --- P-D: „Napraw nagłówek…" — karta OBJECT wraca do PLIKU (wariant C) ---
    "repair.open_btn": {"pl": "Napraw nagłówek…", "en": "Repair header…"},
    # TOOLTIPY TRZECIEGO PRZYCISKU KOLEJKI (R-S3-7) — do S3 miał pusty dla KAŻDEGO wiersza, jako
    # jedyny w rzędzie. Każdy wariant nazywa drogę WŁAŚCIWĄ dla zaznaczonego kubełka, zamiast
    # milczeć o tym, że w ogóle istnieje druga.
    "repair.tip": {
        "pl": "Dopisz kartę OBJECT do PLIKÓW tego kubełka — nazwa wraca do archiwum, "
              "nie tylko do bazy.",
        "en": "Add the OBJECT card to this bucket's FILES — the name goes back to the archive, "
              "not just to the database."},
    # R-S3-1: nad wierszem „cofnięte ręką" przycisk jest AKTYWNY, więc recepta musi powiedzieć,
    # co stanie się z werdyktem — inaczej user waha się, czy zapis go uszanuje, czy zdepcze.
    # Karta gasi nagrobek świadomie (`writeback.py:704-705`) i to jest jedyna droga, którą on gaśnie.
    "repair.tip_cleared": {
        "pl": "Tym klatkom nazwę zdjąłeś ręką — dopisanie karty OBJECT do PLIKÓW zastąpi "
              "ten werdykt nazwą, którą tu wpiszesz.",
        "en": "You undid the name on these frames — adding the OBJECT card to the FILES replaces "
              "that verdict with the name you enter here."},
    "repair.tip_raw": {
        "pl": "RAW nie ma karty OBJECT z natury formatu — tu drogą jest „Przypisz obiekt…” "
              "(ręka, zapis do bazy).",
        "en": "RAW has no OBJECT card by the nature of the format — here the way is “Assign "
              "object…” (by hand, written to the database)."},
    "repair.tip_named": {
        "pl": "Te klatki nazwę w nagłówku MAJĄ — jest tylko nierozpoznana. Drogą jest "
              "„Przypisz obiekt…” (ręka, zapis do bazy).",
        "en": "These frames DO have a name in the header — it is merely unrecognised. The way is "
              "“Assign object…” (by hand, written to the database)."},
    "repair.tip_path": {
        "pl": "Ten kubełek ma już gotową propozycję nazwy — drogą jest „Zatwierdź ze ścieżki…”, "
              "nie naprawa nagłówka.",
        "en": "This bucket already has a proposed name — the way is “Confirm from path…”, "
              "not header repair."},
    # P4-2: dawne „odzyskaj plik" OSKARŻAŁO plik także wtedy, gdy zawiódł dysk albo dostęp. Zdanie
    # kieruje do kolumny „Powód" i nazywa wszystkie trzy sytuacje - każda ma inną drogę naprawy.
    "repair.tip_unreadable": {
        "pl": "Tych kopii nie przeczytano, więc nie ma do czego dopisać karty. Kolumna „Powód” "
              "mówi, dlaczego: „dysk/dostęp” - plik może być zdrowy, sprawdź wolumin i uprawnienia; "
              "„nagłówek nie przechodzi parsera” - plik jest do zgłoszenia albo naprawy; "
              "„baza danych” - błąd po naszej stronie, powtórz skan, a jeśli wraca - zgłoś go.",
        "en": "These copies were not read, so there is nothing to add a card to. The “Reason” "
              "column says why: “disk/access” - the file may be healthy, check the volume and "
              "permissions; “header fails the parser” - the file needs reporting or repair; "
              "“database” - an error on our side, repeat the scan and report it if it comes back."},
    "repair.tip_busy": {
        "pl": "Druga powierzchnia właśnie pisze do plików — poczekaj na jej koniec.",
        "en": "Another surface is writing to files right now — wait for it to finish."},
    # R1: kubełek osi SPRZĘTU trafia pod ten przycisk tylko dlatego, że sąsiaduje w kolejce —
    # karta `OBJECT` nie ma z nim nic wspólnego, a milczenie odesłałoby usera w złe miejsce.
    "repair.tip_config": {
        "pl": "Ten kubełek nie jest o nazwie obiektu, a o SPRZĘCIE — drogą jest „Przypisz "
              "zestaw…”. Karty do RAW-a i tak nie dopiszemy: format jest read-only.",
        "en": "This bucket is not about the object name but about HARDWARE — the way is “Assign "
              "setup…”. A card cannot be written to RAW anyway: the format is read-only."},
    "repair.tip_pick": {
        "pl": "Zaznacz kubełek klatek bez nazwy w nagłówku — ta akcja pisze do PLIKÓW.",
        "en": "Select a bucket of frames with no name in the header — this action writes to FILES."},
    "repair.title": {"pl": "Napraw nagłówek — karta OBJECT", "en": "Repair header — OBJECT card"},
    "repair.head": {
        "pl": "{frames} klatek w {groups} folderach. Nazwa trafi do PLIKU (karta OBJECT); "
              "obiekt w bazie wypełni potem zwykły etap „Rozwiąż”.",
        "en": "{frames} frames in {groups} folders. The name goes into the FILE (OBJECT card); "
              "the object in the database is filled later by the regular „Resolve” stage.",
    },
    # Grupa „Napraw nagłówek…”: etykieta od folderu obiektu (`RepairHeaderDialog._etykieta_grupy`),
    # liczba odmieniona.
    "repair.group": {
        "pl": {"one": "{folder}  ·  {n} klatka", "few": "{folder}  ·  {n} klatki",
               "many": "{folder}  ·  {n} klatek"},
        "en": {"one": "{folder}  ·  {n} frame", "other": "{folder}  ·  {n} frames"}},
    "repair.no_proposal": {
        "pl": "brak zgodnej propozycji ze ścieżki — wpisz oznaczenie",
        "en": "no matching proposal from the path — type a designation",
    },
    "repair.preview": {"pl": "do pliku: OBJECT = {value}", "en": "into file: OBJECT = {value}"},
    "repair.preview_none": {"pl": "—", "en": "—"},
    "repair.skipped_head": {
        "pl": "Pominięte ({n}) — powód przy każdej:", "en": "Skipped ({n}) — reason for each:",
    },
    "repair.save_btn": {"pl": "Zapisz karty", "en": "Write cards"},
    "repair.save_btn_n": {"pl": "Zapisz karty ({n})", "en": "Write cards ({n})"},
    "repair.resolve_btn": {"pl": "Rozwiąż teraz", "en": "Resolve now"},
    "repair.close_btn": {"pl": "Zamknij", "en": "Close"},
    "repair.nothing": {
        "pl": "Brak klatek bez nazwy w nagłówku.", "en": "No frames without a name in the header.",
    },
    "repair.skip.gone": {
        "pl": "klatka zniknęła z bazy między odczytem a otwarciem okna",
        "en": "frame disappeared from the database between the read and opening the window",
    },
    "repair.err.empty": {"pl": "pusto — wpisz oznaczenie", "en": "empty — type a designation"},
    "repair.err.ascii": {
        "pl": "„{text}” ma znaki spoza drukowalnego ASCII - nagłówek FITS ich nie przyjmie",
        "en": "„{text}” has characters outside printable ASCII - a FITS header will not take them",
    },
    "repair.err.too_long": {
        "pl": "za długie ({n} znaków, limit {max})", "en": "too long ({n} characters, limit {max})",
    },
    "repair.err.unresolvable": {
        "pl": "„{text}” nie jest oznaczeniem katalogowym ani znaną nazwą — po zapisie klatka "
              "zostałaby bez obiektu",
        "en": "„{text}” is neither a catalog designation nor a known name — after writing, the "
              "frame would still have no object",
    },
    "repair.err.group": {"pl": "{folder}: {reason}", "en": "{folder}: {reason}"},
    "repair.err.nothing": {
        "pl": "Żadna grupa nie jest zaznaczona.", "en": "No group is selected.",
    },
    "repair.err.all_skipped": {
        "pl": "Nic do zapisu — wszystkie klatki pominięte. {reason}",
        "en": "Nothing to write — all frames skipped. {reason}",
    },
    "repair.err.no_host": {
        "pl": "Ten widok nie ma skąd uruchomić etapu — użyj „Rozwiąż” w Dostawie.",
        "en": "This view cannot start the stage — use „Resolve” in Delivery.",
    },

    # --- dialog „Przypisz obiekt" ---
    "assign.title": {"pl": "Przypisz obiekt", "en": "Assign object"},
    "assign.group_head": {
        "pl": {"one": "Grupa „{name}” — {n} klatka.", "few": "Grupa „{name}” — {n} klatki.",
               "many": "Grupa „{name}” — {n} klatek."},
        "en": {"one": "Group “{name}” - {n} frame.", "other": "Group “{name}” - {n} frames."},
    },
    # Grupa BEZ zeznania (kubełek RAW, S4): nagłówek nie ma nazwy do zacytowania. Obietnicy
    # „alias zostanie zapamiętany" tu NIE MA i to jest zamierzone — dla nazwy z gramatyki
    # katalogowej klucz aliasu nie powstaje, więc zdanie byłoby nieprawdziwe w najczęstszym geście.
    "assign.group_head_nameless": {
        "pl": {"one": "{n} klatka bez nazwy w metadanych (format bez karty OBJECT).",
               "few": "{n} klatki bez nazwy w metadanych (format bez karty OBJECT).",
               "many": "{n} klatek bez nazwy w metadanych (format bez karty OBJECT)."},
        "en": {"one": "{n} frame with no name in metadata (format has no OBJECT card).",
               "other": "{n} frames with no name in metadata (format has no OBJECT card)."},
    },
    # ZAZNACZENIE z paska Zbiorów (S2b) — trzecie wejście tego okna i JEDYNE, które pyta
    # o nadpisanie cudzej nazwy. Zdanie grupy RAW („bez nazwy w metadanych, format bez karty
    # OBJECT") było tu podwójną nieprawdą: klatki nazwę mają (ze ścieżki), a bywają FITS-ami
    # z kartą. Liczba = ile gest REALNIE ruszy, nie ile zaznaczono.
    "assign.selection_head": {
        "pl": {"one": "Zaznaczenie: {n} klatka do nazwania.",
               "few": "Zaznaczenie: {n} klatki do nazwania.",
               "many": "Zaznaczenie: {n} klatek do nazwania."},
        "en": {"one": "Selection: {n} frame to name.", "other": "Selection: {n} frames to name."},
    },
    "assign.selection_overwrite": {
        "pl": {"one": "{n} z nich ma już nazwę ze ścieżki — zostanie nadpisana.",
               "few": "{n} z nich mają już nazwę ze ścieżki — zostanie nadpisana.",
               "many": "{n} z nich ma już nazwę ze ścieżki — zostanie nadpisana."},
        "en": {"one": "{n} of them already has a name from the path — it will be overwritten.",
               "other": "{n} of them already have a name from the path — it will be overwritten."},
    },
    # OSTRZEŻENIE NA DRODZE KLIKNIĘCIA, nie w tooltipie (wizytacja S3): zapis na nagrobku gasi
    # WŁASNY WERDYKT usera, a okno o tym milczało — jedyne zdanie na ten temat wisiało w tooltipie
    # przycisku, którego klikający wprost z wiersza nigdy nie zobaczy.
    "assign.cleared_warning": {
        "pl": {"one": "{n} z nich sam cofnąłeś — ta nazwa zastąpi Twój wcześniejszy werdykt.",
               "few": "{n} z nich sam cofnąłeś — ta nazwa zastąpi Twój wcześniejszy werdykt.",
               "many": "{n} z nich sam cofnąłeś — ta nazwa zastąpi Twój wcześniejszy werdykt."},
        "en": {"one": "{n} of them you undid yourself — this name replaces your earlier verdict.",
               "other": "{n} of them you undid yourself — this name replaces your earlier verdict."},
    },
    # Reszta zaznaczenia ZOSTAJE nietknięta i user ma to wiedzieć PRZED zapisem, a nie z komunikatu
    # po nim: kalibracja i klatki z nagłówka/regionu są chronione, więc różnica między „zaznaczyłem
    # 80" a „zapisze się 30" nie jest awarią, tylko regułą.
    "assign.selection_skip": {
        "pl": {"one": "{n} klatka zaznaczenia zostaje nietknięta (kalibracja albo nazwa z pliku).",
               "few": "{n} klatki zaznaczenia zostają nietknięte (kalibracja albo nazwa z pliku).",
               "many": "{n} klatek zaznaczenia zostaje nietkniętych (kalibracja albo nazwa z pliku)."},
        "en": {"one": "{n} selected frame stays untouched (calibration or a name from the file).",
               "other": "{n} selected frames stay untouched (calibration or a name from the file)."},
    },
    "assign.cancel_btn": {"pl": "Anuluj", "en": "Cancel"},
    "assign.alias_remembered": {
        "pl": "Alias zostanie zapamiętany: nowe klatki z tą nazwą przypisze resolver.",
        "en": "The alias will be remembered: the resolver will assign new frames with this name.",
    },
    # Nazwa spoza katalogów (słownik obiektów własnych): kolumna „Katalog" zostaje PUSTA i to jest
    # stan poprawny. Nota mówi to przed zapisem, żeby pusta komórka nie czytała się jak zgubione pole.
    "assign.own_object_note": {
        "pl": "„{canon}” to obiekt własny — spoza katalogów, więc kolumna „Katalog” zostanie pusta.",
        "en": "“{canon}” is an own object - outside the catalogs, so the “Catalog” column stays empty.",
    },
    "assign.catalog_note": {
        "pl": "Ta nazwa rozwiązuje się katalogowo — katalog bije alias: nowe klatki "
              "z tą nazwą przypisze nagłówek, zapamiętany alias dotyczy tej grupy.",
        "en": "This name resolves via the catalog — the catalog beats the alias: the header "
              "will assign new frames with this name, the remembered alias applies to this group.",
    },
    "assign.existing_object": {"pl": "Istniejący obiekt:", "en": "Existing object:"},
    "assign.pick_object": {"pl": "— wybierz obiekt —", "en": "— pick object —"},
    # Szukajka listy obiektów (2026-09-26): user grzebiący w nazwach MUSI widzieć aliasy, a lista
    # ma się dać zawęzić po każdej nazwie obiektu, nie tylko po kanonie (`M106` znajduje NGC4258).
    "assign.search_placeholder": {
        "pl": "Szukaj na liście po kanonie albo aliasie, np. M106",
        "en": "Search the list by canon or alias, e.g. M106",
    },
    # Stan pusty szukajki mówi to w miejscu wyboru - inaczej combo z samym placeholderem nie
    # odróżnia „fraza za wąska" od „biblioteka pusta" (wzorzec listwy facetów, R-S3-5).
    "assign.search_empty": {
        "pl": "(żaden obiekt nie pasuje do „{text}”)",
        "en": "(no object matches “{text}”)",
    },
    # Pusty wynik szukajki PROWADZI do pola nazwy (wizytacja: user utknął przy „M 44”, którego
    # biblioteka nie ma) - wpisana fraza przechodzi do pola niżej, a zdanie mówi, gdzie jest.
    "assign.search_moved": {
        "pl": "Nie ma go na liście - wpisana nazwa przeszła do pola niżej.",
        "en": "Not on the list - the typed name moved to the field below.",
    },
    "assign.search_to_field": {
        "pl": "Nie ma go na liście - nazwę spoza listy wpisz w polu niżej.",
        "en": "Not on the list - type a name from outside the list in the field below.",
    },
    # Przycisk akcji przy nazwie, która ZAŁOŻY obiekt: `{action}` = napis wołającego
    # („Przypisz N klatek”, w wybieraku „Dalej - podgląd…”).
    "assign.create_btn": {"pl": "Załóż {canon} · {action}", "en": "Create {canon} · {action}"},
    # Kanon spoza bazy: zapis ZAŁOŻY obiekt - mówione przed kliknięciem, przy zdaniu na żywo.
    "assign.creates_object": {
        "pl": " · nowy obiekt: zapis założy go w bazie",
        "en": " · new object: saving creates it in the database",
    },
    # AR-135: wybór z listy starej tożsamości pary katalogowej idzie do celu pary.
    "assign.xref_redirect": {
        "pl": "{old} to dziś {new} (para katalogowa) - klatki pójdą do {new}",
        "en": "{old} is now {new} (catalog pair) - the frames go to {new}",
    },
    # Zdanie na żywo pod polem nazwy: co wpisano → jaki kanon zapisze Horreum → jaka forma stanie
    # w nagłówku (`catalog.header_form`). Mówi to PRZED kliknięciem „Przypisz".
    "assign.canon_preview": {
        "pl": "{text} → {canon} · w nagłówku: {header}",
        "en": "{text} → {canon} · in the header: {header}",
    },
    "assign.canon_preview_tip": {
        "pl": "Kanon Horreum (bez spacji) trafia do bazy i do nazw folderów; forma ze spacją "
              "to zapis nazwy obiektu w nagłówku pliku (karta OBJECT).",
        "en": "The Horreum canon (no space) goes to the database and to folder names; the form "
              "with a space is how the object name is written in the file header (OBJECT card).",
    },
    # Od S4 pole przyjmuje KAŻDĄ nazwę, którą rozpozna przebieg (oznaczenie katalogowe, nazwa
    # potoczna, słownik obiektów własnych, nazwa nauczona aliasem) — etykieta mówiąca „oznaczenie
    # katalogowe" kłamałaby o regule i odstraszała od jedynej drogi dla `LMC`.
    # AR-98: pole przyjmuje KAŻDE oznaczenie, które przebieg rozpozna - także obiektu już
    # obecnego w bibliotece - więc etykieta nie obiecuje NOWEGO obiektu.
    "assign.new_designation": {
        "pl": "albo wpisz oznaczenie (wypełnione nadpisuje wybór z listy):",
        "en": "or type a designation (if filled, it overrides the list selection):",
    },
    "assign.designation_placeholder": {"pl": "np. IC 1795 albo LMC", "en": "e.g. IC 1795 or LMC"},
    "assign.accept_btn": {
        "pl": {"one": "Przypisz {n} klatkę", "few": "Przypisz {n} klatki",
               "many": "Przypisz {n} klatek"},
        "en": {"one": "Assign {n} frame", "other": "Assign {n} frames"},
    },
    # Komunikat MUSI mówić o regule, która realnie odrzuciła nazwę: od S4 bramką jest cała drabina
    # (`resolver.name_resolves`), nie sama gramatyka katalogowa. Dawne „nie rozpoznaję oznaczenia
    # katalogowego" kłamałoby o przyczynie dla nazwy potocznej i dla wpisu słownika.
    "assign.unknown_name": {
        "pl": "Nie rozpoznaję nazwy „{text}” — resolver nie umie jej rozwiązać. "
              "Podaj oznaczenie katalogowe, nazwę potoczną albo nazwę ze słownika obiektów własnych.",
        "en": "Unrecognized name “{text}” - the resolver cannot resolve it. "
              "Enter a catalog designation, a common name, or a name from the own-objects dictionary.",
    },
    # Słownik obiektów własnych jest plikiem CZŁOWIEKA — literówka w nim ma zostać ZGŁOSZONA, nie
    # wywalić okno tracebackiem. Bliźniak `object.path_proposed_broken` po stronie kolejki.
    "assign.dictionary_broken": {
        "pl": "Słownik obiektów własnych ma błąd (objects_own.json) — popraw plik, żeby nazwy "
              "dały się rozpoznać.",
        "en": "The own-objects dictionary has an error (objects_own.json) — fix the file so names "
              "can be resolved.",
    },
    "assign.pick_or_designate": {
        "pl": "Wybierz istniejący obiekt albo podaj nazwę.",
        "en": "Pick an existing object or enter a name.",
    },
    "assign.alias_conflict": {
        "pl": "Alias dla tej nazwy wskazuje już obiekt „{target}” — wybierz go z listy.",
        "en": "The alias for this name already points to object “{target}” - pick it from the list.",
    },

    # --- MainWindow: menu, nawigacja, dialogi plików ---
    "menu.file": {"pl": "&Plik", "en": "&File"},
    "menu.open_db": {"pl": "Otwórz bazę…", "en": "Open database…"},
    "menu.new_db": {"pl": "Nowa baza…", "en": "New database…"},
    "menu.work_root": {"pl": "Folder roboczy WBPP…", "en": "WBPP working folder…"},
    "status.work_root_set": {
        "pl": "Folder roboczy: {path} - powstanie przy pierwszym wydaniu; stąd okno żniw "
              "bierze wyniki WBPP",
        "en": "Working folder: {path} - created at the first release; the harvest window "
              "takes WBPP results from here",
    },
    # Zdanie po żniwach ze stosami: rodowód z historii pliku, liczony per stos. Stos, któremu zapis
    # się nie udał, zostaje z rodowodem okna czasu - paskowi wolno to powiedzieć tylko wprost.
    "status.harvest_lineage": {
        "pl": {"one": "rodowód: {n} stos z historii żniw",
               "few": "rodowód: {n} stosy z historii żniw",
               "many": "rodowód: {n} stosów z historii żniw"},
        "en": {"one": "lineage: {n} stack from harvest history",
               "other": "lineage: {n} stacks from harvest history"},
    },
    "status.harvest_lineage_lost": {
        "pl": "rodowód dokładny stosów ({n}) NIE zapisany - Dostawa nie doszła do końca; folderu wydania nie "
              "kasuj, otwórz ponownie „Wciągnij z WBPP…” i „Zamknij i przyjmij do archiwum”",
        "en": "exact lineage of the stacks ({n}) NOT recorded - Intake did not finish; keep the release folder, "
              "reopen \"Take in from WBPP…\" and \"Close and receive into the archive\"",
    },
    "status.harvest_lineage_window": {
        "pl": {"one": "{n} stos zostaje z rodowodem okna czasu",
               "few": "{n} stosy zostają z rodowodem okna czasu",
               "many": "{n} stosów zostaje z rodowodem okna czasu"},
        "en": {"one": "{n} stack keeps its time-window lineage",
               "other": "{n} stacks keep their time-window lineage"},
    },
    # Łańcuch nie postawił stosowi integracji, więc rodowodu nie ma wcale (to nie jest rodowód okna).
    "status.harvest_lineage_none": {
        "pl": {"one": "{n} stos bez rodowodu - Dostawa nie ujęła go jako stosu; uruchom „Przyjmij nowe” na archiwum",
               "few": "{n} stosy bez rodowodu - Dostawa nie ujęła ich jako stosów; uruchom „Przyjmij nowe” na archiwum",
               "many": "{n} stosów bez rodowodu - Dostawa nie ujęła ich jako stosów; uruchom „Przyjmij nowe” na archiwum"},
        "en": {"one": "{n} stack without lineage - Intake did not take it in as a stack; run Receive new on the archive",
               "other": "{n} stacks without lineage - Intake did not take them in as stacks; run Receive new on the archive"},
    },
    # Obiekt stosu wobec obiektu wydania po żniwach (AR-103): zdanie mówi, CO się nie zgadza, a przycisk
    # recepty na pasku - co zrobi gest. `pair` i `none` niosą kanony z bazy, nie z nagłówka.
    "app.release_object.other": {
        "pl": {"one": "{n} stos ma inny obiekt niż wydanie ({pary})",
               "few": "{n} stosy mają inny obiekt niż wydanie ({pary})",
               "many": "{n} stosów ma inny obiekt niż wydanie ({pary})"},
        "en": {"one": "{n} stack has a different object than the release ({pary})",
               "other": "{n} stacks have a different object than the release ({pary})"},
    },
    "app.release_object.pair": {"pl": "stos: {stack}, wydanie: {release}",
                                "en": "stack: {stack}, release: {release}"},
    "app.release_object.none": {
        "pl": {"one": "{n} stos bez obiektu, a wydanie mówi {release}",
               "few": "{n} stosy bez obiektu, a wydanie mówi {release}",
               "many": "{n} stosów bez obiektu, a wydanie mówi {release}"},
        "en": {"one": "{n} stack has no object, the release says {release}",
               "other": "{n} stacks have no object, the release says {release}"},
    },
    "app.release_object.assign": {"pl": "Przypisz obiekt wydania", "en": "Assign release object"},
    "app.release_object.assigned": {
        "pl": {"one": "Obiekt wydania przypisany ręką: {n} stos ({canons})",
               "few": "Obiekt wydania przypisany ręką: {n} stosy ({canons})",
               "many": "Obiekt wydania przypisany ręką: {n} stosów ({canons})"},
        "en": {"one": "Release object assigned by hand: {n} stack ({canons})",
               "other": "Release object assigned by hand: {n} stacks ({canons})"},
    },
    "app.release_object.already": {
        "pl": {"one": "{n} stos ma już obiekt wydania",
               "few": "{n} stosy mają już obiekt wydania",
               "many": "{n} stosów ma już obiekt wydania"},
        "en": {"one": "{n} stack already has the release object",
               "other": "{n} stacks already have the release object"},
    },
    "app.release_object.drift": {
        "pl": {"one": "{n} stos pominięty - jego obiekt zmienił się od żniw, nic nie zapisano",
               "few": "{n} stosy pominięte - ich obiekt zmienił się od żniw, nic nie zapisano",
               "many": "{n} stosów pominiętych - ich obiekt zmienił się od żniw, nic nie zapisano"},
        "en": {"one": "{n} stack skipped - its object changed since the harvest, nothing saved",
               "other": "{n} stacks skipped - their object changed since the harvest, nothing saved"},
    },
    "app.release_object.undo": {"pl": "Cofnij", "en": "Undo"},
    "app.release_object.unknown": {
        "pl": {"one": "{n} stos bez porównania - obiektu wydania {release} nie ma w tej bazie",
               "few": "{n} stosy bez porównania - obiektu wydania {release} nie ma w tej bazie",
               "many": "{n} stosów bez porównania - obiektu wydania {release} nie ma w tej bazie"},
        "en": {"one": "{n} stack not compared - the release object {release} is not in this database",
               "other": "{n} stacks not compared - the release object {release} is not in this database"},
    },
    # Cofnięcie mówi, DO CZEGO stos wrócił (`StackObjectChange.before`) - człony sklejane w `undone`.
    "app.release_object.undone": {"pl": "Cofnięto: {czlony}", "en": "Undone: {czlony}"},
    "app.release_object.restored": {
        "pl": {"one": "{n} stos wrócił do poprzedniego obiektu",
               "few": "{n} stosy wróciły do poprzedniego obiektu",
               "many": "{n} stosów wróciło do poprzedniego obiektu"},
        "en": {"one": "{n} stack is back to its previous object",
               "other": "{n} stacks are back to their previous object"},
    },
    "app.release_object.restored_none": {
        "pl": {"one": "{n} stos znów bez obiektu",
               "few": "{n} stosy znów bez obiektu",
               "many": "{n} stosów znów bez obiektu"},
        "en": {"one": "{n} stack has no object again",
               "other": "{n} stacks have no object again"},
    },
    "app.release_object.restored_cleared": {
        "pl": {"one": "{n} stos znów bez obiektu z decyzji ręki",
               "few": "{n} stosy znów bez obiektu z decyzji ręki",
               "many": "{n} stosów znów bez obiektu z decyzji ręki"},
        "en": {"one": "{n} stack is again without an object by hand decision",
               "other": "{n} stacks are again without an object by hand decision"},
    },
    "app.release_object.undo_drift": {
        "pl": {"one": "{n} stos bez cofnięcia - jego obiekt zmienił się po geście",
               "few": "{n} stosy bez cofnięcia - ich obiekt zmienił się po geście",
               "many": "{n} stosów bez cofnięcia - ich obiekt zmienił się po geście"},
        "en": {"one": "{n} stack not undone - its object changed after the gesture",
               "other": "{n} stacks not undone - their object changed after the gesture"},
    },
    "menu.view": {"pl": "&Widok", "en": "&View"},
    "menu.theme.dark": {"pl": "Ciemny", "en": "Dark"},
    "menu.theme.light": {"pl": "Jasny", "en": "Light"},
    "nav.dostawa": {"pl": "Dostawa", "en": "Intake"},
    # Wiersz klasycznej prezentacji strony zbiorów; ta sama nazwa pada w podpowiedziach zadań
    # Porządków („Klik prowadzi do: …"), więc mówi dokładnie to, co stoi w sidebarze.
    "nav.zbiory": {"pl": "Zbiory klasyczne", "en": "Classic collections"},
    "nav.porzadki": {"pl": "Porządki", "en": "Housekeeping"},
    "nav.porzadki_count": {"pl": "Porządki ({n})", "en": "Housekeeping ({n})"},
    "nav.planer": {"pl": "Planer", "en": "Planner"},
    "nav.dom": {"pl": "Dom", "en": "Home"},
    "nav.znajdz": {"pl": "Znajdź", "en": "Find"},
    # Nagłówek sekcji - wiersz nieklikalny nad miejscami, które Dom zbiera pod „Więcej…".
    "nav.wiecej": {"pl": "Więcej", "en": "More"},

    # --- DOM (`home.py`): czasowniki, „Co mam", teczki, ostatni gest ---------------------------
    "home.title": {"pl": "Co chcesz zrobić?", "en": "What do you want to do?"},
    "home.tile.receive": {"pl": "Przyjmij", "en": "Receive"},
    "home.tile.receive_tip": {
        "pl": "Uruchamia dostawę i pokazuje raport: co przyszło i czego nie rozpoznałem",
        "en": "Starts the intake and shows the report: what came in and what was not recognized"},
    "home.tile.find": {"pl": "Znajdź", "en": "Find"},
    "home.tile.find_tip": {
        "pl": "Obiekt, noc, filtr, teleskop, zestaw albo tekst uwag - jedno pole i Enter",
        "en": "Object, night, filter, telescope, set or note text - one field and Enter"},
    "home.tile.release": {"pl": "Wydaj do WBPP", "en": "Release to WBPP"},
    "home.tile.release_tip": {
        "pl": "Teczka obiektu: lighty, mastery i surowe flaty jako linki dla WBPP",
        "en": "Object folder: lights, masters and raw flats as links for WBPP"},
    "home.tile.release_busy": {
        "pl": "Wydanie czeka na koniec przebiegu Dostawy - etap przelicza kalibrację i rodowód",
        "en": "Release waits for the intake run to finish - it recomputes calibration and lineage"},
    "home.tile.fix": {"pl": "Popraw", "en": "Fix"},
    "home.tile.fix_count": {"pl": "Popraw · {n}", "en": "Fix · {n}"},
    "home.tile.fix_tip": {
        "pl": "Zadania w Porządkach - ta sama liczba, co przy Porządkach w sidebarze",
        "en": "Tasks in Housekeeping - the same count as next to Housekeeping in the sidebar"},
    "home.more": {"pl": "Więcej…", "en": "More…"},
    "home.more.planner": {"pl": "Planer", "en": "Planner"},
    "home.more.sites": {"pl": "Mapa stanowisk", "en": "Site map"},
    "home.more.rename": {"pl": "Nazwy plików…", "en": "File names…"},
    "home.more.macro": {"pl": "Makra nagłówków…", "en": "Header macros…"},
    "home.more.perspectives": {"pl": "Perspektywy", "en": "Perspectives"},
    "home.more.advanced_intake": {"pl": "Tryb zaawansowany dostawy", "en": "Advanced intake"},
    "home.more.classic": {"pl": "Zbiory klasyczne", "en": "Classic collections"},
    "home.have.line": {"pl": "Co mam: {what}", "en": "What I have: {what}"},
    "home.have.empty": {
        "pl": "Co mam: jeszcze żadnego lightu z obiektem - zacznij od „Przyjmij”.",
        "en": "What I have: no lights with an object yet - start with “Receive”."},
    "home.have.objects": {
        "pl": {"one": "{n} obiekt", "few": "{n} obiekty", "many": "{n} obiektów"},
        "en": {"one": "{n} object", "other": "{n} objects"}},
    "home.have.lights": {
        "pl": {"one": "{n} light", "few": "{n} lighty", "many": "{n} lightów"},
        "en": {"one": "{n} light", "other": "{n} lights"}},
    "home.have.nights": {
        "pl": {"one": "{n} noc", "few": "{n} noce", "many": "{n} nocy"},
        "en": {"one": "{n} night", "other": "{n} nights"}},
    "home.have.last_night": {"pl": "ostatnia noc {night}", "en": "last night {night}"},
    "home.folders.title": {"pl": "Teczki - najwięcej godzin", "en": "Objects - most hours"},
    "home.folders.computing": {"pl": "Liczę gotowość…", "en": "Computing readiness…"},
    "home.folders.empty": {
        "pl": "Brak teczek - żaden obiekt nie ma jeszcze aktywnych lightów.",
        "en": "No objects yet - none has active lights."},
    "home.folders.failed": {
        "pl": "Gotowość się nie policzyła: {msg}", "en": "Readiness could not be computed: {msg}"},
    "home.folders.more": {
        "pl": {"one": "… i {n} kolejna - szukaj w Znajdź",
               "few": "… i {n} kolejne - szukaj w Znajdź",
               "many": "… i {n} kolejnych - szukaj w Znajdź"},
        "en": {"one": "… and {n} more - search in Find", "other": "… and {n} more - search in Find"}},
    "home.card.sets": {
        "pl": {"one": "{n} zestaw", "few": "{n} zestawy", "many": "{n} zestawów"},
        "en": {"one": "{n} set", "other": "{n} sets"}},
    "home.card.flat": {"pl": "flat {n} %", "en": "flat {n} %"},
    "home.card.raw": {"pl": " (+ surowe {n} %)", "en": " (+ raw {n} %)"},
    "home.card.dark": {"pl": "dark {n} %", "en": "dark {n} %"},
    "home.card.pending": {
        "pl": {"one": "{n} light do przeliczenia w Dostawie",
               "few": "{n} lighty do przeliczenia w Dostawie",
               "many": "{n} lightów do przeliczenia w Dostawie"},
        "en": {"one": "{n} light to recompute in Intake",
               "other": "{n} lights to recompute in Intake"}},
    "home.card.tip": {"pl": "Klik: klatki {canon} w Znajdź", "en": "Click: {canon} frames in Find"},
    "home.last.label": {"pl": "Ostatnio:", "en": "Last:"},
    "home.last.journal": {"pl": "Ostatnio ({day}): {what}", "en": "Last ({day}): {what}"},
    "home.last.day": {"pl": "{dd}.{mm}", "en": "{mm}/{dd}"},
    "home.last.day_year": {"pl": "{dd}.{mm}.{yyyy}", "en": "{yyyy}-{mm}-{dd}"},
    # Zdanie gestu ogólne: kilka czasowników naraz albo czasownik bez własnego zdania - liczba
    # mówi o WSZYSTKICH zmianach gestu.
    "home.gest.many": {
        "pl": {"one": "{n} zmiana", "few": "{n} zmiany", "many": "{n} zmian"},
        "en": {"one": "{n} change", "other": "{n} changes"}},
    "home.gest.object_assigned": {
        "pl": {"one": "{n} klatce nadano obiekt", "few": "{n} klatkom nadano obiekt",
               "many": "{n} klatkom nadano obiekt"},
        "en": {"one": "object assigned to {n} frame", "other": "object assigned to {n} frames"}},
    "home.gest.object_cleared": {
        "pl": {"one": "{n} klatce cofnięto obiekt", "few": "{n} klatkom cofnięto obiekt",
               "many": "{n} klatkom cofnięto obiekt"},
        "en": {"one": "object cleared on {n} frame", "other": "object cleared on {n} frames"}},
    "home.gest.object_aliased": {
        "pl": {"one": "{n} alias zapamiętano", "few": "{n} aliasy zapamiętano",
               "many": "{n} aliasów zapamiętano"},
        "en": {"one": "{n} alias remembered", "other": "{n} aliases remembered"}},
    "home.gest.object_upserted": {
        "pl": {"one": "{n} obiekt dodano", "few": "{n} obiekty dodano", "many": "{n} obiektów dodano"},
        "en": {"one": "{n} object added", "other": "{n} objects added"}},
    "home.gest.location_renamed": {
        "pl": {"one": "{n} plik przemianowano", "few": "{n} pliki przemianowano",
               "many": "{n} plików przemianowano"},
        "en": {"one": "{n} file renamed", "other": "{n} files renamed"}},
    "home.gest.note_set": {
        "pl": {"one": "{n} klatce zapisano uwagę", "few": "{n} klatkom zapisano uwagę",
               "many": "{n} klatkom zapisano uwagę"},
        "en": {"one": "note saved on {n} frame", "other": "note saved on {n} frames"}},
    "home.gest.note_cleared": {
        "pl": {"one": "{n} klatce usunięto uwagę", "few": "{n} klatkom usunięto uwagę",
               "many": "{n} klatkom usunięto uwagę"},
        "en": {"one": "note removed from {n} frame", "other": "note removed from {n} frames"}},
    "home.gest.camera_pixel_user_set": {
        "pl": {"one": "{n} kamerze wpisano piksel", "few": "{n} kamerom wpisano piksel",
               "many": "{n} kamerom wpisano piksel"},
        "en": {"one": "pixel size set on {n} camera", "other": "pixel size set on {n} cameras"}},
    "home.gest.camera_pixel_user_cleared": {
        "pl": {"one": "{n} kamerze zdjęto wpisany piksel", "few": "{n} kamerom zdjęto wpisany piksel",
               "many": "{n} kamerom zdjęto wpisany piksel"},
        "en": {"one": "pixel size cleared on {n} camera",
               "other": "pixel size cleared on {n} cameras"}},
    "home.gest.frame_retired": {
        "pl": {"one": "{n} klatkę wycofano", "few": "{n} klatki wycofano", "many": "{n} klatek wycofano"},
        "en": {"one": "{n} frame retired", "other": "{n} frames retired"}},
    "home.gest.frame_unretired": {
        "pl": {"one": "{n} klatkę przywrócono", "few": "{n} klatki przywrócono",
               "many": "{n} klatek przywrócono"},
        "en": {"one": "{n} frame restored", "other": "{n} frames restored"}},
    "home.gest.config_assigned": {
        "pl": {"one": "{n} klatce przypisano zestaw", "few": "{n} klatkom przypisano zestaw",
               "many": "{n} klatkom przypisano zestaw"},
        "en": {"one": "set assigned to {n} frame", "other": "set assigned to {n} frames"}},
    "home.gest.observatory_assigned": {
        "pl": {"one": "{n} klatce wskazano stanowisko", "few": "{n} klatkom wskazano stanowisko",
               "many": "{n} klatkom wskazano stanowisko"},
        "en": {"one": "site assigned to {n} frame", "other": "site assigned to {n} frames"}},
    "home.gest.observatory_named": {
        "pl": {"one": "{n} stanowisku nadano nazwę", "few": "{n} stanowiskom nadano nazwę",
               "many": "{n} stanowiskom nadano nazwę"},
        "en": {"one": "{n} site named", "other": "{n} sites named"}},
    "home.gest.observatory_merged": {
        "pl": {"one": "{n} stanowisko scalono", "few": "{n} stanowiska scalono",
               "many": "{n} stanowisk scalono"},
        "en": {"one": "{n} site merged", "other": "{n} sites merged"}},
    "home.gest.telescope_merged": {
        "pl": {"one": "{n} teleskop scalono", "few": "{n} teleskopy scalono",
               "many": "{n} teleskopów scalono"},
        "en": {"one": "{n} telescope merged", "other": "{n} telescopes merged"}},
    "home.gest.telescope_approved": {
        "pl": {"one": "{n} teleskop zatwierdzono", "few": "{n} teleskopy zatwierdzono",
               "many": "{n} teleskopów zatwierdzono"},
        "en": {"one": "{n} telescope approved", "other": "{n} telescopes approved"}},
    "home.gest.telescope_labeled": {
        "pl": {"one": "{n} teleskopowi nadano nazwę", "few": "{n} teleskopom nadano nazwę",
               "many": "{n} teleskopom nadano nazwę"},
        "en": {"one": "{n} telescope named", "other": "{n} telescopes named"}},
    "home.gest.telescope_parked": {
        "pl": {"one": "{n} teleskop odłożono", "few": "{n} teleskopy odłożono",
               "many": "{n} teleskopów odłożono"},
        "en": {"one": "{n} telescope parked", "other": "{n} telescopes parked"}},
    "home.gest.integration_judged": {
        "pl": {"one": "{n} werdykt rodowodu zapisano", "few": "{n} werdykty rodowodu zapisano",
               "many": "{n} werdyktów rodowodu zapisano"},
        "en": {"one": "{n} lineage verdict saved", "other": "{n} lineage verdicts saved"}},
    "home.gest.integration_offset_set": {
        "pl": {"one": "{n} stosowi ustawiono odniesienie czasu",
               "few": "{n} stosom ustawiono odniesienie czasu",
               "many": "{n} stosom ustawiono odniesienie czasu"},
        "en": {"one": "time reference set on {n} stack",
               "other": "time reference set on {n} stacks"}},
    "home.gest.target_plan_set": {
        "pl": {"one": "{n} cel planu zapisano", "few": "{n} cele planu zapisano",
               "many": "{n} celów planu zapisano"},
        "en": {"one": "{n} plan target saved", "other": "{n} plan targets saved"}},
    "home.gest.target_plan_cleared": {
        "pl": {"one": "{n} cel planu zdjęto", "few": "{n} cele planu zdjęto",
               "many": "{n} celów planu zdjęto"},
        "en": {"one": "{n} plan target removed", "other": "{n} plan targets removed"}},
    "home.gest.perspective_saved": {
        "pl": {"one": "{n} perspektywę zapisano", "few": "{n} perspektywy zapisano",
               "many": "{n} perspektyw zapisano"},
        "en": {"one": "{n} perspective saved", "other": "{n} perspectives saved"}},

    # --- PLANER CELÓW (T5): nagłówek nocy, komórki listy, noty ---------------------------------
    # Świadomie BEZ badge'a przy pozycji nav (D-0731-6): „ile do zrobienia" zależy od suwaka
    # `min_hours`, więc liczba w nawiasie kłamałaby przy każdej zmianie progu.
    "planner.night_header": {
        "pl": "Noc {night} · {site} · ciemność {dark} UTC · Księżyc {moon}, wys. {alt}",
        "en": "Night {night} · {site} · darkness {dark} UTC · Moon {moon}, alt {alt}",
    },
    "planner.site_unnamed": {"pl": "stanowisko bez nazwy", "en": "unnamed site"},
    "planner.counts": {
        "pl": "Cele: {pool} → {feasible} po progach → {above} nad horyzontem → {visible} widocznych"
              " (wierszy: {rows})",
        "en": "Targets: {pool} → {feasible} after thresholds → {above} above horizon → {visible}"
              " visible (rows: {rows})",
    },
    "planner.arcmin": {"pl": "{n}′", "en": "{n}′"},
    "planner.one_frame": {"pl": "1 kadr", "en": "1 frame"},
    "planner.mosaic": {"pl": "mozaika {n}", "en": "mosaic {n}"},
    "planner.your_name": {"pl": "u Ciebie: {names}", "en": "your name: {names}"},
    "planner.gaps": {"pl": "brak {channels}", "en": "missing {channels}"},
    "planner.no_frames": {"pl": "bez klatek", "en": "no frames"},
    # K-3: status katalogowy obok typu - kandydatka i mimika nigdy nie podpisują się samym „PN”.
    "planner.type_candidate": {"pl": "{type} (kandydatka)", "en": "{type} (candidate)"},
    "planner.type_mimic": {"pl": "{type} (mimika PN)", "en": "{type} (PN mimic)"},
    # I-2e — most rodowodu stosów do planera. „w obrazach" mówi o CZASIE, który realnie wszedł
    # w gotowy obraz; jest osobną liczbą od godzin zebranych i nie ma prawa brzmieć jak ich powtórka.
    "planner.integrated": {"pl": "w obrazach {hours}", "en": "in images {hours}"},
    "planner.stacks_header": {"pl": "Gotowe obrazy ({n}):", "en": "Finished images ({n}):"},
    "planner.stack_no_copy": {"pl": "(brak kopii pod ręką)", "en": "(no copy at hand)"},
    "planner.integrated_by_channel": {"pl": "Zintegrowane: {parts}",
                                      "en": "Integrated: {parts}"},
    "planner.reason_no_gap": {"pl": "bez luk", "en": "no gaps"},
    "planner.reason_rig_cannot": {"pl": "zestaw nie umie", "en": "rig cannot"},
    "planner.reason_no_rig": {"pl": "brak zestawu", "en": "no rig"},
    "planner.status_planned": {"pl": "zaplanowany", "en": "planned"},
    "planner.status_active": {"pl": "w toku", "en": "active"},
    "planner.status_done": {"pl": "zrobiony", "en": "done"},
    "planner.status_skip": {"pl": "pominięty", "en": "skipped"},
    "planner.park_unset": {
        "pl": "Park NIEUSTAWIONY — liczone WSZYSTKIE teleskopy bazy, także historyczne.",
        "en": "Park NOT SET — counting ALL telescopes in the database, historical ones too.",
    },
    "planner.park_source_db": {"pl": "Park (z bazy): {park}", "en": "Park (from database): {park}"},
    "planner.park_source_arg": {"pl": "Park (z wywołania): {park}", "en": "Park (from call): {park}"},
    "planner.park_without_rigs": {
        "pl": "W parku bez zestawu (brak lightów): {names}",
        "en": "In the park with no rig (no lights): {names}",
    },
    "planner.unfiltered_mono": {
        "pl": "{n} lightów bez filtra na kamerze mono — kubełek RGB może być zanieczyszczony.",
        "en": "{n} lights with no filter on a mono camera — the RGB bucket may be polluted.",
    },
    "planner.hidden_by_status": {
        "pl": "Ukrytych jako „pominięty”: {n} (filtr statusu je pokaże).",
        "en": "Hidden as “skipped”: {n} (the status filter will show them).",
    },
    "planner.rig_skipped": {
        "pl": "Zestaw {name} poza planem: {reason}",
        "en": "Rig {name} outside the plan: {reason}",
    },
    # Filtr kadru (dług T5, PL-1, PL-2): na żądanie, domyślnie wyłączony. Włączony zmienia
    # ZNACZENIE licznika „po progach" na „twoim sprzętem" - napis idzie razem z semantyką.
    "planner.counts_rig": {
        "pl": "Cele: {pool} → {feasible} wykonalnych twoim sprzętem ({filter}; {hidden})"
              " → {above} nad horyzontem → {visible} widocznych (wierszy: {rows})",
        "en": "Targets: {pool} → {feasible} doable with your gear ({filter}; {hidden})"
              " → {above} above horizon → {visible} visible (rows: {rows})",
    },
    # Liczba wierszy przy soczewce, która chowa: wstawiana w `{rows}` licznika, więc bez soczewki
    # napis zostaje ten sam. Liczba po dwukropku - bez odmiany rzeczownika.
    "planner.rows_in_lens": {"pl": "{rows}; w soczewce {name}: {shown}",
                             "en": "{rows}; in the {name} lens: {shown}"},
    "planner.rig_hidden": {
        "pl": {"one": "filtr schował {n} cel", "few": "filtr schował {n} cele",
               "many": "filtr schował {n} celów"},
        "en": {"one": "the filter hid {n} target", "other": "the filter hid {n} targets"},
    },
    "planner.rig_filter_fill": {"pl": "wypełnienie ≥{pct}%", "en": "fill ≥{pct}%"},
    "planner.rig_filter_panels": {"pl": "maks. paneli {n}", "en": "max panels {n}"},
    "planner.rig_filter_no_park": {
        "pl": "Filtr kadru ({filter}) wyłączony: park nieustawiony, a liczenie po wszystkich "
              "teleskopach bazy, także historycznych, nie odcięłoby uczciwie niczego. Ustaw park.",
        "en": "Framing filter ({filter}) is off: the park is not set, and counting over every "
              "telescope in the database, historical ones too, would cut nothing honestly. Set the park.",
    },
    "planner.rig_filter_no_rigs": {
        "pl": "Filtr kadru ({filter}) wyłączony: park nie dał ani jednego zestawu z polem widzenia.",
        "en": "Framing filter ({filter}) is off: the park gave no rig with a known field of view.",
    },
    "planner.lens_hidden": {
        "pl": {"one": "Soczewka {name}: filtr kadru schował jeszcze {n} cel, którego ten zestaw"
                      " nie spełnia.",
               "few": "Soczewka {name}: filtr kadru schował jeszcze {n} cele, których ten zestaw"
                      " nie spełnia.",
               "many": "Soczewka {name}: filtr kadru schował jeszcze {n} celów, których ten zestaw"
                       " nie spełnia."},
        "en": {"one": "Lens {name}: the framing filter hid {n} more target this rig does not meet.",
               "other": "Lens {name}: the framing filter hid {n} more targets this rig does not"
                        " meet."},
    },

    # --- ekran planera (T5c): kolumny listy i panel sterowania --------------------------------
    "planner.col_canon": {"pl": "Cel", "en": "Target"},
    "planner.col_type": {"pl": "Typ", "en": "Type"},
    "planner.col_size": {"pl": "Rozmiar", "en": "Size"},
    "planner.col_culmination": {"pl": "Kulminacja", "en": "Culmination"},
    "planner.col_window": {"pl": "Okno", "en": "Window"},
    "planner.col_rig": {"pl": "Zestaw i kadr", "en": "Rig and framing"},
    # Nagłówek SKRÓCONY (podłoga szerokości `planner._MIN_W`), pełna nazwa w podpowiedzi nagłówka.
    "planner.col_fill": {"pl": "Wypełn.", "en": "Fill"},
    "planner.col_fill_tip": {
        "pl": "Wypełnienie kadru: większy z ilorazów osi celu do boków kadru zestawu w soczewce.\n"
              "Mozaika wypełnia każdy panel, więc ma zawsze 100% (komórka przygaszona).",
        "en": "Frame fill: the larger ratio of the target's axes to the frame sides of the rig in\n"
              "the lens. A mosaic fills every panel, so it is always 100% (dimmed cell).",
    },
    "planner.fill_mosaic_tip": {
        "pl": "Mozaika zawsze wypełnia kadr - 100% nie znaczy tu, że cel pasuje do jednego kadru.",
        "en": "A mosaic always fills the frame - 100% here does not mean the target fits one frame.",
    },
    "planner.col_coverage": {"pl": "Pokrycie", "en": "Coverage"},
    "planner.col_cost": {"pl": "Koszt B/D/W", "en": "Cost B/D/N"},
    "planner.col_recommend": {"pl": "Rada", "en": "Advice"},
    "planner.col_plan": {"pl": "Plan", "en": "Plan"},
    "planner.col_note": {"pl": "Notatka", "en": "Note"},
    "planner.controls": {"pl": "Wyszukiwanie", "en": "Search"},
    "planner.night": {"pl": "Noc", "en": "Night"},
    "planner.night_auto": {"pl": "(bieżąca noc)", "en": "(current night)"},
    "planner.layer_cirrus": {"pl": "Pokaż cirrus (LBN/LDN)", "en": "Show cirrus (LBN/LDN)"},
    "planner.status": {"pl": "Status", "en": "Status"},
    "planner.status_any": {"pl": "(dowolny)", "en": "(any)"},
    "planner.min_size": {"pl": "Min. rozmiar ′", "en": "Min size ′"},
    "planner.min_dark": {"pl": "Min. rozmiar ciemnej ′", "en": "Min dark size ′"},
    "planner.max_mag": {"pl": "Maks. magnitudo", "en": "Max magnitude"},
    "planner.min_alt": {"pl": "Min. wysokość °", "en": "Min altitude °"},
    "planner.min_hours": {"pl": "Godziny na kanał", "en": "Hours per channel"},
    "planner.max_cost": {"pl": "Próg kosztu", "en": "Cost threshold"},
    "planner.find_label": {"pl": "Szukaj celu", "en": "Find target"},
    "planner.find": {"pl": "Szukaj", "en": "Find"},
    "planner.find_hint": {"pl": "nazwa albo katalog, np. NGC7000", "en": "name or catalog, e.g. NGC7000"},
    "planner.find_note": {
        "pl": "Tryb szukania POMIJA progi i horyzont — pytasz o konkretny cel, dostajesz jego okno.",
        "en": "Search mode SKIPS thresholds and horizon — you asked about one target, you get its window.",
    },
    "planner.chip_best": {"pl": "najlepsze dopasowanie", "en": "best fit"},
    "planner.order_label": {"pl": "Porządek:", "en": "Order:"},
    "planner.order_core": {"pl": "rada planera", "en": "planner advice"},
    "planner.order_lens": {"pl": "dopasowanie do soczewki", "en": "fit in the lens"},
    "planner.order_tip": {
        "pl": "„Rada planera” układa listę tak, jak radzi rachunek nocy (widoczność, luki, koszt\n"
              "Księżyca, okno, wysokość). „Dopasowanie do soczewki” układa ją kadrem wybranego\n"
              "zestawu: najpierw cele mieszczące się w jednym kadrze, potem najlepiej wypełniające.",
        "en": "“Planner advice” orders the list the way the night computation advises (visibility,\n"
              "gaps, Moon cost, window, altitude). “Fit in the lens” orders it by framing in the\n"
              "chosen rig: single-frame targets first, then the ones filling it best.",
    },
    "planner.reset_thresholds": {"pl": "Przywróć domyślne", "en": "Restore defaults"},
    "planner.reset_thresholds_tip": {
        "pl": "Progi wracają do 6′ rozmiaru, 15′ dla ciemnych, 13 mag dla galaktyk, 30° wysokości\n"
              "i 1 h na kanał; próg kosztu Księżyca i filtr kadru wyłączone.",
        "en": "Thresholds return to 6′ size, 15′ for dark nebulae, 13 mag for galaxies, 30° altitude\n"
              "and 1 h per channel; the Moon cost threshold and the framing filter go off.",
    },
    "planner.chips_label": {"pl": "Patrzę oczami zestawu:", "en": "Seen through the rig:"},
    "planner.chip_tip": {
        "pl": "Soczewka, nie filtr: zmienia kolumny „Zestaw i kadr”, „Wypełn.” oraz „Rada”."
              " Żaden cel nie znika.",
        "en": "A lens, not a filter: changes the “Rig and framing”, “Fill” and “Advice” columns."
              " No target disappears.",
    },
    "planner.chip_tip_filter": {
        "pl": "Soczewka: zmienia kolumny „Zestaw i kadr”, „Wypełn.” oraz „Rada”. Przy włączonym"
              " filtrze kadru chowa cele, których TEN zestaw nie spełnia.",
        "en": "Lens: changes the “Rig and framing”, “Fill” and “Advice” columns. With the framing"
              " filter on it hides the targets THIS rig does not meet.",
    },
    "planner.min_fill": {"pl": "Min. wypełnienie", "en": "Min fill"},
    "planner.max_panels": {"pl": "Maks. paneli", "en": "Max panels"},
    "planner.rig_filter_tip": {
        "pl": "Filtr kadru, domyślnie wyłączony: chowa cele, których ŻADEN zestaw parku nie zrobi\n"
              "z takim wypełnieniem albo w tylu panelach. Wypełnienie to większy z ilorazów osi celu\n"
              "do boków kadru (mozaika = 100%). Przy nieustawionym parku filtr nie działa.",
        "en": "Framing filter, off by default: hides targets that NO rig of the park can shoot\n"
              "with that fill or in that many panels. Fill is the larger ratio of the target's axes\n"
              "to the frame sides (mosaic = 100%). With no park set the filter does nothing.",
    },
    "planner.controls_state_rig": {"pl": " · filtr kadru: {filter}", "en": " · framing filter: {filter}"},
    "planner.controls_state_rig_off": {"pl": " (nieczynny)", "en": " (inactive)"},
    # Q14: przełącznik kandydatek i mimik PN - wzór filtra kadru (domyślnie wyłączony, nazwany w tytule).
    "planner.hide_pn": {"pl": "Ukryj kandydatki i mimiki PN", "en": "Hide PN candidates and mimics"},
    "planner.hide_pn_tip": {
        "pl": "Domyślnie wyłączony: chowa cele, które katalog podaje jako kandydatkę na mgławicę\n"
              "planetarną (bez potwierdzenia widmem) albo mimikę (zgłoszoną jako PN i odrzuconą).\n"
              "Potwierdzone PN i cele bez statusu zostają. Tryb szukania go pomija.",
        "en": "Off by default: hides targets the catalog lists as a planetary nebula candidate\n"
              "(no spectroscopic confirmation) or a mimic (reported as a PN and rejected).\n"
              "Confirmed PNe and targets without a status stay. Search mode skips it.",
    },
    "planner.controls_state_pn": {"pl": " · bez kandydatek i mimik PN",
                                  "en": " · no PN candidates or mimics"},
    "planner.pn_hidden": {
        "pl": {"one": "Przełącznik PN schował {n} kandydatkę lub mimikę.",
               "few": "Przełącznik PN schował {n} kandydatki lub mimiki.",
               "many": "Przełącznik PN schował {n} kandydatek lub mimik."},
        "en": {"one": "The PN switch hid {n} candidate or mimic.",
               "other": "The PN switch hid {n} candidates or mimics."},
    },
    "planner.empty_rig": {
        "pl": "Żaden cel nie przeszedł bieżących progów i filtra kadru - poluzuj wypełnienie albo"
              " liczbę paneli.",
        "en": "No target passed the current thresholds and the framing filter - relax the fill or"
              " the panel count.",
    },
    "planner.controls_state": {
        "pl": "Progi — rozmiar ≥{size}′, ciemna ≥{dark}′, mag ≤{mag}, wys. ≥{alt}°, {hours} h/kanał",
        "en": "Thresholds — size ≥{size}′, dark ≥{dark}′, mag ≤{mag}, alt ≥{alt}°, {hours} h/channel",
    },
    "planner.max_cost_on": {"pl": "licz próg", "en": "apply threshold"},
    "planner.counts_find": {
        "pl": {"one": "Tryb szukania: {n} trafienie dla „{needle}” (progi i horyzont pominięte)",
               "few": "Tryb szukania: {n} trafienia dla „{needle}” (progi i horyzont pominięte)",
               "many": "Tryb szukania: {n} trafień dla „{needle}” (progi i horyzont pominięte)"},
        "en": {"one": "Search mode: {n} hit for “{needle}” (thresholds and horizon skipped)",
               "other": "Search mode: {n} hits for “{needle}” (thresholds and horizon skipped)"},
    },
    "planner.empty_find": {
        "pl": "Nie znam celu „{needle}” — sprawdź nazwę albo oznaczenie katalogowe (np. NGC7000, Sh2-155).",
        "en": "I do not know the target “{needle}” — check the name or catalog id (e.g. NGC7000, Sh2-155).",
    },
    # AR-146: pusty wynik dla nazwy, którą katalog zna. `{name}` = `find_as` albo `find_self`.
    "planner.find_as": {"pl": "„{needle}” = {canon}", "en": "“{needle}” = {canon}"},
    "planner.find_self": {"pl": "„{needle}”", "en": "“{needle}”"},
    "planner.empty_find_outside": {
        "pl": "{name}, poza celami planera.",
        "en": "{name}, not among the planner targets.",
    },
    "planner.empty_find_hidden": {
        "pl": {"one": "„{needle}” trafia {n} cel, ale chowają go bieżące filtry.",
               "few": "„{needle}” trafia {n} cele, ale chowają je bieżące filtry.",
               "many": "„{needle}” trafia {n} celów, ale chowają je bieżące filtry."},
        "en": {"one": "“{needle}” matches {n} target, but the current filters hide it.",
               "other": "“{needle}” matches {n} targets, but the current filters hide them."},
    },
    "planner.empty_find_layer": {
        "pl": "{name} ({type}) - cel spoza wczytanych warstw: zaznacz „{layer}”, żeby go zobaczyć.",
        "en": "{name} ({type}) - a target outside the loaded layers: tick “{layer}” to see it.",
    },
    "planner.status_none": {"pl": "(bez oznaczenia)", "en": "(not marked)"},
    "planner.panel_of": {"pl": "Zaznaczony cel — {canon}", "en": "Selected target — {canon}"},
    "planner.park_close": {"pl": "Zamknij", "en": "Close"},
    "planner.not_visible_tip": {
        "pl": "Tej nocy nie wychodzi nad przyjęty horyzont — wiersz zostaje, żeby było widać dlaczego.",
        "en": "Does not rise above the chosen horizon tonight — the row stays so you can see why.",
    },
    "planner.empty": {
        "pl": "Żaden cel nie przeszedł bieżących progów — poluzuj rozmiar, magnitudo albo wysokość.",
        "en": "No target passed the current thresholds — relax size, magnitude or altitude.",
    },
    # AR-48: baza bez stanowiska z GPS to STAN ekranu planera (pusty stan z gestem), nie surowe
    # zdanie rdzenia na pasku nad cudzym ekranem. Tytuł idzie na nagłówek nocy i na pasek (tylko
    # przy widocznym planerze), zdanie i gest - na środek ekranu.
    "planner.no_site_title": {
        "pl": "Brak stanowiska z pozycją GPS - nie ma z czego policzyć nocy",
        "en": "No site with a GPS position - there is no night to compute",
    },
    "planner.no_site": {
        "pl": "Planer liczy noc z pozycji obserwatora, a baza nie zna jeszcze żadnego stanowiska "
              "z GPS. Wskaż stanowisko na osi obserwatorium - plan policzy się po powrocie tutaj.",
        "en": "The planner computes the night from the observer's position, and the database knows "
              "no site with GPS yet. Set a site on the observatory axis - the plan is computed "
              "when you come back here.",
    },
    "planner.no_site_action": {"pl": "Ustaw stanowisko…", "en": "Set a site…"},

    # --- panel celu (T5d, JEDYNE miejsce zapisu ekranu) + park -------------------------------
    "planner.panel": {"pl": "Zaznaczony cel", "en": "Selected target"},
    "planner.priority": {"pl": "Priorytet", "en": "Priority"},
    "planner.priority_none": {"pl": "—", "en": "—"},
    "planner.note_hint": {"pl": "notatka do celu", "en": "note for this target"},
    "planner.save_mark": {"pl": "Zapisz oznaczenie", "en": "Save mark"},
    "planner.clear_mark": {"pl": "Zdejmij oznaczenie", "en": "Clear mark"},
    "planner.show_frames": {"pl": "Pokaż klatki celu →", "en": "Show target frames →"},
    "planner.no_gaps": {"pl": "✓ bez luk", "en": "✓ no gaps"},
    "planner.mark_saved": {"pl": "Zapisano oznaczenie: {canon}.", "en": "Mark saved: {canon}."},
    "planner.mark_cleared": {"pl": "Zdjęto oznaczenie: {canon}.", "en": "Mark cleared: {canon}."},
    "planner.mark_same": {"pl": "Bez zmian: {canon}.", "en": "No change: {canon}."},

    # --- oś ŻYWOTNOŚCI klatki na pasku Zbiorów (D-OW-3/R2) ---
    "grid.sel.frame": {"pl": "Klatka", "en": "Frame"},
    "grid.sel.frame_retire": {"pl": "Wycofaj klatkę…", "en": "Retire frame…"},
    "grid.sel.frame_restore": {"pl": "Przywróć klatkę", "en": "Restore frame"},
    "grid.sel.frame_retire_ask": {
        "pl": "Wycofać {n} zaznaczonych klatek?  Wycofanie zamyka sprawę klatki, której pliku "
              "już nie ma na dysku: wypadnie z kolejek roboczych, ale ZOSTANIE w archiwum "
              "i w godzinach. Gest można cofnąć (Klatka ▾ → Przywróć klatkę).",
        "en": "Retire {n} selected frames?  Retiring closes the case of a frame whose file is "
              "gone from disk: it drops out of the work queues but STAYS in the archive and in "
              "the exposure hours. You can undo this (Frame ▾ → Restore frame).",
    },
    # Odmiana po `{n}` = wszystkich klatkach gestu (dopełniacz po „z": „z 1 klatki", „z 5 klatek"),
    # wzorem `object.assigned` - „Przywrócono 1 z 1 klatek" czytało się jak błąd.
    "grid.sel.frame_retired": {
        "pl": {"one": "Wycofano {done} z {n} klatki", "few": "Wycofano {done} z {n} klatek",
               "many": "Wycofano {done} z {n} klatek"},
        "en": {"one": "Retired {done} of {n} frame", "other": "Retired {done} of {n} frames"}},
    "grid.sel.frame_restored": {
        "pl": {"one": "Przywrócono {done} z {n} klatki", "few": "Przywrócono {done} z {n} klatek",
               "many": "Przywrócono {done} z {n} klatek"},
        "en": {"one": "Restored {done} of {n} frame", "other": "Restored {done} of {n} frames"}},
    "grid.sel.frame_skip_present": {"pl": " · plik istnieje: {n}", "en": " · file exists: {n}"},
    "grid.sel.frame_skip_no_location": {
        "pl": " · bez lokalizacji: {n}", "en": " · no location: {n}"},
    "grid.sel.frame_skip_superseded": {"pl": " · zastąpione: {n}", "en": " · superseded: {n}"},
    "grid.sel.frame_skip_already": {
        "pl": " · już w tym stanie: {n}", "en": " · already in that state: {n}"},
    "grid.sel.frame_tip_ready": {
        "pl": "Do wycofania: {retirable} · do przywrócenia: {restorable}",
        "en": "To retire: {retirable} · to restore: {restorable}",
    },
    "grid.sel.frame_tip_empty": {
        "pl": "Zaznacz klatki, żeby je wycofać albo przywrócić.",
        "en": "Select frames to retire or restore them.",
    },
    "grid.sel.frame_tip_alive": {
        "pl": "Pliki zaznaczonych klatek istnieją na dysku — wycofać można tylko klatkę, "
              "której pliku już nie ma.",
        "en": "The selected frames' files exist on disk — only a frame whose file is gone "
              "can be retired.",
    },
    "grid.sel.frame_tip_none": {
        "pl": "W zaznaczeniu nie ma ani klatki do wycofania, ani wycofanej do przywrócenia.",
        "en": "The selection has neither a frame to retire nor a retired one to restore.",
    },

    # --- sierota kurateli (R-S0-7): oznaczenie, którego lista planu nie ma jak pokazać ---
    "planner.orphans": {
        "pl": "Oznaczenia bez celu w katalogu ({n})",
        "en": "Marks with no catalogue target ({n})",
    },
    "planner.orphans_hint": {
        "pl": "Te oznaczenia nie mają jak trafić na listę powyżej — katalog nie zna ich nazwy "
              "albo przeniósł ją pod inny rekord. Lista planu ich NIE pokazuje.",
        "en": "These marks cannot reach the list above — the catalogue does not know their name "
              "or has moved it under another record. The plan list does NOT show them.",
    },
    "planner.orphan_row": {
        "pl": "{canon} · {status} · {where}  {note}",
        "en": "{canon} · {status} · {where}  {note}",
    },
    "planner.orphan_unknown": {"pl": "poza katalogiem", "en": "outside the catalogue"},
    "planner.orphan_moved_to": {
        "pl": "w katalogu jako {where}",
        "en": "in the catalogue as {where}",
    },
    "planner.orphan_move": {"pl": "Przenieś", "en": "Move"},
    "planner.orphan_move_taken": {
        "pl": "{where} ma już własne oznaczenie — przeniesienie nadpisałoby je. "
              "Zdejmij je najpierw albo zdejmij tę sierotę.",
        "en": "{where} already has its own mark — moving would overwrite it. "
              "Clear it first, or clear this orphan instead.",
    },
    "planner.orphan_move_tip": {
        "pl": "Przenieś oznaczenie (status, priorytet i notatkę) na {where} — rekord, "
              "który przejął tę nazwę.",
        "en": "Move the mark (status, priority and note) to {where} — the record that took "
              "over this name.",
    },
    "planner.orphan_move_tip_none": {
        "pl": "Przeniesienie ma sens tylko wtedy, gdy katalog zna tę nazwę pod innym rekordem.",
        "en": "Moving only makes sense when the catalogue knows this name under another record.",
    },
    "planner.orphan_move_tip_taken": {
        "pl": "{where} ma już własne oznaczenie - przeniesienie nadpisałoby je. "
              "Zdejmij je najpierw albo zdejmij tę sierotę.",
        "en": "{where} already has its own mark - moving would overwrite it. "
              "Clear it first, or clear this orphan instead.",
    },
    "planner.orphan_clear": {"pl": "Zdejmij", "en": "Clear"},
    "planner.orphan_undo": {"pl": "Cofnij zdjęcie", "en": "Undo clearing"},
    "planner.orphan_undo_tip": {
        "pl": "Przywraca ostatnio zdjęte oznaczenie z tej sesji. Sieroty NIE DA SIĘ odtworzyć "
              "inaczej — zapis wymaga nazwy, którą zna katalog.",
        "en": "Restores the mark cleared last in this session. An orphan CANNOT be recreated "
              "any other way — writing requires a name the catalogue knows.",
    },
    "planner.orphan_cleared": {
        "pl": "Zdjęto osierocone oznaczenie: {canon}. Możesz to cofnąć.",
        "en": "Orphaned mark cleared: {canon}. You can undo this.",
    },
    "planner.orphan_moved": {
        "pl": "Przeniesiono oznaczenie {canon} → {where}.",
        "en": "Mark moved: {canon} → {where}.",
    },
    "planner.orphan_undone": {
        "pl": "Przywrócono oznaczenie: {canon}.",
        "en": "Mark restored: {canon}.",
    },
    "planner.park_btn": {"pl": "Park…", "en": "Park…"},
    "planner.park_title": {"pl": "Park teleskopów", "en": "Telescope park"},
    "planner.park_hint": {
        "pl": "Czym dziś fotografujesz? Park jest Twoim zdaniem o sprzęcie — planer nie zgaduje go\n"
              "z ostatniej klatki, bo „ostatnio używany” to nie to samo co „posiadany”.",
        "en": "What do you shoot with today? The park is your statement about gear — the planner does\n"
              "not guess it from the last frame: “last used” is not “owned”.",
    },
    "planner.park_col_telescope": {"pl": "Teleskop", "en": "Telescope"},
    "planner.park_canon_tip": {
        "pl": "Z nagłówka: {canon}\n(tej nazwy używa `horreum park --add`)",
        "en": "From header: {canon}\n(this is the name `horreum park --add` takes)",
    },
    "planner.park_col_lights": {"pl": "Lighty", "en": "Lights"},
    "planner.park_col_last": {"pl": "Ostatnia klatka", "en": "Last frame"},
    "planner.park_col_state": {"pl": "Park", "en": "Park"},
    "planner.park_in": {"pl": "w parku", "en": "in the park"},
    "planner.park_historic": {"pl": "historyczny", "en": "historical"},
    "planner.park_unsaid": {"pl": "(nie wypowiedziałeś się)", "en": "(you have not said)"},
    "planner.no_object_for_target": {
        "pl": "Ten cel nie ma w bazie żadnego obiektu — nie ma czego pokazać w Zbiorach.",
        "en": "This target has no object in the database — there is nothing to show in Collections.",
    },
    "planner.park_changed": {
        "pl": "Park: zmieniono {n} oznaczeń — plan przeliczony.",
        "en": "Park: {n} marks changed — plan recomputed.",
    },
    "main.no_db": {
        "pl": "Brak bazy — otwórz lub utwórz bazę (menu Plik).",
        "en": "No database — open or create one (File menu).",
    },
    "main.db_loaded": {"pl": "Baza: {path}", "en": "Database: {path}"},
    # AR-69: baza zapisana nowszym Horreum - odmowa, zanim program cokolwiek w niej zmieni.
    "main.db_too_new": {
        "pl": "Baza {name} pochodzi z nowszej wersji Horreum (schemat v{found}), a ten program "
              "zna schemat do v{supported}.\n\nZaktualizuj Horreum. Baza zostaje nietknięta.",
        "en": "Database {name} comes from a newer version of Horreum (schema v{found}), and this "
              "program knows schemas up to v{supported}.\n\nUpdate Horreum. The database is left "
              "untouched.",
    },
    "main.db_open_failed": {
        "pl": "Nie udało się otworzyć bazy {name}.\n\nPowód: {reason}\n\nPlik może być uszkodzony, "
              "zajęty przez inny program albo nie być bazą Horreum. Okno nie przełączyło się na "
              "ten plik.",
        "en": "Could not open database {name}.\n\nReason: {reason}\n\nThe file may be damaged, "
              "locked by another program, or not a Horreum database. The window did not switch "
              "to this file.",
    },

    # --- FAZY DŁUGICH OPERACJI (F-1) — czasownik w pierwszej osobie ---
    # „Czytam bazę…", nie „Ładowanie": user pytał, czy aplikacja COŚ ROBI, więc odpowiedź ma być
    # zdaniem o robocie, a nie etykietą stanu. Wielokropek niesie „to jeszcze trwa" — kończymy nim
    # KAŻDĄ fazę, żeby jej zniknięcie było jedynym sygnałem końca.
    "busy.open_db": {"pl": "Otwieram bazę: {name}…", "en": "Opening database: {name}…"},
    "busy.mount_views": {"pl": "Buduję widoki…", "en": "Building views…"},
    "busy.refresh_views": {"pl": "Odświeżam widoki po etapie…", "en": "Refreshing views after stage…"},
    "busy.read_frames": {"pl": "Czytam klatki…", "en": "Reading frames…"},
    "busy.read_queue": {"pl": "Czytam bibliotekę i kolejkę przeglądu…",
                        "en": "Reading library and review queue…"},
    "busy.fill_frames": {"pl": "Pokazuję klatki: {n}…", "en": "Showing frames: {n}…"},
    "busy.count_proposals": {"pl": "Liczę propozycje ze ścieżki…", "en": "Counting path proposals…"},
    "busy.saving_names": {"pl": "Zapisuję nazwy: {done} z {total}…",
                          "en": "Saving names: {done} of {total}…"},
    "busy.saving_frames": {
        "pl": {"one": "Zapisuję {n} klatkę…", "few": "Zapisuję {n} klatki…",
               "many": "Zapisuję {n} klatek…"},
        "en": {"one": "Saving {n} frame…", "other": "Saving {n} frames…"},
    },
    # Przywracanie idzie transakcja per OBIEKT, nie per klatka — licznik mówi więc o grupach,
    # tak jak `saving_names` mówi o nazwach: „zapisuję" bez liczby nie odróżniałoby przebiegu
    # przez pięć obiektów od zawieszenia się na pierwszym.
    "busy.restoring": {"pl": "Przywracam przypisania: {done} z {total}…",
                       "en": "Restoring assignments: {done} of {total}…"},
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
    "grid.col.images": {"pl": "Obrazy", "en": "Images"},
    "grid.col.lineage": {"pl": "Rodowód", "en": "Lineage"},
    # Stan rodowodu gotowego obrazu (`queries.LINEAGE_STATES`) - komórka, belka grupy, facet listwy.
    "grid.lineage.state.exact": {"pl": "dokładny", "en": "exact"},
    "grid.lineage.state.history": {"pl": "z historii pliku", "en": "from file history"},
    "grid.lineage.state.mixed": {"pl": "częściowo potwierdzony", "en": "partly confirmed"},
    "grid.lineage.state.window": {"pl": "z okna czasu", "en": "from time window"},
    "grid.lineage.state.pending": {"pl": "do potwierdzenia", "en": "to confirm"},
    "grid.lineage.state.rejected": {"pl": "wszystkie odrzucone", "en": "all rejected"},
    "grid.lineage.state.none": {"pl": "brak", "en": "none"},
    "grid.lineage.state.uncounted": {"pl": "nie liczono", "en": "not computed"},
    "grid.lineage.state.nd": {"pl": "nie dotyczy (to nie gotowy obraz)",
                              "en": "not applicable (not a finished image)"},
    "grid.lineage.tip.exact": {
        "pl": "Każda klatka tego obrazu jest pewna: wskazana ręką albo dopasowana po nazwach "
              "przy wydaniu.",
        "en": "Every frame of this image is certain: pointed out by hand or matched by name "
              "at release.",
    },
    "grid.lineage.tip.history": {
        "pl": "Plik sam zapisał, z czego powstał (historia obróbki). Panel „Rodowód” pokazuje listę.",
        "en": "The file recorded what it was made from (processing history). "
              "The “Lineage” panel lists it.",
    },
    "grid.lineage.tip.mixed": {
        "pl": "Część klatek potwierdzona, część wynika tylko z czasu - resztę potwierdzisz "
              "w panelu „Rodowód”.",
        "en": "Some frames confirmed, some only inferred from time - confirm the rest "
              "in the “Lineage” panel.",
    },
    "grid.lineage.tip.window": {
        "pl": "Klatki dobrane z okna czasu, nikt ich nie potwierdził - sprawdź w panelu „Rodowód”.",
        "en": "Frames picked from the time window, nobody confirmed them - "
              "check in the “Lineage” panel.",
    },
    "grid.lineage.tip.pending": {
        "pl": "Program nie ustalił, z czego powstał ten obraz - panel „Rodowód” mówi dlaczego "
              "i co zrobić.",
        "en": "The program could not tell what this image was made from - "
              "the “Lineage” panel says why and what to do.",
    },
    "grid.lineage.tip.rejected": {
        "pl": "Odrzuciłeś wszystkie proponowane klatki - obraz nie ma rodowodu z Twojej decyzji.",
        "en": "You rejected every proposed frame - the image has no lineage by your decision.",
    },
    "grid.lineage.tip.none": {
        "pl": "Obraz nie ma rodowodu i nie czeka na Twój gest - policz rodowód w Dostawie, "
              "żeby sprawdzić go od nowa.",
        "en": "The image has no lineage and awaits no gesture of yours - recompute lineage "
              "in Intake to check it again.",
    },
    "grid.lineage.tip.uncounted": {
        "pl": "Rodowodu tego obrazu jeszcze nie liczono - policz go w Dostawie.",
        "en": "This image's lineage has not been computed yet - compute it in Intake.",
    },

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
    "perspective.ready_images": {"pl": "Gotowe obrazy", "en": "Finished images"},
    "perspective.dups": {"pl": "Duplikaty", "en": "Duplicates"},
    "perspective.vanished": {"pl": "Zniknięte", "en": "Vanished"},
    "perspective.lineage": {"pl": "Rodowód do potwierdzenia", "en": "Lineage to confirm"},
    "perspective.superseded": {"pl": "Zastąpione", "en": "Superseded"},
    "perspective.retired": {"pl": "Wycofane", "en": "Retired"},
    "grid.criteria.only_retired": {"pl": "wycofane ręką", "en": "retired by hand"},
    # PREFIKS, nie sufiks — ta sama lekcja, którą repo odrobiło już raz dla duplikatów
    # (`grid.py`: „Prefiks »×N« PRZED nazwą (P2-2): sufiks ginął przy elizji długich ścieżek").
    # Marker wycofania wszedł jako sufiks i powtórzył ten błąd: kolumna „Ścieżka" startuje na
    # domyślnej szerokości sekcji, a realna nazwa pliku archiwum jest od niej kilkakrotnie
    # szersza, więc `(wycofana)` było elidowane ZAWSZE i obietnica z `grid.py` („ten wiersz ma
    # się tłumaczyć sam, bo user bywa daltonistą albo ma inny motyw") nie docierała do ekranu
    # ani razu w układzie domyślnym. Zmierzone firsthandem 0811 (wizytator-qt).
    # Sort jest na to obojętny: `_sort_key` czyta surowe `row["path"]`, nie `DisplayRole`.
    "grid.cell.retired": {"pl": "(wycofana)  {name}", "en": "(retired)  {name}"},
    "grid.tip.retired": {
        "pl": "\n(wycofana ręką {ts} — pliku już nie szukamy; można to cofnąć: Klatka ▾ → Przywróć)",
        "en": "\n(retired by hand {ts} — the file is no longer looked for; undo: Frame ▾ → Restore)",
    },
    # G2-7d: wycofana, a plik wrócił. Własne zdanie komórki i tooltipa, bo zdanie zwykłej
    # wycofanej („pliku już nie szukamy") jest o niej nieprawdą. Znacznik jest PREFIKSEM z tego
    # samego powodu, co `grid.cell.retired` wyżej - sufiks ginie w elizji kolumny „Ścieżka".
    "perspective.retired_conflict": {
        "pl": "Wycofane, a plik wrócił", "en": "Retired, but the file is back"},
    "grid.criteria.only_retired_conflict": {
        "pl": "wycofane, a plik wrócił", "en": "retired, but the file is back"},
    "grid.cell.retired_back": {
        "pl": "(wycofana, plik wrócił)  {name}", "en": "(retired, file is back)  {name}"},
    "grid.tip.retired_back": {
        "pl": "\n(wycofana ręką {ts}, ale plik jest znów na dysku - werdykt czeka na decyzję: "
              "Klatka ▾ → Przywróć)",
        "en": "\n(retired by hand {ts}, but the file is on disk again - the verdict awaits a "
              "decision: Frame ▾ → Restore)",
    },
    "perspective.missing_copy": {"pl": "Brakujące kopie", "en": "Missing copies"},
    "perspective.copy_conflict": {"pl": "Klatki z niezgodnymi kopiami",
                                  "en": "Frames with disagreeing copies"},
    "perspective.orphan_testimony": {
        "pl": "Zeznanie z nieobecnej kopii", "en": "Testimony from a missing copy"},
    "perspective.withheld_testimony": {"pl": "Zeznanie wstrzymane", "en": "Testimony withheld"},
    "perspective.kept_copies": {"pl": "Kopie zostawione do oka", "en": "Copies kept for review"},
    "perspective.torn_write": {
        "pl": "Plik po przerwanym zapisie", "en": "File after an interrupted write"},
    "perspective.pending_finish": {
        "pl": "Zapis czeka na dokończenie", "en": "Write awaiting completion"},
    "perspective.path_header_conflict": {
        "pl": "Nagłówek inny niż folder", "en": "Header differs from folder"},
    "perspective.to_review": {"pl": "Do przeglądu", "en": "To review"},

    # --- pusty grid (rozwiązywane w USE-site; stałe _EMPTY_* trzymają KLUCZ) ---
    # FH-4: wariant niepustej bazy idzie za PRZYCZYNĄ pustki - wybiera go decyzja recepty
    # (`grid._rodzaj_recepty_powrotu`) pytana o klatki WIDOKU; pasek stanu pyta tę samą metodę
    # o klatki GESTU i w trimie, który ma klatki, dostaje inną odpowiedź (poprawka po firsthandzie).
    # Przycisk pod zdaniem nosi nazwę gestu (przy zbiorze: napis przycisku paska zbioru,
    # `grid.sel.clear_set`), więc zdanie gestu nie cytuje. „Brak klatek w tej perspektywie" pada
    # wyłącznie wtedy, gdy perspektywa nie ma ani jednej klatki. Dawne „zmień filtr lub
    # perspektywę" przy facecie wskazywało gest, który nic nie odsłaniał.
    "grid.empty_filter": {
        "pl": "Brak klatek w tym zbiorze - zawężają go facety albo filtr.",
        "en": "No frames in this set - it is narrowed by facets or the filter.",
    },
    "grid.empty_persp": {
        "pl": "Brak klatek w tej perspektywie.",
        "en": "No frames in this perspective.",
    },
    "grid.empty_persp_action": {
        "pl": "Przełącz na perspektywę „{perspective}”",
        "en": "Switch to the “{perspective}” perspective",
    },
    # Pusta perspektywa kopii przy kopiach bez zebranych faktów: robota mieszka w Dostawie
    # (`grid._ustaw_pusty_stan`). Dopełniacz w PL, więc nazwa widoku stoi w zdaniu, nie z `nav.dostawa`.
    "grid.empty_go_intake": {"pl": "Idź do Dostawy", "en": "Go to Intake"},
    # Brak recepty przy niepustej bazie jest dziś nieosiągalny (bez zawężenia widać wszystko), więc
    # zdanie nie obiecuje żadnego gestu - przycisk bez gestu kłamałby tak samo jak zła recepta.
    "grid.empty_view": {"pl": "Brak klatek w tym widoku.", "en": "No frames in this view."},
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
    # Zdanie mówi wprost, że NIC NIE ZGINĘŁO, i podaje adres — bo „zastąpiona" bez tego czyta się
    # jak strata. Numer klatki jest tu jedynym stałym uchwytem: nazwa pliku bywa ta sama.
    # ⛔ NIE MÓWI „pod tą ścieżką" (bramka 3a 0809, zarzut `kimi`): klatka zastąpiona nie ma ANI
    # JEDNEJ lokacji, więc komórka obok pokazuje „(brak lokalizacji)" — zdanie wskazywałoby ścieżkę,
    # której na ekranie nie ma, czyli tłumaczyłoby się przez rzecz niewidoczną.
    "grid.tip.superseded": {
        "pl": "\n(zastąpiona — jej treść żyje dalej jako klatka #{id}; ta kopia już nie istnieje)",
        "en": "\n(superseded — its content lives on as frame #{id}; this copy is gone)",
    },
    "grid.cell.superseded": {
        "pl": "zastąpiona przez #{id}",
        "en": "superseded by #{id}",
    },
    # WCHŁONIĘTY SZKIELET (AR-42): plik wyzdrowiał i przeczytany dał prawdziwą tożsamość - to nie
    # podmiana treści, więc nie „zastąpiona". Ogniwo do następczyni zostaje w zdaniu.
    "grid.cell.absorbed": {
        "pl": "wchłonięta przez #{id}",
        "en": "absorbed into #{id}",
    },
    "grid.tip.absorbed": {
        "pl": "\n(wchłonięta - plik wyzdrowiał i przeczytany jest klatką #{id}; ta klatka była "
              "pustym miejscem po nieudanym odczycie, nic tu nie zginęło)",
        "en": "\n(absorbed - the file recovered and now reads as frame #{id}; this frame was a "
              "placeholder after a failed read, nothing was lost)",
    },
    "grid.tip.vanished_at": {
        "pl": "\n(zniknięta {ts} — wszystkie lokalizacje present=0)",
        "en": "\n(vanished {ts} — all locations present=0)",
    },
    "grid.tip.dup_locs": {
        "pl": "\n({n} obecnych lokalizacji)", "en": "\n({n} present locations)",
    },
    # KOPIE POD KURSOREM (0021): każda obecna kopia własnym wierszem - pełna ścieżka, liczba obrazów
    # (role dokleja kod, bo to wartości z pliku, nie napis UI) i pola, w których jej nagłówek mówi
    # co innego niż pozostałe. Nazwy pól to keywordy z pliku (`FILTER=CLS`) - fakt domenowy, D-L3.
    "grid.tip.copy_path": {"pl": "\n• {path}", "en": "\n• {path}"},
    # Kopia wskazana gestem „Ta kopia prowadzi" (ważna kotwica ręki) - ten sam znacznik co w menu.
    "grid.tip.copy_hand": {"pl": " · wskazana ręką", "en": " · picked by hand"},
    "grid.tip.copy_images": {"pl": " · obrazy: {n}", "en": " · images: {n}"},
    "grid.tip.copy_diff": {
        "pl": "\n    mówi inaczej: {fields}", "en": "\n    says otherwise: {fields}",
    },
    "grid.tip.copy_field_images": {"pl": "obrazy", "en": "images"},
    # Pola rozjazdu z NAZWY i ŚCIEŻKI kopii (AR-1, `queries.copy_name_facts`) - w zdaniu
    # „mówi inaczej: grupa flatów=202203240" obok keywordów nagłówka.
    "grid.tip.copy_field_flatgrp": {"pl": "grupa flatów", "en": "flat group"},
    "grid.tip.copy_field_name_filter": {"pl": "filtr w nazwie", "en": "filter in name"},
    "grid.tip.copy_field_filter_dir": {"pl": "folder filtra", "en": "filter folder"},
    # Podpowiedź „?" w kolumnie „Obrazy" (perspektywy kopii): nagłówek zdania, a drogi dokleja
    # `grid.tip.copy_unread` - jeden właściciel recepty dla kopii bez zebranych faktów.
    "grid.tip.images_unknown": {"pl": "Liczba obrazów nieznana:", "en": "Number of images unknown:"},
    # DWIE DROGI W JEDNYM ZDANIU, bo podpowiedź nie wie, która jest prawdziwa: kopia „obecna" w bazie
    # może już nie mieć pliku na dysku, a wtedy Dostawa jej nie uzupełni nigdy - recepta z samym
    # „Przyjmij nowe” prowadziła w ślepy zaułek. Sprawdzenia dysku w podpowiedzi NIE robimy (udział
    # SMB pod kursorem myszy), rozstrzyga pass obecności. Nazwy miejsca i przycisku czytane
    # z katalogu (`{place}`, `{mark}`), żeby zdanie nie rozjechało się z ekranem po zmianie etykiety.
    # Obie drogi są WARUNKOWE: „uzupełni je Przyjmij nowe" obiecywało wynik, którego Dostawa przy
    # kopii bez pliku nie da nigdy (firsthand: po „Przyjmij nowe" dwie skasowane kopie dalej bez
    # zeznania). Kolejność = kolejność pytań człowieka: najpierw „czy plik jest", potem droga.
    # Druga droga ma DWA kroki (AR-28 (a)): „Oznacz zniknięte” pojawia się w Dostawie dopiero po
    # sprawdzeniu obecności, więc w świeżej sesji samo „{mark}” wskazywało przycisk, którego nie
    # ma. „{check}” działa bez wskazanego katalogu (bierze ostatnie źródło „Przyjmij nowe”).
    # Drugi krok jest WARUNKOWY i zdanie to mówi: przycisk pojawia się tylko, gdy sprawdzenie
    # POTWIERDZI zniknięcie - hamulec passa (drzewo puste, za dużo kandydatów) potwierdzeń nie
    # liczy, więc bezwarunkowe „→ {mark}” obiecywało przycisk, którego wtedy nie ma.
    "grid.tip.copy_unread": {
        "pl": "\n    zeznanie nagłówka jeszcze niezebrane (gdy plik jest na dysku - "
              "{place} → „Przyjmij nowe”; jeśli pliku nie ma już na dysku - "
              "{place} → „{check}” → „{mark}”, który pojawi się pod wynikiem, gdy sprawdzenie "
              "potwierdzi zniknięcie)",
        "en": "\n    header testimony not collected yet (if the file is on disk - "
              "{place} → “Receive new”; if the file is no longer on disk - "
              "{place} → “{check}” → “{mark}”, which appears below the result when the check "
              "confirms the file is gone)",
    },
    # HISTORIA PRZEPROWADZKI, nie ostrzeżenie (D-V-9, wariant rozwojowy). Zdanie jest w czasie
    # przeszłym i bez wykrzyknika, bo nic tu nie wymaga roboty: plik ŻYJE pod adresem z komórki,
    # a stary adres jest odpowiedzią na „przecież to leżało gdzie indziej", nie zgłoszeniem awarii.
    # Wariant mnogi podaje LICZBĘ i pierwszy adres zamiast sklejać listę - tooltip ma się przeczytać
    # jednym spojrzeniem, a pełny wykaz kopii ma własną powierzchnię.
    "grid.tip.former_path": {
        "pl": "\n(wcześniejszy adres: {path})", "en": "\n(former address: {path})",
    },
    "grid.tip.former_paths": {
        "pl": "\n(wcześniejsze adresy ({n}), pierwszy: {path})",
        "en": "\n(former addresses ({n}), first: {path})",
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
    # Przełącznik kolumny bazowej „Obrazy" nad listą keywordów: domyślnie idzie za perspektywą,
    # klik ręki obowiązuje w każdej perspektywie (`FramesView._on_images_toggled`).
    "grid.fields.images": {"pl": "Kolumna „{col}”", "en": "“{col}” column"},
    "grid.fields.images_tip": {
        "pl": "Liczba obrazów w pliku kopii. Domyślnie widoczna tam, gdzie ma treść: "
              "{perspectives}. Twój wybór tutaj obowiązuje w każdej perspektywie.",
        "en": "Number of images in the copy's file. Shown by default where it has content: "
              "{perspectives}. Your choice here applies in every perspective."},
    # Pokrycie pól liczone w tle: lista pod tytułem zostaje z poprzedniego wyniku, a tytuł mówi,
    # że liczby są w drodze - pusta lista w tym czasie wyglądałaby jak archiwum bez pól.
    "grid.fields.title_counting": {"pl": "Pola (kolumny) - liczę pokrycie…",
                                   "en": "Fields (columns) - counting coverage…"},
    "grid.fields.title_failed": {"pl": "Pola (kolumny) - pokrycie nieodświeżone",
                                 "en": "Fields (columns) - coverage not refreshed"},
    "grid.fields.failed_status": {"pl": "Nie policzyłem pokrycia pól: {msg}",
                                  "en": "Could not count field coverage: {msg}"},

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
    "grid.macro.comment_ph": {"pl": "komentarz (opc.)", "en": "comment (opt.)"},
    "grid.macro.comment_tip": {
        "pl": "Pusty - karta zachowuje zastany komentarz. Wpisany - zapis razem z nim; użyj, gdy "
              "zastany komentarz nie mieści się w karcie FITS przy nowej wartości.",
        "en": "Empty - the card keeps its existing comment. Filled in - written together with "
              "it; use it when the existing comment no longer fits the FITS card with the new "
              "value.",
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
    # AR-61: edycja JEDNEJ komórki keyworda - ta sama klinga i szuflada co makro. Pole komentarza
    # edytora bierze brzmienie z `grid.macro.comment_ph`/`comment_tip` (to samo znaczenie).
    "grid.cell.value_ph": {"pl": "wartość", "en": "value"},
    # Podgląd stagingu: komentarz karty, który zapis wniesie (samodzielnie albo przy wartości).
    "grid.preview.comment_only": {"pl": "komentarz → {comment}", "en": "comment → {comment}"},
    "grid.preview.comment_tip": {"pl": " · komentarz → {comment!r}",
                                 "en": " · comment → {comment!r}"},
    "grid.cell.staged": {
        "pl": "Komórka {kw}: {old} → {new} - w szufladzie, czeka na zatwierdzenie",
        "en": "Cell {kw}: {old} → {new} - in the drawer, awaiting commit"},
    "grid.cell.staged_replaced": {
        "pl": "Komórka {kw}: {old} → {new} - zastąpiła wcześniejszą zmianę tej karty w szufladzie",
        "en": "Cell {kw}: {old} → {new} - replaced an earlier change of this card in the drawer"},
    "grid.cell.refused": {
        "pl": "Komórka {kw} - bez zmiany: {reason}",
        "en": "Cell {kw} - not staged: {reason}"},
    "grid.cell.staging_busy": {
        "pl": "Edycja komórki: najpierw zatwierdź albo odrzuć staging nazw",
        "en": "Cell edit: first commit or discard the name staging"},
    "grid.cell.macro_blocked": {
        "pl": {"one": "Makro: w szufladzie czeka {n} edycja komórki - zatwierdź albo odrzuć ją "
                      "przed nowym makrem",
               "few": "Makro: w szufladzie czekają {n} edycje komórek - zatwierdź albo odrzuć je "
                      "przed nowym makrem",
               "many": "Makro: w szufladzie czeka {n} edycji komórek - zatwierdź albo odrzuć je "
                       "przed nowym makrem"},
        "en": {"one": "Macro: {n} cell edit is waiting in the drawer - commit or discard it "
                      "before a new macro",
               "other": "Macro: {n} cell edits are waiting in the drawer - commit or discard them "
                        "before a new macro"}},
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

    # --- TokenRow: grupa flatu, końcowy separator, wielkość liter rodzaju ---
    "grid.token.flatgrp": {"pl": "grupa flatu (FLATGRP)", "en": "flat group (FLATGRP)"},
    "grid.token.trail": {"pl": "końcowe _ (ostatni)", "en": "trailing _ (last)"},
    "grid.token.case_keep": {"pl": "jak w bazie", "en": "as stored"},
    "grid.token.case_upper": {"pl": "WIELKIE", "en": "UPPER"},
    "grid.token.case_lower": {"pl": "małe", "en": "lower"},

    # --- TemplateEditor ---
    "grid.tmpl.title": {"pl": "Wzór nazwy:", "en": "Name pattern:"},
    "grid.tmpl.add_token": {"pl": "+ Token", "en": "+ Token"},
    "grid.tmpl.restore": {"pl": "Przywróć domyślny", "en": "Restore default"},
    # AR-78: wzór zwijany do jednego wiersza ze streszczeniem
    "grid.tmpl.toggle_tip": {
        "pl": "Zwiń albo rozwiń wzór - zwinięty zostawia tabeli więcej wierszy",
        "en": "Collapse or expand the pattern - collapsed leaves more rows for the table",
    },
    "grid.tmpl.summary_empty": {"pl": "pusty wzór", "en": "empty pattern"},
    "grid.tmpl.empty_hint": {
        "pl": "pusty wzór - dodaj token przyciskiem „+ Token”",
        "en": "empty pattern - add a token with the “+ Token” button",
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
    "grid.echo.no_delta_batch": {
        "pl": "jedno źródło czasu - Δ niepoliczalna (brak drugiego do porównania)",
        "en": "one time source - Δ not computable (nothing to compare with)",
    },

    # --- SelectionBar (pasek zbioru) ---
    "grid.sel.proj_tip": {
        "pl": "Materializuj bieżącą perspektywę w drzewo linków/kopii (WBPP feed)",
        "en": "Materialize the current perspective into a tree of links/copies (WBPP feed)",
    },
    "grid.sel.proj_tip_empty": {"pl": "brak klatek w zbiorze", "en": "no frames in the set"},
    # Skład zbioru w tle (AR-27): akcje na CAŁYM widoku czekają, aż tabela pokaże nowy zbiór.
    # Ten sam stan, co faza paska (`busy.read_frames`), więc ten sam czasownik - podpowiedź i odmowa
    # mówiące „Wczytuję zbiór" obok paska „Czytam klatki…" brzmiały jak dwie różne roboty.
    "grid.sel.loading_tip": {"pl": "Czytam klatki… - akcja ruszy na zbiorze, który zaraz pokaże tabela",
                             "en": "Reading frames… - the action will run on the set the table is about to show"},
    "grid.sel.loading_refused": {"pl": "Czytam klatki - spróbuj, gdy tabela pokaże nowy zbiór.",
                                 "en": "Reading frames - try again once the table shows the new set."},
    "grid.sel.project": {"pl": "Wydaj na stół…", "en": "Serve to table…"},
    "grid.sel.release_object": {"pl": "Wydaj obiekt…", "en": "Release object…"},
    "grid.sel.release_object_tip": {
        "pl": "Wydaj komplet obiektu do WBPP: lighty, mastery i surowe flaty, rozdzielone zestawem",
        "en": "Release an object's full set to WBPP: lights, masters and raw flats, split by rig",
    },
    "grid.sel.clear_set": {"pl": "× Wyczyść zbiór", "en": "× Clear set"},
    "grid.sel.clear_tip": {
        "pl": "Zdejmij facety i filtr zaawansowany (perspektywa zostaje)",
        "en": "Remove facets and advanced filter (the perspective stays)",
    },
    "grid.sel.fix_headers": {"pl": "Popraw nagłówki…", "en": "Fix headers…"},
    "grid.sel.tidy_names": {"pl": "Uporządkuj nazwy plików…", "en": "Tidy file names…"},
    "grid.sel.save_view": {"pl": "★ Zapisz widok", "en": "★ Save view"},
    # Oś obiektu na zaznaczeniu (S2b) — JEDNA kontrolka, dwie pozycje menu.
    # Strzałkę rozwinięcia rysuje STYL (`QToolButton.InstantPopup`) — tekst jej nie powtarza
    # (R-S2b-11: kontrolka miała dwa chevrony, własny i natywny).
    "grid.sel.object": {"pl": "Obiekt", "en": "Object"},
    # JEDNA ROBOTA, JEDEN CZASOWNIK (R-S2b-11). Ta sama sprawa nazywała się po drodze na cztery
    # sposoby: „Nazwij zaznaczenie…" (menu) → „Przypisz obiekt" (tytuł okna) → „Przypisz N klatek"
    # (akcept) → „Przypisz obiekt…" (kolejka). Wygrywa „przypisz", i to nie z przewagi liczebnej:
    # tak nazywa tę robotę KANON (`repo.user_assign_object`, event `object.assigned`), a w tym
    # samym menu stoi jej cofnięcie — „Cofnij przypisanie". Para gest↔cofnięcie musi mówić jednym
    # czasownikiem, inaczej user nie widzi, że to dwie strony tej samej rzeczy.
    # Fakt „pisze po ZAZNACZENIU, nie po tym, co widać" niesie tooltip i nagłówek okna, nie etykieta.
    "grid.sel.object_name": {"pl": "Przypisz obiekt…", "en": "Assign object…"},
    "grid.sel.object_clear": {"pl": "Cofnij przypisanie", "en": "Undo assignment"},
    # R-S2b-12: pozycja skrótu. Sam kanon ze strzałką — to nie polecenie („przypisz…"), tylko
    # CEL, w który gest od razu trafi; wielokropka nie ma, bo nic się już nie otworzy.
    "grid.sel.object_recent": {"pl": "→ {canon}", "en": "→ {canon}"},
    "grid.sel.object_empty": {
        "pl": "Zaznacz klatki — ta akcja pisze WYŁĄCZNIE po zaznaczeniu, nie po tym, co widać.",
        "en": "Select frames — this action writes ONLY to the selection, not to what is visible."},
    "grid.sel.object_conflict": {
        "pl": "Zaznaczenie ma {n} różnych obiektów do nadpisania — zawęź je. Nic nie zapisano.",
        "en": "Selection holds {n} different objects to overwrite — narrow it. Nothing was written."},
    "grid.sel.object_named": {
        "pl": {"one": "Nazwano {assigned} z {n} klatki: {canon}",
               "few": "Nazwano {assigned} z {n} klatek: {canon}",
               "many": "Nazwano {assigned} z {n} klatek: {canon}"},
        "en": {"one": "Named {assigned} of {n} frame: {canon}",
               "other": "Named {assigned} of {n} frames: {canon}"}},
    "grid.sel.object_cleared": {
        "pl": {"one": "Cofnięto przypisanie na {assigned} z {n} klatki",
               "few": "Cofnięto przypisanie na {assigned} z {n} klatek",
               "many": "Cofnięto przypisanie na {assigned} z {n} klatek"},
        "en": {"one": "Assignment undone on {assigned} of {n} frame",
               "other": "Assignment undone on {assigned} of {n} frames"}},
    # R-S2b-3: cofnięcie MÓWI, CO ZDJĘŁO — dokładnie jak bliźniacze zdanie nadania („…: NGC 7023").
    # OSOBNY klucz, nie placeholder w zdaniu bazowym: to zdanie ma dwóch wołających o różnych
    # kwargach, więc `{canons}` w nim byłoby `KeyError`-em u drugiego — a bramka i18n pyta
    # o komplet PL/EN i istnienie klucza, NIE o parytet placeholderów z wołającym.
    # ⚠ CZŁON MUSI NAZWAĆ SWÓJ PRZEDMIOT, bo nie stoi już przy zdaniu bazowym (firsthand). Goły
    # dwukropek przyklejał się do OSTATNIEGO członu rozbicia: „…· z nagłówka/regionu: 482: IC434,
    # LMC, Moon (+4)" czyta się jako nazwy tych 482 POMINIĘTYCH, a nazywa 229 ZDJĘTYCH. Zmierzone
    # na żywym archiwum przy zaznaczeniu 711 klatek.
    # …a czasownik należy do GESTU, nie do członu: „zdjęto" przy przywracaniu byłoby nieprawdą
    # o kierunku zapisu. Domyślny klucz opisuje cofnięcie, przywracanie podaje własny.
    "grid.sel.object_canons": {"pl": " · zdjęto z: {canons}", "en": " · removed from: {canons}"},
    "grid.sel.object_canons_restored": {
        "pl": " · oddano: {canons}", "en": " · given back: {canons}"},
    "grid.sel.object_canons_more": {"pl": " (+{n})", "en": " (+{n})"},
    # FC-9: droga powrotu W ZDANIU, nie tylko w tooltipie kontrolki. Recepta cytuje etykiety
    # kontrolki i pozycji menu, więc zmiana któregokolwiek napisu przenosi się tu sama.
    # DWA WARIANTY, BO GEST BYWA WYKONALNY DOPIERO PO INNYM GEŚCIE (bramka pakietu, zarzut
    # blokujący). Gdy cel wyszedł z widoku, zaznaczenie po `refresh()` jest puste, więc
    # `_sync_object_actions` gasi CAŁĄ kontrolkę „Obiekt" - recepta bez słowa „potem" wskazywałaby
    # wtedy napis wyszarzony w tej samej chwili, czyli produkowała dokładnie tę klasę, którą ta
    # paczka zamyka. Kolejność w zdaniu jest kolejnością W CZASIE: najpierw odsłoń, potem przywróć.
    # BEZ WIODĄCEGO „ · ": te dwa człony nie stoją już w zdaniu raportu, tylko na WŁASNYM widżecie
    # paska (FH-2), a separator dokłada `_zlacz_recepty`, gdy członów jest więcej niż jeden.
    "grid.sel.object_clear_undo": {
        "pl": "przywrócisz: {menu} → {action}",
        "en": "to undo this: {menu} → {action}"},
    "grid.sel.object_clear_undo_after": {
        "pl": "potem przywrócisz: {menu} → {action}",
        "en": "then undo it: {menu} → {action}"},
    # AR-71: droga powrotu WYCOFANIA klatki ma własne klucze - brzmienie dziś to samo, co przy
    # cofnięciu przypisania, ale zmiana zdania osi obiektu nie może zmienić recepty osi klatki.
    "grid.sel.frame_retire_undo": {
        "pl": "przywrócisz: {menu} → {action}",
        "en": "to undo this: {menu} → {action}"},
    "grid.sel.frame_retire_undo_after": {
        "pl": "potem przywrócisz: {menu} → {action}",
        "en": "then undo it: {menu} → {action}"},
    # FH-9: droga powrotu PRZYWRÓCENIA przypisania - jej odwrotem jest cofnięcie, więc czasownik
    # jest inny niż wyżej („przywrócisz" mówiłoby o kierunku, którego ten gest nie ma). Para
    # wariantów z tego samego powodu co wyżej: cel bywa najpierw do odsłonięcia.
    "grid.sel.object_restore_undo": {
        "pl": "cofniesz: {menu} → {action}",
        "en": "to take it back: {menu} → {action}"},
    # Odmowy wykonania recepty paska (Z4, Z9) i pozycji menu osi zaznaczenia, które recepta
    # nazywa (AR-70: „Cofnij przypisanie”, „Przywróć cofnięte przypisanie”, „Przywróć klatkę”).
    # Żaden z tych gestów sam nie ruszy po końcu zajętości - inaczej niż gesty izolacji („ruszy po
    # zakończeniu") - więc zdanie mówi, że nic nie zapisano i gest trzeba ponowić. Jedno zdanie na
    # obie drogi, bo recepta woła ten sam slot, co pozycja menu.
    "grid.recipe.busy_stage": {
        "pl": "Trwa etap Dostawy - nic nie zapisano; ponów gest po jego zakończeniu.",
        "en": "An Intake stage is running - nothing was saved; repeat the gesture after it finishes."},
    "grid.recipe.busy_write": {
        "pl": "Trwa zapis nagłówków do plików - nic nie zapisano; ponów gest po jego zakończeniu.",
        "en": "A header write to files is in progress - nothing was saved; repeat the gesture after "
              "it finishes."},
    "grid.recipe.nothing_to_reveal": {
        "pl": "Zbiór nie jest już zawężony - nie ma czego odsłaniać.",
        "en": "The set is no longer narrowed - there is nothing to reveal."},
    "grid.sel.object_restore_undo_after": {
        "pl": "potem cofniesz: {menu} → {action}",
        "en": "then take it back: {menu} → {action}"},
    # FC-2: gest bywa gestem, który WYPYCHA własny cel z widoku - przy facecie „Obiekt" cofnięcie
    # zostawia widok pusty (zmierzone: 43 → 0 klatek), bo facet liczy po `f.object_id`. Klucz jest
    # WSPÓLNY DLA OBU OSI zaznaczenia (obiekt i żywotność klatki): na osi klatki wypchnięcie celu
    # jest wręcz regułą, bo wycofanie zdejmuje klatkę z kubełków roboczych. Trzecia oś ma odtąd
    # gotową frazę zamiast trzeciej kopii.
    "grid.sel.out_of_view": {
        "pl": " · poza widokiem: {n}", "en": " · out of view: {n}"},
    # DWIE RECEPTY, NIE TRZY - i to jest pomiar, nie skrót. Przełączenie perspektywy zeruje TAKŻE
    # facety i filtr (`_on_perspective`), a „Przegląd" nie ma ani trimu, ani filtra, więc przy obu
    # zawężeniach naraz jeden gest odsłania wszystko. Wariant „zdejmij oba" kazałby zrobić dwa
    # gesty tam, gdzie wystarcza jeden. „× Wyczyść zbiór" zostaje tam, gdzie user ma ZACHOWAĆ
    # perspektywę - jest wtedy węższy, czyli tańszy dla jego zbioru.
    # RECEPTA WYSZŁA Z NAWIASU RAZEM Z WYJŚCIEM ZE ZDANIA (FH-2): na własnym widżecie nie jest już
    # wtrętem w raporcie, tylko samodzielną instrukcją, a nawias sugerowałby uwagę na marginesie.
    # RECEPTA NAZYWA SWÓJ CEL (`grid.sel.reveal_target`): dawne „odsłoni je …" odsyłało do zdania
    # raportu, a recepta żyje dłużej niż ono - po przejściu do innego zbioru (Znajdź „M64" po geście
    # na NGC3623) „je" nie miało odniesienia, a klik czyścił bieżący widok. Dwa klucze niżej niosą
    # wyłącznie GEST odsłonięcia (`{how}` zdania celu); liczba i obiekt idą z celu gestu.
    "grid.sel.out_of_view_set": {
        "pl": "„{action}”", "en": "“{action}”"},
    "grid.sel.out_of_view_persp": {
        "pl": "perspektywa „{perspective}”",
        "en": "the “{perspective}” perspective"},
    # Odmiana po klatkach celu niewidocznych na ekranie (biernik: „odsłonisz 1 klatkę"); `{obj}` =
    # `grid.sel.reveal_object` albo pusty, gdy gest nie ma jednego obiektu.
    "grid.sel.reveal_target": {
        "pl": {"one": "odsłonisz {n} klatkę{obj}: {how}", "few": "odsłonisz {n} klatki{obj}: {how}",
               "many": "odsłonisz {n} klatek{obj}: {how}"},
        "en": {"one": "to reveal {n} frame{obj}: {how}", "other": "to reveal {n} frames{obj}: {how}"}},
    "grid.sel.reveal_object": {"pl": " {canon}", "en": " of {canon}"},
    "grid.sel.object_restore": {"pl": "Przywróć cofnięte przypisanie",
                                "en": "Restore undone assignment"},
    "grid.sel.object_restored": {
        "pl": {"one": "Przywrócono przypisanie na {assigned} z {n} klatki",
               "few": "Przywrócono przypisanie na {assigned} z {n} klatek",
               "many": "Przywrócono przypisanie na {assigned} z {n} klatek"},
        "en": {"one": "Assignment restored on {assigned} of {n} frame",
               "other": "Assignment restored on {assigned} of {n} frames"}},
    # Rozbicie PER FAKT — każda przyczyna osobno, bo znaczą dla człowieka co innego.
    "grid.sel.object_skip_kind": {"pl": " · kalibracja: {n}", "en": " · calibration: {n}"},
    "grid.sel.object_skip_source": {"pl": " · z nagłówka/regionu: {n}",
                                    "en": " · from header/region: {n}"},
    # Osobno od `_source`, bo to INNA PRZYCZYNA (wizytacja S3): klatka bez obiektu nie miała czego
    # cofać i nie ma przy niej żadnego nagłówka do naprawienia. Sklejone dawały receptę, której
    # nie da się wykonać — user czytał „z nagłówka/regionu" o klatce bez nagłówka.
    "grid.sel.object_skip_nothing": {"pl": " · nie było czego cofać: {n}",
                                     "en": " · nothing to undo: {n}"},
    # FC-6: ten sam fakt przy PRZYWRACANIU - klatka nie jest nagrobkiem. Osobny klucz, bo czasownik
    # należy do GESTU, nie do członu (ten sam powód, co `object_canons_restored`): „nie było czego
    # cofać" pod zdaniem „Przywrócono…" byłoby nieprawdą o kierunku zapisu. Podaje go wołający
    # (`nothing_key`), pozostałe człony rozbicia są neutralne wobec kierunku i zostają wspólne.
    "grid.sel.object_restore_skip_nothing": {"pl": " · nie było czego przywrócić: {n}",
                                             "en": " · nothing to restore: {n}"},
    # FC-6: nagrobek BEZ pamięci (baza-dawca sprzed 0017) jest CZŁONEM rozbicia, nie osobnym
    # zdaniem. Dwa dawne zdania („nie ma czego przywrócić" przy zerze, „pominięto N…" jako ogon)
    # były drugą gramatyką tej samej osi: sąsiedni gest w tej samej sytuacji mówi „0 z N"
    # z rozbiciem. Osobno od „nie było czego przywrócić", bo klatka JEST nagrobkiem, tylko nie
    # pamięta, co ręka zdjęła - ręką nic tu się nie naprawi. Jeden klucz wystarcza: człon pojawia
    # się wyłącznie przy przywracaniu (klingi zostawiają licznik na zerze).
    "grid.sel.object_skip_no_memory": {"pl": " · bez zapamiętanego obiektu: {n}",
                                       "en": " · without a remembered object: {n}"},
    "grid.sel.object_skip_drift": {"pl": " · zmieniły się w międzyczasie: {n}",
                                   "en": " · changed meanwhile: {n}"},
    # Osobno od `_drift`: klinga ODMÓWIŁA (`ValueError` - konflikt aliasu, klatka spoza bazy), więc
    # „zmieniły się w międzyczasie" kłamałoby o stanie, który się nie ruszył. Człon liczy transakcję,
    # która padła, i te, do których gest już nie doszedł - żadna z nich nie jest zapisana.
    "grid.sel.object_skip_failed": {"pl": " · nie zapisano, klinga odmówiła: {n}",
                                    "en": " · not written, the blade refused: {n}"},
    # NIE pominięcie, tylko skład tego, co zapisano (D-OW-7) — „w tym", nie „poza tym". Gotowy
    # obraz jest jedyną klatką, przy której zapis osi sięga rodowodu, więc user ma prawo wiedzieć,
    # że go dotknął. Dawne brzmienie („· gotowe obrazy: N" wśród pominięć) po odwróceniu decyzji
    # mówiłoby dokładnie odwrotnie do prawdy.
    # ODMIENIONY, bo najczęstszy przypadek to JEDEN stos w zaznaczeniu (R-S3-8): „w tym gotowe
    # obrazy: 1" było widoczne w trzech miejscach naraz — w zdaniu po geście z dwóch powierzchni
    # i (od R-S3-8) w tooltipie kontrolki przed gestem.
    "grid.sel.object_stacks": {
        "pl": {"one": " · w tym gotowy obraz: {n}",
               "few": " · w tym gotowe obrazy: {n}",
               "many": " · w tym gotowych obrazów: {n}"},
        "en": {"one": " · including {n} finished image",
               "other": " · including {n} finished images"},
    },
    # POWÓD WYGASZENIA jako tooltip (R-S2b-8) — „wygaszony przycisk tłumaczy się SAM". Każdy powód
    # niesie RECEPTĘ, nie samą diagnozę: user ma się dowiedzieć, gdzie ta nazwa się poprawia, a nie
    # tylko że tutaj nie. Wariant AKTYWNY mówi, ile klatek gest ruszy — to ta sama liczba, którą
    # pokaże okno, więc poznaje ją PRZED kliknięciem.
    "grid.sel.object_tip_empty": {
        "pl": "Zaznacz klatki — ta akcja pisze wyłącznie po zaznaczeniu.",
        "en": "Select frames — this action writes only to the selection."},
    # TRZECIA DROGA W TYM SAMYM ZDANIU, co dwie pierwsze (R-S2b-3) — inaczej tooltip zapowiadałby
    # dwie liczby przy trzech akcjach w menu, czyli klasa R-S3-8 od nowa.
    "grid.sel.object_tip_restorable": {"pl": " · do przywrócenia: {n}",
                                       "en": " · to restore: {n}"},
    "grid.sel.object_tip_no_lights": {
        "pl": "Zaznaczenie nie ma klatek nieba. Kalibracja obiektu nie ma z definicji.",
        "en": "The selection has no sky frames. Calibration has no object by definition."},
    "grid.sel.object_tip_stacks": {
        "pl": "Same gotowe obrazy z nazwą z pliku — tę poprawia się kartą OBJECT "
              "(Porządki → „Napraw nagłówek…”).",
        "en": "Only finished images named from the file — fix that with the OBJECT card "
              "(Tasks → “Fix header…”)."},
    "grid.sel.object_tip_header": {
        "pl": "Nazwa pochodzi z nagłówka — poprawia się ją w PLIKU "
              "(Porządki → „Napraw nagłówek…”), nie w bazie.",
        "en": "The name comes from the header — fix it in the FILE "
              "(Tasks → “Fix header…”), not in the database."},
    "grid.sel.object_tip_ready": {
        "pl": "Do nazwania: {namable} · do cofnięcia: {clearable}",
        "en": "To name: {namable} · to undo: {clearable}"},

    # --- Panel RODOWODU gotowego stosu (I-2d, P-I) ---
    # Słownictwo trzyma jedną granicę: „weszło" = fakt zapisany, „wynika z czasu" = kandydat.
    # Nigdzie nie mówimy „na pewno" o czymś, czego dowodem jest wyłącznie okno czasu.
    "grid.sel.lineage": {"pl": "Rodowód…", "en": "Lineage…"},
    # Tooltip był JEDYNYM drogowskazem do panelu i po dołożeniu osi kalibracji ZAPRZECZAŁ jej
    # istnieniu („zaznacz JEDEN stos"), czyli zniechęcał do zaznaczenia klatki nieba — drugiej
    # połowy tego, co panel umie. Zdanie powitalne wymienia obie osie, ale widać je dopiero
    # PO otwarciu panelu, więc nie jest afordancją.
    "grid.sel.lineage_tip": {
        "pl": "Skąd ta klatka ma swój kształt — zaznacz gotowy obraz (z czego powstał) "
              "albo klatkę nieba (czym ją skalibrowano)",
        "en": "Where this frame gets its shape — select a finished image (what it was made of) "
              "or a sky frame (what calibrated it)",
    },
    # Odmiana przez `t_plural` [wiz #15]: „Weszło 1 klatek" czytało się jak błąd bazy, a bliźniacza
    # flaga `grid.lin.flag.twins` w TYM SAMYM panelu odmieniała się poprawnie — rozjazd był widoczny
    # obok siebie. Godziny idą dodatkowym `kw`, bo forma zależy WYŁĄCZNIE od liczby klatek.
    "grid.lin.head": {
        "pl": {"one": "Weszła {n} klatka · {hours} h",
               "few": "Weszły {n} klatki · {hours} h",
               "many": "Weszło {n} klatek · {hours} h"},
        "en": {"one": "{n} frame went in · {hours} h",
               "other": "{n} frames went in · {hours} h"},
    },
    "grid.lin.confirm": {"pl": "Potwierdź zaznaczone", "en": "Confirm selected"},
    "grid.lin.confirm_tip": {
        "pl": "Zapisz, że te klatki NAPRAWDĘ weszły w ten obraz (przestają być kandydatami)",
        "en": "Record that these frames REALLY went into this image (they stop being candidates)",
    },
    "grid.lin.reject": {"pl": "Odrzuć zaznaczone", "en": "Reject selected"},
    "grid.lin.reject_tip": {
        "pl": "Zapisz, że te klatki NIE weszły — zostaną na liście jako odrzucone i nie wliczą się "
              "do godzin",
        "en": "Record that these frames did NOT go in — they stay listed as rejected and stop "
              "counting towards the hours",
    },
    "grid.lin.judged_confirmed": {"pl": "Potwierdzono {n}", "en": "Confirmed {n}"},
    "grid.lin.judged_excluded": {"pl": "Odrzucono {n}", "en": "Rejected {n}"},
    "grid.lin.judged_none": {
        "pl": "Bez zmian — te klatki miały już taki werdykt",
        "en": "No change — those frames already carried this verdict",
    },
    "grid.lin.src.history": {"pl": "plik zeznał", "en": "file testified"},
    # AR-102: zbiór dokładny z żniw - WBPP zintegrował dokładnie te lighty, które Horreum wydał.
    "grid.lin.src.harvest": {"pl": "z wydania", "en": "from the release"},
    "grid.lin.src.window": {"pl": "wynika z czasu", "en": "inferred from time"},
    "grid.lin.src.user": {"pl": "Twoja decyzja", "en": "your decision"},
    "grid.lin.src.excluded": {"pl": "odrzucone", "en": "rejected"},
    # Zdania powitalne panelu opisują OBIE osie od C3: gotowy obraz mówi, z czego powstał, klatka
    # nieba — czym ją skalibrowano. Zdanie wymieniające tylko stosy kłamałoby o połowie panelu.
    "grid.lin.hint.none": {
        "pl": "Zaznacz w tabeli gotowy obraz (zobaczysz, z czego powstał) albo klatkę nieba "
              "(zobaczysz, czym ją skalibrowano).",
        "en": "Select a finished image (to see what it was made of) or a sky frame (to see what "
              "calibrated it).",
    },
    "grid.lin.hint.not_stack": {
        "pl": "Rodowód mają gotowe obrazy i klatki nieba — klatka kalibracyjna sama jest "
              "narzędziem, nie ma czym być skalibrowana.",
        "en": "Lineage belongs to finished images and sky frames — a calibration frame is the tool "
              "itself, so nothing calibrates it.",
    },
    # --- oś KALIBRACJI w panelu (C3, Issue #6) ---
    # Nagłówek: nazwa klatki i stan KAŻDEJ klasy osobno (wizytacja 0802) - dawne „N z 2 klas” zrównywało
    # „nie ma” z „nie policzono”, a „klas” było żargonem.
    "grid.lin.cal.head": {"pl": "{name} - {classes}", "en": "{name} - {classes}"},
    "grid.lin.cal.head.class": {"pl": "{rel}: {state}", "en": "{rel}: {state}"},
    "grid.lin.cal.head.linked": {"pl": "jest", "en": "linked"},
    "grid.lin.cal.head.pending": {"pl": "nie policzono", "en": "not computed"},
    "grid.lin.cal.head.gap": {"pl": "brak", "en": "missing"},
    "grid.lin.cal.head.linked_inactive": {"pl": "jest (nieaktywny)", "en": "linked (inactive)"},
    "grid.lin.cal.head.linked_mismatch": {"pl": "jest (inna nastawa)", "en": "linked (other settings)"},
    # Niezgodność nastawy kandydata albo powiązanego mastera wobec lightu - człony `profile_key`
    # (`lineage._POLA_PRZEPISU`): najpierw wartość mastera, potem lightu.
    "grid.lin.cal.mismatch": {"pl": "⚠ inna nastawa: {what}", "en": "⚠ other settings: {what}"},
    "grid.lin.cal.mis.filt": {"pl": "filtr {master} ≠ {light}", "en": "filter {master} ≠ {light}"},
    "grid.lin.cal.mis.tel": {"pl": "inny teleskop", "en": "other telescope"},
    "grid.lin.cal.mis.bin": {"pl": "binning {master} ≠ {light}", "en": "binning {master} ≠ {light}"},
    "grid.lin.cal.mis.exp": {"pl": "ekspozycja {master} s ≠ {light} s",
                             "en": "exposure {master} s ≠ {light} s"},
    "grid.lin.cal.mis.t": {"pl": "temperatura {master} °C ≠ {light} °C",
                           "en": "temperature {master} °C ≠ {light} °C"},
    "grid.lin.cal.mis.g": {"pl": "gain {master} ≠ {light}", "en": "gain {master} ≠ {light}"},
    "grid.lin.cal.mis.o": {"pl": "offset {master} ≠ {light}", "en": "offset {master} ≠ {light}"},
    "grid.lin.cal.mis.no_filter": {"pl": "bez filtra", "en": "no filter"},
    "grid.lin.cal.mis.unknown": {"pl": "nastawa nieznana", "en": "settings unknown"},
    "grid.lin.cal.pick_ok": {"pl": "Wskaż", "en": "Choose"},
    "grid.lin.cal.pick_cancel": {"pl": "Anuluj", "en": "Cancel"},
    # Kalibrator nieaktywny (wycofany, zastąpiony, bez pliku) - wskazanie ręki go nie opuszcza samo.
    "grid.lin.cal.inactive": {
        "pl": "⚠ master wycofany, zastąpiony albo bez pliku - wskaż inny",
        "en": "⚠ master retired, replaced or without a file - choose another",
    },
    "grid.lin.cal.tip_busy": {
        "pl": "Trwa etap w Dostawie albo zapis do plików - gesty wrócą, gdy się skończy.",
        "en": "A Delivery step or a write to files is running - the gestures return when it ends.",
    },
    "grid.lin.cal.restore_tip_none": {
        "pl": "Zdejmij Twój wybór - przepis nie ma kandydata, więc klatka zostanie bez kalibratora.",
        "en": "Remove your choice - the recipe has no candidate, so the frame stays without a "
              "calibrator.",
    },
    "grid.lin.cal.restored_no_auto": {
        "pl": "Zdjęto Twój wybór: {rel} - przepis nie ma kandydata, klatka została bez kalibratora",
        "en": "Your choice removed: {rel} - the recipe has no candidate, the frame has no "
              "calibrator now",
    },
    "grid.lin.cal.db_busy": {
        "pl": "Nie zapisano: baza jest zajęta innym zapisem - spróbuj za chwilę.",
        "en": "Not saved: the database is busy with another write - try again in a moment.",
    },
    "grid.lin.cal.vanished": {
        "pl": "master #{id} - plik zniknął z dysku",
        "en": "master #{id} - the file has vanished from disk",
    },
    "grid.lin.cal.delta": {"pl": "Δ {n} dni", "en": "Δ {n} days"},
    "grid.lin.cal.src.horreum": {"pl": "dobrane z przepisu", "en": "matched by recipe"},
    "grid.lin.cal.src.user": {"pl": "Twoja decyzja", "en": "your decision"},
    "grid.lin.cal.src.wbpp": {"pl": "z historii obróbki", "en": "from processing history"},
    "grid.lin.cal.off_recipe": {"pl": "spoza przepisu", "en": "outside the recipe"},
    "grid.lin.cal.gap.not_calibrated": {
        "pl": "przepisy nie są jeszcze policzone - uruchom etap Kalibracja w Dostawie",
        "en": "recipes have not been computed yet - run the Calibration step in Delivery",
    },
    "grid.lin.cal.rel.dark": {"pl": "ciemność (dark)", "en": "dark"},
    "grid.lin.cal.rel.flat": {"pl": "pole (flat)", "en": "flat"},
    # Nieliczone to OSTRZEŻENIE, nie wygaszenie: robota na jedno kliknięcie, nie brak.
    "grid.lin.cal.state.pending": {
        "pl": "⚠ master jest - powiązania jeszcze nie policzono",
        "en": "⚠ master exists - the link has not been computed yet",
    },
    "grid.lin.cal.pending": {
        "pl": "⚠ uruchom etap Rodowód („Policz teraz”), żeby powiązać to, co już jest w archiwum",
        "en": "⚠ run the Lineage step (“Count now”) to link what the archive already holds",
    },
    # --- gesty ręki na osi kalibracji (E4-5) ---
    "grid.lin.cal.pick": {"pl": "Wskaż kalibrator…", "en": "Choose calibrator…"},
    "grid.lin.cal.pick_tip": {
        "pl": "Wybierz master dla zaznaczonego wiersza - także spoza przepisu. Twój wybór "
              "przetrwa kolejne przeliczenia.",
        "en": "Choose the master for the selected row - also outside the recipe. Your choice "
              "survives later recomputations.",
    },
    "grid.lin.cal.pick_tip_none": {
        "pl": "Brak masterów tej klasy z tej samej kamery - nie ma czego wskazać.",
        "en": "No masters of this kind from the same camera - nothing to choose.",
    },
    "grid.lin.cal.tip_select": {
        "pl": "Zaznacz na liście wiersz ciemności albo pola.",
        "en": "Select the dark or the flat row in the list.",
    },
    "grid.lin.cal.pick_title": {"pl": "Wskaż kalibrator", "en": "Choose calibrator"},
    "grid.lin.cal.pick_prompt": {
        "pl": "Master dla: {rel}. Najpierw z przepisu (najbliższy w czasie u góry), "
              "potem SPOZA PRZEPISU.",
        "en": "Master for: {rel}. Recipe matches first (closest in time on top), "
              "then OUTSIDE THE RECIPE.",
    },
    "grid.lin.cal.cand.recipe": {"pl": "z przepisu", "en": "recipe"},
    "grid.lin.cal.cand.off": {"pl": "SPOZA PRZEPISU", "en": "OUTSIDE THE RECIPE"},
    "grid.lin.cal.cand.current": {"pl": "obecny", "en": "current"},
    "grid.lin.cal.cand.no_time": {"pl": "bez daty", "en": "no date"},
    "grid.lin.cal.restore": {"pl": "Przywróć automat", "en": "Restore automatic"},
    "grid.lin.cal.restore_tip": {
        "pl": "Zdejmij Twój wybór - program dobierze kalibrator z przepisu i od razu przeliczy.",
        "en": "Remove your choice - the program picks the calibrator by recipe and recomputes now.",
    },
    "grid.lin.cal.restore_tip_auto": {
        "pl": "Ten kalibrator dobrał program - nie ma czego przywracać.",
        "en": "The program chose this calibrator - nothing to restore.",
    },
    "grid.lin.cal.count": {"pl": "Policz teraz", "en": "Count now"},
    "grid.lin.cal.count_tip": {
        "pl": "Uruchom etap Rodowód (trwa chwilę) - panel odświeży się sam.",
        "en": "Run the Lineage step (takes a moment) - the panel refreshes by itself.",
    },
    "grid.lin.cal.picked": {
        "pl": "Zapisano Twój kalibrator: {rel} - przeliczenia go nie zmienią",
        "en": "Your calibrator is saved: {rel} - recomputations will not change it",
    },
    "grid.lin.cal.picked_none": {
        "pl": "Bez zmian - ten kalibrator ({rel}) już jest Twoim wyborem",
        "en": "No change - this calibrator ({rel}) is already your choice",
    },
    "grid.lin.cal.restored": {"pl": "Zdjęto Twój wybór: {rel}", "en": "Your choice removed: {rel}"},
    "grid.lin.cal.restored_none": {
        "pl": "Nic do przywrócenia - wybór zmienił się w międzyczasie",
        "en": "Nothing to restore - the choice changed in the meantime",
    },
    "grid.lin.cal.counting": {
        "pl": "liczę rodowód kalibracji - panel odświeży się sam",
        "en": "computing calibration lineage - the panel refreshes by itself",
    },
    "grid.lin.cal.count_busy": {
        "pl": "rodowodu NIE policzono: {reason}",
        "en": "lineage NOT computed: {reason}",
    },
    "grid.lin.cal.count_no_host": {
        "pl": "uruchom etap Rodowód w Dostawie",
        "en": "run the Lineage step in Delivery",
    },
    # Odmowy klingi (`repo.CALIBRATION_REFUSALS`) - zapis się nie odbył, panel pokazuje stan z bazy.
    "grid.lin.cal.refused.not_light": {
        "pl": "Nie zapisano: ta klatka nie jest już klatką nieba.",
        "en": "Not saved: this frame is no longer a sky frame.",
    },
    "grid.lin.cal.refused.not_master": {
        "pl": "Nie zapisano: wybrana klatka nie jest masterem tej klasy.",
        "en": "Not saved: the chosen frame is not a master of this kind.",
    },
    "grid.lin.cal.refused.inactive": {
        "pl": "Nie zapisano: wybrany master jest wycofany albo zastąpiony.",
        "en": "Not saved: the chosen master is retired or replaced.",
    },
    "grid.lin.cal.refused.camera": {
        "pl": "Nie zapisano: wybrany master pochodzi z innej kamery.",
        "en": "Not saved: the chosen master comes from another camera.",
    },
    "grid.lin.cal.refused.drift": {
        "pl": "Nie zapisano: kalibrator zmienił się w międzyczasie - panel pokazuje stan bieżący, "
              "wybierz jeszcze raz.",
        "en": "Not saved: the calibrator changed in the meantime - the panel shows the current "
              "state, choose again.",
    },
    "grid.lin.cal.gap.incomplete_recipe": {
        "pl": "nie wiadomo, czego szukać: klatka nie podaje pełnej nastawy",
        "en": "nothing to look for: the frame does not give its full settings",
    },
    "grid.lin.cal.gap.no_profile": {
        "pl": "brak w archiwum czegokolwiek o tej nastawie",
        "en": "the archive holds nothing with these settings",
    },
    "grid.lin.cal.gap.no_master": {
        "pl": "są klatki surowe, nie ma złożonego mastera",
        "en": "raw frames exist, no stacked master",
    },
    "grid.lin.hint.many": {
        "pl": "Zaznacz DOKŁADNIE jedną klatkę — rodowód opisuje pojedynczą klatkę.",
        "en": "Select EXACTLY one frame — lineage describes a single frame.",
    },
    "grid.lin.hint.not_computed": {
        "pl": "Rodowodu jeszcze nie liczono. Wciągnij stosy w Dostawie — policzy się przy okazji.",
        "en": "Lineage has not been computed yet. Pull in stacks in Delivery — it is computed there.",
    },
    "grid.lin.reason.degenerate_window": {
        "pl": "Nie wiem, z czego powstał: nagłówek opisuje jedną klatkę, nie całą serię.",
        "en": "Unknown source: the header describes a single frame, not a whole series.",
    },
    "grid.lin.reason.history_mismatch": {
        "pl": "Nie wiem, z czego powstał: plik zeznaje inne klatki, niż wychodzi z czasu.",
        "en": "Unknown source: the file testifies to different frames than the time window gives.",
    },
    "grid.lin.reason.no_object": {
        "pl": "Nie wiem, z czego powstał: obraz nie ma rozpoznanego obiektu.",
        "en": "Unknown source: the image has no recognised object.",
    },
    "grid.lin.reason.no_window": {
        "pl": "Nie wiem, z czego powstał: nagłówek nie podaje czasu początku i końca.",
        "en": "Unknown source: the header gives no start and end time.",
    },
    "grid.lin.reason.no_candidates": {
        "pl": "Nie wiem, z czego powstał: w tym czasie nie ma w archiwum ani jednej pasującej klatki.",
        "en": "Unknown source: the archive holds no matching frame from that time.",
    },
    "grid.lin.reason.telescope_mismatch": {
        "pl": "Nie wiem, z czego powstał: klatki z tej nocy są z innego teleskopu niż zapisany "
              "w obrazie.",
        "en": "Unknown source: that night's frames come from a different telescope than the image "
              "records.",
    },
    "grid.lin.cand.night": {"pl": "Noc:", "en": "Night:"},
    "grid.lin.cand.night_master": {
        "pl": "{night} - noc obrazu ({n})",
        "en": "{night} - image's night ({n})",
    },
    "grid.lin.cand.night_other": {"pl": "{night} ({n})", "en": "{night} ({n})"},
    # LICZBA W TYM ZDANIU ODMIENIA SIĘ, bo bywa jedynką: obraz z pustą nocą własną i JEDNĄ klatką
    # w nocy sąsiedniej dostawał „1 klatek w pozostałych" (bramka pakietu 3a, 0808). Zdanie liczy
    # materiał, więc nie ma prawa mówić o nim gramatyką listy.
    "grid.lin.cand.empty_night": {
        "pl": {"one": "Tej nocy archiwum nie ma pasującego materiału - wybierz inną noc "
                      "({n} klatka w pozostałych).",
               "few": "Tej nocy archiwum nie ma pasującego materiału - wybierz inną noc "
                      "({n} klatki w pozostałych).",
               "many": "Tej nocy archiwum nie ma pasującego materiału - wybierz inną noc "
                       "({n} klatek w pozostałych)."},
        "en": {"one": "The archive holds no matching material that night - pick another one "
                      "({n} frame in the rest).",
               "other": "The archive holds no matching material that night - pick another one "
                        "({n} frames in the rest)."},
    },
    "grid.lin.cand.empty_all": {
        "pl": "Archiwum nie ma ani jednej klatki tego obiektu o zgodnym filtrze i ekspozycji.",
        "en": "The archive holds no frame of this object with a matching filter and exposure.",
    },
    # TRZECIA PUSTKA, NIE ODMIANA DRUGIEJ: klatki SĄ, brakuje zegara tego obrazu. Zdanie ma nieść
    # LICZBĘ (żeby było widać stawkę) i RECEPTĘ (gest stoi tuż pod nim), bo bez nich panel mówił
    # tym obrazom, że archiwum jest puste — a stało w nim po 36 klatek (bramka pakietu 3a, 0808).
    "grid.lin.cand.no_reference": {
        "pl": {"one": "Jest {n} pasująca klatka z lustrzanki, ale nie znam zegara tego obrazu - "
                      "wskaż odniesienie czasu przyciskiem niżej.",
               "few": "Są {n} pasujące klatki z lustrzanki, ale nie znam zegara tego obrazu - "
                      "wskaż odniesienie czasu przyciskiem niżej.",
               "many": "Jest {n} pasujących klatek z lustrzanki, ale nie znam zegara tego obrazu - "
                       "wskaż odniesienie czasu przyciskiem niżej."},
        "en": {"one": "There is {n} matching DSLR frame, but this image's clock is unknown - "
                      "point the time reference with the button below.",
               "other": "There are {n} matching DSLR frames, but this image's clock is unknown - "
                        "point the time reference with the button below."},
    },
    "grid.lin.offset": {
        "pl": "Wskaż odniesienie czasu…",
        "en": "Set time reference…",
    },
    "grid.lin.offset_set": {
        "pl": "Odniesienie: {hours} h — zmień…",
        "en": "Time reference: {hours} h — change…",
    },
    "grid.lin.offset_title": {
        "pl": "Odniesienie czasu obrazu",
        "en": "Image time reference",
    },
    "grid.lin.offset_prompt": {
        "pl": "O ile godzin zegar aparatu wyprzedzał UTC, gdy powstawał ten materiał?\n"
              "(Polska zimą: +1 · Polska latem: +2 · zapis w UTC: 0)",
        "en": "How many hours was the camera clock ahead of UTC when this material was shot?\n"
              "(Poland in winter: +1 · Poland in summer: +2 · recorded in UTC: 0)",
    },
    # TRZY ZDANIA, BO TO TRZY RÓŻNE STANY — a nie odcienie jednego: gest bez gospodarza (nie ma
    # czym przeliczyć), gest domknięty (liczy się już) i gest zapisany przy zajętym silniku.
    # Ostatnie mówi o OBU połówkach: zapis się udał, przeliczenie nie ruszyło i wiadomo dlaczego.
    "grid.lin.offset_saved": {
        "pl": "Odniesienie zapisane: {hours} h. Policz rodowód stosów w Dostawie, żeby dobrać klatki.",
        "en": "Time reference saved: {hours} h. Compute stack lineage in Delivery to match frames.",
    },
    "grid.lin.offset_saved_counting": {
        "pl": "Odniesienie zapisane: {hours} h — liczę rodowód stosów…",
        "en": "Time reference saved: {hours} h — computing stack lineage…",
    },
    "grid.lin.offset_saved_busy": {
        "pl": "Odniesienie zapisane: {hours} h. Rodowód NIE policzony: {reason}",
        "en": "Time reference saved: {hours} h. Lineage NOT computed: {reason}",
    },
    # NA CO GEST ZADZIAŁAŁ (G2-3d): wskazanie zegara o dobę obok przechodzi walidację zakresu,
    # więc jedynym sprawdzianem jest to, ile materiału ten zegar odblokował. Człon dokleja się
    # do KAŻDEGO z trzech zdań wyżej i mówi też zero - to ono odróżnia „zegar nie miał czego
    # odblokować" od „materiał czekał i właśnie ruszył".
    "grid.lin.offset_waiting": {
        "pl": " · klatek czekało na zegar: {n}",
        "en": " · frames were waiting for a clock: {n}",
    },
    # Powód, który przestał być prawdą, zanim ktokolwiek policzył go ponownie (firsthand 0808).
    # Nie udajemy, że wiemy więcej: mówimy, że TEN ZAPIS jest starszy niż zmiana, i gdzie go odświeżyć.
    "grid.lin.reason.stale": {
        "pl": "Rodowód policzono, zanim zmieniłeś ten obraz — zapis poniżej jest nieaktualny. "
              "Policz rodowód w Dostawie, żeby zobaczyć bieżący stan.",
        "en": "Lineage was computed before you changed this image — the record below is out of "
              "date. Compute lineage in Delivery to see the current state.",
    },
    "grid.lin.reason.offset_unknown": {
        "pl": "Nie wiem, z czego powstał: materiał leży w plikach RAW, a te liczą czas w zegarze "
              "aparatu. Wskaż odniesienie tego obrazu, a klatki się dobiorą.",
        "en": "Unknown source: the material sits in RAW files, which count time on the camera's "
              "clock. Point out this image's time reference and the frames will match.",
    },
    "grid.lin.flag.ambiguous": {
        "pl": "⚠ część tych klatek wchodzi też w inny obraz",
        "en": "⚠ some of these frames also go into another image",
    },
    # Odmiana przez `t_plural` [#11]: n=1 jest tu przypadkiem TYPOWYM (para plik + `_drizzle_1x`),
    # a „1 inne wersje" czytałoby się jak błąd — ta sama lekcja co przy liczniku zaznaczenia.
    # Podmiotem jest „zestaw" (liczba pojedyncza, „ma"), a liczba wersji stoi w bierniku.
    "grid.lin.flag.twins": {
        "pl": {"one": "ten sam zestaw klatek ma jeszcze {n} inną wersję obrazu",
               "few": "ten sam zestaw klatek ma jeszcze {n} inne wersje obrazu",
               "many": "ten sam zestaw klatek ma jeszcze {n} innych wersji obrazu"},
        "en": {"one": "{n} other version of the image uses the same set of frames",
               "other": "{n} other versions of the image use the same set of frames"},
    },
    "grid.lin.flag.telescope": {
        "pl": "⚠ obraz zapisał inny teleskop niż jego klatki (karta do naprawy)",
        "en": "⚠ the image records a different telescope than its frames (header to fix)",
    },
    # UWAGA OBOK WERDYKTU (G2-1d): pula mieszana RAW+FITS - rodowód (albo inny powód) stoi, a obok
    # leżą RAW-y, których nie da się umieścić w czasie. Zdanie niesie LICZBĘ i RECEPTĘ (gest
    # odniesienia stoi pod nim), jak `grid.lin.cand.no_reference`.
    "grid.lin.flag.raw_unreferenced": {
        "pl": {"one": "⚠ {n} pasującej klatki z lustrzanki nie umiem umieścić w czasie - "
                      "wskaż odniesienie zegara",
               "few": "⚠ {n} pasujących klatek z lustrzanki nie umiem umieścić w czasie - "
                      "wskaż odniesienie zegara",
               "many": "⚠ {n} pasujących klatek z lustrzanki nie umiem umieścić w czasie - "
                       "wskaż odniesienie zegara"},
        "en": {"one": "⚠ {n} matching DSLR frame cannot be placed in time - "
                      "point the clock reference",
               "other": "⚠ {n} matching DSLR frames cannot be placed in time - "
                        "point the clock reference"},
    },
    "grid.lin.flag.declared": {
        "pl": {"one": "plik deklaruje {n} klatkę", "few": "plik deklaruje {n} klatki",
               "many": "plik deklaruje {n} klatek"},
        "en": {"one": "the file declares {n} frame", "other": "the file declares {n} frames"},
    },
    "grid.lin.flag.excluded": {"pl": "odrzuconych: {n}", "en": "rejected: {n}"},
    # PODSTAWA rodowodu stosu (0034, `integration.lineage_basis`): tokeny = `stacks.LINEAGE_BASES`,
    # parytet w obie strony pilnuje `tests/test_i18n.py`. Zdanie mówi, NA CZYM stoi „plik zeznał”.
    "grid.lin.basis.name": {"pl": "wejścia z nazw plików", "en": "inputs from file names"},
    "grid.lin.basis.temp": {"pl": "wejścia potwierdzone temperaturami z nazw",
                            "en": "inputs confirmed by temperatures in names"},
    "grid.lin.basis.count": {"pl": "wejścia z liczby klatek", "en": "inputs from the frame count"},
    "grid.lin.flag.outside_window": {
        "pl": "część klatek leży poza oknem nagłówka",
        "en": "some frames lie outside the header window",
    },
    # „N z M” (E4-9): plik zeznał N wejść, okno ma M klatek - wiersze są kandydatami okna. Odmiana
    # po M (dopełniacz po „z”: „z 1 klatki”, „z 34 klatek”).
    "grid.lin.flag.used_rows": {
        "pl": {"one": "plik użył {used} z {n} klatki okna",
               "few": "plik użył {used} z {n} klatek okna",
               "many": "plik użył {used} z {n} klatek okna"},
        "en": {"one": "the file used {used} of {n} window frame",
               "other": "the file used {used} of {n} window frames"},
    },
    # Dwuklik wiersza panelu → te klatki w Zbiorach (chip zbioru z drogą powrotu).
    "grid.lin.common_dir": {"pl": "Wszystkie z katalogu:", "en": "All from folder:"},
    # Werdykt podzbioru okna („plik użył N z M"): nagłówek mówi prawdę o N, ostrzeżenie - o sprawie.
    "grid.lin.head_subset": {
        "pl": {"one": "Okno: {n} klatka, plik użył {used} (≈{hours} h)",
               "few": "Okno: {n} klatki, plik użył {used} (≈{hours} h)",
               "many": "Okno: {n} klatek, plik użył {used} (≈{hours} h)"},
        "en": {"one": "Window: {n} frame, the file used {used} (≈{hours} h)",
               "other": "Window: {n} frames, the file used {used} (≈{hours} h)"},
    },
    "grid.lin.flag.used_rows_warn": {
        "pl": {"one": "⚠ plik użył {used} z {n} klatki okna i nie zapisał, których - "
                      "potwierdź je na liście",
               "few": "⚠ plik użył {used} z {n} klatek okna i nie zapisał, których - "
                      "potwierdź je na liście",
               "many": "⚠ plik użył {used} z {n} klatek okna i nie zapisał, których - "
                       "potwierdź je na liście"},
        "en": {"one": "⚠ the file used {used} of {n} window frame and did not record which - "
                      "confirm them in the list",
               "other": "⚠ the file used {used} of {n} window frames and did not record which - "
                        "confirm them in the list"},
    },
    "grid.lin.reason.no_candidates_window": {
        "pl": "Nie wiem, z czego powstał: okno nagłówka nie wybrało żadnej klatki - poniżej materiał "
              "do potwierdzenia.",
        "en": "Unknown source: the header window picked no frame - material to confirm below.",
    },
    # Recepta „Cofnij" po werdykcie ręki - powrót do stanu sprzed gestu (D-1011-4).
    "grid.lin.undo": {"pl": "Cofnij werdykt", "en": "Undo the verdict"},
    "grid.lin.undo_after": {"pl": "potem cofniesz werdykt", "en": "then undo the verdict"},
    "grid.lin.undone": {"pl": "Przywrócono stan sprzed werdyktu: {n}",
                        "en": "Restored the state before the verdict: {n}"},
    "grid.lin.undo_nothing": {
        "pl": "Nie ma już czego cofać - te wiersze rodowodu zmieniono później.",
        "en": "Nothing left to undo - these lineage rows were changed later.",
    },
    "grid.lin.show_tip": {
        "pl": "Dwuklik wiersza: pokaż te klatki w Zbiorach (× na chipie wraca tutaj)",
        "en": "Double-click a row: show these frames in Collections (× on the chip comes back here)",
    },
    "grid.lin.show.inputs": {"pl": "Wejścia obrazu {name} ({n})",
                             "en": "Inputs of image {name} ({n})"},
    "grid.lin.show.candidates": {"pl": "Propozycje dla obrazu {name} ({n})",
                                 "en": "Candidates for image {name} ({n})"},
    "grid.lin.show.calibration": {"pl": "Kalibratory klatki {name} ({n})",
                                  "en": "Calibrators of frame {name} ({n})"},

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
    # I-1: perspektywa mieszka w BAZIE, więc ta sama nazwa bywa przyjechana z drugiej maszyny.
    # Nadpisanie musi być POWIEDZIANE — „zapisano" mówiłoby o czymś, co się nie stało.
    "grid.persp.overwritten": {"pl": "Nadpisano perspektywę „{name}” (nazwa była już w bazie)",
                               "en": "Perspective „{name}” overwritten (name already in database)"},
    "grid.persp.unreadable": {
        "pl": "Perspektywa „{name}” zapisana w starym formacie (SQL) — nie umiem jej zastosować",
        "en": "Perspective „{name}” stored in the old format (SQL) — cannot apply it",
    },

    # --- projekcja / kryteria zbioru ---
    "grid.proj.no_frames": {
        "pl": "Projekcja: brak widocznych klatek", "en": "Projection: no visible frames",
    },
    # FH-13: słowa łączące opisu drzewa filtra (`filter_engine.describe`). Glify operatorów
    # porównania (= ≠ > < ≥ ≤) są wspólne dla obu języków i zostają w silniku; nazwy facetów
    # bierze z `facets.group.*` (jedno źródło z listwą).
    "filter.describe.all": {"pl": "wszystkie klatki", "en": "all frames"},
    "filter.describe.and": {"pl": "i", "en": "and"},
    "filter.describe.or": {"pl": "lub", "en": "or"},
    "filter.describe.not": {"pl": "poza ({inner})", "en": "excluding ({inner})"},
    "filter.describe.has": {"pl": "ma {kw}", "en": "has {kw}"},
    "filter.describe.lacks": {"pl": "bez {kw}", "en": "without {kw}"},
    "filter.describe.contains": {"pl": "zawiera", "en": "contains"},
    "filter.describe.startswith": {"pl": "zaczyna się od", "en": "starts with"},
    "grid.criteria.only_dups": {"pl": "tylko duplikaty", "en": "only duplicates"},
    "grid.criteria.only_review": {"pl": "tylko do przeglądu", "en": "only to review"},
    "grid.criteria.only_vanished": {"pl": "tylko zniknięte", "en": "only vanished"},
    "grid.criteria.only_superseded": {"pl": "tylko zastąpione", "en": "only superseded"},
    "grid.criteria.only_missing_copy": {
        "pl": "tylko z brakującą kopią", "en": "only with a missing copy"},
    "grid.criteria.only_copy_conflict": {
        "pl": "tylko klatki z niezgodnymi kopiami", "en": "only frames with disagreeing copies"},
    "grid.criteria.only_orphan_testimony": {
        "pl": "tylko zeznanie z nieobecnej kopii", "en": "only testimony from a missing copy"},
    "grid.criteria.only_withheld_testimony": {
        "pl": "tylko zapisy z zeznaniem wstrzymanym", "en": "only writes with testimony withheld"},
    "grid.criteria.only_kept_copies": {
        "pl": "tylko kopie zostawione do oka", "en": "only copies kept for review"},
    "grid.criteria.only_torn_write": {
        "pl": "tylko pliki po przerwanym zapisie", "en": "only files after an interrupted write"},
    "grid.criteria.only_pending_finish": {
        "pl": "tylko zapisy czekające na dokończenie", "en": "only writes awaiting completion"},
    "grid.criteria.only_path_header_conflict": {
        "pl": "tylko nagłówek inny niż zatwierdzony folder",
        "en": "only header differing from the confirmed folder"},
    # Ten sam zbiór, co perspektywa `perspective.lineage` i wiersz Porządków `tasks.stacks_lineage` -
    # jedna nazwa na trzech powierzchniach („bez rodowodu" znaczy gdzie indziej stos, którego
    # Dostawa nie ujęła wcale, `status.harvest_lineage_none`).
    "grid.criteria.only_lineage": {
        "pl": "tylko rodowód do potwierdzenia",
        "en": "only lineage to confirm",
    },
    # D-V-9f: perspektywa zapisana NOWSZYM wydaniem niesie warunki, których ten build nie zna.
    # Pominięcie ich poszerza zbiór, więc pasek mówi to wprost i nazywa klucze - bez nazw nie
    # dałoby się sprawdzić, czego brakuje.
    "grid.criteria.unknown_keys": {
        "pl": {"one": "zapisana w nowszej wersji - {n} warunek pominięty ({keys})",
               "few": "zapisana w nowszej wersji - {n} warunki pominięte ({keys})",
               "many": "zapisana w nowszej wersji - {n} warunków pominiętych ({keys})"},
        "en": {"one": "saved by a newer version - {n} condition skipped ({keys})",
               "other": "saved by a newer version - {n} conditions skipped ({keys})"},
    },
    "grid.status.loaded": {
        "pl": "Grid: {frames}, {cols} kolumn-keywordów",
        "en": "Grid: {frames}, {cols} keyword columns",
    },

    # --- writeback (commit/undo/reject; podsumowania składane) ---
    # Człony liczby zdania wyniku zapisu - wpisy MNOGIE (`wb_worker._liczba` wybiera `t_plural`):
    # dawne „1 zapisanych”, „1 zablokowanych”, „1 błędów”.
    "grid.wb.applied": {
        "pl": {"one": "{n} zapisany", "few": "{n} zapisane", "many": "{n} zapisanych"},
        "en": {"one": "{n} applied", "other": "{n} applied"}},
    "grid.wb.renamed": {"pl": "{n} przemianowanych", "en": "{n} renamed"},
    "grid.wb.restored": {
        "pl": {"one": "{n} przywrócony", "few": "{n} przywrócone", "many": "{n} przywróconych"},
        "en": {"one": "{n} restored", "other": "{n} restored"}},
    "grid.wb.semantic": {
        "pl": {"one": "{n} cofnięty semantycznie (bajty pliku inne niż przed zapisem)",
               "few": "{n} cofnięte semantycznie (bajty plików inne niż przed zapisem)",
               "many": "{n} cofniętych semantycznie (bajty plików inne niż przed zapisem)"},
        "en": {"one": "{n} restored semantically (file bytes differ from before the write)",
               "other": "{n} restored semantically (file bytes differ from before the write)"}},
    "grid.wb.withheld": {
        "pl": {"one": "{n} zapisany z zeznaniem wstrzymanym (głosem klatki mówi inna kopia)",
               "few": "{n} zapisane z zeznaniem wstrzymanym (głosem klatki mówi inna kopia)",
               "many": "{n} zapisanych z zeznaniem wstrzymanym (głosem klatki mówi inna kopia)"},
        "en": {"one": "{n} written with testimony withheld (another copy speaks for the frame)",
               "other": "{n} written with testimony withheld (another copy speaks for the frame)"}},
    "grid.wb.undo_withheld": {
        "pl": {"one": "{n} przywrócony bez powrotu zeznania (głosem klatki mówi inna kopia)",
               "few": "{n} przywrócone bez powrotu zeznania (głosem klatki mówi inna kopia)",
               "many": "{n} przywróconych bez powrotu zeznania (głosem klatki mówi inna kopia)"},
        "en": {"one": "{n} restored without testimony (another copy speaks for the frame)",
               "other": "{n} restored without testimony (another copy speaks for the frame)"}},
    "grid.wb.blocked": {
        "pl": {"one": "{n} zablokowany", "few": "{n} zablokowane", "many": "{n} zablokowanych"},
        "en": {"one": "{n} blocked", "other": "{n} blocked"}},
    "grid.wb.errors": {
        "pl": {"one": "{n} błąd", "few": "{n} błędy", "many": "{n} błędów"},
        "en": {"one": "{n} error", "other": "{n} errors"}},
    "grid.wb.skipped": {
        "pl": {"one": "{n} pominięty", "few": "{n} pominięte", "many": "{n} pominiętych"},
        "en": {"one": "{n} skipped", "other": "{n} skipped"}},
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
    # AR-72: po zdjęciu podglądu nazw kolumna wraca do kart czekających w szufladzie
    "grid.rename.preview_cleared_staging_back": {
        "pl": "Podgląd nazw wyczyszczony - wrócił podgląd zmian czekających w szufladzie",
        "en": "Name preview cleared - the changes waiting in the drawer are previewed again",
    },
    "grid.rename.status_summary": {"pl": "Rename: {summary}", "en": "Rename: {summary}"},
    # Recepta przy nieudanym cofnięciu - wspólna dla obu kling szuflady (makro i rename, AR-31 (2)):
    # commit albo przebieg zostaje przy „Cofnij" (wiersze nieudane czekają), więc drugi klik
    # ponawia dokładnie je - reszta jest już cofnięta.
    "grid.wb.undo_retry": {
        "pl": " · „{undo}” ponowi pliki, których cofnięcie się nie udało",
        "en": " · “{undo}” retries the files whose undo failed",
    },
    "grid.rename.undo_status": {"pl": "Undo nazw: {msg}", "en": "Undo names: {msg}"},
    "grid.rename.rejected": {
        "pl": "Odrzucono {n} zmian nazw", "en": "Discarded {n} name changes",
    },

    # --- Znajdź (flows/znajdz_view.py + prezentacja „znajdz" w grid.py) i Uwagi w gridzie ---
    "find.placeholder": {
        "pl": "Znajdź: obiekt albo nazwa potoczna · noc:2026-08 · filtr:Ha,OIII · teleskop: · "
              "zestaw: · uwagi:",
        "en": "Find: object or common name · night:2026-08 · filter:Ha,OIII · telescope: · "
              "setup: · notes:"},
    # Rozpoznane części zapytania działają - zdanie mówi tylko o tym, czego archiwum nie zna.
    "find.unmatched": {"pl": "Nie znam: {items} - reszta zapytania działa.",
                       "en": "Not recognised: {items} - the rest of the query applies."},
    # Zapytanie bez ani jednej rozpoznanej części NIE zastępuje zbioru - zdanie mówi to wprost.
    "find.nothing_matched": {"pl": "Nie znam: {items} - zbiór bez zmian.",
                             "en": "Not recognised: {items} - the set is unchanged."},
    "find.chip.notes": {"pl": "Uwagi: „{text}”", "en": "Notes: “{text}”"},
    # Chip WPISANEGO terminu: nazwa osi i to, co user wpisał („Noc: 2025-11").
    "find.chip.term": {"pl": "{name}: {value}", "en": "{name}: {value}"},
    "find.chip.remove_tip": {"pl": "Zdejmij ten warunek ze zbioru",
                             "en": "Remove this condition from the set"},
    "find.col.night": {"pl": "Noc", "en": "Night"},
    "find.col.exposure": {"pl": "Czas", "en": "Exposure"},
    "find.col.rig": {"pl": "Zestaw", "en": "Setup"},
    "find.col.notes": {"pl": "Uwagi", "en": "Notes"},
    "find.col.file": {"pl": "Plik", "en": "File"},
    "find.cell.exposure": {"pl": "{s} s", "en": "{s} s"},
    "find.verb.release": {"pl": "Wydaj do WBPP", "en": "Release to WBPP"},
    "find.verb.columns": {"pl": "Kolumny", "en": "Columns"},
    # FH-12: pozycja listy perspektyw, której definicja nie zgadza się już ze zbiorem.
    "grid.persp.changed": {"pl": "{name} (zmieniona)", "en": "{name} (modified)"},
    "grid.criteria.notes": {"pl": "uwagi zawierają „{text}”", "en": "notes contain “{text}”"},
    "grid.notes.action": {"pl": "Uwagi…", "en": "Notes…"},
    "grid.notes.tip_ready": {
        "pl": {"one": "Uwaga dla {n} zaznaczonej klatki",
               "few": "Uwaga dla {n} zaznaczonych klatek",
               "many": "Uwaga dla {n} zaznaczonych klatek"},
        "en": {"one": "Note for {n} selected frame", "other": "Note for {n} selected frames"}},
    "grid.notes.tip_empty": {"pl": "Zaznacz klatki, żeby dopisać albo usunąć uwagę.",
                             "en": "Select frames to add or remove a note."},
    # Okno uwag samo nie ruszy po zajętości - zdanie nie obiecuje, że gest „ruszy po zakończeniu".
    "grid.notes.busy_stage": {
        "pl": "Trwa etap Dostawy - uwagę zapiszesz po jego zakończeniu.",
        "en": "An Intake stage is running - you can save the note after it finishes."},
    "grid.notes.busy_write": {
        "pl": "Trwa zapis nagłówków do plików - uwagę zapiszesz po jego zakończeniu.",
        "en": "A header write to files is in progress - you can save the note after it finishes."},
    "grid.notes.set_done": {"pl": "Zapisano uwagę · zmienione klatki: {changed} z {total}",
                            "en": "Note saved · frames changed: {changed} of {total}"},
    "grid.notes.cleared_done": {"pl": "Usunięto uwagi · zmienione klatki: {changed} z {total}",
                                "en": "Notes removed · frames changed: {changed} of {total}"},
    "grid.notes.restored": {"pl": "Cofnięto uwagi · przywrócone klatki: {changed}",
                            "en": "Notes undone · frames restored: {changed}"},
    "grid.notes.undo": {"pl": "Cofnij uwagi", "en": "Undo notes"},
    "grid.notes.undo_after": {"pl": "potem cofniesz uwagi", "en": "then undo the notes"},
    "grid.notes.undo_nothing": {"pl": "Nie ma już czego cofać - uwagi tych klatek zmieniono później.",
                                "en": "Nothing left to undo - these frames' notes changed since."},

    # ============================================================ pipeline.py (rollout §4: pipeline)

    # --- poziomy zapisu (combo; wartość "cold"/"scratch" = identyfikator do bazy, ZOSTAJE) ---
    "pipeline.tier.cold": {"pl": "zimny (archiwum)", "en": "cold (archive)"},
    "pipeline.tier.scratch": {"pl": "roboczy", "en": "scratch"},

    # --- nazwy etapów (status bar / „… w toku"): _STAGE_LABEL trzyma KLUCZE ---
    "pipeline.stage.scan": {"pl": "Skan", "en": "Scan"},
    "pipeline.stage.group": {"pl": "Grupowanie", "en": "Grouping"},
    "pipeline.stage.resolve": {"pl": "Rozwiązywanie", "en": "Resolving"},
    "pipeline.stage.calibrate": {"pl": "Kalibracja", "en": "Calibration"},
    "pipeline.stage.lineage": {"pl": "Rodowód", "en": "Lineage"},
    "pipeline.stage.delta": {"pl": "Delta", "en": "Delta"},
    "pipeline.stage.presence": {"pl": "Obecność", "en": "Presence"},
    "pipeline.stage.stacks": {"pl": "Stosy", "en": "Stacks"},
    "pipeline.stage.stack_lineage": {"pl": "Rodowód stosów", "en": "Stack lineage"},
    "pipeline.stage.copy_facts": {"pl": "Fakty kopii", "en": "Copy facts"},
    "pipeline.stage.stack_history": {"pl": "Historia stosów", "en": "Stack history"},
    # NAGŁÓWEK KAŻDEJ LINII LOGU DOSTAWY: nazwa etapu `pipeline.stage.*` od małej litery - te same
    # słowa, którymi przycisk „Przyjmij nowe (…)” wymienia łańcuch (`pipeline.naglowek_etapu`, Z18).
    # Klucze linii niżej niosą samą treść, bez nawiasu.
    "pipeline.fmt.head": {"pl": "[{stage}] ", "en": "[{stage}] "},
    # Etap uzupełnień (fakty kopii, przejęcie zeznania, historia stosów) bez kandydatów: rdzeń go
    # pomija w ciszy, a log mówi, że etap biegł i nie miał czego zrobić (`PipelineView._uzupelnienia`).
    "pipeline.fmt.nothing_to_do": {"pl": "nic do zrobienia", "en": "nothing to do"},
    # To samo na drodze „Stosy”: uzupełnienia biegną tam zawężone do drzewa obróbki, więc zdanie
    # mówi o zakresie - samo „nic do zrobienia” czytało się jak stan archiwum (Porządki liczą całe).
    "pipeline.fmt.nothing_to_do_tree": {
        "pl": "nic do zrobienia w drzewie obróbki", "en": "nothing to do in the processing tree",
    },
    # Etap, który nie ruszył (źródło niedostępne, hamulec obecności) - jedna treść dla każdego etapu.
    "pipeline.fmt.not_done": {"pl": "NIE WYKONANO - {reason}", "en": "NOT DONE - {reason}"},
    "pipeline.fmt.stack_history.written": {
        "pl": "zapisana {n} z {rows}", "en": "stored {n} of {rows}"},
    "pipeline.fmt.stack_history.stale": {
        "pl": "zmienione na dysku od skanu: {n}", "en": "changed on disk since the scan: {n}"},
    "pipeline.fmt.stack_history.failed": {"pl": "błąd odczytu: {n}", "en": "read error: {n}"},
    "pipeline.fmt.stack_history.remaining": {"pl": "czeka: {n}", "en": "waiting: {n}"},
    "pipeline.counts_stack_history": {
        "pl": "Historia stosów {done}/{total} · zapisane {written} · {tail}",
        "en": "Stack history {done}/{total} · stored {written} · {tail}",
    },
    "pipeline.stage.adopt_testimony": {"pl": "Przejęcie zeznania", "en": "Testimony adoption"},
    # Linia raportu przejęcia zeznania (AR-5). Odmowy tylko, gdy są (QUIET); każda nazywa przyczynę,
    # bo „przejęto 1 z 3" bez niej zatajałoby, dlaczego dwie klatki dalej mówią głosem nieobecnej kopii.
    "pipeline.fmt.adopt.adopted": {
        "pl": "przejęte od ocalałej kopii {n} z {rows}",
        "en": "adopted from the surviving copy {n} of {rows}",
    },
    "pipeline.fmt.adopt.identity": {
        "pl": "plik to inna klatka {n} (bez zapisu)", "en": "file is another frame {n} (not written)",
    },
    "pipeline.fmt.adopt.stale": {
        "pl": "zmienione na dysku od skanu {n} (dogoni je skan)",
        "en": "changed on disk since the scan {n} (the scan will catch up)",
    },
    # Stan w BAZIE przesunął się między odczytem a zapisem (drugi skan, gest ręki, druga kopia) -
    # to nie jest fakt o pliku, więc bez ścieżek i bez obietnicy „dogoni je skan".
    "pipeline.fmt.adopt.raced": {
        "pl": "stan zmienił się w trakcie {n} (zapyta następna dostawa)",
        "en": "state changed meanwhile {n} (the next delivery will ask again)",
    },
    "pipeline.fmt.adopt.failed": {"pl": "nieczytelne {n}", "en": "unreadable {n}"},
    "pipeline.fmt.adopt.remaining": {"pl": "czeka {n}", "en": "waiting {n}"},
    "pipeline.counts_adopt": {
        "pl": "Ocalałe kopie {done}/{total} · przejęte {adopted} · {tail}",
        "en": "Surviving copies {done}/{total} · adopted {adopted} · {tail}",
    },
    # Linia raportu uzupełnienia faktów kopii (0021) - człony odmów tylko, gdy są (QUIET), ale gdy
    # są, stoją obok liczby uzupełnionych: „uzupełniono 540 z 550" bez „zmienione na dysku 10"
    # zatajałoby, dlaczego reszta czeka.
    "pipeline.fmt.copy_facts.written": {
        "pl": "uzupełniono {n} z {rows}", "en": "filled in {n} of {rows}",
    },
    "pipeline.fmt.copy_facts.stale": {
        "pl": "zmienione na dysku od skanu {n} (dogoni je skan)",
        "en": "changed on disk since the scan {n} (the scan will catch up)",
    },
    # Kopia skasowana z dysku, o której baza jeszcze nie wie - nie „nieczytelna": człon mówi, gdzie
    # jest gest, który ją zamyka (pass obecności w Dostawie). Dwa kroki z nazwami z katalogu
    # (`{check}`, `{mark}`): „Oznacz zniknięte” pojawia się dopiero pod wynikiem sprawdzenia i tylko
    # po potwierdzonym zniknięciu - ten sam warunek co `pipeline.tip.presence*`.
    "pipeline.fmt.copy_facts.missing": {
        "pl": "brak pliku {n} - „{check}” → „{mark}” (pojawi się, gdy sprawdzenie potwierdzi "
              "zniknięcie)",
        "en": "file missing {n} - “{check}” → “{mark}” (appears when the check confirms the file "
              "is gone)",
    },
    # Fakty dociągnięte w trakcie przebiegu inną drogą (re-sync pisarza, skan) - nic nie czeka.
    "pipeline.fmt.copy_facts.elsewhere": {
        "pl": "zebrane równolegle {n}", "en": "collected elsewhere {n}",
    },
    # Zapis nagłówka w miejscu trwał przy obu próbach odczytu - plik zdrowy, kopia czeka.
    "pipeline.fmt.copy_facts.raced": {
        "pl": "zapis nagłówka w toku {n} (dobierze następna dostawa)",
        "en": "header write in progress {n} (the next intake will pick it up)",
    },
    "pipeline.fmt.copy_facts.failed": {"pl": "nieczytelne {n}", "en": "unreadable {n}"},
    "pipeline.fmt.copy_facts.remaining": {"pl": "czeka {n}", "en": "waiting {n}"},
    "pipeline.counts_copy_facts": {
        "pl": "Nagłówki kopii {done}/{total} · uzupełnione {written} · {tail}",
        "en": "Copy headers {done}/{total} · filled in {written} · {tail}",
    },

    # --- powody przeglądu w raporcie delty: _REVIEW_REASONS trzyma KLUCZE ---
    "pipeline.reason.no_config": {"pl": "bez konfiguracji", "en": "no config"},
    "pipeline.reason.headerless": {"pl": "bez nagłówka", "en": "headerless"},
    "pipeline.reason.no_camera": {"pl": "bez kamery", "en": "no camera"},
    "pipeline.reason.kind_unknown": {"pl": "rodzaj nieznany", "en": "kind unknown"},
    "pipeline.reason.unreadable": {"pl": "kopia nieczytelna", "en": "unreadable copy"},

    # --- linia „do przeglądu" w raporcie delty (frames = reuse grid.frames) ---
    "pipeline.review.none": {"pl": "brak", "en": "none"},
    "pipeline.review.line": {
        "pl": "{frames} · powody: {reasons}", "en": "{frames} · reasons: {reasons}",
    },

    # --- panel budowy UI ---
    "pipeline.db_none": {"pl": "Baza: (brak)", "en": "Database: (none)"},
    # Nazwa złotej akcji - sama, do zdań, które ją wskazują. Napis przycisku dokłada łańcuch etapów
    # (`pipeline.receive_chain`) składany z `pipeline.ETAPY_PRZYJMIJ_NOWE` nazwami `pipeline.stage.*`
    # (AR-115): dawny literał łańcucha gubił etapy, które biegły. Łańcuch wymienia fakty kopii: bez
    # nich człowiek z 550 kopiami „?" w Porządkach nie miał skąd wiedzieć, że złota akcja jest jedną
    # z dwóch dróg do tej roboty.
    "pipeline.receive": {"pl": "Przyjmij nowe", "en": "Receive new"},
    "pipeline.receive_chain": {"pl": "{name}  ({chain})", "en": "{name}  ({chain})"},
    # Gest „Zbierz fakty kopii (N)" (`PipelineView._on_copy_facts`): dwa etapy łańcucha złotej
    # akcji bez skanu. Liczba w nawiasie nie odmienia rzeczownika - odmiana żyje w podpowiedzi
    # i w linii powodu.
    "pipeline.btn.copy_facts": {"pl": "Zbierz fakty kopii ({n})", "en": "Collect copy facts ({n})"},
    "pipeline.tip.copy_facts": {
        "pl": {"one": "{n} kopia czeka na fakty (liczba obrazów, zeznanie nagłówka). Gest czyta "
                      "same nagłówki i przejmuje zeznanie ocalałej kopii, a po przejęciu przelicza "
                      "pochodne - te same etapy co w „Przyjmij nowe”, bez skanu i bez pytania "
                      "o katalog, w całym archiwum.",
               "few": "{n} kopie czekają na fakty (liczba obrazów, zeznanie nagłówka). Gest czyta "
                      "same nagłówki i przejmuje zeznanie ocalałej kopii, a po przejęciu przelicza "
                      "pochodne - te same etapy co w „Przyjmij nowe”, bez skanu i bez pytania "
                      "o katalog, w całym archiwum.",
               "many": "{n} kopii czeka na fakty (liczba obrazów, zeznanie nagłówka). Gest czyta "
                       "same nagłówki i przejmuje zeznanie ocalałej kopii, a po przejęciu "
                       "przelicza pochodne - te same etapy co w „Przyjmij nowe”, bez skanu i bez "
                       "pytania o katalog, w całym archiwum."},
        "en": {"one": "{n} copy is waiting for its facts (image count, header testimony). This "
                      "reads headers only and adopts the surviving copy's testimony, then "
                      "recomputes what derives from it - the same stages as in “Receive new”, with "
                      "no scan and no folder prompt, across the whole archive.",
               "other": "{n} copies are waiting for their facts (image count, header testimony). "
                        "This reads headers only and adopts the surviving copy's testimony, then "
                        "recomputes what derives from it - the same stages as in “Receive new”, "
                        "with no scan and no folder prompt, across the whole archive."},
    },
    # Linia nad akcjami, gdy do Dostawy przyprowadził klik w wiersz „?" Porządków
    # (`PipelineView.show_reason`): po co człowiek tu jest i która akcja to załatwia.
    "pipeline.why.copy_facts": {
        "pl": {"one": "Zebrać fakty kopii: {n} kopia czeka - bez jej zeznania wiersze „?” "
                      "w Porządkach nie mają czego porównać. „{gest}” zbierze je bez skanu.",
               "few": "Zebrać fakty kopii: {n} kopie czekają - bez ich zeznań wiersze „?” "
                      "w Porządkach nie mają czego porównać. „{gest}” zbierze je bez skanu.",
               "many": "Zebrać fakty kopii: {n} kopii czeka - bez ich zeznań wiersze „?” "
                       "w Porządkach nie mają czego porównać. „{gest}” zbierze je bez skanu."},
        "en": {"one": "Collect copy facts: {n} copy is waiting - without its testimony the “?” "
                      "rows in Housekeeping have nothing to compare. “{gest}” collects it with "
                      "no scan.",
               "other": "Collect copy facts: {n} copies are waiting - without their testimony "
                        "the “?” rows in Housekeeping have nothing to compare. “{gest}” collects "
                        "them with no scan."},
    },
    "pipeline.source_last": {"pl": "ostatnie źródło: {source}", "en": "last source: {source}"},
    "pipeline.source_first": {
        "pl": "(pierwsza dostawa — zapyta o katalog)",
        "en": "(first delivery — it will ask for a folder)",
    },
    "pipeline.advanced_head": {
        "pl": "Tryb zaawansowany — wskazany katalog:",
        "en": "Advanced mode — chosen folder:",
    },
    "pipeline.pick_dir": {"pl": "Wskaż katalog…", "en": "Choose folder…"},
    "pipeline.root_none": {"pl": "(nie wskazano)", "en": "(none chosen)"},
    "pipeline.tier_label": {"pl": "poziom:", "en": "tier:"},
    "pipeline.volume_none": {"pl": "wolumen: —", "en": "volume: —"},
    "pipeline.volume_unset": {
        "pl": "wolumen: ? (serial nieustalony)", "en": "volume: ? (serial undetermined)",
    },
    "pipeline.volume_ok": {
        "pl": "wolumen: {serial} (skan przyrostowy — znane pliki pomijane)",
        "en": "volume: {serial} (incremental scan — known files skipped)",
    },
    "pipeline.process_all": {"pl": "Przetwórz wszystko", "en": "Process all"},
    "pipeline.btn.scan": {"pl": "Skanuj", "en": "Scan"},
    "pipeline.btn.group": {"pl": "Grupuj", "en": "Group"},
    "pipeline.btn.resolve": {"pl": "Rozwiąż", "en": "Resolve"},
    "pipeline.btn.calibrate": {"pl": "Kalibracja", "en": "Calibrate"},
    # DWA RÓŻNE RODOWODY NIE MOGĄ NAZYWAĆ SIĘ TAK SAMO (firsthand 0808). Ten liczy oś KALIBRACJI
    # (czym skalibrowano klatkę nieba); rodowód STOSÓW ma własny przycisk niżej. Etykieta „Rodowód"
    # kosztowała Zdzinia cztery kliknięcia w niewłaściwy etap i wniosek, że program nie działa —
    # bo klikał rzecz, która działała poprawnie, tylko robiła co innego.
    "pipeline.btn.lineage": {"pl": "Rodowód kalibracji", "en": "Calibration lineage"},
    "pipeline.btn.stack_lineage": {"pl": "Policz rodowód stosów", "en": "Compute stack lineage"},
    "pipeline.tip.stack_lineage": {
        "pl": "Przelicza, z czego powstały gotowe obrazy — z tego, co JUŻ jest w bazie. "
              "Bez skanu dysku i bez pytania o katalog. Uruchom po nadaniu obiektu, zestawu "
              "albo odniesienia czasu.",
        "en": "Recomputes what the finished images were made of — from what is ALREADY in the "
              "database. No disk scan, no folder prompt. Run it after assigning an object, "
              "a setup or a time reference.",
    },
    "pipeline.btn.delta": {"pl": "Pokaż deltę", "en": "Show delta"},
    "pipeline.btn.presence": {"pl": "Sprawdź obecność", "en": "Check presence"},
    # Obecność na katalogu wskazanym TERAZ, bez zapamiętania go jako źródła „Przyjmij nowe”
    # (`PipelineView._on_presence_pick`) - droga do korzenia archiwum z podpowiedzi „Sprawdź obecność”.
    "pipeline.btn.presence_in": {"pl": "Sprawdź obecność w…", "en": "Check presence in…"},
    "pipeline.tip.presence_in": {
        "pl": "Zapyta o katalog (np. korzeń archiwum) i porówna go z bazą. Katalog nie zostaje "
              "źródłem „{receive}”. Tylko raport - zapis to „{mark}”, który pojawi się pod "
              "wynikiem, gdy sprawdzenie potwierdzi zniknięcie.",
        "en": "Asks for a folder (e.g. the archive root) and compares it with the database. The "
              "folder does not become the “{receive}” source. Report only - writing is “{mark}”, "
              "which appears below the result when the check confirms a copy is gone.",
    },
    "pipeline.dlg.pick_presence": {
        "pl": "Wskaż katalog do sprawdzenia obecności",
        "en": "Choose a folder to check presence in",
    },
    "pipeline.btn.cancel": {"pl": "Anuluj", "en": "Cancel"},
    "pipeline.tip.calibrate": {
        "pl": "Przepis klatek kalibracyjnych — po „Rozwiąż” (przepis flata potrzebuje filtra)",
        "en": "Calibration frames recipe — after „Resolve” (the flat recipe needs the filter)",
    },
    "pipeline.tip.lineage": {
        "pl": "Powiąż lighty z masterami po przepisie — po „Kalibracja” (potrzebuje osi przepisu)",
        "en": "Link lights to masters by recipe — after „Calibrate” (needs the recipe axis)",
    },
    # Trzy podpowiedzi „Sprawdź obecność" - po jednej na źródło drzewa, w kolejności wyboru
    # (`PipelineView._on_presence`, AR-28 (a)): wskazany katalog, ostatnie źródło, pytanie.
    # Zapis jest WARUNKOWY i podpowiedź to mówi (AR-31 (4), bliźniak recepty `grid.tip.copy_unread`):
    # „{mark}” pojawia się tylko, gdy sprawdzenie POTWIERDZI zniknięcie - hamulec „drzewo puste”
    # potwierdzeń nie liczy, a „nic nie znikło” nie ma czego oznaczać. Ponad progiem kandydatów
    # „Sprawdź obecność” liczy potwierdzenia, a zapis pyta dialogiem `pipeline.force.*` (AR-31 (6)).
    "pipeline.tip.presence": {
        "pl": "Porówna z bazą wskazany katalog: {root}. Tylko raport - zapis to „{mark}”, "
              "który pojawi się pod wynikiem, gdy sprawdzenie potwierdzi zniknięcie.",
        "en": "Compares the chosen folder with the database: {root}. Report only - writing is "
              "“{mark}”, which appears below the result when the check confirms a copy is gone.",
    },
    # AR-30 (3): ostatnie źródło bywa podkatalogiem dostawy - kopia spoza niego nie jest wtedy
    # kandydatem, więc podpowiedź mówi, czym sprawdzić całe archiwum. `{pick}` = „Sprawdź obecność
    # w…”, które źródła dostawy NIE przestawia (wcześniej wskazywało „Wskaż katalog…”, a ten je
    # zapamiętuje - podpowiedź prowadziła wprost w tę szkodę, przed którą sama ostrzegała).
    "pipeline.tip.presence_last": {
        "pl": "Katalogu nie wskazano - porówna z bazą ostatnie źródło „Przyjmij nowe”: {source}. "
              "Sprawdza tylko kopie pod tym katalogiem - żeby objąć całe archiwum, użyj "
              "„{pick}” i wskaż jego korzeń (źródło „Przyjmij nowe” zostaje bez zmian). Tylko "
              "raport - zapis to „{mark}”, który pojawi się pod wynikiem, gdy sprawdzenie "
              "potwierdzi zniknięcie.",
        "en": "No folder chosen - compares the last “Receive new” source with the database: "
              "{source}. It checks only copies under this folder - to cover the whole archive, use "
              "“{pick}” and choose its root (the “Receive new” source stays unchanged). Report only - "
              "writing is “{mark}”, which appears below the result when the check confirms a copy "
              "is gone.",
    },
    "pipeline.tip.presence_ask": {
        "pl": "Zapyta o katalog i porówna go z bazą. Tylko raport - zapis to „{mark}”, który "
              "pojawi się pod wynikiem, gdy sprawdzenie potwierdzi zniknięcie.",
        "en": "Asks for a folder and compares it with the database. Report only - writing is "
              "“{mark}”, which appears below the result when the check confirms a copy is gone.",
    },
    "pipeline.btn.mark_vanished": {"pl": "Oznacz zniknięte", "en": "Mark vanished"},
    # Dialog przełamania hamulca progowego przed „Oznacz zniknięte” (AR-31 (6),
    # `PipelineView._ask_force`). Liczba to POTWIERDZONE zniknięcia z DRY, nie kandydaci; próg
    # przekroczyli kandydaci, więc zdanie o progu mówi o nich. Domyślny przycisk to „Anuluj”.
    "pipeline.force.title": {"pl": "Zapis ponad progiem hamulca",
                             "en": "Write above the brake threshold"},
    "pipeline.force.text": {
        "pl": {"one": "Kandydatów było więcej niż próg hamulca ({limit}), więc zapis wymaga "
                      "potwierdzenia. Sprawdzenie potwierdziło: zniknęła {n} kopia.",
               "few": "Kandydatów było więcej niż próg hamulca ({limit}), więc zapis wymaga "
                      "potwierdzenia. Sprawdzenie potwierdziło: zniknęły {n} kopie.",
               "many": "Kandydatów było więcej niż próg hamulca ({limit}), więc zapis wymaga "
                       "potwierdzenia. Sprawdzenie potwierdziło: zniknęło {n} kopii."},
        "en": {"one": "There were more candidates than the brake threshold ({limit}), so writing "
                      "needs your confirmation. The check confirmed {n} copy is gone.",
               "other": "There were more candidates than the brake threshold ({limit}), so "
                        "writing needs your confirmation. The check confirmed {n} copies are gone."},
    },
    "pipeline.force.info": {
        "pl": "Zatwierdzenie oznaczy jako zniknięte wyłącznie kopie, które sprawdzenie właśnie "
              "potwierdziło; jeśli przy zapisie dysk potwierdzi inne kopie, nic nie zostanie zapisane. "
              "Kopię przemianowaną w międzyczasie zapis pominie, a raport poda, ile takich było. "
              "Pliki i wiersze bazy zostają, a kopia, która wróci, odzyska obecność przy skanie. "
              "Jeśli ta liczba zaskakuje (np. udział zamontowany pusty), wybierz „Anuluj”.",
        "en": "Confirming marks as vanished only the copies the check has just confirmed; if the "
              "disk confirms different copies at write time, nothing is written. A copy renamed in "
              "the meantime is skipped, and the report says how many were. Files and database rows "
              "stay, and a copy that comes back regains presence on scan. If this number is a "
              "surprise (e.g. a share mounted empty), choose “Cancel”.",
    },
    "pipeline.force.ok": {
        "pl": {"one": "Oznacz {n} kopię", "few": "Oznacz {n} kopie", "many": "Oznacz {n} kopii"},
        "en": {"one": "Mark {n} copy", "other": "Mark {n} copies"},
    },
    "pipeline.btn.show_collections": {"pl": "Pokaż w Zbiorach", "en": "Show in Collections"},
    # Podpis logu przebiegu, gdy stan bazy odszedł od niego po geście (AR-99,
    # `PipelineView.naglowek_przebiegu`) - log mówi o chwili przebiegu, panel nad nim o stanie.
    "pipeline.log_before_changes": {
        "pl": "Przebieg z {time} (stan sprzed Twoich zmian)",
        "en": "Run at {time} (state before your changes)",
    },
    # Źródło, którego wątek tła nie zobaczył jako katalogu (odłączony udział, katalog skasowany) -
    # wspólne dla „Sprawdź obecność” i sekwencji skanu („Przyjmij nowe”, „Skanuj”, „Przetwórz
    # wszystko”, AR-31 (3)). Stan wraca Z WĄTKU TŁA: sprawdzenie w oknie zamrażało je do timeoutu
    # sieci. Pierwsze zdanie to człon raportu (po „NIE WYKONANO"), drugie stoi w sekcji wyniku obok
    # „Wskaż katalog…".
    "pipeline.source.unreachable": {
        "pl": "źródło niedostępne: {root}", "en": "source unavailable: {root}",
    },
    "pipeline.source.unreachable_pick": {
        "pl": "Źródło niedostępne: {root} - wskaż katalog.",
        "en": "Source unavailable: {root} - choose a folder.",
    },

    # --- droga „Stosy" (I-2b, P-I): gotowe obrazy po integracji z drzewa OBRÓBKI ---
    "pipeline.stacks_head": {
        "pl": "Stosy — gotowe obrazy po integracji (drzewo obróbki, osobno od archiwum):",
        "en": "Stacks — finished images after integration (processing tree, separate from the archive):",
    },
    "pipeline.btn.harvest": {"pl": "Wciągnij z WBPP…", "en": "Take in from WBPP…"},
    "pipeline.tip.harvest": {
        "pl": "Wyniki WBPP z wydania do archiwum: historia integracji w pliku mówi, z których "
              "klatek powstał wynik, a baza zna te klatki z nazwy. Nazwa i katalog z faktów, "
              "kopia bez nadpisywania, potem zwykła dostawa.",
        "en": "WBPP results from a release into the archive: the integration history in the "
              "file says which frames made the result, and the database knows those frames by "
              "name. Name and folder from facts, copy without overwriting, then a regular intake.",
    },
    "pipeline.stacks_in_work_root": {
        "pl": "To folder roboczy WBPP - stosy z wydań wciąga okno żniw (Wciągnij z WBPP…); "
              "pliki w folderze roboczym są tymczasowe",
        "en": "This is the WBPP working folder - stacks from releases are taken in by the "
              "harvest window (Take in from WBPP…); files in the working folder are temporary",
    },
    "pipeline.btn.stacks": {"pl": "Wciągnij stosy…", "en": "Take in stacks…"},
    "pipeline.tip.stacks": {
        "pl": "Wskaż korzeń drzewa obróbki — Horreum wciągnie same pliki `masterLight*.xisf` "
              "(bez plików pochodnych) i nie ruszy ani jednego bajtu",
        "en": "Choose the processing tree root — Horreum takes only `masterLight*.xisf` files "
              "(no derived files) and touches not a single byte",
    },
    # Memo pod wierszem przycisków sekcji: korzeń nazwany słowami okna „Wciągnij stosy…”, które go
    # ustawia (`pipeline.dlg.pick_stacks`) - samo „ostatni korzeń” nie mówiło, czego.
    "pipeline.stacks_last": {
        "pl": "ostatni korzeń drzewa obróbki: {root}", "en": "last processing tree root: {root}",
    },
    "pipeline.stacks_first": {
        "pl": "(jeszcze nie wskazano korzenia drzewa obróbki)",
        "en": "(no processing tree root chosen yet)",
    },
    # Druga linia memo stosów - cztery rozłączne liczniki ze stanu (`queries.stack_lineage_counts`).
    "pipeline.stacks_counts": {
        "pl": "gotowe obrazy: {all} · z rodowodem: {with_inputs} · bez wejść: {without} · "
              "nieliczone: {uncounted}",
        "en": "finished images: {all} · with lineage: {with_inputs} · without inputs: {without} · "
              "not computed: {uncounted}",
    },
    "pipeline.stacks_counts_tip": {
        "pl": "Liczone ze stanu bazy (bez wycofanych i zastąpionych). Bez kopii na dysku: {no_copy}.",
        "en": "Counted from the database state (without retired and superseded). "
              "Without a copy on disk: {no_copy}.",
    },

    # --- dialogi wyboru katalogu ---
    "pipeline.dlg.pick_scan": {"pl": "Wskaż katalog do skanu", "en": "Choose a folder to scan"},
    "pipeline.dlg.pick_delivery": {"pl": "Wskaż katalog dostawy", "en": "Choose a delivery folder"},
    "pipeline.dlg.pick_stacks": {
        "pl": "Wskaż korzeń drzewa obróbki", "en": "Choose the processing tree root",
    },

    # --- guard serialu / błąd ---
    "pipeline.guard.mixed": {
        "pl": "wolumen nieustalony — skan wstrzymany (baza zna realne wolumeny)",
        "en": "volume undetermined — scan halted (the database knows real volumes)",
    },
    "pipeline.error_prefix": {"pl": "BŁĄD — {msg}", "en": "ERROR — {msg}"},

    # --- status / licznik w biegu ---
    "pipeline.cancelling": {
        "pl": "Anulowanie… (po bieżącym pliku)", "en": "Cancelling… (after current file)",
    },
    # Powody odmowy fasady `run_stage` (D-PD-6) - POWÓD, nie goły False: jedna bramka łączyła dwa
    # różne stany, a komunikat oparty na bool-u mógłby skłamać. Zdania od WIELKIEJ litery: stoją
    # samodzielnie (pasek stanu, odmowa kafla na stronie Dostawy, wiersz błędu okna naprawy,
    # podpowiedź) obok rodzeństwa z tych samych powierzchni, które zaczyna wielką.
    "pipeline.refuse.no_db": {
        "pl": "Brak otwartej bazy - otwórz bazę i spróbuj ponownie",
        "en": "No database open - open one and try again",
    },
    "pipeline.refuse.running": {
        "pl": "Etap w biegu - uruchom „Rozwiąż” po jego zakończeniu",
        "en": "A stage is running - start “Resolve” after it finishes",
    },
    # Odmowa wejść SPOZA strony (kafel Przyjmij, żniwa): wołający nie prosił o „Rozwiąż”, więc
    # zdanie mówi, gdzie widać bieżący etap i co zrobić po nim.
    "pipeline.refuse.delivery_running": {
        "pl": "Etap Dostawy w biegu - postęp na stronie Dostawy; przyjmij po jego zakończeniu",
        "en": "An Intake stage is running - progress is on the Intake page; receive after it finishes",
    },
    "pipeline.refuse.writeback": {
        "pl": "Trwa zapis nagłówków do plików - etapy Dostawy ruszą po jego zakończeniu",
        "en": "Header write to files in progress - Intake stages start after it finishes",
    },
    # Odmowa „Oznacz zniknięte” PO dialogu progu: w trakcie pytania inny etap albo zmiana źródła
    # zapomniały wynik sprawdzenia (`_forget_vanished`). `refuse.running` nie pasuje - odsyła
    # do „Rozwiąż”.
    "pipeline.refuse.mark_stale": {
        "pl": "Wynik sprawdzenia przepadł w trakcie pytania (inny etap albo zmiana źródła) - nic "
              "nie zapisano; sprawdź obecność ponownie",
        "en": "The check result was dropped while the question was open (another stage or a "
              "source change) - nothing was written; check presence again",
    },
    "pipeline.counts": {
        "pl": "Pliki {done}/{total} · nowe {new} · pominięte {skipped} · przegląd {review} · {tail}",
        "en": "Files {done}/{total} · new {new} · skipped {skipped} · review {review} · {tail}",
    },
    "pipeline.stage_running": {"pl": "{stage} w toku…", "en": "{stage} in progress…"},
    "pipeline.stage_done_status": {"pl": "{stage}: gotowe.", "en": "{stage}: done."},
    "pipeline.scan_cancelled": {
        "pl": "przerwano po {n} plikach - baza spójna, ponowny skan dokończy.",
        "en": "interrupted after {n} files - database consistent, a rescan will finish.",
    },
    "pipeline.stage_interrupted": {
        "pl": "Etap „{stage}” przerwany.", "en": "Stage „{stage}” interrupted.",
    },
    "pipeline.stage_failed_status": {
        "pl": "Etap „{stage}” nie powiódł się.", "en": "Stage „{stage}” failed.",
    },
    "pipeline.stage_failed_line": {
        "pl": "BŁĄD — etap „{stage}”: {msg}", "en": "ERROR — stage „{stage}”: {msg}",
    },

    # --- sekcja zniknięć: zdanie po zapisie ---
    "pipeline.marked_as_vanished": {
        "pl": "Oznaczono {copies} jako zniknięte — {tail}.",
        "en": "Marked {copies} as vanished — {tail}.",
    },
    "pipeline.no_frame_lost_last": {
        "pl": "żadna klatka nie straciła ostatniej kopii",
        "en": "no frame lost its last copy",
    },

    # --- raport dostawy: linie per etap (szkielet konkatenacji zostaje, wkład z katalogu) ---
    "pipeline.fmt.scan": {
        "pl": "pliki {files} · nowe {new} · istniejące {existing} · pominięte {skipped} · "
              "wykluczone katalogi {excluded} · lokalizacje {loc_new} · odświeżone {loc_ref} "
              "(zeznania {hdr_ref}, przepięte {rebound}) · nagłówki {headers} · "
              "przegląd f/{frame_review} k/{camera_review} rodzaj/{kind}",
        "en": "files {files} · new {new} · existing {existing} · skipped {skipped} · "
              "excluded folders {excluded} · locations {loc_new} · refreshed {loc_ref} "
              "(testimonies {hdr_ref}, rebound {rebound}) · headers {headers} · "
              "review f/{frame_review} c/{camera_review} kind/{kind}",
    },
    # Skan albo droga „Stosy”, które nie ruszyły, bo wątek tła nie zobaczył korzenia jako katalogu
    # (AR-31 (3)), mówią `pipeline.fmt.not_done` pod nagłówkiem SWOJEGO etapu
    # (`PipelineView._on_source_unreachable`) - brak linii czytałby się jak „nic nie przybyło".
    # Rodowód stosów (I-2d) - człony składane w `PipelineView._format_stack_lineage`.
    "pipeline.fmt.slin.linked": {
        "pl": "wiadomo z czego: {n} z {total} obrazów ({inputs} klatek)",
        "en": "source known: {n} of {total} images ({inputs} frames)",
    },
    "pipeline.fmt.slin.history": {
        "pl": "z tego {n} potwierdza sam plik", "en": "of those {n} confirmed by the file itself",
    },
    "pipeline.fmt.slin.subset": {
        "pl": "{n} z nich: plik użył części klatek okna", "en": "{n} of those: the file used part of the window frames",
    },
    "pipeline.fmt.slin.outside_window": {
        "pl": "{n} z nazw spoza okna nagłówka", "en": "{n} from names outside the header window",
    },
    # AR-102: stosy, których rodowód przyszedł z żniw (zbiór dokładny wydania) - dowód mocniejszy niż
    # plik dopasowany do okna, więc osobny człon, nie doliczenie do „potwierdza sam plik”.
    "pipeline.fmt.slin.harvest": {
        "pl": "z wydania {n}", "en": "from a release {n}",
    },
    "pipeline.fmt.slin.waiting": {
        "pl": "czeka na Ciebie {n}", "en": "waiting for you {n}",
    },
    # Wiersz z drogą do gestu przy tym członie (AR-115, `PipelineView._sync_rodowod`); liczba ze
    # STANU (zbiór perspektywy), nie z przebiegu - gest w panelu rodowodu zmienia ją między biegami.
    "pipeline.lineage_waiting": {
        "pl": {"one": "{n} obraz czeka na Ciebie w perspektywie „{where}”",
               "few": "{n} obrazy czekają na Ciebie w perspektywie „{where}”",
               "many": "{n} obrazów czeka na Ciebie w perspektywie „{where}”"},
        "en": {"one": "{n} image is waiting for you in the “{where}” perspective",
               "other": "{n} images are waiting for you in the “{where}” perspective"},
    },
    "pipeline.fmt.slin.ambiguous": {
        "pl": "wspólne klatki z innym obrazem: {n}", "en": "frames shared with another image: {n}",
    },
    "pipeline.fmt.slin.telescope": {
        "pl": "rozjazd teleskopu: {n}", "en": "telescope mismatch: {n}",
    },
    # Recepta w komunikacie, nie sam licznik: to jedyny człon raportu, po którym user ma coś ZROBIĆ
    # (podłączyć archiwum), a nie tylko coś wiedzieć.
    "pipeline.fmt.slin.kept_unread": {
        "pl": "pominięto, archiwum odłączone: {n} — podłącz i powtórz",
        "en": "skipped, archive disconnected: {n} — connect it and repeat",
    },
    # DRUGA przyczyna tego samego pominięcia, z INNĄ receptą: pliku nie ma w bibliotece (skasowany
    # roboczy WBPP, stos przeniesiony), więc „podłącz archiwum" kazałoby czekać na coś, co nie
    # wróci. Rozdział należy do powierzchni — rdzeń niesie dwa liczniki, nie dwie prozy.
    "pipeline.fmt.slin.kept_no_location": {
        "pl": "pominięto bez obecnej kopii pliku: {n} — puść skan albo Obecność",
        "en": "skipped without a present copy: {n} — run scan or Presence",
    },
    # TRZECIA przyczyna, JEDYNA bez recepty — i to jest informacja, nie brak. Plik leży na miejscu,
    # a zapisany rodowód stoi na dowodzie mocniejszym niż to, co przebieg umiał ustalić teraz
    # (`repo.RANGA_ASSERT`). Człon istnieje, żeby przebieg o zerowej delcie nie wyglądał jak
    # bezczynność — po geście osi obiektu na lighcie dowiedzionego stosu to najczęstszy wynik.
    "pipeline.fmt.slin.kept_proven": {
        "pl": "pominięto, zapisany dowód mocniejszy: {n}",
        "en": "skipped, recorded evidence is stronger: {n}",
    },
    # Droga „Stosy" - człony składane w `PipelineView._format_stacks`; odmowy TYLKO gdy niezerowe.
    "pipeline.fmt.stacks.taken": {
        "pl": "wciągnięte {n} z {cand} kandydatów", "en": "taken {n} of {cand} candidates",
    },
    "pipeline.fmt.stacks.derived": {
        "pl": "pochodne obróbki poza zakresem {n}", "en": "derived files out of scope {n}",
    },
    "pipeline.fmt.stacks.skipped": {"pl": "znane, pominięte {n}", "en": "known, skipped {n}"},
    "pipeline.fmt.stacks.rejected_kind": {
        "pl": "ODRZUCONE (nie zeznają stacku) {n}", "en": "REJECTED (not testifying a stack) {n}",
    },
    "pipeline.fmt.stacks.rejected_unreadable": {
        "pl": "ODRZUCONE (nagłówek nieczytelny) {n}", "en": "REJECTED (unreadable header) {n}",
    },
    "pipeline.fmt.stacks.failed": {
        "pl": "błędy odczytu, bez zapisu {n}", "en": "read errors, nothing written {n}",
    },
    # PRZEBIEG NIEKOMPLETNY, nie „błąd": drzewa nie było widać w całości, więc liczby wyżej są
    # dolnym oszacowaniem. Bez tego członu zerwany share wygląda na puste drzewo (E4-1 pkt 4).
    "pipeline.fmt.stacks.unreadable": {
        "pl": "PRZEBIEG NIEKOMPLETNY: katalogi nieprzeczytane {n}",
        "en": "RUN INCOMPLETE: unreadable directories {n}",
    },
    "pipeline.fmt.scan_derived": {
        "pl": "pochodne obróbki pod STACKS pominięte {n}",
        "en": "derived files under STACKS skipped {n}",
    },
    "pipeline.fmt.scan_unreadable": {
        "pl": "PRZEBIEG NIEKOMPLETNY: katalogi nieprzeczytane {n}",
        "en": "RUN INCOMPLETE: unreadable directories {n}",
    },
    # Sekcja pod linią „PRZEBIEG NIEKOMPLETNY” (E4-7, `PipelineView._pokaz_nieprzeczytane`) mówi
    # KTÓRE katalogi, nie tylko ile. „Mogą”, nie „są” - nieprzeczytany katalog bywa pusty (jak CLI).
    "pipeline.unreadable_head": {
        "pl": {"one": "Nie przeczytałem {n} katalogu - liczby raportu mogą być niższe niż stan "
                      "drzewa:",
               "few": "Nie przeczytałem {n} katalogów - liczby raportu mogą być niższe niż stan "
                      "drzewa:",
               "many": "Nie przeczytałem {n} katalogów - liczby raportu mogą być niższe niż stan "
                       "drzewa:"},
        "en": {"one": "{n} folder could not be read - the report's numbers may be lower than the "
                      "tree holds:",
               "other": "{n} folders could not be read - the report's numbers may be lower than "
                        "the tree holds:"},
    },
    "pipeline.unreadable_more": {
        "pl": {"one": "i {n} inny", "few": "i {n} inne", "many": "i {n} innych"},
        "en": {"one": "and {n} more", "other": "and {n} more"},
    },
    "pipeline.btn.rescan": {"pl": "Skanuj ponownie", "en": "Scan again"},
    "pipeline.tip.rescan": {
        "pl": "Ten sam przebieg na {root}, bez pytania o katalog. Pliki bez zmian pomija brama "
              "przyrostowa, więc czyta głównie to, czego zabrakło.",
        "en": "The same run on {root}, with no folder prompt. The incremental gate skips unchanged "
              "files, so it mostly reads what was missing.",
    },
    "pipeline.fmt.group": {
        "pl": "nagłówki {headers} · teleskopy {telescopes} · bez TELESCOP {no_tel} · "
              "kalibracja poza osią {off_axis}{unassigned}{by_hand} · "
              "konfiguracje {conf_prop}/{conf_assign} · konfig. do przeglądu {conf_review}",
        "en": "headers {headers} · telescopes {telescopes} · no TELESCOP {no_tel} · "
              "off-axis calibration {off_axis}{unassigned}{by_hand} · "
              "configs {conf_prop}/{conf_assign} · configs to review {conf_review}",
    },
    "pipeline.fmt.group_unassigned": {"pl": " (odpięte {n})", "en": " (unassigned {n})"},
    # R1b: przebieg MIJA klatki z zestawem od ręki — i musi to powiedzieć. Bez tej doklejki po
    # geście na 427 klatkach raport pokazywałby SAM SPADEK („bez TELESCOP" i „do przeglądu" lecą
    # w dół), a przyczyna byłaby niewidzialna: człowiek czytałby, że przebieg nagle „naprawił"
    # coś sam. QUIET — doklejka wchodzi wyłącznie przy niezerowej liczbie, jak „odpięte" obok.
    "pipeline.fmt.group_by_hand": {"pl": " (zestaw ręką {n})", "en": " (setup by hand {n})"},
    # Nagrobek osi (0040) wrócił na oś nazwą z pliku - to nie „nowy” wiersz, więc własny człon;
    # wyłącznie przy niezerowej liczbie (QUIET).
    "pipeline.fmt.group_unretired": {
        "pl": {"one": " · {n} teleskop przywrócony na oś",
               "few": " · {n} teleskopy przywrócone na oś",
               "many": " · {n} teleskopów przywróconych na oś"},
        "en": {"one": " · {n} telescope back on the axis",
               "other": " · {n} telescopes back on the axis"}},
    "pipeline.fmt.resolve_unretired": {
        "pl": {"one": " · {n} obiekt przywrócony na oś",
               "few": " · {n} obiekty przywrócone na oś",
               "many": " · {n} obiektów przywróconych na oś"},
        "en": {"one": " · {n} object back on the axis",
               "other": " · {n} objects back on the axis"}},
    "pipeline.fmt.resolve": {
        "pl": "klatki {frames} · klatki light {lights} · obiekty nowe {obj_new} · "
              "przypisane {obj_assign} · przegląd {obj_review} (różnych {obj_distinct}) · "
              "filtry {filters}",
        "en": "frames {frames} · light frames {lights} · new objects {obj_new} · "
              "assigned {obj_assign} · review {obj_review} (distinct {obj_distinct}) · "
              "filters {filters}",
    },
    # Doklejka o SŁOWNIKU obiektów własnych — osobny klucz i wyłącznie przy niezerowym ruchu
    # (QUIET: przy niezmienionym assecie każdy przebieg jest ciszą, więc stałe „słownik: 0" byłoby
    # szumem w każdej dostawie). Bez tej linii cztery liczniki przebiegu nie miały ŻADNEJ
    # powierzchni: odpięcie N klatek po edycji assetu i kolizja nazwy przechodziły bez słowa,
    # a kolizja jest jedyną rzeczą, którą user ma tu do rozstrzygnięcia.
    "pipeline.fmt.resolve_own": {
        "pl": "  (słownik: +{seeded} nazw · −{retired} wycofanych · {unassigned} klatek wróciło "
              "do kolejki)",
        "en": "  (dictionary: +{seeded} names · −{retired} retired · {unassigned} frames back "
              "in the queue)"},
    # Szczebel ścieżki PROPONUJE — linia mówi wprost, że to CZEKA na gest, a nie że zostało zrobione.
    "pipeline.fmt.resolve_path": {
        "pl": "  (ze ścieżki: {names} nazw / {frames} klatek CZEKA na potwierdzenie — oś obiektu)",
        "en": "  (from path: {names} names / {frames} frames AWAIT confirmation — object axis)"},
    "pipeline.fmt.resolve_own_conflict": {
        "pl": "  ⚠ {n} nazw ze słownika należy już do innego obiektu — pominięte, "
              "rozstrzygnij ręcznie",
        "en": "  ⚠ {n} dictionary names already belong to another object — skipped, "
              "resolve by hand"},
    # AR-135: uzgodnienie z tabelą `catalog_xref` - nazwa przepięta do celu pary (klatki z tej nazwy
    # idą za nią) i nazwa, która w bazie wskazuje inny obiekt niż drabina (rozstrzyga człowiek).
    "pipeline.fmt.resolve_xref_rebound": {
        "pl": {"one": " · nazwa katalogowa przepięta do celu: {n} (klatek za nią: {frames})",
               "few": " · nazwy katalogowe przepięte do celu: {n} (klatek za nimi: {frames})",
               "many": " · nazw katalogowych przepiętych do celu: {n} (klatek za nimi: {frames})"},
        "en": {"one": " · catalogue name moved to its target: {n} (frames followed: {frames})",
               "other": " · catalogue names moved to their targets: {n} (frames followed: {frames})"}},
    "pipeline.fmt.resolve_alias_conflict": {
        "pl": {"one": "  ⚠ {n} nazwa wskazuje w bazie inny obiekt niż katalog - Porządki",
               "few": "  ⚠ {n} nazwy wskazują w bazie inny obiekt niż katalog - Porządki",
               "many": "  ⚠ {n} nazw wskazuje w bazie inny obiekt niż katalog - Porządki"},
        "en": {"one": "  ⚠ {n} name points to another object than the catalogue "
                      "- see Housekeeping",
               "other": "  ⚠ {n} names point to another object than the catalogue "
                        "- see Housekeeping"}},
    # E5-1: nagłówek wygrywa z potwierdzeniem ze ścieżki (header-primary), ale głośno. Dwie
    # doklejki, każda tylko gdy niezerowa (QUIET): inny obiekt = gest człowieka przegrał z plikiem
    # (ostrzeżenie), ten sam obiekt = zmieniło się tylko źródło (informacja).
    # Frazy odmieniane przez liczbę (`i18n.t_plural`) - „przepiął 1 klatkę / 2 klatki / 5 klatek".
    "pipeline.fmt.resolve_path_overridden": {
        "pl": {"one": "  ⚠ nagłówek przepiął {n} klatkę z zatwierdzonego folderu na INNY obiekt",
               "few": "  ⚠ nagłówek przepiął {n} klatki z zatwierdzonego folderu na INNY obiekt",
               "many": "  ⚠ nagłówek przepiął {n} klatek z zatwierdzonego folderu na INNY obiekt"},
        "en": {"one": "  ⚠ the header moved {n} frame off the confirmed folder to ANOTHER object",
               "other": "  ⚠ the header moved {n} frames off the confirmed folder to ANOTHER "
                        "object"}},
    "pipeline.fmt.resolve_path_to_header": {
        "pl": {"one": "  (nagłówek potwierdził zatwierdzony folder: {n} klatka - ten sam obiekt, "
                      "źródło z nagłówka)",
               "few": "  (nagłówek potwierdził zatwierdzony folder: {n} klatki - ten sam obiekt, "
                      "źródło z nagłówka)",
               "many": "  (nagłówek potwierdził zatwierdzony folder: {n} klatek - ten sam obiekt, "
                       "źródło z nagłówka)"},
        "en": {"one": "  (the header confirmed the approved folder: {n} frame - same object, "
                      "source now the header)",
               "other": "  (the header confirmed the approved folder: {n} frames - same object, "
                        "source now the header)"}},
    "pipeline.fmt.calibrate": {
        "pl": "klatki {frames} · przepisy {prof_prop}/{prof_assign} · "
              "fakty ze ścieżki {facts} · bez kompletu {incomplete}",
        "en": "frames {frames} · recipes {prof_prop}/{prof_assign} · "
              "facts from path {facts} · incomplete {incomplete}",
    },
    "pipeline.fmt.calibrate_gaps": {"pl": "\n   braki: {gaps}", "en": "\n   gaps: {gaps}"},
    # Kubełek braku przepisu językiem ekranu (`pipeline.zdanie_braku_przepisu`); `facts` = nazwy pól
    # przepisu z rdzenia (`calibration.REQUIRED`), bez tłumaczenia.
    "pipeline.fmt.calibrate_gap": {"pl": "{cls}: brak {facts}", "en": "{cls}: missing {facts}"},
    "pipeline.fmt.lineage": {
        "pl": "lighty {lights} · powiązane: {linked}",
        "en": "lights {lights} · linked: {linked}",
    },
    "pipeline.fmt.lineage_gaps": {"pl": "\n   luki: {gaps}", "en": "\n   gaps: {gaps}"},
    "pipeline.fmt.lineage_unlinked": {
        "pl": "\n   zdjęte ogniwa bez kandydata: {unlinked}",
        "en": "\n   links removed (no candidate left): {unlinked}",
    },
    "pipeline.fmt.group_variants": {
        "pl": " · warianty kadru: powiązane {linked}, czekają {waiting}, odrzucone {bad}",
        "en": " · crop variants: linked {linked}, waiting {waiting}, rejected {bad}",
    },
    # `nameless` STOI OSOBNO od procentu (P-D): klatka bez `object_raw` nie wchodzi do mianownika
    # delty (nie ma nazwy, pod którą byłaby „nierozpoznana"), a bez tej pozycji raport dostawy jest
    # na całą klasę ślepy — i pierwsza nowa dostawa bez `OBJECT` przeszłaby bez śladu.
    "pipeline.fmt.delta": {
        "pl": "obiekt {resolved}/{total} ({pct:.1f}%){no_raw} · filtry {filters}\n"
              "   nierozpoznane: {top}\n   bez nazwy w nagłówku: {nameless}\n"
              "   do przeglądu: {review}",
        "en": "object {resolved}/{total} ({pct:.1f}%){no_raw} · filters {filters}\n"
              "   unrecognized: {top}\n   no name in header: {nameless}\n"
              "   to review: {review}",
    },
    # DWA KLUCZE, BO DWIE POPULACJE (recenzja + wizytacja S3). Nagrobek nie jest podzbiorem
    # żadnego POJEDYNCZEGO zdania raportu: część ma nazwę w nagłówku (idzie do „nierozpoznane"),
    # część nie (idzie do „bez nazwy w nagłówku"). Jeden klucz doklejany w jedno miejsce mówił
    # „z tego" o liczbie, której te klatki nie były częścią. Oba: zostają w procencie świadomie —
    # wykluczenie podnosiłoby go, czyli metryka nagradzałaby odrzucenie zeznania.
    "pipeline.delta.cleared_named": {
        "pl": " · z tego cofnięte ręką: {n}", "en": " · of which undone by hand: {n}"},
    "pipeline.delta.cleared_nameless": {
        "pl": " · z tego cofnięte ręką: {n}", "en": " · of which undone by hand: {n}"},
    # Doklejka do PROCENTU (nie do `{nameless}`): to druga strona tego samego zawężenia — klatki,
    # które obiekt MAJĄ, ale nazwy w nagłówku nie miały, więc do ułamka nie wchodzą po ŻADNEJ
    # stronie. Bez tej doklejki licznik po prostu spada i ekran nie tłumaczy dlaczego.
    "pipeline.delta.resolved_no_raw": {
        "pl": " + {n} rozwiązanych bez nazwy (poza procentem)",
        "en": " + {n} resolved without a name (outside the percentage)"},
    "pipeline.delta.none": {"pl": "—", "en": "—"},
    # Doklejka do `{nameless}`, wyłącznie gdy populacja RAW istnieje. Osobny klucz, nie druga linia
    # szablonu: przy archiwum bez lustrzanki (dziś 0) stałe „RAW: 0" byłoby szumem w każdej dostawie.
    "pipeline.delta.nameless_raw": {"pl": "  (+{n} RAW — format bez karty, do przypisania ręcznie)",
                                    "en": "  (+{n} RAW — format has no card, assign by hand)"},
    "pipeline.delta.nameless_stacks": {
        "pl": "  (+{n} gotowych stosów — do naprawy kartą w Porządkach)",
        "en": "  (+{n} finished stacks — repair with a card in Housekeeping)"},

    # --- raport passa obecności: części składane przez ` · ` ---
    "pipeline.fmt.presence.cancelled": {
        "pl": "przerwane przez użytkownika - nic nie zapisano",
        "en": "cancelled by user - nothing was written",
    },
    "pipeline.fmt.presence.scope": {
        "pl": "zakres {scoped} · na dysku {walked}", "en": "scope {scoped} · on disk {walked}",
    },
    "pipeline.fmt.presence.out_of_reach": {"pl": "poza zasięgiem {n}", "en": "out of reach {n}"},
    "pipeline.fmt.presence.marked": {"pl": "oznaczono {n}", "en": "marked {n}"},
    "pipeline.fmt.presence.gone": {"pl": "zniknęło {n}", "en": "vanished {n}"},
    "pipeline.fmt.presence.nothing_gone": {"pl": "nic nie znikło", "en": "nothing vanished"},
    "pipeline.fmt.presence.resurfaced": {
        "pl": "WYNURZONE {n} (dryf wielkości liter?)",
        "en": "RESURFACED {n} (letter-case drift?)",
    },
    "pipeline.fmt.presence.undecided": {"pl": "nierozstrzygnięte {n}", "en": "undecided {n}"},
    "pipeline.fmt.presence.drifted": {
        "pl": "pominięte przez rename {n}", "en": "skipped by rename {n}",
    },
    # Hamulec obecności w języku UI (AR-50 (1)) - rdzeń `presence._brake_reason` mówi po polsku dla CLI.
    "pipeline.fmt.presence.brake.limit": {
        "pl": "HAMULEC: kandydatów {candidates} > próg {limit} (zakres {scoped})",
        "en": "BRAKE: {candidates} candidates > limit {limit} (scope {scoped})",
    },
    "pipeline.fmt.presence.brake.empty_scope": {
        "pl": "HAMULEC: zakres pusty (0 kopii w bazie pod tym katalogiem) - brak danych to nie brak "
              "zniknięć",
        "en": "BRAKE: empty scope (0 copies in the database under this folder) - no data is not "
              "the same as nothing vanished",
    },
    "pipeline.fmt.presence.brake.empty_tree": {
        "pl": "HAMULEC: drzewo puste (0 plików pod {root}) - dysk podłączony, ale bez treści?",
        "en": "BRAKE: empty tree (0 files under {root}) - drive connected but empty?",
    },
    # Pozostałe powody zatrzymania w języku UI (AR-62) - z `PresenceSummary.abort_kind` i pól liczbowych.
    "pipeline.fmt.presence.abort.volume_unknown": {
        "pl": "wolumin nieustalony - obecność zdejmujemy tylko wtedy, gdy wiadomo, czyje drzewo "
              "oglądamy; pod {root} jest wolumin {serial}",
        "en": "volume undetermined - presence is removed only when we know whose tree we are "
              "looking at; {root} holds volume {serial}",
    },
    "pipeline.fmt.presence.abort.serial_unreadable": {
        "pl": "nie da się odczytać serialu woluminu pod {root} - podłącz dysk i powtórz",
        "en": "cannot read the volume serial under {root} - connect the drive and try again",
    },
    "pipeline.fmt.presence.abort.serial_mismatch": {
        "pl": "pod {root} jest wolumin {serial}, a zakres w bazie należy do {volume} - podłączony "
              "jest inny dysk",
        "en": "{root} holds volume {serial}, but the scope in the database belongs to {volume} - "
              "a different drive is connected",
    },
    "pipeline.fmt.presence.abort.force_mismatch": {
        "pl": {"one": "zatwierdzono {force} do oznaczenia, a dysk potwierdza teraz {n} zniknięcie "
                      "- nic nie zapisano",
               "few": "zatwierdzono {force} do oznaczenia, a dysk potwierdza teraz {n} zniknięcia "
                      "- nic nie zapisano",
               "many": "zatwierdzono {force} do oznaczenia, a dysk potwierdza teraz {n} zniknięć "
                       "- nic nie zapisano"},
        "en": {"one": "{force} approved for marking, but the disk now confirms {n} vanished copy "
                      "- nothing was written",
               "other": "{force} approved for marking, but the disk now confirms {n} vanished "
                        "copies - nothing was written"},
    },
    "pipeline.fmt.presence.abort.gone_set_changed": {
        "pl": "zbiór potwierdzonych zniknięć inny niż w sprawdzeniu, które zatwierdzono - dysk "
              "zmienił się od tamtej chwili, nic nie zapisano",
        "en": "the set of confirmed vanished copies differs from the approved check - the disk "
              "changed since then, nothing was written",
    },
    "pipeline.fmt.presence.brake_recipe": {
        "pl": "„Sprawdź obecność” policzy potwierdzenia i da drogę zapisu",
        "en": "“Check presence” will count confirmations and offer a way to save",
    },
    "pipeline.presence.skipped_no_volume": {
        "pl": "pominięty — wolumin nieustalony, brak kotwicy zakresu",
        "en": "skipped — volume undetermined, no scope anchor",
    },

    # ============================================================ flows/przyjmij.py („co przyszło”)
    # Panel nad stroną Dostawy: liczby ze STANU bazy (`queries.delivery_report`) i ze skanu, wiersze
    # „nie rozpoznałem” z gestem na miejscu. Człony „etykieta liczba” jak w raporcie etapów; zera
    # milczą. Przycisk przypisania i link do Porządków biorą etykiety z istniejących kluczy
    # (`object.assign_btn`, `nav.porzadki`) - ta sama akcja i to samo miejsce, jedna nazwa.
    "intake.title": {"pl": "Co przyszło", "en": "What came in"},
    "intake.head": {"pl": "Dostawa z {time}: {what}", "en": "Intake at {time}: {what}"},
    "intake.new": {
        "pl": {"one": "{n} nowa klatka", "few": "{n} nowe klatki", "many": "{n} nowych klatek"},
        "en": {"one": "{n} new frame", "other": "{n} new frames"},
    },
    "intake.nothing_new": {"pl": "nic nowego", "en": "nothing new"},
    "intake.kinds": {"pl": "({parts})", "en": "({parts})"},
    "intake.kind.light": {"pl": "lighty {n}", "en": "lights {n}"},
    "intake.kind.flat": {"pl": "flaty {n}", "en": "flats {n}"},
    "intake.kind.masters": {"pl": "mastery {n}", "en": "masters {n}"},
    "intake.kind.stacks": {"pl": "stosy {n}", "en": "stacks {n}"},
    "intake.kind.other": {"pl": "inne {n}", "en": "other {n}"},
    "intake.copies_known": {"pl": "kopie znanych klatek {n}", "en": "copies of known frames {n}"},
    "intake.unchanged": {"pl": "bez zmian {n}", "en": "unchanged {n}"},
    "intake.refused": {"pl": "Dostawa nie ruszyła: {reason}", "en": "Intake did not start: {reason}"},
    "intake.cancelled": {
        "pl": "Dostawa przerwana w etapie „{stage}” - niżej to, co zdążyło wejść",
        "en": "Intake interrupted at stage “{stage}” - below is what made it in",
    },
    "intake.failed": {
        "pl": "{line} - niżej to, co zdążyło wejść",
        "en": "{line} - below is what made it in",
    },
    "intake.objects": {"pl": "Obiekty: {items}", "en": "Objects: {items}"},
    "intake.object_item": {"pl": "{canon} ×{n} ({hours})", "en": "{canon} ×{n} ({hours})"},
    "intake.objects_more": {
        "pl": {"one": "i {n} inny", "few": "i {n} inne", "many": "i {n} innych"},
        "en": {"one": "and {n} more", "other": "and {n} more"},
    },
    "intake.cal": {"pl": "Kalibracja nowych lightów: {parts}",
                   "en": "Calibration of new lights: {parts}"},
    "intake.cal.master_flat": {"pl": "flat master {n}", "en": "master flat {n}"},
    "intake.cal.raw_flat": {"pl": "surowy flat {n}", "en": "raw flat {n}"},
    "intake.cal.no_flat": {"pl": "bez flatu {n}", "en": "no flat {n}"},
    "intake.cal.pending": {"pl": "do przeliczenia {n}", "en": "to recompute {n}"},
    "intake.cal.master_dark": {"pl": "dark master {n}", "en": "master dark {n}"},
    "intake.cal.no_dark": {"pl": "bez darka {n}", "en": "no dark {n}"},
    "intake.unresolved_head": {
        "pl": {"one": "Nie rozpoznałem: {n} klatka", "few": "Nie rozpoznałem: {n} klatki",
               "many": "Nie rozpoznałem: {n} klatek"},
        "en": {"one": "Not recognized: {n} frame", "other": "Not recognized: {n} frames"},
    },
    "intake.all_recognized": {"pl": "Wszystko rozpoznane", "en": "Everything recognized"},
    "intake.unresolved_row": {"pl": "„{name}” ×{n} w tej dostawie",
                              "en": "“{name}” ×{n} in this intake"},
    "intake.unresolved_total": {"pl": " · łącznie {total} w archiwum",
                                "en": " · {total} in the archive in total"},
    "intake.unresolved_more": {
        "pl": {"one": "i {n} inna nazwa", "few": "i {n} inne nazwy", "many": "i {n} innych nazw"},
        "en": {"one": "and {n} more name", "other": "and {n} more names"},
    },
    "intake.nameless": {"pl": "bez nazwy w nagłówku {n}", "en": "no name in the header {n}"},
    "intake.nameless_raw": {"pl": "RAW bez nazwy {n}", "en": "RAW without a name {n}"},
    "intake.nameless_stacks": {"pl": "stosy bez nazwy {n}", "en": "stacks without a name {n}"},
    "intake.cleared": {
        "pl": {"one": "Bez obiektu z decyzji ręki: {n} klatka",
               "few": "Bez obiektu z decyzji ręki: {n} klatki",
               "many": "Bez obiektu z decyzji ręki: {n} klatek"},
        "en": {"one": "Without an object by hand decision: {n} frame",
               "other": "Without an object by hand decision: {n} frames"},
    },
    "intake.tip.tasks": {
        "pl": "Pokazuje ten kubełek w Porządkach - tam jest jego naprawa",
        "en": "Shows this bucket in Housekeeping - its fix lives there",
    },
    "intake.assign_tip": {
        "pl": {"one": "Wskaż obiekt dla {n} klatki o tej nazwie - nazwę zapamiętam "
                      "na następne dostawy",
               "few": "Wskaż obiekt dla {n} klatek o tej nazwie - nazwę zapamiętam "
                      "na następne dostawy",
               "many": "Wskaż obiekt dla {n} klatek o tej nazwie - nazwę zapamiętam "
                       "na następne dostawy"},
        "en": {"one": "Pick the object for {n} frame with this name - the name is remembered for "
                      "next deliveries",
               "other": "Pick the object for {n} frames with this name - the name is remembered "
                        "for next deliveries"},
    },
    "intake.assign_busy_tip": {
        "pl": "Dostawa w biegu - przypisanie po jej zakończeniu",
        "en": "Intake is running - assign after it finishes",
    },
    "intake.assign_writeback_tip": {
        "pl": "Trwa zapis nagłówków do plików - przypisanie po jego zakończeniu",
        "en": "Header write to files in progress - assign after it finishes",
    },
    "intake.assign.remembered": {
        "pl": "Zapamiętałem: „{raw}” = {canon} - następne dostawy rozpoznają same",
        "en": "Remembered: “{raw}” = {canon} - next deliveries will recognize it on their own",
    },
    "intake.assign.assigned": {
        "pl": {"one": "Przypisałem {canon} ({n} klatka)", "few": "Przypisałem {canon} ({n} klatki)",
               "many": "Przypisałem {canon} ({n} klatek)"},
        "en": {"one": "Assigned {canon} ({n} frame)", "other": "Assigned {canon} ({n} frames)"},
    },
    "intake.assign.gone": {
        "pl": "„{raw}” nie czeka już na obiekt - raport przeliczony",
        "en": "“{raw}” no longer waits for an object - report recomputed",
    },

    # ============================================================ projection_dialog.py (rollout §4)
    # (proj.create_copies/create_links/files_no_size/plan_tree_folders = FUNDAMENT wyżej)

    # --- eta_text (Qt-wolny pomocnik prezentacji — jak portfolio) ---
    "proj.eta_s": {"pl": " · pozostało ~{n} s", "en": " · ~{n} s left"},
    "proj.eta_min": {"pl": " · pozostało ~{n} min", "en": " · ~{n} min left"},
    "proj.eta_h": {"pl": " · pozostało ~{h:.1f} h", "en": " · ~{h:.1f} h left"},

    # --- budowa dialogu ---
    "proj.title": {"pl": "Wydaj na stół", "en": "Serve to table"},
    "proj.frames_in_perspective": {
        "pl": "Klatek w perspektywie: {n}", "en": "Frames in the perspective: {n}",
    },
    "proj.target_label": {"pl": "Cel wydania:", "en": "Target:"},
    "proj.add_target": {"pl": "+ inny cel…", "en": "+ another target…"},
    "proj.segment_hint": {
        "pl": "Cel musi zawierać segment _WBPP lub _Review (drzewo wykluczone ze skanu).",
        "en": "The target must contain a _WBPP or _Review segment (a tree excluded from the scan).",
    },
    "proj.layout_label": {"pl": "Układ:", "en": "Layout:"},
    "proj.layout_by_object": {
        "pl": "po obiektach  (obiekt / filtr)", "en": "by object  (object / filter)",
    },
    "proj.layout_wbpp": {
        "pl": "WBPP feed  (obiekt / teleskop / filtr)",
        "en": "WBPP feed  (object / telescope / filter)",
    },
    "proj.force_copy": {
        "pl": "Wymuś kopię bajtów (tryb zaawansowany — gdy hardlink po SMB zawodzi)",
        "en": "Force byte copy (advanced — when hardlink over SMB fails)",
    },
    "proj.placeholder": {
        "pl": "Dodaj lub wybierz cel wydania — podgląd (DRY) policzy się sam.",
        "en": "Add or pick a target — the preview (DRY) will compute itself.",
    },
    "proj.btn_refresh": {"pl": "Odśwież podgląd", "en": "Refresh preview"},
    "proj.btn_create": {"pl": "Utwórz", "en": "Create"},
    "proj.btn_cancel_apply": {"pl": "Przerwij wydawanie", "en": "Stop serving"},
    "proj.btn_close": {"pl": "Zamknij", "en": "Close"},

    # --- dodawanie celu ---
    "proj.dlg.pick_target": {
        "pl": "Wskaż cel wydania (pod _WBPP/_Review)", "en": "Choose a target (under _WBPP/_Review)",
    },
    "proj.dlg.name_title": {"pl": "Nazwa celu", "en": "Target name"},
    "proj.dlg.name_label": {"pl": "Nazwa:", "en": "Name:"},
    "proj.add_failed": {"pl": "Nie można dodać celu: {e}", "en": "Cannot add target: {e}"},

    # --- auto-DRY: stany raportu / noty karty ---
    "proj.pick_or_add": {
        "pl": "Dodaj lub wybierz cel wydania („+ inny cel…”).",
        "en": "Add or pick a target (“+ another target…”).",
    },
    "proj.probing": {"pl": "Sonduję cel (DRY)…", "en": "Probing target (DRY)…"},
    "proj.dry_failed": {"pl": "Nie można: {msg}", "en": "Cannot: {msg}"},
    "proj.note_forced_copy": {"pl": "wymuszona kopia bajtów", "en": "forced byte copy"},
    "proj.note_other_vol": {"pl": "inny wolumen → kopia bajtów", "en": "other volume → byte copy"},
    "proj.note_same_vol": {
        "pl": "ten sam wolumen → hardlink (zero bajtów)",
        "en": "same volume → hardlink (zero bytes)",
    },

    # --- apply: nagłówek biegu, przyciski-skutki, błędy ---
    "proj.applying": {
        "pl": "Wydaję na stół → {root}\n\nDysk się ZMIENIA. „Przerwij wydawanie” zatrzyma po bieżącym "
              "pliku; to, co powstało,\nzostaje na dysku (undo = skasuj folder w Eksploratorze).",
        "en": "Serving to table → {root}\n\nThe disk is CHANGING. “Stop serving” halts after the current "
              "file; whatever was made\nstays on disk (undo = delete the folder in Explorer).",
    },
    # Bieg wydania OBIEKTU - słownik wydania, nie stołu (tryb obiektu `ProjectionDialog`).
    "proj.obj.applying": {
        "pl": "Wydaję obiekt → {root}\n\nDysk się ZMIENIA. „Przerwij wydawanie” zatrzyma po bieżącym "
              "pliku; to, co powstało,\nzostaje na dysku (undo = skasuj folder w Eksploratorze).",
        "en": "Releasing the object → {root}\n\nThe disk is CHANGING. “Stop releasing” halts after the "
              "current file; whatever was made\nstays on disk (undo = delete the folder in Explorer).",
    },
    "proj.obj.btn_cancel_apply": {"pl": "Przerwij wydawanie", "en": "Stop releasing"},
    "proj.cancelling": {
        "pl": "Anulowanie… (po bieżącym pliku)", "en": "Cancelling… (after current file)",
    },
    "proj.btn_cancelled": {"pl": "Przerwano", "en": "Cancelled"},
    "proj.btn_created_ok": {"pl": "Utworzono ✓", "en": "Created ✓"},
    "proj.btn_nothing_new": {"pl": "Bez zmian ✓", "en": "No changes ✓"},
    "proj.status_summary": {
        "pl": "Wydano na stół: {files} → {root}",
        "en": "Served to table: {files} → {root}",
    },
    # `{files}` zdań na pasek stanu: liczba odmieniona frazą („skopiowano 1 plik"), nie „1 skopiowano".
    "proj.files_copied": {
        "pl": {"one": "skopiowano {n} plik", "few": "skopiowano {n} pliki", "many": "skopiowano {n} plików"},
        "en": {"one": "copied {n} file", "other": "copied {n} files"},
    },
    "proj.files_linked": {
        "pl": {"one": "zlinkowano {n} plik", "few": "zlinkowano {n} pliki", "many": "zlinkowano {n} plików"},
        "en": {"one": "linked {n} file", "other": "linked {n} files"},
    },
    "proj.abort_prefix": {"pl": "ABORT: {msg}\n\n", "en": "ABORT: {msg}\n\n"},
    "proj.btn_not_created": {"pl": "Nie utworzono", "en": "Not created"},
    "proj.made_before_error": {
        "pl": "\n\nUtworzono {done} z {total} przed błędem — częściowe drzewo zostaje w celu.",
        "en": "\n\nCreated {done} of {total} before the error — a partial tree stays in the target.",
    },
    "proj.apply_error": {
        "pl": "Błąd: {msg}{made}\n\nOdśwież podgląd przed kolejną próbą.",
        "en": "Error: {msg}{made}\n\nRefresh the preview before the next attempt.",
    },
    "proj.btn_error": {"pl": "Przerwane błędem", "en": "Failed with error"},

    # --- raport `_format`: słowa trybu, nagłówki, linie liczników ---
    "proj.word_copy_todo": {"pl": "do skopiowania", "en": "to copy"},
    "proj.word_link_todo": {"pl": "do zlinkowania", "en": "to link"},
    "proj.word_copy_done": {"pl": "skopiowano", "en": "copied"},
    "proj.word_link_done": {"pl": "zlinkowano", "en": "linked"},
    "proj.mode_copies": {"pl": "kopie", "en": "copies"},
    "proj.mode_links": {"pl": "hardlinki", "en": "hardlinks"},
    # Nazwa układu w nagłówku raportu - mapa `projection_dialog._LAYOUT_KEYS` (token dysku → nazwa).
    "proj.layout_name.by_object": {"pl": "po obiektach", "en": "by object"},
    "proj.layout_name.wbpp_feed": {"pl": "WBPP feed", "en": "WBPP feed"},
    "proj.layout_name.object": {"pl": "obiekt do WBPP", "en": "object for WBPP"},
    "proj.dry_head": {
        "pl": "DRY - bez zmian na dysku (układ {layout}, {mode}):",
        "en": "DRY - no disk changes (layout {layout}, {mode}):",
    },
    "proj.dry_counts": {
        "pl": "  {todo}: {would}   istnieje: {exists}   konflikty: {conflict}   pominięto: {skipped}",
        "en": "  {todo}: {would}   exists: {exists}   conflicts: {conflict}   skipped: {skipped}",
    },
    "proj.dry_size": {"pl": "  rozmiar kopii: {size}", "en": "  copy size: {size}"},
    # Sonda bez nic do zrobienia (`projection_dialog.dry_complete`): odpowiedź na pytanie, z którym
    # user wraca do wydanego obiektu, zamiast nagłówka „DRY" nad samymi zerami.
    "proj.dry_head_complete": {
        "pl": "Komplet już w celu (układ {layout}, {mode}):",
        "en": "Already complete in the target (layout {layout}, {mode}):",
    },
    "proj.head_cancelled": {"pl": "Przerwano", "en": "Cancelled"},
    "proj.head_partial": {"pl": "Wynik częściowy", "en": "Partial result"},
    "proj.head_created": {"pl": "Utworzono", "en": "Created"},
    "proj.head_nothing_new": {"pl": "Nic nowego — komplet już w celu",
                              "en": "Nothing new — target already complete"},
    "proj.done_head": {
        "pl": "{head} (układ {layout}, {mode}):", "en": "{head} (layout {layout}, {mode}):",
    },
    "proj.done_counts": {
        "pl": "  {done}: {linked}   istniało: {exists}   konflikty: {conflict}   verify_bad: {vbad}"
              "   błędy: {errors}   pominięto: {skipped}",
        "en": "  {done}: {linked}   existed: {exists}   conflicts: {conflict}   verify_bad: {vbad}"
              "   errors: {errors}   skipped: {skipped}",
    },
    "proj.untouched": {
        "pl": "  nietknięte: {n} (plan zostaje - wznów przez „Odśwież podgląd”)",
        "en": "  untouched: {n} (the plan stays - resume via “Refresh preview”)",
    },
    "proj.multi_present": {
        "pl": "  wiele obecnych kopii: {n} (użyto pierwszej)",
        "en": "  multiple present copies: {n} (used the first)",
    },
    "proj.drift": {
        "pl": "  ⚠ w korzeniu stoi już drzewo o innym układzie ({was}) — ponowne wydanie dołoży "
              "drugie obok niego",
        "en": "  ⚠ the root already holds a tree with a different layout ({was}) — issuing again "
              "will add a second one next to it",
    },
    "proj.plan_tree": {"pl": "  drzewo planu: {tree}", "en": "  plan tree: {tree}"},
    "proj.more_folders": {
        "pl": "    … (+{n} folderów)", "en": "    … (+{n} more folders)",
    },

    # --- wydanie obiektu (tryb obiektu `ProjectionDialog`) ---
    "proj.obj.title": {"pl": "Wydaj obiekt do WBPP", "en": "Release object to WBPP"},
    "proj.obj.head": {
        "pl": "{canon}: {lights} · {masters} · {raw}",
        "en": "{canon}: {lights} · {masters} · {raw}",
    },
    # Luki nagłówka - osobny wiersz w roli `warn` (`projection_dialog.object_gaps_text`).
    "proj.obj.head_no_flat": {"pl": "bez flatu {n}", "en": "without flat {n}"},
    "proj.obj.head_no_dark": {"pl": "bez darka {n}", "en": "without dark {n}"},
    "proj.obj.pending_head": {
        "pl": "do przeliczenia w Dostawie: {n}", "en": "to recompute in Delivery: {n}",
    },
    "proj.obj.n_lights": {
        "pl": {"one": "{n} light", "few": "{n} lighty", "many": "{n} lightów"},
        "en": {"one": "{n} light", "other": "{n} lights"},
    },
    "proj.obj.n_masters": {
        "pl": {"one": "{n} master", "few": "{n} mastery", "many": "{n} masterów"},
        "en": {"one": "{n} master", "other": "{n} masters"},
    },
    "proj.obj.n_raw_flats": {
        "pl": {"one": "{n} surowy flat", "few": "{n} surowe flaty", "many": "{n} surowych flatów"},
        "en": {"one": "{n} raw flat", "other": "{n} raw flats"},
    },
    "proj.obj.zestaw_label": {"pl": "Zestaw:", "en": "Rig:"},
    "proj.obj.zestaw_all": {"pl": "Wszystkie", "en": "All"},
    "proj.obj.zestaw_item": {
        "pl": {"one": "{seg} ({n} light)", "few": "{seg} ({n} lighty)", "many": "{seg} ({n} lightów)"},
        "en": {"one": "{seg} ({n} light)", "other": "{seg} ({n} lights)"},
    },
    "proj.obj.zestaw_line": {
        "pl": "  zestaw {seg}: {lights} · {hours:.2f} h · mastery: {masters} · {raw}",
        "en": "  rig {seg}: {lights} · {hours:.2f} h · masters: {masters} · {raw}",
    },
    "proj.obj.nights": {"pl": " (noce: {nights})", "en": " (nights: {nights})"},
    "proj.obj.no_flat_line": {
        "pl": "    bez flatu: {n} - {why}", "en": "    without flat: {n} - {why}",
    },
    "proj.obj.no_dark_line": {"pl": "    bez darka: {n}", "en": "    without dark: {n}"},
    "proj.obj.pending_line": {
        "pl": "    do przeliczenia w Dostawie: {n} - {why}",
        "en": "    to recompute in Delivery: {n} - {why}",
    },
    "proj.obj.open_explorer": {"pl": "Otwórz w Eksploratorze", "en": "Open in Explorer"},
    # Wyjście WBPP wydania: gdzie człowiek ustawia Output Directory i jak miesza wydania bezpiecznie.
    "proj.work_card": {"pl": "Folder roboczy", "en": "Working folder"},
    "proj.obj.out_line": {"pl": "Wyjście WBPP: {path}", "en": "WBPP output: {path}"},
    "proj.obj.out_copy": {"pl": "Kopiuj ścieżkę", "en": "Copy path"},
    "proj.obj.out_hint": {
        "pl": "W WBPP ustaw Output Directory na tę ścieżkę. Jedna sesja WBPP na jedno wydanie; "
              "gdy mieszasz wydania, dodaj keyword TELESCOP jako Pre i Post.",
        "en": "In WBPP set Output Directory to this path. One WBPP session per release; when "
              "you mix releases, add the TELESCOP keyword as Pre and Post.",
    },
    "proj.obj.status_summary": {
        "pl": "Wydano obiekt {canon}: {files} → {root}",
        "en": "Released object {canon}: {files} → {root}",
    },
    "proj.obj.status_cancelled": {
        "pl": "Przerwano wydanie obiektu {canon}: {word} {n} z {total}, reszta nietknięta → {root}",
        "en": "Release of object {canon} stopped: {word} {n} of {total}, the rest untouched → {root}",
    },
    # Powody luki flatu (`lineage.raw_flats_for`) - mapa `projection_dialog._FLAT_GAP_KEYS`.
    "proj.obj.gap.incomplete_recipe": {
        "pl": "niepełna nastawa w nagłówku lightu",
        "en": "incomplete settings in the light header",
    },
    "proj.obj.gap.no_profile": {
        "pl": "brak w archiwum flatów tej nastawy",
        "en": "no flats with these settings in the archive",
    },
    "proj.obj.gap.pending": {
        "pl": "master jest, rodowód go nie przeliczył",
        "en": "a master exists, lineage has not linked it",
    },
    "proj.obj.gap.no_raw": {
        "pl": "nastawa znana, brak surowych flatów z obecną kopią",
        "en": "settings known, no raw flats with a present copy",
    },
    "proj.obj.gap.out_of_window": {
        "pl": "najbliższe surowe flaty dalej niż {days} dni",
        "en": "nearest raw flats more than {days} days away",
    },
    "proj.obj.gap.no_time": {
        "pl": "light bez daty obserwacji - nie zna swojej nocy",
        "en": "light without an observation date - its night is unknown",
    },

    # --- okno teczek „Wydaj obiekt…" (`ObjectPickDialog`) ---
    "proj.pick.title": {"pl": "Wybierz obiekt do wydania", "en": "Pick an object to release"},
    "proj.pick.hint": {
        "pl": "Dwuklik albo „Dalej” otwiera podgląd wydania (nic nie powstaje na dysku).",
        "en": "Double-click or “Next” opens the release preview (nothing is written to disk).",
    },
    "proj.pick.search_label": {"pl": "Szukaj:", "en": "Search:"},
    "proj.pick.search_placeholder": {"pl": "nazwa obiektu", "en": "object name"},
    "proj.pick.col.object": {"pl": "Obiekt", "en": "Object"},
    "proj.pick.col.hours": {"pl": "Godz.", "en": "Hours"},
    "proj.pick.col.lights": {"pl": "Lightów", "en": "Lights"},
    "proj.pick.col.nights": {"pl": "Nocy", "en": "Nights"},
    "proj.pick.col.sets": {"pl": "Zestawów", "en": "Rigs"},
    "proj.pick.col.flat": {"pl": "Flat (master / surowy)", "en": "Flat (master / raw)"},
    "proj.pick.col.dark": {"pl": "Dark", "en": "Dark"},
    "proj.pick.col.last_night": {"pl": "Ostatnia noc", "en": "Last night"},
    "proj.pick.col.state_tip": {
        "pl": "Stan kalibracji: zielony = komplet master flat i dark, bursztynowy = częściowo, "
              "czerwony = żaden light nie ma flatu ani darka",
        "en": "Calibration state: green = master flat and dark complete, amber = partial, "
              "red = no light has a flat or a dark",
    },
    "proj.pick.state.green": {
        "pl": "komplet: master flat i master dark dla każdego lightu",
        "en": "complete: master flat and master dark for every light",
    },
    "proj.pick.state.amber": {
        "pl": "częściowo: części lightów brakuje flatu albo darka",
        "en": "partial: some lights lack a flat or a dark",
    },
    "proj.pick.state.red": {
        "pl": "brak kalibracji: żaden light nie ma flatu ani darka",
        "en": "no calibration: no light has a flat or a dark",
    },
    "proj.pick.flat_pending": {
        "pl": " · do przeliczenia w Dostawie: {n} %", "en": " · to recompute in Delivery: {n} %",
    },
    "proj.pick.next": {"pl": "Dalej", "en": "Next"},
    "proj.pick.empty": {
        "pl": "Brak obiektów z lightami w bazie.", "en": "No objects with lights in the database.",
    },
    # Drugie zdanie stanu pustego (wzorzec R-S3-5): fraza bez trafień to nie pusta baza.
    "proj.pick.empty_search": {
        "pl": "Brak teczek dla „{fraza}”", "en": "No objects to release for “{fraza}”",
    },

    # --- okno żniw „Wciągnij z WBPP…” (`harvest_dialog.py`) ---------------------------------
    # EN: czasownik drogi to „take in” - słowo, które stoi na Dostawie i w menu „Więcej…” Domu
    # („Take in from WBPP…”), jak polskie „Wciągnij”; rzeczownik „harvest” zostaje tam, gdzie polski
    # mówi „żniwa” (okno żniw, zeznanie żniw).
    "harvest.title": {"pl": "Wciągnij wyniki WBPP", "en": "Take in WBPP results"},
    "harvest.hint": {
        "pl": "Master flat trafia do biblioteki kalibracji, gdy historia integracji w pliku wymienia surowe "
              "flaty znane bazie; stos z wydania Horreum - do biblioteki STACKS, obok lightów swoich wejść. "
              "Plik w wyjściu WBPP zostaje nietknięty, kopia niczego nie nadpisuje.",
        "en": "A master flat goes into the calibration library when the integration history in the file "
              "names raw flats the database knows; a stack from a Horreum release goes into the STACKS "
              "library, next to the lights of its inputs. The file in the WBPP output stays untouched, the "
              "copy overwrites nothing.",
    },
    "harvest.output_label": {"pl": "Wyjście WBPP:", "en": "WBPP output:"},
    "harvest.output_placeholder": {
        "pl": "katalog wyjścia WBPP (np. …\\out)", "en": "WBPP output folder (e.g. …\\out)",
    },
    "harvest.btn_pick": {"pl": "Wskaż…", "en": "Browse…"},
    "harvest.dlg.pick_output": {"pl": "Wskaż katalog wyjścia WBPP", "en": "Choose the WBPP output folder"},
    "harvest.btn_archive": {"pl": "Zmień…", "en": "Change…"},
    "harvest.btn_archive_back": {"pl": "Wróć do archiwum bazy", "en": "Back to the database archive"},
    "harvest.dlg.pick_archive": {
        "pl": "Wskaż archiwum (źródło Dostawy)", "en": "Choose the archive (Intake source)",
    },
    "harvest.archive_label": {"pl": "Archiwum: {root}", "en": "Archive: {root}"},
    "harvest.archive_unset": {"pl": "Archiwum: nie wskazane", "en": "Archive: not set"},
    "harvest.no_output": {
        "pl": "Wskaż katalog wyjścia WBPP - podgląd policzy się sam.",
        "en": "Choose the WBPP output folder - the preview computes itself.",
    },
    "harvest.no_archive": {
        "pl": "Wskaż archiwum (źródło Dostawy) - tam trafią mastery i stosy.",
        "en": "Choose the archive (Intake source) - the masters and stacks go there.",
    },
    "harvest.missing_dir": {"pl": "Katalog nie istnieje: {path}", "en": "Folder does not exist: {path}"},
    "harvest.empty": {"pl": "Brak masterów i stosów w {path}", "en": "No masters or stacks in {path}"},
    "harvest.probing": {
        "pl": "Czytam pliki wyjścia i ich historię (podgląd, bez zmian na dysku)…",
        "en": "Reading the output files and their history (preview, no disk changes)…",
    },
    "harvest.dry_failed": {"pl": "Nie można: {msg}", "en": "Cannot: {msg}"},
    "harvest.head_dry": {
        "pl": "Do wciągnięcia {place} · już w archiwum {exists} · do przeglądu {review}",
        "en": "To take in {place} · already in the archive {exists} · to review {review}",
    },
    "harvest.manifest_note": {
        "pl": "Wydanie Horreum (manifest _PROJEKCJA.json): {path}",
        "en": "Horreum release (manifest _PROJEKCJA.json): {path}",
    },
    "harvest.col.file": {"pl": "Plik", "en": "File"},
    "harvest.col.kind": {"pl": "Rodzaj", "en": "Kind"},
    "harvest.kind.master_flat": {"pl": "master flat", "en": "master flat"},
    "harvest.kind.master_light": {"pl": "stos", "en": "stack"},
    "harvest.kind.master_dark": {"pl": "master dark", "en": "master dark"},
    # Plik z nazwą mastera, którego nagłówek mówi o surowej klatce - rodzaj, który nada mu skan.
    "harvest.kind.light": {"pl": "surowy light", "en": "raw light"},
    "harvest.kind.flat": {"pl": "surowy flat", "en": "raw flat"},
    "harvest.kind.dark": {"pl": "surowy dark", "en": "raw dark"},
    "harvest.kind.bias": {"pl": "surowy bias", "en": "raw bias"},
    "harvest.kind.unknown": {"pl": "nieznany", "en": "unknown"},
    "harvest.col.status": {"pl": "Stan", "en": "Status"},
    "harvest.col.name": {"pl": "Nazwa docelowa", "en": "Target name"},
    "harvest.col.dir": {"pl": "Katalog docelowy", "en": "Target folder"},
    "harvest.col.release": {"pl": "Wydanie", "en": "Release"},
    "harvest.col.reason": {"pl": "Powód", "en": "Reason"},
    "harvest.status.would_place": {"pl": "do wciągnięcia", "en": "to take in"},
    "harvest.status.exists": {"pl": "już w archiwum", "en": "already in the archive"},
    "harvest.status.review": {"pl": "do przeglądu", "en": "to review"},
    "harvest.status.placed": {"pl": "wciągnięty", "en": "taken in"},
    "harvest.status.verify_bad": {"pl": "bajty inne niż w podglądzie", "en": "bytes differ from preview"},
    "harvest.status.conflict": {"pl": "konflikt nazwy", "en": "name conflict"},
    "harvest.status.error": {"pl": "błąd", "en": "error"},
    "harvest.status.cancelled": {"pl": "przerwano", "en": "cancelled"},
    "harvest.outside_release": {"pl": "poza wydaniem Horreum", "en": "outside a Horreum release"},
    "harvest.nights": {"pl": "  (noce wejść: {nights})", "en": "  (input nights: {nights})"},
    "harvest.exists_no_copy": {
        "pl": "znany bazie, bez obecnej kopii", "en": "known to the database, no present copy",
    },
    # Powody przeglądu - tokeny `harvest.REASONS` przez literalną mapę `_HARVEST_REASONS`.
    "harvest.reason.no_raw_darks": {
        "pl": "master dark/bias - archiwum nie ma surowych darków, z których mógłby powstać",
        "en": "dark/bias master - the archive holds no raw darks it could come from",
    },
    "harvest.reason.unreadable": {"pl": "pliku nie da się odczytać", "en": "the file cannot be read"},
    "harvest.reason.no_history": {
        "pl": "brak historii integracji w pliku", "en": "no integration history in the file",
    },
    "harvest.reason.no_inputs": {
        "pl": "historia bez włączonych wejść", "en": "history with no enabled inputs",
    },
    "harvest.reason.inputs_unknown": {
        "pl": "wejść nieznanych bazie: {n}", "en": "inputs unknown to the database: {n}",
    },
    "harvest.reason.inputs_ambiguous": {
        "pl": "nazw wejść pasujących do kilku klatek: {n}",
        "en": "input names matching several frames: {n}",
    },
    "harvest.reason.mixed_profile": {
        "pl": "profili flatu wśród wejść: {n}", "en": "flat profiles among the inputs: {n}",
    },
    "harvest.reason.no_profile": {
        "pl": "wejść bez profilu flatu: {n}", "en": "inputs without a flat profile: {n}",
    },
    "harvest.reason.no_night": {
        "pl": "wejść bez daty nocy (nazwa mastera jej wymaga): {n}",
        "en": "inputs without a night date (the master name needs one): {n}",
    },
    "harvest.reason.header_mismatch": {
        "pl": "nagłówek pliku nie zgadza się z wejściami", "en": "the file header disagrees with its inputs",
    },
    # `header_mismatch` stosu, któremu brak czytelnego `DATE-OBS` (`harvest_dialog.date_obs_text`):
    # nazwa stosu niesie datę nocy, więc bez daty z godziną stosu nie da się nazwać.
    "harvest.reason.date_obs_missing": {
        "pl": "brak DATE-OBS w nagłówku - nazwa stosu wymaga daty i godziny",
        "en": "no DATE-OBS in the header - the stack name needs a date and time",
    },
    "harvest.reason.date_obs_unreadable": {
        "pl": "DATE-OBS bez godziny albo nieczytelne ({value}) - nazwa stosu wymaga daty i godziny",
        "en": "DATE-OBS without a time or unreadable ({value}) - the stack name needs a date and time",
    },
    "harvest.reason.outside_release": {
        "pl": "wejścia spoza wydania, w którego drzewie leży wyjście",
        "en": "inputs outside the release whose tree holds the output",
    },
    # Stos z wejściami spoza wydania - recepta w zdaniu (dane rdzenia nie znają języka ekranu).
    "harvest.reason.outside_release_stack": {
        "pl": "wejść spoza wydania (stos skopiuj ręcznie do STACKS archiwum, „Przyjmij nowe” na archiwum "
              "go weźmie): {n}",
        "en": "inputs outside the release (copy the stack into the archive STACKS by hand, Receive new on the "
              "archive will take it): {n}",
    },
    "harvest.reason.no_config": {
        "pl": "profil bez zestawu (teleskop × kamera) - nie wiem, do którego katalogu",
        "en": "profile without a rig (telescope × camera) - target folder unknown",
    },
    "harvest.reason.name_taken": {
        "pl": "zajęte wszystkie nazwy kandydujące: {n}", "en": "all candidate names taken: {n}",
    },
    "harvest.reason.no_release": {
        "pl": "stos spoza wydania Horreum - skopiuj go ręcznie do biblioteki stosów, „Przyjmij nowe” na "
              "archiwum go weźmie",
        "en": "stack outside a Horreum release - copy it into the stacks library by hand, Receive new on the "
              "archive will take it",
    },
    "harvest.reason.no_light_seat": {
        "pl": "stos wymaga jednej siedziby lightów pod LIGHTS (skopiuj go ręcznie do STACKS, „Przyjmij nowe” "
              "na archiwum go weźmie), znalezionych: {n}",
        "en": "a stack needs one home of its lights under LIGHTS (copy it into STACKS by hand, Receive new on "
              "the archive will take it), found: {n}",
    },
    "harvest.reason.color_unknown": {
        "pl": "kolor stosu nieczytelny z nazwy WBPP (mono, RGB, R, G, B)",
        "en": "stack color unreadable from the WBPP name (mono, RGB, R, G, B)",
    },
    "harvest.reason.foreign_calibration": {
        "pl": "grupa skalibrowana masterem spoza swojego zestawu (jedna sesja WBPP na wydanie albo keyword "
              "TELESCOP jako Pre i Post)",
        "en": "group calibrated with a master from outside its rig (one WBPP session per release, or the "
              "TELESCOP keyword as Pre and Post)",
    },
    "harvest.btn_apply": {
        "pl": {"one": "Wciągnij {n} plik", "few": "Wciągnij {n} pliki", "many": "Wciągnij {n} plików"},
        "en": {"one": "Take in {n} file", "other": "Take in {n} files"},
    },
    "harvest.btn_accept": {"pl": "Zamknij i przyjmij do archiwum", "en": "Close and receive into the archive"},
    "harvest.btn_cancel_apply": {"pl": "Przerwij wciąganie", "en": "Stop taking in"},
    "harvest.btn_close": {"pl": "Zamknij", "en": "Close"},
    "harvest.applying": {
        "pl": "Kopiuję pliki do archiwum - dysk się ZMIENIA. „Przerwij wciąganie” zatrzyma po "
              "bieżącym pliku; to, co wciągnięte, zostaje w archiwum.",
        "en": "Copying files into the archive - the disk is CHANGING. \"Stop taking in\" halts "
              "after the current file; whatever was taken in stays in the archive.",
    },
    "harvest.cancelling": {"pl": "Przerywam… (po bieżącym pliku)", "en": "Stopping… (after the current file)"},
    "harvest.head_done": {
        "pl": "Wciągnięto {placed} · pominięto {exists} (już w archiwum) · do przeglądu {review} · "
              "konflikty {conflict} · błędy {errors}",
        "en": "Taken in {placed} · skipped {exists} (already in the archive) · to review {review} · "
              "conflicts {conflict} · errors {errors}",
    },
    "harvest.verify_bad_tail": {
        "pl": " · bajty inne niż w podglądzie {n}", "en": " · bytes differ from preview {n}",
    },
    "harvest.cancelled_tail": {"pl": " · przerwano, nietknięte: {n}", "en": " · stopped, untouched: {n}"},
    "harvest.made_before_error": {
        "pl": " (przetworzono {done} z {total} przed błędem)",
        "en": " (processed {done} of {total} before the error)",
    },
    "harvest.apply_error": {"pl": "Błąd wciągania: {msg}{made}", "en": "Error while taking in: {msg}{made}"},
    "harvest.btn_nothing": {"pl": "Nic nie wciągnięto", "en": "Nothing taken in"},
    "harvest.btn_cancelled": {"pl": "Przerwano", "en": "Stopped"},
    "harvest.btn_error": {"pl": "Przerwane błędem", "en": "Stopped by an error"},
    "harvest.status_placed": {
        "pl": {"one": "Wciągnięto {n} plik do archiwum → {root}",
               "few": "Wciągnięto {n} pliki do archiwum → {root}",
               "many": "Wciągnięto {n} plików do archiwum → {root}"},
        "en": {"one": "Took {n} file into the archive → {root}",
               "other": "Took {n} files into the archive → {root}"},
    },
    "harvest.status_unknown": {
        "pl": {"one": "W archiwum leży {n} kopia nieznana bazie → {root}",
               "few": "W archiwum leżą {n} kopie nieznane bazie → {root}",
               "many": "W archiwum leży {n} kopii nieznanych bazie → {root}"},
        "en": {"one": "{n} copy in the archive unknown to the database → {root}",
               "other": "{n} copies in the archive unknown to the database → {root}"},
    },
    # Zdanie zwykłego „Zamknij”: fakt bez ścieżki - ścieżka stoi za instrukcją (`status_later`/`_outside`).
    "harvest.close_placed": {
        "pl": {"one": "Wciągnięto {n} plik do archiwum", "few": "Wciągnięto {n} pliki do archiwum",
               "many": "Wciągnięto {n} plików do archiwum"},
        "en": {"one": "Took {n} file into the archive", "other": "Took {n} files into the archive"},
    },
    "harvest.close_unknown": {
        "pl": {"one": "W archiwum leży {n} kopia nieznana bazie", "few": "W archiwum leżą {n} kopie nieznane bazie",
               "many": "W archiwum leży {n} kopii nieznanych bazie"},
        "en": {"one": "{n} copy in the archive unknown to the database",
               "other": "{n} copies in the archive unknown to the database"},
    },
    # Stosy znane bazie bez rodowodu dokładnego (AR-104): zbiór wejść leży tylko w zeznaniu żniw.
    "harvest.status_lineage": {
        "pl": "Stosy do rodowodu dokładnego po Dostawie: {n} → {root}",
        "en": "Stacks for exact lineage after Intake: {n} → {root}",
    },
    "harvest.close_lineage": {
        "pl": "Stosy w archiwum bez rodowodu dokładnego: {n} - zapisze go tylko „Zamknij i przyjmij do "
              "archiwum” w oknie żniw; folderu wydania nie kasuj do tego czasu",
        "en": "Stacks in the archive without their exact lineage: {n} - only \"Close and receive into the "
              "archive\" in the harvest window records it; keep the release folder until then",
    },
    "harvest.close_lineage_tail": {
        "pl": " (stosy bez rodowodu dokładnego: {n} - zapisze go tylko „Zamknij i przyjmij do archiwum”, także "
              "po ponownym otwarciu tego okna; folderu wydania nie kasuj)",
        "en": " (stacks without exact lineage: {n} - only \"Close and receive into the archive\" records it, "
              "also after reopening this window; keep the release folder)",
    },
    "harvest.sum_unknown": {"pl": " · kopie nieznane bazie: {n}", "en": " · copies unknown to the database: {n}"},
    "harvest.status_nothing": {
        "pl": "Żniwa: nic nie wciągnięto (już w archiwum {exists} · do przeglądu {review})",
        "en": "Harvest: nothing taken in (already in the archive {exists} · to review {review})",
    },
    "harvest.status_error": {"pl": "Żniwa przerwane błędem: {msg}", "en": "Harvest stopped by an error: {msg}"},
    "harvest.status_later": {
        "pl": " - baza pozna je przy następnej dostawie („Przyjmij”) → {root}",
        "en": " - the database learns them at the next delivery (\"Receive\") → {root}",
    },
    "harvest.status_outside": {
        "pl": " - kopie leżą poza źródłem Dostawy; baza pozna je przez „Zamknij i przyjmij do archiwum” "
              "albo Dostawę wskazaną na archiwum → {root}",
        "en": " - the copies lie outside the Intake source; the database learns them through \"Close and "
              "receive into the archive\" or an Intake pointed at the archive → {root}",
    },
    "harvest.sum_conflict": {"pl": " · konflikty: {n}", "en": " · conflicts: {n}"},
    "harvest.sum_error": {"pl": " · błędy: {n}", "en": " · errors: {n}"},
    "harvest.btn_done": {"pl": "Wciągnięto", "en": "Taken in"},
    "harvest.not_absolute": {
        "pl": "Ścieżka wyjścia musi być pełna (z dyskiem albo \\\\serwer): {path}",
        "en": "The output path must be absolute (with a drive or \\\\server): {path}",
    },
    "harvest.stale": {
        "pl": "Podgląd dla: {path} - Enter liczy nowy", "en": "Preview for: {path} - Enter computes a new one",
    },
    "harvest.archive_differs": {
        "pl": "Baza zna archiwum w {db} - pliki trafią gdzie indziej, a Dostawa na tamtym archiwum ich nie zobaczy.",
        "en": "The database knows the archive at {db} - the files go elsewhere, and an Intake on that "
              "archive will not see them.",
    },
    "harvest.archive_locked": {
        "pl": "Archiwum zablokowane: w tym oknie wciągnięto już kopie do tego archiwum - drugie archiwum "
              "dałoby korzeń, którego Dostawa nie powinna skanować.",
        "en": "Archive locked: this window has already taken copies into this archive - a second archive "
              "would give a root Intake should not scan.",
    },
    "harvest.accept_refused": {
        "pl": "Nie przyjmę: {root} nie leży pod {cal} ani pod {stacks}",
        "en": "Will not receive: {root} is not under {cal} or {stacks}",
    },
    # Lista wydań nad polem wyjścia (karty: folder roboczy WBPP i karty celu wydania).
    "harvest.rel.col.object": {"pl": "Obiekt", "en": "Object"},
    "harvest.rel.col.card": {"pl": "Karta", "en": "Card"},
    "harvest.rel.col.date": {"pl": "Data wydania", "en": "Release date"},
    "harvest.rel.col.state": {"pl": "Stan", "en": "Status"},
    "harvest.rel.waiting": {"pl": "czeka na WBPP", "en": "waiting for WBPP"},
    # „do sprawdzenia” = kandydaci bez rozstrzygającego zeznania; „do wciągnięcia” mówi dopiero świeży podgląd.
    "harvest.rel.unchecked": {"pl": "do sprawdzenia {n}", "en": "to check {n}"},
    "harvest.rel.pending": {"pl": "do wciągnięcia {n}", "en": "to take in {n}"},
    "harvest.rel.done": {"pl": "wciągnięte {n}", "en": "taken in {n}"},
    "harvest.rel.done_before": {"pl": "poprzednio wciągnięte {n}", "en": "previously taken in {n}"},
    "harvest.rel.review": {"pl": "do przeglądu {n}", "en": "to review {n}"},
    "harvest.rel.lineage": {"pl": "rodowód do zapisania {n}", "en": "lineage to record {n}"},
    "harvest.rel.no_sources": {
        "pl": "Ustaw folder roboczy: Plik → Folder roboczy WBPP…",
        "en": "Set the working folder: File → WBPP working folder…",
    },
    "harvest.rel.none": {
        "pl": "Na kartach nie ma jeszcze wydań obiektu.", "en": "The cards hold no object releases yet.",
    },
    "harvest.rel.missing_one": {
        "pl": "Folder karty nie istnieje: {path} - podłącz dysk albo ustaw folder roboczy: Plik → Folder "
              "roboczy WBPP…",
        "en": "The card folder does not exist: {path} - connect the drive or set the working folder: File → "
              "WBPP working folder…",
    },
    "harvest.rel.missing_many": {
        "pl": {"one": "{n} folder karty nie istnieje: {paths} - podłącz dysk albo ustaw folder roboczy: Plik → "
                      "Folder roboczy WBPP…",
               "few": "{n} foldery kart nie istnieją: {paths} - podłącz dysk albo ustaw folder roboczy: Plik → "
                      "Folder roboczy WBPP…",
               "many": "{n} folderów kart nie istnieje: {paths} - podłącz dysk albo ustaw folder roboczy: Plik → "
                       "Folder roboczy WBPP…"},
        "en": {"one": "{n} card folder does not exist: {paths} - connect the drive or set the working folder: "
                      "File → WBPP working folder…",
               "other": "{n} card folders do not exist: {paths} - connect the drive or set the working folder: "
                        "File → WBPP working folder…"},
    },
    "harvest.rel.probing": {"pl": "Liczę wydania na kartach…", "en": "Counting the releases on the cards…"},
    "harvest.rel.failed": {"pl": "Lista wydań: {msg}", "en": "Release list: {msg}"},
    "harvest.rel.done_note": {
        "pl": "Folder wydania możesz skasować - Horreum go już nie potrzebuje; własne pliki obróbki przenieś "
              "przed skasowaniem.",
        "en": "You can delete the release folder - Horreum no longer needs it; move your own processing files "
              "out before deleting it.",
    },
    "harvest.rel.review_note": {
        "pl": "Najpierw rozstrzygnij pozycje do przeglądu - ich pliki leżą tylko w tym folderze.",
        "en": "Resolve the items to review first - their files exist only in this folder.",
    },
    "harvest.rel.lineage_note": {
        "pl": "Stosy z tego wydania czekają na rodowód dokładny - zapisze go „Zamknij i przyjmij do archiwum”. "
              "Zbiór ich wejść leży tylko w tym folderze, więc nie kasuj go do tego czasu.",
        "en": "Stacks from this release await their exact lineage - \"Close and receive into the archive\" "
              "records it. The set of their inputs exists only in this folder, so keep it until then.",
    },
    "harvest.rel.btn_open": {"pl": "Otwórz", "en": "Open"},
    "harvest.closing": {"pl": "Zamykam po bieżącym pliku…", "en": "Closing after the current file…"},
    "harvest.manifest_error": {
        "pl": "Kopie leżą w archiwum, ale zeznania żniw nie zapisano: {err}",
        "en": "The copies are in the archive, but the harvest record was not written: {err}",
    },

    # ============================================================ drobne (rollout §4: tasks/facets/portfolio)
    # (mapproj/map_view: 0 UI-stringów — „km" jednostka neutralna; NIE dokładamy i18n, R-i18n #7)

    # --- tasks.py (widok Porządki): _TASKS + tytuły podstron trzymają KLUCZE ---
    "tasks.list_title": {
        "pl": "Porządki — zadania ze stanu bazy", "en": "Housekeeping — tasks from the database state",
    },
    "tasks.back": {"pl": "← Porządki", "en": "← Housekeeping"},
    "tasks.telescope_axis": {"pl": "Oś teleskopu", "en": "Telescope axis"},
    "tasks.observatory_axis": {"pl": "Oś obserwatorium", "en": "Observatory axis"},
    "tasks.object_review": {"pl": "Przegląd obiektów", "en": "Object review"},
    "tasks.unresolved_lights": {"pl": "Klatki bez obiektu", "en": "Frames without object"},
    # E5-2: klatka MA obiekt z zatwierdzonego folderu, a karta `OBJECT` w pliku mówi co innego.
    # 0022/Q8: zapis nagłówka w miejscu przerwany albo niepotwierdzony - kopia izolowana od skanu.
    "tasks.torn_write_frames": {
        "pl": "Plik po przerwanym zapisie", "en": "File after an interrupted write"},
    # AR-17 (1): plik ma nowy nagłówek i przeszedł weryfikację, baza jeszcze nie - robotą jest
    # dokończenie. Nazwa bierze czasownik gestu („Dokończ zapis"), żeby wiersz i gest mówiły jednym
    # słowem.
    "tasks.pending_finish_frames": {
        "pl": "Zapis czeka na dokończenie", "en": "Write awaiting completion"},
    # Podpowiedzi dwóch wierszy izolacji: gest mieszka w menu prawego kliku w Zbiorach, więc
    # wiersz mówi, gdzie go szukać. Nazwy gestów z katalogu (`{finish}` / `{restore}` / `{release}`).
    "tasks.torn_write_tip": {
        "pl": "Zapis nagłówka przerwano - plik może mieć rozdarty nagłówek, skan go pomija.\n"
              "W Zbiorach: zaznacz klatki, prawy klik → „{restore}” (stary nagłówek wraca "
              "w miejscu) albo „{release}” (po Twoim sprawdzeniu pliku).",
        "en": "The header write was interrupted - the file may have a torn header, the scan "
              "skips it.\nIn Collections: select the frames, right-click → “{restore}” (the old "
              "header comes back in place) or “{release}” (after you have checked the file).",
    },
    # AR-30 (2): „Dokończ" bywa odmową - przy nieudanej kontroli danych drogą jest powrót, przy
    # pliku skasowanym albo podmienionym zwolnienie. Podpowiedź mówi to z góry, zamiast kazać
    # przejść przez odmowę, żeby poznać właściwy gest.
    "tasks.pending_finish_tip": {
        "pl": "Plik ma już nowy nagłówek, ale baza jeszcze go nie wciągnęła - skan go pomija.\n"
              "W Zbiorach: zaznacz klatki, prawy klik → „{finish}”. Gdy plik nie przejdzie "
              "kontroli danych - „{restore}”; gdy pliku nie ma albo to inny plik - „{release}” "
              "(po Twoim sprawdzeniu).",
        "en": "The file already has the new header, but the database has not taken it in yet - "
              "the scan skips it.\nIn Collections: select the frames, right-click → “{finish}”. "
              "When the file fails the data check - “{restore}”; when the file is gone or is a "
              "different file - “{release}” (after you have checked it).",
    },
    "tasks.path_header_conflict_frames": {
        "pl": "Nagłówek inny niż zatwierdzony folder",
        "en": "Header differs from the confirmed folder"},
    # Nazwa perspektywy, którą wiersz otwiera (`perspective.lineage`) - jeden zbiór, jedna nazwa.
    "tasks.stacks_lineage": {"pl": "Rodowód do potwierdzenia", "en": "Lineage to confirm"},
    "tasks.superseded_frames": {"pl": "Zastąpione (historia)", "en": "Superseded (history)"},
    "tasks.retired_frames": {"pl": "Wycofane (historia)", "en": "Retired (history)"},
    "tasks.retired_conflict_frames": {
        "pl": "Wycofane, a plik wrócił", "en": "Retired, but the file is back"},
    "tasks.telescopes_unlabeled": {"pl": "Teleskopy bez etykiety", "en": "Telescopes without a label"},
    "tasks.observatories_unnamed": {"pl": "Stanowiska bez nazwy", "en": "Sites without a name"},
    # AR-59: robota osi stanowiska i osi sprzętu jako wiersze z liczbą klatek. Podpowiedź mówi, gdzie
    # w podstronie mieszka gest (nazwa z katalogu, `{assign}`).
    "tasks.observatory_review_frames": {"pl": "Klatki bez stanowiska",
                                        "en": "Frames without a site"},
    "tasks.observatory_review_tip": {
        "pl": "Nagłówek nie niesie GPS, a stanowiska nie wskazała ręka.\n"
              "Dark i bias (z masterami) poza liczbą - nie widzą nieba.\n"
              "W podstronie: „{assign}” - okno grupuje te klatki po folderze.",
        "en": "The header carries no GPS and no site was assigned by hand.\n"
              "Darks and biases (with masters) are not counted - they see no sky.\n"
              "On the subpage: “{assign}” - the window groups these frames by folder."},
    "tasks.config_review_frames": {"pl": "Klatki bez zestawu", "en": "Frames without a setup"},
    "tasks.config_review_tip": {
        "pl": "Klatki na osi teleskopu, którym automat nie policzył zestawu (teleskop × kamera) - "
              "dark i bias nie wchodzą, bo zestawu z definicji nie mają.\n"
              "W podstronie: kubełek bez zestawu jest zaznaczony, gest „{assign}”.",
        "en": "Frames on the telescope axis with no setup (telescope × camera) worked out by the "
              "automaton - dark and bias are left out, they have no setup by definition.\n"
              "On the subpage: the no-setup bucket is selected, gesture “{assign}”."},
    # AR-41: werdykt obiektu z ręki został na klatce zastąpionej, bo następczyni nie jest lightem.
    # Wiersz klikalny, ale nie robota (jak „Zastąpione"): prowadzi do perspektywy zastąpionych.
    "tasks.object_kept_frames": {"pl": "Fakt ręki zatrzymany na zastąpionej klatce",
                                 "en": "Hand fact kept on a superseded frame"},
    "tasks.object_kept_tip": {
        "pl": "Werdykt obiektu wskazany ręką został na klatce zastąpionej: następczyni nie jest "
              "lightem, więc nie ma dokąd go przenieść. Nic nie przepadło i nie ma tu roboty - "
              "lista w perspektywie „{persp}”.",
        "en": "An object verdict given by hand stayed on the superseded frame: the successor is "
              "not a light, so there is nowhere to transfer it. Nothing was lost and there is no "
              "work here - the list is in the “{persp}” perspective."},
    # AR-41: gest przeniesienia faktów ręki w perspektywie „Zastąpione" i jego zdanie
    # (`supersede.zdanie_przeniesienia`). Człony osi i pominięć doklejane do zdania głównego.
    "supersede.transfer.action": {"pl": "Przenieś fakty ręki na następczynię",
                                  "en": "Transfer hand facts to the successor"},
    "supersede.transfer.action_tip": {
        "pl": "Werdykty ręki (obiekt, zestaw, stanowisko, uwaga, rodowód) przechodzą "
              "z zaznaczonych klatek zastąpionych na klatki, które niosą dziś ich plik - tylko "
              "tam, gdzie następczyni nie przemówiła sama.",
        "en": "Hand verdicts (object, setup, site, note, lineage) move from the selected "
              "superseded frames to the frames that carry their file today - only where the "
              "successor has not spoken for itself."},
    "supersede.transfer.done": {
        "pl": {"one": "Przeniesienie faktów ręki: {done} z {n} klatki",
               "few": "Przeniesienie faktów ręki: {done} z {n} klatek",
               "many": "Przeniesienie faktów ręki: {done} z {n} klatek"},
        "en": {"one": "Hand facts transferred: {done} of {n} frame",
               "other": "Hand facts transferred: {done} of {n} frames"}},
    "supersede.transfer.axes": {"pl": " ({axes})", "en": " ({axes})"},
    "supersede.transfer.axis_object": {"pl": "obiekt: {n}", "en": "object: {n}"},
    "supersede.transfer.axis_config": {"pl": "zestaw: {n}", "en": "setup: {n}"},
    "supersede.transfer.axis_site": {"pl": "stanowisko: {n}", "en": "site: {n}"},
    "supersede.transfer.axis_note": {"pl": "uwagi: {n}", "en": "notes: {n}"},
    "supersede.transfer.axis_lineage": {"pl": "rodowód: {n}", "en": "lineage: {n}"},
    "supersede.transfer.object_kept": {
        "pl": {"one": ". {n} werdykt obiektu został na klatce zastąpionej - następczyni nie jest "
                      "lightem",
               "few": ". {n} werdykty obiektu zostały na klatkach zastąpionych - następczynie nie "
                      "są lightami",
               "many": ". {n} werdyktów obiektu zostało na klatkach zastąpionych - następczynie "
                       "nie są lightami"},
        "en": {"one": ". {n} object verdict stayed on the superseded frame - the successor is "
                      "not a light",
               "other": ". {n} object verdicts stayed on the superseded frames - the successors "
                        "are not lights"}},
    "supersede.transfer.lineage_dropped": {
        "pl": {"one": ". {n} wskaźnik rodowodu zdjęty - następczyni ma własny werdykt",
               "few": ". {n} wskaźniki rodowodu zdjęte - następczynie mają własne werdykty",
               "many": ". {n} wskaźników rodowodu zdjętych - następczynie mają własne werdykty"},
        "en": {"one": ". {n} lineage pointer removed - the successor has its own verdict",
               "other": ". {n} lineage pointers removed - the successors have their own verdicts"}},
    "supersede.transfer.skip_own": {
        "pl": {"one": ". {n} następczyni ma własne źródło",
               "few": ". {n} następczynie mają własne źródło",
               "many": ". {n} następczyń ma własne źródło"},
        "en": {"one": ". {n} successor has its own source",
               "other": ". {n} successors have their own source"}},
    "supersede.transfer.skip_config_mismatch": {
        "pl": {"one": ". Zestaw nie pasuje do {n} następczyni",
               "few": ". Zestaw nie pasuje do {n} następczyń",
               "many": ". Zestaw nie pasuje do {n} następczyń"},
        "en": {"one": ". The setup does not fit {n} successor",
               "other": ". The setup does not fit {n} successors"}},
    # Szósta oś (E4-5): wskazanie kalibratora ręką nie przechodzi na następczynię, która nie jest
    # lightem albo ma inną kamerę niż master - zostaje na klatce zastąpionej.
    "supersede.transfer.skip_calibration_mismatch": {
        "pl": {"one": ". Kalibrator nie pasuje do {n} następczyni",
               "few": ". Kalibrator nie pasuje do {n} następczyń",
               "many": ". Kalibrator nie pasuje do {n} następczyń"},
        "en": {"one": ". The calibrator does not fit {n} successor",
               "other": ". The calibrator does not fit {n} successors"}},
    "supersede.transfer.axis_calibration": {"pl": "kalibrator: {n}", "en": "calibrator: {n}"},
    "supersede.transfer.skip_none": {
        "pl": {"one": ". {n} klatka bez faktów ręki",
               "few": ". {n} klatki bez faktów ręki",
               "many": ". {n} klatek bez faktów ręki"},
        "en": {"one": ". {n} frame without hand facts",
               "other": ". {n} frames without hand facts"}},
    "supersede.transfer.not_superseded": {
        "pl": {"one": ". {n} klatka nie jest zastąpiona - gest jej nie dotyczy",
               "few": ". {n} klatki nie są zastąpione - gest ich nie dotyczy",
               "many": ". {n} klatek nie jest zastąpionych - gest ich nie dotyczy"},
        "en": {"one": ". {n} frame is not superseded - the gesture does not apply to it",
               "other": ". {n} frames are not superseded - the gesture does not apply to them"}},
    # Ogniwo zgaszone przez skan między odczytem a klingą (treść wróciła pod ścieżkę).
    "supersede.transfer.no_longer_superseded": {
        "pl": {"one": ". {n} klatka przestała być zastąpiona w trakcie gestu - jej plik wrócił",
               "few": ". {n} klatki przestały być zastąpione w trakcie gestu - ich pliki wróciły",
               "many": ". {n} klatek przestało być zastąpionych w trakcie gestu - ich pliki "
                       "wróciły"},
        "en": {"one": ". {n} frame stopped being superseded during the gesture - its file is back",
               "other": ". {n} frames stopped being superseded during the gesture - their files "
                        "are back"}},
    # Gest przerwany błędem klingi na kolejnej klatce: zdanie częściowe + powód (okno ostrzeżenia).
    "supersede.transfer.interrupted": {
        "pl": "Gest przerwany na kolejnej klatce: {err}. Wcześniejsze klatki są zapisane.",
        "en": "The gesture stopped at the next frame: {err}. Earlier frames are saved."},
    # 0032: okno „Uwagi…” (`gui/note_dialog.py`). Zdanie stanu składa dwie liczby: `state_some`
    # odmienia się przez liczbę klatek Z UWAGĄ (orzeczenie: „ma” / „mają”), a wstawiony człon
    # `of_frames` przez liczbę zaznaczonych („z 1 klatki” / „z 5 klatek”).
    "note.title": {"pl": "Uwagi klatek", "en": "Frame notes"},
    "note.placeholder": {"pl": "np. chmury po 2:00, zmieniony flat",
                         "en": "e.g. clouds after 2 am, flat replaced"},
    "note.counter": {"pl": "{n} / {max} znaków", "en": "{n} / {max} characters"},
    # Nadmiar liczony PO zwinięciu białych znaków - tą samą miarą, którą sprawdza klinga.
    "note.too_long": {
        "pl": {"one": "Uwaga jest za długa o {n} znak - skróć ją, żeby zapisać",
               "few": "Uwaga jest za długa o {n} znaki - skróć ją, żeby zapisać",
               "many": "Uwaga jest za długa o {n} znaków - skróć ją, żeby zapisać"},
        "en": {"one": "The note is {n} character too long - shorten it to save",
               "other": "The note is {n} characters too long - shorten it to save"}},
    "note.of_frames": {
        "pl": {"one": "z {n} klatki", "few": "z {n} klatek", "many": "z {n} klatek"},
        "en": {"one": "of {n} frame", "other": "of {n} frames"}},
    "note.state_some": {
        "pl": {"one": "Uwagę ma {n} {of}", "few": "Uwagę mają {n} {of}",
               "many": "Uwagę ma {n} {of}"},
        "en": {"one": "{n} {of} has a note", "other": "{n} {of} have a note"}},
    "note.state_single": {"pl": "Klatka ma uwagę", "en": "The frame has a note"},
    "note.state_none": {
        "pl": {"one": "Klatka nie ma uwagi", "few": "Żadna z {n} klatek nie ma uwagi",
               "many": "Żadna z {n} klatek nie ma uwagi"},
        "en": {"one": "The frame has no note", "other": "None of the {n} frames has a note"}},
    "note.state_mixed": {
        "pl": {"one": "Różne uwagi na {k} z {n} klatki - zapis zastąpi je jedną",
               "few": "Różne uwagi na {k} z {n} klatkach - zapis zastąpi je jedną",
               "many": "Różne uwagi na {k} z {n} klatkach - zapis zastąpi je jedną"},
        "en": {"one": "Different notes on {k} of {n} frame - saving replaces them with one",
               "other": "Different notes on {k} of {n} frames - saving replaces them with one"}},
    "note.save": {"pl": "Zapisz", "en": "Save"},
    "note.clear": {"pl": "Usuń uwagi", "en": "Remove notes"},
    "note.cancel": {"pl": "Anuluj", "en": "Cancel"},
    "tasks.dup_frames": {"pl": "Duplikaty (>1 kopia)", "en": "Duplicates (>1 copy)"},
    # 0021: podzbiór „Duplikatów", stoi tuż pod nimi. Nazwa mówi o KLATKACH, bo liczba obok liczy
    # klatki (`queries.copy_conflict_frame_ids`) - „Kopie niezgodne ze sobą" obiecywało liczbę kopii.
    # To samo brzmienie niesie perspektywa i człon paska kryteriów.
    "tasks.copy_conflict_frames": {"pl": "Klatki z niezgodnymi kopiami",
                                   "en": "Frames with disagreeing copies"},
    # AR-5: klatka mówi głosem pliku, którego nie ma. Nazwa niesie przyczynę, nie objaw („niezgodne"
    # już zajęte przez sąsiada wyżej, a tu obecne kopie bywają zgodne ze sobą).
    "tasks.orphan_testimony_frames": {
        "pl": "Zeznanie z nieobecnej kopii", "en": "Testimony from a missing copy"},
    # AR-82: plik kopii zapisany, zeznanie klatki przy innej kopii.
    "tasks.withheld_testimony_frames": {
        "pl": "Zeznanie wstrzymane", "en": "Testimony withheld"},
    # AR-64: kopie plików zostawione obok ścieżki po przerwanej podmianie.
    "tasks.kept_copy_frames": {
        "pl": "Kopie zostawione do oka", "en": "Copies kept for review"},
    # Człon drugi dwóch wierszy wyżej, gdy ich zero znaczy „nie wiem": kopia bez zebranego zeznania
    # w porównaniu nie bierze udziału. „?" mówi, że liczby nie ma, reszta - dlaczego. Człon mówi
    # STAN, nie drogę: „czeka na Dostawę" było nieprawdą przy kopii, której pliku już nie ma
    # (Dostawa jej nie uzupełni nigdy), a zdanie z obiema drogami nie mieści się w wierszu - człon
    # drugi nie jest elidowany i zabiera miejsce nazwie przy liście 400 px. Drogi niesie podpowiedź.
    "tasks.copies_unread": {
        "pl": {"one": "? · {n} kopia bez zeznania", "few": "? · {n} kopie bez zeznania",
               "many": "? · {n} kopii bez zeznania"},
        "en": {"one": "? · {n} copy not yet read", "other": "? · {n} copies not yet read"},
    },
    # Człon drugi tych samych wierszy, gdy liczba NIE jest zerem, a kopie bez zeznania są: liczba
    # jest dolną granicą („{m}+"), bo kopie bez faktów w porównaniu nie biorą udziału. Odmiana po
    # liczbie kopii (`{n}`), jak w „?". `{m}` to cały człon liczby wiersza - przy robocie mniejszej
    # od liczby razem z nią („0 z 1+", `tasks.of_total`).
    "tasks.copies_partial": {
        "pl": {"one": "{m}+ · {n} kopia bez zeznania", "few": "{m}+ · {n} kopie bez zeznania",
               "many": "{m}+ · {n} kopii bez zeznania"},
        "en": {"one": "{m}+ · {n} copy not yet read", "other": "{m}+ · {n} copies not yet read"},
    },
    # Podpowiedź wiersza w stanie „?" i „N+": drogi WARUNKOWE, w kolejności pytań człowieka („czy plik
    # jest"), bo wiersz nie sprawdza dysku - rozstrzyga pass obecności. Kopie stosów spod korzenia
    # stosów dostają fakty wyłącznie drogą „Stosy" („Przyjmij nowe" chodzi po archiwum), a wiersz nie
    # zna korzenia stosów - stąd druga droga, też warunkowa. Nazwy z katalogu (`{place}`, `{stacks}`,
    # `{check}`, `{mark}`), jak w podpowiedzi kopii w Zbiorach - z tym samym dwukrokiem drogi „pliku
    # nie ma" (AR-28 (a)) i tym samym warunkiem drugiego kroku (przycisk tylko po potwierdzonym
    # zniknięciu). Ostatnie zdanie mówi, dokąd prowadzi klik (AR-28 (b)): `{dest}` - Dostawa przy
    # „?", Zbiory przy „N+" (tam są klatki do obejrzenia). To samo zdanie mówi pusty stan pustej
    # perspektywy kopii w Zbiorach (`grid._ustaw_pusty_stan`, przycisk do Dostawy), więc nie nazywa
    # swojej powierzchni („ta liczba", nie „liczba tego wiersza") - jeden właściciel zdania.
    "tasks.copies_unread_tip": {
        "pl": {"one": "{n} kopia nie ma jeszcze zebranego zeznania nagłówka, więc ta liczba "
                      "jej nie obejmuje.\n"
                      "Gdy plik jest na dysku - {place} → „Przyjmij nowe”.\n"
                      "Gdy kopia leży pod korzeniem stosów - {place} → „{stacks}”.\n"
                      "Jeśli pliku nie ma już na dysku - {place} → „{check}” → „{mark}” (pojawi "
                      "się pod wynikiem, gdy sprawdzenie potwierdzi zniknięcie).\n"
                      "Klik prowadzi do: {dest}.",
               "few": "{n} kopie nie mają jeszcze zebranego zeznania nagłówka, więc ta liczba "
                      "ich nie obejmuje.\n"
                      "Gdy plik jest na dysku - {place} → „Przyjmij nowe”.\n"
                      "Gdy kopia leży pod korzeniem stosów - {place} → „{stacks}”.\n"
                      "Jeśli pliku nie ma już na dysku - {place} → „{check}” → „{mark}” (pojawi "
                      "się pod wynikiem, gdy sprawdzenie potwierdzi zniknięcie).\n"
                      "Klik prowadzi do: {dest}.",
               "many": "{n} kopii nie ma jeszcze zebranego zeznania nagłówka, więc ta liczba "
                       "ich nie obejmuje.\n"
                       "Gdy plik jest na dysku - {place} → „Przyjmij nowe”.\n"
                       "Gdy kopia leży pod korzeniem stosów - {place} → „{stacks}”.\n"
                       "Jeśli pliku nie ma już na dysku - {place} → „{check}” → „{mark}” (pojawi "
                       "się pod wynikiem, gdy sprawdzenie potwierdzi zniknięcie).\n"
                       "Klik prowadzi do: {dest}."},
        "en": {"one": "{n} copy has no header testimony collected yet, so this count does "
                      "not include it.\n"
                      "If the file is on disk - {place} → “Receive new”.\n"
                      "If the copy lies under the stacks root - {place} → “{stacks}”.\n"
                      "If the file is no longer on disk - {place} → “{check}” → “{mark}” (appears "
                      "below the result when the check confirms the file is gone).\n"
                      "A click takes you to: {dest}.",
               "other": "{n} copies have no header testimony collected yet, so this count "
                        "does not include them.\n"
                        "If the file is on disk - {place} → “Receive new”.\n"
                        "If the copy lies under the stacks root - {place} → “{stacks}”.\n"
                        "If the file is no longer on disk - {place} → “{check}” → “{mark}” "
                        "(appears below the result when the check confirms the file is gone).\n"
                        "A click takes you to: {dest}."},
    },
    # Dopisek tej podpowiedzi, gdy część kopii ma fakty reguły NOWSZEJ niż binarka (AR-33, AR-50 (3)):
    # Dostawa tej wersji ich nie uzupełni, więc zdanie wyżej nie może za nie obiecywać odpowiedzi.
    "tasks.copies_newer_rule_tip": {
        "pl": {"one": "W tym {n} kopia ma zeznanie zebrane nowszą wersją Horreum - ta wersja go nie "
                      "porówna, a Dostawa go nie uzupełni; odpowiedź da nowsza wersja programu.",
               "few": "W tym {n} kopie mają zeznanie zebrane nowszą wersją Horreum - ta wersja go "
                      "nie porówna, a Dostawa go nie uzupełni; odpowiedź da nowsza wersja programu.",
               "many": "W tym {n} kopii ma zeznanie zebrane nowszą wersją Horreum - ta wersja go "
                       "nie porówna, a Dostawa go nie uzupełni; odpowiedź da nowsza wersja "
                       "programu."},
        "en": {"one": "Of these, {n} copy has testimony collected by a newer Horreum - this version "
                      "cannot compare it and Intake will not fill it in; a newer version will.",
               "other": "Of these, {n} copies have testimony collected by a newer Horreum - this "
                        "version cannot compare it and Intake will not fill it in; a newer version "
                        "will."},
    },
    "tasks.vanished_frames": {"pl": "Zniknięte z dysku", "en": "Vanished from disk"},
    # NAZWA MÓWI O UBYTKU, NIE O AWARII (D-V-9a). Wiersz stoi obok „Zniknięte z dysku" i musi się
    # od niego odróżniać JEDNYM spojrzeniem: tam nie ma ani jednej żywej kopii i jest robota, tu
    # klatka żyje i nie ma nic do zrobienia. Stąd „kopie", nie „klatki", i człon w nawiasie, który
    # nazywa naturę wiersza dokładnie tak, jak robią to dwaj sąsiedzi z historii.
    "tasks.missing_copy_frames": {
        "pl": "Brakujące kopie (historia)", "en": "Missing copies (history)"},

    # --- perspektywa „Wersje stosów" (grid.py + tasks.py): ten sam materiał zintegrowany kilka razy.
    # Rodzaje członka i świadkowie to klucze SKŁADANE w locie (`grid.version.kind.<rodzaj>`,
    # `grid.version.why.<świadek>`) - parytet z tokenami read-modelu pinuje test perspektywy.
    "perspective.stack_versions": {"pl": "Wersje stosów", "en": "Stack versions"},
    "grid.criteria.only_stack_versions": {"pl": "tylko wersje stosów", "en": "only stack versions"},
    "tasks.stack_versions": {"pl": "Wersje stosów", "en": "Stack versions"},
    "grid.top.group_version": {"pl": "Wersja stosu", "en": "Stack version"},
    "grid.col.version": {"pl": "Wersja", "en": "Version"},
    "grid.version.group": {
        "pl": "{object} · {filter} · {exp} s · okno {start} - {end}",
        "en": "{object} · {filter} · {exp} s · window {start} - {end}"},
    "grid.version.group_rig": {
        "pl": " · zestaw {telescope} + {camera}", "en": " · rig {telescope} + {camera}"},
    "grid.version.no_object": {"pl": "(bez obiektu)", "en": "(no object)"},
    # Skrót świadka do komórki „Wersja" (pełne zdanie zostaje w `grid.version.why.<świadek>`).
    "grid.version.short.declared": {"pl": "historia", "en": "history"},
    "grid.version.short.tool": {"pl": "sygnatura", "en": "signature"},
    "grid.version.short.measure": {"pl": "szum i PSF", "en": "noise and PSF"},
    "grid.version.short.same_tool": {"pl": "ta sama sygnatura", "en": "same signature"},
    "grid.version.short.same_measure": {"pl": "te same pomiary", "en": "same measurements"},
    "grid.version.kind.inna": {"pl": "inna integracja", "en": "separate integration"},
    "grid.version.kind.pochodna": {
        "pl": "pochodna tej samej integracji", "en": "derived from the same integration"},
    "grid.version.kind.nieustalone": {"pl": "nieustalone", "en": "undetermined"},
    "grid.version.inputs": {
        "pl": {"one": "{n} wejście", "few": "{n} wejścia", "many": "{n} wejść"},
        "en": {"one": "{n} input", "other": "{n} inputs"},
    },
    "grid.version.why.declared": {
        "pl": "Dowód odrębnej integracji: historia pliku deklaruje inną liczbę wejść niż wersja obok.",
        "en": "Evidence of a separate integration: the file history declares a different number "
              "of inputs than the version next to it."},
    "grid.version.why.tool": {
        "pl": "Dowód odrębnej integracji: inna sygnatura przebiegu (PCL:Signature:Integration).",
        "en": "Evidence of a separate integration: a different run signature "
              "(PCL:Signature:Integration)."},
    "grid.version.why.measure": {
        "pl": "Dowód odrębnej integracji: inne pomiary szumu i PSF zapisane w nagłówku obrazu "
              "tego samego kanału.",
        "en": "Evidence of a separate integration: different noise and PSF measurements in the "
              "header of an image of the same channel."},
    "grid.version.why.same_tool": {
        "pl": "Pochodna: ta sama sygnatura integracji co stos obok.",
        "en": "Derived: the same integration signature as the stack next to it."},
    "grid.version.why.same_measure": {
        "pl": "Pochodna: identyczne pomiary szumu i PSF - nagłówek skopiowany z jednego obrazu.",
        "en": "Derived: identical noise and PSF measurements - the header was copied from one image."},
    "grid.version.why.none": {
        "pl": "Nieustalone: baza nie ma świadka - brak sygnatury, historii i porównywalnych pomiarów.",
        "en": "Undetermined: the database has no witness - no signature, no history and no "
              "comparable measurements."},
    "grid.version.window": {"pl": "\nOkno: {start} - {end}", "en": "\nWindow: {start} - {end}"},
    "grid.version.keep": {"pl": "Zostaw tę wersję", "en": "Keep this version"},
    "grid.version.keep_tip": {
        "pl": {"one": "Kopiuje do schowka {n} ścieżkę pozostałych wersji. Horreum niczego nie usuwa.",
               "few": "Kopiuje do schowka {n} ścieżki pozostałych wersji. Horreum niczego nie usuwa.",
               "many": "Kopiuje do schowka {n} ścieżek pozostałych wersji. Horreum niczego nie usuwa."},
        "en": {"one": "Copies {n} path of the other versions to the clipboard. Horreum deletes nothing.",
               "other": "Copies {n} paths of the other versions to the clipboard. "
                        "Horreum deletes nothing."},
    },
    "grid.version.select_one": {
        "pl": "Zaznacz dokładnie jeden stos - wersję, którą zostawiasz.",
        "en": "Select exactly one stack - the version you keep."},
    "grid.version.nothing": {
        "pl": "Ten stos nie ma w grupie wersji z dowodem odrębnej integracji - schowek bez zmian.",
        "en": "This stack has no version with evidence of a separate integration in its group - "
              "the clipboard is unchanged."},
    "grid.version.copied": {
        "pl": {"one": "Skopiowano do schowka {n} ścieżkę", "few": "Skopiowano do schowka {n} ścieżki",
               "many": "Skopiowano do schowka {n} ścieżek"},
        "en": {"one": "Copied {n} path to the clipboard", "other": "Copied {n} paths to the clipboard"},
    },
    "grid.version.copied_stacks": {
        "pl": {"one": " (pozostała wersja: {n} stos)", "few": " (pozostałe wersje: {n} stosy)",
               "many": " (pozostałe wersje: {n} stosów)"},
        "en": {"one": " (other version: {n} stack)", "other": " (other versions: {n} stacks)"},
    },
    "grid.version.skipped_unknown": {
        "pl": {"one": " · bez dowodu wersji pominięty {n} stos",
               "few": " · bez dowodu wersji pominięte {n} stosy",
               "many": " · bez dowodu wersji pominiętych {n} stosów"},
        "en": {"one": " · no version evidence, skipped {n} stack",
               "other": " · no version evidence, skipped {n} stacks"},
    },
    "grid.version.no_delete": {
        "pl": " · Horreum niczego nie usuwa - pliki usuwasz sam, a skan zdejmie je z tej listy",
        "en": " · Horreum deletes nothing - you delete the files yourself, and a scan takes them "
              "off this list"},
    # Werdykt „zostawiam wszystkie" grupy wersji (AR-10, 0026) i jego droga powrotu.
    "grid.version.keep_all": {"pl": "Zostaw wszystkie wersje", "en": "Keep all versions"},
    "grid.version.reopen": {"pl": "Cofnij „zostaw wszystkie”", "en": "Undo “keep all”"},
    "grid.version.keep_all_tip": {
        "pl": {"one": "Zapisuje werdykt: {n} stos tej grupy zostaje. Grupa przestaje być robotą "
                      "w Porządkach. Horreum niczego nie usuwa.",
               "few": "Zapisuje werdykt: {n} stosy tej grupy zostają. Grupa przestaje być robotą "
                      "w Porządkach. Horreum niczego nie usuwa.",
               "many": "Zapisuje werdykt: {n} stosów tej grupy zostaje. Grupa przestaje być robotą "
                       "w Porządkach. Horreum niczego nie usuwa."},
        "en": {"one": "Records the verdict: {n} stack of this group stays. The group stops being "
                      "work in Housekeeping. Horreum deletes nothing.",
               "other": "Records the verdict: {n} stacks of this group stay. The group stops being "
                        "work in Housekeeping. Horreum deletes nothing."},
    },
    "grid.version.reopen_tip": {
        "pl": {"one": "Cofa werdykt: {n} stos tej grupy wraca do roboty w Porządkach.",
               "few": "Cofa werdykt: {n} stosy tej grupy wracają do roboty w Porządkach.",
               "many": "Cofa werdykt: {n} stosów tej grupy wraca do roboty w Porządkach."},
        "en": {"one": "Withdraws the verdict: {n} stack of this group is work in Housekeeping again.",
               "other": "Withdraws the verdict: {n} stacks of this group are work in Housekeeping "
                        "again."},
    },
    "grid.version.select_group": {
        "pl": "Zaznacz stos (albo stosy) jednej grupy wersji.",
        "en": "Select a stack (or stacks) of one version group."},
    "grid.version.no_group": {
        "pl": "Ten stos nie należy już do żadnej grupy wersji - widok odświeży się przy następnym "
              "przeładowaniu.",
        "en": "This stack no longer belongs to any version group - the view refreshes on the next "
              "reload."},
    "grid.version.kept_done": {
        "pl": {"one": "Zapisano werdykt „zostaw wszystkie” - {n} stos grupy zostaje",
               "few": "Zapisano werdykt „zostaw wszystkie” - {n} stosy grupy zostają",
               "many": "Zapisano werdykt „zostaw wszystkie” - {n} stosów grupy zostaje"},
        "en": {"one": "Verdict “keep all” recorded - {n} stack of the group stays",
               "other": "Verdict “keep all” recorded - {n} stacks of the group stay"},
    },
    "grid.version.reopened_done": {
        "pl": {"one": "Cofnięto werdykt „zostaw wszystkie” - {n} stos grupy wraca do roboty",
               "few": "Cofnięto werdykt „zostaw wszystkie” - {n} stosy grupy wracają do roboty",
               "many": "Cofnięto werdykt „zostaw wszystkie” - {n} stosów grupy wraca do roboty"},
        "en": {"one": "Verdict “keep all” withdrawn - {n} stack of the group is work again",
               "other": "Verdict “keep all” withdrawn - {n} stacks of the group are work again"},
    },
    # Gest werdyktu, który nie ruszył żadnej klatki - werdykt zmienił w międzyczasie ktoś inny.
    "grid.version.kept_none": {
        "pl": "Werdykt „zostaw wszystkie” był już zapisany dla całej grupy - nic nie zmieniono",
        "en": "The “keep all” verdict was already recorded for the whole group - nothing changed"},
    "grid.version.reopened_none": {
        "pl": "Grupa nie ma już werdyktu „zostaw wszystkie” - nie było czego cofać",
        "en": "The group no longer has a “keep all” verdict - there was nothing to withdraw"},
    "grid.version.keep_blocked_kept": {
        "pl": "Grupa ma werdykt „zostaw wszystkie” - najpierw go cofnij („{reopen}”).",
        "en": "The group has a “keep all” verdict - withdraw it first (“{reopen}”)."},
    "grid.version.kept": {"pl": "zostawione", "en": "kept"},
    "grid.version.kept_tip": {
        "pl": "\nWerdykt: zostawiasz wszystkie wersje tej grupy ({at}). Droga powrotu: prawy klik "
              "→ „{reopen}”.",
        "en": "\nVerdict: you keep all versions of this group ({at}). Way back: right click "
              "→ “{reopen}”."},
    # Liczba obrazów kopii w kolumnie „Wersja" (AR-10). `count` to tekst komórki „Obrazy" (przy
    # kopiach różnych „3 | 1"), forma odmiany idzie za największą liczbą.
    "grid.version.images": {
        "pl": {"one": "{count} obraz", "few": "{count} obrazy", "many": "{count} obrazów"},
        "en": {"one": "{count} image", "other": "{count} images"},
    },
    "grid.version.images_fits": {"pl": "obrazy: -", "en": "images: -"},
    "grid.version.images_fits_tip": {
        "pl": "\nObrazy: plik FITS - Horreum czyta pierwszy obraz i nie liczy pozostałych.",
        "en": "\nImages: a FITS file - Horreum reads the first image and does not count the rest."},
    # Źródło daty w komórce „Wersja" - klucz składany z `timestamp_source` read-modelu.
    "grid.version.when.signature": {
        "pl": "\nData: chwila integracji z sygnatury (PCL:Signature:Integration).",
        "en": "\nDate: the integration time from the signature (PCL:Signature:Integration)."},
    "grid.version.when.created": {
        "pl": "\nData: XISF:CreationTime - chwila zapisu pliku zaraz po integracji (stos sprzed "
              "sygnatury integracji).",
        "en": "\nDate: XISF:CreationTime - when the file was saved right after integration (a stack "
              "from before the integration signature)."},
    # Środek kadru w kolumnie „Wersja" (AR-10) - fakt rozróżniający, nie świadek wersji.
    "grid.version.center": {"pl": "środek {label}", "en": "center {label}"},
    "grid.version.center_tip": {
        "pl": {"one": "\nŚrodek {label}: RA {ra}°, Dec {dec}° z nagłówka. W tej grupie jest {n} "
                      "środek kadru - stosy z tą samą literą mają ten sam. To fakt do rozróżnienia, "
                      "nie dowód odrębnej integracji: kanały jednej integracji też bywają "
                      "zapisane z różnymi środkami.",
               "few": "\nŚrodek {label}: RA {ra}°, Dec {dec}° z nagłówka. W tej grupie są {n} "
                      "różne środki kadru - stosy z tą samą literą mają ten sam. To fakt do "
                      "rozróżnienia, nie dowód odrębnej integracji: kanały jednej integracji też "
                      "bywają zapisane z różnymi środkami.",
               "many": "\nŚrodek {label}: RA {ra}°, Dec {dec}° z nagłówka. W tej grupie jest {n} "
                       "różnych środków kadru - stosy z tą samą literą mają ten sam. To fakt do "
                       "rozróżnienia, nie dowód odrębnej integracji: kanały jednej integracji też "
                       "bywają zapisane z różnymi środkami."},
        "en": {"one": "\nCenter {label}: RA {ra}°, Dec {dec}° from the header. This group has {n} "
                      "frame center - stacks with the same letter share it. A fact to tell them "
                      "apart, not evidence of a separate integration: channels of one integration "
                      "are sometimes saved with different centers too.",
               "other": "\nCenter {label}: RA {ra}°, Dec {dec}° from the header. This group has "
                        "{n} different frame centers - stacks with the same letter share one. A "
                        "fact to tell them apart, not evidence of a separate integration: channels "
                        "of one integration are sometimes saved with different centers too."},
    },
    "tasks.of_total": {"pl": "{open} z {total}", "en": "{open} of {total}"},
    "tasks.stack_versions_kept_tip": {
        "pl": {"one": "{n} stos stoi w grupie z werdyktem „{keep}” - to nie jest robota. Werdykt "
                      "cofniesz w tej perspektywie, prawym klikiem na stosie.",
               "few": "{n} stosy stoją w grupach z werdyktem „{keep}” - to nie jest robota. Werdykt "
                      "cofniesz w tej perspektywie, prawym klikiem na stosie.",
               "many": "{n} stosów stoi w grupach z werdyktem „{keep}” - to nie jest robota. "
                       "Werdykt cofniesz w tej perspektywie, prawym klikiem na stosie."},
        "en": {"one": "{n} stack is in a group with the verdict “{keep}” - that is not work. You "
                      "withdraw the verdict in this perspective, with a right click on the stack.",
               "other": "{n} stacks are in groups with the verdict “{keep}” - that is not work. You "
                        "withdraw the verdict in this perspective, with a right click on the stack."},
    },

    # --- kopia wiodąca klatki (grid.py, menu prawego kliku; AR-4, AR-23). Gest woła rdzeń
    # `lead_copy`: klatka przejmuje zeznanie wskazanej kopii, wybór jest faktem ręki.
    "grid.lead.menu": {"pl": "Ta kopia prowadzi", "en": "This copy leads"},
    "grid.lead.menu_tip": {
        "pl": "Wskaż kopię, której nagłówek ma mówić za klatkę. To Twój wybór - Dostawa go nie "
              "przestawi.",
        "en": "Pick the copy whose header speaks for the frame. It is your choice - Intake does "
              "not change it."},
    # Dopiski pozycji kopii (po ścieżce): kopia, której głosem mówi dziś klatka, i kopia bez
    # zebranego zeznania w bazie (nie wiadomo, czy mówi).
    "grid.lead.speaks": {"pl": "  · mówi teraz", "en": "  · speaks now"},
    "grid.lead.unread": {"pl": "  · bez zeznania w bazie", "en": "  · testimony not read"},
    # Kilka kopii zgodnych z zeznaniem klatki naraz: żadna z nich nie „mówi" sama, więc dopisek
    # mówi o zgodności, a wybór człowieka niesie osobny znacznik (`grid.lead.hand`, pozycja
    # zaznaczona) - także w podpowiedzi ścieżki w Zbiorach.
    "grid.lead.agrees": {"pl": "  · zgodna z zeznaniem", "en": "  · matches the testimony"},
    "grid.lead.agrees_tip": {
        "pl": "Nagłówek tej kopii jest zgodny z zeznaniem klatki - tak samo jak innej obecnej kopii. "
              "Wybór zapisze, że prowadzi ta.",
        "en": "This copy's header matches the frame testimony - as does another present copy. "
              "Picking it records that this one leads."},
    "grid.lead.hand": {"pl": "  · wskazana ręką", "en": "  · picked by hand"},
    "grid.lead.hand_tip": {
        "pl": "Tę kopię wskazałeś gestem „{lead}” - Dostawa jej nie przestawi.",
        "en": "You picked this copy with “{lead}” - Intake does not change it."},
    "grid.lead.speaks_tip": {
        "pl": "Klatka mówi dziś głosem tej kopii. Wybór potwierdzi go, o ile nagłówek pliku różni "
              "się od zapisanego.",
        "en": "The frame speaks with this copy's voice today. Picking it confirms that only if the "
              "file header differs from the stored one."},
    "grid.lead.choice_tip": {
        "pl": "Klatka przejmie nagłówek tej kopii (obiekt, filtr, ekspozycja, data z pliku).",
        "en": "The frame takes over this copy's header (object, filter, exposure, date from the "
              "file)."},
    "grid.lead.select_one": {
        "pl": "Zaznacz jedną klatkę - kopię wiodącą wskazuje się dla jednej klatki naraz.",
        "en": "Select one frame - the leading copy is picked for one frame at a time."},
    "grid.lead.not_waiting": {
        "pl": "Ta klatka nie czeka na wskazanie kopii - jej obecne kopie mówią jednym głosem z nią.",
        "en": "This frame is not waiting for a copy to be picked - its present copies agree with it."},
    # Zdania po geście: `{copy}` = katalog i nazwa pliku kopii, `{reason}` = diagnoza odczytu.
    "grid.lead.adopted": {
        "pl": "Klatka mówi teraz głosem kopii {copy}.",
        "en": "The frame now speaks with the voice of copy {copy}."},
    "grid.lead.back": {
        "pl": " Powrót: „{lead}” na kopii {copy}.",
        "en": " To go back: “{lead}” on copy {copy}."},
    "grid.lead.no_back": {
        "pl": " Poprzednie zeznanie pochodziło z kopii, której już nie ma - zostaje w dzienniku, "
              "gestem nie wróci.",
        "en": " The previous testimony came from a copy that is gone - it stays in the log, the "
              "gesture cannot bring it back."},
    "grid.lead.confirmed": {
        "pl": "Kopia {copy} prowadzi - zeznanie klatki bez zmian, wybór zapisany.",
        "en": "Copy {copy} leads - the frame testimony is unchanged, the choice is saved."},
    "grid.lead.unchanged": {
        "pl": "Klatka już mówi głosem kopii {copy} - nic nie zapisano.",
        "en": "The frame already speaks with the voice of copy {copy} - nothing was saved."},
    "grid.lead.absent": {
        "pl": "Kopii {copy} nie ma już na dysku - nic nie zapisano.",
        "en": "Copy {copy} is no longer on disk - nothing was saved."},
    "grid.lead.isolated": {
        "pl": "Kopia {copy} czeka na rozstrzygnięcie zapisu nagłówka (Porządki) - nic nie zapisano.",
        "en": "Copy {copy} awaits a decision about its header write (Housekeeping) - nothing was "
              "saved."},
    "grid.lead.failed": {
        "pl": "Nie udało się przeczytać kopii {copy}: {reason} - nic nie zapisano.",
        "en": "Copy {copy} could not be read: {reason} - nothing was saved."},
    "grid.lead.identity": {
        "pl": "Pod ścieżką kopii {copy} leży inna treść niż ta klatka - nic nie zapisano. "
              "Dostawa na jej katalogu przepnie kopię.",
        "en": "The path of copy {copy} holds content other than this frame - nothing was saved. "
              "Intake on its folder rebinds the copy."},
    "grid.lead.stale": {
        "pl": "Nagłówek kopii {copy} zmienił się od ostatniego skanu - nic nie zapisano. Po Dostawie "
              "na jej katalogu wskaż kopię jeszcze raz.",
        "en": "The header of copy {copy} changed since the last scan - nothing was saved. After "
              "Intake on its folder, pick the copy again."},
    "grid.lead.raced": {
        "pl": "Stan kopii {copy} zmienił się w trakcie gestu - nic nie zapisano. Wskaż kopię "
              "jeszcze raz.",
        "en": "The state of copy {copy} changed during the gesture - nothing was saved. Pick the "
              "copy again."},
    # Podpowiedzi dwóch wierszy Porządków kopii: gest mieszka w menu prawego kliku w Zbiorach.
    "tasks.copy_conflict_tip": {
        "pl": "Kopie jednej klatki mówią różnie, a oś klatki pokazuje głos jednej z nich.\n"
              "W Zbiorach: prawy klik na klatce → „{lead}” i kopia, której nagłówek ma mówić.",
        "en": "Copies of one frame disagree, and the frame axis shows the voice of one of them.\n"
              "In Collections: right-click the frame → “{lead}” and the copy whose header should "
              "speak."},
    "tasks.orphan_testimony_tip": {
        "pl": "Klatka mówi głosem pliku, którego już nie ma.\nW Zbiorach: prawy klik na klatce → "
              "„{lead}” i obecna kopia. Klatkę z jedną kopią naprawia też Dostawa na katalogu tej "
              "kopii.",
        "en": "The frame speaks with the voice of a file that is gone.\nIn Collections: "
              "right-click the frame → “{lead}” and a present copy. A frame with one copy is also "
              "fixed by Intake on that copy's folder."},
    "tasks.kept_copy_tip": {
        "pl": "Przerwany zapis zostawił kopie pliku obok ścieżki (*.horreum-kopia, *.tmp) - stanu nie "
              "dało się dowieść.\nPorównaj je z plikiem (ścieżki w dzienniku zdarzeń lokacji) "
              "i usuń zbędne; wiersz znika, gdy ich nie ma.",
        "en": "An interrupted write left copies of the file next to its path (*.horreum-kopia, "
              "*.tmp) - their state could not be proven.\nCompare them with the file (paths in the "
              "location's event log) and delete the unneeded ones; the row disappears when they "
              "are gone."},
    "tasks.withheld_testimony_tip": {
        "pl": "Plik kopii zapisany, ale klatka mówi głosem innej kopii.\nW Zbiorach: prawy klik na "
              "klatce → „{lead}” i zapisana kopia - zapis się dokończy. Albo „Cofnij” zapisu.",
        "en": "The copy's file was written, but the frame speaks with another copy's voice.\nIn "
              "Collections: right-click the frame → “{lead}” and the written copy - the write "
              "completes. Or “Undo” the write."},
    # Dopisek podpowiedzi „Kopii niezgodnych", gdy część klatek ma kopię wskazaną ręką: rozjazd
    # kopii zostaje faktem (lista go pokazuje), ale robotą nie jest.
    "tasks.copy_conflict_led_tip": {
        "pl": {"one": "\n{n} klatka ma kopię wiodącą wskazaną ręką - to nie jest robota. Zdanie "
                      "zmienisz tym samym gestem.",
               "few": "\n{n} klatki mają kopię wiodącą wskazaną ręką - to nie jest robota. Zdanie "
                      "zmienisz tym samym gestem.",
               "many": "\n{n} klatek ma kopię wiodącą wskazaną ręką - to nie jest robota. Zdanie "
                       "zmienisz tym samym gestem."},
        "en": {"one": "\n{n} frame has its leading copy picked by hand - that is not work. You "
                      "change your mind with the same gesture.",
               "other": "\n{n} frames have their leading copy picked by hand - that is not work. "
                        "You change your mind with the same gesture."},
    },

    # --- drogi wyjścia z izolacji zapisu w miejscu (grid.py, menu prawego kliku; AR-17 (2)).
    # Kopia z operacją w fazie izolującej jest pomijana przez skan; gesty wołają rdzeń
    # (`writeback.finish_inplace` / `writeback.recover_torn` / `writeback.release_isolation`).
    "grid.inplace.finish": {"pl": "Dokończ zapis", "en": "Finish the write"},
    "grid.inplace.restore": {
        "pl": "Przywróć nagłówek sprzed zapisu", "en": "Restore the header from before the write"},
    "grid.inplace.release": {"pl": "Zwolnij plik do skanu…", "en": "Release the file to the scan…"},
    "grid.inplace.none": {
        "pl": "Zaznaczone klatki nie mają przerwanego ani niedokończonego zapisu nagłówka.",
        "en": "The selected frames have no interrupted or unfinished header write."},
    "grid.inplace.busy_stage": {
        "pl": "Trwa etap Dostawy - gest ruszy po jego zakończeniu.",
        "en": "An Intake stage is running - the gesture starts after it finishes."},
    "grid.inplace.busy_write": {
        "pl": "Trwa zapis nagłówków do plików - gest ruszy po jego zakończeniu.",
        "en": "A header write to files is in progress - the gesture starts after it finishes."},
    # „Dokończ" nie ma sensu przy zapisie przerwanym - zdanie mówi, która droga jest właściwa.
    "grid.inplace.finish_open_only": {
        "pl": "Dokończyć można tylko zapis, który przeszedł weryfikację i czeka na dokończenie. "
              "Przy zapisie przerwanym: „{restore}”.",
        "en": "Only a write that passed verification and awaits completion can be finished. "
              "For an interrupted write: “{restore}”."},
    "grid.inplace.finish_tip": {
        "pl": {"one": "Dokończy {n} zapis: kontrola danych pliku i wciągnięcie nagłówka do bazy, "
                      "potem plik wraca do skanu.",
               "few": "Dokończy {n} zapisy: kontrola danych pliku i wciągnięcie nagłówka do bazy, "
                      "potem pliki wracają do skanu.",
               "many": "Dokończy {n} zapisów: kontrola danych pliku i wciągnięcie nagłówka do "
                       "bazy, potem pliki wracają do skanu."},
        "en": {"one": "Finishes {n} write: a data check of the file and taking the header into "
                      "the database, then the file returns to the scan.",
               "other": "Finishes {n} writes: a data check of each file and taking the header "
                        "into the database, then the files return to the scan."},
    },
    # AR-30 (2): dopisek do `finish_tip` - dokończenie odmawia przy nieudanej kontroli danych
    # i przy pliku, którego nie ma albo który jest inny; podpowiedź wskazuje wtedy właściwy gest.
    "grid.inplace.finish_tip_else": {
        "pl": " Gdy plik nie przejdzie kontroli danych - „{restore}”; gdy pliku nie ma albo to "
              "inny plik - „{release}”.",
        "en": " When the file fails the data check - “{restore}”; when the file is gone or is a "
              "different file - “{release}”."},
    # AR-30 (4): cel gestu to klatka, wykonanie idzie per kopia - przy kilku kopiach jednej klatki
    # w izolacji podpowiedź mówi, które pliki gest ruszy. Zdanie NEUTRALNE wobec liczby klatek:
    # lista `{files}` zbiera kopie WSZYSTKICH zaznaczonych klatek wielokopiowych, a dawne „Klatka
    # ma kilka kopii” mówiło o jednej klatce przy liście plików z kilku.
    "grid.inplace.many_copies": {
        "pl": {"one": " Gest obejmie każdą kopię w izolacji, także kilka kopii tej samej klatki - "
                      "{n} plik: {files}.",
               "few": " Gest obejmie każdą kopię w izolacji, także kilka kopii tej samej klatki - "
                      "{n} pliki: {files}.",
               "many": " Gest obejmie każdą kopię w izolacji, także kilka kopii tej samej klatki - "
                       "{n} plików: {files}."},
        "en": {"one": " The gesture covers every isolated copy, including several copies of the "
                      "same frame - {n} file: {files}.",
               "other": " The gesture covers every isolated copy, including several copies of the "
                        "same frame - {n} files: {files}."},
    },
    "grid.inplace.restore_tip": {
        "pl": {"one": "Przywróci stary nagłówek w {n} pliku, w miejscu, i zdejmie izolację.",
               "few": "Przywróci stary nagłówek w {n} plikach, w miejscu, i zdejmie izolację.",
               "many": "Przywróci stary nagłówek w {n} plikach, w miejscu, i zdejmie izolację."},
        "en": {"one": "Restores the old header in {n} file, in place, and lifts the isolation.",
               "other": "Restores the old header in {n} files, in place, and lifts the isolation."},
    },
    # Dopisek przy zapisie czekającym na dokończenie: rdzeń cofa go WYŁĄCZNIE przy nieudanej
    # kontroli danych, poprawny zapis odmawia z drogą do dokończenia.
    "grid.inplace.restore_tip_written": {
        "pl": " Zapis czekający na dokończenie cofa tylko wtedy, gdy plik nie przechodzi kontroli "
              "danych - poprawny zapis: „{finish}”.",
        "en": " A write awaiting completion is undone only when the file fails the data check - "
              "for a correct write: “{finish}”."},
    "grid.inplace.release_tip": {
        "pl": {"one": "Zdejmie izolację {n} pliku bez zmiany pliku i bez sprawdzania - po Twoim "
                      "rozstrzygnięciu, że plik jest w porządku. Wymaga powodu.",
               "few": "Zdejmie izolację {n} plików bez zmiany plików i bez sprawdzania - po Twoim "
                      "rozstrzygnięciu, że pliki są w porządku. Wymaga powodu.",
               "many": "Zdejmie izolację {n} plików bez zmiany plików i bez sprawdzania - po "
                       "Twoim rozstrzygnięciu, że pliki są w porządku. Wymaga powodu."},
        "en": {"one": "Lifts the isolation of {n} file without changing or checking it - after "
                      "your own decision that the file is fine. Needs a reason.",
               "other": "Lifts the isolation of {n} files without changing or checking them - "
                        "after your own decision that the files are fine. Needs a reason."},
    },
    # Zdanie wyniku na pasku - człon główny, człony odmów (tylko gdy są) i pierwszy powód rdzenia.
    "grid.inplace.finished": {
        "pl": {"one": "Dokończono {n} zapis", "few": "Dokończono {n} zapisy",
               "many": "Dokończono {n} zapisów"},
        "en": {"one": "Finished {n} write", "other": "Finished {n} writes"},
    },
    "grid.inplace.restored": {
        "pl": {"one": "Przywrócono nagłówek w {n} pliku", "few": "Przywrócono nagłówek w {n} plikach",
               "many": "Przywrócono nagłówek w {n} plikach"},
        "en": {"one": "Restored the header in {n} file", "other": "Restored the header in {n} files"},
    },
    "grid.inplace.released": {
        "pl": {"one": "Zwolniono do skanu {n} plik", "few": "Zwolniono do skanu {n} pliki",
               "many": "Zwolniono do skanu {n} plików"},
        "en": {"one": "Released {n} file to the scan", "other": "Released {n} files to the scan"},
    },
    "grid.inplace.blocked": {
        "pl": {"one": " · zablokowany {n}", "few": " · zablokowane {n}", "many": " · zablokowanych {n}"},
        "en": {"one": " · blocked {n}", "other": " · blocked {n}"},
    },
    "grid.inplace.failed": {
        "pl": {"one": " · nieudany {n}", "few": " · nieudane {n}", "many": " · nieudanych {n}"},
        "en": {"one": " · failed {n}", "other": " · failed {n}"},
    },
    "grid.inplace.cancelled": {
        "pl": " · przerwano, reszta nietknięta", "en": " · interrupted, the rest untouched"},
    "grid.inplace.detail": {"pl": " - {file}: {detail}", "en": " - {file}: {detail}"},
    # Okno „Zwolnij plik do skanu…": skutek słowami + powód człowieka (idzie do dziennika).
    "grid.inplace.release_ask": {
        "pl": {"one": "Zwolnienie zdejmie izolację {n} pliku BEZ zmiany pliku i bez żadnego "
                      "sprawdzenia - skan przeczyta go potem jak każdy inny. Zrób to wtedy, gdy sam "
                      "sprawdziłeś, że plik jest w porządku (np. przywrócony z pełnej kopii).\n"
                      "Powód zapisze się w dzienniku:",
               "few": "Zwolnienie zdejmie izolację {n} plików BEZ zmiany plików i bez żadnego "
                      "sprawdzenia - skan przeczyta je potem jak każde inne. Zrób to wtedy, gdy sam "
                      "sprawdziłeś, że pliki są w porządku (np. przywrócone z pełnej kopii).\n"
                      "Powód zapisze się w dzienniku:",
               "many": "Zwolnienie zdejmie izolację {n} plików BEZ zmiany plików i bez żadnego "
                       "sprawdzenia - skan przeczyta je potem jak każde inne. Zrób to wtedy, gdy "
                       "sam sprawdziłeś, że pliki są w porządku (np. przywrócone z pełnej kopii).\n"
                       "Powód zapisze się w dzienniku:"},
        "en": {"one": "Releasing lifts the isolation of {n} file WITHOUT changing it and without "
                      "any check - the scan will then read it like any other. Do it when you have "
                      "checked yourself that the file is fine (e.g. restored from a full copy).\n"
                      "The reason goes into the log:",
               "other": "Releasing lifts the isolation of {n} files WITHOUT changing them and "
                        "without any check - the scan will then read them like any other. Do it "
                        "when you have checked yourself that the files are fine (e.g. restored "
                        "from a full copy).\nThe reason goes into the log:"},
    },
    "grid.inplace.release_placeholder": {
        "pl": "np. przywrócony z pełnej kopii, porównany hashem",
        "en": "e.g. restored from a full copy, compared by hash"},
    "grid.inplace.release_ok": {"pl": "Zwolnij", "en": "Release"},
    "grid.inplace.release_need_reason": {
        "pl": "Wpisz powód - zwolnienie to Twoje rozstrzygnięcie i zostaje w dzienniku.",
        "en": "Enter a reason - releasing is your decision and stays in the log."},
    # Recepta przy wejściu w perspektywę izolacji: gesty są w menu prawego kliku, którego nie widać.
    "grid.inplace.recipe_torn": {
        "pl": "zaznacz klatki, prawy klik → „{restore}” albo „{release}”",
        "en": "select the frames, right-click → “{restore}” or “{release}”"},
    "grid.inplace.recipe_pending": {
        "pl": "zaznacz klatki, prawy klik → „{finish}”",
        "en": "select the frames, right-click → “{finish}”"},

    # --- facets.py (listwa facetów): _GROUPS tytuły trzymają KLUCZE ---
    "facets.group.object": {"pl": "Obiekt", "en": "Object"},
    "facets.group.filter": {"pl": "Filtr", "en": "Filter"},
    "facets.group.kind": {"pl": "Rodzaj", "en": "Kind"},
    "facets.group.telescope": {"pl": "Teleskop", "en": "Telescope"},
    "facets.group.night": {"pl": "Noc", "en": "Night"},
    # Skrót nazwany WPROST w podpowiedzi pola: `QShortcut` jest w GUI niewidoczny, a „3 interakcje
    # → 2" nie zadziała dla kogoś, kto nie wie, że skrót istnieje (bramka pakietu, zarzut 14).
    "facets.search_object": {"pl": "szukaj obiektu (Ctrl+F)…", "en": "search object (Ctrl+F)…"},
    "facets.tip.clicks": {
        "pl": "Klik: uwzględnij → wyklucz → wyczyść   ·   Prawy klik: wyklucz wprost",
        "en": "Click: include → exclude → clear   ·   Right click: exclude directly",
    },
    "facets.hidden": {"pl": "(+{n} ukryte)", "en": "(+{n} hidden)"},
    # R-S3-9: wiersz trafiony CUDZĄ nazwą mówi którą — bez tego „Large Magellanic Cloud" dawało
    # `LMC` i nic nie tłumaczyło, dlaczego pasuje. Alias mówi brzmieniem z okna „Przypisz obiekt”
    # (słownik własny, potem karta `OBJECT`; AR-45), a klucz `alias_norm` tylko tam, gdzie brzmienia brak.
    "facets.tip.alias_hit": {
        "pl": "Pasuje przez inną nazwę tego obiektu: {alias}",
        "en": "Matched by another name of this object: {alias}",
    },
    # R-S3-5: stan pusty miał projekt „niemy prostokąt ~180 px". Dwa zdania, bo to dwie różne
    # prawdy: „fraza nic nie znalazła" (zawęź inaczej) vs „ta grupa nie ma nic do pokazania przy
    # obecnym zawężeniu" (poluzuj INNY facet).
    "facets.empty_search": {
        "pl": "Brak trafień dla „{fraza}”", "en": "No matches for “{fraza}”"},
    "facets.empty_group": {
        "pl": "Brak wartości przy tym zawężeniu", "en": "No values with the current narrowing"},

    # --- portfolio.py (Qt-wolny agregat godzin): _NO_FILTER trzyma KLUCZ ---
    "portfolio.no_filter": {"pl": "(bez filtra)", "en": "(no filter)"},
    "portfolio.plus_no_exptime": {
        "pl": " (+{n} bez exptime)", "en": " (+{n} without exptime)",
    },
    "portfolio.frames_no_exptime": {
        "pl": "+{n} klatek bez exptime", "en": "+{n} frames without exptime",
    },
    # AR-75: czas materiału poniżej 0,1 h mówi minutami (`format_hours`)
    "portfolio.minutes": {"pl": "{n} min", "en": "{n} min"},
    "portfolio.under_minute": {"pl": "< 1 min", "en": "< 1 min"},

    # --- KANAŁ gotowego obrazu (0028, P4-3): grupa listwy facetów ---
    "facets.group.channel": {"pl": "Kanał", "en": "Channel"},
    # --- RODOWÓD gotowego obrazu: grupa listwy facetów (stany `grid.lineage.state.*`) ---
    "facets.group.lineage": {"pl": "Rodowód", "en": "Lineage"},

    # --- ZMIANA OBIEKTU RAZEM Z PLIKIEM (AR-17 krok 3, D-1011-5) i karta w miejscu (AR-117) ---
    # Okno podglądu i wykonania (`gui/object_change_dialog.py`).
    "objchg.title_change": {"pl": "Zmień obiekt", "en": "Change object"},
    "objchg.title_align": {"pl": "Uzgodnij pliki z obiektem", "en": "Align files with their object"},
    "objchg.head_change": {
        "pl": {"one": "Zmiana obiektu {n} zaznaczonej klatki na {canon} - karta OBJECT: „{card}”.",
               "few": "Zmiana obiektu {n} zaznaczonych klatek na {canon} - karta OBJECT: „{card}”.",
               "many": "Zmiana obiektu {n} zaznaczonych klatek na {canon} - karta OBJECT: „{card}”."},
        "en": {"one": "Changing the object of {n} selected frame to {canon} - OBJECT card: “{card}”.",
               "other": "Changing the object of {n} selected frames to {canon} - OBJECT card: "
                        "“{card}”."}},
    "objchg.head_align": {
        "pl": {"one": "Uzgodnienie pliku {n} zaznaczonej klatki z obiektem, który już ma.",
               "few": "Uzgodnienie plików {n} zaznaczonych klatek z obiektem, który już mają.",
               "many": "Uzgodnienie plików {n} zaznaczonych klatek z obiektem, który już mają."},
        "en": {"one": "Aligning the file of {n} selected frame with the object it already has.",
               "other": "Aligning the files of {n} selected frames with the object they already "
                        "have."}},
    "objchg.explain_change": {
        "pl": "Najpierw baza (obiekt z ręki), potem plik: przeniesienie do folderu obiektu "
              "i karta OBJECT w pliku - per plik razem albo wcale. „Cofnij” przywraca karty, "
              "pliki, katalogi i obiekt, dopóki okno jest otwarte.",
        "en": "Database first (object set by hand), then the file: a move into the object folder "
              "and the OBJECT card in the file - per file together or not at all. “Undo” "
              "restores cards, files, folders and the object while the window is open."},
    "objchg.explain_align": {
        "pl": "Obiekt w bazie zostaje. Plik jedzie do folderu swojego obiektu, a karta OBJECT "
              "dostaje jego formę - per plik razem albo wcale. „Cofnij” działa, dopóki okno jest "
              "otwarte.",
        "en": "The object in the database stays. The file moves into its object folder and the "
              "OBJECT card gets the object form - per file together or not at all. “Undo” works "
              "while the window is open."},
    # Reguła nazwy pliku (D-1011-6 `O2`) - widoczna przed kliknięciem, bo z listy folderów jej
    # nie widać.
    "objchg.name_rule": {
        "pl": "Nazwa pliku: zmienia się wyłącznie człon obiektu na początku nazwy, reszta zostaje "
              "znak w znak; nazwa, która obiektem się nie zaczyna (np. nazwa z aparatu), zostaje "
              "cała. Pełne przemianowanie robi pasek „Nazwy”.",
        "en": "File name: only the object part at the start of the name changes, the rest stays "
              "exactly as it is; a name that does not start with the object (e.g. a camera name) "
              "stays whole. A full rename is done by the “Names” bar."},
    # Nagłówek „Uzgodnij” nazywa obiekty klatek (doklejany do `objchg.head_align` i
    # `objchg.head_resume_align`); ponad trzy - reszta liczbą (`objchg.head_objects_more`).
    "objchg.head_objects": {
        "pl": {"one": " Obiekt w bazie: {objects}.",
               "few": " Obiekty w bazie ({n}): {objects}.",
               "many": " Obiekty w bazie ({n}): {objects}."},
        "en": {"one": " Object in the database: {objects}.",
               "other": " Objects in the database ({n}): {objects}."}},
    "objchg.head_objects_more": {
        "pl": {"one": " i {n} inny", "few": " i {n} inne", "many": " i {n} innych"},
        "en": {"one": " and {n} more", "other": " and {n} more"}},
    # Wejście z Porządków na przerwany przebieg (AR-121): okno bez planu, stan z bazy. Numer
    # przebiegu niesie wiersz stanu pod listą (do zaznaczenia i skopiowania), nie nagłówek.
    "objchg.head_resume_change": {
        "pl": {"one": "Przerwany przebieg: zmiana obiektu {n} klatki na {canon} - karta "
                      "OBJECT: „{card}”.",
               "few": "Przerwany przebieg: zmiana obiektu {n} klatek na {canon} - karta "
                      "OBJECT: „{card}”.",
               "many": "Przerwany przebieg: zmiana obiektu {n} klatek na {canon} - karta "
                       "OBJECT: „{card}”."},
        "en": {"one": "Interrupted run: changing the object of {n} frame to {canon} - "
                      "OBJECT card: “{card}”.",
               "other": "Interrupted run: changing the object of {n} frames to {canon} - "
                        "OBJECT card: “{card}”."}},
    "objchg.head_resume_align": {
        "pl": {"one": "Przerwany przebieg: uzgodnienie pliku {n} klatki z obiektem.",
               "few": "Przerwany przebieg: uzgodnienie plików {n} klatek z obiektem.",
               "many": "Przerwany przebieg: uzgodnienie plików {n} klatek z obiektem."},
        "en": {"one": "Interrupted run: aligning the file of {n} frame with its object.",
               "other": "Interrupted run: aligning the files of {n} frames with their object."}},
    "objchg.explain_resume": {
        "pl": "Stan pozycji z bazy. „Dokończ” zapisuje pozycje, które czekają; „Cofnij” przywraca "
              "karty, pliki, katalogi i obiekt sprzed gestu.",
        "en": "Item state from the database. “Finish” writes the items that are waiting; “Undo” "
              "restores cards, files, folders and the object from before the gesture."},
    "objchg.st.pending": {"pl": "czeka na zapis", "en": "waiting to be written"},
    "objchg.st.pending_to": {"pl": "czeka na zapis → {path}", "en": "waiting to be written → {path}"},
    "objchg.explain_resume_undoing": {
        "pl": "Cofanie tego przebiegu zostało przerwane. „Cofnij” dokończy je od pierwszej "
              "niedomkniętej pozycji - do stanu sprzed gestu.",
        "en": "Undoing this run was interrupted. “Undo” finishes it from the first unfinished "
              "item - back to the state before the gesture."},
    "objchg.explain_resume_failed": {
        "pl": "Przebieg ma pozycję w stanie częściowym - powód i drogę dalej mówi kolumna Status. "
              "„Cofnij” cofa cały przebieg.",
        "en": "The run has an item in a partial state - the Status column gives the reason and the "
              "way forward. “Undo” reverts the whole run."},
    "objchg.finish_btn_bare": {"pl": "Dokończ", "en": "Finish"},
    "objchg.col.old": {"pl": "Plik dziś", "en": "File now"},
    "objchg.col.new": {"pl": "Po zmianie", "en": "After the change"},
    "objchg.col.card": {"pl": "Karta OBJECT", "en": "OBJECT card"},
    "objchg.col.reason": {"pl": "Powód / plik", "en": "Reason / file"},
    "objchg.col.n": {"pl": "Klatek", "en": "Frames"},
    "objchg.undo_btn": {"pl": "Cofnij", "en": "Undo"},
    "objchg.close_btn": {"pl": "Zamknij", "en": "Close"},
    "objchg.planning": {"pl": "Liczę plan - sprawdzam foldery celu na dysku…",
                        "en": "Computing the plan - checking target folders on disk…"},
    "objchg.err.plan": {"pl": "Plan się nie policzył: {msg}", "en": "The plan failed: {msg}"},
    "objchg.no_move": {"pl": "bez przeniesienia", "en": "no move"},
    "objchg.mkdirs_tip": {"pl": "Nowe katalogi:\n{dirs}", "en": "New folders:\n{dirs}"},
    "objchg.skipped_head": {
        "pl": {"one": "Pominie {n} klatkę - powód i plik:",
               "few": "Pominie {n} klatki - powody i pliki:",
               "many": "Pominie {n} klatek - powody i pliki:"},
        "en": {"one": "Skips {n} frame - reason and file:",
               "other": "Skips {n} frames - reasons and files:"}},
    "objchg.counts": {
        "pl": "Do innego folderu: {folder} · nowa nazwa w tym samym folderze: {nazwa} · karty "
              "OBJECT: {karty} · nowe katalogi: {katalogi} · usunie pustych katalogów: {usunie} · "
              "obiekt w bazie: {obiekt} · bez zmian: {bez_zmian} · pominie: {pominie}",
        "en": "To another folder: {folder} · new name in the same folder: {nazwa} · OBJECT cards: "
              "{karty} · new folders: {katalogi} · empty folders to remove: {usunie} · object in "
              "the database: {obiekt} · unchanged: {bez_zmian} · skipped: {pominie}"},
    "objchg.rmdirs_tip": {"pl": "Puste po zmianie - zostaną usunięte:\n{dirs}",
                          "en": "Empty after the change - will be removed:\n{dirs}"},
    # Lista po biegu (zapis albo cofnięcie): co się stało z pozycją.
    "objchg.col.was": {"pl": "Było", "en": "Was"},
    "objchg.col.is": {"pl": "Jest", "en": "Is now"},
    "objchg.col.status": {"pl": "Status", "en": "Status"},
    "objchg.st.done": {"pl": "zrobione", "en": "done"},
    "objchg.st.undone": {"pl": "cofnięte", "en": "undone"},
    "objchg.st.blocked": {"pl": "zablokowane", "en": "blocked"},
    "objchg.st.failed": {"pl": "błąd", "en": "error"},
    "objchg.st.withheld": {"pl": "karta zapisana, zeznanie wstrzymane",
                           "en": "card written, testimony withheld"},
    "objchg.st.skipped": {"pl": "pominięte", "en": "skipped"},
    "objchg.st.untouched": {"pl": "nie ruszone (bieg przerwany przed tą pozycją)",
                            "en": "untouched (the run stopped before this item)"},
    "objchg.st.reason": {"pl": " - {reason}", "en": " - {reason}"},
    # Spadek karty na drogę atomową w wierszu listy - to samo zdanie człowieka co w wyniku okna
    # (`wb.inplace_fallback`); szczegół rdzenia w podpowiedzi.
    "objchg.st.rewritten": {
        "pl": "cały plik przepisany (karty nie dało się wpisać w samym nagłówku)",
        "en": "whole file rewritten (the card could not be written into the header alone)"},
    "objchg.st.detail_tip": {"pl": "Szczegół techniczny: {detail}",
                             "en": "Technical detail: {detail}"},
    # Plik zajęty przez inny program w powodzie rdzenia (`czytelny_powod`) - bliźniak powodu
    # przeniesienia rdzenia po AR-125.
    "objchg.reason.busy": {"pl": "plik zajęty przez inny program - spróbuj ponownie za chwilę",
                           "en": "the file is in use by another program - try again in a moment"},
    # Powody POZYCJI przebiegu po KODZIE (`item_reasons.ITEM_REASON_CODES`, AR-141) - zdanie
    # w języku UI także dla powodu zapisanego w bazie (okno z Porządków); PL znak w znak jak zdanie
    # rdzenia (test AST). `{inner}`/`{outer}`/`{detail}` = powód niższej warstwy: z kodem w języku
    # UI, bez kodu (pisarz karty, tekst systemu) - znak w znak. Uwagi (`notes`) idą za zdaniem.
    "objchg.item.rename_open": {
        "pl": "przerwany rename tego pliku czeka na rozstrzygnięcie (zamiar otwarty) - powód "
              "w wyniku rekoncyliacji",
        "en": "an interrupted move of this file awaits resolution (intent open) - the reason is "
              "in the reconciliation result"},
    "objchg.item.no_location": {"pl": "brak location w bazie",
                                "en": "no location in the database"},
    "objchg.item.copy_gone": {"pl": "kopia zniknęła (present=0)",
                              "en": "the copy is gone (present=0)"},
    "objchg.item.path_moved": {
        "pl": "kopia stoi pod inną ścieżką niż w podglądzie - odśwież podgląd",
        "en": "the copy is at a different path than in the preview - refresh the preview"},
    "objchg.item.no_mtime_anchor": {
        "pl": "kopia bez kotwicy mtime z podglądu - gest nie wie, czy to ten sam plik",
        "en": "the copy has no mtime anchor from the preview - the gesture cannot tell whether it "
              "is the same file"},
    "objchg.item.changed_since_preview": {
        "pl": "plik zmieniony od podglądu (mtime w bazie) - odśwież podgląd",
        "en": "the file changed since the preview (mtime in the database) - refresh the preview"},
    "objchg.item.unreachable": {"pl": "plik nieosiągalny przed zapisem ({detail})",
                                "en": "the file is unreachable before writing ({detail})"},
    "objchg.item.changed_since_scan": {
        "pl": "plik zmieniony od ostatniego skanu - Dostawa, potem gest ponownie",
        "en": "the file changed since the last scan - run Intake, then the gesture again"},
    "objchg.item.rename_bounced": {
        "pl": "przeniesienie odbite w poprzedniej próbie (status {status}) - odśwież podgląd",
        "en": "the move was refused in the previous attempt (status {status}) - refresh the "
              "preview"},
    "objchg.item.target_taken": {"pl": "cel zajęty w bazie (location:{location})",
                                 "en": "the target is taken in the database (location:{location})"},
    "objchg.item.header_changed": {
        "pl": "nagłówek zmieniony od podglądu albo bez kotwicy (header_hash) - karta nie wejdzie; "
              "odśwież podgląd",
        "en": "the header changed since the preview or has no anchor (header_hash) - the card "
              "will not go in; refresh the preview"},
    "objchg.item.db_refused": {"pl": "zmiana obiektu odmówiona: {inner}",
                               "en": "object change refused: {inner}"},
    "objchg.item.copies_changed": {
        "pl": "klatka nie ma dokładnie jednej obecnej kopii, tej z podglądu - kopia wjechała albo "
              "zniknęła po podglądzie; odśwież podgląd",
        "en": "the frame does not have exactly one present copy, the one from the preview - a copy "
              "arrived or disappeared after the preview; refresh the preview"},
    "objchg.item.drift_resumed": {
        "pl": "obiekt klatki zmienił się po kroku bazy tej pozycji (przed awarią) - plik nie jest "
              "dalej ruszany",
        "en": "the frame's object changed after this item's database step (before the crash) - "
              "the file is not touched further"},
    "objchg.item.drift_resumed_undo": {
        "pl": "obiekt klatki zmienił się po kroku bazy tej pozycji (przed awarią) - plik nie jest "
              "dalej ruszany; resztę gestu zdejmuje cofnięcie przebiegu",
        "en": "the frame's object changed after this item's database step (before the crash) - "
              "the file is not touched further; undoing the run removes the rest of the gesture"},
    "objchg.item.drift": {
        "pl": "obiekt klatki zmienił się od podglądu (dryf) - pozycja nietknięta; odśwież podgląd",
        "en": "the frame's object changed since the preview (drift) - item untouched; refresh the "
              "preview"},
    "objchg.item.dir_intent_failed": {
        "pl": "zamiar katalogu {dir} nie zapisany ({detail}) - katalogu nie założono, pliku nie "
              "ruszono",
        "en": "the intent for folder {dir} was not saved ({detail}) - the folder was not created, "
              "the file was not touched"},
    "objchg.item.dir_create_failed": {
        "pl": "katalogu {dir} nie da się założyć ({detail}) - pliku nie ruszono",
        "en": "folder {dir} cannot be created ({detail}) - the file was not touched"},
    "objchg.item.dir_unconfirmed": {
        "pl": "katalog {dir} założony, ale jego potwierdzenie w bazie padło ({detail}) - zostaje do "
              "oka, pliku nie ruszono",
        "en": "folder {dir} was created, but confirming it in the database failed ({detail}) - it "
              "stays for review, the file was not touched"},
    "objchg.item.target_dir_missing": {
        "pl": "katalog celu {dir} nie istnieje, a podgląd go nie zakładał - odśwież podgląd",
        "en": "the target folder {dir} does not exist and the preview did not plan to create it - "
              "refresh the preview"},
    "objchg.item.rename_torn": {
        "pl": "{inner}; baza pozycji jak po kroku bazy - miejsce pliku rozstrzyga rekoncyliacja "
              "renamu, drogą dalej jest cofnięcie przebiegu",
        "en": "{inner}; the item's database state is as after the database step - move "
              "reconciliation decides where the file is, the way forward is undoing the run"},
    "objchg.item.card_refused": {"pl": "karta odbita bez zapisu: {inner}",
                                 "en": "card refused without writing: {inner}"},
    "objchg.item.card_partial": {
        "pl": "karta zapisana częściowo: {inner}; plik zostaje pod {path}, baza pozycji jak po "
              "zapisie - najpierw naprawa karty wg powodu, potem ewentualnie cofnięcie przebiegu",
        "en": "card partly written: {inner}; the file stays at {path}, the item's database state "
              "is as after writing - first repair the card as the reason says, then undo the run "
              "if needed"},
    "objchg.item.card_prev_failed": {"pl": "karta z poprzedniej próby: {inner}",
                                     "en": "card from the previous attempt: {inner}"},
    "objchg.item.card_prev_refused": {"pl": "karta odbita w poprzedniej próbie: {inner}",
                                      "en": "card refused in the previous attempt: {inner}"},
    "objchg.item.inplace_fallback": {"pl": "droga dotychczasowa: {detail}",
                                     "en": "previous route (whole file rewritten): {detail}"},
    "objchg.item.confirmed_from_disk": {
        "pl": "zapis potwierdzony z dysku po przerwanym commicie {commits} - nic do zapisania",
        "en": "write confirmed from disk after the interrupted commit {commits} - nothing to "
              "write"},
    "objchg.item.file_not_back": {
        "pl": "{outer}; plik NIE wrócił pod {path} ({inner}) - zostaje pod nową ścieżką, baza "
              "pozycji jak po zapisie; drogą dalej jest cofnięcie przebiegu",
        "en": "{outer}; the file did NOT return to {path} ({inner}) - it stays at the new path, "
              "the item's database state is as after writing; the way forward is undoing the run"},
    "objchg.item.undo_card": {"pl": "karta nie wróciła: {inner}",
                              "en": "the card did not return: {inner}"},
    "objchg.item.undo_file": {"pl": "plik nie wrócił: {inner}",
                              "en": "the file did not return: {inner}"},
    "objchg.item.undo_before_write": {
        "pl": "przebieg cofnięty, zanim zapis doszedł do tej pozycji",
        "en": "the run was undone before writing reached this item"},
    "objchg.item.undo_refused_earlier": {"pl": "odmówione przy zapisie - nic do cofnięcia",
                                         "en": "refused when writing - nothing to undo"},
    "objchg.item.isolated_recover": {
        "pl": "lokacja ma nieukończony zapis w miejscu (operacja {op_id}, {op_kind}, faza "
              "{phase}) - plik jest izolowany; najpierw odzysk: „Przywróć nagłówek sprzed zapisu” "
              "(`recover_torn({op_id})`)",
        "en": "the location has an unfinished in-place write (operation {op_id}, {op_kind}, phase "
              "{phase}) - the file is isolated; first recovery: “Restore the header from before "
              "the write” (`recover_torn({op_id})`)"},
    "objchg.item.isolated_finish": {
        "pl": "lokacja ma nieukończony zapis w miejscu (operacja {op_id}, {op_kind}, faza "
              "{phase}) - plik jest izolowany; najpierw dokończenie: „Dokończ zapis” "
              "(`finish_inplace({op_id})`), a gdy kontrola danych nie przechodzi - powrót: "
              "„Przywróć nagłówek sprzed zapisu” (`recover_torn({op_id})`)",
        "en": "the location has an unfinished in-place write (operation {op_id}, {op_kind}, phase "
              "{phase}) - the file is isolated; first finish: “Finish the write” "
              "(`finish_inplace({op_id})`), and if the data check fails - way back: “Restore the "
              "header from before the write” (`recover_torn({op_id})`)"},
    "objchg.item.inplace_after_gate": {
        "pl": "lokacja dostała zapis w miejscu (operacja {op_id}, {op_kind}, faza {phase}) po "
              "bramce renamu - nagłówek, z którego pochodzi nowa nazwa, mógł się zmienić; renamu "
              "nie było, plik nietknięty - odśwież podgląd nazw",
        "en": "the location got an in-place write (operation {op_id}, {op_kind}, phase {phase}) "
              "after the move gate - the header the new name comes from may have changed; no move "
              "happened, the file is untouched - refresh the names preview"},
    "objchg.item.src_missing": {"pl": "źródło nie istnieje na dysku",
                                "en": "the source does not exist on disk"},
    "objchg.item.dst_exists": {"pl": "cel już istnieje na dysku (anty-clobber)",
                               "en": "the target already exists on disk (anti-clobber)"},
    "objchg.item.busy": {
        "pl": "plik zajęty przez inny program (WinError {winerror}, prób: {tries}) - spróbuj "
              "ponownie za chwilę",
        "en": "the file is in use by another program (WinError {winerror}, attempts: {tries}) - "
              "try again in a moment"},
    "objchg.item.torn_other": {
        "pl": "plik PRZENIESIONY na {dst}, baza NIE przepięta ({detail}), a zamiar tej próby "
              "rozstrzygnął inny proces (baza: {db_path}, zamiar: {in_flight}) - kompensacji nie "
              "ma; sprawdź, gdzie stoi plik",
        "en": "file MOVED to {dst}, database NOT updated ({detail}), and another process settled "
              "this attempt's intent (database: {db_path}, intent: {in_flight}) - no "
              "compensation; check where the file is"},
    "objchg.item.returned_intent_left": {
        "pl": "baza nie przyjęła przepięcia ({detail}) - plik wrócił pod nazwę {src}, ale zamiar "
              "renamu nie zgaszony ({intent_detail}) - rekoncyliacja go zamknie",
        "en": "the database did not accept the move ({detail}) - the file returned to {src}, but "
              "the move intent is not cleared ({intent_detail}) - reconciliation will close it"},
    "objchg.item.torn_db_not": {
        "pl": "plik PRZENIESIONY na {dst}, ale baza NIE przepięta ({detail}) - zamiar renamu "
              "zapisany: ponowienie albo cofnięcie przebiegu dokończy przepięcie",
        "en": "file MOVED to {dst}, but database NOT updated ({detail}) - the move intent is "
              "saved: retrying or undoing the run will finish the update"},
    "objchg.item.returned": {
        "pl": "baza nie przyjęła przepięcia ({detail}) - plik wrócił pod nazwę {src}; renamu nie "
              "ma, można ponowić",
        "en": "the database did not accept the move ({detail}) - the file returned to {src}; no "
              "move happened, you can retry"},
    "objchg.item.intent_not_saved": {
        "pl": "zamiar renamu nie zapisany ({detail}) - renamu nie było, plik nietknięty",
        "en": "the move intent was not saved ({detail}) - no move happened, the file is "
              "untouched"},
    "objchg.item.torn_unknown": {
        "pl": "stan pliku nieznany po błędzie renamu ({inner}) - zamiar renamu zostaje: ponowienie "
              "albo cofnięcie przebiegu rozstrzygnie, gdzie plik stoi",
        "en": "file state unknown after a move error ({inner}) - the move intent stays: retrying "
              "or undoing the run will decide where the file is"},
    "objchg.item.intent_dropped": {
        "pl": "zamiar renamu {rename_id} zgaszony przez inny proces - renamu nie było, plik "
              "nietknięty; odśwież przebieg",
        "en": "move intent {rename_id} was cleared by another process - no move happened, the "
              "file is untouched; refresh the run"},
    "objchg.item.target_taken_db": {
        "pl": "cel zajęty w bazie: location:{location} ma już (volume={volume}, {path})",
        "en": "the target is taken in the database: location:{location} already has "
              "(volume={volume}, {path})"},
    "objchg.item.not_on_run_path": {"pl": "plik nie stoi na ścieżce z przebiegu",
                                    "en": "the file is not at the path from the run"},
    "objchg.item.alias_conflict": {
        "pl": "alias '{alias}' wskazuje już object:{object_id} - konflikt, zero zapisu",
        "en": "alias '{alias}' already points to object:{object_id} - conflict, nothing written"},
    "objchg.item.retired_via_xref": {
        "pl": "obiekt '{canon}' to nagrobek, a jego kanon prowadzi dziś przez parę katalogową do "
              "'{target}' - nagrobka nie wskrzeszam, celem jest '{target}'",
        "en": "object '{canon}' is retired, and its canon now leads through a catalog pair to "
              "'{target}' - the retired object is not revived, the target is '{target}'"},
    "objchg.item.hand_newer_kept": {
        "pl": "baza: klatka niesie już nowszą decyzję niż gest - zostaje",
        "en": "database: the frame already carries a newer decision than the gesture - it stays"},
    "objchg.item.undo_hand_newer": {
        "pl": "baza: klatka niesie nowszą decyzję niż gest - obiekt zostaje",
        "en": "database: the frame carries a newer decision than the gesture - the object stays"},
    "objchg.item.testimony_withheld": {
        "pl": "plik ZAPISANY (backup do cofnięcia w commicie {commit_id}), ale zeznanie klatki NIE "
              "przyjęło zapisu - klatka ma {copies}, a głosem klatki mówi {lead}; zapis dokończy "
              "się samo po wskazaniu tej kopii („Ta kopia prowadzi” w Zbiorach) albo gdy zostanie "
              "jedyną obecną kopią klatki, inaczej „Cofnij”",
        "en": "file WRITTEN (backup for undo in commit {commit_id}), but the frame testimony did "
              "NOT accept the write - the frame has {copies}, and {lead} speaks for the frame; the "
              "write finishes by itself once you point at this copy (“This copy leads” in "
              "Collections) or once it is the frame's only present copy, otherwise “Undo”"},
    "objchg.item.testimony_withheld_undo": {
        "pl": "nagłówek PRZYWRÓCONY (commit {commit_id}), ale zeznanie klatki NIE wróciło - klatka "
              "ma {copies}, a głosem klatki mówi {lead}; dokończy się samo po wskazaniu tej kopii "
              "(„Ta kopia prowadzi” w Zbiorach) albo gdy zostanie jedyną obecną kopią klatki",
        "en": "header RESTORED (commit {commit_id}), but the frame testimony did NOT come back - "
              "the frame has {copies}, and {lead} speaks for the frame; it finishes by itself once "
              "you point at this copy (“This copy leads” in Collections) or once it is the "
              "frame's only present copy"},
    "objchg.item.copies": {
        "pl": {"one": "{n} obecną kopię", "few": "{n} obecne kopie", "many": "{n} obecnych kopii"},
        "en": {"one": "{n} present copy", "other": "{n} present copies"}},
    "objchg.item.lead_copy": {"pl": "kopia {path}", "en": "the copy {path}"},
    "objchg.item.lead_none": {"pl": "żadna kopia jednoznacznie", "en": "no single copy"},
    "objchg.item.withheld_completed": {
        "pl": "dokończone: zeznanie klatki przyjęło zapisany nagłówek",
        "en": "finished: the frame testimony accepted the written header"},
    "objchg.item.withheld_superseded": {
        "pl": "karta zapisana, potem zastąpiona nowszym stanem pliku - zeznanie z niej nie przeszło",
        "en": "card written, then superseded by a newer state of the file - the testimony did not "
              "take it"},
    "objchg.item.hand_newer": {"pl": "nowsza decyzja ręki o obiekcie klatki zostaje",
                               "en": "a newer manual decision about the frame's object stays"},
    # Koperta prozy bez kodu (tekst systemu, pisarz karty), za którą stoi nota z kodem - proza znak
    # w znak, nota w języku UI.
    "objchg.item.prose": {"pl": "{text}", "en": "{text}"},
    "objchg.item.hand_unknown": {
        "pl": "wersja decyzji ręki sprzed aktualizacji nieznana - nagrobek zostaje do oka",
        "en": "the version of the manual decision from before the update is unknown - the "
              "exclusion stays for review"},
    # Reguła formy folderu obiektu (`resolve.catalog.FOLDER_RULE_CODES`, AR-141) - szczegół
    # pominięcia `bad_target` w języku UI.
    "objchg.folder.empty": {"pl": "kanon pusty albo nie jest tekstem",
                            "en": "the canon is empty or not text"},
    "objchg.folder.edge_space": {"pl": "kanon zaczyna się albo kończy białym znakiem",
                                 "en": "the canon starts or ends with whitespace"},
    "objchg.folder.slash_outside_comet": {"pl": "„/” poza oznaczeniem komety",
                                          "en": "“/” outside a comet designation"},
    "objchg.folder.reserved_dot": {"pl": "nazwa „.” albo „..” jest zarezerwowana",
                                   "en": "the name “.” or “..” is reserved"},
    "objchg.folder.forbidden_char": {"pl": "znak zakazany w nazwie katalogu: {char}",
                                     "en": "a character not allowed in a folder name: {char}"},
    "objchg.folder.device_name": {"pl": "nazwa urządzenia Windows ({name})",
                                  "en": "a Windows device name ({name})"},
    "objchg.folder.trailing_dot_space": {
        "pl": "kropka albo spacja na końcu nazwy (Windows ją zdejmuje)",
        "en": "a dot or space at the end of the name (Windows strips it)"},
    "objchg.folder.too_long": {"pl": "nazwa ma {n} znaków, a Windows przyjmuje najwyżej {limit}",
                               "en": "the name has {n} characters, Windows accepts at most {limit}"},
    # Pominięcia planera po KODZIE (`object_change.SKIP_CODES`, `ObjectChangeSkip.params`) - zdanie
    # w języku UI; kod bez wpisu tutaj zostaje przy zdaniu rdzenia (`tekst_pominiecia`). Komplet
    # pinuje test parytetu (klucze składane w locie: `objchg.skip.<kod>`).
    "objchg.skip.kind_not_light": {
        "pl": "rodzaj „{kind}” nie ma obiektu z definicji - gest dotyczy lightów i stosów",
        "en": "kind “{kind}” has no object by definition - the gesture is for lights and stacks"},
    "objchg.skip.retired": {"pl": "klatka wycofana z archiwum",
                            "en": "frame retired from the archive"},
    "objchg.skip.superseded": {"pl": "klatka zastąpiona inną (podmiana pliku)",
                               "en": "frame superseded by another (file replaced)"},
    "objchg.skip.no_present_copy": {"pl": "brak obecnej kopii", "en": "no present copy"},
    "objchg.skip.many_copies": {
        "pl": "wiele obecnych kopii ({n}) - jedna klatka, jeden folder obiektu",
        "en": "several present copies ({n}) - one frame, one object folder"},
    "objchg.skip.isolated": {
        "pl": "kopia izolowana przerwanym albo niedokończonym zapisem w miejscu - najpierw odzysk "
              "albo dokończenie w Porządkach",
        "en": "copy isolated by an interrupted or unfinished in-place write - recover or finish it "
              "in Housekeeping first"},
    "objchg.skip.no_mtime": {"pl": "kopia bez mtime - brak kotwicy przeniesienia",
                             "en": "copy without mtime - no anchor for the move"},
    "objchg.skip.no_object": {"pl": "klatka bez obiektu - nie ma czego uzgadniać",
                              "en": "frame without an object - nothing to align"},
    "objchg.skip.bad_target": {
        "pl": "folder obiektu „{canon}” nie powstanie - system plików nie przyjmie tej nazwy "
              "({detail})",
        "en": "the object folder “{canon}” cannot be created - the file system will not accept "
              "this name ({detail})"},
    "objchg.skip.off_position": {
        "pl": "plik nie stoi na pozycji obiektu w drzewie archiwum - nie ma folderu obiektu, do "
              "którego mógłby trafić",
        "en": "the file is not at the object position in the archive tree - there is no object "
              "folder it could go to"},
    "objchg.skip.folder_twins": {
        "pl": "folder obiektu „{canon}” ma tę samą nazwę co folder innego obiektu ({twins}) - pliki "
              "dwóch obiektów trafiłyby do jednego folderu",
        "en": "the object folder “{canon}” has the same name as another object's folder ({twins}) "
              "- files of two objects would land in one folder"},
    "objchg.skip.card_skip": {
        "pl": "karta OBJECT nie do zapisania ({detail}) - plik zostaje, bo karta i folder idą razem",
        "en": "the OBJECT card cannot be written ({detail}) - the file stays, because the card and "
              "the folder go together"},
    # Powód bramki karty `OBJECT` (`queries.object_card_gate`, kod `ZdanieRdzenia`) - szczegół
    # zdania `objchg.skip.card_skip` w języku UI (AR-138); PL = zdanie bramki znak w znak.
    "objchg.gate.no_present_copy": {"pl": "brak obecnej kopii", "en": "no present copy"},
    "objchg.gate.many_copies": {"pl": "wiele obecnych kopii ({n})",
                                "en": "several present copies ({n})"},
    "objchg.gate.compressed": {"pl": "skompresowany master", "en": "compressed master"},
    "objchg.gate.degenerate": {
        "pl": "tożsamość nieobliczalna (degenerat) - zapis rozdwoiłby klatkę",
        "en": "identity cannot be computed (degenerate) - a write would split the frame"},
    "objchg.gate.no_header_hash": {"pl": "brak header_hash - brak kontroli zapisu",
                                   "en": "no header_hash - no write check"},
    "objchg.gate.unreadable": {"pl": "kopia oznaczona jako nieczytelna",
                               "en": "copy marked as unreadable"},
    "objchg.gate.many_cards": {"pl": "wiele kart OBJECT ({n})", "en": "several OBJECT cards ({n})"},
    "objchg.gate.copy_without_facts": {
        "pl": "kopia bez zebranych faktów przy klatce z nieobecną kopią - zbierze je „Przyjmij "
              "nowe”, gdy plik jest na dysku i nie czeka na dokończenie przerwanego zapisu",
        "en": "a copy without collected facts in a frame with an absent copy - Receive new "
              "collects them when the file is on disk and not waiting for an interrupted write "
              "to finish"},
    "objchg.gate.copy_other_card": {
        "pl": "kopia zeznaje inną kartę OBJECT niż klatka",
        "en": "the copy testifies a different OBJECT card than the frame"},
    "objchg.gate.form_not_canon": {
        "pl": "forma karty nie wraca do kanonu (kanon znany tylko z aliasu)",
        "en": "the card form does not lead back to the canon (canon known only from an alias)"},
    "objchg.gate.joined_names": {
        "pl": "sklejka oznaczeń - nie każdy człon wskazuje ten obiekt",
        "en": "joined designations - not every part points to this object"},
    "objchg.gate.card_not_text": {"pl": "karta OBJECT nietekstowa ({vtype})",
                                  "en": "non-text OBJECT card ({vtype})"},
    "objchg.gate.fits_checksum": {"pl": "FITS z sumą kontrolną (CHECKSUM/DATASUM)",
                                  "en": "FITS with a checksum (CHECKSUM/DATASUM)"},
    "objchg.skip.card_rule": {"pl": "karta OBJECT: {detail}", "en": "OBJECT card: {detail}"},
    # Szczegóły odmowy karty i katalogu jako fakty rdzenia (AR-138): reguła karty FITS 4.0, długości
    # komentarza przed i po układzie karty, rodzaj błędu systemu.
    "objchg.skip.card_too_long": {
        "pl": "karta OBJECT „{value}” za długa - znaków: {length}, rekord FITS mieści: {limit}",
        "en": "the OBJECT card “{value}” is too long - {length} characters, a FITS record holds "
              "{limit}"},
    "objchg.skip.card_chars": {
        "pl": "karta OBJECT „{value}” ma znaki spoza drukowalnego ASCII - nagłówek FITS ich nie "
              "przyjmie",
        "en": "the OBJECT card “{value}” has characters outside printable ASCII - a FITS header "
              "will not take them"},
    "objchg.skip.card_comment": {
        "pl": "karta OBJECT: nowa wartość ucięłaby zastany komentarz karty z {before} do {after} "
              "znaków (karta FITS po zmianie ma pole wartości stałego formatu) - plik zostaje, bo "
              "karta i folder idą razem",
        "en": "OBJECT card: the new value would cut the existing card comment from {before} to "
              "{after} characters (a changed FITS card gets a fixed-format value field) - the file "
              "stays, because the card and the folder go together"},
    "objchg.skip.dir_unreadable": {"pl": "katalog celu nieczytelny ({dir}): {detail}",
                                   "en": "target folder unreadable ({dir}): {detail}"},
    "objchg.skip.dir_denied": {"pl": "katalog celu nieczytelny - brak dostępu: {dir}",
                               "en": "target folder unreadable - access denied: {dir}"},
    "objchg.skip.dir_missing": {"pl": "katalog celu nie istnieje na dysku: {dir}",
                                "en": "the target folder does not exist on disk: {dir}"},
    "objchg.skip.file_in_dir_place": {"pl": "w miejscu katalogu celu stoi plik: {path}",
                                      "en": "a file stands where the target folder should be: "
                                            "{path}"},
    "objchg.skip.variant_dir": {
        "pl": "wersja stosu leży w innym katalogu niż oryginał - para jedzie razem",
        "en": "the stack version lies in a different folder than the original - the pair moves "
              "together"},
    "objchg.skip.variant_name": {
        "pl": "nazwa wersji stosu nie wynika z nazwy oryginału ({name}) - para jedzie razem",
        "en": "the stack version name does not follow from the original's name ({name}) - the "
              "pair moves together"},
    "objchg.skip.unchanged": {
        "pl": "bez zmian - plik w folderze obiektu, nazwa i karta zgodne",
        "en": "unchanged - the file is in the object folder, name and card agree"},
    "objchg.skip.target_on_disk": {"pl": "na dysku stoi już plik pod ścieżką celu: {path}",
                                   "en": "a file already exists on disk at the target path: {path}"},
    "objchg.skip.batch_collision": {"pl": "kolizja we wsadzie - dwa pliki w jeden cel: {path}",
                                    "en": "collision in the batch - two files to one target: {path}"},
    "objchg.skip.target_in_db": {"pl": "w bazie jest inna kopia pod ścieżką celu: {path}",
                                 "en": "the database has another copy at the target path: {path}"},
    "objchg.skip.pair": {"pl": "para stosu jedzie razem - druga połowa pominięta: {inner}",
                         "en": "the stack pair moves together - the other half is skipped: "
                               "{inner}"},
    # Ostrzeżenia po KODZIE (AR-138): planera (`object_change.WARNING_CODES`) i sterownika zapisu
    # (`object_change.ZdanieRdzenia`) - zdanie w języku UI (`tekst_ostrzezenia`); wpis mnogi
    # odmienia się przez parametr `n`. Ostrzeżenie bez kodu zostaje przy zdaniu rdzenia.
    "objchg.warn.stack_split": {
        "pl": {"one": "stos {stack}: gest przeniesie {moved} z {inputs} jego wejść - wejścia "
                      "rozejdą się na {n} folder, a żniwa ustalają siedzibę stosu z jednego "
                      "folderu lightów",
               "few": "stos {stack}: gest przeniesie {moved} z {inputs} jego wejść - wejścia "
                      "rozejdą się na {n} foldery, a żniwa ustalają siedzibę stosu z jednego "
                      "folderu lightów",
               "many": "stos {stack}: gest przeniesie {moved} z {inputs} jego wejść - wejścia "
                       "rozejdą się na {n} folderów, a żniwa ustalają siedzibę stosu z jednego "
                       "folderu lightów"},
        "en": {"one": "stack {stack}: the gesture moves {moved} of its {inputs} inputs - the "
                      "inputs will split across {n} folder, and the harvest takes the stack's "
                      "home from one lights folder",
               "other": "stack {stack}: the gesture moves {moved} of its {inputs} inputs - the "
                        "inputs will split across {n} folders, and the harvest takes the stack's "
                        "home from one lights folder"}},
    "objchg.warn.dir_not_removed": {"pl": "katalog {dir} nie usunięty ({detail})",
                                    "en": "folder {dir} not removed ({detail})"},
    "objchg.warn.dir_uncertain": {
        "pl": "katalog {dir}: zamiar założenia bez potwierdzenia, a katalog istnieje - własność "
              "niepewna, zostaje do oka",
        "en": "folder {dir}: intent to create it without confirmation, and the folder exists - "
              "ownership uncertain, left for review"},
    "objchg.warn.dir_not_empty": {
        "pl": "katalog {dir}: założony przez gest, ale nie jest pusty - zostaje",
        "en": "folder {dir}: created by the gesture, but it is not empty - it stays"},
    "objchg.replan_btn": {"pl": "Policz plan ponownie", "en": "Compute the plan again"},
    "objchg.skipped_head_done": {
        "pl": {"one": "Pominięto {n} klatkę - powód i plik:",
               "few": "Pominięto {n} klatki - powody i pliki:",
               "many": "Pominięto {n} klatek - powody i pliki:"},
        "en": {"one": "Skipped {n} frame - reason and file:",
               "other": "Skipped {n} frames - reasons and files:"}},
    "objchg.card_rewrite": {"pl": " · cały plik przepisany (FITS: dopisanie karty)",
                            "en": " · whole file rewritten (FITS: card added)"},
    "objchg.err.stage": {"pl": "Zapis planu do bazy odmówiony: {msg}",
                         "en": "Saving the plan to the database was refused: {msg}"},
    "objchg.res.notes": {"pl": " · z uwagą: {n} - {note}", "en": " · with a note: {n} - {note}"},
    "objchg.res.rescan": {
        "pl": {"one": " · {n} plik zmienił się od ostatniego skanu - najpierw przebieg Dostawy "
                      "(skan), potem gest ponownie",
               "few": " · {n} pliki zmieniły się od ostatniego skanu - najpierw przebieg Dostawy "
                      "(skan), potem gest ponownie",
               "many": " · {n} plików zmieniło się od ostatniego skanu - najpierw przebieg Dostawy "
                       "(skan), potem gest ponownie"},
        "en": {"one": " · {n} file changed since the last scan - run Intake (scan) first, then "
                      "the gesture again",
               "other": " · {n} files changed since the last scan - run Intake (scan) first, then "
                        "the gesture again"}},
    "objchg.res.run": {"pl": " · przebieg {run_id}", "en": " · run {run_id}"},
    "objchg.card_kept": {"pl": "{value} (bez zmiany)", "en": "{value} (unchanged)"},
    "objchg.card_none": {"pl": "- (bez karty)", "en": "- (no card)"},
    "objchg.card_absent": {"pl": "(brak)", "en": "(none)"},
    "objchg.card_change": {"pl": "{old} → {new}", "en": "{old} → {new}"},
    "objchg.finish_btn": {"pl": "Dokończ ({n})", "en": "Finish ({n})"},
    "objchg.action_change": {"pl": "Zmień obiekt ({n})", "en": "Change object ({n})"},
    "objchg.action_change_bare": {"pl": "Zmień obiekt", "en": "Change object"},
    "objchg.action_align": {"pl": "Uzgodnij ({n})", "en": "Align ({n})"},
    "objchg.action_align_bare": {"pl": "Uzgodnij", "en": "Align"},
    "objchg.nothing_tip": {
        "pl": "Plan nie ma nic do zrobienia - pliki stoją już w folderze obiektu z właściwą kartą "
              "albo są pominięte z powodem.",
        "en": "The plan has nothing to do - the files already sit in the object folder with the "
              "right card, or they are skipped with a reason."},
    # Liczba w formie „etykieta: N” - bez odmiany, bo wspólna gramatyka zdania wyniku
    # (`wb_worker.zdanie_wyniku_zapisu`) składa ten człon przez `t`, nie `t_plural`.
    "objchg.res.applied": {"pl": "zmienione pozycje: {n}", "en": "items changed: {n}"},
    "objchg.res.undone": {"pl": "cofnięte pozycje: {n}", "en": "items undone: {n}"},
    "objchg.res.dirs": {"pl": " · katalogi założone: {created}, usunięte: {removed}",
                        "en": " · folders created: {created}, removed: {removed}"},
    "objchg.res.dirs_uncertain": {
        "pl": {"one": " · {n} katalog o niepewnej własności zostaje do oka (nie usuwam)",
               "few": " · {n} katalogi o niepewnej własności zostają do oka (nie usuwam)",
               "many": " · {n} katalogów o niepewnej własności zostaje do oka (nie usuwam)"},
        "en": {"one": " · {n} folder of uncertain ownership is left for review (not removed)",
               "other": " · {n} folders of uncertain ownership are left for review (not removed)"}},
    # Wejścia gestu w Zbiorach: pozycja menu „Obiekt", wybór celu, „Uzgodnij pliki…" perspektywy.
    "grid.sel.object_change": {"pl": "Zmień obiekt…", "en": "Change object…"},
    "grid.sel.object_change_tip": {"pl": " · „Zmień obiekt…” - do sprawdzenia w podglądzie: {n}",
                                   "en": " · “Change object…” - to check in the preview: {n}"},
    "grid.sel.object_change_tip_only": {
        "pl": {"one": "„Zmień obiekt…” - do sprawdzenia w podglądzie: {n} klatka (plik, karta "
                      "i baza razem).",
               "few": "„Zmień obiekt…” - do sprawdzenia w podglądzie: {n} klatki (plik, karta "
                      "i baza razem).",
               "many": "„Zmień obiekt…” - do sprawdzenia w podglądzie: {n} klatek (plik, karta "
                       "i baza razem)."},
        "en": {"one": "“Change object…” - to check in the preview: {n} frame (file, card and "
                      "database together).",
               "other": "“Change object…” - to check in the preview: {n} frames (file, card and "
                        "database together)."}},
    "grid.sel.object_change_align": {"pl": "Uzgodnij pliki…", "en": "Align files…"},
    "grid.sel.object_change_align_tip": {
        "pl": {"one": "Plik {n} zaznaczonej klatki pojedzie do folderu jej obiektu - podgląd "
                      "przed zapisem.",
               "few": "Pliki {n} zaznaczonych klatek pojadą do folderu ich obiektu - podgląd "
                      "przed zapisem.",
               "many": "Pliki {n} zaznaczonych klatek pojadą do folderu ich obiektu - podgląd "
                       "przed zapisem."},
        "en": {"one": "The file of {n} selected frame moves into its object folder - preview "
                      "before writing.",
               "other": "The files of {n} selected frames move into their object folder - "
                        "preview before writing."}},
    "grid.sel.object_change_recipe": {"pl": "zaznacz klatki, prawy klik → „{align}”",
                                      "en": "select the frames, right-click → “{align}”"},
    "grid.sel.object_change_pick_title": {"pl": "Zmień obiekt - wybierz cel",
                                          "en": "Change object - pick the target"},
    "grid.sel.object_change_pick_head": {
        "pl": {"one": "Nowy obiekt dla {n} zaznaczonej klatki. Wybór niczego nie zapisuje - plan "
                      "z plikami pokaże następne okno.",
               "few": "Nowy obiekt dla {n} zaznaczonych klatek. Wybór niczego nie zapisuje - plan "
                      "z plikami pokaże następne okno.",
               "many": "Nowy obiekt dla {n} zaznaczonych klatek. Wybór niczego nie zapisuje - "
                       "plan z plikami pokaże następne okno."},
        "en": {"one": "New object for {n} selected frame. Picking writes nothing - the next "
                      "window shows the plan with the files.",
               "other": "New object for {n} selected frames. Picking writes nothing - the next "
                        "window shows the plan with the files."}},
    "grid.sel.object_change_pick_ok": {"pl": "Dalej - podgląd…", "en": "Next - preview…"},
    "grid.sel.object_change_unknown": {
        "pl": "Drabina nazw nie rozpoznaje „{canon}” - gest nie ruszy.",
        "en": "The name ladder does not recognise “{canon}” - the gesture will not start."},
    "grid.sel.object_change_no_card": {
        "pl": "Obiekt {canon} nie ma formy karty OBJECT, która wróciłaby do niego przy odczycie "
              "(kanon znany tylko z aliasu). Gest obiecuje kartę i folder razem, więc odmawia - "
              "obiekt w samej bazie nada „Przypisz obiekt…”.",
        "en": "Object {canon} has no OBJECT card form that would resolve back to it on reading "
              "(canon known only from an alias). The gesture promises the card and the folder "
              "together, so it refuses - “Assign object…” sets the object in the database only."},
    # Wiersz Porządków i jego perspektywa (nazwy rodziny presetów: `perspective.*`,
    # `grid.criteria.only_*` - konwencja bramki `test_KAZDY_preset_ma_etykiete_i_zuzyta_flage`).
    "tasks.file_object_mismatch_frames": {"pl": "Plik nie zgadza się z obiektem",
                                          "en": "File disagrees with its object"},
    "tasks.file_object_mismatch_tip": {
        "pl": "Gest: zaznacz klatki w perspektywie, prawy klik → „{align}”. Plik pojedzie do "
              "folderu obiektu, karta OBJECT dostanie jego formę - podgląd przed zapisem.",
        "en": "Gesture: select the frames in the view, right-click → “{align}”. The file moves "
              "into the object folder and the OBJECT card gets its form - preview before writing."},
    # Wiersz przerwanych przebiegów gestu zmiany obiektu (AR-121) - otwiera okno na przebiegu.
    "tasks.object_change_interrupted": {"pl": "Przerwane zmiany obiektu",
                                        "en": "Interrupted object changes"},
    "tasks.object_change_interrupted_tip": {
        "pl": "„Zmień obiekt…” albo „Uzgodnij pliki…” nie doszło do końca (przerwanie, awaria "
              "albo błąd pozycji). Klik otwiera najstarszy przebieg: „Dokończ” zapisze pozycje, "
              "które czekają, „Cofnij” wróci do stanu sprzed gestu.",
        "en": "“Change object…” or “Align files…” did not finish (interrupted, crashed or an item "
              "failed). A click opens the oldest run: “Finish” writes the items that are waiting, "
              "“Undo” returns to the state before the gesture."},
    "perspective.file_object_mismatch": {"pl": "Plik nie zgadza się z obiektem",
                                         "en": "File disagrees with its object"},
    "grid.criteria.only_file_object_mismatch": {
        "pl": "tylko plik niezgodny z obiektem (folder albo karta)",
        "en": "only files disagreeing with their object (folder or card)"},
    # Wiersz Porządków AR-135 i jego perspektywa: para `catalog_xref` dopisana po fakcie.
    "tasks.xref_reconcile_frames": {"pl": "Nazwa katalogowa wskazuje inny obiekt",
                                    "en": "Catalog name points to another object"},
    "tasks.xref_reconcile_tip": {
        "pl": "Para katalogowa prowadzi nazwę do celu: {pairs}. Zaznacz klatki w perspektywie "
              "i użyj „{change}” - cel stoi po strzałce.",
        "en": "A catalog pair leads the name to its target: {pairs}. Select the frames in the "
              "view and use “{change}” - the target follows the arrow."},
    "perspective.xref_reconcile": {"pl": "Nazwa katalogowa wskazuje inny obiekt",
                                   "en": "Catalog name points to another object"},
    "grid.criteria.only_xref_reconcile": {
        "pl": "tylko klatki obiektu, którego nazwę para katalogowa prowadzi do innego celu",
        "en": "only frames whose object name a catalog pair leads to another target"},
    # Okna kart piszą w miejscu (AR-117) - zdanie mówi o drodze zapisu tylko przy spadku, językiem
    # człowieka (szczegół rdzenia - w podpowiedzi okna, nie w zdaniu).
    "wb.inplace_fallback": {
        "pl": " · cały plik przepisany: {n} (karty nie dało się wpisać w samym nagłówku)",
        "en": " · whole file rewritten: {n} (the card could not be written into the header "
              "alone)"},
    # Dom: gest zmiany obiektu przenosi pliki, a nie przemianowuje (relokacja z powodem gestu).
    "home.gest.object_relocated": {
        "pl": {"one": "przeniesiono {n} plik do folderu obiektu",
               "few": "przeniesiono {n} pliki do folderu obiektu",
               "many": "przeniesiono {n} plików do folderu obiektu"},
        "en": {"one": "{n} file moved to the object folder",
               "other": "{n} files moved to the object folder"}},
    "home.gest.object_relocated_back": {
        "pl": {"one": "cofnięto zmianę obiektu - {n} plik wrócił na dawne miejsce",
               "few": "cofnięto zmianę obiektu - {n} pliki wróciły na dawne miejsce",
               "many": "cofnięto zmianę obiektu - {n} plików wróciło na dawne miejsce"},
        "en": {"one": "object change undone - {n} file returned to its former place",
               "other": "object change undone - {n} files returned to their former place"}},
    # Relokacje gestu bez rozróżnienia katalogu (read-model nie mówi, czy folder się zmienił).
    "home.gest.object_files": {
        "pl": {"one": "zmiana obiektu - {n} plik w nowym miejscu albo pod nową nazwą",
               "few": "zmiana obiektu - {n} pliki w nowym miejscu albo pod nową nazwą",
               "many": "zmiana obiektu - {n} plików w nowym miejscu albo pod nową nazwą"},
        "en": {"one": "object change - {n} file in a new place or under a new name",
               "other": "object change - {n} files in a new place or under a new name"}},
    # ---- optyka teleskopu: ręka, pliki, zestawy, kubełki (AR-128, AR-129, D-1012-2) ----
    "axis.tel.rigs": {"pl": "Zestawy (z planera):", "en": "Setups (from the planner):"},
    "axis.tel.restore_optics": {"pl": "Przywróć z plików", "en": "Restore from files"},
    "axis.tel.restore_optics_tip": {
        "pl": "Zdejmij ogniskowę i f/ wpisane ręką - oś wróci do wartości z plików. "
              "Pliki nie są ruszane.",
        "en": "Remove the focal length and f/ entered by hand - the axis returns to the values "
              "from the files. The files are not touched."},
    "axis.tel.files_focal": {"pl": "pliki: {v} mm ({n} kl.)", "en": "files: {v} mm ({n} fr.)"},
    "axis.tel.files_f_ratio": {"pl": "pliki: f/{v} ({n} kl.)", "en": "files: f/{v} ({n} fr.)"},
    "axis.tel.files_none": {"pl": "pliki: brak zeznania", "en": "files: no value"},
    "axis.tel.optics_hand_tip": {
        "pl": "Wartość wpisana ręką - wygrywa w osi, planerze i Porządkach.\n{files}\n"
              "Dwuklik: zmień; pusty wpis albo „Przywróć z plików”: wróć do plików.",
        "en": "Value entered by hand - it wins on the axis, in the planner and in Housekeeping.\n"
              "{files}\nDouble-click: change; empty entry or “Restore from files”: back to the files."},
    "axis.tel.optics_files_tip": {
        "pl": "Wartość z plików (najczęstsza wśród klatek tego teleskopu).\n{files}\n"
              "Dwuklik: wpisz własną - pliki nie są ruszane.",
        "en": "Value from the files (the most common among this telescope's frames).\n{files}\n"
              "Double-click: enter your own - the files are not touched."},
    "axis.tel.optics_not_number": {"pl": "„{text}” to nie liczba",
                                   "en": "“{text}” is not a number"},
    "axis.tel.optics_saved": {"pl": "Zapisano wartość ręki.", "en": "Hand value saved."},
    "axis.tel.optics_cleared": {"pl": "Ręka zdjęta - oś mówi wartością z plików.",
                                "en": "Hand value removed - the axis uses the files again."},
    "axis.tel.optics_unchanged": {"pl": "Optyka bez zmian.", "en": "Optics unchanged."},
    "axis.tel.optics_rejected": {"pl": "Nie zapisano: {e}", "en": "Not saved: {e}"},
    "axis.tel.aperture": {"pl": "średnica (wyliczona): {d} mm = {focal} / {f}",
                          "en": "aperture (computed): {d} mm = {focal} / {f}"},
    "axis.tel.aperture_unknown": {"pl": "średnica: brak ogniskowej albo f/ - wpisz, żeby policzyć",
                                  "en": "aperture: focal length or f/ missing - enter it to compute"},
    "axis.tel.rig_line": {
        "pl": "{camera} · piksel {px} µm · {s1}″/px (bin 2: {s2}″/px) · kadr {fx}′ × {fy}′",
        "en": "{camera} · pixel {px} µm · {s1}″/px (bin 2: {s2}″/px) · field {fx}′ × {fy}′"},
    "axis.tel.rig_unknown": {"pl": "{camera} · {reason}", "en": "{camera} · {reason}"},
    "axis.tel.rig_reason.no_focal": {"pl": "brak ogniskowej", "en": "no focal length"},
    "axis.tel.rig_reason.no_pixel": {"pl": "brak rozmiaru piksela", "en": "no pixel size"},
    "axis.tel.rig_reason.no_naxis": {"pl": "brak wymiarów klatki", "en": "no frame dimensions"},
    "axis.tel.rig_reason.mixed_optics": {"pl": "klatki różnej optyki - kadr nieznany",
                                         "en": "frames of mixed optics - field unknown"},
    "object.config_focal_line": {"pl": "- ogniskowa niezgodna z teleskopem",
                                 "en": "- focal length disagrees with the telescope"},
    "object.frames_config_focal": {
        "pl": "Klatki z ogniskową niezgodną z teleskopem ({n})",
        "en": "Frames whose focal length disagrees with the telescope ({n})"},
    "object.set_config_tip_focal": {
        "pl": "Ogniskowa w pliku odbiega od teleskopu o ponad 5 %. Wybierz teleskop z listy tych, "
              "które mieszczą się w tej różnicy, albo dopisz nowy. Zapis idzie do BAZY; pliki "
              "zostają bez zmian.",
        "en": "The focal length in the file differs from the telescope by more than 5 %. Pick a "
              "telescope from those within that difference, or add a new one. The write goes to "
              "the DATABASE; the files stay unchanged."},
    "cfg.title_focal": {"pl": "Teleskop dla ogniskowej z plików",
                        "en": "Telescope for the focal length in the files"},
    "cfg.head_focal": {
        "pl": "{folders} · {frames} - ogniskowa w pliku nie zgadza się z teleskopem, do którego "
              "klatki trafiły. Lista pokazuje teleskopy mieszczące się w 5 % od tej ogniskowej; "
              "„Dopisz nowy…” zakłada teleskop razem z przypisaniem. Zapis idzie do BAZY.",
        "en": "{folders} · {frames} - the focal length in the file disagrees with the telescope "
              "these frames went to. The list shows telescopes within 5 % of that focal length; "
              "“Add new…” creates a telescope together with the assignment. The write goes to "
              "the DATABASE."},
    "cfg.focal_item": {"pl": "pliki: {focal} mm · dziś: {telescope} {source_focal} mm ({park})",
                       "en": "files: {focal} mm · now: {telescope} {source_focal} mm ({park})"},
    "cfg.err_group_focal": {
        "pl": "Grupa {folder} ma w plikach {focal} mm - poza 5 % od teleskopu ({telescope} mm). "
              "Odznacz ją albo wybierz inny teleskop.",
        "en": "Group {folder} has {focal} mm in its files - more than 5 % from the telescope "
              "({telescope} mm). Uncheck it or pick another telescope."},
    "cfg.park_yes": {"pl": "w parku", "en": "in park"},
    "cfg.park_no": {"pl": "historyczny", "en": "historical"},
    "cfg.park_unsaid": {"pl": "park nieoznaczony", "en": "park not set"},
    "cfg.add_new": {"pl": "Dopisz nowy…", "en": "Add new…"},
    "cfg.new_name": {"pl": "Nazwa teleskopu:", "en": "Telescope name:"},
    "cfg.new_focal": {"pl": "Ogniskowa [mm]:", "en": "Focal length [mm]:"},
    "cfg.new_f_ratio": {"pl": "f/:", "en": "f/:"},
    "cfg.new_f_ratio_hint": {"pl": "puste = nie wiem", "en": "empty = unknown"},
    "cfg.new_park": {"pl": "W parku:", "en": "In park:"},
    "cfg.new_park_pick": {"pl": "- wybierz -", "en": "- pick -"},
    "cfg.err_new_focal": {"pl": "Podaj ogniskową nowego teleskopu.",
                          "en": "Enter the focal length of the new telescope."},
    "cfg.err_new_park": {"pl": "Zaznaczone grupy pochodzą z teleskopów o różnym parku - wybierz park.",
                         "en": "The checked groups come from telescopes with different park "
                               "settings - pick one."},
    "tasks.focal_mismatch_frames": {"pl": "Ogniskowa niezgodna z teleskopem",
                                    "en": "Focal length disagrees with the telescope"},
    "tasks.focal_mismatch_tip": {
        "pl": "Klatki, których ogniskowa w pliku odbiega od teleskopu o ponad 5 %. Horreum nie "
              "zakłada teleskopu samo - wybierasz z listy pasujących albo dopisujesz nowy.\n"
              "W podstronie: kubełek jest zaznaczony, gest „{assign}”.",
        "en": "Frames whose focal length in the file differs from the telescope by more than 5 %. "
              "Horreum does not create telescopes on its own - you pick a matching one or add a "
              "new one.\nOn the subpage: the bucket is selected, gesture “{assign}”."},
    "tasks.f_ratio_mismatch_frames": {"pl": "f/ niezgodna z teleskopem",
                                      "en": "f/ disagrees with the telescope"},
    "tasks.f_ratio_mismatch_tip": {
        "pl": "Klatki, których f/ w pliku odbiega od teleskopu o ponad 5 % (np. f/200 zamiast "
              "f/8). Brak f/ w pliku tu nie trafia.\nW Zbiorach: zaznacz klatki, prawy klik → "
              "„{fix}” - zapis do plików dopiero po „Zapisz” w szufladzie, z cofnięciem.",
        "en": "Frames whose f/ in the file differs from the telescope by more than 5 % (e.g. f/200 "
              "instead of f/8). A missing f/ does not land here.\nIn Collections: select frames, "
              "right-click → “{fix}” - files are written only after “Save” in the drawer, with undo."},
    "perspective.f_ratio_mismatch": {"pl": "f/ niezgodna z teleskopem",
                                     "en": "f/ disagrees with the telescope"},
    "grid.criteria.only_f_ratio_mismatch": {
        "pl": "tylko f/ w pliku niezgodna z teleskopem",
        "en": "only f/ in the file disagreeing with the telescope"},
    "grid.optics.fix_action": {"pl": "Popraw f/ w plikach (zgodnie z teleskopem)…",
                               "en": "Fix f/ in the files (to match the telescope)…"},
    "grid.optics.fix_tip": {
        "pl": "Wpisy FOCRATIO = f/ teleskopu trafią do szuflady zapisu; pliki zmienią się dopiero "
              "po „Zapisz”, z cofnięciem.",
        "en": "FOCRATIO = telescope f/ entries go to the write drawer; files change only after "
              "“Save”, with undo."},
    "grid.optics.staged": {
        "pl": {"one": "W szufladzie: {n} wpis f/.", "few": "W szufladzie: {n} wpisy f/.",
               "many": "W szufladzie: {n} wpisów f/."},
        "en": {"one": "In the drawer: {n} f/ entry.", "other": "In the drawer: {n} f/ entries."}},
    "grid.optics.skipped": {"pl": " Pominięte: {reasons}.", "en": " Skipped: {reasons}."},
    "grid.optics.refused.no_target": {
        "pl": "{telescope} nie ma f/ - wpisz ją na Osi teleskopu",
        "en": "{telescope} has no f/ - enter it on the Telescope axis"},
    "grid.optics.refused.no_files": {
        "pl": "pliki {telescope} nie zeznają f/ - nie ma większości do porównania",
        "en": "the files of {telescope} carry no f/ - no majority to compare with"},
    "grid.optics.refused.majority": {
        "pl": "f/ teleskopu {telescope} nie zgadza się z większością jego plików - sprawdź Oś "
              "teleskopu albo uruchom Dostawę; gest poprawia mniejszość, nie większość",
        "en": "the f/ of {telescope} disagrees with most of its files - check the Telescope axis "
              "or run Intake; the gesture fixes the minority, never the majority"},
    "grid.optics.recipe": {
        "pl": "f/ w pliku → f/ teleskopu: {lines}. Zaznacz klatki, prawy klik → „{fix}”.",
        "en": "f/ in the file → telescope f/: {lines}. Select frames, right-click → “{fix}”."},
    "grid.optics.recipe_line": {"pl": "{telescope} {file} → {target} ({n} kl.)",
                                "en": "{telescope} {file} → {target} ({n} fr.)"},
    "axis.tel.optics_header": {"pl": "Optyka:", "en": "Optics:"},
    "axis.tel.optics_busy": {"pl": "Trwa etap Dostawy - optyka teleskopu poczeka na jego koniec.",
                             "en": "An Intake stage is running - telescope optics wait for it to end."},
    "axis.tel.optics_earlier_tip": {
        "pl": "Pliki nie zeznają tej wartości - zapisano ją wcześniej (np. przy powołaniu "
              "teleskopu).\n{files}\nDwuklik: potwierdź albo wpisz własną.",
        "en": "The files carry no such value - it was stored earlier (e.g. when the telescope was "
              "created).\n{files}\nDouble-click: confirm it or enter your own."},
    "axis.tel.optics_stale_tip": {
        "pl": "Nieaktualne - Dostawa przeliczy (pliki mówią dziś inaczej).\n{files}\n"
              "Dwuklik: wpisz własną wartość.",
        "en": "Out of date - Intake will recompute it (the files say otherwise today).\n{files}\n"
              "Double-click: enter your own value."},
    "axis.tel.restore_focal_files": {"pl": "Ogniskowa wróci do plików: {v} mm.",
                                     "en": "Focal length returns to the files: {v} mm."},
    "axis.tel.restore_focal_earlier": {
        "pl": "Pliki nie zeznają ogniskowej - zostanie {v} mm zapisane wcześniej.",
        "en": "The files carry no focal length - {v} mm stored earlier will remain."},
    "axis.tel.restore_focal_none": {"pl": "Pliki nie zeznają ogniskowej - pole zostanie puste.",
                                    "en": "The files carry no focal length - the field stays empty."},
    "axis.tel.restore_f_ratio_files": {"pl": "f/ wróci do plików: f/{v}.",
                                       "en": "f/ returns to the files: f/{v}."},
    "axis.tel.restore_f_ratio_earlier": {
        "pl": "Pliki nie zeznają f/ - zostanie f/{v} zapisane wcześniej.",
        "en": "The files carry no f/ - f/{v} stored earlier will remain."},
    "axis.tel.restore_f_ratio_none": {"pl": "Pliki nie zeznają f/ - pole zostanie puste.",
                                      "en": "The files carry no f/ - the field stays empty."},
    "object.config_focal_info_empty": {
        "pl": "Ogniskowe w plikach zgadzają się z teleskopami - nic do wyboru.",
        "en": "Focal lengths in the files agree with the telescopes - nothing to pick."},
    # „COFNIJ DOPISANIE” (AR-133, `Q8`): recepta paska po „Dopisz nowy…” i zdanie wyniku
    # (`repo.undo_new_telescope` → `NewTelescopeUndo`). Powód odmowy to token klingi
    # (`repo.RETIRE_REFUSALS`) - zdanie per token, parytet pinuje test toru.
    "object.config_undo_add": {
        "pl": "Cofnij dopisanie „{telescope}”",
        "en": "Undo adding “{telescope}”"},
    "object.config_undo_add.done": {
        "pl": {"one": "Cofnięto dopisanie „{telescope}”: {n} klatka wróciła do zestawu sprzed gestu",
               "few": "Cofnięto dopisanie „{telescope}”: {n} klatki wróciły do zestawu sprzed gestu",
               "many": "Cofnięto dopisanie „{telescope}”: {n} klatek wróciło do zestawu sprzed "
                       "gestu"},
        "en": {"one": "Undid adding “{telescope}”: {n} frame is back on its setup from before",
               "other": "Undid adding “{telescope}”: {n} frames are back on their setup from "
                        "before"}},
    "object.config_undo_add.kept": {
        "pl": {"one": " · {n} klatka zostaje - jej zestaw zmienił się po geście",
               "few": " · {n} klatki zostają - ich zestaw zmienił się po geście",
               "many": " · {n} klatek zostaje - ich zestaw zmienił się po geście"},
        "en": {"one": " · {n} frame stays - its setup changed after the gesture",
               "other": " · {n} frames stay - their setup changed after the gesture"}},
    "object.config_undo_add.retired": {
        "pl": " · teleskop „{telescope}” zdjęty z osi",
        "en": " · telescope “{telescope}” removed from the axis"},
    "object.config_undo_add.stays": {
        "pl": " · teleskop „{telescope}” zostaje: {reason}",
        "en": " · telescope “{telescope}” stays: {reason}"},
    "object.config_undo_add.refused": {
        "pl": "Nie cofnięto dopisania „{telescope}”: {reason}",
        "en": "Adding “{telescope}” not undone: {reason}"},
    "object.config_undo_add.busy": {
        "pl": "Trwa etap Dostawy - cofnięcie dopisania poczeka na jego koniec.",
        "en": "A Delivery stage is running - undoing the addition waits for it to finish."},
    "object.config_undo_add.refused.frames": {
        "pl": "ma klatki przypisane poza gestem",
        "en": "it has frames assigned outside the gesture"},
    "object.config_undo_add.refused.cleared_memory": {
        "pl": "nagrobek klatki pamięta ten obiekt",
        "en": "a frame's tombstone remembers this object"},
    "object.config_undo_add.refused.live_run": {
        "pl": "dotyczy go inny niecofnięty gest „Zmień obiekt…”",
        "en": "another “Change object…” gesture that is not undone involves it"},
    "object.config_undo_add.refused.foreign_alias": {
        "pl": "ma nazwę zapisaną poza gestem",
        "en": "it has a name saved outside the gesture"},
    "object.config_undo_add.refused.merged": {
        "pl": "jest scalony z innym teleskopem",
        "en": "it is merged into another telescope"},
    "object.config_undo_add.refused.members": {
        "pl": "scalono z nim inne teleskopy",
        "en": "other telescopes are merged into it"},
    "object.config_undo_add.refused.profile": {
        "pl": "wskazuje go profil kalibracji",
        "en": "a calibration profile points to it"},
    "object.config_undo_add.refused.calibration_fact": {
        "pl": "wskazuje go fakt przepisu kalibracji klatki",
        "en": "a frame's calibration recipe fact points to it"},
    "object.config_undo_add.refused.hand_after": {
        "pl": "zmieniono go ręką po geście (etykieta, park albo optyka)",
        "en": "it was changed by hand after the gesture (label, park or optics)"},
    "object.config_undo_add.refused.undone": {
        "pl": "to dopisanie jest już cofnięte",
        "en": "this addition is already undone"},
    "object.config_undo_add.refused.source_retired": {
        "pl": "klatki wróciłyby do zestawu teleskopu, którego dopisanie cofnięto wcześniej",
        "en": "the frames would return to a setup of a telescope whose addition was undone "
              "earlier"},
    # Zero klatek wróciło (wszystkie zmienione po geście) - zdanie nie mówi „cofnięto”, którego
    # nie było; człony `kept` i `stays`/`retired` doklejają się jak przy cofnięciu.
    "object.config_undo_add.nothing": {
        "pl": "Dopisanie „{telescope}”: żadna klatka nie wróciła do zestawu sprzed gestu",
        "en": "Adding “{telescope}”: no frame went back to its setup from before"},
    # Gest Osi teleskopu („Cofnij dopisanie” przy zaznaczonym wierszu z niecofniętym śladem
    # `telescope_add`) - trwała droga obok recepty paska, przeżywa przełączenie strony i restart.
    "axis.tel.undo_add": {"pl": "Cofnij dopisanie", "en": "Undo adding"},
    "axis.tel.undo_add_tip": {
        "pl": "Teleskop dopisany oknem „Dopisz nowy…” - klatki wracają do zestawu sprzed gestu, "
              "a teleskop schodzi z osi, gdy nie ma klatek ani zmian ręki po geście.",
        "en": "Telescope added with “Add new…” - the frames go back to their setup from before, "
              "and the telescope leaves the axis when it has no frames and no hand changes after "
              "the gesture."},
}
