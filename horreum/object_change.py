r"""Zmiana obiektu klatki RAZEM z plikiem (AR-17 krok 3) - plan gestu „Zmień obiekt…” i „Uzgodnij”.

Decyzje Zdzinia: `E5-1` (2026-09-26 - folderami zarządza Horreum, folder bez spacji = forma
systemu plików kanonu, nagłówek ze spacją, jedna wersja na obiekt) i `D-1011-5` (2026-10-11 -
baza najpierw ręką, potem plik; per plik przeniesienie i karta razem albo wcale; jedno cofnięcie;
katalogi zakładane i usuwane przez gest zapisane w bazie; nazwa pliku ze wzoru „Nazw” z nowym
obiektem w tym samym ruchu).

TEN MODUŁ JEST CZYSTY: zero zapisu do bazy i do plików, zero Qt. Wejściem są wiersze read-modelu
(`gui.queries.object_change_rows`), wyjściem `ObjectChangePlan` - dokładnie to, co pokaże podgląd
i co zapisze sterownik. Dysk czyta wyłącznie przez wstrzykiwane `isdir`/`listdir` (istnienie celu,
forma istniejącego katalogu - `R:` nie rozróżnia wielkości liter, baza tak). Wykonanie: staging
`repo.stage_object_change` + sterownik `writeback.commit_object_change` (jedna operacja GUI),
cofnięcie `writeback.undo_object_change`.

DWA TRYBY JEDNEGO SILNIKA: `target` = `ObjectTarget` (gest „Zmień obiekt…” - baza dostaje nowy
obiekt ręką) albo `None` („Uzgodnij” z Porządków - obiekt zostaje, plik dogania obiekt, który
klatka już ma).

CEL PLIKU = folder z `resolve.paths.path_after_object_change` (forma systemu plików kanonu pod
kategorią z rodzaju obiektu) + nazwa z silnika „Nazw” (`naming.run_rename`: ten sam wzór, ta sama
polityka daty, kanon celu w tokenie obiektu) - jeden `os.rename` zmienia folder i nazwę
(D-1011-5 Q8).
Stos (`master_light`) nazwy ze wzoru lightów nie dostaje: archiwum stosów ma własny układ
(`naming.stack_name`, `<obiekt>_<YYYY-MM-DD>_…`), więc wymieniany jest wyłącznie człon obiektu,
a wersja stosu (`stack_variant`) bierze nazwę z nowej nazwy oryginału (`naming.variant_stack_name`).
"""
import dataclasses
import ntpath
import os
import re
import uuid

from . import card_rules, naming
from .resolve.frames import LIGHT_KINDS
from .resolve.paths import STACK_KIND, path_after_object_change, path_key


@dataclasses.dataclass(frozen=True)
class ObjectTarget:
    """Cel gestu „Zmień obiekt…”. `card_form` = forma karty `OBJECT` kanonu
    (`resolver.forma_karty_object`) - None, gdy kanon nie wraca z formy do siebie (znany tylko
    z aliasu): wtedy gest odmawia celu, zanim powstanie plan (obietnica „karta i folder razem”)."""
    canon: str
    catalog: str | None
    kind: str                      # objects.OBJECT_KINDS
    alias_norm: str | None         # nazwa wpisana w oknie → alias (jak `repo.user_assign_object`)
    card_form: str | None


@dataclasses.dataclass(frozen=True)
class ObjectChangeItem:
    """Jedna klatka do zmiany. `new_path` None = plik już stoi w folderze obiektu z właściwą nazwą;
    `mkdirs` = katalogi do założenia od najpłytszego; `card_op` None = karta już w formie albo
    format bez karty (RAW). `expected_*` = kotwice z chwili podglądu (rename: `mtime`, karta:
    `header_hash`, ręka: trójca `(object_id, object_source, object_cleared_id)`)."""
    frame_id: int
    location_id: int
    old_path: str
    new_path: str | None
    mkdirs: tuple[str, ...]
    card_op: str | None            # 'set' | 'add' | None
    card_old: str | None
    card_new: str | None
    expected_header_hash: str | None
    expected_mtime: str
    expected_object: tuple
    object_change: bool            # czy baza zmienia obiekt tej klatki


