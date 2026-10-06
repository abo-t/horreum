"""Kryteria akceptacji PF-5 (brief/PLAN_przejscie_fits.md §5) — read-only walidacja realnego pipeline'u.

Re-baseline PF-5: baseline = DAWCA LIVE (`fitsmirror.db`), koniec custos.db. Świeżą bazę
Horreum buduje wprost z dawcy przez REALNY import (`import_fitsmirror.run_import`) — ten sam
pipeline co PF-3 (jedna klinga: `ingest_record` → grouper → resolver → kalibracja → rodowód,
z bramkami §4.6 w środku).
Skrypt dokłada kryteria §5 na wynikowej bazie i (opcjonalnie) odtwarza pełny stan PF-4 doskanem
XISF. Zero prywatnych ścieżek w kodzie — wszystko z argumentów.

Tryb HYBRYDOWY (odpowiednik replay+subset ze skilla `pipeline-replay-validation`):
  (I) IMPORT  — `run_import(dawca LIVE → świeża work.db)`. Cache'owane zeznania dawcy przez
      DOKŁADNIE ten sam `ingest_record`+grouper+resolver co realny skan, a od P-G także
      kalibracja+rodowód (fasada kończy CAŁY łańcuch Dostawy); §4.6 gate'y w środku
      (abort = twarde złamanie). Baseline FITS (8 teleskopów, 5 kamer), w minuty, zero 839 GB.
  (X) XISF-DOSKAN (opcja `--xisf-root DIR`) — po imporcie realny `scan_tree` po drzewie z XISF
      (volume z `volume_serial`), potem grouper+resolver. Odtwarza PF-4: FITS gate'owane mtime
      (skip, zero re-odczytu), XISF wciągane → 9. teleskop ED, pełne kotwice §5. Pełne `<xisf-root>`
      → pełny stan pf4 (czyta tylko ~331 nagłówków XISF, reszta stat-skip). Poddrzewo `STACKS`
      pod korzeniem jest ODCINANE (AR-53 O1): stosy wchodzą wyłącznie etapem (T), a kotwice
      FULL znaczą „archiwum" (`korzenie_doskanu`; zwykły skan produktu `STACKS` wciąga dalej).
  (K) KALIBRACJA — `run_calibration` na gotowym stanie (po grouperze i resolverze) + kolejny przebieg
      jako dowód idempotencji. Oś przepisu jest bramkowana tu, bo jej kotwice (38 dark / 37 flat)
      zmierzono na pełnym archiwum, a mastery są XISF — bez doskanu nie ma czego liczyć.
      **Od P-G łańcuch kalibracji+rodowodu robi już `run_import`**, więc w trybie IMPORT ta faza
      jest przebiegiem DRUGIM (zera delt = dowód, nie regresja; pinuje to §4.6), a w FULL wciąż
      pierwszym dla masterów przyniesionych doskanem.
  (T) STOSY (opcja `--stacks-root <xisf-root>\\STACKS`) - po doskanie zwykły `scan_tree` KORZENIA
      archiwum, czyli droga produktu (E4-1 wariant A+): archiwum przeskakuje brama `mtime`, wchodzi
      wyłącznie `STACKS` z sitem pochodnych, gotowe obrazy po integracji jako `master_light`
      (rodzaj z `IMAGETYP`). Trzeci etap, bo trzeci ZAKRES - dawca to archiwum FITS, `--xisf-root`
      to archiwum XISF bez `STACKS`, a to jest drzewo gotowych obrazów. Inny `--stacks-root` niż
      `<xisf-root>\\STACKS` i lokacja dodana spoza `STACKS` przerywają przebieg (EXPECT).
      Uruchomiony BEZ `--xisf-root` daje bazę, której ta bramka nie zna (kotwice STOSÓW
      są liczone na stanie FULL) — skrypt odmawia takiego przebiegu zamiast liczyć nieporównywalne.
  (U) RODOWÓD STOSÓW (razem z `--stacks-root`) — `run_stack_lineage` (I-2c): co weszło w gotowy
      obraz. Osobna faza od (L), bo to inna oś (tam „czym skalibrowano klatkę", tu „z czego zrobiono
      obraz") i inne źródło pewności: historia PixInsighta DOWODZI, okno tylko WSKAZUJE kandydatów.
  (C) KRYTERIA — stage-aware (import / full / full+stosy): zestawia aktualia z EXP_* PF-3+PF-4+P-I.
  (S) SUBSET (opcja `--subset DIR`) — realny `scan_tree` małego katalogu do OSOBNEJ work.db:
      dowód, że czytniki astropy/XISF + sha1 działają na realnych bajtach; tu (i tylko tu) realny
      no-split FITS-float ↔ XISF-string, gdy katalog ma oba formaty.

§8.1 (meta-tripwir AST jednej klingi) i bramka izolowanego clone'a są OSOBNE — pytest
(`tests/test_repo_safety.py`) i procedura clone→venv→non-editable→pytest; ten skrypt je przypomina.

Użycie:
  python scripts/acceptance_s5.py --donor fitsmirror.db [--xisf-root <xisf-root>]
                                  [--stacks-root <xisf-root>\\STACKS] [--live-db <zywa horreum.db>]
                                  [--subset PATH\\maly_real_dir] [--work PATH\\horreum_s5.db] [--keep]

`--live-db` podawaj ZAWSZE, gdy Horreum naprawiał nagłówki na tym samym drzewie (D-0722-2
wariant A): dawca jest zamrożonym snapshotem sprzed napraw, więc bez rejestru losowa próbka
falsyfikatora czyta naprawiony plik jako „dawca stęchły z NIEZNANEGO powodu" i abortuje.
"""
import argparse
import json
import os
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

# pakiet horreum z korzenia repo (skrypt leży w scripts/)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from horreum import db                                              # noqa: E402
from horreum import supersede                                     # noqa: E402
from horreum.audit import (config_review_reason_gap, config_source_invariants,  # noqa: E402
                           config_unpaired_reassignments, entity_event_parity,
                           light_population_closure, object_source_audit,
                           retire_invariants, supersede_invariants)
from horreum.calibration import KIND_RECIPE, run_calibration      # noqa: E402
from horreum.lineage import run_lineage                           # noqa: E402
from horreum.grouper import NO_TELESCOPE_KINDS, run_grouper       # noqa: E402
from horreum.gui.queries import nameless_frames                   # noqa: E402  (Qt-wolne)
from horreum.import_fitsmirror import (                                   # noqa: E402
    ImportAbort, donor_header, open_donor, read_repaired_registry, run_import,
)
from horreum.resolve.headers import extract_header                # noqa: E402
from horreum.resolve.regions import resolve_region                # noqa: E402
from horreum.resolver import (                                    # noqa: E402
    NO_OBJECT_CARD_FILETYPES, delta_report, run_resolver)
from horreum.resolve.paths import STACK_KIND, STACKS_DIR          # noqa: E402
from horreum.scan import (                                        # noqa: E402
    EXCLUDED_DIR_NAMES, HEADER_SUFFIXES, canonize_root, scan_tree)
from horreum.stacks import run_stack_lineage                      # noqa: E402
from horreum.volumes import volume_serial                         # noqa: E402


# ── POCHODZENIE KOTWIC (AR-53, decyzja Zdzinia 2026-10-05) ──────────────────────────────────────
# Kotwica bez daty i stanu archiwum jest liczbą bez nazwy miary: przebieg FULL 2026-10-04 dał
# 11 czerwieni i każdą trzeba było rozbierać ręcznie, żeby odróżnić regresję od kotwicy po prostu
# STAREJ (zmierzonej na innym stanie `R:`). Stąd każda `EXP_*` niesie `Pomiar` - kiedy, jakim
# przebiegiem, na jakim stanie archiwum i jakim kodem - a FAIL drukuje go obok obu wartości
# razem z wiekiem kotwicy. JEDNO ŹRÓDŁO: data i stan mieszkają WYŁĄCZNIE w `Pomiar`; komentarze
# przy kotwicach zostają historią DECYZJI (dlaczego ta liczba), nie metryczką pomiaru.
# Ponowny pomiar = nowy `Pomiar` (jeden na przebieg) i przepięcie na niego wartości, które
# ten przebieg zmierzył. Pole, którego nie da się ustalić z komentarzy i gita, mówi „nieustalone".
# Korzenie drzew zapisujemy symbolicznie (`<archiwum>`, `<stosy>`) - repo jest publiczne.
@dataclass(frozen=True)
class Pomiar:
    """Jeden przebieg, który zmierzył (albo potwierdził) kotwice. `dzien=None` = nieustalone."""
    dzien: str | None    # 'RRRR-MM-DD'
    przebieg: str        # tryb + argumenty
    stan_r: str          # zdarzenie na archiwum, po którym mierzono
    kod: str             # commit kodu przebiegu albo commit, który wpisał wartość


@dataclass(frozen=True)
class Kotwica:
    """Oczekiwana wartość kryterium z pochodzeniem. `wartosc=None` = NIEZMIERZONA (bramka mówi
    „nie wiem", patrz `crit_k`). `potwierdzenie` = ostatni udokumentowany przebieg, w którym ta
    sama wartość dała PASS - odróżnia kotwicę starą od kotwicy starej, ale świeżo sprawdzonej."""
    wartosc: object
    pomiar: Pomiar
    potwierdzenie: Pomiar | None = None


def opis_pomiaru(p, dzis):
    """Jedna linia pochodzenia z wiekiem w dniach liczonym od `dzis` (`datetime.date`)."""
    if p.dzien is None:
        kiedy = "data nieustalona"
    else:
        kiedy = f"{p.dzien} ({(dzis - date.fromisoformat(p.dzien)).days} dni temu)"
    return f"{kiedy}; przebieg: {p.przebieg}; stan R: {p.stan_r}; kod: {p.kod}"


def opis_niezgodnosci(k, akt, dzis, rel="=="):
    """Linie wydruku przy FAIL kryterium z kotwicą: oczekiwana i aktualna wartość, pochodzenie
    kotwicy i jej wiek, a jeśli jest - ostatnie potwierdzenie."""
    linie = [f"oczekiwano {rel} {k.wartosc!r}, aktualnie {akt!r}",
             f"kotwica zmierzona: {opis_pomiaru(k.pomiar, dzis)}"]
    if k.potwierdzenie is not None:
        linie.append(f"ostatnio potwierdzona: {opis_pomiaru(k.potwierdzenie, dzis)}")
    return linie


# Przebiegi, z których pochodzą dzisiejsze kotwice - odczytane z komentarzy i z gita
# (`git log -G` na liniach kotwic). „wpisane w <commit>" = wiemy, kiedy liczba weszła do kodu,
# ale nie, jakim kodem ją zmierzono.
# Re-baseline PF-5: firsthand IMPORT tym skryptem (15 559 frame == location, 8 teleskopów),
# WSZYSTKO PASS - komunikat `70abc43`. Dzień = data commitu; argumentów poza `--donor`
# komunikat nie podaje (`--live-db` powstał dopiero w ff32564).
_POMIAR_PF5_IMPORT = Pomiar(
    "2026-07-03", "IMPORT --donor <dawca> (firsthand PF-5, WSZYSTKO PASS)",
    "nie dotyczy - zeznanie zamrożonego dawcy; archiwum przed naprawą `ED` (P6)", "70abc43")
_POMIAR_OBS = Pomiar(None, "nieustalone", "nieustalone", "wpisane w d2a58d6 (2026-07-03)")
# Kind-scoping: przebieg akceptacji na kodzie `1c3d1bf`, WSZYSTKO PASS z `config.review=1`
# (archiwum kolejki, sesja 2026-07-22 (2)) - PRZED naprawą `ED` na `R:` (sesja (8) tego dnia).
_POMIAR_KIND_SCOPING = Pomiar("2026-07-22", "FULL (argumenty nieustalone), WSZYSTKO PASS",
                              "przed naprawą `ED` na archiwum (P6)", "1c3d1bf")
_POMIAR_P6B = Pomiar("2026-07-22", "nieustalone (re-baseline P6b razem z backfillem)",
                     "po naprawie `ED` (P6) i backfillu kart XISF (P6b)", "wpisane w 0528263")
# C2: archiwum kolejki, sesja 2026-07-22 (10) - trzeci przebieg (pierwszy padł transientem SMB).
_POMIAR_C2 = Pomiar("2026-07-22", "FULL --xisf-root <archiwum> --live-db: WSZYSTKO PASS",
                    "po naprawie `ED` (P6) i backfillu kart XISF (P6b)", "8bf2d66")
_POMIAR_IMPORT_0801 = Pomiar("2026-08-01", "IMPORT --donor --live-db",
                             "nie dotyczy (od AR-49 kotwica liczy zeznanie dawcy)",
                             "wpisane w 9e72c91")
_POMIAR_FULL_0801 = Pomiar("2026-08-01", "FULL --donor --xisf-root <archiwum> --live-db",
                           "po pilocie P-D (karty `OBJECT`), RAW-y DSLR w archiwum",
                           "wpisane w 33a2a19")
_POMIAR_STOSY_0801 = Pomiar("2026-08-01", "sonda drogi „Stosy” na starym drzewie obróbki",
                            "stare drzewo obróbki, przed przenosinami do `STACKS`",
                            "wpisane w 7c06e07")
_POMIAR_RAW_0804 = Pomiar("2026-08-04", "FULL i FULL+STOSY --live-db",
                          "po kasacji `LIGHTS\\Orion\\A7S1_000\\OSC` (7 `.dng`, 2026-08-03)",
                          "9ac4c18")
_PROG = Pomiar(None, "próg z zapasem, nie pomiar", "nie dotyczy", "85.0 od 70abc43")
# Potwierdzenia: przebiegi, w których kotwica dała PASS bez zmiany wartości.
_POTW_0804 = Pomiar("2026-08-04", "FULL i FULL+STOSY --live-db: WSZYSTKO PASS",
                    "po kasacji 7 `.dng` (C3); stosy w starym drzewie obróbki", "9ac4c18")
_POTW_IMPORT_1004 = Pomiar("2026-10-04", "IMPORT --donor --live-db: WSZYSTKO PASS (56)",
                           "po wsadzie kart `OBJECT` (7412 plików)", "b718ec4")
_POTW_FULL_1004 = Pomiar("2026-10-04", "FULL --donor --xisf-root <archiwum> --live-db "
                         "(11 FAIL, ta kotwica PASS)", "po wsadzie kart `OBJECT` i renamie T-1; "
                         "`STACKS` jeszcze w doskanie (przed O1)", "5b39f72")
# AR-53 (2026-10-06): kotwice FULL i FULL+STOSY przepięte po zbadaniu KAŻDEJ niezgodności - żadna nie
# jest regresją. (b) rozdział obiektywów RAW (paczka F); (c) kod `64f8fbc` (2026-08-09) czyta XISF ze
# znakiem nielegalnym w XML - masterflat OIII przestał być degeneratem (ten sam `file_sha1`, plik
# nietknięty); (d) nowe dane w archiwum; (e) kasacja błędnych kopii `L-Pro`/`OSC` z `R:` (AR-5,
# 2026-09-26) - znikła klasa-sierota. Stosy: drzewo `STACKS` (193 pliki w nazwach kanonicznych)
# zamiast starego drzewa obróbki (128), etap drogą produktu.
_POMIAR_FULL_1005 = Pomiar("2026-10-05", "FULL --donor --xisf-root <archiwum> --live-db (10 FAIL, "
                           "przyczyny zbadane 2026-10-06)", "po wsadzie kart `OBJECT`, renamie T-1 "
                           "i kasacji kopii AR-5; `STACKS` poza doskanem (O1)", "7d8f69e + 778b268")
_POMIAR_STOSY_1006 = Pomiar("2026-10-06", "FULL+STOSY --donor --xisf-root <archiwum> --stacks-root "
                            "<archiwum>\\STACKS --live-db (18 FAIL - wyłącznie kotwice sprzed AR-53)",
                            "jak `_POMIAR_FULL_1005`; 193 stosy pod `STACKS`",
                            "dd5a31a + etap stosów drogą produktu")
# Potwierdza WYŁĄCZNIE kotwice, które w tym przebiegu dały PASS (kamery, konflikt piksela).
# Kotwice przepięte z jego `akt=` mają w polu potwierdzenia nic - ich wartość zmierzono, a nie
# potwierdzono.
_POTW_STOSY_1006 = Pomiar(_POMIAR_STOSY_1006.dzien, _POMIAR_STOSY_1006.przebieg + ", ta kotwica PASS",
                          _POMIAR_STOSY_1006.stan_r, _POMIAR_STOSY_1006.kod)

