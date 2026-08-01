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
      → pełny stan pf4 (czyta tylko ~331 nagłówków XISF, reszta stat-skip).
  (K) KALIBRACJA — `run_calibration` na gotowym stanie (po grouperze i resolverze) + kolejny przebieg
      jako dowód idempotencji. Oś przepisu jest bramkowana tu, bo jej kotwice (38 dark / 37 flat)
      zmierzono na pełnym archiwum, a mastery są XISF — bez doskanu nie ma czego liczyć.
      **Od P-G łańcuch kalibracji+rodowodu robi już `run_import`**, więc w trybie IMPORT ta faza
      jest przebiegiem DRUGIM (zera delt = dowód, nie regresja; pinuje to §4.6), a w FULL wciąż
      pierwszym dla masterów przyniesionych doskanem.
  (C) KRYTERIA — stage-aware (import vs full po obecności XISF): zestawia aktualia z EXP_* PF-3+PF-4.
  (S) SUBSET (opcja `--subset DIR`) — realny `scan_tree` małego katalogu do OSOBNEJ work.db:
      dowód, że czytniki astropy/XISF + sha1 działają na realnych bajtach; tu (i tylko tu) realny
      no-split FITS-float ↔ XISF-string, gdy katalog ma oba formaty.

§8.1 (meta-tripwir AST jednej klingi) i bramka izolowanego clone'a są OSOBNE — pytest
(`tests/test_repo_safety.py`) i procedura clone→venv→non-editable→pytest; ten skrypt je przypomina.

Użycie:
  python scripts/acceptance_s5.py --donor fitsmirror.db [--xisf-root <xisf-root>]
                                  [--live-db <zywa horreum.db>]
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
from datetime import datetime, timezone

# pakiet horreum z korzenia repo (skrypt leży w scripts/)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from horreum import db                                              # noqa: E402
from horreum.calibration import KIND_RECIPE, run_calibration      # noqa: E402
from horreum.lineage import run_lineage                           # noqa: E402
from horreum.grouper import NO_TELESCOPE_KINDS, run_grouper       # noqa: E402
from horreum.import_fitsmirror import (                                   # noqa: E402
    ImportAbort, open_donor, read_repaired_registry, run_import,
)
from horreum.resolver import (                                    # noqa: E402
    NO_OBJECT_CARD_FILETYPES, delta_report, run_resolver)
from horreum.scan import canonize_root, scan_tree                 # noqa: E402
from horreum.volumes import volume_serial                         # noqa: E402

# ── Kotwice EXP_* PF-3 (dawca) + PF-4 (doskan drzewa `R:`), z horreum_pf4.db 2026-07-02 ──────────
# UWAGA 2026-08-01: doskan NIE jest już „XISF-owy" — odkąd istnieje moduł DSLR (`e7dcdda`), ciągnie
# z `R:` także 763 RAW-y, więc baza FULL ma populacje, których żywa `pf4` (0 RAW-ów) nie zna.
# Stąd kotwice FULL są STAGE-AWARE i ROZDZIELONE astro/RAW — liczba sklejająca oba tory ukryłaby
# regresję w torze astro za kolejną sesją z lustrzanką.
# 5 kamer w IMPORT: (pixel_um, is_mono). Po naprawie nagłówków INSTRUME 100% — brak review kamer.
EXP_CAMERAS_IMPORT = {
    "ASI2600MM": (3.76, 1), "ASI2600MD": (3.76, 1), "ASI2600MC": (3.76, 0),
    "ASI294MC": (4.63, 0), "SONYA7RM3": (4.86, 0),
}
# RE-BASELINE FULL 2026-08-01 (odnowa bramki): doskan `R:` ciągnie też RAW-y, odkąd istnieje moduł
# DSLR (`e7dcdda`) — korpusy lustrzanek są na osi kamer TAK SAMO realne jak ASI. `pixel_um=None`
# NIE jest luką do załatania: EXIF nie podaje rozmiaru piksela, a wpisanie go z deklaracji byłoby
# DRUGIM właścicielem faktu (ta sama zasada, co „FOV z zeznania klatek" w planerze). Skutek do
# zapamiętania: dla DSLR nie policzymy FOV, więc planer ich nie kadruje.
# `SONYA7RM3` NIE jest nowa — ma 4.86 µm z `bayerpat` (FITS) i dodatkowo 301 klatek RAW; to ONA
# dowodzi, że oba tory schodzą się na jednym wierszu kamery zamiast go rozbijać.
EXP_CAMERAS_FULL = dict(EXP_CAMERAS_IMPORT,
                        SONYA7S=(None, 0), SONYA7M3=(None, 0), CANONEOS40D=(None, 0))