@dataclasses.dataclass(frozen=True)
class ObjectChangeSkip:
    """Klatka, której gest nie ruszy - z powodem dla człowieka."""
    frame_id: int
    path: str
    reason: str


@dataclasses.dataclass(frozen=True)
class ObjectChangeWarning:
    """Ostrzeżenie bez blokady - dziś: przeniesienie CZĘŚCI wejść stosu (żniwa liczą siedzibę stosu
    z jednego folderu lightów). `frame_ids` = klatki planu, których dotyczy."""
    frame_ids: tuple[int, ...]
    text: str


@dataclasses.dataclass(frozen=True)
class ObjectChangePlan:
    """`rmdirs` = katalogi źródłowe, które po wykonaniu CAŁEGO planu będą puste i sterownik je
    usunie (od najgłębszego) - podgląd mówi o tej mutacji dysku, zanim zajdzie."""
    run_id: str
    target: ObjectTarget | None
    items: tuple[ObjectChangeItem, ...]
    skipped: tuple[ObjectChangeSkip, ...]
    warnings: tuple[ObjectChangeWarning, ...] = ()
    rmdirs: tuple[str, ...] = ()


# Powód, którym `naming.run_rename` oddaje klatkę, gdy wzór zostawia nazwę bez zmian - dla planu to
# nie pominięcie, tylko brak zmiany nazwy (test pinuje zgodność z silnikiem nazw).
_NAZWA_BEZ_ZMIAN = "nazwa bez zmian"

# Układ nazwy stosu w archiwum (`naming.stack_name`): człon obiektu, potem data `DATE-OBS` stosu.
# Człon obiektu bywa wieloczłonowy (`C2025A6_Lemmon_2025-10-19_…`), więc dopasowanie leniwe do
# pierwszej daty - tokeny obiektu daty nie udają.
_UKLAD_STOSU = re.compile(r"^(?P<obiekt>.+?)_(?P<reszta>\d{4}-\d{2}-\d{2}_.+)$")


class _Odmowa(Exception):
    """Pozycja pominięta z powodem - wewnętrzny sygnał planera, nie wychodzi poza moduł."""


class _Dysk:
    """Odczyt dysku planera wyłącznie przez wstrzykiwane `isdir`/`listdir`, z pamięcią katalogów:
    jeden `listdir` na katalog wsadu (308 plików w 6 folderach = 6 odczytów po SMB, nie 308).

    WIRTUALNY STAN PLANU: katalogi ZAPLANOWANE do założenia (`_planowane`, klucz `path_key`) - pierwsza
    pozycja ustala pisownię nowego segmentu, każda następna bierze tę samą. Bez tego dwa pliki
    z podfolderami `Rig\\Ha` i `rig\\Ha` pod nieistniejącym folderem obiektu dostałyby dwie pisownie
    jednego katalogu `R:`, a baza dwie pisownie jednej ścieżki."""

    def __init__(self, isdir, listdir):
        self._isdir, self._listdir, self._pamiec, self._planowane = isdir, listdir, {}, {}

    def wpisy(self, katalog):
        """`(nazwy, {casefold: nazwa})` katalogu; błąd odczytu → `_Odmowa` (pozycja z powodem,
        nie wywrócony podgląd całego wsadu)."""
        klucz = path_key(katalog)
        if klucz not in self._pamiec:
            try:
                nazwy = sorted(self._listdir(katalog))
            except OSError as exc:
                self._pamiec[klucz] = exc
            else:
                self._pamiec[klucz] = (set(nazwy), {n.casefold(): n for n in reversed(nazwy)})
        wynik = self._pamiec[klucz]
        if isinstance(wynik, OSError):
            raise _Odmowa(f"katalog celu nieczytelny ({katalog}): {wynik}")
        return wynik

    def katalog(self, cel, stary):
        """Katalog celu w pisowni Z DYSKU + katalogi do założenia, od najpłytszego.

        `R:` nie rozróżnia wielkości liter, baza tak (D-1011-5) - katalog istniejący w innej
        pisowni (`ic405` wobec kanonu `IC405`) bierze formę z dysku, inaczej baza dostałaby drugą
        pisownię tej samej ścieżki. Wspólny z katalogiem źródłowym początek bierze pisownię ścieżki
        z bazy (skan zapisuje formę z dysku), resztę rozstrzyga `listdir` rodzica (`casefold`).
        Poziom, którego nie ma, i wszystkie pod nim idą do założenia; plik w miejscu katalogu =
        `_Odmowa`. Poziom zaplanowany już przez wcześniejszą pozycję bierze jej pisownię.

        Każda pozycja niesie PEŁNY łańcuch katalogów, których potrzebuje (także zaplanowanych
        wcześniej) - pozycja pominięta później albo odbita w sterowniku nie zostawia następnej
        bez katalogu. Łańcuch jest jeden, bo pisownia jest jedna; powtórkę między pozycjami
        sterownik rozpoznaje na dysku i w `run_dir` (bez wielkości liter)."""
        czesci = re.split(r"([\\/]+)", cel)
        pozycje = [j for j in range(0, len(czesci), 2) if czesci[j]]
        stare = [s for s in re.split(r"[\\/]+", stary) if s]
        k = 0
        while (k < min(len(pozycje), len(stare))
               and czesci[pozycje[k]].casefold() == stare[k].casefold()):
            czesci[pozycje[k]] = stare[k]
            k += 1
        mkdirs = []
        for j in pozycje[k:]:
            zaplanowany = self._planowane.get(path_key("".join(czesci[:j + 1])))
            if zaplanowany is not None:
                czesci[j] = zaplanowany
            elif not mkdirs:
                nazwy, bez_wielkosci = self.wpisy("".join(czesci[:j]))
                na_dysku = czesci[j] if czesci[j] in nazwy else bez_wielkosci.get(czesci[j].casefold())
                if na_dysku is not None:
                    czesci[j] = na_dysku
                    if not self._isdir("".join(czesci[:j + 1])):
                        raise _Odmowa(f"w miejscu katalogu celu stoi plik: {''.join(czesci[:j + 1])}")
                    continue
            mkdirs.append("".join(czesci[:j + 1]))
        for j in pozycje[len(pozycje) - len(mkdirs):]:
            self._planowane.setdefault(path_key("".join(czesci[:j + 1])), czesci[j])
        return "".join(czesci), tuple(mkdirs)


