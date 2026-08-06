"""AUDYT INWARIANTÓW — jedna formuła, dwaj wołający (S1, brief obiektów własnych §4/11).

Bramki, które dotąd żyły WYŁĄCZNIE w `scripts/acceptance_s5.py`, czyli poza baterią: skrypt chodzi
na dawcy i realnym `R:`, więc jego kryteria nie mogły się zaczerwienić przy `pytest`. Formuła
przeniesiona tutaj jest wołana i przez skrypt, i przez test — inaczej „poprawiliśmy równość"
znaczyło tylko „poprawiliśmy jedno z dwóch miejsc, które ją liczą".

READ-ONLY: zero DML, zero eventów, zero migracji — moduł nie jest klingą. SQL LITERAŁEM, rozwinięty
per encja: dawna pętla sklejała nazwę tabeli f-stringiem, a dynamiczny SQL jest dla meta-tripwiru
AST nieweryfikowalny (`tests/test_repo_safety.py`) i wpuszczony do pakietu zaczerwieniłby bramkę.

RÓWNOŚĆ ENCJA == EVENT MA CZŁON ODEJMOWANY (dług domknięty w S1): część zapisów da się COFNĄĆ, więc
liczba encji to emisje MINUS wycofania. Bez tego pierwszy przebieg po edycji słownika obiektów
własnych świecił czerwono z powodu, który nie jest regresją — a taką czerwień „naprawia się"
podniesieniem kotwicy, po czym bramka przestaje łapać regresję prawdziwą.
"""
from dataclasses import dataclass

from .resolve.objects import ALIAS_SOURCES, OBJECT_KINDS, OBJECT_SOURCES


@dataclass(frozen=True)
class Parity:
    """Jeden wiersz bramki `§5.9`. `minus` niesie NAZWĘ verbu odejmowanego (albo None) — raport ma
    pokazać, że odejmowanie ZASZŁO, a nie tylko że równość wyszła."""
    name: str
    entities: int
    events: int
    retracted: int
    minus: object

    @property
    def ok(self):
        # `retracted` MUSI mieścić się w emisjach: bez tego brak N emisji i nadmiar N wycofań
        # znosiłyby się do zielonego — bramka przestałaby łapać dokładnie to, po co powstała.
        return (self.entities == self.events - self.retracted
                and 0 <= self.retracted <= self.events)


def _events(con, verb):
    """Liczba emisji verbu. JEDYNY helper, bo tu SQL jest stały, a zmienny jest PARAMETR — meta-tripwir
    AST czyta pierwszy argument `execute` i literał widzi. Liczniki ENCJI takiego skrótu mieć nie mogą:
    nazwa tabeli nie jest parametrem, więc helper zrobiłby z nich SQL dynamiczny (nieweryfikowalny)
    i bramka zapaliłaby się na tym module — co zresztą zrobiła przy pierwszym podejściu."""
    return con.execute("SELECT count(*) FROM event WHERE verb = ?", (verb,)).fetchone()[0]