# ── Kotwice EXP_* PF-3 (dawca) + PF-4 (doskan drzewa `R:`) ──────────────────────────────────────
# UWAGA 2026-08-01: doskan NIE jest już „XISF-owy" — odkąd istnieje moduł DSLR (`e7dcdda`), ciągnie
# z `R:` także RAW-y (dziś `EXP_NAMELESS_RAW_FULL`), więc baza FULL ma populacje, których żywa
# `pf4` (0 RAW-ów w chwili tego zapisu) nie zna. Stąd kotwice FULL są STAGE-AWARE i ROZDZIELONE
# astro/RAW — liczba sklejająca oba tory ukryłaby regresję w torze astro za kolejną sesją
# z lustrzanką. **Tor RAW jedzie z ŻYWEGO drzewa, więc jego kotwice ruszają się od zmian na dysku
# — pierwszy taki ruch: nota C3 przy `EXP_CONFIG_REVIEW_RAW_FULL`.**
# 5 kamer w IMPORT: (pixel_um, is_mono). Po naprawie nagłówków INSTRUME 100% — brak review kamer.
EXP_CAMERAS_IMPORT = Kotwica({
    "ASI2600MM": (3.76, 1), "ASI2600MD": (3.76, 1), "ASI2600MC": (3.76, 0),
    "ASI294MC": (4.63, 0), "SONYA7RM3": (4.86, 0),
}, _POMIAR_PF5_IMPORT, _POTW_IMPORT_1004)
# RE-BASELINE FULL 2026-08-01 (odnowa bramki): doskan `R:` ciągnie też RAW-y, odkąd istnieje moduł
# DSLR (`e7dcdda`) — korpusy lustrzanek są na osi kamer TAK SAMO realne jak ASI.
# `SONYA7RM3` NIE jest nowa — ma 4.86 µm z `bayerpat` (FITS) i dodatkowo 301 klatek RAW; to ONA
# dowodzi, że oba tory schodzą się na jednym wierszu kamery zamiast go rozbijać.
# Wartość wypisana WPROST, nie `dict(IMPORT, …)`: ponowny pomiar kotwicy IMPORT nie może po cichu
# przestawić kotwicy FULL, która przy tym pomiarze nie była mierzona.
# PIKSEL Z EXIF 2026-10-06 (AR-55 (2)): RAW niesie `XPIXSZ` z `FocalPlaneXResolution`, więc
# lustrzanki dostają piksel z pierwszego zeznania (A7S z DNG 8,469 - ARW tagu nie ma; A7M3 5,962;
# 40D 5,723). SONYA7RM3 zostaje przy 4,86 z dawcy FITS, a jej EXIF 4,62 to KONFLIKT PRAWDZIWY
# (5 % poza tolerancją 0,6 %) - świeża baza FULL go stawia (`EXP_PIXEL_CONFLICT_FULL`); w żywej
# bazie zdejmuje go piksel z ręki (4,52), którego świeża baza nie zna. Wartości z sondy, nie
# z przebiegu FULL - pierwszy przebieg je potwierdzi albo obali.
_POMIAR_EXIF_PIKSEL_1006 = Pomiar(
    "2026-10-06", "sonda read-only EXIF RAW (plik na kamerę i format), nie przebieg tego skryptu",
    "po renamie T-1; 756 RAW obecnych w pf4", "AR-55 (2), wpisane razem z czytnikiem")
EXP_CAMERAS_FULL = Kotwica({
    "ASI2600MM": (3.76, 1), "ASI2600MD": (3.76, 1), "ASI2600MC": (3.76, 0),
    "ASI294MC": (4.63, 0), "SONYA7RM3": (4.86, 0),
    "SONYA7S": (8.469, 0), "SONYA7M3": (5.962, 0), "CANONEOS40D": (5.723, 0),
}, _POMIAR_EXIF_PIKSEL_1006, _POTW_STOSY_1006)
EXP_PIXEL_CONFLICT_IMPORT = Kotwica(0, _POMIAR_PF5_IMPORT, _POTW_IMPORT_1004)
EXP_PIXEL_CONFLICT_FULL = Kotwica(1, _POMIAR_EXIF_PIKSEL_1006, _POTW_STOSY_1006)
# dawca FITS (§1): A140R/RC8/76EDPH/ED120R/RC6/N800/Sony135/ED120
EXP_TELESCOPES_IMPORT = Kotwica(8, _POMIAR_PF5_IMPORT, _POTW_IMPORT_1004)
# Po naprawie ED na realnym R: (2026-07-22, brief PLAN_p6_xisf_writeback §8) etykieta `ED` nie ma już
# nosiciela na osi: 7 masterflatów XISF dostało `ED120R`+789, a masterdarki z `TELESCOP='ED'` są POZA
# osią (kind-scoping, wariant B). Świeża baza nie powołuje 9. teleskopu — dług PF-4 spłacony.
# RE-BASELINE FULL 2026-08-01: 8 optyk astro + 4 OBIEKTYWY z EXIF, które wnoszą RAW-y (`FE 24-105mm
# F4 G OSS` 265 klatek, `105mm F1.4 DG HSM | Art 018` 36, `DT 0mm F0 SAM` 22, `FE 70-300mm` 8 —
# wszystkie w 100% RAW). Obiektyw JEST optyką, więc własny wiersz osi jest poprawny, nie śmieciem;
# do PLANERA i tak nie wchodzą, bo park jest jawną własnością usera (D-0731-12), nie derywatem.
# AR-53 (b): rozdział obiektywów RAW (paczka F, `D-OW-3/R1`) - `DT 0mm F0 SAM` na 50/@70/@188 mm.
EXP_TELESCOPES_FULL = Kotwica(14, _POMIAR_FULL_1005)   # astro (jak IMPORT) + obiektywy DSLR
# …z nich powołane WYŁĄCZNIE przez klatki RAW (obiektywy z EXIF)
EXP_TELESCOPES_RAW_ONLY_FULL = Kotwica(6, _POMIAR_FULL_1005)
# % obiektu na light/master_light. Próg z zapasem; wartość AKTUALNĄ podaje wydruk §5.7 tego skryptu
# (dawca, `--full`) — nie zamrażamy jej tutaj, bo metryka zmieniła DEFINICJĘ w S0 (licznik zawężony
# do klatek z nazwą w nagłówku, symetrycznie do mianownika), więc każda liczba sprzed tej zmiany
# opisuje inny rachunek. Licznik i mianownik kurczą się razem, więc próg powinien się bronić —
# ale to jest do ZMIERZENIA pierwszym przebiegiem po S0, nie do założenia.
EXP_OBJECT_PCT_MIN = Kotwica(85.0, _PROG)
# Stan PF-4 (pełny, po doskanie XISF) — XISF wnoszą dług review i degenerat:
# masterflat OIII: bajt \x07 w XML → sha1_data nieobliczalne (degenerat). AR-53 (c): od `64f8fbc`
# skan czyta taki plik - degeneratu nie ma, kotwica 0 pilnuje, żeby nie wrócił.
EXP_UNCOMPUTABLE_FULL = Kotwica(0, _POMIAR_FULL_1005)
EXP_FRAME_REVIEW_FULL = Kotwica(0, _POMIAR_FULL_1005)   # ten sam masterflat (kopia nieczytelna → review)
# Po kind-scopingu config (wariant B, 2026-07-22) dark/bias są POZA osią teleskopu: ich `config_id
# IS NULL` to stan docelowy, nie delta, więc `config.review` ich nie dotyczy. Zostaje 1 realna sprawa
# — masterflat Sony A7R3 o rodzaju `unknown` (ten sam degenerat, co §5.2). Było 7 (6 masterdarków + on).
# `unknown` masterflat A7R3 - rodzaj wymaga decyzji, nie optyka
EXP_CONFIG_REVIEW_FULL = Kotwica(1, _POMIAR_KIND_SCOPING, _POTW_0804)
# …liczona POZA RAW-ami (2026-08-01). RAW-y bez configu to stan UCZCIWY: zdjęcie z lustrzanki
# bez teleskopu w EXIF nie ma z czego powołać osi. Gdyby obie populacje wpadły do jednej kotwicy,
# pojawienie się DRUGIEJ realnej sprawy w torze astro schowałoby się za jednym zdjęciem
# mniej z aparatu — kotwica przestałaby pilnować tego, po co powstała.
#
# ── NOTA C3: RE-BASELINE −7 NA TRZECH KOTWICACH RAW (2026-08-04) ─────────────────────────────────
# Kotwice toru RAW jadą z ŻYWEGO skanu `R:\ASTRO_` (nie z zamrożonego dawcy — patrz uwaga nad
# EXP_* FULL), więc kasowanie plików na dysku RUSZA je zgodnie z prawdą. Zdarzyło się to pierwszy
# raz 2026-08-03: cały folder `LIGHTS\Orion\A7S1_000\OSC` (7 klatek `.dng`, `frame_id` 16627–16633)
# został skasowany z dysku decyzją użytkownika — pliki WADLIWE, blok D-OW-3\C3 w briefie obiektów
# własnych. Przebieg akceptacji 2026-08-04 zobaczył to jako pierwszy: 763→756, 432→425, 763→756,
# jedna przyczyna na trzy czerwienie. Sprawdzone przed przestemplowaniem: pozostałe 13 klatek
# Oriona (`A7S1_050` 4 + `A7S1_070` 9) leżą na dysku nietknięte, a plików z `A7S1_000` nie ma
# NIGDZIE w `R:\ASTRO_` (nie przenosiny — kasacja). Strona BAZY C3 (7 wierszy `frame`/`location`/
# `header` + 28 `cards` + 28 `event` na żywej `pf4`) jest na 2026-08-04 NIERUSZONA — należy do
# etapu 3 D-0802-2. Kotwice mówią o świeżej bazie akceptacji, nie o `pf4`, więc są niezależne.
EXP_CONFIG_REVIEW_RAW_FULL = Kotwica(425, _POMIAR_RAW_0804)   # było 432 - nota C3 wyżej
EXP_XISF_KINDS = Kotwica(
    {"flat": 11, "light": 228, "master_dark": 38, "master_flat": 74, "unknown": 1},
    _POMIAR_FULL_1005)   # AR-53: (c) OIII 15629 unknown → master_flat, (d) +26 lightów XISF
# Oś OBSERWATORIUM (PLAN_os_obserwatorium §8) — RE-BASELINE P6b (D-X-8a), świadomy i zmierzony:
# do P6a karty XISF NIE POWSTAWAŁY, więc GPS był de facto FITS-only. Od P6a skan wypełnia karty
# także dla XISF, a backfill (`horreum backfill-xisf`) dociąga je do lokacji sprzed P6a — 202 klatki
# XISF niosą SITELAT+SITELONG i wchodzą na oś. Wszystkie 202 mają JEDNĄ parę współrzędnych, 52 m od
# stanowiska „Szczecin, Będargowo" → ZERO nowych stanowisk (EXP_OBSERVATORIES bez ruchu), rusza się
# wyłącznie populacja. Kotwica jest STAGE-AWARE: etap IMPORT (dawca FITS, zero XISF) zostaje na
# 15 409 — gdyby liczba tam drgnęła, znaczyłoby to zmianę w torze FITS, nie skutek P6.
# klaster 4 km: 24 distinct pary → 11 stanowisk (dom↔praca 4.385 km OSOBNE)
EXP_OBSERVATORIES = Kotwica(11, _POMIAR_OBS, _POTW_IMPORT_1004)
# dawca FITS: klatki z SITELAT+SITELONG (97.0%)
EXP_GPS_FRAMES_IMPORT = Kotwica(15409, _POMIAR_P6B, _POTW_IMPORT_1004)
# + XISF z GPS w kartach (202 w P6b, wszystkie do stanowiska #5; 267 po nowych dostawach, AR-53 (d))
EXP_GPS_FRAMES_FULL = Kotwica(15676, _POMIAR_FULL_1005)
# bez GPS w torze ASTRO: 150 fits + 124 xisf (326 − 202 z GPS)
EXP_NO_GPS_FULL = Kotwica(274, _POMIAR_FULL_0801, _POTW_0804)
# RAW osobno (2026-08-01): klatki DSLR, wszystkie bez stanowiska. To NIE brak danych — sentinel
# GPS (0,0) idzie w `resolve/observatory.py:67` na `None` świadomie („null island" nie jest miejscem),
# a aparat bez modułu GPS nie zapisuje nic. Rozdzielone od astro z tego samego powodu, co
# `config.review`: jedna liczba przykryłaby ruch w populacji FITS/XISF.
EXP_NO_GPS_RAW_FULL = Kotwica(756, _POMIAR_RAW_0804)   # było 763 - nota C3 przy EXP_CONFIG_REVIEW_RAW_FULL
# Oś KALIBRACJI (C2, brief PLAN_kalibracja_C_brief §3.2) — kotwice ZMIERZONE read-only PRZED kodem.
# Mastery są XISF, więc obie liczby dotyczą wyłącznie etapu FULL; w imporcie FITS nie ma czego liczyć.
EXP_RECIPE_DARK = Kotwica(38, _POMIAR_C2, _POTW_0804)   # masterdarki → przepisy (każdy master unikalny)
# 38, nie 37 z briefu §3.2: brief mierzył ŻYWĄ pf4, a ta ma o jedną klasę MNIEJ z powodu, który
# sam brief przewidział (§8). `frame 15645` ma DWIE kopie o sprzecznym zeznaniu — ten sam master
# leży w `…RC8_2600MC\CLS\` i `…\L-Pro\` (identyczne DANE → jedna klatka, różne nagłówki → jeden
# z nich przeżywa). Świeży skan zostaje przy PIERWSZYM odczycie (`CLS` — własna, jednoelementowa
# klasa → 38); na żywej pf4 backfill P6b przestawił zeznanie na `L-Pro`, gdzie klasa już istniała
# (→ 37). Sprzeczność siedzi w DANYCH i C2 ma ją POKAZAĆ, nie rozstrzygać — dlatego kotwicą jest
# liczba świeżej bazy, a osobne kryterium pinuje samą PRZYCZYNĘ (klasa-sierota z pary kopii).
EXP_RECIPE_FLAT = Kotwica(38, _POMIAR_C2, _POTW_0804)   # 2256 flatów + 73 masterflaty na ŚWIEŻEJ bazie
# Klasa-sierota ze sprzecznej pary kopii (`frame 15645`, CLS↔L-Pro) - PRZYCZYNA 38. klasy wyżej.
# Do AR-53 literał w kryterium §5.11; wyjęty tu, żeby jego pochodzenie było tak samo widoczne.
# AR-53 (e): kopię `L-Pro` skasowano z `R:` (AR-5, 2026-09-26) - sprzeczności już nie ma; 0 pilnuje,
# żeby nowa para kopii o sprzecznym zeznaniu nie weszła po cichu.
EXP_RECIPE_ORPHAN_FULL = Kotwica(0, _POMIAR_FULL_1005)
# masterflat A7R3 (`unknown`) - POZA osią, jawnie wykluczony; OIII czytelny od `64f8fbc` (AR-53 (c))
EXP_MASTERS_EXCLUDED_FULL = Kotwica(1, _POMIAR_FULL_1005)
# RODOWÓD (C4) — lighty powiązane z masterem po przepisie, ŚWIEŻA baza. Zmierzone przebiegiem
# FULL (świeża baza z dawcy) ORAZ niezależnie na kopii żywej pf4 - obie dały te same liczby
# (profil-sierota CLS↔L-Pro §5.11 nie ruszył sum rodowodu). Domknięcie w tamtym pomiarze:
# dark 7331 + luki 6185 = flat 11938 + luki 1578 = 13 516 lightów.
# lighty z masterdarkiem (reszta: 5978 brak przepisu + 207 niekompletny)
EXP_LINEAGE_DARK = Kotwica(7370, _POMIAR_FULL_1005)   # AR-53 (d)
# lighty z masterflatem (reszta: 1455 brak przepisu + 123 brak mastera)
EXP_LINEAGE_FLAT = Kotwica(12003, _POMIAR_FULL_1005)   # AR-53 (d)
# KOTWICA NAWROTU P-D (D-PD-10): lighty, których nagłówek MILCZY o obiekcie. `delta_report` był na
# nie ślepy (mianownik wymaga `object_raw NOT NULL`), więc §5.7 świeciło zielono o klatkach, których
# nie widzi. Kotwica jest STAGE-AWARE i to nie jest ozdoba: w IMPORT baza powstaje z ZAMROŻONEGO
# dawcy, którego zeznanie dla tych plików nadal nie ma karty `OBJECT`, więc jedna liczba dla obu
# trybów świeciłaby na czerwono przy POPRAWNYM przebiegu. Zadaniem kotwicy jest wykrywać ZMIANĘ
# (nowa dostawa bez `OBJECT`), a nie być równa 25: liczba porusza się razem z `regions.json` —
# dawca niesie 108 lightów bez karty, z czego region rozwiązuje 83.
EXP_NAMELESS_IMPORT = Kotwica(25, _POMIAR_IMPORT_0801, _POTW_IMPORT_1004)   # ZMIERZONE przebiegiem,
# nie policzone z rachunku: dawca niesie 108 lightów bez karty `OBJECT`, region rozwiązuje 83,
# zostaje 25. Sonda RO dawcy 2026-10-03 potwierdza: te same 25, wszystkie w podgrupie
# późno-naprawianej (`import_fitsmirror._late_repaired`, 6605 ścieżek).
#
# AR-49 (wariant O2, 2026-10-03): KOTWICA LICZY ZEZNANIE DAWCY, NIE STAN BAZY. Baza importu NIE jest
# w całości zeznaniem dawcy: gdy falsyfikator trafi w późno-naprawiany plik o faktach kopii
# zmienionych na dysku, CAŁA podgrupa późno-naprawiana wchodzi zeznaniem DYSKU (`Preflight.recompute`).
# Po wsadzie kart `OBJECT` na `R:` (7412 plików) celowana część próbki (`NGC3034 RC8 Ha`) miała
# zmienione fakty kopii, podgrupa przeliczyła się z dysku, a 25 klatek dostało nazwę z karty - stan
# bazy dał 0 IDENTYCZNIE kodem `e45a3c4` i `cf1911d`. Przy częściowo przepisanym `R:` wynik
# zależałby dodatkowo od ZIARNA: każdy z 5 losowych plików trafia w podgrupę z szansą ~42%
# (6605 z 15 559). Stąd `nameless_split`: lighty spoza podgrupy liczone ze stanu (ich zeznaniem JEST
# dawca), lighty podgrupy - z zeznania dawcy (`import_fitsmirror.donor_header`) tym samym kryterium
# co resolver dla klatki bez `object_raw` (region po współrzędnych). Kotwica łapie zmianę W DAWCY
# niezależnie od stanu `R:` i od ziarna; podgrupa przeliczona dostaje OSOBNĄ, raportowaną liczbę
# (bez kotwicy - jej wartość zależy od tego, czy przeliczenie w ogóle zaszło, i od stanu dysku).
EXP_NAMELESS_FULL = Kotwica(25, _POMIAR_FULL_0801, _POTW_FULL_1004)   # ZMIERZONE po pilocie P-D.
# **Przesłanka briefu §6 pkt 9 („po naprawie padnie na 0")
# OKAZAŁA SIĘ FAŁSZYWA i to jest tu udokumentowane, żeby nikt nie „poprawił" tej liczby z powrotem
# na 0:** baza akceptacji bierze `mtime` ze STANU NA DYSKU, ale zeznanie FITS (nagłówek, `file_sha1`,
# `header_hash`) z ZAMROŻONEGO dawcy — więc brama przyrostowa doskanu widzi `mtime` równy i pomija
# plik. Dowód: lokacja 4581 ma w bazie akceptacji `mtime` PO naprawie i `file_sha1` SPRZED niej,
# a jej dziennik nie zawiera ani jednego `location.refreshed` (same trzy zdarzenia `import:fitsmirror`).
# Doskan nie widzi więc naprawy na `R:`; widzi ją wyłącznie podgrupa przeliczona w imporcie - i tę
# kotwica od AR-49 liczy zeznaniem dawcy, jak w IMPORT. FULL = te same 25 z dawcy + lighty
# wciągnięte doskanem bez nazwy (dziś 0; ta część stoi na ŻYWYM drzewie, jak tor RAW). Zadaniem obu
# kotwic jest łapać ZMIANĘ W DAWCY; nawrotu na ŻYWEJ bazie pilnuje `object_nameless` w raporcie
# dostawy (inna rola - patrz §6 pkt 9 briefu).
EXP_NAMELESS_RAW_FULL = Kotwica(756, _POMIAR_RAW_0804)   # lighty w formacie bez karty `OBJECT`
# (`resolver.NO_OBJECT_CARD_FILETYPES`). Zmierzone: KAŻDY RAW-light jest bez `object_raw`, ZERO
# wyjątków - EXIF nie zna tego pola. Osobna kotwica, bo osobna droga naprawy (ręka, nie karta);
# zlanie z 25 sprawiło, że liczba nie pilnowała ANI populacji astro, ANI DSLR.
# Było 763 - nota C3 przy EXP_CONFIG_REVIEW_RAW_FULL (te same 7 klatek).
#
# TRZECI GENERATOR RUCHU KOTWIC `EXP_NAMELESS_*` (G2-8d) - obok zmiany w dawcy i dostawy na żywym
# drzewie: WYCOFANIE klatki ręką (`frame.retired_at`, D-OW-3/R2). Predykat bezimiennych
# (`gui.queries.nameless_frames`, za nim `nameless_split`) odsiewa wycofane, więc każde wycofanie
# lightu bez nazwy zbija kubełek o 1. Na świeżej bazie z dawcy populacja wycofanych jest ZEROWA
# (gest robi człowiek w GUI, skrypt nie; `--live-db` przenosi WYŁĄCZNIE rejestr napraw,
# `read_repaired_registry`), więc w tym skrypcie generator nie działa wprost - rusza liczbę tam,
# gdzie wycofania żyją: w raporcie dostawy na żywej bazie. Do akceptacji dociera pośrednio, gdy
# wycofanie idzie w parze z kasacją pliku na dysku (wzór: nota C3, import pomija plik nieobecny).
# Protokół: kotwica rusza się o N - nowy `Pomiar` z „-N wycofanych/skasowanych" w `stan_r`,
# nigdy ciche podbicie liczby.