def _powod_klatki(r, target):
    """Powód, dla którego klatki gest nie ruszy z samego jej stanu (bez celu i dysku), albo None."""
    if r["kind"] not in LIGHT_KINDS:
        return f"rodzaj „{r['kind']}” nie ma obiektu z definicji - gest dotyczy lightów i stosów"
    if r["retired_at"] is not None:
        return "klatka wycofana z archiwum"
    if r["superseded_by"] is not None:
        return "klatka zastąpiona inną (podmiana pliku)"
    if r["n_present"] == 0:
        return "brak obecnej kopii"
    if r["n_present"] > 1:
        return f"wiele obecnych kopii ({r['n_present']}) - jedna klatka, jeden folder obiektu"
    if r["isolated"]:
        return ("kopia izolowana przerwanym albo niedokończonym zapisem w miejscu - najpierw "
                "odzysk albo dokończenie w Porządkach")
    if r["mtime"] is None:
        return "kopia bez mtime - brak kotwicy przeniesienia"
    if target is None and r["canon"] is None:
        return "klatka bez obiektu - nie ma czego uzgadniać"
    return None


def _karta(r, comment_loss_route):
    """`(card_op, card_new)` pozycji albo `_Odmowa`, gdy karta jest potrzebna, a zapisu nie będzie -
    wtedy plik zostaje w całości (D-1011-5 Q2: przeniesienie i karta razem albo wcale; RAW i region
    przy „Uzgodnij” karty nie mają, więc przenoszą się bez niej). Bramka bazy (`card_skip`, ta sama
    co w ujednoliceniu karty) plus dwie przepowiednie pisarza: reguły karty FITS 4.0
    (`card_rules.card_violation`) i utrata zastanego komentarza (`writeback.comment_loss_route`) -
    obie odmawiają w obu drogach zapisu, więc podgląd ma je pokazać, nie sterownik."""
    if not r["card_applicable"]:
        return None, None
    if r["card_skip"] is not None:
        raise _Odmowa(f"karta OBJECT nie do zapisania ({r['card_skip']}) - plik zostaje, bo karta "
                      f"i folder idą razem")
    nowa = r["card_form"]
    if nowa is None:
        raise AssertionError(f"klatka {r['frame_id']}: karta do zapisu bez formy i bez powodu bramki")
    if r["card"] == nowa:
        return None, nowa
    op = "set" if r["card_present"] else "add"         # pusta karta stoi w nagłówku - `set`
    naruszenie = card_rules.card_violation("OBJECT", nowa, None, new_card=op == "add")
    if naruszenie is not None:
        raise _Odmowa(f"karta OBJECT: {naruszenie.reason}")
    if op == "set":
        odmowa = comment_loss_route(r["filetype"], "OBJECT", nowa, r["card_comment"])
        if odmowa is not None:
            raise _Odmowa(f"karta OBJECT: {odmowa}")
    return op, nowa


