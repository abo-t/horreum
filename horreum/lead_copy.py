"""KOPIA WIODĄCA KLATKI - gest człowieka „Ta kopia prowadzi" (AR-4, AR-23). Rdzeń Qt-wolny: menu
tabeli Zbiorów pyta tu o kopie do wyboru (`lead_copy_choices`), a wątek tła gestu woła
`lead_copy_gesture` (przejęcie zeznania wskazanej kopii + pochodne).

DLACZEGO GEST, A NIE REGUŁA (decyzja Zdzinia 2026-09-26, AR-4): gdy obecne kopie klatki mówią
różnie, kopię wiodącą wskazuje człowiek - żadnej automatycznej reguły wyboru przy ≥2 kopiach.
Jego wybór jest FAKTEM RĘKI: zdarzenie `header.adopted` z aktorem `user:local`, które czyta
`queries.hand_testimony_frame_ids` (jeden właściciel pytania „czyj głos niesie `header`") - więc
etap Dostawy klatki nie przestawia (`queries.orphan_testimony_routes` oddaje ją człowiekowi),
wiersz Porządków „Kopie niezgodne" przestaje liczyć ją jako robotę, a `horreum human-facts` liczy
ją w osi `testimony_hand`.

JEDNA DROGA CZYTANIA PLIKU KOPII (SPOT): bramka izolacji zapisu w miejscu (`scan._isolated`),
odczyt `scan.scan_file`, tożsamość regułą wjazdu (`scan._record_identity`), kotwica odcisku
nagłówka (`scan._odcisk_lokacji`), generacja dziennika zapisu w miejscu z jednym ponowieniem
(`scan._PROBY_GENERACJI`), pochodne tą samą derywacją (`scan._derive_axes`) i klinga
`repo.adopt_testimony` - te same kroki, w tej samej kolejności, co etap
`scan.adopt_orphan_testimony`. Różni się wyłącznie przesłanka: etap pyta, czy klatka nadal należy
do niego (jedna obecna kopia, zeznanie spoza ręki), gest - czy kopia jest obecna i czy klatka
czeka na decyzję człowieka.

PO PRZEJĘCIU POCHODNE (`derive.run_derived`): przejęcie zmienia `header`, z którego liczą się
grupy, filtr kanoniczny, kalibracja i rodowód - bez nich klatka mówiłaby nowym głosem w nagłówku,
a starym w osi filtra do następnej Dostawy. Ta sama lista i kolejność co po przejęciu w Dostawie
(`derive.adopt_and_derive`)."""
import json
from dataclasses import dataclass

from . import derive, repo, scan
from .resolve.headers import FAKTY_BIEZACE, copy_facts_state, copy_testimony, extract_header

HAND_ACTOR = "user:local"


@dataclass(frozen=True)
class LeadChoice:
    """Jedna obecna kopia klatki w menu gestu: `mowi` - jej zeznanie (osiem pól `hdr_*`) jest dziś
    zeznaniem klatki; `fakty` - kopia ma zebrane fakty bieżącej reguły (bez nich nie wiadomo, czy
    mówi); `rozne` - etykiety pól, w których odbiega od pozostałych (`queries.copy_divergence`);
    `fakty_kopii` - wiersz `queries.present_copy_facts` tej kopii (wartości do zdania o rozjeździe)."""
    location_id: int
    path: str
    mowi: bool
    fakty: bool
    rozne: tuple
    fakty_kopii: dict


@dataclass(frozen=True)
class LeadCopyResult:
    """Wynik gestu. `verdict`:
      * `'adopted'` - zeznanie przejęte (`header.adopted`, fakt ręki), pochodne przeliczone;
      * `'unchanged'` - zeznanie klatki już jest zeznaniem tej kopii, ZERO zapisu (klinga);
      * `'confirmed'` - kopia już mówiła; klinga zapisała sam wybór ręki (`header.adopted`
        z `changed: {}` i `confirmed: True`, bez zmiany treści);
      * `'absent'` - kopii nie ma już na dysku według bazy (`present = 0`);
      * `'isolated'` - kopia izolowana po zapisie w miejscu (Porządki mają na to własne wiersze);
      * `'failed'` - plik nieczytelny (`reason` = diagnoza odczytu);
      * `'identity'` - pod ścieżką leży inna treść niż ta klatka (robota skanu);
      * `'stale'` - nagłówek pliku zmienił się od skanu (robota skanu, który odświeży zeznanie);
      * `'raced'` - stan bazy zmienił się w trakcie odczytu (równoległy zapis, kopia przestawiona,
        ścieżka przepięta na inną klatkę niż ta z menu gestu).
    `back` - ścieżki INNYCH obecnych kopii, które mówiły głosem klatki PRZED gestem: wybór którejś
    z nich tym samym gestem jest drogą powrotu. Puste przy przejęciu = poprzednie zeznanie nie
    pochodziło z żadnej obecnej kopii (kopia, z której pochodziło, zniknęła) i gestem nie wróci."""
    verdict: str
    frame_id: int
    path: str
    reason: str | None = None
    back: tuple = ()