# ── ETAP STOSÓW (I-2b, P-I) — RE-BASELINE JAWNY, nie skutek uboczny ──────────────────────────────
# Wciągnięcie gotowych obrazów po integracji RUSZA kotwice liczone po CAŁEJ bazie (brief §0 fakt 24)
# i to było wiadome PRZED napisaniem linii kodu: `EXP_XISF_KINDS` porównuje słownik kindów ŚCISŁĄ
# równością, więc nowy klucz `master_light` to FAIL, a nie „prawie zielono". Stąd osobny zestaw
# kotwic zamiast podbicia starych: **etap FULL ma dalej pilnować archiwum**, a stosy własnych liczb.
# Kotwica populacji = **128 PLIKÓW** (D-P-I-6: każdy plik to własna klatka; 85 to liczba INTEGRACJI,
# czyli relacji, i wejdzie dopiero z segmentem I-2c).
#
# AR-53 (O1, decyzja Zdzinia 2026-10-05): stosy wchodzą WYŁĄCZNIE w zakresie `--stacks-root`.
# Od przenosin gotowych obrazów do `<archiwum>\STACKS` (0810) zwykły skan archiwum je widzi
# (E4-1 wariant A+), więc przebieg FULL 2026-10-04 wciągnął 193 stosy doskanem i zaczerwienił
# kotwice archiwum. Doskan tego skryptu odcina dziś `STACKS` (`korzenie_doskanu`), żeby kotwice
# FULL znaczyły „archiwum"; kotwice tego bloku zmierzono na STARYM drzewie obróbki (128 plików),
# a 2026-10-06 ponownie na `<archiwum>\STACKS` (193 pliki) - komentarze z liczbami 128/18/81
# niżej opisują tamten, pierwszy pomiar.
#
# Zmiana DROGI etapu (2026-10-06): dawna droga „Stosy" (`scan_stacks`) szukała nazw `masterLight…`,
# a pod `<archiwum>\STACKS` leżą dziś nazwy kanoniczne - przebieg dał 0 kandydatów. Etap idzie
# drogą produktu: zwykły `scan_tree` korzenia archiwum po doskanie (archiwum przeskakuje brama
# `mtime`), sito `is_derived_name` pod `STACKS`, rodzaj z `IMAGETYP`. Znaczenia kotwic poniżej:
# kandydaci = pliki pod `STACKS` po sicie, pochodne = odsiane sitem, wciągnięte = nowe klatki
# `master_light`, odrzucone = pliki pod `STACKS` bez rodzaju stosu, nieczytelne albo bez lokacji.
# Zmierzone 2026-10-06: 193 pliki, 0 pochodnych (pochodne obróbki nie leżą już pod `STACKS`),
# 193 stosy, 0 odrzuconych.
EXP_STACKS_CANDIDATES = Kotwica(193, _POMIAR_STOSY_1006)
# …i tyle plików odsiało sito pochodnych (dawna droga: 259 nazw `masterLight…` razem)
EXP_STACKS_DERIVED = Kotwica(0, _POMIAR_STOSY_1006)
# 128/128 zeznało `master_light` - nic nie wypada z rodzaju stosu
EXP_STACKS_INGESTED = Kotwica(193, _POMIAR_STOSY_1006)
# …i ma tak zostać: >0 znaczy, że pod `STACKS` leży coś, co nie jest stosem
EXP_STACKS_REJECTED = Kotwica(0, _POMIAR_STOSY_1006)
# Kotwice STANU po etapie stosów — te same pytania co w FULL, ale na trzecim zakresie. `None` =
# NIEZMIERZONA: skrypt wypisze aktualia i poprosi o zaszycie (ten sam protokół, co `EXP_NAMELESS_*`
# przed pilotem P-D). Nigdy nie wpisuj tu liczby z rachunku „FULL + 128" — kotwica ma być
# ZMIERZONA, bo stack przechodzi przez grouper i resolver jak każda klatka i jego skutki nie są
# dodawaniem. Słownik kindów wypisany WPROST (do AR-53 `dict(EXP_XISF_KINDS, master_light=…)`):
# ponowny pomiar kotwicy FULL nie może po cichu przestawić kotwicy, której nikt nie mierzył.
EXP_XISF_KINDS_STACKS = Kotwica(
    {"flat": 11, "light": 228, "master_dark": 38, "master_flat": 74, "unknown": 1,
     "master_light": 193}, _POMIAR_STOSY_1006)
# Zmierzone, nie policzone z rachunku. (Konkretny korzeń starego drzewa obróbki trzyma kolejka
# sesji - poza gitem; tu liczy się TRYB pomiaru.)
# 12 z FULL + DWIE etykiety, które żyją WYŁĄCZNIE w drzewie obróbki:
# `ED` (4 klatki) — etykieta ZDJĘTA z archiwum writebackiem P6 (2026-07-22), ale pliki po integracji
# noszą ją dalej, bo powstały przed naprawą i nikt ich nie przepisywał; oraz `EQMOD HEQ5/6` (4) —
# nazwa MONTAŻU wpisana przez program akwizycji w kartę `TELESCOP`. Obie to FAKT archiwum obróbki,
# nie śmieć do wyczyszczenia — szum modelu naprawia się kind-scopingiem, nigdy kasowaniem pól.
# `EQMOD HEQ5/6` czeka na decyzję kuratelską (park/merge) — patrz kolejka.
EXP_TELESCOPES_STACKS = Kotwica(16, _POMIAR_STOSY_1006)   # 14 z FULL + dwie etykiety stosów
# gotowe stosy bez karty `OBJECT` i bez obiektu (własny kubełek, D-P-I-5). Plików bez karty było
# 22 - cztery rozwiązał REGION po współrzędnych, więc z kubełka wypadły. KLUCZOWY DOWÓD
# ROZDZIAŁU: `EXP_NAMELESS_FULL` (25) po dołożeniu 18 stosów NIE DRGNĘŁO.
# AR-53: 0 - stosy pod `STACKS` niosą dziś kartę `OBJECT` (wsad kart, ruch zapowiedziany niżej).
EXP_NAMELESS_STACKS = Kotwica(0, _POMIAR_STOSY_1006)
#
# ⚠️ KOTWICE STOSÓW SĄ RUCHOME INACZEJ NIŻ RESZTA (D-0802-1 + P6d, 2026-08-02). Stosy przychodzą
# z ŻYWEGO skanu drzewa obróbki, a writeback od D-0802-1 ich SIĘGA - więc pierwsza naprawa kart
# `OBJECT` w drzewie stosów ZBIJE tę liczbę i bramka zaświeci czerwono ZGODNIE Z PRAWDĄ. To NIE
# jest regresja: wtedy nowy `Pomiar` z liczbą plików, które dostały kartę. Ta sama uwaga dotyczy
# `EXP_CONFIG_REVIEW_STACKS` (stosy bez `TELESCOP`).
# POPRAWKA AR-53 do dawnego zdania „kotwice FULL stoją na ZAMROŻONYM dawcy, więc naprawa plików
# na `R:` ich nie rusza": prawdziwe WYŁĄCZNIE dla klatek, które import bierze z zeznania dawcy.
# Podgrupa przeliczona z dysku (`Preflight.recompute`, patrz AR-49 wyżej) i wszystko, co wnosi
# doskan (XISF, RAW), stoi na stanie `R:` - te kotwice ruszają się od wsadów, renamów i kasacji
# na dysku tak samo jak stosy. Dlatego każda kotwica niesie `Pomiar` ze stanem archiwum.
# 274 z FULL + 128 stosów. PixInsight NIE przenosi `SITELAT`/`SITELONG` do produktu integracji
# - zmierzone 0/128, więc CAŁA populacja stosów jest poza osią obserwatorium.
EXP_NO_GPS_STACKS = Kotwica(467, _POMIAR_STOSY_1006)   # AR-53: 274 z FULL + 193 stosy
# ── Kotwice RODOWODU STOSÓW (I-2c, faza (U)) — ZMIERZONE przebiegiem 2026-08-02 ──────────────────
# Ostrożność, która okazała się niepotrzebna, ale zostaje zapisana: nie wolno było przepisać liczb
# z sondy na kopii ŻYWEJ pf4, bo baza akceptacji stoi na ZAMROŻONYM dawcy i zna inne nazwy obiektów
# niż archiwum po naprawach writebacku („Mur"/„Snapshot" zamiast NGC7000/IC1795), a oś obiektu jest
# WARUNKIEM doboru okna. Pomiar dał liczby IDENTYCZNE z sondą (81/3367/6) — bo żaden stos nie celuje
# w obiekt, którego nazwę naprawiano. To ZBIEG OKOLICZNOŚCI tych danych, nie reguła: pierwszy stos
# NGC7000 rozjedzie te dwa światy i wtedy ta kotwica ma zaświecić, a nie zostać „poprawiona".
# integracje z co najmniej jednym wejściem (z 128 stosów)
EXP_SLIN_LINKED = Kotwica(124, _POMIAR_STOSY_1006)   # AR-53: ze 193 stosów
EXP_SLIN_INPUTS = Kotwica(5742, _POMIAR_STOSY_1006)   # wierszy `integration_input`
# …z tego DOWIEDZIONE zeznaniem pliku; 75 to KANDYDACI z okna.
EXP_SLIN_HISTORY = Kotwica(27, _POMIAR_STOSY_1006)   # AR-53: reszta (97) to kandydaci z okna
# Reszta populacji to trzy rozłączne kubełki „nie wiem": okno zdegenerowane 24, brak obiektu 18,
# okno puste 5 (81 + 47 == 128 — partycję pilnuje osobne kryterium, nie te trzy liczby).
# ⚠️ Te kotwice są RUCHOME tak samo jak `EXP_NAMELESS_STACKS`: stoją na ŻYWYM skanie drzewa obróbki,
# a nie na zamrożonym dawcy. Naprawa karty `OBJECT` w stosie przesunie 18 → mniej i podniesie
# `linked`; przeniesienie stosów do `R:\ASTRO_\STACKS` zmieni ścieżki, ale nie liczby (tożsamość
# integracji to KLATKA, nie ścieżka). Zmiana = zmierz i podbij z notą, nigdy „napraw do zera".
# 1 z FULL (`unknown` masterflat A7R3) + 7 stosów bez `TELESCOP`. Siedem plików po integracji nie
# niesie karty teleskopu, więc nie ma z czego powołać osi - stan UCZCIWY, dokładnie jak RAW-y obok.
EXP_CONFIG_REVIEW_STACKS = Kotwica(1, _POMIAR_STOSY_1006)   # AR-53: stosy niosą dziś `TELESCOP`
# KAMERY BEZ WŁASNEJ KOTWICY — i to jest wynik DECYZJI, nie przeoczenie. Pierwszy przebieg pokazał
# 2 kamery z `pixel_conflict` i `SONYA7S`, która dostała piksel od stacku: `_drizzle_2x` zapisuje
# `XPIXSZ=1.88` przy matrycy 3.76 (siatka wynikowa, nie sprzęt), a korpusy Sony podają w produkcie
# integracji `5.4` przy 4.86 archiwum. Rozstrzygnięcie Zdzinia 2026-08-02: **oś podziału masterów po
# pikselu jest niepotrzebna — liczy się, JAKĄ KAMERĄ robione.** Stąd `cameras.NO_PIXEL_KINDS`:
# stack powołuje kamerę, ale nie wnosi `XPIXSZ`. Skutek: kotwice §5.3 zostają WSPÓLNE dla FULL
# i STOSÓW (te same 8 kamer, `pixel_conflict == 0`), bo rozjazd przestał istnieć u ŹRÓDŁA zamiast
# być zaszyty w bramce jako „dwa znane wyjątki".


def _ok(cond):
    return "PASS" if cond else "FAIL"


# ── (I) IMPORT: dawca LIVE → świeża baza przez realny pipeline PF-3 ───────────────────────────────
def build_import(donor_path, work_path, now, out, live_db=None):
    """Zbuduj świeżą horreum.db z dawcy LIVE przez `run_import` (jedna klinga; §4.6 gate'y w środku).
    Dawca RO (`open_donor`). Zwraca (con, ImportSummary, zeznanie dawcy podgrupy przeliczonej -
    `donor_object_testimony`). Twarde złamanie → ImportAbort propaguje.

    `live_db` (opcja `--live-db`) = ŻYWA baza Horreum, z której bierzemy rejestr napraw
    (D-0722-2 wariant A). Bez niego falsyfikator czyta pliki naprawione przez Horreum jako
    „dawca stęchły z nieznanego powodu" i abortuje, gdy losowa próbka w nie trafi."""
    if os.path.exists(work_path):
        os.remove(work_path)
    out(f"== (I) IMPORT: {donor_path} -> {work_path} ==")
    repaired = None
    if live_db:
        repaired = read_repaired_registry(live_db)
        out(f"  rejestr napraw Horreum: {len(repaired)} sciezek z {live_db}")
    donor = open_donor(donor_path)
    try:
        con = db.open_db(work_path)
        con.execute("PRAGMA synchronous=OFF")          # baza JEDNORAZOWA — wolno przyspieszyć
        summary = run_import(donor, con, now=now, repaired_paths=repaired)
        testimony = donor_object_testimony(donor, summary.preflight.recompute)
    finally:
        donor.close()
    pf = summary.preflight
    out(f"  pre-flight: root {pf.root} volume {pf.volume}; dawca {pf.files_total} plikow; "
        f"nadwyzka dysku {pf.surplus}; falsyfikator OK ({len(pf.verified)} plikow)")
    for note in pf.notes:
        out(f"    {note}")
    out(f"  import: {summary.imported}/{summary.files_total} "
        f"(skipped {summary.skipped}, przeliczone z dysku {summary.recomputed})")
    out(f"  grouper: {summary.group}")
    out(f"  resolver: {summary.resolve}")
    out(f"  bramki §4.6: {'WSZYSTKIE PASS' if not summary.gate_failures else summary.gate_failures}")
    return con, summary, testimony