def _puste_po_planie(cele, wiersz, dysk, writeback):
    """Katalogi źródłowe, które po wykonaniu CAŁEGO planu zostaną puste - te, które sterownik usunie
    na końcu przebiegu (`writeback._sprzatnij_po_zapisie`), liczone TĄ SAMĄ regułą: kandydaci to
    poziomy od wspólnego przodka starej i nowej ścieżki (bez niego) w dół do katalogu starej ścieżki,
    wyłącznie dla pozycji z przeniesieniem (`_wspolny_przodek`, `_poziomy_pod` sterownika - jedno
    źródło reguły). Katalog jest pusty po planie, gdy każdy jego wpis (`listdir`, pamięć `_Dysk`) to
    plik planu, który z niego wyjeżdża, albo podkatalog, który też się opróżni - i gdy żaden plik
    planu do niego (ani pod niego) nie przyjeżdża. Plik spoza bazy (`.txt`), plik pozycji pominiętej
    albo katalog nieczytelny = katalog zostaje. Od najgłębszego, jak w sterowniku."""
    kandydaci, wyjezdzaja, przyjazdy = {}, {}, []
    for fid, (nowa, _) in cele.items():
        if nowa is None:
            continue
        stara = wiersz[fid]["path"]
        katalog = ntpath.dirname(stara)
        wyjezdzaja.setdefault(path_key(katalog), set()).add(ntpath.basename(stara).casefold())
        przyjazdy.append(path_key(nowa))
        wspolny = writeback._wspolny_przodek({"old_path": stara, "new_path": nowa})
        for k in writeback._poziomy_pod(wspolny, katalog):
            kandydaci.setdefault(path_key(k), k)
    puste, wynik = set(), []
    for klucz, k in sorted(kandydaci.items(),
                           key=lambda kv: (-writeback._glebokosc(kv[1]), kv[0])):
        if any(p.startswith(klucz + "\\") for p in przyjazdy):
            continue
        try:
            nazwy, _ = dysk.wpisy(k)
        except _Odmowa:
            continue
        if all(n.casefold() in wyjezdzaja.get(klucz, ()) or path_key(ntpath.join(k, n)) in puste
               for n in nazwy):
            puste.add(klucz)
            wynik.append(k)
    return tuple(wynik)


def _nazwa_stosu(nazwa, canon):
    """Nazwa stosu po zmianie obiektu: człon obiektu układu `naming.stack_name` wymieniony na token
    obiektu kanonu celu (ten sam, który składa `naming.compose_name`), reszta bez zmian. Nazwa spoza
    układu zostaje - nie niesie obiektu, więc nie ma w niej czego poprawiać."""
    m = _UKLAD_STOSU.match(nazwa)
    if m is None:
        return nazwa
    token, _ = naming.compose_name({"kind": STACK_KIND, "object_canon": canon}, None,
                                   template=("object",))
    return f"{token}_{m.group('reszta')}"