def _zeznanie_klatki(con, frame_id):
    """Zeznanie klatki w ośmiu polach kopii (`copy_testimony` z `header.raw_json`) albo `None`,
    gdy klatka nie ma `header` (frame-szkielet)."""
    row = con.execute("SELECT raw_json FROM header WHERE frame_id = ?", (frame_id,)).fetchone()
    return None if row is None else copy_testimony(json.loads(row[0]))


def lead_copy_choices(con, frame_id):
    """Obecne kopie klatki do menu gestu, w kolejności wjazdu - lista `LeadChoice`.

    „Mówi" liczy ta sama reguła co predykat zeznania z nieobecnej kopii
    (`queries.orphan_testimony_copies`): osiem pól zeznania kopii równe `copy_testimony` nagłówka
    klatki, wyłącznie dla kopii z faktami bieżącej reguły - kopia bez nich mówi „nie wiem".
    Import `gui.queries` LENIWY, jak w `scan.adopt_candidates` (moduł Qt-wolny, ale ciągnie
    resolver/stacks/grouper)."""
    from .gui import queries
    kopie = queries.present_copy_facts(con, [frame_id])
    rozne = queries.copy_divergence(kopie)
    zeznanie = _zeznanie_klatki(con, frame_id)
    out = []
    for k in kopie:
        fakty = copy_facts_state(k["hdr_hash"], k["hdr_rule"]) == FAKTY_BIEZACE
        mowi = (fakty and zeznanie is not None
                and all(k[kolumna] == v for kolumna, v in zeznanie.items()))
        out.append(LeadChoice(int(k["location_id"]), k["path"], mowi, fakty,
                              rozne.get(k["location_id"], ()), dict(k)))
    return out


def awaiting_hand(con, frame_id):
    """Czy klatka czeka na wskazanie kopii wiodącej - należy do któregoś z dwóch wierszy Porządków
    („Kopie niezgodne", „Zeznanie z nieobecnej kopii"). Pyta JEDYNYCH właścicieli predykatów
    (`queries.copy_conflict_frame_ids`, `queries.orphan_testimony_frame_ids`), więc gest żyje
    dokładnie tam, gdzie liczba wiersza - razem z guardami żywotności (wycofana i zastąpiona
    wypadają). Klatka z decyzją ręki zostaje w „Kopiach niezgodnych" (kopie dalej się różnią):
    tam gest jest drogą zmiany zdania."""
    from .gui import queries
    return (frame_id in queries.copy_conflict_frame_ids(con)
            or frame_id in queries.orphan_testimony_frame_ids(con))


