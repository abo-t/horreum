r"""Pass OBECNOŚCI kopii (P5, Issue #7) — wykrywanie zniknięć plików z drzewa.

Skan jest przyrostowy i DOPISUJĄCY: wciąga nowe i zmienione pliki, ale nigdy nie mówi „tego już
nie ma". Bez tego passa każde skasowanie pliku na dysku zostawia w bazie kłamstwo „kopia jest",
o którym `writeback`/`naming`/`projection` dowiadują się dopiero przy próbie dotknięcia pliku.
Ten moduł domyka drugą stronę: porównuje ZAKRES bazy z realnym drzewem i zdejmuje obecność
(`present = 0`) tym kopiom, których dowodliwie NIE MA.

APPEND-ONLY (ŚWIĘTE): pass niczego nie kasuje — ani plików, ani wierszy. Znika wyłącznie
twierdzenie „plik pod tą ścieżką jest"; tożsamość frame'a (`sha1_data`), zeznanie, historia
i sam wiersz `location` zostają. Powrót pliku przywraca `present = 1` zwykłym re-odczytem skanu
(brama `scan._already_scanned` przepuszcza kopie nieobecne — D-V-6), więc `present=0` NIE jest
drzwiami jednokierunkowymi. Zapis idzie WYŁĄCZNIE przez jedną klingę
(`repo.mark_location_vanished`) — ten moduł nie wykonuje DML (meta-tripwir AST to potwierdza)
i nie mutuje dysku (`os.stat` czyta, więc modul świadomie ZOSTAJE poza `DOORS` w
`test_writeback_safety.py` — wpisanie go tam zwolniłoby go z tripwiru mutacji plików).

MECHANIKA (D-V — brief `PLAN_p5_znikniecia.md`):

    canonize_root(root)              -- forma literowa, odmowa UNC, root nie istnieje → abort
      → volume_serial(root) == volume?   -- PRZESŁANKA: przemapowana litera = cudze drzewo
      → iter_headers(root, excluded_out, errors_out)   -- jedno przejście (~12 700 plik/s)
      → zakres = lokacje (volume, prefiks root, rozszerzenie nagłówkonośne, present=1)
      → kandydaci = zakres \ przejście, minus poddrzewa odcięte i NIEPRZECZYTANE
      → HAMULEC (przed potwierdzeniami — nie płacimy 15 tys. `stat` po to, żeby przerwać)
      → potwierdzenie per plik (`scan.path_gone`: ENOENT/ENOTDIR = nie ma, reszta = nie wiem)
      → DRY: raport | apply: repo.mark_location_vanished(...) w jednym `run_id`

DLACZEGO PRZEJŚCIE, A NIE `stat` PO WIERSZACH BAZY (pomiar 2026-07-22 na `R:\ASTRO_`, 15 890
plików): przejście = 1,2 s, `stat` po wierszach = ~9 s (0,55 ms/plik po SMB). Ale rozstrzyga nie
koszt, tylko PRUNE: `stat` po wierszach nie wie, których katalogów skan nie oglądał, więc nie
odróżnia „nie ma" od „nie patrzyliśmy" — a pomylenie tych dwóch rzeczy kasuje obecność plikom,
które spokojnie leżą pod `_WBPP`.

TRZY RZECZY, KTÓRE NIE SĄ ZNIKNIĘCIEM (każda ma własny kubełek, żaden nie prowadzi do zapisu):
  - katalog ODCIĘTY prune'em (`_WBPP`/`_Review`) i katalog NIEPRZECZYTANY (`errors_out`) →
    `out_of_reach`: plik istnieje, tylko poza zasięgiem;
  - kandydat, który JEDNAK istnieje → `resurfaced`: to zwykle dryf wielkości liter DB↔dysk,
    a nie wyścig — i wtedy przyszły skan ZMINTUJE DRUGĄ lokację na ten sam plik (import traktuje
    ten stan jako twardy abort, `import_fitsmirror.py:271-278`). Raport wypisuje pełną listę;
  - `stat` bez rozstrzygnięcia (brak uprawnień, zerwany SMB) → `undecided`.
"""
import os
import uuid
from dataclasses import dataclass, field

from . import repo
from .gui import queries          # Qt-WOLNE (jak w projection.py) — puste gui/__init__.py
from .scan import HEADER_SUFFIXES, canonize_root, iter_headers, path_gone
from .volumes import volume_serial