# ── §5.7b: kotwica nawrotu P-D na ZEZNANIU DAWCY (AR-49, wariant O2) ─────────────────────────────
def donor_object_testimony(donor, paths):
    """Zeznanie DAWCY o obiekcie dla ścieżek podgrupy przeliczonej z dysku: `{path: (object_raw,
    ra_deg, dec_deg)}`, pola gorące tą samą derywacją co `header` w bazie (`extract_header` na
    syntezie `donor_header`). Czytane, dopóki dawca jest otwarty - po imporcie baza o tych plikach
    zna już tylko zeznanie dysku. Ścieżka spoza dawcy = złamany kontrakt `preflight` (EXPECT)."""
    out = {}
    for path in sorted(paths):
        header = donor_header(donor, path)
        if header is None:
            raise RuntimeError(f"podgrupa przeliczona poza dawca: {path} - kontrakt preflight zlamany")
        hot = extract_header(header)
        out[path] = (hot["object_raw"], hot["ra_deg"], hot["dec_deg"])
    return out


@dataclass
class NamelessSplit:
    """Lighty bez nazwy rozdzielone wg ŹRÓDŁA zeznania. `anchor` = `outside` + `recomputed_donor`."""
    anchor: int = 0             # bez nazwy wg zeznania dawcy (FULL: + wciągnięte doskanem)
    outside: int = 0            # bez nazwy wśród klatek bez kopii przeliczonej (stan bazy)
    recomputed_lights: int = 0  # lighty (w predykacie formatu) z kopią przeliczoną z dysku
    recomputed_donor: int = 0   # …z nich bez nazwy wg zeznania DAWCY
    recomputed_disk: int = 0    # …z nich bez nazwy wg zeznania DYSKU (stan bazy)
    mismatch: list = field(default_factory=list)   # frame_id: werdykt dawcy != potoku przy tym samym zeznaniu


def nameless_split(con, testimony):
    """Policz kotwicę §5.7b na zeznaniu DAWCY, niezależnie od tego, czy i co przeliczono z dysku.

    Klatka bez kopii przeliczonej ma w bazie zeznanie dawcy (albo doskanu w FULL), więc o niej
    rozstrzyga stan: `gui.queries.nameless_frames` (oba człony - ten sam predykat co
    `resolver.nameless_lights`). Klatka z kopią przeliczoną ma w bazie zeznanie DYSKU, więc o niej
    rozstrzyga zeznanie dawcy: bez `object_raw` i bez regionu po współrzędnych = bez nazwy. To jest
    całe kryterium resolvera dla takiej klatki - drabina nazw milczy przy braku nazwy, alias też,
    a na świeżej bazie nie ma źródeł ręki. Zakres formatu/rodzaju/zastąpienia bierzemy ze stanu
    (te fakty wsad kart nie zmienia), żeby nie budować drugiej derywacji rodzaju klatki.

    `mismatch` pinuje tę derywację do potoku: tam, gdzie zeznanie dysku o obiekcie i współrzędnych
    jest RÓWNE zeznaniu dawcy, werdykt dawcy musi być werdyktem bazy. Rozjazd = derywacja tu
    odjechała od resolvera i kotwica przestała mierzyć to, co mierzy stan."""
    s = NamelessSplit()
    nameless = {r["frame_id"] for r in nameless_frames(con)}
    nameless |= {r["frame_id"] for r in nameless_frames(con, cleared=True)}
    skip = frozenset(NO_OBJECT_CARD_FILETYPES)
    recomputed = {}                                 # frame_id -> (wiersz, ścieżka przeliczona)
    for r in con.execute(
            "SELECT f.id AS fid, f.kind, f.filetype, f.superseded_by, f.retired_at, "
            "h.frame_id AS hid, h.object_raw, h.ra_deg, h.dec_deg, l.path "
            "FROM location l JOIN frame f ON f.id = l.frame_id "
            "LEFT JOIN header h ON h.frame_id = f.id ORDER BY l.path"):
        if r["path"] in testimony:
            recomputed.setdefault(r["fid"], r)
    s.outside = len(nameless - set(recomputed))
    for fid, r in recomputed.items():
        if (r["kind"] != "light" or (r["filetype"] or "") in skip or r["hid"] is None
                or r["superseded_by"] is not None or r["retired_at"] is not None):
            continue
        s.recomputed_lights += 1
        obj, ra, dec = testimony[r["path"]]
        donor_nameless = obj is None and resolve_region(ra, dec) is None
        s.recomputed_donor += donor_nameless
        s.recomputed_disk += fid in nameless
        if (obj, ra, dec) == (r["object_raw"], r["ra_deg"], r["dec_deg"]) \
                and donor_nameless != (fid in nameless):
            s.mismatch.append(fid)
    s.anchor = s.outside + s.recomputed_donor
    return s


# ── (X) XISF-DOSKAN: realny scan_tree po drzewie z XISF (odtwarza PF-4) ──────────────────────────
def korzenie_doskanu(root):
    """O1 (AR-53): doskan archiwum BEZ poddrzewa `STACKS` - stosy wchodzą wyłącznie w zakresie
    `--stacks-root`, więc kotwice FULL znaczą „archiwum". Zwraca `(korzenie, odcięte, robocze)`:
    podkatalogi korzenia do osobnych przebiegów `scan_tree`, odcięte ścieżki `STACKS` i pominięte
    drzewa robocze górnego poziomu (te skan korzenia liczy w `dirs_excluded`, więc wołający
    dolicza je do tej samej telemetrii).

    PO STRONIE SKRYPTU, nie parametrem produktu: zwykły skan ma wciągać `STACKS` (E4-1 wariant
    A+) i to zostaje nietknięte. Skan po podkatalogach jest równoważny skanowi korzenia pod
    trzema warunkami, a każdy pilnujemy wprost (EXPECT, nie cicha różnica zakresu):
      * pod samym korzeniem nie leży plik nagłówkonośny - przebieg po podkatalogach by go pominął;
      * żaden podkatalog nie ma własnego `STACKS` - `scan_tree` z korzeniem w podkatalogu
        nałożyłby tam sito pochodnych, którego skan korzenia tam nie stosuje;
      * drzewa robocze (`EXCLUDED_DIR_NAMES`) pomijamy tak, jak odcina je skan korzenia.
    Kolejność podkatalogów = kolejność `Path` (jak `_iter_suffixes`), więc pierwszy odczyt
    kopii o sprzecznym zeznaniu wygrywa tak samo jak w skanie korzenia (§5.11, `frame 15645`).

    DOWIĄZANIA jak w `os.walk(followlinks=False)`, którym idzie skan korzenia: do dowiązania
    symbolicznego katalogu nie schodzi (`os.path.islink`), do JUNCTION schodzi (junction nie jest
    symlinkiem), a dowiązanie do pliku czyta jak plik. Stąd: symlink katalogu pomijamy, junction
    jest zwykłym podkatalogiem, `is_dir()` z podążaniem rozstrzyga tylko „katalog czy plik".
    Nieczytelny podkatalog górnego poziomu przerywa przebieg wyjątkiem z `os.scandir` (EXPECT) -
    skan korzenia pominąłby go po cichu (`onerror`), a bramka liczyłaby wtedy niepełne archiwum."""
    root = canonize_root(root)
    korzenie, odciete, robocze = [], [], []
    with os.scandir(root) as it:
        wpisy = sorted(it, key=lambda e: Path(e.path))
    for e in wpisy:
        nazwa = e.name.lower()
        if not e.is_dir():
            if os.path.splitext(nazwa)[1] in HEADER_SUFFIXES:
                raise RuntimeError(f"plik nagłówkonośny wprost pod korzeniem doskanu: {e.path} - "
                                   "doskan po podkatalogach by go pominął")
            continue
        if nazwa == STACKS_DIR:
            odciete.append(e.path)
            continue
        if nazwa in EXCLUDED_DIR_NAMES:
            robocze.append(e.path)
            continue
        if e.is_symlink():                          # `os.walk` korzenia tu nie schodzi
            continue
        with os.scandir(e.path) as sub:
            if any(s.is_dir() and not s.is_symlink() and s.name.lower() == STACKS_DIR
                   for s in sub):
                raise RuntimeError(f"podkatalog `{STACKS_DIR}` poza korzeniem doskanu: {e.path} - "
                                   "skan po podkatalogach nałożyłby tam sito pochodnych")
        korzenie.append(e.path)
    return korzenie, odciete, robocze


def doskan_xisf(con, xisf_root, now, out):
    """Po imporcie dołóż XISF realnym skanem (jak PF-4). FITS gate'owane mtime (skip), XISF wciągane;
    potem grouper+resolver. Volume z `volume_serial` (brama musi trafiać znane FITS).
    `STACKS` pod korzeniem jest ODCINANY (O1, `korzenie_doskanu`)."""
    out("")
    out(f"== (X) XISF-DOSKAN: scan_tree {xisf_root} (bez {STACKS_DIR.upper()}) ==")
    root = canonize_root(xisf_root)
    volume = volume_serial(root)
    if volume is None:
        raise RuntimeError(f"volume_serial({root!r}) nieustalony — zamontuj wolumin XISF-roota")
    korzenie, odciete, robocze = korzenie_doskanu(root)
    for p in odciete:
        out(f"  poza doskanem (O1, stosy tylko przez --stacks-root): {p}")
    for p in robocze:
        out(f"  poza doskanem (drzewo robocze): {p}")
    files = frames_new = skipped = frame_review = 0
    dirs_excluded = len(robocze)                    # górny poziom - skan korzenia też by je liczył
    for korzen in korzenie:
        s = scan_tree(con, korzen, volume=volume,
                      drive_letter=(os.path.splitdrive(root)[0] or None), tier=None, now=now)
        files += s.files
        frames_new += s.frames_new
        skipped += s.skipped
        frame_review += s.frame_review
        dirs_excluded += s.dirs_excluded
    out(f"  scan ({len(korzenie)} poddrzew): files={files} frames_new={frames_new} "
        f"skipped(mtime)={skipped} frame_review={frame_review} dirs_excluded={dirs_excluded}")
    gs = run_grouper(con, now=now)
    rs = run_resolver(con, now=now)
    out(f"  grouper: {gs}")
    out(f"  resolver: {rs}")


# ── (T) STOSY: zwykły `scan_tree` korzenia archiwum - droga produktu (E4-1 wariant A+) ──────────
@dataclass
class EtapStosow:
    """Zeznanie etapu (T) dla kryteriów §5.13 - liczby wyłącznie z poddrzewa `STACKS`."""
    pod_stacks: int = 0        # pliki nagłówkonośne pod `STACKS` widziane przez przejście
    candidates: int = 0        # pod `STACKS` po sicie pochodnych
    derived_skipped: int = 0   # odsiane sitem `is_derived_name`
    derived_paths: list = field(default_factory=list)
    skipped: int = 0           # pominięte bramą przyrostową (`mtime`)
    ingested: int = 0          # NOWE klatki rodzaju `STACK_KIND`
    rejected: int = 0          # lokacje pod `STACKS`, których klatka nie ma rodzaju stosu
    rejected_paths: list = field(default_factory=list)
    failed: int = 0            # nieczytelne (marker) + widziane bez lokacji (backstop, izolacja)
    failed_paths: list = field(default_factory=list)
    incomplete: bool = False   # przejście nie zobaczyło całego drzewa (`ScanSummary.incomplete`)


def _pod(path, prefix):
    """`path` pod `prefix` bez wielkości liter (NTFS) - ta sama reguła, co sito w `scan_tree`."""
    return path.casefold().startswith(prefix.casefold())


def doskan_stacks(con, xisf_root, stacks_root, now, out):
    """Po doskanie archiwum dołóż GOTOWE OBRAZY drogą produktu: zwykły `scan_tree` KORZENIA
    archiwum, potem grouper+resolver (stack jest na osi teleskopu i na osi obiektu -
    `master_light` to kind pełnoprawny, nie wyjątek). Pliki archiwum przeskakuje brama przyrostowa
    (doskan już je zna), więc wchodzi wyłącznie `STACKS` - z sitem pochodnych, które `scan_tree`
    nakłada tylko na `STACKS` bezpośrednio pod korzeniem skanu (`_stacks_prefix`). Rodzaj klatki
    daje zeznanie `IMAGETYP`, jak każdej innej; dawna droga „Stosy" (`scan_stacks`) szukała nazw
    `masterLight…`, a pliki pod `STACKS` noszą dziś nazwy kanoniczne.

    EXPECT, nie cichy rozjazd zakresu: `stacks_root` musi być `<xisf_root>\\STACKS` (inny korzeń
    przesunąłby sito i kotwice mierzyłyby inną populację), a każda lokacja i klatka dodana w tym
    etapie musi leżeć pod `STACKS` - coś spoza znaczy, że archiwum zmieniło się po doskanie.

    Zwraca `(EtapStosow, idempotent)`. Kryteria czytają ZEZNANIE etapu niezależnie od liczb STANU
    bazy - dwaj świadkowie tej samej populacji: gdyby etap wciągnął 128 plików, a w bazie było ich
    127, rozjazd wyszedłby natychmiast.

    DRUGI PRZEBIEG jest BRAMKĄ, nie ozdobą (wzorzec (K)/(L)): zero nowych klatek i ANI JEDNEGO
    eventu. Bez tego dowodu wciąganie stosów przy każdej dostawie mnożyłoby lokacje, a idempotencja
    byłaby obietnicą z docstringa."""
    out("")
    root = canonize_root(xisf_root)
    stacks = canonize_root(stacks_root)
    if stacks.casefold() != os.path.join(root, STACKS_DIR).casefold():
        raise RuntimeError(f"--stacks-root {stacks!r} to nie <xisf-root>\\{STACKS_DIR.upper()} "
                           f"({root!r}) - zwykły skan nakłada sito pochodnych tylko tam")
    out(f"== (T) STOSY: scan_tree {root} (wchodzi wyłącznie {stacks}) ==")
    volume = volume_serial(root)
    if volume is None:
        raise RuntimeError(f"volume_serial({root!r}) nieustalony - zamontuj wolumin archiwum")
    prefix = stacks + os.sep
    widziane = []
    brama = {"przed": 0, "stacks": 0}

    # `progress` woła się po KAŻDYM pliku przejścia z licznikami już doliczonymi, więc przyrost
    # `skipped` przy ścieżce pod `STACKS` to pominięcie bramą właśnie tego pliku.
    def _przejscie(_i, _total, spath, summ):
        if _pod(spath, prefix):
            widziane.append(spath)
            brama["stacks"] += summ.skipped - brama["przed"]
        brama["przed"] = summ.skipped

    def _skan(progress=None):
        return scan_tree(con, root, volume=volume, drive_letter=(os.path.splitdrive(root)[0] or None),
                         tier=None, now=now, progress=progress)

    max_frame = con.execute("SELECT coalesce(max(id), 0) FROM frame").fetchone()[0]
    max_loc = con.execute("SELECT coalesce(max(id), 0) FROM location").fetchone()[0]
    s = _skan(_przejscie)
    poza = [r["path"] for r in con.execute("SELECT path FROM location WHERE id > ?", (max_loc,))
            if not _pod(r["path"], prefix)]
    if poza:
        raise RuntimeError(f"etap stosów dodał {len(poza)} lokacji spoza {stacks}, np. {poza[0]} - "
                           "archiwum zmieniło się po doskanie")
    # Podmiana treści pliku archiwum pod znaną ścieżką nie daje nowej lokacji: skan przepina starą
    # na nową klatkę (`location.rebound`). Bez tego guardu złapałby ją dopiero `bez_lokacji` niżej -
    # z komunikatem, który wskazuje `STACKS` zamiast pliku, który się zmienił.
    przepiete = [r["path"] for r in con.execute(
        "SELECT path FROM location WHERE id <= ? AND frame_id > ?", (max_loc, max_frame))]
    if przepiete:
        raise RuntimeError(f"etap stosów przepiął {len(przepiete)} znanych lokacji na nowe klatki, "
                           f"np. {przepiete[0]} - treść archiwum zmieniła się po doskanie")
    bez_lokacji = con.execute(
        "SELECT count(*) FROM frame f WHERE f.id > ? AND NOT EXISTS "
        "(SELECT 1 FROM location l WHERE l.frame_id = f.id AND l.id > ?)",
        (max_frame, max_loc)).fetchone()[0]
    if bez_lokacji:
        raise RuntimeError(f"etap stosów dodał {bez_lokacji} klatek bez nowej lokacji pod {stacks}")

    e = EtapStosow(pod_stacks=len(widziane), derived_skipped=s.derived_skipped,
                   derived_paths=list(s.derived_paths), incomplete=s.incomplete)
    e.candidates = e.pod_stacks - e.derived_skipped
    e.ingested = con.execute("SELECT count(*) FROM frame WHERE id > ? AND kind = ?",
                             (max_frame, STACK_KIND)).fetchone()[0]
    lok = [r for r in con.execute(
        "SELECT l.path, l.unreadable_since, l.unreadable_reason, f.kind FROM location l "
        "JOIN frame f ON f.id = l.frame_id WHERE l.volume = ? AND l.present = 1 ORDER BY l.path",
        (volume,)) if _pod(r["path"], prefix)]
    for r in lok:
        if r["unreadable_since"] is not None:
            e.failed_paths.append(f"{r['path']}: {r['unreadable_reason']}")
        elif r["kind"] != STACK_KIND:
            e.rejected_paths.append(f"{r['path']}: rodzaj '{r['kind']}', nie {STACK_KIND}")
    e.rejected = len(e.rejected_paths)
    znane = {r["path"].casefold() for r in lok} | {p.casefold() for p in e.derived_paths}
    e.failed_paths += [f"{p}: brak lokacji po przejściu" for p in widziane
                       if p.casefold() not in znane]
    e.failed = len(e.failed_paths)
    e.skipped = brama["stacks"]
    out(f"  pod STACKS: pliki={e.pod_stacks} kandydaci={e.candidates} wciagniete={e.ingested} "
        f"odsiane_sitem={e.derived_skipped} pominiete(mtime)={e.skipped} odrzucone={e.rejected} "
        f"bledy={e.failed}")
    out(f"  scan_tree calosc: files={s.files} frames_new={s.frames_new} skipped(mtime)={s.skipped} "
        f"frame_review={s.frame_review} niekompletny={s.incomplete}")
    for p in e.derived_paths[:5]:
        out(f"    ODSIANE {p}")
    for p in e.rejected_paths[:5]:
        out(f"    ODRZUCONE {p}")
    for p in e.failed_paths[:5]:
        out(f"    BLAD {p}")

    przed_ev = con.execute("SELECT count(*) FROM event").fetchone()[0]
    przed_fr = con.execute("SELECT count(*) FROM frame").fetchone()[0]
    s2 = _skan()
    po_ev = con.execute("SELECT count(*) FROM event").fetchone()[0]
    po_fr = con.execute("SELECT count(*) FROM frame").fetchone()[0]
    idem = (s2.frames_new == 0 and s2.locations_new == 0 and po_fr == przed_fr and po_ev == przed_ev)
    out(f"  przebieg 2 (idempotencja): frames_new={s2.frames_new} locations_new={s2.locations_new} "
        f"skipped(mtime)={s2.skipped}/{s2.files}; klatki {przed_fr}=={po_fr}; eventy {przed_ev}=={po_ev}")
    gs = run_grouper(con, now=now)
    rs = run_resolver(con, now=now)
    out(f"  grouper: {gs}")
    out(f"  resolver: {rs}")
    return e, idem


