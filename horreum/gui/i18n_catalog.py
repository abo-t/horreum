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
    "obshand.nothing": {"pl": "Brak klatek bez stanowiska - każda ma GPS albo wskazanie ręki.",
                        "en": "No frames without a site - each has GPS or a hand assignment."},
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
    "object.path_proposed_count": {
        "pl": "{names} nazw / {frames} klatek", "en": "{names} names / {frames} frames"},
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
    "path.head": {
        "pl": "{names} nazw · {frames} klatek. Nazwa pochodzi z FOLDERU na pozycji obiektu; "
              "zapis idzie do BAZY, a tam, gdzie plik na to pozwala, także jako karta OBJECT "
              "do PLIKU - nagłówek i folder powiedzą to samo. Odznacz to, czego nie chcesz "
              "zapisać; zatwierdzone cofniesz w Zbiorach przez „Obiekt ▾ → Cofnij przypisanie”, "
              "karty - przyciskiem „Cofnij karty” do zamknięcia okna.",
        "en": "{names} names · {frames} frames. The name comes from the FOLDER at the object "
              "position; the write goes to the DATABASE and, where the file allows it, also as an "
              "OBJECT card into the FILE - the header and the folder will say the same. Uncheck "
              "whatever you do not want written; confirmed names can be undone in Frames via "
              "“Object ▾ → Undo assignment”, cards - with „Undo cards” until the window closes."},
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
    "path.item": {"pl": "{canon}  ·  {n} klatek", "en": "{canon}  ·  {n} frames"},
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
    "path.done": {
        "pl": {"one": "Zatwierdzono {n} nazwę · przypisano {assigned} z {total} klatek",
               "few": "Zatwierdzono {n} nazwy · przypisano {assigned} z {total} klatek",
               "many": "Zatwierdzono {n} nazw · przypisano {assigned} z {total} klatek"},
        "en": {"one": "Confirmed {n} name · assigned {assigned} of {total} frames",
               "other": "Confirmed {n} names · assigned {assigned} of {total} frames"}},
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
        "en": "Name „{name}” has no alphanumeric characters — it cannot be a remembered alias.",
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
    "repair.group": {"pl": "{folder}  ·  {n} klatek", "en": "{folder}  ·  {n} frames"},
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
        "en": {"one": "Group „{name}” — {n} frame.", "other": "Group „{name}” — {n} frames."},
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
        "en": "„{canon}” is an own object — outside the catalogs, so the „Catalog” column stays empty.",
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
        "en": "(no object matches „{text}”)",
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
    "assign.new_designation": {
        "pl": "albo nowa nazwa (wypełnione nadpisuje wybór z listy):",
        "en": "or a new name (if filled, it overrides the list selection):",
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
        "en": "Unrecognized name „{text}” — the resolver cannot resolve it. "
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
    "nav.planer": {"pl": "Planer", "en": "Planner"},

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
    "grid.sel.frame_retired": {
        "pl": "Wycofano {done} z {total} klatek", "en": "Retired {done} of {total} frames"},
    "grid.sel.frame_restored": {
        "pl": "Przywrócono {done} z {total} klatek", "en": "Restored {done} of {total} frames"},
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
    "busy.saving_frames": {"pl": "Zapisuję {n} klatek…", "en": "Saving {n} frames…"},
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
        "en": "Switch to the \"{perspective}\" perspective",
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
    "grid.tip.copy_images": {"pl": " · obrazy: {n}", "en": " · images: {n}"},
    "grid.tip.copy_diff": {
        "pl": "\n    mówi inaczej: {fields}", "en": "\n    says otherwise: {fields}",
    },
    "grid.tip.copy_field_images": {"pl": "obrazy", "en": "images"},
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
              "{place} → “Take new”; if the file is no longer on disk - "
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
    "grid.sel.project": {"pl": "Wydaj na stół…", "en": "Serve to table…"},
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
        "pl": "Nazwano {assigned} z {total} klatek: {canon}",
        "en": "Named {assigned} of {total} frames: {canon}"},
    "grid.sel.object_cleared": {
        "pl": "Cofnięto przypisanie na {assigned} z {total} klatek",
        "en": "Assignment undone on {assigned} of {total} frames"},
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
    "grid.sel.out_of_view_set": {
        "pl": "odsłoni je „{action}”", "en": "reveal with \"{action}\""},
    "grid.sel.out_of_view_persp": {
        "pl": "odsłoni je perspektywa „{perspective}”",
        "en": "reveal with the \"{perspective}\" perspective"},
    "grid.sel.object_restore": {"pl": "Przywróć cofnięte przypisanie",
                                "en": "Restore undone assignment"},
    "grid.sel.object_restored": {
        "pl": "Przywrócono przypisanie na {assigned} z {total} klatek",
        "en": "Assignment restored on {assigned} of {total} frames"},
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
    # Zwykłe `t`, nie `t_plural`: trzy identyczne formy PL to sam koszt i ryzyko rozjazdu przy
    # edycji jednej z nich — odmiany tu nie ma, bo liczba stoi przy „z {total}".
    "grid.lin.cal.head": {
        "pl": "Skalibrowana: {n} z {total} klas",
        "en": "Calibrated: {n} of {total} classes",
    },
    "grid.lin.cal.vanished": {
        "pl": "master #{id} — plik zniknął z dysku",
        "en": "master #{id} — the file has vanished from disk",
    },
    "grid.lin.cal.delta": {"pl": "Δ {n} dni", "en": "Δ {n} days"},
    "grid.lin.cal.src.horreum": {"pl": "dobrane z przepisu", "en": "matched by recipe"},
    "grid.lin.cal.src.user": {"pl": "Twoja decyzja", "en": "your decision"},
    "grid.lin.cal.src.wbpp": {"pl": "z historii obróbki", "en": "from processing history"},
    "grid.lin.cal.gap.not_calibrated": {
        "pl": "przepisy nie są jeszcze policzone — uruchom etap Kalibracja w Dostawie",
        "en": "recipes have not been computed yet — run the Calibration step in Delivery",
    },
    "grid.lin.cal.rel.dark": {"pl": "ciemność (dark)", "en": "dark"},
    "grid.lin.cal.rel.flat": {"pl": "pole (flat)", "en": "flat"},
    "grid.lin.cal.state.pending": {
        "pl": "master jest — powiązania jeszcze nie policzono",
        "en": "master exists — the link has not been computed yet",
    },
    "grid.lin.cal.pending": {
        "pl": "⚠ uruchom etap Rodowód w Dostawie, żeby powiązać to, co już jest w archiwum",
        "en": "⚠ run the Lineage step in Delivery to link what the archive already holds",
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
    "grid.lin.hint.one_only": {
        "pl": "Zaznaczono kilka różnych klatek. Zostaw jedną — panel nie ma jak powiedzieć, "
              "o której z nich mówi.",
        "en": "Several different frames are selected. Leave one — the panel has no way to say "
              "which of them it is describing.",
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
    "grid.lin.flag.twins": {
        "pl": {"one": "ten sam zestaw klatek ma jeszcze {n} inna wersja obrazu",
               "few": "ten sam zestaw klatek mają jeszcze {n} inne wersje obrazu",
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
    "grid.criteria.only_torn_write": {
        "pl": "tylko pliki po przerwanym zapisie", "en": "only files after an interrupted write"},
    "grid.criteria.only_pending_finish": {
        "pl": "tylko zapisy czekające na dokończenie", "en": "only writes awaiting completion"},
    "grid.criteria.only_path_header_conflict": {
        "pl": "tylko nagłówek inny niż zatwierdzony folder",
        "en": "only header differing from the confirmed folder"},
    "grid.criteria.only_lineage": {
        "pl": "tylko obrazy bez rodowodu",
        "en": "only images without lineage",
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
    "pipeline.stage.adopt_testimony": {"pl": "Przejęcie zeznania", "en": "Testimony adoption"},
    # Linia raportu przejęcia zeznania (AR-5). Odmowy tylko, gdy są (QUIET); każda nazywa przyczynę,
    # bo „przejęto 1 z 3" bez niej zatajałoby, dlaczego dwie klatki dalej mówią głosem nieobecnej kopii.
    "pipeline.fmt.adopt.prefix": {
        "pl": "Zeznanie z nieobecnej kopii: ", "en": "Testimony from a missing copy: "},
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
    "pipeline.fmt.copy_facts.prefix": {"pl": "Fakty kopii: ", "en": "Copy facts: "},
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
    # Łańcuch w etykiecie wymienia fakty kopii: bez nich człowiek z 550 kopiami „?" w Porządkach
    # nie miał skąd wiedzieć, że złota akcja jest jedną z dwóch dróg do tej roboty.
    "pipeline.receive": {
        "pl": "Przyjmij nowe  (skan → fakty kopii → grupuj → rozwiąż → kalibracja → delta)",
        "en": "Take new  (scan → copy facts → group → resolve → calibrate → delta)",
    },
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
                      "recomputes what derives from it - the same stages as in “Take new”, with "
                      "no scan and no folder prompt, across the whole archive.",
               "other": "{n} copies are waiting for their facts (image count, header testimony). "
                        "This reads headers only and adopts the surviving copy's testimony, then "
                        "recomputes what derives from it - the same stages as in “Take new”, "
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
        "en": "No folder chosen - compares the last “Take new” source with the database: "
              "{source}. It checks only copies under this folder - to cover the whole archive, use "
              "“{pick}” and choose its root (the “Take new” source stays unchanged). Report only - "
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
    "pipeline.btn.stacks": {"pl": "Wciągnij stosy…", "en": "Take in stacks…"},
    "pipeline.tip.stacks": {
        "pl": "Wskaż korzeń drzewa obróbki — Horreum wciągnie same pliki `masterLight*.xisf` "
              "(bez plików pochodnych) i nie ruszy ani jednego bajtu",
        "en": "Choose the processing tree root — Horreum takes only `masterLight*.xisf` files "
              "(no derived files) and touches not a single byte",
    },
    "pipeline.stacks_last": {"pl": "ostatni korzeń: {root}", "en": "last root: {root}"},
    "pipeline.stacks_first": {
        "pl": "(jeszcze nie wskazano korzenia)", "en": "(no root chosen yet)",
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
    # Powody odmowy fasady `run_stage` (D-PD-6) — POWÓD, nie goły False: jedna bramka łączyła dwa
    # różne stany, a komunikat oparty na bool-u mógłby skłamać.
    "pipeline.refuse.no_db": {
        "pl": "brak otwartej bazy — otwórz bazę i spróbuj ponownie",
        "en": "no database open — open one and try again",
    },
    "pipeline.refuse.running": {
        "pl": "etap w biegu — uruchom „Rozwiąż” po jego zakończeniu",
        "en": "a stage is running — start „Resolve” after it finishes",
    },
    "pipeline.refuse.writeback": {
        "pl": "trwa zapis nagłówków do plików - etapy Dostawy ruszą po jego zakończeniu",
        "en": "header write to files in progress - Intake stages start after it finishes",
    },
    # Odmowa „Oznacz zniknięte” PO dialogu progu: w trakcie pytania inny etap albo zmiana źródła
    # zapomniały wynik sprawdzenia (`_forget_vanished`). `refuse.running` nie pasuje - odsyła
    # do „Rozwiąż”.
    "pipeline.refuse.mark_stale": {
        "pl": "wynik sprawdzenia przepadł w trakcie pytania (inny etap albo zmiana źródła) - nic "
              "nie zapisano; sprawdź obecność ponownie",
        "en": "the check result was dropped while the question was open (another stage or a "
              "source change) - nothing was written; check presence again",
    },
    "pipeline.counts": {
        "pl": "Pliki {done}/{total} · nowe {new} · pominięte {skipped} · przegląd {review} · {tail}",
        "en": "Files {done}/{total} · new {new} · skipped {skipped} · review {review} · {tail}",
    },
    "pipeline.stage_running": {"pl": "{stage} w toku…", "en": "{stage} in progress…"},
    "pipeline.stage_done_status": {"pl": "{stage}: gotowe.", "en": "{stage}: done."},
    "pipeline.scan_cancelled": {
        "pl": "[skan] przerwano po {n} plikach — baza spójna, ponowny skan dokończy.",
        "en": "[scan] interrupted after {n} files — database consistent, a rescan will finish.",
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
        "pl": "[skan] pliki {files} · nowe {new} · istniejące {existing} · pominięte {skipped} · "
              "wykluczone katalogi {excluded} · lokalizacje {loc_new} · odświeżone {loc_ref} "
              "(zeznania {hdr_ref}, przepięte {rebound}) · nagłówki {headers} · "
              "przegląd f/{frame_review} k/{camera_review} rodzaj/{kind}",
        "en": "[scan] files {files} · new {new} · existing {existing} · skipped {skipped} · "
              "excluded folders {excluded} · locations {loc_new} · refreshed {loc_ref} "
              "(testimonies {hdr_ref}, rebound {rebound}) · headers {headers} · "
              "review f/{frame_review} c/{camera_review} kind/{kind}",
    },
    # Skan, który nie ruszył, bo wątek tła nie zobaczył źródła jako katalogu (AR-31 (3)) - lustro
    # `pipeline.fmt.presence.not_done`: brak linii czytałby się jak „nic nie przybyło".
    "pipeline.fmt.scan_not_done": {
        "pl": "[skan] NIE WYKONANO - {reason}", "en": "[scan] NOT DONE - {reason}",
    },
    # To samo dla drogi „Stosy": sondę korzenia stosów robi wątek tła (AR-31 (3)), więc korzeń
    # nieosiągalny wraca jej własną linią, a nie linią skanu archiwum ani obecności.
    "pipeline.fmt.stacks_not_done": {
        "pl": "[stosy] NIE WYKONANO - {reason}", "en": "[stacks] NOT DONE - {reason}",
    },
    # Rodowód stosów (I-2d) — człony składane w `PipelineView._format_stack_lineage`.
    "pipeline.fmt.slin.prefix": {"pl": "[rodowód stosów] ", "en": "[stack lineage] "},
    "pipeline.fmt.slin.linked": {
        "pl": "wiadomo z czego: {n} z {total} obrazów ({inputs} klatek)",
        "en": "source known: {n} of {total} images ({inputs} frames)",
    },
    "pipeline.fmt.slin.history": {
        "pl": "z tego {n} potwierdza sam plik", "en": "of those {n} confirmed by the file itself",
    },
    "pipeline.fmt.slin.waiting": {
        "pl": "czeka na Ciebie {n}", "en": "waiting for you {n}",
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
    # Droga „Stosy" — człony składane w `PipelineView._format_stacks`; odmowy TYLKO gdy niezerowe.
    "pipeline.fmt.stacks.prefix": {"pl": "[stosy] ", "en": "[stacks] "},
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
    "pipeline.fmt.group": {
        "pl": "[grupuj] nagłówki {headers} · teleskopy {telescopes} · bez TELESCOP {no_tel} · "
              "kalibracja poza osią {off_axis}{unassigned}{by_hand} · "
              "konfiguracje {conf_prop}/{conf_assign} · konfig. do przeglądu {conf_review}",
        "en": "[group] headers {headers} · telescopes {telescopes} · no TELESCOP {no_tel} · "
              "off-axis calibration {off_axis}{unassigned}{by_hand} · "
              "configs {conf_prop}/{conf_assign} · configs to review {conf_review}",
    },
    "pipeline.fmt.group_unassigned": {"pl": " (odpięte {n})", "en": " (unassigned {n})"},
    # R1b: przebieg MIJA klatki z zestawem od ręki — i musi to powiedzieć. Bez tej doklejki po
    # geście na 427 klatkach raport pokazywałby SAM SPADEK („bez TELESCOP" i „do przeglądu" lecą
    # w dół), a przyczyna byłaby niewidzialna: człowiek czytałby, że przebieg nagle „naprawił"
    # coś sam. QUIET — doklejka wchodzi wyłącznie przy niezerowej liczbie, jak „odpięte" obok.
    "pipeline.fmt.group_by_hand": {"pl": " (zestaw ręką {n})", "en": " (setup by hand {n})"},
    "pipeline.fmt.resolve": {
        "pl": "[rozwiąż] klatki {frames} · klatki light {lights} · obiekty nowe {obj_new} · "
              "przypisane {obj_assign} · przegląd {obj_review} (różnych {obj_distinct}) · "
              "filtry {filters}",
        "en": "[resolve] frames {frames} · light frames {lights} · new objects {obj_new} · "
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
        "pl": "[kalibracja] klatki {frames} · przepisy {prof_prop}/{prof_assign} · "
              "fakty ze ścieżki {facts} · bez kompletu {incomplete}",
        "en": "[calibrate] frames {frames} · recipes {prof_prop}/{prof_assign} · "
              "facts from path {facts} · incomplete {incomplete}",
    },
    "pipeline.fmt.calibrate_gaps": {"pl": "\n   braki: {gaps}", "en": "\n   gaps: {gaps}"},
    "pipeline.fmt.lineage": {
        "pl": "[rodowód] lighty {lights} · powiązane: {linked}",
        "en": "[lineage] lights {lights} · linked: {linked}",
    },
    "pipeline.fmt.lineage_gaps": {"pl": "\n   luki: {gaps}", "en": "\n   gaps: {gaps}"},
    # `nameless` STOI OSOBNO od procentu (P-D): klatka bez `object_raw` nie wchodzi do mianownika
    # delty (nie ma nazwy, pod którą byłaby „nierozpoznana"), a bez tej pozycji raport dostawy jest
    # na całą klasę ślepy — i pierwsza nowa dostawa bez `OBJECT` przeszłaby bez śladu.
    "pipeline.fmt.delta": {
        "pl": "[delta] obiekt {resolved}/{total} ({pct:.1f}%){no_raw} · filtry {filters}\n"
              "   nierozpoznane: {top}\n   bez nazwy w nagłówku: {nameless}\n"
              "   do przeglądu: {review}",
        "en": "[delta] object {resolved}/{total} ({pct:.1f}%){no_raw} · filters {filters}\n"
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
    "pipeline.fmt.presence.not_done": {
        "pl": "[obecność] NIE WYKONANO — {reason}", "en": "[presence] NOT DONE — {reason}",
    },
    "pipeline.fmt.presence.cancelled": {
        "pl": "[obecność] przerwane przez użytkownika — nic nie zapisano",
        "en": "[presence] cancelled by user — nothing was written",
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
    "pipeline.fmt.presence.prefix": {"pl": "[obecność] ", "en": "[presence] "},
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
    "pipeline.fmt.presence.brake_recipe": {
        "pl": "„Sprawdź obecność” policzy potwierdzenia i da drogę zapisu",
        "en": "“Check presence” will count confirmations and offer a way to save",
    },
    "pipeline.presence.skipped_no_volume": {
        "pl": "pominięty — wolumin nieustalony, brak kotwicy zakresu",
        "en": "skipped — volume undetermined, no scope anchor",
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
        "en": "Add or pick a target („+ another target…”).",
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
        "en": "Serving to table → {root}\n\nThe disk is CHANGING. „Stop serving” halts after the current "
              "file; whatever was made\nstays on disk (undo = delete the folder in Explorer).",
    },
    "proj.cancelling": {
        "pl": "Anulowanie… (po bieżącym pliku)", "en": "Cancelling… (after current file)",
    },
    "proj.btn_cancelled": {"pl": "Przerwano", "en": "Cancelled"},
    "proj.btn_created_ok": {"pl": "Utworzono ✓", "en": "Created ✓"},
    "proj.btn_nothing_new": {"pl": "Bez zmian ✓", "en": "No changes ✓"},
    "proj.status_summary": {
        "pl": "Wydano na stół: {n} {word} → {root}",
        "en": "Served to table: {n} {word} → {root}",
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
    "proj.dry_head": {
        "pl": "DRY — bez zmian na dysku (układ {layout}, {mode}):",
        "en": "DRY — no disk changes (layout {layout}, {mode}):",
    },
    "proj.dry_counts": {
        "pl": "  {todo}: {would}   istnieje: {exists}   konflikty: {conflict}   pominięto: {skipped}",
        "en": "  {todo}: {would}   exists: {exists}   conflicts: {conflict}   skipped: {skipped}",
    },
    "proj.dry_size": {"pl": "  rozmiar kopii: {size}", "en": "  copy size: {size}"},
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
        "pl": "  nietknięte: {n} (plan zostaje — wznów przez „Odśwież podgląd”)",
        "en": "  untouched: {n} (the plan stays — resume via „Refresh preview”)",
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
    "tasks.stacks_lineage": {"pl": "Obrazy bez rodowodu", "en": "Images without lineage"},
    "tasks.superseded_frames": {"pl": "Zastąpione (historia)", "en": "Superseded (history)"},
    "tasks.retired_frames": {"pl": "Wycofane (historia)", "en": "Retired (history)"},
    "tasks.retired_conflict_frames": {
        "pl": "Wycofane, a plik wrócił", "en": "Retired, but the file is back"},
    "tasks.telescopes_unlabeled": {"pl": "Teleskopy bez etykiety", "en": "Telescopes without a label"},
    "tasks.observatories_unnamed": {"pl": "Stanowiska bez nazwy", "en": "Sites without a name"},
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
    # liczbie kopii (`{n}`), jak w „?".
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
                      "If the file is on disk - {place} → “Take new”.\n"
                      "If the copy lies under the stacks root - {place} → “{stacks}”.\n"
                      "If the file is no longer on disk - {place} → “{check}” → “{mark}” (appears "
                      "below the result when the check confirms the file is gone).\n"
                      "A click takes you to: {dest}.",
               "other": "{n} copies have no header testimony collected yet, so this count "
                        "does not include them.\n"
                        "If the file is on disk - {place} → “Take new”.\n"
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
    # `LMC` i nic nie tłumaczyło, dlaczego pasuje. Alias jest w formie znormalizowanej, bo tylko
    # taka istnieje w bazie (`object_alias.alias_norm`) — user rozpoznaje w niej własną frazę.
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

    # --- KANAŁ gotowego obrazu (0028, P4-3): grupa listwy facetów ---
    "facets.group.channel": {"pl": "Kanał", "en": "Channel"},
}