def plan_object_change(rows, *, target, template, library_root, location_at, run_id=None,
                       isdir=os.path.isdir, listdir=os.listdir, date_source="date_obs",
                       offset_hours=0) -> ObjectChangePlan:
    """Wiersze read-modelu (`gui.queries.object_change_rows`, policzone dla TEGO `target`) →
    `ObjectChangePlan`. Kontrakt: `brief/FALA10_zmien_obiekt.md` §4.1 i §8 (§8 wygrywa).

    PARAMETRY: `target` - `ObjectTarget` albo None („Uzgodnij”); `template` - wzór „Nazw” (lista
    albo dict per typ, `naming._pick_template`); `date_source`/`offset_hours` - polityka daty jak
    w pasku „Nazw” (`naming.run_rename`, zawsze z drugim źródłem w zapasie); `library_root` -
    korzeń archiwum (`resolver.library_root_from_db`, kotwica drzewa stosów); `location_at` -
    `(volume, path) → frozenset[location_id]` (`gui.queries.location_lookup`), kolizja w bazie;
    `isdir`/`listdir` - jedyny dostęp do dysku.

    POZYCJA (`ObjectChangeItem`): katalog z `path_after_object_change` w pisowni z dysku + nazwa
    (lighty: `naming.run_rename` z kanonem celu w tokenie obiektu; stos: `_nazwa_stosu`; wersja
    stosu: `naming.variant_stack_name` z nowej nazwy oryginału, w katalogu oryginału). Cel równy
    źródłu po normalizacji Windows i `casefold` → `new_path` None (sama zmiana pisowni nie jest
    robotą tego gestu). Karta: `set`/`add` na formę celu albo None.

    POMINIĘCIA (`ObjectChangeSkip`, zdanie PL dla człowieka): stan klatki (`_powod_klatki`), plik
    spoza pozycji obiektu, kanon nie do postawienia jako folder, karta potrzebna a nie do zapisania
    (cały plik zostaje), nazwa nie do złożenia, kolizja celu we wsadzie, na dysku (`listdir`
    katalogu celu) albo w bazie (inna lokacja), wersja stosu w innym katalogu niż oryginał (oba),
    połowa pary stosu pominięta (druga też), pozycja bez żadnej zmiany.

    OSTRZEŻENIA (`ObjectChangeWarning`): przeniesienie rozdziela wejścia stosu między foldery
    (żniwa liczą siedzibę stosu z jednego folderu lightów, `harvest._light_tail`) - nie blokada,
    ręka może rozdzielić świadomie.

    KATALOGI DO USUNIĘCIA (`rmdirs`): źródłowe, które po całym planie zostaną puste - sterownik usuwa
    je na końcu przebiegu, więc podgląd musi to powiedzieć (`_puste_po_planie`, reguła sterownika).

    EXPECT: cel bez formy karty (`target.card_form` None - okno odmawia go przed planem), wiersze
    policzone dla innego celu, cel w drzewie roboczym `_WBPP`/`_Review` (niemożliwy z konstrukcji
    reguły pozycji) → wyjątek, nie plan.

    Importy `writeback` (astropy) i `scan` w ciele funkcji - jak `macro.plan_object_card_form`:
    moduł planu importuje się bez nich."""
    from . import writeback
    from .scan import EXCLUDED_DIR_NAMES
    if target is not None and target.card_form is None:
        raise ValueError(f"cel {target.canon!r} bez formy karty OBJECT - gest odmawia go przed "
                         f"planem (karta i folder razem)")
    naming.validate_template(template)
    rows = list(rows)
    canon_celu = target.canon if target is not None else None
    for r in rows:
        if r["target_canon"] != canon_celu:
            raise ValueError(f"wiersz klatki {r['frame_id']} policzony dla celu "
                             f"{r['target_canon']!r}, plan dla {canon_celu!r}")
    run_id = run_id or uuid.uuid4().hex
    dysk = _Dysk(isdir, listdir)
    wiersz = {int(r["frame_id"]): r for r in rows}
    pominiete: dict[int, str] = {}
    robocze: dict[int, dict] = {}

    # 1. Stan klatki, folder celu, karta, katalog z dysku.
    for fid, r in wiersz.items():
        try:
            powod = _powod_klatki(r, target)
            if powod is not None:
                raise _Odmowa(powod)
            canon = target.canon if target is not None else r["canon"]
            rodzaj = target.kind if target is not None else r["object_kind"]
            try:
                cel = path_after_object_change(r["path"], canon, r["kind"], library_root,
                                               object_kind=rodzaj)
            except ValueError as exc:
                raise _Odmowa(f"cel, którego system plików nie przyjmie: {exc}") from None
            if cel is None:
                raise _Odmowa("plik nie stoi na pozycji obiektu w drzewie archiwum - nie ma "
                              "folderu obiektu, do którego mógłby trafić")
            if r["folder_twins"]:
                raise _Odmowa(f"folder obiektu {canon!r} ma tę samą nazwę co folder innego "
                              f"obiektu ({', '.join(r['folder_twins'])}) - pliki dwóch obiektów "
                              f"trafiłyby do jednego folderu")
            if any(s.casefold() in EXCLUDED_DIR_NAMES for s in re.split(r"[\\/]+", cel)):
                raise AssertionError(f"cel w drzewie roboczym (_WBPP/_Review): {cel}")
            card_op, card_new = _karta(r, writeback.comment_loss_route)
            glowa = ntpath.dirname(cel)
            sep = cel[len(glowa)] if cel[len(glowa):len(glowa) + 1] in ("\\", "/") else "\\"
            katalog, mkdirs = dysk.katalog(glowa, ntpath.dirname(r["path"]))
        except _Odmowa as exc:
            pominiete[fid] = str(exc)
            continue
        robocze[fid] = {"canon": canon, "katalog": katalog, "sep": sep, "mkdirs": mkdirs,
                        "card_op": card_op, "card_new": card_new,
                        "object_change": target is not None and r["canon"] != target.canon}

    # 2. Nazwy: lighty silnikiem „Nazw” (ścieżka już w katalogu celu - token `folder` widzi nowy
    #    folder), stosy wymianą członu obiektu.
    swiatla = {fid: dict(wiersz[fid], object_canon=p["canon"],
                         path=p["katalog"] + p["sep"] + ntpath.basename(wiersz[fid]["path"]))
               for fid, p in robocze.items() if wiersz[fid]["kind"] != STACK_KIND}
    if swiatla:
        run = naming.run_rename(swiatla, targets_fn=lambda ids: [swiatla[i] for i in ids],
                                source=date_source, offset_hours=offset_hours, template=template,
                                fallback=True, run_id=run_id)
        for pv in run.touched:
            robocze[pv.frame_id]["nazwa"] = ntpath.basename(pv.new_path)
        for sk in run.skipped:
            if sk.reason == _NAZWA_BEZ_ZMIAN:
                robocze[sk.frame_id]["nazwa"] = ntpath.basename(wiersz[sk.frame_id]["path"])
            else:
                pominiete[sk.frame_id] = f"nazwa pliku: {sk.reason}"
                del robocze[sk.frame_id]
    for fid, p in robocze.items():
        if wiersz[fid]["kind"] == STACK_KIND:
            p["nazwa"] = _nazwa_stosu(ntpath.basename(wiersz[fid]["path"]), p["canon"])

    # 3. Wersja stosu jedzie z oryginałem: ten sam katalog celu, nazwa z nowej nazwy oryginału.
    for fid in sorted(robocze):
        para = wiersz[fid]["variant_of"]
        if para is None:
            continue
        oryginal, wariant = para
        if oryginal not in robocze:
            if oryginal not in pominiete:
                raise AssertionError(f"wersja stosu {fid} bez oryginału {oryginal} w wierszach")
            continue                                   # połowa pominięta - krok 6
        po = robocze[oryginal]
        if (path_key(ntpath.dirname(wiersz[fid]["path"]))
                != path_key(ntpath.dirname(wiersz[oryginal]["path"]))):
            pominiete[fid] = "wersja stosu leży w innym katalogu niż oryginał - para jedzie razem"
            del robocze[fid]
            continue
        nazwa = naming.variant_stack_name(po["nazwa"], wariant)
        if nazwa is None:
            pominiete[fid] = (f"nazwa wersji stosu nie wynika z nazwy oryginału ({po['nazwa']}) - "
                              f"para jedzie razem")
            del robocze[fid]
            continue
        robocze[fid].update(katalog=po["katalog"], sep=po["sep"], mkdirs=po["mkdirs"], nazwa=nazwa)

    # 4. Cel pliku, brak zmian, kolizja na dysku.
    cele: dict[int, tuple] = {}
    for fid in sorted(robocze):
        p, r = robocze[fid], wiersz[fid]
        nowa, mkdirs = p["katalog"] + p["sep"] + p["nazwa"], p["mkdirs"]
        if path_key(nowa) == path_key(r["path"]):
            nowa, mkdirs = None, ()
        if nowa is None and p["card_op"] is None and not p["object_change"]:
            pominiete[fid] = "bez zmian - plik w folderze obiektu, nazwa i karta zgodne"
            continue
        if nowa is not None and not mkdirs:
            try:
                _, bez_wielkosci = dysk.wpisy(p["katalog"])
            except _Odmowa as exc:
                pominiete[fid] = str(exc)
                continue
            if p["nazwa"].casefold() in bez_wielkosci:
                pominiete[fid] = f"na dysku stoi już plik pod ścieżką celu: {nowa}"
                continue
        cele[fid] = (nowa, mkdirs)

    # 5. Kolizje: dwie pozycje wsadu w jeden cel, cel zajęty w bazie przez inną lokację.
    licznik: dict[str, int] = {}
    for nowa, _ in cele.values():
        if nowa is not None:
            licznik[path_key(nowa)] = licznik.get(path_key(nowa), 0) + 1
    for fid in sorted(cele):
        nowa = cele[fid][0]
        if nowa is None:
            continue
        if licznik[path_key(nowa)] > 1:
            pominiete[fid] = f"kolizja we wsadzie - dwa pliki w jeden cel: {nowa}"
        elif location_at(wiersz[fid]["volume"], nowa) - {int(wiersz[fid]["location_id"])}:
            pominiete[fid] = f"w bazie jest inna kopia pod ścieżką celu: {nowa}"
        else:
            continue
        del cele[fid]

    # 6. Para stosu razem albo wcale.
    for fid, r in wiersz.items():
        if r["variant_of"] is None:
            continue
        for jeden, drugi in ((fid, r["variant_of"][0]), (r["variant_of"][0], fid)):
            if jeden in pominiete and drugi in cele:
                pominiete[drugi] = (f"para stosu jedzie razem - druga połowa pominięta: "
                                    f"{pominiete[jeden]}")
                del cele[drugi]

    # 7. Ostrzeżenie: wejścia stosu rozdzielone między foldery.
    przeniesione = {}
    for fid, (nowa, _) in cele.items():
        if nowa is not None:
            przed, po = path_key(ntpath.dirname(wiersz[fid]["path"])), path_key(ntpath.dirname(nowa))
            if przed != po:
                przeniesione[fid] = po
    stosy = {s[0]: s for fid in przeniesione for s in wiersz[fid]["stacks"]}
    warnings = []
    for sid in sorted(stosy):
        _, nazwa, wejscia = stosy[sid]
        foldery = {przeniesione.get(f, path_key(ntpath.dirname(sciezka))) for f, sciezka in wejscia}
        ruszone = tuple(sorted({f for f, _ in wejscia if f in przeniesione}))
        if len(foldery) > 1:
            warnings.append(ObjectChangeWarning(
                frame_ids=ruszone,
                text=(f"stos {nazwa}: gest przeniesie {len(ruszone)} z {len({f for f, _ in wejscia})} "
                      f"jego wejść - wejścia rozejdą się na {len(foldery)} folderów, a żniwa "
                      f"ustalają siedzibę stosu z jednego folderu lightów")))

    items = tuple(ObjectChangeItem(
        frame_id=fid, location_id=int(wiersz[fid]["location_id"]), old_path=wiersz[fid]["path"],
        new_path=cele[fid][0], mkdirs=cele[fid][1], card_op=robocze[fid]["card_op"],
        card_old=wiersz[fid]["card"], card_new=robocze[fid]["card_new"],
        expected_header_hash=wiersz[fid]["header_hash"], expected_mtime=wiersz[fid]["mtime"],
        expected_object=(wiersz[fid]["object_id"], wiersz[fid]["object_source"],
                         wiersz[fid]["object_cleared_id"]),
        object_change=robocze[fid]["object_change"]) for fid in sorted(cele))
    skipped = tuple(ObjectChangeSkip(fid, wiersz[fid]["path"] or "", pominiete[fid])
                    for fid in sorted(pominiete))
    return ObjectChangePlan(run_id=run_id, target=target, items=items, skipped=skipped,
                            warnings=tuple(warnings),
                            rmdirs=_puste_po_planie(cele, wiersz, dysk, writeback))