def adopt_lead_copy(con, *, location_id, now, actor=HAND_ACTOR, expected_frame_id=None):
    """PRZEJĘCIE ZEZNANIA WSKAZANEJ KOPII - bez pochodnych (te dokłada `lead_copy_gesture`).
    Zwraca `LeadCopyResult`. Kolejność bramek jak w etapie `scan.adopt_orphan_testimony`
    (docstring modułu). Lokacja nieznana bazie to błąd wołającego (EXPECT) → `ValueError`.

    `expected_frame_id` - klatka, z której menu człowiek wskazał kopię. Skan mógł w międzyczasie
    przepiąć ścieżkę na inną klatkę; wtedy werdykt `raced` bez zapisu - tu i jeszcze raz w klindze,
    pod lockiem (`repo.adopt_testimony`)."""
    loc = con.execute("SELECT frame_id, path, volume, present FROM location WHERE id = ?",
                      (location_id,)).fetchone()
    if loc is None:
        raise ValueError(f"location:{location_id} nie istnieje")
    frame_id, path = int(loc["frame_id"]), loc["path"]
    if expected_frame_id is not None and frame_id != expected_frame_id:
        return LeadCopyResult("raced", int(expected_frame_id), path)
    if not loc["present"]:
        return LeadCopyResult("absent", frame_id, path)
    # Droga powrotu liczona PRZED zapisem: po nim „mówi" przechodzi na wskazaną kopię.
    back = tuple(c.path for c in lead_copy_choices(con, frame_id)
                 if c.mowi and c.location_id != location_id)
    for proba in range(1, scan._PROBY_GENERACJI + 1):
        # Generacja PRZED bramką izolacji (kontrakt `scan_tree`): zapis w miejscu po niej odrzuca
        # przejęcie (`repo.StaleScanRecord`) - jedno ponowienie, drugi konflikt → `raced`.
        gen = repo.inplace_generation(con)
        if scan._isolated(con, path, loc["volume"]):
            return LeadCopyResult("isolated", frame_id, path)
        try:
            rec = scan.scan_file(path)
        except Exception as exc:               # I/O - wynik z diagnozą, nie zapis
            return LeadCopyResult("failed", frame_id, path, reason=scan.unreadable_reason_of(exc))
        try:
            werdykt = _przejmij(con, frame_id, location_id, rec, now=now, actor=actor,
                                inplace_gen=gen, expected_frame_id=expected_frame_id)
        except repo.StaleScanRecord:           # zapis w miejscu po generacji - odczyt stęchły
            if proba < scan._PROBY_GENERACJI:
                continue
            werdykt = "raced"
        if werdykt == "drift":                 # klinga: kopia zmieniła stan między odczytem a zapisem
            werdykt = "raced"
        return LeadCopyResult(werdykt, frame_id, path,
                              reason=rec.error if werdykt == "failed" else None,
                              back=back if werdykt in ("adopted", "confirmed") else ())
    raise AssertionError("pętla generacji bez werdyktu")   # pragma: no cover - EXPECT


def _przejmij(con, frame_id, location_id, rec, *, now, actor, inplace_gen, expected_frame_id=None):
    """Bramki odczytu i zapis klingą - werdykt `'failed'` | `'identity'` | `'stale'` | werdykt klingi
    (`'adopted'` | `'unchanged'` | `'drift'`). Odczyt starszy niż operacja zapisu w miejscu tej
    kopii → `repo.StaleScanRecord` przed klasyfikacją i przed derywacją osi (AR-17 (8), jak w
    `scan._adopt_one`)."""
    scan._odmow_staremu_odczytowi(con, location_id, inplace_gen)
    if rec.header is None:
        return "failed"
    sha1_data, _ = scan._record_identity(rec)
    frame_sha1 = con.execute("SELECT sha1_data FROM frame WHERE id = ?", (frame_id,)).fetchone()
    if frame_sha1 is None or frame_sha1[0] != sha1_data:
        return "identity"
    if rec.header_hash != scan._odcisk_lokacji(con, location_id):
        return "stale"
    scan._odmow_staremu_odczytowi(con, location_id, inplace_gen)
    kind, _kind_source, _ident, camera_id = scan._derive_axes(con, rec, now=now, actor=actor)
    return repo.adopt_testimony(
        con, location_id=location_id, sha1_data=sha1_data, header_hash=rec.header_hash,
        raw_json=json.dumps(rec.header, ensure_ascii=False), cards=rec.cards,
        hot_fields=extract_header(rec.header), camera_id=camera_id, kind=kind, now=now,
        actor=actor, inplace_gen=inplace_gen, expected_frame_id=expected_frame_id)


def lead_copy_gesture(con, location_id, now, actor=HAND_ACTOR, expected_frame_id=None):
    """Cały gest: przejęcie (`adopt_lead_copy`), a po REALNYM przejęciu pochodne w kolejności
    `derive.DERIVED_STAGES`. `now` - znacznik ISO albo funkcja, która go zwraca (kontrakt
    `derive`). `expected_frame_id` - klatka z menu gestu (Z6, `adopt_lead_copy`). Zwraca
    `LeadCopyResult`."""
    znacznik = now() if callable(now) else now
    wynik = adopt_lead_copy(con, location_id=location_id, now=znacznik, actor=actor,
                            expected_frame_id=expected_frame_id)
    if wynik.verdict == "adopted":
        list(derive.run_derived(con, now))
    return wynik