def entity_event_parity(con):
    """`§5.9` — encje == emisje − wycofania, co do sztuki. Zwraca krotkę `Parity`.

    CZŁON ODEJMOWANY MA TA PARA, KTÓRA MA DROGĘ COFNIĘCIA: `object_alias` można wycofać
    (`object.alias_retired`), `frame.object_id` odpiąć (`object.unassigned`), a `frame.config_id`
    zdjąć klatce spoza osi teleskopu (`config.unassigned` — `repo.unassign_config`, kind-scoping
    darków). Dla obserwatorium i przepisu kalibracji drogi cofnięcia dziś nie ma; gdy powstanie,
    człon dochodzi TUTAJ — w jednym miejscu, nie w dwóch.

    UWAGA — RÓWNOŚĆ CONFIGU JEST DOKŁADNA WYŁĄCZNIE NA ŚWIEŻEJ BAZIE, i to nie z winy tej formuły:
    `repo.assign_config` przy PRZEPIĘCIU emituje samo `config.assigned`, bez partnera
    `config.unassigned` — czyli dokładnie ten defekt, który S0 naprawił na osi obiektu
    (`assign_object` emituje parę). Każde przepięcie configu zawyża więc lewą stronę o 1 na zawsze
    (event jest append-only, historii nie przepisujemy). Zmierzone na żywej `pf4`: 16215 emisji,
    z tego 7 przepięć, 32 odpięcia ⇒ 16208 − 32 = 16176 klatek z configiem, czyli różnica 7 jest
    W CAŁOŚCI wyjaśniona brakiem pary. Bramka chodzi na świeżej bazie dawcy, gdzie przepięć nie ma,
    więc jest tam dokładna. Domknięcie osi configu to osobny ruch — nazwane, nie przemilczane."""
    return (
        Parity("camera",
               con.execute("SELECT count(*) FROM camera").fetchone()[0],
               _events(con, "camera.upserted"), 0, None),
        Parity("frame",
               con.execute("SELECT count(*) FROM frame").fetchone()[0],
               _events(con, "frame.observed"), 0, None),
        Parity("location",
               con.execute("SELECT count(*) FROM location").fetchone()[0],
               _events(con, "location.added"), 0, None),
        Parity("header",
               con.execute("SELECT count(*) FROM header").fetchone()[0],
               _events(con, "header.recorded"), 0, None),
        Parity("telescope",
               con.execute("SELECT count(*) FROM telescope").fetchone()[0],
               _events(con, "telescope.proposed"), 0, None),
        Parity("config",
               con.execute("SELECT count(*) FROM config").fetchone()[0],
               _events(con, "config.proposed"), 0, None),
        # append-only: obiektu nie kasujemy nigdy — brak członu odejmowanego jest tu INWARIANTEM,
        # nie brakiem funkcji (sprzątanie osi ma dostać własny ekran, z `retired_at`, nie DELETE).
        Parity("object",
               con.execute("SELECT count(*) FROM object").fetchone()[0],
               _events(con, "object.upserted"), 0, None),
        Parity("object_alias",
               con.execute("SELECT count(*) FROM object_alias").fetchone()[0],
               _events(con, "object.aliased"), _events(con, "object.alias_retired"),
               "object.alias_retired"),
        Parity("observatory",
               con.execute("SELECT count(*) FROM observatory").fetchone()[0],
               _events(con, "observatory.proposed"), 0, None),
        Parity("calibration_profile",
               con.execute("SELECT count(*) FROM calibration_profile").fetchone()[0],
               _events(con, "calibration_profile.proposed"), 0, None),
        Parity("frame.config_id",
               con.execute(
                   "SELECT count(*) FROM frame WHERE config_id IS NOT NULL").fetchone()[0],
               _events(con, "config.assigned"), _events(con, "config.unassigned"),
               "config.unassigned"),
        Parity("frame.object_id",
               con.execute(
                   "SELECT count(*) FROM frame WHERE object_id IS NOT NULL").fetchone()[0],
               _events(con, "object.assigned"), _events(con, "object.unassigned"),
               "object.unassigned"),
        Parity("frame.observatory_id",
               con.execute(
                   "SELECT count(*) FROM frame WHERE observatory_id IS NOT NULL").fetchone()[0],
               _events(con, "observatory.assigned"), 0, None),
        Parity("frame.calibration_profile_id",
               con.execute("SELECT count(*) FROM frame "
                           "WHERE calibration_profile_id IS NOT NULL").fetchone()[0],
               _events(con, "calibration_profile.assigned"), 0, None),
    )


@dataclass(frozen=True)
class SourceAudit:
    """Wartości osi OBIEKT zastane w bazie wobec stałych, które je deklarują."""
    frame_unknown: tuple      # wartości `frame.object_source` spoza OBJECT_SOURCES
    alias_unknown: tuple      # wartości `object_alias.source` spoza ALIAS_SOURCES
    kind_unknown: tuple       # wartości `object.kind` spoza OBJECT_KINDS

    @property
    def ok(self):
        return not (self.frame_unknown or self.alias_unknown or self.kind_unknown)