# Hamulec masowy (D-V-4, progi RATYFIKOWANE przez usera 2026-07-22 — wariant ostrzejszy niż
# rekomendowany max(100, 5 %)). Przy 15 890 lokacjach próg wypada na 318 kopii. Progi bronią przed
# jednym realnym scenariuszem utraty: share zamontowany PUSTY w miejsce pełnego. Legalne sprzątanie
# większej sesji przechodzi przez `--force N` (deklaracja intencji), nie przez podnoszenie progu.
_BRAKE_MIN = 50
_BRAKE_FRACTION = 0.02


@dataclass
class PresenceSummary:
    """Wynik jednego przebiegu — liczby ROZŁĄCZNE tam, gdzie rozłączne być muszą: `confirmed_gone`
    + `resurfaced` + `undecided` ≤ `candidates` (mniej przy anulowaniu). `vanished` = ile realnie
    oznaczono (0 przy DRY i przy dryfie ścieżki)."""
    root: str = ""
    volume: str = ""
    run_id: object = None
    scoped: int = 0                # lokacje present=1 w zakresie (volume, root, rozszerzenia)
    walked: int = 0                # pliki nagłówkonośne znalezione na dysku
    excluded_dirs: list = field(default_factory=list)    # odcięte prune'em (_WBPP/_Review)
    unreadable_dirs: list = field(default_factory=list)  # NIEPRZECZYTANE przez os.walk (D-V-11)
    out_of_reach: int = 0          # wiersze pod katalogiem odciętym/nieprzeczytanym — POZA oceną
    candidates: int = 0            # zakres \ przejście, po odsiewie out_of_reach
    confirmed_gone: int = 0        # potwierdzone: system mówi „nie ma"
    resurfaced: int = 0            # kandydat JEDNAK istnieje (dryf casingu / wyścig)
    resurfaced_paths: list = field(default_factory=list)
    undecided: int = 0             # stat bez rozstrzygnięcia — raport, ZERO zapisu
    drifted: int = 0               # ścieżka zmieniona między planem a zapisem (rename) — pominięte
    frames_without_copy: int = 0   # KLATKI bez ani jednej obecnej kopii PO zapisie (≠ liczba kopii!)
    vanished: int = 0              # realnie oznaczone (0 przy DRY)
    gone_paths: list = field(default_factory=list)       # potwierdzone znikłe (raport, także DRY)
    cancelled: bool = False        # przerwane kooperatywnie na granicy kandydata — ZERO zapisu
    confirmed: bool = False        # czy pętla potwierdzeń w ogóle poszła (pod hamulcem: NIE)
    # DWA RÓŻNE FAKTY, celowo nie jedno pole: `brake` = „hamulec by zadziałał" (baner, przebieg mógł
    # mimo to dokończyć — DRY zawsze, apply za `--force N`); `aborted` = „ZATRZYMANO, nic nie zapisano".
    # Sklejone w jedno pole kłamały: przebieg z `--force` oznaczał 3 kopie i JEDNOCZEŚNIE raportował
    # ABORT, a CLI zwracało kod 1 po udanym zapisie.
    brake: object = None
    aborted: object = None


def _in_scope(path, prefix_cf):
    """Czy `path` należy do zakresu: leży pod rootem I jest plikiem NAGŁÓWKONOŚNYM.

    Prefiks porównujemy `casefold` (NTFS nie rozróżnia wielkości liter, a `location.path` bywa
    zapisany casingiem sprzed rename'u) — ale Z GRANICĄ SEPARATORA już wbudowaną w `prefix_cf`,
    bo gołe `startswith` na `R:\\ASTRO_` łyka `R:\\ASTRO_OLD` (cudze drzewo w zakresie).

    Rozszerzenie (D-V-10) odsiewa uniwersum, którego przejście NIE POTRAFI ZOBACZYĆ: `iter_headers`
    zwraca wyłącznie FITS+XISF, więc w dniu włączenia przebiegu DSLR/raw (`.ARW`/`.DNG`, PLAN §1.5)
    KAŻDA lokacja rawa stałaby się kandydatem do zniknięcia. Zakres musi być dokładnie tym, co walk
    umie wypatrzeć."""
    return (path.casefold().startswith(prefix_cf)
            and os.path.splitext(path)[1].lower() in HEADER_SUFFIXES)