# ── (K) OŚ KALIBRACJI: przepis + DOWÓD IDEMPOTENCJI (bramka C2) ──────────────────────────────────
_CAL_VERBS = ("calibration_profile.proposed", "calibration_profile.assigned",
              "calibration_profile.unassigned", "calibration.fact")


def calibrate(con, now, out):
    """Oś przepisu na gotowym stanie (PO grouperze i resolverze — przepis flata bierze
    `frame.filter_canon`, który wypełnia dopiero resolver).

    Od P-G (2026-08-01) `run_import` sam kończy łańcuch kalibracją, więc **w trybie IMPORT ten
    przebieg jest już DRUGI** i pokazuje zera delt — to nie regresja, tylko dowód, że fasada
    zrobiła swoje (pinuje to §4.6 w kryteriach). W trybie FULL nadal robi realną robotę: mastery
    XISF przychodzą doskanem PO imporcie. Liczby STANU (`frames`/`incomplete`/`reasons`) są
    przeliczane z bazy przy każdym przebiegu, więc kryteria §5.11 czytają je tak samo w obu trybach.

    Kolejny przebieg jest tu BRAMKĄ, nie ozdobą: liczy się zmiana STANU, więc porównujemy liczniki
    eventów encyjnych sprzed i po. `calibration.review_summary` świadomie POZA porównaniem — to event
    audytowy emitowany bezwarunkowo przy niepustej liście braków (wzorzec `flag_object_review_summary`),
    więc jego powtórzenie nie jest zmianą stanu. Zwraca `(summary, idempotent)`."""
    out("")
    out("== (K) OŚ KALIBRACJI: run_calibration + idempotencja ==")
    s1 = run_calibration(con, now=now)
    out(f"  przebieg po imporcie (FULL: pierwszy dla XISF, IMPORT: już drugi): {s1}")
    przed = {v: con.execute("SELECT count(*) FROM event WHERE verb=?", (v,)).fetchone()[0]
             for v in _CAL_VERBS}
    s2 = run_calibration(con, now=now)
    po = {v: con.execute("SELECT count(*) FROM event WHERE verb=?", (v,)).fetchone()[0]
          for v in _CAL_VERBS}
    idem = (s2.profiles_proposed, s2.profiles_assigned, s2.facts_recorded) == (0, 0, 0) and po == przed
    out(f"  przebieg 2 (idempotencja): {s2}")
    out(f"  eventy encyjne bez zmian: {przed == po} ({przed})")
    return s1, idem


# ── (L) RODOWÓD: light↔master + DOWÓD IDEMPOTENCJI (bramka C4) ─────────────────────────────────────
# Verby rodowodu MUSZĄ tu być (adj. #3): bez nich „zero eventów encyjnych" byłoby ślepe na
# `calibration.linked/.unlinked`. `calibration.lineage_summary` POZA porównaniem — event audytowy.
_LIN_VERBS = ("calibration.linked", "calibration.unlinked")


def lineage(con, now, out):
    """Rodowód na gotowym stanie (PO kalibracji — dopasowuje light do wyłonionych profili).
    Kolejny przebieg jest BRAMKĄ: liczy się zmiana STANU, więc porównujemy liczniki eventów rodowodu
    sprzed i po. Jak w (K): od P-G rodowód liczy już `run_import`, więc w trybie IMPORT to przebieg
    DRUGI — ale `linked`/`reasons`/`lights` są STANEM (przeliczane co przebieg), nie deltą, więc
    kryteria §5.12 czytają je bez zmian. Zwraca `(summary, idempotent)`."""
    out("")
    out("== (L) RODOWÓD: run_lineage + idempotencja ==")
    s1 = run_lineage(con, now=now)
    out(f"  przebieg po imporcie: lighty={s1.lights} linked={s1.linked} luki={s1.reasons}")
    przed = {v: con.execute("SELECT count(*) FROM event WHERE verb=?", (v,)).fetchone()[0]
             for v in _LIN_VERBS}
    rows_przed = con.execute("SELECT count(*) FROM calibration").fetchone()[0]
    s2 = run_lineage(con, now=now)
    po = {v: con.execute("SELECT count(*) FROM event WHERE verb=?", (v,)).fetchone()[0]
          for v in _LIN_VERBS}
    rows_po = con.execute("SELECT count(*) FROM calibration").fetchone()[0]
    idem = not s2.linked_new and po == przed and rows_przed == rows_po
    out(f"  przebieg 2 (idempotencja): linked_new={s2.linked_new} wiersze {rows_przed}=={rows_po}")
    return s1, idem


# ── (U) RODOWÓD STOSÓW: run_stack_lineage + idempotencja (I-2c, P-I) ─────────────────────────────
_SLIN_VERBS = ("integration.recorded", "integration.updated", "integration.linked",
               "integration.unlinked")


def stack_lineage(con, now, out):
    """Rodowód stosów na gotowym stanie (PO (T) i po grouperze/resolverze — dobór stoi na osi
    obiektu i osi teleskopu). Drugi przebieg jest BRAMKĄ jak w (K)/(L): zero nowych relacji, zero
    nowych eventów zapisu, tyle samo wierszy.

    UWAGA NA WYBÓR ŚWIADKA: `integration.lineage_summary` emituje się PRZY KAŻDYM przebiegu (to
    event audytowy o STANIE, jak `review_summary`), więc do dowodu idempotencji bierzemy WYŁĄCZNIE
    czasowniki ZAPISU. Ta sama pułapka co §5.6 — kotwica na `count(event)` mierzy liczbę przebiegów,
    nie liczbę spraw. Zwraca `(summary, idempotent)`."""
    out("")
    out("== (U) RODOWÓD STOSÓW: run_stack_lineage + idempotencja ==")
    s1 = run_stack_lineage(con, now=now)
    out(f"  przebieg 1: stosy={s1.stacks} z_rodowodem={s1.linked} wejsc={s1.inputs} "
        f"zrodla={s1.by_assert} powody={s1.reasons}")
    out(f"    okna nierozlaczne={s1.ambiguous} rozjazd_teleskopu={s1.telescope_mismatch} "
        f"historia_nieodczytana={s1.history_unread}")
    przed = {v: con.execute("SELECT count(*) FROM event WHERE verb=?", (v,)).fetchone()[0]
             for v in _SLIN_VERBS}
    rows_przed = con.execute("SELECT count(*) FROM integration_input").fetchone()[0]
    s2 = run_stack_lineage(con, now=now)
    po = {v: con.execute("SELECT count(*) FROM event WHERE verb=?", (v,)).fetchone()[0]
          for v in _SLIN_VERBS}
    rows_po = con.execute("SELECT count(*) FROM integration_input").fetchone()[0]
    # DWA RÓŻNE FAKTY, DWIE RÓŻNE LINIE. „Zero zapisu, bo nic się nie zmieniło" (idempotencja)
    # i „zero zapisu, bo nie przeczytaliśmy pliku" (strażnik 4) to nie to samo — sklejone w jedno
    # kryterium dawały czerwień o FAŁSZYWEJ przyczynie: etykieta mówiłaby „zero relacji, zero
    # eventów", gdy jedno i drugie faktycznie zachodzi. A bramkę czerwoną na poprawnym stanie
    # naprawia się podnoszeniem kotwicy — po czym przestaje ona łapać regresję prawdziwą.
    idem = (not s2.linked_new and not s2.unlinked and po == przed and rows_przed == rows_po)
    # `kept_proven` obok `kept_unread`, bo to DWA rozne powody zerowej delty (S2b): pierwszy znaczy
    # „nie przeczytalem pliku", drugi „przeczytalem, ale zapisany dowod jest mocniejszy". Jedna
    # liczba kazalaby diagnozowac odlaczone archiwum przy stosie lezacym na miejscu.
    out(f"  przebieg 2 (idempotencja): linked_new={s2.linked_new} unlinked={s2.unlinked} "
        f"pominietych_bez_zeznania={s2.kept_unread} pominietych_dowod_mocniejszy={s2.kept_proven} "
        f"wiersze {rows_przed}=={rows_po}")
    return s1, idem, s2.kept_unread