def object_source_audit(con):
    """Czy baza używa WYŁĄCZNIE wartości źródeł zadeklarowanych w `resolve.objects`.

    Falsyfikator tej bramki to WSTRZYKNIĘCIE wartości spoza stałej, nigdy samo dopisanie nowej:
    wartość, którą paczka świadomie wnosi (`curated`), przechodzi z definicji — bramka ma łapać
    źródło, którego NIKT nie zadeklarował, bo dokładnie tak powstał dzisiejszy rozjazd trzech
    siedzib tego enumu."""
    fr = tuple(sorted(r[0] for r in con.execute(
        "SELECT DISTINCT object_source FROM frame WHERE object_source IS NOT NULL").fetchall()
        if r[0] not in OBJECT_SOURCES))
    al = tuple(sorted(r[0] for r in con.execute(
        "SELECT DISTINCT source FROM object_alias").fetchall() if r[0] not in ALIAS_SOURCES))
    ki = tuple(sorted(r[0] for r in con.execute(
        "SELECT DISTINCT kind FROM object WHERE kind IS NOT NULL").fetchall()
        if r[0] not in OBJECT_KINDS))
    return SourceAudit(frame_unknown=fr, alias_unknown=al, kind_unknown=ki)


@dataclass(frozen=True)
class LightClosure:
    """Rozkład populacji lightów na predykaty raportu — i czy się DOMYKA (R-S0-6)."""
    total: int
    buckets: dict
    headerless: int          # light/master_light bez wiersza `header` I bez obiektu
    filetype_unknown: int    # …i te z zeznaniem, ale bez `filetype` (baza sprzed kolumny)

    @property
    def counted(self):
        return sum(self.buckets.values()) + self.headerless + self.filetype_unknown

    @property
    def ok(self):
        return self.counted == self.total


def light_population_closure(con, rep):
    """Czy sześć predykatów raportu obiektu pokrywa CAŁĄ populację light/master_light.

    Rozkład, który się nie domyka, jest fałszywie zieloną bramą — repo pilnuje tego przy delcie
    i ta sama reguła należy się osi obiektu. Predykaty `nameless_*` mają INNER JOIN na `header`,
    a `resolved_no_raw` wymaga obiektu, więc klatka BEZ wiersza `header` i BEZ obiektu nie wpada
    do żadnego z sześciu — dlatego dostaje własną liczbę zamiast ginąć w reszcie. Dziś ta klasa
    jest pusta (zmierzone), więc kryterium jest tripwirem na przyszłość, nie naprawą bieżącego
    błędu; jego wartość polega na tym, że przestanie być zielone w milczeniu.

    `rep` = `resolver.DeltaReport` z tej samej bazy (nie liczymy predykatów drugi raz — dwie kopie
    tej samej definicji rozjechałyby się dokładnie tak, jak rozjechał się enum źródeł)."""
    total = con.execute(
        "SELECT count(*) FROM frame WHERE kind IN ('light','master_light')").fetchone()[0]
    headerless = con.execute(
        "SELECT count(*) FROM frame f WHERE f.kind IN ('light','master_light') "
        "AND f.object_id IS NULL "
        "AND NOT EXISTS (SELECT 1 FROM header h WHERE h.frame_id = f.id)").fetchone()[0]
    # DRUGA klasa ucieczki, obok bezgłowej: predykaty `nameless_*` dzielą populację warunkiem
    # `filetype IN/NOT IN (…)`, a `NULL` nie spełnia ŻADNEGO z nich (SQL: `NULL NOT IN` → NULL).
    # Light z zeznaniem, bez obiektu, bez `object_raw` i bez `filetype` wypadał więc z sumy i
    # wysadzałby to kryterium na bazie sprzed kolumny `filetype`. Dostaje własną liczbę, żeby
    # klasa się POKAZAŁA — świadomie NIE ruszamy `nameless_lights`, bo to kotwica nawrotu P-D
    # i zmiana jej predykatu przesunęłaby liczbę, którą tamta bramka pilnuje.
    # `kind='light'` WYŁĄCZNIE — i to nie jest zawężenie z ostrożności: `nameless_stacks` pyta sam
    # o `master_light` bez warunku na `filetype`, więc gotowy stos z NULL-em JUŻ tam wpada.
    # Objęcie go tutaj liczyłoby tę samą klatkę dwa razy i zamieniło kryterium sumy w jego własną
    # regresję.
    filetype_unknown = con.execute(
        "SELECT count(*) FROM frame f JOIN header h ON h.frame_id = f.id "
        "WHERE f.kind = 'light' AND f.object_id IS NULL "
        "AND h.object_raw IS NULL AND f.filetype IS NULL").fetchone()[0]
    buckets = {"resolved": rep.object_resolved,
               "resolved_no_raw": rep.object_resolved_no_raw,
               "unresolved": rep.object_unresolved,
               "nameless": rep.object_nameless,
               "nameless_raw": rep.object_nameless_raw,
               "nameless_stacks": rep.object_nameless_stacks}
    return LightClosure(total=total, buckets=buckets, headerless=headerless,
                        filetype_unknown=filetype_unknown)