def _under_any(path, barriers_cf):
    """Czy `path` leży pod którymś katalogiem-barierą (odciętym prune'em albo nieprzeczytanym).
    Bariery przychodzą Z SEPARATOREM na końcu — inaczej `_WBPP` łyka `_WBPPX`, który jest normalnie
    skanowanym katalogiem, i realne zniknięcie schowałoby się w `out_of_reach`."""
    p = path.casefold()
    return any(p.startswith(b) for b in barriers_cf)


def _brake_reason(summary):
    """Powód zatrzymania albo `None`. Liczony PRZED pętlą potwierdzeń — inaczej przy zerwanym SMB
    płacimy tysiące `stat` tylko po to, żeby powiedzieć „przerwane".

    `scoped == 0` jest tu tak samo ważne jak próg: literówka w serialu albo zły root dają zakres
    pusty, zero kandydatów i raport „nic nie znikło" NIEODRÓŻNIALNY od przebiegu zdrowego. Pass
    decydujący o zdejmowaniu obecności nie ma prawa milczeć na pustym zakresie (EXPECT)."""
    if summary.scoped == 0:
        return "zakres pusty (0 lokacji) — sprawdź --volume i root; brak danych to nie brak zniknięć"
    if summary.walked == 0:
        return f"drzewo puste (0 plików pod {summary.root}) — wolumin zamontowany, ale bez treści?"
    limit = max(_BRAKE_MIN, int(summary.scoped * _BRAKE_FRACTION))
    if summary.candidates > limit:
        return (f"kandydatów {summary.candidates} > próg {limit} "
                f"({_BRAKE_MIN} albo {_BRAKE_FRACTION:.0%} z {summary.scoped})")
    return None