# ── (C) KRYTERIA §5 na bazie zbudowanej z dawcy (stage-aware: import vs full) ─────────────────────
def check_criteria(con, summary, out, cal=None, cal_idempotent=None, lin=None, lin_idempotent=None,
                   stacks=None, stacks_idempotent=None, slin=None, slin_idempotent=None,
                   slin_kept=None, donor_testimony=None, now=None):
    """`donor_testimony` = `donor_object_testimony` podgrupy przeliczonej (z `build_import`); musi
    pokrywać `summary.preflight.recompute` co do ścieżki - inaczej kotwica §5.7b liczyłaby część
    podgrupy zeznaniem dysku (EXPECT, nie cicha degradacja). `now` (ISO-8601) liczy wiek kotwic
    w wydruku FAIL; domyślnie bieżąca chwila.

    Zwraca listę `(etykieta, ok, pochodzenie)`, gdzie `pochodzenie` to linie `opis_niezgodnosci`
    przy FAIL kryterium z kotwicą (inaczej pusta krotka) - podsumowanie powtarza je przy FAIL-u."""
    donor_testimony = donor_testimony or {}
    if set(donor_testimony) != set(summary.preflight.recompute):
        raise RuntimeError("check_criteria: zeznanie dawcy nie pokrywa podgrupy przeliczonej "
                           f"({len(donor_testimony)} != {len(summary.preflight.recompute)})")
    dzis = (datetime.fromisoformat(now) if now else datetime.now(timezone.utc)).date()
    results = []                                    # (etykieta, PASS/FAIL, pochodzenie)

    def crit(label, cond, pochodzenie=()):
        pochodzenie = tuple(pochodzenie) if not cond else ()
        results.append((label, bool(cond), pochodzenie))
        out(f"  [{_ok(cond)}] {label}")
        for linia in pochodzenie:
            out(f"         {linia}")

    n_xisf = con.execute("SELECT count(*) FROM frame WHERE filetype='xisf'").fetchone()[0]
    full = n_xisf > 0
    # TRZECI etap wykrywany po ZEZNANIU DROGI, nie po populacji `master_light` w bazie: gdyby droga
    # przebiegła i nie wciągnęła NICZEGO, detekcja po bazie cicho zdegradowałaby przebieg do FULL
    # i bramka pochwaliłaby stan, którego nikt nie chciał. `stacks is not None` znaczy „droga szła".
    ze_stosami = stacks is not None
    stage = ("FULL + STOSY (import + doskan XISF + drzewo obróbki = P-I)" if ze_stosami
             else "FULL (import + doskan XISF = PF-4)" if full else "IMPORT (dawca FITS = PF-3)")
    exp_tel = EXP_TELESCOPES_FULL if full else EXP_TELESCOPES_IMPORT
    out("")
    out(f"== (C) KRYTERIA §5 — stan: {stage} ==")

    def crit_k(label, k, akt, nota="", rel="=="):
        """Kryterium z KOTWICĄ (`Kotwica`): przy FAIL drukuje pochodzenie i wiek kotwicy obok
        obu wartości (AR-53). `rel` `==` albo `>=` (próg). Kotwica może być jeszcze NIEZMIERZONA
        (`wartosc=None`) - wtedy wypisujemy aktualia i NIE stawiamy fałszywie zielonego PASS-a
        ani fałszywego FAIL-a: bramka ma powiedzieć „nie wiem", a nie zgadywać. Ten sam protokół,
        którym przed pilotem P-D zaszywano `EXP_NAMELESS_*`."""
        if k.wartosc is None:
            out(f"  [ ?? ] {label} — kotwica NIEZMIERZONA, aktualnie {akt}{nota}; "
                f"zaszyj po tym przebiegu")
            return
        ok = akt >= k.wartosc if rel == ">=" else akt == k.wartosc
        crit(f"{label} {rel} {k.wartosc} (akt={akt}){nota}", ok,
             opis_niezgodnosci(k, akt, dzis, rel))


    # §4.6 IMPORT DOMYKA ŁAŃCUCH (P-G, 2026-08-01): fasada robi group→resolve→calibrate→lineage,
    # więc baza „po imporcie" znaczy to samo, co baza po Dostawie w GUI. Bramka jest KONIECZNA,
    # bo regresja byłaby tu NIEWIDOCZNA: (K)/(L) niżej i tak zbudowałyby oś, tyle że dopiero
    # w skrypcie — a realny import poza tym skryptem zostawiłby bazę z pustą osią przepisu.
    out(f"\n§4.6 łańcuch importu: kalibracja {summary.calibration}; "
        f"rodowód lighty={getattr(summary.lineage, 'lights', None)}")
    # Domknięcie populacji, nie „> 0 profili": kompletność przepisu zależy od DANYCH (dawca bez
    # masterdarków dałby same niekompletne), a pytanie brzmi „czy etap poszedł", nie „czy dane były
    # ładne". Ten sam kształt co §5.11 niżej — tam na stanie bazy, tu na zeznaniu fasady.
    cal_i = summary.calibration
    crit("§4.6 import domyka łańcuch: oś przepisu policzona JUŻ w imporcie (populacja domknięta)",
         cal_i is not None and cal_i.frames > 0
         and cal_i.profiles_assigned + cal_i.incomplete == cal_i.frames)
    crit("§4.6 import domyka łańcuch: rodowód policzony JUŻ w imporcie",
         summary.lineage is not None and summary.lineage.lights > 0)

    # §5.1 tożsamość: sha1_data 100% (każdy frame ma odcisk danych; degenerat = flaga)
    n_frame = con.execute("SELECT count(*) FROM frame").fetchone()[0]
    n_sha = con.execute(
        "SELECT count(*) FROM frame WHERE sha1_data IS NOT NULL AND sha1_data!=''").fetchone()[0]
    uncomp = con.execute("SELECT count(*) FROM frame WHERE sha1_data_uncomputable=1").fetchone()[0]
    out(f"\n§5.1 tożsamość: frame={n_frame} z sha1_data={n_sha} (degenerat uncomputable={uncomp})")
    crit("§5.1 sha1_data 100% (każdy frame ma odcisk danych)", n_sha == n_frame and n_frame > 0)
    if full:
        crit_k("§5.1 degenerat XISF (OIII masterflat, bajt \\x07)", EXP_UNCOMPUTABLE_FULL, uncomp)
    else:
        crit("§5.1 zero degeneratów w imporcie FITS (nagłówki naprawione)", uncomp == 0)

    # frame == location − dedupy treścią (import: 1:1; full: 5 dedupów XISF w pf4)
    n_loc = con.execute("SELECT count(*) FROM location").fetchone()[0]
    if not full:
        crit(f"§4.6 frame == location == dawca−skipped ({summary.imported})",
             n_frame == summary.imported and n_loc == summary.imported)
    else:
        out(f"  (full) frame={n_frame} location={n_loc} — dedupy treścią = {n_loc - n_frame}")
        crit("§4.6 location >= frame (dedup sha1_data łączy byte-identyczne mastery)", n_loc >= n_frame)

    # §5.3/§5.8 kamery: forma, piksel, mono, ZERO rozbić modelu (no-split). STAGE-AWARE od
    # 2026-08-01: FULL niesie 3 korpusy lustrzanek z RAW-ów, IMPORT (dawca FITS) ich nie zna.
    exp_cams = EXP_CAMERAS_FULL if full else EXP_CAMERAS_IMPORT
    out("\n§5.3/§5.8 kamery (model, pixel, is_mono, src):")
    cams = {r[0]: r for r in con.execute(
        "SELECT model_canon, pixel_um, is_mono, is_mono_source, pixel_conflict FROM camera")}
    for mc in sorted(cams):
        _, px, mono, msrc, pc = cams[mc]
        out(f"    {mc:12s} px={px} is_mono={mono} src={msrc} pixel_conflict={pc}")
    # Równość słowników {model: (piksel, mono)} = ten sam zbiór kamer i zgodny piksel+mono każdej.
    akt_cams = {mc: (cams[mc][1], cams[mc][2]) for mc in cams}
    crit(f"§5.3 {len(exp_cams.wartosc)} kamer, piksel+mono zgodne "
         f"(MM/MD mono, MC/294/Sony/DSLR kolor)", akt_cams == exp_cams.wartosc,
         opis_niezgodnosci(exp_cams, akt_cams, dzis))
    distinct_models = con.execute("SELECT count(DISTINCT model_canon) FROM camera").fetchone()[0]
    n_cam_rows = con.execute("SELECT count(*) FROM camera").fetchone()[0]
    crit("§5.8 zero rozbić modelu (distinct model_canon == wierszy camera)",
         distinct_models == n_cam_rows == len(exp_cams.wartosc))
    pconf = con.execute("SELECT count(*) FROM camera WHERE pixel_conflict=1").fetchone()[0]
    # Etap stosów nie dokłada konfliktu — produkt integracji nie wnosi `XPIXSZ`
    # (`cameras.NO_PIXEL_KINDS`, decyzja Zdzinia 2026-08-02). FULL niesie jeden prawdziwy: SONYA7RM3,
    # karta FITS 4,86 wobec EXIF 4,62 (AR-55, nota przy `EXP_CAMERAS_FULL`).
    exp_pconf = EXP_PIXEL_CONFLICT_FULL if full else EXP_PIXEL_CONFLICT_IMPORT
    crit(f"§5.3 pixel_conflict == {exp_pconf.wartosc} (rozjazdy piksela poza tolerancją)",
         pconf == exp_pconf.wartosc, opis_niezgodnosci(exp_pconf, pconf, dzis))

    # §5.4 teleskopy: liczność (import 8 / full 12) + suspect=0 (verb telescope.review MARTWY po PF-2)
    out("\n§5.4 teleskopy (canon, f/, focal, #frames, #RAW):")
    tels = con.execute(
        "SELECT t.telescop_canon, t.f_ratio_nominal, t.focal_nominal, "
        "  (SELECT count(*) FROM frame f JOIN config c ON c.id=f.config_id WHERE c.telescope_id=t.id), "
        "  (SELECT count(*) FROM frame f JOIN config c ON c.id=f.config_id "
        "   WHERE c.telescope_id=t.id AND f.filetype IN (SELECT value FROM json_each(?))) "
        "FROM telescope t ORDER BY 4 DESC",
        (json.dumps(list(NO_OBJECT_CARD_FILETYPES)),)).fetchall()
    for tc, fr_, fl, nfr, nraw in tels:
        out(f"    {tc:28s} f/{str(fr_):<5} focal={str(fl):<6} frames={nfr:<6} RAW={nraw}")
    if ze_stosami:
        # Drzewo obróbki niesie WŁASNE etykiety `TELESCOP` — także takie, których archiwum już nie
        # zna po naprawach na `R:`. Osobna kotwica, bo to inny zakres: gdyby liczyć jedną, powrót
        # martwej etykiety w drzewie obróbki wyglądałby jak regresja naprawy archiwum.
        crit_k("§5.4 liczba teleskopów (z drzewem stosów)", EXP_TELESCOPES_STACKS, len(tels))
    else:
        crit_k("§5.4 liczba teleskopów", exp_tel, len(tels))
    if full and not ze_stosami:
        # Rozdział, nie sama liczba: kotwica liczby teleskopów milczałaby o tym, czy przybyło optyki
        # astro, czy kolejnego obiektywu. Obiektyw = oś powołana WYŁĄCZNIE klatkami RAW.
        raw_only = sum(1 for *_x, nfr, nraw in tels if nfr and nfr == nraw)
        out(f"    z tego powołane wyłącznie przez RAW (obiektywy DSLR): {raw_only}")
        crit_k("§5.4 osie wyłącznie-RAW (obiektywy z EXIF)", EXP_TELESCOPES_RAW_ONLY_FULL, raw_only)
    suspect = con.execute("SELECT count(*) FROM event WHERE verb='telescope.review'").fetchone()[0]
    crit(f"§5.4 telescope.review MARTWY po PF-2 (akt={suspect})", suspect == 0)

    # §5.6 config bez cichego NULL: frame z headerem bez config_id ⟺ ma config.review.
    # KIND-AWARE (wariant B): dark/bias są poza osią teleskopu, więc ich NULL nie jest „cichy" —
    # jest docelowy. Predykat czerpie zbiór z `grouper.NO_TELESCOPE_KINDS` (jeden właściciel, SPOT),
    # ten sam, którego używa `resolver.review_state`; osobno raportujemy, ile klatek tak wyłączono.
    cfg = con.execute("SELECT count(*) FROM config").fetchone()[0]
    # DISTINCT target, nie `count(*)` — poprawka 2026-08-02 (I-2b). `flag_config_review` emituje
    # BEZWARUNKOWO przy każdym przebiegu groupera (znany wzorzec: „kolejka review = STAN, NIE
    # count(event)"), więc surowy licznik zdarzeń rośnie z LICZBĄ PRZEBIEGÓW, a nie z liczbą spraw.
    # Kryterium nazywa się „zero cichego NULL" i jest pytaniem o ZBIÓR: czy każda klatka bez configu
    # ma zapisany POWÓD. Dopóki grouper biegł dwa razy, licznik przypadkiem równał się stanowi;
    # trzeci przebieg (droga „Stosy") to ujawnił — 873 zdarzenia na 440 spraw. Zmierzone, nie
    # domyślone: rozkład to 433 (przebieg po doskanie XISF) + 440 (po stosach).
    cfg_review = con.execute(
        "SELECT count(DISTINCT target) FROM event WHERE verb='config.review'").fetchone()[0]
    off_axis = json.dumps(sorted(NO_TELESCOPE_KINDS))
    no_cfg_hdr = con.execute(
        "SELECT count(*) FROM frame f WHERE f.config_id IS NULL "
        "AND f.kind NOT IN (SELECT value FROM json_each(?)) "
        "AND EXISTS(SELECT 1 FROM header h WHERE h.frame_id=f.id)", (off_axis,)).fetchone()[0]
    calib_null = con.execute(
        "SELECT count(*) FROM frame f WHERE f.config_id IS NULL "
        "AND f.kind IN (SELECT value FROM json_each(?))", (off_axis,)).fetchone()[0]
    unassigned = con.execute(
        "SELECT count(*) FROM event WHERE verb='config.unassigned'").fetchone()[0]
    # KRYTERIUM JEST KIERUNKOWE, nie równościowe (R1/W4) — i to jest poprawka wymuszona przez
    # segment, który PIERWSZY RAZ W HISTORII REPO WYPROWADZA klatki z tego zbioru. Do R1 stan mógł
    # tylko rosnąć albo stać, więc równość `stan == |targety|` przypadkiem działała. Gest „Przypisz
    # zestaw…" zdejmuje klatkę ze stanu, a dziennik jest APPEND-ONLY: jej `config.review` zostaje
    # tam na zawsze. Równość pękłaby więc na zmianie POPRAWNEJ, dokładnie o liczbę naprawionych
    # klatek — czyli bramka karałaby za sprzątanie.
    # Pytanie, na które ta pozycja odpowiada, brzmi „zero cichego NULL": czy KAŻDA klatka bez
    # configu ma zapisany POWÓD. To zawieranie (`stan ⊆ targety`), nie równość — liczymy klatki
    # stanu BEZ zdarzenia i żądamy zera. Nadmiar targetów po drugiej stronie jest odtąd normalny
    # i raportowany jako `naprawione`, żeby liczba nie znikła z oczu.
    # Formuła w `horreum.audit`, nie tutaj — żeby liczyła ją TAKŻE bateria (powód: nagłówek `audit`).
    bez_powodu = config_review_reason_gap(con)
    naprawione = cfg_review - no_cfg_hdr
    out(f"\n§5.6 config={cfg} config.review={cfg_review} frame-bez-config-z-headerem={no_cfg_hdr} "
        f"(kalibracja poza osią={calib_null}, odpięte={unassigned}, "
        f"wyprowadzone ze zbioru={naprawione}, bez powodu={bez_powodu})")
    crit("§5.6 zero cichego NULL (każda klatka bez configu ma zapisany POWÓD)",
         bez_powodu == 0)
    crit("§5.6 kalibracja bez osi NIE ma config.assigned (kind-scoping)",
         con.execute(
             "SELECT count(*) FROM frame WHERE config_id IS NOT NULL "
             "AND kind IN (SELECT value FROM json_each(?))", (off_axis,)).fetchone()[0] == 0)
    if full:
        # RAW liczony ODDZIELNIE (2026-08-01): DSLR bez teleskopu w EXIF nie ma z czego powołać osi,
        # więc jego `config_id IS NULL` to stan docelowy — dokładnie ta sama figura, co kind-scoping
        # dark/bias wyżej, tylko po osi FORMATU.
        cfg_review_raw = con.execute(
            "SELECT count(*) FROM frame f JOIN header h ON h.frame_id = f.id "
            "WHERE f.config_id IS NULL AND f.filetype IN (SELECT value FROM json_each(?)) "
            "AND f.kind NOT IN (SELECT value FROM json_each(?))",
            (json.dumps(list(NO_OBJECT_CARD_FILETYPES)), off_axis)).fetchone()[0]
        out(f"    z tego RAW (DSLR bez teleskopu w EXIF): {cfg_review_raw}")
        if ze_stosami:
            crit_k("§5.6 config.review poza RAW (z drzewem stosów)",
                   EXP_CONFIG_REVIEW_STACKS, cfg_review - cfg_review_raw,
                   nota=" - stacki bez `TELESCOP` nie powołają osi")
        else:
            crit_k("§5.6 config.review poza RAW (`unknown` masterflat A7R3)",
                   EXP_CONFIG_REVIEW_FULL, cfg_review - cfg_review_raw)
        crit_k("§5.6 config.review RAW (stan docelowy DSLR)", EXP_CONFIG_REVIEW_RAW_FULL,
               cfg_review_raw)
    else:
        crit("§5.6 config.review == 0 w imporcie FITS (nagłówki naprawione)", cfg_review == 0)

    # §5.7 obiekt — % na light/master_light przez REALNY delta_report (kalibracja świadomie poza)
    rep = delta_report(con, top=40)
    out(f"\n§5.7 obiekt: {rep.object_resolved}/{rep.object_resolved+rep.object_unresolved} "
        f"= {rep.object_pct}% (delta {rep.object_unresolved} w {len(rep.object_delta)} distinct)")
    # Populacja WYPCHNIĘTA z procentu po zrównaniu licznika z mianownikiem (S0): klatki, które
    # obiekt mają, choć nagłówek nazwy nie niósł (dziś: region). Wcześniej doliczały się do
    # licznika, nie wchodząc do mianownika — czyli podnosiły wynik o wartość, której bramka nie
    # widziała, i maskowały spadek rozpoznania. RAPORT, nie bramka: to nie jest dług do zamknięcia,
    # tylko liczba, która ma być jawna.
    out(f"    poza procentem — rozwiazane BEZ nazwy w naglowku: {rep.object_resolved_no_raw}")
    for raw, n in rep.object_delta[:12]:
        out(f"    {n:5d}  {raw}")
    crit_k("§5.7 object_pct [%]", EXP_OBJECT_PCT_MIN, rep.object_pct, rel=">=")

    # §5.7a ROZKŁAD POPULACJI SIĘ DOMYKA (R-S0-6). Sześć predykatów raportu dzieli lighty na kubełki,
    # a dotąd NIC nie sprawdzało, czy pokrywają całość — rozkład, który się nie domyka, jest
    # fałszywie zieloną bramą (repo pilnuje tego przy delcie, oś obiektu nie miała odpowiednika).
    # Ujawnia przy okazji klasę „light bez wiersza `header` i bez obiektu": predykaty `nameless_*`
    # mają INNER JOIN, a `resolved_no_raw` wymaga obiektu, więc taka klatka nie wpada do żadnego
    # z sześciu. Dziś ta klasa jest pusta — kryterium jest tripwirem, nie naprawą.
    closure = light_population_closure(con, rep)
    out(f"    rozkład: {' + '.join(f'{k} {v}' for k, v in closure.buckets.items())}"
        f" + bez nagłówka {closure.headerless}"
        f" + wycofane {closure.retired} + zastąpione {closure.superseded}"
        f" = {closure.counted} / {closure.total}")
    crit(f"§5.7a rozkład lightów domyka się do populacji "
         f"({closure.counted} == {closure.total})", closure.ok)

    # §5.7b kotwica nawrotu P-D — lighty bez `object_raw` (poza mianownikiem procentu wyżej).
    # Od AR-49 kotwica stoi na ZEZNANIU DAWCY (`nameless_split`), nie na stanie bazy: podgrupa
    # przeliczona z dysku niesie stan `R:` i zależy od próbki falsyfikatora, więc idzie OSOBNĄ
    # liczbą - raportem, nie kotwicą (jej wartość mówi, ile naprawił dysk, nie co zeznał dawca).
    # Dopóki kotwica nie jest zmierzona (None), pozycja RAPORTUJE liczbę i nie zapala bramki:
    # zaszycie liczby wziętej z rachunku zamiast z przebiegu byłoby dokładnie tym błędem,
    # który ta kotwica ma łapać.
    exp_nameless = EXP_NAMELESS_FULL if full else EXP_NAMELESS_IMPORT
    ns = nameless_split(con, donor_testimony)
    out(f"\n§5.7b bez nazwy w nagłówku (light): wg zeznania dawcy {ns.anchor}; "
        f"stan bazy {rep.object_nameless}")
    out(f"    podgrupa przeliczona z dysku: {len(donor_testimony)} plików, lightów {ns.recomputed_lights}; "
        f"bez nazwy wg dawcy {ns.recomputed_donor}, wg dysku {ns.recomputed_disk} (raport, bez kotwicy)")
    crit_k("§5.7b bez nazwy wg zeznania dawcy", exp_nameless, ns.anchor)
    crit(f"§5.7b derywacja zeznania dawcy zgodna z potokiem przy niezmienionym zeznaniu obiektu "
         f"(rozjazdy={len(ns.mismatch)})", not ns.mismatch)
    # Bliźniacza populacja po drugiej stronie FORMATU: klatki, które nie mają JAK zeznać o obiekcie.
    # Liczona zawsze, pilnowana tylko w FULL — dawca jest FITS-only, więc w IMPORT jest z definicji 0
    # i osobne kryterium byłoby pustym rytuałem.
    out(f"    z tego format bez karty `OBJECT` (RAW): {rep.object_nameless_raw}")
    if full:
        crit_k("§5.7b object_nameless_raw", EXP_NAMELESS_RAW_FULL, rep.object_nameless_raw,
               nota=" (DSLR - droga naprawy: ręka)")
    else:
        crit("§5.7b zero RAW w imporcie FITS (dawca jest FITS-only)",
             rep.object_nameless_raw == 0)
    # TRZECIA populacja tego samego objawu (I-2b/D-P-I-5): gotowy obraz po integracji. Kotwica
    # FULL wyżej NIE drgnie po dołożeniu stosów — i to jest dowód, że rozdział działa: gdyby
    # `EXP_NAMELESS_FULL` skoczyło z 25, znaczyłoby, że stacki wpadły do kubełka archiwum
    # i pierwsza dostawa bez `OBJECT` schowałaby się za drzewem obróbki.
    out(f"    z tego gotowe stosy (po integracji): {rep.object_nameless_stacks}")
    if ze_stosami:
        crit_k("§5.7b object_nameless_stacks", EXP_NAMELESS_STACKS,
               rep.object_nameless_stacks, nota=" - własny kubełek, naprawa kartą (P6d)")
    else:
        crit("§5.7b zero stosów, gdy droga Stosów nie szła (etap ich nie wciągał)",
             rep.object_nameless_stacks == 0)

    # §5.8 (full) — kinds XISF (dowód, że doskan wciągnął to co PF-4)
    if full:
        xk = dict(con.execute(
            "SELECT kind, count(*) FROM frame WHERE filetype='xisf' GROUP BY kind").fetchall())
        out(f"\n§5.8 kinds XISF: {xk}")
        # Ścisła równość SŁOWNIKA (nie „zawiera") — dlatego etap stosów MUSI mieć własną kotwicę:
        # nowy klucz `master_light` jest tu FAIL-em, i to była przewidziana konsekwencja I-2b,
        # nie niespodzianka (brief §0 fakt 24).
        exp_kinds = EXP_XISF_KINDS_STACKS if ze_stosami else EXP_XISF_KINDS
        crit_k("§5.8 kinds XISF", exp_kinds, xk)
        frev = con.execute("SELECT count(*) FROM event WHERE verb='frame.review'").fetchone()[0]
        crit_k("§5.8 frame.review (OIII masterflat)", EXP_FRAME_REVIEW_FULL, frev)

    # §5.13 ETAP STOSÓW (I-2b, P-I) - dwóch niezależnych świadków tej samej populacji:
    # ZEZNANIE ETAPU (ile plików pod `STACKS` przejście zobaczyło i co z nimi zrobiło) i STAN BAZY
    # (ile klatek jest). Plik o DANYCH identycznych z inną klatką (dedup po `sha1_data`, legalny)
    # daje lokację, nie klatkę - widać go w parze kandydaci/wciągnięte; `master_light` sprzed
    # etapu - w parze stan bazy/wciągnięte.
    if ze_stosami:
        out(f"\n§5.13 STACKS zwyklym skanem: pliki={stacks.pod_stacks} kandydaci={stacks.candidates} "
            f"wciagniete={stacks.ingested} pochodne={stacks.derived_skipped} "
            f"odrzucone={stacks.rejected} bledy={stacks.failed}")
        crit_k("§5.13 kandydaci (pliki pod STACKS po sicie pochodnych)", EXP_STACKS_CANDIDATES,
               stacks.candidates)
        crit_k("§5.13 pochodne obróbki odsiane sitem (§5 briefu P-I)", EXP_STACKS_DERIVED,
               stacks.derived_skipped)
        crit_k("§5.13 wciągnięte (nowe klatki master_light)", EXP_STACKS_INGESTED,
               stacks.ingested)
        # Zero odrzuconych NIE jest ozdobą: dopóki tak jest, populacja kandydatów == populacja
        # stacków. Plik pod `STACKS`, który zeznaje inny rodzaj albo się nie czyta, to sprawa do
        # OBEJRZENIA, nie do podbicia liczby.
        crit_k("§5.13 odrzucone (rodzaj inny niż master_light, nieczytelne, bez lokacji)",
               EXP_STACKS_REJECTED, stacks.rejected + stacks.failed)
        n_ml = con.execute(
            "SELECT count(*) FROM frame WHERE kind='master_light'").fetchone()[0]
        out(f"    stan bazy: frame(kind='master_light') = {n_ml}")
        crit("§5.13 stan bazy zgodny z zeznaniem etapu (master_light wyłącznie z etapu)",
             n_ml == stacks.ingested)
        # Idempotencję etapu na REALNYM drzewie mierzy faza (T) drugim przebiegiem - tak samo, jak
        # (K)/(L) mierzą swoją. Bramka jest KONIECZNA, nie ozdobna: bez niej wciągnięcie stosów przy
        # każdej dostawie mnożyłoby lokacje, a to dokładnie ten błąd, który przy `volume='?'` już
        # raz groził skanowi (guard serialu w Dostawie).
        crit("§5.13 etap idempotentny (2. przebieg: zero nowych klatek, zero eventów)",
             stacks_idempotent is True)

    # §5.14 RODOWÓD STOSÓW (I-2c, P-I) — bramka pyta o INWARIANTY, nie tylko o liczby. Powód:
    # kotwice tego toru zależą od osi obiektu, a ta zależy od tego, czy nagłówki były naprawiane;
    # inwariant („każdy stos ma wiersz", „wejście to zawsze light", „bez wejść ⇒ jest POWÓD")
    # obroni się na każdej bazie, a kotwica dopiero po pomiarze.
    if ze_stosami and slin is not None:
        out(f"\n§5.14 rodowod stosow: z_rodowodem={slin.linked}/{slin.stacks} wejsc={slin.inputs} "
            f"zrodla={slin.by_assert} powody={slin.reasons}")
        n_int = con.execute("SELECT count(*) FROM integration").fetchone()[0]
        n_ml = con.execute("SELECT count(*) FROM frame WHERE kind='master_light'").fetchone()[0]
        # KAŻDY stos dostaje wiersz — także ten bez wejść. „Nie wiem z czego" jest faktem
        # i musi być odróżnialne od „jeszcze nie liczyliśmy" (milczenie obu wyglądałoby tak samo).
        crit(f"§5.14 każdy stos ma wiersz integracji ({n_int} == {n_ml})", n_int == n_ml)
        bez_powodu = con.execute(
            "SELECT count(*) FROM integration i WHERE i.unresolved_reason IS NULL "
            "AND NOT EXISTS (SELECT 1 FROM integration_input ii WHERE ii.integration_id = i.id)"
        ).fetchone()[0]
        crit("§5.14 integracja bez wejść ZAWSZE niesie powód (zero cichych pustek)",
             bez_powodu == 0)
        # OBA STRAŻNIKI PYTAJĄ O AUTOMAT, NIE O CZŁOWIEKA — stąd `asserted_by <> 'user'`. Werdykt
        # ręki ZOSTAJE w tabeli z założenia (`unlink_integration_input` go omija), więc bez tego
        # wyłączenia pierwsze „odrzuć wejście" w panelu „Rodowód" zapala bramkę na stanie
        # POPRAWNYM — a bramkę czerwoną na poprawnym stanie naprawia się podnoszeniem kotwicy,
        # po czym przestaje ona łapać regresję prawdziwą. Inwariant brzmi „automat nie zapisał
        # wejść", nie „nie ma wejść".
        z_wejsciami_i_powodem = con.execute(
            "SELECT count(*) FROM integration i WHERE i.unresolved_reason IS NOT NULL "
            "AND EXISTS (SELECT 1 FROM integration_input ii WHERE ii.integration_id = i.id "
            "            AND ii.asserted_by <> 'user')"
        ).fetchone()[0]
        crit("§5.14 powód wyklucza wejścia automatu (odmowa == ZERO relacji)",
             z_wejsciami_i_powodem == 0)
        # Strażnik okna zdegenerowanego — sedno D-P-I-2: taki stos ma NIE dostać ani jednej relacji.
        deg_z_wejsciami = con.execute(
            "SELECT count(*) FROM integration i WHERE i.degenerate = 1 "
            "AND EXISTS (SELECT 1 FROM integration_input ii WHERE ii.integration_id = i.id "
            "            AND ii.asserted_by <> 'user')"
        ).fetchone()[0]
        crit("§5.14 okno zdegenerowane nie dostaje relacji automatu (strażnik D-P-I-2)",
             deg_z_wejsciami == 0)
        nie_light = con.execute(
            "SELECT count(*) FROM integration_input ii JOIN frame f ON f.id = ii.input_frame_id "
            "WHERE f.kind <> 'light'").fetchone()[0]
        crit("§5.14 wejściem jest WYŁĄCZNIE light (stos nie wchodzi w stos)", nie_light == 0)
        # Partycja: każdy stos jest ALBO z rodowodem, ALBO w dokładnie jednym kubełku powodu.
        crit(f"§5.14 partycja domyka populację ({slin.linked} + {sum(slin.reasons.values())} "
             f"== {slin.stacks})", slin.linked + sum(slin.reasons.values()) == slin.stacks)
        crit_k("§5.14 integracje z rodowodem", EXP_SLIN_LINKED, slin.linked)
        crit_k("§5.14 wejść razem", EXP_SLIN_INPUTS, slin.inputs)
        crit_k("§5.14 dowiedzione historią pliku", EXP_SLIN_HISTORY,
               slin.by_assert.get("history", 0),
               nota=" - reszta to KANDYDACI z okna, nie fakty")
        crit("§5.14 rodowód idempotentny (2. przebieg: zero relacji, zero eventów zapisu)",
             slin_idempotent is True)
        # DWA kryteria, bo „nic nie pominąłem" jest WĘŻSZE niż „przeczytałem wszystko": stos BEZ
        # wcześniejszego rodowodu nigdy nie wchodzi do `kept_unread` (nie ma czego chronić), więc
        # sam ten licznik byłby zielony także wtedy, gdy przebieg nie przeczytał ANI JEDNEGO
        # zeznania. Kotwica jest realna, nie ozdobna: korpus to 128/128 czytelnych `.xisf`.
        crit(f"§5.14 przebieg przeczytał zeznanie KAŻDEGO stosu (nieodczytanych: "
             f"{slin.history_unread})", slin.history_unread == 0)
        crit(f"§5.14 żaden gotowy rodowód nie został pominięty (pominiętych: {slin_kept})",
             slin_kept == 0)

    # §5.9 encje == eventy (co do sztuki) — audyt jednej klingi kompletny. FORMUŁA ŻYJE
    # W `horreum.audit`, żeby liczyła ją także bateria: dopóki mieszkała tu, żaden test nie mógł
    # jej zaczerwienić, a skrypt chodzi wyłącznie na dawcy.
    out("\n§5.9 encje == eventy (emisje − wycofania):")
    parity = entity_event_parity(con)
    all_match = True
    for p in parity:
        all_match &= p.ok
        minus = f" − {p.minus} {p.retracted}" if p.minus else ""
        if p.legacy:
            minus += f" − przepięcia bez pary {p.legacy}"
        out(f"    {p.name:28s} {p.entities:6d} == {p.events:6d}{minus}  [{_ok(p.ok)}]")
    crit("§5.9 encje == eventy (co do sztuki, łącznie z przypisaniami)", all_match)
    # Człon `legacy` osi configu jest HISTORIĄ żywej bazy (przepięcia sprzed pary verbów, R-S1-5).
    # Ta baza powstała bieżącym kodem, więc każde przepięcie bez pary jest tu regresją klingi -
    # osobne kryterium, żeby odejmowanie historii nie zazieleniło jej po cichu.
    n_bez_pary = config_unpaired_reassignments(con)
    crit(f"§5.9 przepięcia configu bez pary verbów (świeża baza: {n_bez_pary})", n_bez_pary == 0)

    # §5.15 ZASTĄPIENIE TOŻSAMOŚCI (R4, #DR2) — bramka GO-1. Pyta o INWARIANTY, nie o liczbę:
    # populacja zastąpionych jest na świeżej bazie dawcy z definicji ZEROWA (podmiana wymaga
    # DRUGIEGO odczytu tej samej ścieżki, a skrypt czyta drzewo raz), więc kotwica na liczbie
    # pinowałaby zero i milczała o wszystkim, co ma pilnować. Inwarianty czerwienią się natomiast
    # w każdej bazie, do której pass wejdzie — także w żywej `pf4` puszczonej tym samym skryptem.
    sup = supersede_invariants(con)
    n_zastapionych = con.execute(
        "SELECT count(*) FROM frame WHERE superseded_by IS NOT NULL").fetchone()[0]
    sieroty = supersede.orphans(con)
    out(f"\n§5.15 zastapienie tozsamosci: zastapionych={n_zastapionych} "
        f"sieroty_bez_ogniwa={len(sieroty)} "
        f"do_przeniesienia={len(supersede.pending_transfer(con))}")
    crit("§5.15 klatka zastąpiona NIE MA obecnej kopii (inaczej jej godziny cicho wypadają)",
         sup["zastapiona_z_obecna_kopia"] == 0)
    crit("§5.15 łańcuch nie urywa się w powietrzu (ogniwo prowadzi do klatki z lokacją)",
         sup["ogniwo_do_zastapionej"] == 0)
    # Sierota BEZ ogniwa to otwarte pytanie, nie awaria; na żywej bazie zdejmuje je pass
    # (`horreum supersede --apply`), nie kasowanie klatki (D-DR-4).
    # ⚠ TO KRYTERIUM CZEKA NA PIERWSZY PRZEBIEG: zero jest WYWNIOSKOWANE (sierota powstaje wyłącznie
    # przez `rebind_location`, a świeży skan czyta każdą ścieżkę RAZ), nie zmierzone na bazie dawcy.
    # Zmierzone jest co innego — żywa `pf4`: 1 przed passem, 0 po. Jeśli pierwszy przebieg akceptacji
    # zaczerwieni ten wiersz, to NIE jest usterka bramki: znaczy, że import dawcy produkuje klatkę
    # bez lokacji, o której nikt dotąd nie wiedział — wtedy diagnoza, nie podnoszenie progu.
    crit("§5.15 zero sierot nierozstrzygniętych (frame bez lokacji i bez `superseded_by`)",
         len(sieroty) == 0)

    # §5.17 WYCOFANIE KLATKI RĘKĄ (D-OW-3/R2) — strażnik kolumny, której migracja 0018 nie mogła
    # dać ani `CHECK`-a (warunek jest zdaniem o `location`), ani triggera (nie ma ani jednego
    # w historii tego repo). Pyta o INWARIANTY, nie o liczbę: populacja wycofanych jest na świeżej
    # bazie dawcy z definicji ZEROWA, więc kotwica na liczbie pinowałaby zero i milczała.
    #
    # ⚠ PIERWSZY CZŁON NIE JEST AWARIĄ BAZY, tylko ROBOTĄ DO ZROBIENIA: „wycofana, a plik wrócił"
    # powstaje bez niczyjej pomyłki (zwykły re-skan zapala `present = 1`), a werdyktu ręki nie
    # gasimy automatycznie — warunek stały „ręka nietykalna". Czerwony wiersz znaczy więc „idź do
    # Porządków i rozstrzygnij gestem", nie „diagnozuj kod".
    ret = retire_invariants(con)
    n_wycofanych = con.execute(
        "SELECT count(*) FROM frame WHERE retired_at IS NOT NULL").fetchone()[0]
    out(f"\n§5.17 wycofanie klatki: wycofanych={n_wycofanych} "
        f"plik_wrocil={ret['wycofana_z_obecna_kopia']}")
    crit("§5.17 zero wycofanych z OBECNĄ kopią (plik wrócił — rozstrzygnij gestem Przywróć)",
         ret["wycofana_z_obecna_kopia"] == 0)

    # §5.16 OŚ SPRZĘTU WSKAZANA RĘKĄ (R1, #DR2) — bramka GO-1, zbudowana jak §5.15 i z tego samego
    # powodu: na świeżej bazie dawcy populacja ręcznych zestawów jest ZEROWA (gest robi człowiek
    # w GUI, skrypt nie), więc kotwica na liczbie pinowałaby zero. Inwarianty czerwienią się
    # natomiast w KAŻDEJ bazie — także w żywej `pf4` puszczonej tym samym skryptem, a to właśnie
    # tam ta populacja żyje.
    cfg_inv = config_source_invariants(con)
    n_reka = con.execute(
        "SELECT count(*) FROM frame WHERE config_source IS NOT NULL").fetchone()[0]
    out(f"\n§5.16 os sprzetu reka: klatek_ze_zrodlem={n_reka} naruszenia={cfg_inv}")
    crit("§5.16 każdy ręczny zestaw ma ślad człowieka w dzienniku (`actor='user:*'`)",
         cfg_inv["reka_bez_sladu"] == 0)
    crit("§5.16 źródło ręki NIE stoi nad pustą osią (`config_source` bez `config_id`)",
         cfg_inv["reka_bez_osi"] == 0)
    crit("§5.16 kalibracja NIE ma zestawu od ręki (kind-scoping domyka się z obu stron)",
         cfg_inv["reka_na_kalibracji"] == 0)

    # §5.9b enum źródeł osi OBIEKT ⊆ stałych, które go deklarują (jeden właściciel — S1).
    src = object_source_audit(con)
    if not src.ok:
        out(f"    ŹRÓDŁA SPOZA STAŁEJ — frame: {src.frame_unknown}, alias: {src.alias_unknown}")
    crit("§5.9b object_source i object_alias.source ⊆ resolve.objects (OBJECT/ALIAS_SOURCES)",
         src.ok)

    # §5.10 oś OBSERWATORIUM — 11 stanowisk (§8 klaster), populacje domykają, zero nieparsowalnego GPS
    # `sa` (klatki ze stanowiskiem) bierzemy z tego samego audytu, co §5.9 — jedna definicja liczby.
    sa = next(p.entities for p in parity if p.name == "frame.observatory_id")
    n_obs = con.execute("SELECT count(*) FROM observatory").fetchone()[0]
    gps_cards = con.execute(
        "SELECT count(*) FROM frame f "
        "WHERE EXISTS(SELECT 1 FROM cards c WHERE c.frame_id=f.id AND c.keyword='SITELAT') "
        "AND EXISTS(SELECT 1 FROM cards c WHERE c.frame_id=f.id AND c.keyword='SITELONG')").fetchone()[0]
    gps_null = con.execute(
        "SELECT count(*) FROM frame f WHERE f.observatory_id IS NULL "
        "AND EXISTS(SELECT 1 FROM cards c WHERE c.frame_id=f.id AND c.keyword='SITELAT') "
        "AND EXISTS(SELECT 1 FROM cards c WHERE c.frame_id=f.id AND c.keyword='SITELONG')").fetchone()[0]
    no_obs = con.execute("SELECT count(*) FROM frame WHERE observatory_id IS NULL").fetchone()[0]
    pops = con.execute(
        "SELECT o.id, o.lat, o.lon, COUNT(fr.id) AS n FROM observatory o "
        "LEFT JOIN observatory_canonical oc ON oc.canon_id=o.id "
        "LEFT JOIN frame fr ON fr.observatory_id=oc.id "
        "WHERE o.merged_into IS NULL GROUP BY o.id ORDER BY n DESC").fetchall()
    out(f"\n§5.10 oś obserwatorium: {n_obs} stanowisk, {sa} przypisanych, {gps_cards} z GPS-kartami, "
        f"{no_obs} bez stanowiska:")
    for oid, la, lo, n in pops:
        out(f"    #{oid:<3} {la:>10.5f}, {lo:>10.5f}  frames={n}")
    exp_gps = EXP_GPS_FRAMES_FULL if full else EXP_GPS_FRAMES_IMPORT
    crit_k("§5.10 stanowiska (klaster 4 km, §8)", EXP_OBSERVATORIES, n_obs)
    crit_k("§5.10 GPS-karty (§8; FULL niesie też XISF po P6b)", exp_gps, gps_cards)
    crit("§5.10 zero nieparsowalnego GPS (sonda: formaty czyste, 0 śmieci)", gps_null == 0)
    # Twarda brama na CZĘŚCIOWY/śmieciowy GPS (rec.#11): `gps_null` widzi tylko klatki z OBIEMA kartami,
    # więc lone-coord (jedna współrzędna → site_coords None → review) by mu umknął. review_summary łapie
    # OBA (śmieć i lone-coord); jego BRAK dowodzi zero cichego review. Pusta lista → event nie powstaje.
    obs_review = con.execute(
        "SELECT count(*) FROM event WHERE verb='observatory.review_summary'").fetchone()[0]
    crit("§5.10 zero cichego review (brak observatory.review_summary: śmieć/lone-coord)", obs_review == 0)
    crit("§5.10 populacje stanowisk domykają do przypisanych", sum(p[3] for p in pops) == sa)
    crit("§5.10 przypisane == GPS-karty (wszystkie sparsowane)", sa == gps_cards)
    if full:
        # ROZDZIELONE 2026-08-01: tor astro (FITS+XISF bez SITELAT/SITELONG) i tor DSLR (aparat bez
        # modułu GPS albo sentinel (0,0) → `None`). Jedna liczba 1037 nie odróżniłaby nowej dziury
        # w nagłówkach astro od kolejnej sesji z lustrzanką.
        no_obs_raw = con.execute(
            "SELECT count(*) FROM frame WHERE observatory_id IS NULL "
            "AND filetype IN (SELECT value FROM json_each(?))",
            (json.dumps(list(NO_OBJECT_CARD_FILETYPES)),)).fetchone()[0]
        out(f"    bez stanowiska: astro={no_obs - no_obs_raw}  RAW={no_obs_raw}")
        if ze_stosami:
            # Stacki nie niosą GPS (zmierzone: 0/128 ma SITELAT+SITELONG — PixInsight nie przenosi
            # tych kart do produktu integracji), więc ta liczba rośnie o CAŁĄ populację stosów.
            crit_k("§5.10 bez GPS w torze astro (z drzewem stosów)",
                   EXP_NO_GPS_STACKS, no_obs - no_obs_raw)
        else:
            crit_k("§5.10 bez GPS w torze astro (fits + xisf)", EXP_NO_GPS_FULL, no_obs - no_obs_raw)
        crit_k("§5.10 bez GPS w torze RAW (DSLR bez modułu GPS)", EXP_NO_GPS_RAW_FULL, no_obs_raw)

    # §5.11 oś KALIBRACJI (C2) — kotwice przepisu + DOMKNIĘCIE POPULACJI. Rozkład, który się nie
    # sumuje, to brama fałszywie zielona: „38 przepisów" nic nie znaczy, dopóki nie wiadomo, że
    # każda klatka kalibracyjna jest ALBO w przepisie, ALBO policzona jako niekompletna.
    if cal is not None:
        kinds = json.dumps(sorted(KIND_RECIPE))
        recipe_frames = con.execute(
            "SELECT count(*) FROM frame WHERE kind IN (SELECT value FROM json_each(?))",
            (kinds,)).fetchone()[0]
        profiled = con.execute(
            "SELECT count(*) FROM frame WHERE calibration_profile_id IS NOT NULL").fetchone()[0]
        by_class = dict(con.execute(
            "SELECT recipe_class, count(*) FROM calibration_profile GROUP BY recipe_class").fetchall())
        masters_off = con.execute(
            "SELECT count(*) FROM frame WHERE calibration_profile_id IS NULL "
            "AND kind IN ('master_dark','master_bias','master_flat')").fetchone()[0]
        unknown = con.execute("SELECT count(*) FROM frame WHERE kind='unknown'").fetchone()[0]
        facts = dict(con.execute(
            "SELECT source, count(*) FROM calibration_fact GROUP BY source").fetchall())
        out(f"\n§5.11 kalibracja: klatki z przepisem {profiled}/{recipe_frames} "
            f"(bez kompletu {cal.incomplete}); profile {by_class}; fakty {facts}")
        for powod, n in cal.reasons.items():
            out(f"    {n:5d}  {powod}")
        crit("§5.11 domknięcie populacji (każda klatka z przepisem ALBO policzona jako niekompletna)",
             profiled + cal.incomplete == recipe_frames and cal.frames == recipe_frames)
        crit("§5.11 idempotencja: 2. przebieg = zero wierszy i zero eventów encyjnych",
             bool(cal_idempotent))
        crit("§5.11 fakt ze ścieżki JEST zapisany (rename mastera nie przepnie klatki po cichu)",
             facts.get("path", 0) > 0 if full else True)
        if full:
            crit_k("§5.11 przepisy dark (każdy masterdark unikalny)", EXP_RECIPE_DARK,
                   by_class.get("dark", 0))
            crit_k("§5.11 przepisy flat (flaty + masterflaty, świeża baza)", EXP_RECIPE_FLAT,
                   by_class.get("flat", 0))
            # Przyczyna 38. klasy pinowana WPROST: gdyby doszła druga sprzeczna para, sama liczba
            # klas przesunęłaby się „legalnie" i nikt by nie zauważył, że archiwum zeznaje dwoma
            # głosami. Klasa jednoelementowa sama w sobie jest zwyczajna (Sony ma trzy) — dopiero
            # JEDNOELEMENTOWA + KLATKA O WIELU KOPIACH znaczy „kopie mówią co innego".
            sierota = con.execute(
                "SELECT count(*) FROM calibration_profile p WHERE p.recipe_class='flat' "
                "AND (SELECT count(*) FROM frame f WHERE f.calibration_profile_id=p.id) = 1 "
                "AND EXISTS(SELECT 1 FROM frame f JOIN location l ON l.frame_id=f.id "
                "           WHERE f.calibration_profile_id=p.id AND l.present=1 "
                "           GROUP BY f.id HAVING count(l.id) > 1)").fetchone()[0]
            crit_k("§5.11 klasa-sierota ze sprzecznej pary kopii (`frame 15645`, CLS↔L-Pro)",
                   EXP_RECIPE_ORPHAN_FULL, sierota)
            crit("§5.11 każdy master kalibracyjny MA przepis (mastery bez przepisu == 0)",
                 masters_off == 0)
            crit_k("§5.11 poza osią jawnie wykluczone (kind='unknown')", EXP_MASTERS_EXCLUDED_FULL,
                   unknown)

    # §5.12 RODOWÓD (C4) — DOMKNIĘCIE POPULACJI per relacja + szwy pinowane WPROST. Suma kubełków,
    # która nie schodzi do liczby lightów, to brama fałszywie zielona: rozjazd klucza (np. header
    # lightu vs ścieżka mastera) spuchłby „brak przepisu" i nadal się „zsumował".
    if lin is not None:
        lights = con.execute("SELECT count(*) FROM frame WHERE kind='light'").fetchone()[0]
        # kubełki luki po relacji (z reasons "<rel>: <powód>") + stan linked
        for rel in ("dark", "flat"):
            gaps = sum(n for powod, n in lin.reasons.items() if powod.startswith(f"{rel}:"))
            linked = lin.linked.get(rel, 0)
            out(f"\n§5.12 rodowód [{rel}]: linked {linked} + luki {gaps} == lighty {lights}")
            crit(f"§5.12 domknięcie populacji [{rel}] (linked + luki == lighty)",
                 linked + gaps == lights and lin.lights == lights)
        crit("§5.12 idempotencja: 2. przebieg = zero wierszy `calibration` i zero eventów rodowodu",
             bool(lin_idempotent))
        # Każdy kalibrator to MASTER — surowy dark/flat jako kalibrator = złamanie brief C2 §5.
        not_master = con.execute(
            "SELECT count(*) FROM calibration c JOIN frame f ON f.id=c.master_frame_id "
            "WHERE f.kind NOT LIKE 'master_%'").fetchone()[0]
        crit("§5.12 każdy kalibrator to master (kind LIKE 'master_%')", not_master == 0)
        # Reguła czasowa pinowana WPROST: light w profilu FLAT wielo-masterowym linkuje master
        # o min |Δ date_obs| (nie MIN id, nie pierwszy). Sprawdzamy na KAŻDYM takim wierszu.
        czasowa_ok = _check_nearest_in_time(con)
        crit("§5.12 reguła czasowa: każdy link flat = master o min |Δczasu| w profilu", czasowa_ok)
        if full:
            crit_k("§5.12 lighty z darkiem", EXP_LINEAGE_DARK, lin.linked.get("dark", 0))
            crit_k("§5.12 lighty z flatem", EXP_LINEAGE_FLAT, lin.linked.get("flat", 0))

    return results


