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
    "path.head": {
        "pl": "{names} nazw · {frames} klatek. Nazwa pochodzi z FOLDERU na pozycji obiektu; "
              "zapis idzie do BAZY, nie do plików. Odznacz to, czego nie chcesz zapisać; "
              "zatwierdzone cofniesz w Zbiorach przez „Obiekt ▾ → Cofnij przypisanie”.",
        "en": "{names} names · {frames} frames. The name comes from the FOLDER at the object "
              "position; the write goes to the DATABASE, not the files. Uncheck whatever you do not "
              "want written; confirmed names can be undone in Frames via “Object ▾ → Undo "
              "assignment”."},
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
    "path.done": {
        "pl": "Zatwierdzono {names} nazw · przypisano {assigned} z {total} klatek",
        "en": "Confirmed {names} names · assigned {assigned} of {total} frames"},
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
        "pl": "{folders} grup · {frames} klatek — wszystkie mają zestaw wskazany PRZEZ CIEBIE. "
              "Zaznacz tylko te, które chcesz zmienić: zapis NADPISZE poprzednie wskazanie. "
              "Wchodzą odznaczone, żeby jedna poprawka nie przestemplowała reszty.",
        "en": "{folders} groups · {frames} frames — all have a setup indicated BY YOU. Check only "
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
        "pl": "{folders} grup · {frames} klatek. Kamerę zna plik; wskazać trzeba TELESKOP. "
              "Jednostką jest FOLDER × KAMERA, bo jeden zestaw niesie dokładnie jedną kamerę. "
              "Zapis idzie do BAZY, nie do plików — RAW jest read-only.",
        "en": "{folders} groups · {frames} frames. The file knows the camera; the TELESCOPE is what "
              "you must point out. The unit is FOLDER × CAMERA, because one setup carries exactly "
              "one camera. The write goes to the DATABASE, not the files — RAW is read-only."},
    "cfg.item": {"pl": "{folder}  ·  {camera}  ·  {n} klatek",
                 "en": "{folder}  ·  {camera}  ·  {n} frames"},
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
        "pl": "{n} klatek zostanie pominiętych: bez kamery nie ma z czego złożyć zestawu. "
              "Kamera przychodzi z zeznania pliku (INSTRUME/XPIXSZ) — to osobna oś: napraw "
              "nagłówek albo przeskanuj ponownie, potem wróć tutaj.",
        "en": "{n} frames will be skipped: without a camera there is nothing to build a setup from. "
              "The camera comes from the file's testimony (INSTRUME/XPIXSZ) — a separate axis: "
              "repair the header or re-scan, then come back here."},
    "object.config_assigned_report": {
        "pl": "Przypisano zestaw {telescope} → {assigned} z {total} klatek.",
        "en": "Assigned setup {telescope} → {assigned} of {total} frames."},
    # NASTĘPNY TAKT NAZWANY, nie domyślony (wzorzec taktu 3 z „Napraw nagłówek…"): oś sprzętu
    # działa natychmiast (facety, filtr), ale dobór rodowodu stosów czyta teleskop kandydata —
    # więc jeśli te klatki są materiałem gotowego obrazu, rodowód trzeba przeliczyć. Zdanie mówi
    # GDZIE; przycisku tu nie ma, bo na dzisiejszym archiwum nie miałby czego zmienić (wszystkie
    # 3367 wejść rodowodu to FITS-y), a obietnica bez skutku jest gorsza od wskazania drogi.
    "object.config_next_step": {
        "pl": " Rodowód gotowych obrazów przelicz w Dostawie („Policz rodowód”), gdy te klatki "
              "są materiałem stosu.",
        "en": " Recompute stack lineage in Delivery (“Compute lineage”) if these frames are stack "
              "material."},
    "object.config_skipped": {
        "pl": " (pominięte: {occupied} z zestawem, {no_camera} bez kamery, "
              "{kind_skip} kalibracja, {unchanged} bez zmiany)",
        "en": " (skipped: {occupied} already set, {no_camera} without a camera, "
              "{kind_skip} calibration, {unchanged} unchanged)"},
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
    # o pliku. „Rodzaj nieznany" = kopie oznaczone przed 0019 albo wyjątek bez kodu systemu,
    # którego nie dało się rozstrzygnąć.
    "object.unreadable_kinds": {"pl": "kopie: {parts}", "en": "copies: {parts}"},
    "object.unreadable_kind_io": {"pl": "dysk/dostęp {n}", "en": "disk/access {n}"},
    "object.unreadable_kind_parse": {"pl": "nagłówek {n}", "en": "header {n}"},
    "object.unreadable_kind_db": {"pl": "baza {n}", "en": "database {n}"},
    "object.unreadable_kind_unknown": {"pl": "rodzaj nieznany {n}", "en": "kind unknown {n}"},
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
        "pl": "Przypisano {assigned} z {total} klatek → {canon}",
        "en": "Assigned {assigned} of {total} frames → {canon}",
    },
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
        "pl": "„{text}” ma znaki spoza ASCII — nagłówek FITS ich nie przyjmie",
        "en": "„{text}” has non-ASCII characters — a FITS header will not take them",
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

    # --- ekran planera (T5c): kolumny listy i panel sterowania --------------------------------
    "planner.col_canon": {"pl": "Cel", "en": "Target"},
    "planner.col_type": {"pl": "Typ", "en": "Type"},
    "planner.col_size": {"pl": "Rozmiar", "en": "Size"},
    "planner.col_culmination": {"pl": "Kulminacja", "en": "Culmination"},
    "planner.col_window": {"pl": "Okno", "en": "Window"},
    "planner.col_rig": {"pl": "Zestaw i kadr", "en": "Rig and framing"},
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
              "i 1 h na kanał; próg kosztu Księżyca wyłączony.",
        "en": "Thresholds return to 6′ size, 15′ for dark nebulae, 13 mag for galaxies, 30° altitude\n"
              "and 1 h per channel; the Moon cost threshold goes off.",
    },
    "planner.chips_label": {"pl": "Patrzę oczami zestawu:", "en": "Seen through the rig:"},
    "planner.chip_tip": {
        "pl": "Soczewka, nie filtr: zmienia kolumny „Zestaw i kadr” oraz „Rada”. Żaden cel nie znika.",
        "en": "A lens, not a filter: changes the “Rig and framing” and “Advice” columns. No target disappears.",
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
    "grid.lin.flag.declared": {
        "pl": "plik deklaruje {n} klatek", "en": "the file declares {n} frames",
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
    "pipeline.receive": {
        "pl": "Przyjmij nowe  (skan → grupuj → rozwiąż → kalibracja → delta)",
        "en": "Take new  (scan → group → resolve → calibrate → delta)",
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
    "pipeline.btn.cancel": {"pl": "Anuluj", "en": "Cancel"},
    "pipeline.tip.calibrate": {
        "pl": "Przepis klatek kalibracyjnych — po „Rozwiąż” (przepis flata potrzebuje filtra)",
        "en": "Calibration frames recipe — after „Resolve” (the flat recipe needs the filter)",
    },
    "pipeline.tip.lineage": {
        "pl": "Powiąż lighty z masterami po przepisie — po „Kalibracja” (potrzebuje osi przepisu)",
        "en": "Link lights to masters by recipe — after „Calibrate” (needs the recipe axis)",
    },
    "pipeline.tip.presence": {
        "pl": "Wskaż katalog powyżej — pass porównuje drzewo z bazą",
        "en": "Choose a folder above — the pass compares the tree with the database",
    },
    "pipeline.btn.mark_vanished": {"pl": "Oznacz zniknięte", "en": "Mark vanished"},
    "pipeline.btn.show_collections": {"pl": "Pokaż w Zbiorach", "en": "Show in Collections"},

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
    "tasks.stacks_lineage": {"pl": "Obrazy bez rodowodu", "en": "Images without lineage"},
    "tasks.superseded_frames": {"pl": "Zastąpione (historia)", "en": "Superseded (history)"},
    "tasks.retired_frames": {"pl": "Wycofane (historia)", "en": "Retired (history)"},
    "tasks.retired_conflict_frames": {
        "pl": "Wycofane, a plik wrócił", "en": "Retired, but the file is back"},
    "tasks.telescopes_unlabeled": {"pl": "Teleskopy bez etykiety", "en": "Telescopes without a label"},
    "tasks.observatories_unnamed": {"pl": "Stanowiska bez nazwy", "en": "Sites without a name"},
    "tasks.dup_frames": {"pl": "Duplikaty (>1 kopia)", "en": "Duplicates (>1 copy)"},
    "tasks.vanished_frames": {"pl": "Zniknięte z dysku", "en": "Vanished from disk"},
    # NAZWA MÓWI O UBYTKU, NIE O AWARII (D-V-9a). Wiersz stoi obok „Zniknięte z dysku" i musi się
    # od niego odróżniać JEDNYM spojrzeniem: tam nie ma ani jednej żywej kopii i jest robota, tu
    # klatka żyje i nie ma nic do zrobienia. Stąd „kopie", nie „klatki", i człon w nawiasie, który
    # nazywa naturę wiersza dokładnie tak, jak robią to dwaj sąsiedzi z historii.
    "tasks.missing_copy_frames": {
        "pl": "Brakujące kopie (historia)", "en": "Missing copies (history)"},

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
}