def supersede_invariants(con):
    """Dwa inwarianty kolumny `frame.superseded_by` (R4) — `{nazwa: liczba naruszeń}`, zero == zdrowo.

    Kolumna twierdzi coś o RZECZYWISTOŚCI („pod tą ścieżką leży dziś inna tożsamość"), więc może
    się z nią rozjechać — i wtedy milknie na dwa sposoby, oba kosztowne:

    * `zastapiona_z_obecna_kopia` — klatka oznaczona, a ma obecną lokację. Znaczy, że plik wrócił
      inną drogą niż gałąź podmiany w skanie (np. przez `refresh_location`, gdy kopia była
      `present=0` i odżyła). Skutek: jej godziny wypadają z `object_exposure`, a klatka z doboru
      rodowodu — czyli archiwum CICHO chudnie. Gasi to `repo.clear_superseded`.
    * `ogniwo_do_zastapionej` — łańcuch kończy się na klatce, która nie ma ŻADNEJ lokacji i nie ma
      dalszego ogniwa, czyli nie da się dojść do wiersza, który miałby nieść tę treść.
      **Granica świadoma: kopia `present=0` NIE jest tu naruszeniem** — zniknięcie i zastąpienie to
      dwa różne stany (P5). Plik, który zniknął, ma lokację i może wrócić; łańcuch prowadzi wtedy
      do istniejącego wiersza i jest cały. Objęcie `present=0` czerwieniłoby ten inwariant przy
      każdym zwykłym skasowaniu pliku na dysku.

    Cyklu nie liczymy TUTAJ, bo łapie go pass przy zapisie (`supersede._in_cycle`), a DDL łapie
    najkrótszy (`superseded_by <> id`). Inwariant ma pokazywać rozjazd bazy ze ŚWIATEM,
    nie powtarzać strażnika, który już stoi na drodze zapisu."""
    return {
        "zastapiona_z_obecna_kopia": con.execute(
            "SELECT count(*) FROM frame f WHERE f.superseded_by IS NOT NULL "
            "AND EXISTS (SELECT 1 FROM location l WHERE l.frame_id = f.id AND l.present = 1)"
        ).fetchone()[0],
        "ogniwo_do_zastapionej": con.execute(
            "SELECT count(*) FROM frame f JOIN frame n ON n.id = f.superseded_by "
            "WHERE n.superseded_by IS NULL "
            "AND NOT EXISTS (SELECT 1 FROM location l WHERE l.frame_id = n.id)"
        ).fetchone()[0],
    }