def _check_nearest_in_time(con):
    """Dla KAŻDEGO wiersza `calibration` relacji flat: czy podpięty master ma min |Δ date_obs|
    wśród masterów swojego profilu? Liczone na `naming.header_dt` (jak produkcja), NIE `julianday`."""
    from horreum.naming import header_dt
    masters = {}
    for r in con.execute(
            "SELECT f.calibration_profile_id AS pid, f.id AS fid, h.date_obs AS d "
            "FROM frame f LEFT JOIN header h ON h.frame_id=f.id "
            "WHERE f.calibration_profile_id IS NOT NULL AND f.kind LIKE 'master_%'"):
        masters.setdefault(r["pid"], []).append((r["fid"], header_dt(r["d"])))
    for r in con.execute(
            "SELECT c.master_frame_id AS mid, hl.date_obs AS ld, mf.calibration_profile_id AS pid "
            "FROM calibration c JOIN frame mf ON mf.id=c.master_frame_id "
            "LEFT JOIN header hl ON hl.frame_id=c.light_frame_id "
            "WHERE c.relation='flat'"):
        cand = masters.get(r["pid"], [])
        if len(cand) <= 1:
            continue
        ld = header_dt(r["ld"])
        if ld is None:
            continue
        best = min(cand, key=lambda m: (abs((m[1] - ld).total_seconds())
                                        if m[1] is not None else float("inf"), m[0]))
        if best[0] != r["mid"]:
            return False
    return True