EXP_TELESCOPES_IMPORT = 8      # dawca FITS (§1): A140R/RC8/76EDPH/ED120R/RC6/N800/Sony135/ED120
# Po naprawie ED na realnym R: (2026-07-22, brief PLAN_p6_xisf_writeback §8) etykieta `ED` nie ma już
# nosiciela na osi: 7 masterflatów XISF dostało `ED120R`+789, a masterdarki z `TELESCOP='ED'` są POZA
# osią (kind-scoping, wariant B). Świeża baza nie powołuje 9. teleskopu — dług PF-4 spłacony.
# RE-BASELINE FULL 2026-08-01: 8 optyk astro + 4 OBIEKTYWY z EXIF, które wnoszą RAW-y (`FE 24-105mm
# F4 G OSS` 265 klatek, `105mm F1.4 DG HSM | Art 018` 36, `DT 0mm F0 SAM` 22, `FE 70-300mm` 8 —
# wszystkie w 100% RAW). Obiektyw JEST optyką, więc własny wiersz osi jest poprawny, nie śmieciem;
# do PLANERA i tak nie wchodzą, bo park jest jawną własnością usera (D-0731-12), nie derywatem.
EXP_TELESCOPES_FULL = 12       # 8 astro (jak IMPORT) + 4 obiektywy DSLR
EXP_TELESCOPES_RAW_ONLY_FULL = 4   # z tych 12 — powołane WYŁĄCZNIE przez klatki RAW
EXP_OBJECT_PCT_MIN = 85.0      # % obiektu na light/master_light (pf4=87.5; próg z zapasem)
# Stan PF-4 (pełny, po doskanie XISF) — XISF wnoszą dług review i degenerat:
EXP_UNCOMPUTABLE_FULL = 1      # masterflat OIII: bajt \x07 w XML → sha1_data nieobliczalne (degenerat)
EXP_FRAME_REVIEW_FULL = 1      # ten sam masterflat (kopia nieczytelna → review)
# Po kind-scopingu config (wariant B, 2026-07-22) dark/bias są POZA osią teleskopu: ich `config_id
# IS NULL` to stan docelowy, nie delta, więc `config.review` ich nie dotyczy. Zostaje 1 realna sprawa
# — masterflat Sony A7R3 o rodzaju `unknown` (ten sam degenerat, co §5.2). Było 7 (6 masterdarków + on).
EXP_CONFIG_REVIEW_FULL = 1     # `unknown` masterflat A7R3 — rodzaj wymaga decyzji, nie optyka
# …liczona POZA RAW-ami (2026-08-01). 432 RAW-y bez configu to stan UCZCIWY: zdjęcie z lustrzanki
# bez teleskopu w EXIF nie ma z czego powołać osi. Gdyby obie populacje wpadły do jednej kotwicy
# (433), pojawienie się DRUGIEJ realnej sprawy w torze astro schowałoby się za jednym zdjęciem
# mniej z aparatu — kotwica przestałaby pilnować tego, po co powstała.
EXP_CONFIG_REVIEW_RAW_FULL = 432
EXP_XISF_KINDS = {"flat": 11, "light": 202, "master_dark": 38, "master_flat": 73, "unknown": 2}
# Oś OBSERWATORIUM (PLAN_os_obserwatorium §8) — RE-BASELINE P6b (D-X-8a), świadomy i zmierzony:
# do P6a karty XISF NIE POWSTAWAŁY, więc GPS był de facto FITS-only. Od P6a skan wypełnia karty
# także dla XISF, a backfill (`horreum backfill-xisf`) dociąga je do lokacji sprzed P6a — 202 klatki
# XISF niosą SITELAT+SITELONG i wchodzą na oś. Wszystkie 202 mają JEDNĄ parę współrzędnych, 52 m od
# stanowiska „Szczecin, Będargowo" → ZERO nowych stanowisk (EXP_OBSERVATORIES bez ruchu), rusza się
# wyłącznie populacja. Kotwica jest STAGE-AWARE: etap IMPORT (dawca FITS, zero XISF) zostaje na
# 15 409 — gdyby liczba tam drgnęła, znaczyłoby to zmianę w torze FITS, nie skutek P6.
EXP_OBSERVATORIES = 11         # klaster 4 km: 24 distinct pary → 11 stanowisk (dom↔praca 4.385 km OSOBNE)
EXP_GPS_FRAMES_IMPORT = 15409  # dawca FITS: klatki z SITELAT+SITELONG (97.0%)
EXP_GPS_FRAMES_FULL = 15611    # + 202 XISF z GPS w kartach (P6b; wszystkie do stanowiska #5)
EXP_NO_GPS_FULL = 274          # bez GPS w torze ASTRO: 150 fits + 124 xisf (326 − 202 z GPS)
# RAW osobno (2026-08-01): 763 klatki DSLR, wszystkie bez stanowiska. To NIE brak danych — sentinel
# GPS (0,0) idzie w `resolve/observatory.py:67` na `None` świadomie („null island" nie jest miejscem),
# a aparat bez modułu GPS nie zapisuje nic. Rozdzielone od astro z tego samego powodu, co
# `config.review`: 763 przykryłoby ruch w populacji FITS/XISF.
EXP_NO_GPS_RAW_FULL = 763
# Oś KALIBRACJI (C2, brief PLAN_kalibracja_C_brief §3.2) — kotwice ZMIERZONE read-only PRZED kodem.
# Mastery są XISF, więc obie liczby dotyczą wyłącznie etapu FULL; w imporcie FITS nie ma czego liczyć.
EXP_RECIPE_DARK = 38           # 38 masterdarków → 38 przepisów (każdy master unikalny)
# 38, nie 37 z briefu §3.2: brief mierzył ŻYWĄ pf4, a ta ma o jedną klasę MNIEJ z powodu, który
# sam brief przewidział (§8). `frame 15645` ma DWIE kopie o sprzecznym zeznaniu — ten sam master
# leży w `…RC8_2600MC\CLS\` i `…\L-Pro\` (identyczne DANE → jedna klatka, różne nagłówki → jeden
# z nich przeżywa). Świeży skan zostaje przy PIERWSZYM odczycie (`CLS` — własna, jednoelementowa
# klasa → 38); na żywej pf4 backfill P6b przestawił zeznanie na `L-Pro`, gdzie klasa już istniała
# (→ 37). Sprzeczność siedzi w DANYCH i C2 ma ją POKAZAĆ, nie rozstrzygać — dlatego kotwicą jest
# liczba świeżej bazy, a osobne kryterium pinuje samą PRZYCZYNĘ (klasa-sierota z pary kopii).
EXP_RECIPE_FLAT = 38           # 2256 flatów + 73 masterflaty → 38 klas na ŚWIEŻEJ bazie
EXP_MASTERS_EXCLUDED_FULL = 2  # `frame 15629`/`15636`: kind='unknown' — POZA osią, jawnie wykluczone
# RODOWÓD (C4) — lighty powiązane z masterem po przepisie, ŚWIEŻA baza. Zmierzone przebiegiem
# `acceptance_s5 --full --live-db` 2026-07-23 (świeża baza z dawcy) ORAZ niezależnie na kopii żywej
# pf4 — obie dały te same liczby (profil-sierota CLS↔L-Pro §5.11 nie ruszył sum rodowodu). Domknięcie:
# dark 7331 + luki 6185 = flat 11938 + luki 1578 = 13 516 lightów.
EXP_LINEAGE_DARK = 7331        # lighty z masterdarkiem (reszta: 5978 brak przepisu + 207 niekompletny)
EXP_LINEAGE_FLAT = 11938       # lighty z masterflatem (reszta: 1455 brak przepisu + 123 brak mastera)
# KOTWICA NAWROTU P-D (D-PD-10): lighty, których nagłówek MILCZY o obiekcie. `delta_report` był na
# nie ślepy (mianownik wymaga `object_raw NOT NULL`), więc §5.7 świeciło zielono o klatkach, których
# nie widzi. Kotwica jest STAGE-AWARE i to nie jest ozdoba: w IMPORT baza powstaje z ZAMROŻONEGO
# dawcy, którego zeznanie dla tych plików nadal nie ma karty `OBJECT`, więc jedna liczba dla obu
# trybów świeciłaby na czerwono przy POPRAWNYM przebiegu. Zadaniem kotwicy jest wykrywać ZMIANĘ
# (nowa dostawa bez `OBJECT`), a nie być równa 25: liczba porusza się razem z `regions.json` —
# dawca niesie 108 lightów bez karty, z czego region rozwiązuje 83.
EXP_NAMELESS_IMPORT = 25       # ZMIERZONE przebiegiem IMPORT 2026-08-01 (`--donor` + `--live-db`),
# nie policzone z rachunku: dawca niesie 108 lightów bez karty `OBJECT`, region rozwiązuje 83,
# zostaje 25. Liczba jest STABILNA także po naprawie plików na `R:` — baza importu powstaje
# z ZAMROŻONEGO dawcy, którego zeznanie naprawa nie dotyka.
EXP_NAMELESS_FULL = 25         # ZMIERZONE po pilocie P-D na `R:` (2026-08-01), przebieg
# `--xisf-root R:\ASTRO_ --live-db`. **Przesłanka briefu §6 pkt 9 („po naprawie padnie na 0")
# OKAZAŁA SIĘ FAŁSZYWA i to jest tu udokumentowane, żeby nikt nie „poprawił" tej liczby z powrotem
# na 0:** baza akceptacji bierze `mtime` ze STANU NA DYSKU, ale zeznanie FITS (nagłówek, `file_sha1`,
# `header_hash`) z ZAMROŻONEGO dawcy — więc brama przyrostowa doskanu widzi `mtime` równy i pomija
# plik. Dowód: lokacja 4581 ma w bazie akceptacji `mtime` PO naprawie i `file_sha1` SPRZED niej,
# a jej dziennik nie zawiera ani jednego `location.refreshed` (same trzy zdarzenia `import:fitsmirror`).
# FULL nie ma więc jak zobaczyć naprawy na `R:` — jego 25 to ta sama populacja dawcy, co w IMPORT,
# i z tego samego powodu jest stabilna. Zadaniem obu kotwic jest łapać ZMIANĘ W DAWCY; nawrotu na
# ŻYWEJ bazie pilnuje `object_nameless` w raporcie dostawy (inna rola — patrz §6 pkt 9 briefu).
EXP_NAMELESS_RAW_FULL = 763    # lighty w formacie bez karty `OBJECT` (`resolver.NO_OBJECT_CARD_
# FILETYPES`). Zmierzone: 763/763 RAW-lightów bez `object_raw`, ZERO wyjątków — EXIF nie zna tego
# pola. Osobna kotwica, bo osobna droga naprawy (ręka, nie karta); zlanie z 25 dało 788 i sprawiło,
# że liczba nie pilnowała ANI populacji astro, ANI DSLR.