def check(con, root, *, volume, apply=False, force=None, run_id=None, now,
          progress=None, should_cancel=None):
    """Jeden przebieg passa obecności. DRY DOMYŚLNIE (`apply=False`): raportuje i NIE dotyka bazy.

    DLACZEGO DRY JEST DOMYŚLNE, choć `present=0` cofa zwykły re-skan: `event` jest APPEND-ONLY,
    więc fałszywy przebieg zostawia w dzienniku tyle wierszy, ile kopii — stanu nie żal, dziennika
    nie cofnie nic. Wszystkie eventy jednego przebiegu spina `run_id` (audyt: „kto, kiedy, w jakim
    zakresie"), generowany jak w makrach (`macro.py:318`) albo podany jawnie w testach.

    HAMULEC (D-V-4) zatrzymuje TYLKO `apply`. W DRY jego powód ląduje w `brake` jako BANER, a raport
    wychodzi w całości — inaczej uczylibyśmy usera sięgać po `--force` (najgroźniejszą flagę) tylko
    po to, żeby COKOLWIEK zobaczyć. Pod hamulcem pomijamy jednak pętlę potwierdzeń (`confirmed`
    zostaje `False`): to jej koszt hamulec ma oszczędzić, a liczba 0 potwierdzonych znaczy wtedy
    „nie liczono", nie „nic nie znikło".

    `force` = DEKLARACJA INTENCJI, nie przełącznik: liczba potwierdzonych zniknięć, których user
    się spodziewa. Rozjazd (`confirmed_gone != force`) → abort BEZ zapisu, także gdy hamulec milczał.
    Gołe „przełam wszystko" nie istnieje — byłoby przyciskiem „oznacz cały wolumin jako zniknięty".

    ANULOWANIE (`should_cancel`) sprawdzane na granicy KANDYDATA i przerywa CAŁY zapis: lista
    kandydatów jest wtedy niepełna, a apply to jedna decyzja, nie N niezależnych. `progress(done,
    total, path, summary)` wołane synchronicznie — emisja sygnału Qt to robota callbacku GUI.

    Zwraca `PresenceSummary`. Rzuca (EXPECT) tylko z `canonize_root`: root UNC albo nieistniejący
    — to błąd wołania, nie stan danych."""
    summary = PresenceSummary(root=canonize_root(root), volume=volume)

    serial = volume_serial(summary.root)
    if serial != volume:
        # PRZESŁANKA (D-V-2): litera dysku jest efemeryczna. Przemapowane `R:` (inny share, inny NAS)
        # daje przejście po CUDZYM drzewie przy zakresie z naszego woluminu — każdy wiersz stałby się
        # kandydatem, a `stat` uczciwie potwierdziłby „nie ma" (bo tam ich nie ma). Precedens guardu:
        # `import_fitsmirror.py:254-258`.
        if volume == "?":
            summary.aborted = (
                f"wolumin nieustalony ('?') — pass zdejmuje obecność, więc musi wiedzieć, CZYJE "
                f"drzewo ogląda; pod {summary.root} jest {serial!r}")
        elif serial is None:
            summary.aborted = (f"nie da się odczytać serialu woluminu pod {summary.root} "
                               f"— zamontuj wolumin i powtórz")
        else:
            summary.aborted = (f"serial woluminu {serial!r} pod {summary.root} != podany {volume!r} "
                               f"— zamontowany jest inny wolumin niż zakres w bazie")
        return summary

    walked = iter_headers(summary.root, excluded_out=summary.excluded_dirs,
                          errors_out=summary.unreadable_dirs)
    summary.walked = len(walked)
    walked_set = {str(p) for p in walked}      # klucz BINARNY (case-sensitive, jak UNIQUE(volume,path)):
    # casefold scaliłby dwa LEGALNE, rozłączne wiersze różniące się wielkością liter i jedno realne
    # zniknięcie zginęłoby bez śladu (fałszywy negatyw jest niewykrywalny — inaczej niż fałszywy
    # pozytyw, który zatrzyma potwierdzenie).

    sep = os.sep
    prefix_cf = (summary.root.rstrip(sep) + sep).casefold()
    barriers_cf = tuple((d.rstrip(sep) + sep).casefold()
                        for d in summary.excluded_dirs + summary.unreadable_dirs)

    candidates = []
    for row in con.execute(
            "SELECT id, path FROM location WHERE volume = ? AND present = 1", (volume,)):
        path = row["path"]
        if not _in_scope(path, prefix_cf):
            continue
        summary.scoped += 1
        if path in walked_set:
            continue
        if _under_any(path, barriers_cf):
            summary.out_of_reach += 1          # istnieje, tylko poza zasięgiem — NIE zniknięcie
            continue
        candidates.append((row["id"], path))
    summary.candidates = len(candidates)

    summary.brake = _brake_reason(summary)
    if summary.brake is not None:
        if apply and force is None:
            summary.aborted = summary.brake    # zatrzymane: zero potwierdzeń, zero zapisu
            return summary
        if not apply:
            return summary                     # DRY: baner + pełne liczniki, bez kosztu potwierdzeń

    summary.confirmed = True
    gone = []
    for done, (loc_id, path) in enumerate(candidates, start=1):
        if should_cancel is not None and should_cancel():
            summary.cancelled = True
            break
        verdict = path_gone(path)
        if verdict is True:
            gone.append((loc_id, path))
            summary.gone_paths.append(path)
        elif verdict is False:
            summary.resurfaced += 1
            summary.resurfaced_paths.append(path)
        else:
            summary.undecided += 1
        if progress is not None:
            progress(done, len(candidates), path, summary)
    summary.confirmed_gone = len(gone)

    if not apply or summary.cancelled:
        return summary
    if force is not None and summary.confirmed_gone != force:
        summary.aborted = (f"--force {force} != potwierdzonych zniknięć {summary.confirmed_gone} "
                           f"— deklaracja nie zgadza się z dyskiem, nic nie zapisano")
        return summary

    summary.run_id = run_id or uuid.uuid4().hex
    for loc_id, path in gone:
        if repo.mark_location_vanished(
                con, location_id=loc_id, expected_path=path, root=summary.root,
                run_id=summary.run_id, now=now, forced=force is not None):
            summary.vanished += 1
        else:
            summary.drifted += 1               # rename między planem a zapisem albo już nieobecna
    # Kopie ≠ klatki: zniknięcie JEDNEJ z dwóch kopii nie odbiera klatce obecności. Powierzchnia
    # musi umieć powiedzieć obie liczby, inaczej obiecuje listę („pokaż zniknięte"), która bywa
    # PUSTA mimo oznaczonych kopii (wizytator P5 #3). Predykat z JEDNEGO właściciela.
    summary.frames_without_copy = len(queries.vanished_frame_ids(con))
    return summary