# ── (S) SUBSET: realny skan małego katalogu (czytniki + sha1 na realnych bajtach) ────────────────
def run_subset(subset_dirs, now, out):
    out("")
    out(f"== (S) SUBSET — realny scan_tree ({len(subset_dirs)} kat.) ==")
    sub_db = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_subset_s5.db")
    if os.path.exists(sub_db):
        os.remove(sub_db)
    con = db.open_db(sub_db)
    frame_review = 0
    for d in subset_dirs:
        s = scan_tree(con, d, volume="subset", now=now)
        frame_review += s.frame_review
        out(f"  skan {d}: files={s.files} frames_new={s.frames_new} headers={s.headers} "
            f"frame_review={s.frame_review}")

    # no-split §5.8 na realnych typach: ten sam model z FITS i XISF → 1 wiersz (float↔string)
    cams = con.execute(
        "SELECT c.model_canon, c.pixel_um, "
        "  SUM(f.filetype='fits') AS n_fits, SUM(f.filetype='xisf') AS n_xisf "
        "FROM camera c JOIN frame f ON f.camera_id=c.id GROUP BY c.id").fetchall()
    out("  kamery w subsecie (model, pixel, #fits, #xisf):")
    for mc, px, nf, nx in cams:
        flag = "  <- z OBU formatow = JEDEN wiersz (no-split realny)" if nf and nx else ""
        out(f"    {mc:12s} px={px} fits={nf} xisf={nx}{flag}")
    distinct_models = con.execute("SELECT count(DISTINCT model_canon) FROM camera").fetchone()[0]
    n_cam_rows = con.execute("SELECT count(*) FROM camera").fetchone()[0]
    split_ok = distinct_models == n_cam_rows
    out(f"  model_canon distinct={distinct_models} wierszy camera={n_cam_rows}  "
        f"[{_ok(split_ok)} — zero rozbić modelu]")
    out(f"  frame_review łącznie={frame_review} (oczekiwane 0 — realne pliki czytelne)  "
        f"[{_ok(frame_review == 0)}]")
    con.close()
    os.remove(sub_db)
    return split_ok and (frame_review == 0)


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser(
        description="Kryteria akceptacji PF-5 (read-only): import z dawcy LIVE + kryteria §5")
    ap.add_argument("--donor", required=True, help="ścieżka dawcy fitsmirror.db (LIVE, otwierany read-only)")
    ap.add_argument("--xisf-root", default=None,
                    help="drzewo z XISF do doskanu (np. <xisf-root>) - odtwarza pełny stan PF-4. "
                         "O1: skanowane są PODDRZEWA korzenia bez `STACKS`, więc plik leżący "
                         "wprost pod korzeniem kończy przebieg odmową")
    ap.add_argument("--stacks-root", default=None,
                    help="drzewo STOSÓW, musi być `<xisf-root>\\STACKS` - etap wciąga je zwykłym "
                         "skanem korzenia archiwum (gotowe obrazy jako `master_light`). Wymaga "
                         "`--xisf-root` (kotwice stosów są liczone na FULL, który `STACKS` odcina - O1)")
    ap.add_argument("--live-db", default=None,
                    help="ŻYWA baza Horreum (read-only) — rejestr napraw writebacku; bez niej "
                         "falsyfikator abortuje, gdy próbka trafi w plik naprawiony przez Horreum")
    ap.add_argument("--subset", default=None,
                    help="mały realny katalog (lub kilka po przecinku) do krzyż-czeku czytników/sha1")
    ap.add_argument("--work", default=None, help="ścieżka jednorazowej horreum.db (domyślnie obok skryptu)")
    ap.add_argument("--keep", action="store_true", help="nie usuwaj bazy roboczej po zakończeniu")
    args = ap.parse_args(argv)

    out = print
    now = datetime.now(timezone.utc).isoformat()
    work = args.work or os.path.join(os.path.dirname(os.path.abspath(__file__)), "_horreum_s5.db")

    # Kotwice etapu stosów są ZMIERZONE na stanie FULL — bez doskanu porównywałyby się z bazą,
    # której nikt nie mierzył. Odmowa jest tu uczciwsza niż przebieg dający liczby bez znaczenia.
    if args.stacks_root and not args.xisf_root:
        out("ACCEPTANCE ODMOWA: --stacks-root wymaga --xisf-root "
            "(kotwice etapu stosów zmierzono na stanie FULL, nie na samym imporcie).")
        return 2

    try:
        con, summary, testimony = build_import(args.donor, work, now, out, live_db=args.live_db)
    except ImportAbort as exc:
        out(f"\nACCEPTANCE ABORT (import z dawcy nie przeszedł): {exc}")
        return 1

    if args.xisf_root:
        doskan_xisf(con, args.xisf_root, now, out)

    stacks = stacks_idem = None
    if args.stacks_root:
        stacks, stacks_idem = doskan_stacks(con, args.xisf_root, args.stacks_root, now, out)

    cal, cal_idem = calibrate(con, now, out)
    lin, lin_idem = lineage(con, now, out)
    # Rodowód stosów PO kalibracji i rodowodzie kalibracji — kolejność bez znaczenia dla wyniku
    # (osie rozłączne), ale trzyma czytelny porządek raportu: najpierw archiwum, potem produkty.
    slin = slin_idem = slin_kept = None
    if args.stacks_root:
        slin, slin_idem, slin_kept = stack_lineage(con, now, out)
    results = check_criteria(con, summary, out, cal=cal, cal_idempotent=cal_idem,
                             lin=lin, lin_idempotent=lin_idem,
                             stacks=stacks, stacks_idempotent=stacks_idem,
                             slin=slin, slin_idempotent=slin_idem, slin_kept=slin_kept,
                             donor_testimony=testimony, now=now)
    con.close()

    subset_ok = True
    if args.subset:
        dirs = [d.strip() for d in args.subset.split(",") if d.strip()]
        subset_ok = run_subset(dirs, now, out)

    if not args.keep and os.path.exists(work):
        os.remove(work)

    out("")
    out("== PODSUMOWANIE ==")
    failed = [(lab, poch) for lab, ok, poch in results if not ok]
    for lab, poch in failed:
        out(f"  FAIL: {lab}")
        for linia in poch:
            out(f"        {linia}")
    out("  §8.1 (AST jednej klingi) i bramka clone'a — OSOBNE: pytest + procedura clone.")
    hard_ok = not failed and subset_ok
    out(f"  WYNIK: {'WSZYSTKO PASS' if hard_ok else f'{len(failed)} FAIL' + ('' if subset_ok else ' + subset')}")
    return 0 if hard_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