def _ok(cond):
    return "PASS" if cond else "FAIL"


# ── (I) IMPORT: dawca LIVE → świeża baza przez realny pipeline PF-3 ───────────────────────────────
def build_import(donor_path, work_path, now, out, live_db=None):
    """Zbuduj świeżą horreum.db z dawcy LIVE przez `run_import` (jedna klinga; §4.6 gate'y w środku).
    Dawca RO (`open_donor`). Zwraca (con, ImportSummary). Twarde złamanie → ImportAbort propaguje.

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
    return con, summary


# ── (X) XISF-DOSKAN: realny scan_tree po drzewie z XISF (odtwarza PF-4) ──────────────────────────
def doskan_xisf(con, xisf_root, now, out):
    """Po imporcie dołóż XISF realnym skanem (jak PF-4). FITS gate'owane mtime (skip), XISF wciągane;
    potem grouper+resolver. Volume z `volume_serial` (brama musi trafiać znane FITS)."""
    out("")
    out(f"== (X) XISF-DOSKAN: scan_tree {xisf_root} ==")
    root = canonize_root(xisf_root)
    volume = volume_serial(root)
    if volume is None:
        raise RuntimeError(f"volume_serial({root!r}) nieustalony — zamontuj wolumin XISF-roota")
    s = scan_tree(con, root, volume=volume, drive_letter=(os.path.splitdrive(root)[0] or None),
                  tier=None, now=now)
    out(f"  scan: files={s.files} frames_new={s.frames_new} skipped(mtime)={s.skipped} "
        f"frame_review={s.frame_review} dirs_excluded={s.dirs_excluded}")
    gs = run_grouper(con, now=now)
    rs = run_resolver(con, now=now)
    out(f"  grouper: {gs}")
    out(f"  resolver: {rs}")


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


# ── (C) KRYTERIA §5 na bazie zbudowanej z dawcy (stage-aware: import vs full) ─────────────────────
def check_criteria(con, summary, out, cal=None, cal_idempotent=None, lin=None, lin_idempotent=None):
    results = []                                    # (etykieta, PASS/FAIL)

    def crit(label, cond):
        results.append((label, bool(cond)))
        out(f"  [{_ok(cond)}] {label}")

    n_xisf = con.execute("SELECT count(*) FROM frame WHERE filetype='xisf'").fetchone()[0]
    full = n_xisf > 0
    stage = "FULL (import + doskan XISF = PF-4)" if full else "IMPORT (dawca FITS = PF-3)"
    exp_tel = EXP_TELESCOPES_FULL if full else EXP_TELESCOPES_IMPORT
    out("")
    out(f"== (C) KRYTERIA §5 — stan: {stage} ==")

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
        crit(f"§5.1 degenerat XISF ~{EXP_UNCOMPUTABLE_FULL} (OIII masterflat, bajt \\x07)",
             uncomp == EXP_UNCOMPUTABLE_FULL)
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
    cams_ok = set(cams) == set(exp_cams)
    px_mono_ok = all(mc in cams and cams[mc][1] == exp_cams[mc][0]
                     and cams[mc][2] == exp_cams[mc][1] for mc in exp_cams)
    crit(f"§5.3 {len(exp_cams)} kamer, piksel+mono zgodne (MM/MD mono, MC/294/Sony/DSLR kolor)",
         cams_ok and px_mono_ok)
    distinct_models = con.execute("SELECT count(DISTINCT model_canon) FROM camera").fetchone()[0]
    n_cam_rows = con.execute("SELECT count(*) FROM camera").fetchone()[0]
    crit("§5.8 zero rozbić modelu (distinct model_canon == wierszy camera)",
         distinct_models == n_cam_rows == len(exp_cams))
    pconf = con.execute("SELECT count(*) FROM camera WHERE pixel_conflict=1").fetchone()[0]
    crit("§5.3 pixel_conflict == 0 (brak rozjazdu piksela)", pconf == 0)

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
    crit(f"§5.4 liczba teleskopów == {exp_tel} (akt={len(tels)})", len(tels) == exp_tel)
    if full:
        # Rozdział, nie sama liczba: kotwica „12" milczałaby o tym, czy przybyło optyki astro,
        # czy kolejnego obiektywu. Obiektyw = oś powołana WYŁĄCZNIE klatkami RAW.
        raw_only = sum(1 for *_x, nfr, nraw in tels if nfr and nfr == nraw)
        out(f"    z tego powołane wyłącznie przez RAW (obiektywy DSLR): {raw_only}")
        crit(f"§5.4 osie wyłącznie-RAW == {EXP_TELESCOPES_RAW_ONLY_FULL} (obiektywy z EXIF)",
             raw_only == EXP_TELESCOPES_RAW_ONLY_FULL)
    suspect = con.execute("SELECT count(*) FROM event WHERE verb='telescope.review'").fetchone()[0]
    crit(f"§5.4 telescope.review MARTWY po PF-2 (akt={suspect})", suspect == 0)

    # §5.6 config bez cichego NULL: frame z headerem bez config_id ⟺ ma config.review.
    # KIND-AWARE (wariant B): dark/bias są poza osią teleskopu, więc ich NULL nie jest „cichy" —
    # jest docelowy. Predykat czerpie zbiór z `grouper.NO_TELESCOPE_KINDS` (jeden właściciel, SPOT),
    # ten sam, którego używa `resolver.review_state`; osobno raportujemy, ile klatek tak wyłączono.
    cfg = con.execute("SELECT count(*) FROM config").fetchone()[0]
    cfg_review = con.execute("SELECT count(*) FROM event WHERE verb='config.review'").fetchone()[0]
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
    out(f"\n§5.6 config={cfg} config.review={cfg_review} frame-bez-config-z-headerem={no_cfg_hdr} "
        f"(kalibracja poza osią={calib_null}, odpięte={unassigned})")
    crit("§5.6 zero cichego NULL (frame z headerem bez config == config.review)",
         no_cfg_hdr == cfg_review)
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
        crit(f"§5.6 config.review poza RAW ~{EXP_CONFIG_REVIEW_FULL} (`unknown` masterflat A7R3)",
             cfg_review - cfg_review_raw == EXP_CONFIG_REVIEW_FULL)
        crit(f"§5.6 config.review RAW == {EXP_CONFIG_REVIEW_RAW_FULL} (stan docelowy DSLR)",
             cfg_review_raw == EXP_CONFIG_REVIEW_RAW_FULL)
    else:
        crit("§5.6 config.review == 0 w imporcie FITS (nagłówki naprawione)", cfg_review == 0)

    # §5.7 obiekt — % na light/master_light przez REALNY delta_report (kalibracja świadomie poza)
    rep = delta_report(con, top=40)
    out(f"\n§5.7 obiekt: {rep.object_resolved}/{rep.object_resolved+rep.object_unresolved} "
        f"= {rep.object_pct}% (delta {rep.object_unresolved} w {len(rep.object_delta)} distinct)")
    for raw, n in rep.object_delta[:12]:
        out(f"    {n:5d}  {raw}")
    crit(f"§5.7 object_pct >= {EXP_OBJECT_PCT_MIN}% (akt={rep.object_pct}%)",
         rep.object_pct >= EXP_OBJECT_PCT_MIN)

    # §5.7b kotwica nawrotu P-D — lighty bez `object_raw` (poza mianownikiem procentu wyżej).
    # Dopóki kotwica nie jest zmierzona (None), pozycja RAPORTUJE liczbę i nie zapala bramki:
    # zaszycie liczby wziętej z rachunku zamiast z przebiegu byłoby dokładnie tym błędem,
    # który ta kotwica ma łapać.
    exp_nameless = EXP_NAMELESS_FULL if full else EXP_NAMELESS_IMPORT
    out(f"\n§5.7b bez nazwy w nagłówku (light/master_light): {rep.object_nameless}")
    if exp_nameless is None:
        out(f"    (kotwica NIEZMIERZONA dla trybu {'FULL' if full else 'IMPORT'} — "
            f"zaszyj EXP_NAMELESS_* po tym przebiegu)")
    else:
        crit(f"§5.7b object_nameless == {exp_nameless} (akt={rep.object_nameless})",
             rep.object_nameless == exp_nameless)
    # Bliźniacza populacja po drugiej stronie FORMATU: klatki, które nie mają JAK zeznać o obiekcie.
    # Liczona zawsze, pilnowana tylko w FULL — dawca jest FITS-only, więc w IMPORT jest z definicji 0
    # i osobne kryterium byłoby pustym rytuałem.
    out(f"    z tego format bez karty `OBJECT` (RAW): {rep.object_nameless_raw}")
    if full:
        crit(f"§5.7b object_nameless_raw == {EXP_NAMELESS_RAW_FULL} (DSLR — droga naprawy: ręka)",
             rep.object_nameless_raw == EXP_NAMELESS_RAW_FULL)
    else:
        crit("§5.7b zero RAW w imporcie FITS (dawca jest FITS-only)",
             rep.object_nameless_raw == 0)

    # §5.8 (full) — kinds XISF (dowód, że doskan wciągnął to co PF-4)
    if full:
        xk = dict(con.execute(
            "SELECT kind, count(*) FROM frame WHERE filetype='xisf' GROUP BY kind").fetchall())
        out(f"\n§5.8 kinds XISF: {xk}")
        crit(f"§5.8 kinds XISF == PF-4 {EXP_XISF_KINDS}", xk == EXP_XISF_KINDS)
        frev = con.execute("SELECT count(*) FROM event WHERE verb='frame.review'").fetchone()[0]
        crit(f"§5.8 frame.review ~{EXP_FRAME_REVIEW_FULL} (OIII masterflat)",
             frev == EXP_FRAME_REVIEW_FULL)

    # §5.9 encje == eventy (co do sztuki) — audyt jednej klingi kompletny
    out("\n§5.9 encje == eventy:")
    pairs = [
        ("camera", "camera.upserted"), ("frame", "frame.observed"),
        ("location", "location.added"), ("header", "header.recorded"),
        ("telescope", "telescope.proposed"), ("config", "config.proposed"),
        ("object", "object.upserted"), ("object_alias", "object.aliased"),
        ("observatory", "observatory.proposed"),
        ("calibration_profile", "calibration_profile.proposed"),
    ]
    all_match = True
    for ent, verb in pairs:
        ne = con.execute(f"SELECT count(*) FROM {ent}").fetchone()[0]
        nv = con.execute("SELECT count(*) FROM event WHERE verb=?", (verb,)).fetchone()[0]
        ok = ne == nv
        all_match &= ok
        out(f"    {ent:13s} {ne:6d} == {verb:20s} {nv:6d}  [{_ok(ok)}]")
    fa = con.execute("SELECT count(*) FROM frame WHERE config_id IS NOT NULL").fetchone()[0]
    va = con.execute("SELECT count(*) FROM event WHERE verb='config.assigned'").fetchone()[0]
    oa = con.execute("SELECT count(*) FROM frame WHERE object_id IS NOT NULL").fetchone()[0]
    vo = con.execute("SELECT count(*) FROM event WHERE verb='object.assigned'").fetchone()[0]
    sa = con.execute("SELECT count(*) FROM frame WHERE observatory_id IS NOT NULL").fetchone()[0]
    vs = con.execute("SELECT count(*) FROM event WHERE verb='observatory.assigned'").fetchone()[0]
    # Przypisanie przepisu — para trzyma się TYLKO na świeżej bazie (jak wszystkie tutaj): na żywej
    # re-przypisanie emituje `.unassigned`+`.assigned`, więc equality wymagałaby odjęcia odpięć.
    ca = con.execute(
        "SELECT count(*) FROM frame WHERE calibration_profile_id IS NOT NULL").fetchone()[0]
    vc = con.execute(
        "SELECT count(*) FROM event WHERE verb='calibration_profile.assigned'").fetchone()[0]
    out(f"    frame.config_id {fa} == config.assigned {va}  [{_ok(fa == va)}]")
    out(f"    frame.object_id {oa} == object.assigned {vo}  [{_ok(oa == vo)}]")
    out(f"    frame.observatory_id {sa} == observatory.assigned {vs}  [{_ok(sa == vs)}]")
    out(f"    frame.calibration_profile_id {ca} == calibration_profile.assigned {vc}  "
        f"[{_ok(ca == vc)}]")
    all_match &= (fa == va) and (oa == vo) and (sa == vs) and (ca == vc)
    crit("§5.9 encje == eventy (co do sztuki, łącznie z przypisaniami)", all_match)

    # §5.10 oś OBSERWATORIUM — 11 stanowisk (§8 klaster), populacje domykają, zero nieparsowalnego GPS
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
    crit(f"§5.10 {EXP_OBSERVATORIES} stanowisk (klaster 4 km, §8)", n_obs == EXP_OBSERVATORIES)
    crit(f"§5.10 GPS-karty == {exp_gps} (§8; FULL niesie +202 XISF po P6b)", gps_cards == exp_gps)
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
        crit(f"§5.10 bez GPS w torze astro == {EXP_NO_GPS_FULL} (150 fits + 124 xisf)",
             no_obs - no_obs_raw == EXP_NO_GPS_FULL)
        crit(f"§5.10 bez GPS w torze RAW == {EXP_NO_GPS_RAW_FULL} (DSLR bez modułu GPS)",
             no_obs_raw == EXP_NO_GPS_RAW_FULL)

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
            crit(f"§5.11 przepisy dark == {EXP_RECIPE_DARK} (38 masterdarków, każdy unikalny)",
                 by_class.get("dark", 0) == EXP_RECIPE_DARK)
            crit(f"§5.11 przepisy flat == {EXP_RECIPE_FLAT} (2256 flatów + 73 mastery, świeża baza)",
                 by_class.get("flat", 0) == EXP_RECIPE_FLAT)
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
            crit("§5.11 klasa-sierota ze sprzecznej pary kopii: dokładnie 1 (`frame 15645`, "
                 f"CLS↔L-Pro; akt={sierota})", sierota == 1)
            crit("§5.11 każdy master kalibracyjny MA przepis (mastery bez przepisu == 0)",
                 masters_off == 0)
            crit(f"§5.11 poza osią tylko {EXP_MASTERS_EXCLUDED_FULL} jawnie wykluczone "
                 f"(kind='unknown', akt={unknown})", unknown == EXP_MASTERS_EXCLUDED_FULL)

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
            if EXP_LINEAGE_DARK is not None:
                crit(f"§5.12 lighty z darkiem == {EXP_LINEAGE_DARK}",
                     lin.linked.get("dark", 0) == EXP_LINEAGE_DARK)
            if EXP_LINEAGE_FLAT is not None:
                crit(f"§5.12 lighty z flatem == {EXP_LINEAGE_FLAT}",
                     lin.linked.get("flat", 0) == EXP_LINEAGE_FLAT)

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
                    help="drzewo z XISF do doskanu (np. <xisf-root>) — odtwarza pełny stan PF-4")
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

    try:
        con, summary = build_import(args.donor, work, now, out, live_db=args.live_db)
    except ImportAbort as exc:
        out(f"\nACCEPTANCE ABORT (import z dawcy nie przeszedł): {exc}")
        return 1

    if args.xisf_root:
        doskan_xisf(con, args.xisf_root, now, out)

    cal, cal_idem = calibrate(con, now, out)
    lin, lin_idem = lineage(con, now, out)
    results = check_criteria(con, summary, out, cal=cal, cal_idempotent=cal_idem,
                             lin=lin, lin_idempotent=lin_idem)
    con.close()

    subset_ok = True
    if args.subset:
        dirs = [d.strip() for d in args.subset.split(",") if d.strip()]
        subset_ok = run_subset(dirs, now, out)

    if not args.keep and os.path.exists(work):
        os.remove(work)

    out("")
    out("== PODSUMOWANIE ==")
    failed = [lab for lab, ok in results if not ok]
    for lab in failed:
        out(f"  FAIL: {lab}")
    out("  §8.1 (AST jednej klingi) i bramka clone'a — OSOBNE: pytest + procedura clone.")
    hard_ok = not failed and subset_ok
    out(f"  WYNIK: {'WSZYSTKO PASS' if hard_ok else f'{len(failed)} FAIL' + ('' if subset_ok else ' + subset')}")
    return 0 if hard_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
