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
import json
from dataclasses import dataclass, field

from .repo import CONFIG_SOURCES, STICKY_CONFIG_SOURCES   # słowniki osi sprzętu — właściciel (R1)
from .resolve.objects import (ALIAS_SOURCES, OBJECT_KINDS, OBJECT_SOURCES,
                              TRANSFERABLE_OBJECT_SOURCES, WEAK_OBJECT_SOURCES)


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
    retired: int = 0         # …i te WYCOFANE ręką (D-OW-3/R2) - druga klasa ucieczki
    superseded: int = 0      # …i te ZASTĄPIONE (G2-5d) - trzecia, z tego samego powodu co druga

    @property
    def counted(self):
        return sum(self.buckets.values()) + self.headerless + self.retired + self.superseded

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

    Klasy „light z zeznaniem, ale bez `filetype`" NIE MA od R-S4-10: była tu, bo goły `NOT IN`
    w `nameless_lights` wyrzucał NULL, a lustrzany `IN` w `nameless_raw_lights` go nie łapał.
    Oba predykaty `nameless_*` czytają dziś format nieznany jako „nie bez karty"
    (`COALESCE(f.filetype, '')`), więc taki light liczy się w kubełku `nameless` - osobna liczba
    liczyłaby go DRUGI raz i bramka zapaliłaby się z drugiej strony (`counted > total`).

    `rep` = `resolver.DeltaReport` z tej samej bazy (nie liczymy predykatów drugi raz — dwie kopie
    tej samej definicji rozjechałyby się dokładnie tak, jak rozjechał się enum źródeł)."""
    total = con.execute(
        "SELECT count(*) FROM frame WHERE kind IN ('light','master_light')").fetchone()[0]
    headerless = con.execute(
        "SELECT count(*) FROM frame f WHERE f.kind IN ('light','master_light') "
        "AND f.object_id IS NULL AND f.retired_at IS NULL AND f.superseded_by IS NULL "
        "AND NOT EXISTS (SELECT 1 FROM header h WHERE h.frame_id = f.id)").fetchone()[0]
    buckets = {"resolved": rep.object_resolved,
               "resolved_no_raw": rep.object_resolved_no_raw,
               "unresolved": rep.object_unresolved,
               "nameless": rep.object_nameless,
               "nameless_raw": rep.object_nameless_raw,
               "nameless_stacks": rep.object_nameless_stacks}
    # TRZECIA KLASA UCIECZKI (D-OW-3/R2). Sześć kubełków raportu niesie `retired_at IS NULL`,
    # a `total` nie niesie ŻADNEGO guardu — bez tej liczby rozkład przestałby się domykać przy
    # PIERWSZYM geście wycofania, czyli bramka §5.7a zapaliłaby się na prawidłowej pracy programu.
    # Liczona BEZ warunku na obiekt i nagłówek, bo obie sąsiednie klasy dostały `retired_at IS NULL`
    # — inaczej wycofana klatka bezgłowa liczyłaby się dwa razy i suma przestrzeliłaby `total`.
    retired = con.execute(
        "SELECT count(*) FROM frame WHERE kind IN ('light','master_light') "
        "AND retired_at IS NOT NULL").fetchone()[0]
    # CZWARTA KLASA UCIECZKI (G2-5d) - bliźniaczo do wycofanych i z tego samego powodu: sześć
    # kubełków raportu niesie `superseded_by IS NULL`, a `total` nie niesie ŻADNEGO guardu.
    # ⚠ TO KRYTERIUM ŚWIECIŁO CZERWONO NA ŻYWEJ BAZIE, ZANIM POWSTAŁA TA KLASA (`counted=14530`,
    # `total=14531`): jedna klatka (light, RAW, bez obiektu, bez `object_raw`, ZASTĄPIONA) należy
    # kształtem do `nameless_raw`, a wypycha ją stamtąd guard zastąpienia - słusznie, bo klatka,
    # której treść żyje dalej w następczyni, nie jest ROBOTĄ. Nie miała tylko gdzie się podziać.
    #
    # SĄSIEDNIA KLASA UCIECZKI (`headerless`) DOSTAŁA `superseded_by IS NULL` W TEJ SAMEJ TURZE
    # (razem z wchłoniętą od R-S4-10 klasą „bez `filetype`") - i to nie było przewidywanie,
    # tylko ZŁAPANY BŁĄD: bez tego klatka
    # zastąpiona i bezgłowa naraz liczyła się DWA RAZY, a bramka §5.7a zapalała się z drugiej
    # strony (`counted > total`). Ta sama figura, co przy `retired_at` - dowód w
    # `test_rozklad_populacji_domyka_sie_po_zastapieniu[headerless]`.
    #
    # `retired_at IS NULL` NIE JEST OSTROŻNOŚCIĄ, tylko warunkiem rozłączności: klasa `retired`
    # wyżej liczy wycofane BEZ warunku na zastąpienie, więc klatka i wycofana, i zastąpiona
    # wpadłaby do obu i suma przestrzeliłaby `total` - czyli bramka zapaliłaby się w drugą stronę.
    superseded = con.execute(
        "SELECT count(*) FROM frame WHERE kind IN ('light','master_light') "
        "AND superseded_by IS NOT NULL AND retired_at IS NULL").fetchone()[0]
    return LightClosure(total=total, buckets=buckets, headerless=headerless,
                        retired=retired, superseded=superseded)


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


def retire_invariants(con):
    """Inwariant kolumny `frame.retired_at` (D-OW-3/R2) — `{nazwa: liczba naruszeń}`.

    ⚠️ **TO JEST STRAŻNIK, KTÓREGO MIGRACJA 0018 NIE MOGŁA POSTAWIĆ.** Warunek „wolno wycofać
    wyłącznie klatkę bez OBECNEJ kopii" jest zdaniem o tabeli `location`, a `CHECK` widzi kolumny
    własnego wiersza; triggera w tym repo nie ma ani jednego i nie zaczynamy od takiego, który
    wywracałby skan za cudzy werdykt. Zostaje ta droga — dokładnie ta sama, którą bliźniaczej
    kolumny pilnuje `supersede_invariants` (kryterium §5.15). Stąd kryterium §5.17.

    * `wycofana_z_obecna_kopia` — **PLIK WRÓCIŁ PO WYCOFANIU**. To NIE jest awaria i nie jest
      pomyłką człowieka: wycofanie jest werdyktem o chwili zapisu, a plik wraca zwykłym re-skanem
      (`repo.refresh_location` zapala `present = 1`). Powrót unieważnia PRZESŁANKĘ werdyktu, ale
      unieważnić sam werdykt może wyłącznie człowiek — automatyczne zgaszenie kolumny byłoby
      cofnięciem gestu ręki przez wjazd materiału (warunek stały „ręka nietykalna").
      Dlatego liczba > 0 znaczy „jest co rozstrzygnąć gestem", a nie „baza jest chora"; ten sam
      predykat prowadzi AKCYJNY wiersz Porządków (`gui.queries.retired_conflict_frame_ids`).
      Bez tej pary gest wycofania cicho ukrywałby materiał, który wrócił.
    ⛔ CZŁONU „wycofana bez lokacji" TU NIE MA — I TO JEST WYNIK POMIARU, nie przeoczenie.
    Pierwsza wersja tej funkcji go miała, z uzasadnieniem „liczba > 0 znaczy złamany guard klingi"
    (`_retire_verdict` odmawia klatce bez lokacji). Uzasadnienie było FAŁSZYWE, bo myliło stan
    W CHWILI ZAPISU ze stanem BIEŻĄCYM: klatkę wolno wycofać, gdy ma lokację nieobecną, a późniejszy
    `rebind_location` może jej tę ostatnią lokację ZABRAĆ — sekwencja legalna, opisana wprost
    w `supersede.orphans` i pokryta testem tej paczki. Zmierzone: inwariant zapalał się na
    PRAWIDŁOWEJ pracy programu (1 naruszenie po `retire` + `rebind`).
    Ze STANU tego pytania nie da się zadać: „wycofana i bez lokacji" wygląda identycznie po
    złamanym guardzie i po legalnym przepięciu. Odpowiedź siedziałaby wyłącznie w DZIENNIKU
    (payload `frame.retired` niesie ścieżki) — a read-model liczony ze zdarzeń zamiast ze stanu
    to figura, którą repo dostało już trzy razy [pamięć `horreum-review-queue-from-state`].
    Guard klingi broni się więc BATERIĄ (`test_guard_odmawia_sierocie_bez_zadnej_lokacji`),
    nie inwariantem — i to jest właściwe miejsce dla twierdzenia o chwili zapisu.

    Rozjazdu z dziennikiem nie liczymy — `retired_at` jest STANEM, a `event(frame.retired)` bywa
    wielokrotny dla jednej klatki (wycofana, przywrócona, wycofana znowu)."""
    return {
        "wycofana_z_obecna_kopia": con.execute(
            "SELECT count(*) FROM frame f WHERE f.retired_at IS NOT NULL "
            "AND EXISTS (SELECT 1 FROM location l WHERE l.frame_id = f.id AND l.present = 1)"
        ).fetchone()[0],
    }


def config_review_reason_gap(con):
    """`§5.6` — ile klatek bez configu NIE MA zapisanego powodu. Zero == „zero cichego NULL".

    Formuła mieszka TU, a nie w skrypcie akceptacji, z powodu, dla którego ten moduł powstał:
    kryterium żyjące wyłącznie w `scripts/acceptance_s5.py` jest poza baterią i żaden test nie może
    go zaczerwienić, a skrypt chodzi na dawcy i realnym `R:`.

    KIERUNKOWE, nie równościowe — i to jest poprawka wymuszona przez R1 (W4). Do R1 zbiór „klatek
    bez configu" mógł tylko rosnąć albo stać, więc równość `stan == |targety config.review|`
    przypadkiem działała. Gest „Przypisz zestaw…" WYPROWADZA z niego klatki, a dziennik jest
    append-only: ich `config.review` zostaje na zawsze. Równość pękłaby więc dokładnie o liczbę
    NAPRAWIONYCH klatek — bramka karałaby za sprzątanie. Pytanie brzmi „czy każda klatka bez
    configu ma zapisany POWÓD", czyli zawieranie `stan ⊆ targety`.

    Kalibracja poza osią teleskopu NIE wchodzi (kind-scoping: jej `config_id IS NULL` to stan
    docelowy), klatka bez zeznania też nie (grouper iteruje `frame JOIN header`, więc nigdy jej
    nie flaguje) — te same dwa wyłączenia, co w `resolver.review_state.no_config`."""
    from .grouper import NO_TELESCOPE_KINDS

    return con.execute(
        "SELECT count(*) FROM frame f WHERE f.config_id IS NULL "
        "AND f.kind NOT IN (SELECT value FROM json_each(?)) "
        "AND EXISTS(SELECT 1 FROM header h WHERE h.frame_id = f.id) "
        "AND NOT EXISTS(SELECT 1 FROM event e WHERE e.verb = 'config.review' "
        "               AND e.target = 'frame:' || f.id)",
        (json.dumps(sorted(NO_TELESCOPE_KINDS)),)).fetchone()[0]


def config_source_invariants(con):
    """Trzy inwarianty kolumny `frame.config_source` (R1) — `{nazwa: liczba naruszeń}`, zero == zdrowo.

    Kolumna twierdzi, że oś sprzętu tej klatki jest WERDYKTEM CZŁOWIEKA — a to twierdzenie da się
    złamać na trzy sposoby, każdy inaczej kosztowny:

    * `reka_bez_sladu` — źródło mówi „user", a w dzienniku nie ma zdarzenia od człowieka. Zapis
      przez klingę zawsze zostawia `config.assigned` z aktorem `user:*`, więc naruszenie znaczy
      wstrzyknięcie z pominięciem klingi (gołe SQL, cudzy skrypt). To jest ta sama bramka, którą
      G1-1 stawia po stronie akceptacji, tylko liczona na dowolnej bazie.
    * `reka_bez_osi` — źródło ustawione, `config_id` NULL. Klinga zapisuje oba pola razem, więc
      taka para nie ma jak powstać — ale gdyby powstała, MILCZAŁABY: parytet `frame.config_id`
      nie drgnąłby, a `transfer_human_facts` przeniósłby na następczynię „zestaw", którego nie ma
      (stąd jawny człon `config_id IS NOT NULL` w jego guardzie).
    * `reka_na_kalibracji` — dark albo bias z zestawem od ręki. Klinga tego odmawia
      (`NO_TELESCOPE_KINDS`), a przebieg takie przypisanie odpina — inwariant pilnuje, że obie
      drogi rzeczywiście się domykają, zamiast liczyć na jedną z nich.

    Import odroczony (`grouper` importuje `repo`, `repo` importuje `resolve` — a ten moduł stoi
    obok), z tego samego powodu, co w `repo.user_assign_config`: SPOT zbioru rodzajów ma jednego
    właściciela i pytamy jego."""
    from .grouper import NO_TELESCOPE_KINDS

    zrodla = json.dumps(sorted(CONFIG_SOURCES))
    off_axis = json.dumps(sorted(NO_TELESCOPE_KINDS))
    return {
        # ŚLAD MUSI PASOWAĆ DO STANU, nie tylko istnieć (bramka pakietu 3a, zarzut 7): pytanie
        # „czy kiedykolwiek był gest" przepuszczało podmianę `config_id` gołym SQL-em na klatce,
        # która gest KIEDYŚ dostała — źródło zostawało 'user', a oś wskazywała już co innego.
        # Porównujemy więc `config_id` z payloadu zdarzenia z bieżącym stanem.
        "reka_bez_sladu": con.execute(
            "SELECT count(*) FROM frame f "
            "WHERE f.config_source IN (SELECT value FROM json_each(?)) "
            "AND NOT EXISTS (SELECT 1 FROM event e WHERE e.verb = 'config.assigned' "
            "                AND e.target = 'frame:' || f.id AND e.actor LIKE 'user:%' "
            "                AND json_extract(e.payload, '$.config_id') IS f.config_id)",
            (zrodla,)).fetchone()[0],
        "reka_bez_osi": con.execute(
            "SELECT count(*) FROM frame f WHERE f.config_source IS NOT NULL "
            "AND f.config_id IS NULL").fetchone()[0],
        "reka_na_kalibracji": con.execute(
            "SELECT count(*) FROM frame f WHERE f.config_source IS NOT NULL "
            "AND f.kind IN (SELECT value FROM json_each(?))", (off_axis,)).fetchone()[0],
    }


@dataclass(frozen=True)
class HumanFacts:
    """SPIS FAKTÓW, KTÓRE W BAZIE ZAPISAŁA RĘKA — po jednej liczbie na oś, żadnych sum.

    Powstał z warunku Zdzinia (0809): *„wprowadzanie nowych subów albo masterów nie może wpłynąć
    na wycofanie czegokolwiek już ustawionego ręcznie w istniejących w bazie klatkach"*. Do tej
    pory zdanie „ręka przeżyła przebieg" było WNIOSKIEM Z LEKTURY KODU — trzy guardy w klingach
    (`STICKY_OBJECT_SOURCES`, `STICKY_CONFIG_SOURCES`, `RANGA_ASSERT`) rzeczywiście stoją, ale
    żaden pomiar tego nie sprawdzał, więc regresja w którymkolwiek z nich byłaby cicha.

    NIE JEST INWARIANTEM, TYLKO POMIAREM — i to jest cała różnica wobec sąsiadów w tym module.
    Sąsiedzi pytają „czy stan jest zdrowy" i odpowiadają na dowolnej bazie w dowolnej chwili;
    tutaj zdrowie jest RELACJĄ MIĘDZY DWOMA CHWILAMI (przed etapem i po nim), bo liczba faktów
    ręki nie ma żadnej poprawnej wartości bezwzględnej. Stąd `spadki` zamiast `ok`.

    ROŚNIE WOLNO: gest ręki jest rzadki, więc każda z tych liczb zmienia się o jednostki na sesję.
    Zmierzone na żywej `pf4` 2026-08-09, przed etapem 4: obiekt 703 (nagrobków 0) · config 3 ·
    wejścia rodowodu 1876 (odrzuceń 0) · kalibracja 0 i 0."""
    object_hand: int
    object_cleared: int
    config_hand: int
    lineage_inputs: int
    lineage_excluded: int
    calibration_facts: int
    calibration_links: int
    offset_hand: int = 0
    """ODNIESIENIE CZASU stosu (`integration.utc_offset_min`, gest R2) — ósma oś, dołożona po
    bramce pakietu 3a (zarzut 4). Bez niej spis miał dziurę dokładnie tej klasy, którą deklaruje
    domykać: offsetu broni dziś WYŁĄCZNIE rozdział pisarzy (kolumny nie ma na literalnej liście
    pól `upsert_integration`), a to obrona konwencją, nie mechanizmem — dopisanie kolumny do tamtej
    listy wyzerowałoby gest ręki przy pierwszym przebiegu, a spis zameldowałby „ubytków BRAK".

    WARTOŚĆ DOMYŚLNA 0 jest świadoma i ma jeden kierunek błędu: odniesienie zapisane PRZED tą
    zmianą nie ma tego klucza, więc wczyta się jako zero. Zero po stronie „przed" może co najwyżej
    ukryć WZROST (a wzrost naruszeniem nie jest) — ubytku nie ukryje nigdy."""

    retired_hand: int = 0
    """WYCOFANIE KLATKI (`frame.retired_at`, gest D-OW-3/R2) — dziewiąta oś. Wycofanie jest
    WERDYKTEM RĘKI („pliku tej klatki już nie szukam"), więc bez tej liczby `horreum human-facts
    --baseline` przepuściłby jego cichy ubytek — a warunek Zdzinia mówi o KAŻDYM fakcie ustawionym
    ręcznie, nie o wybranych osiach. Ryzyko jest przy tym realne, nie teoretyczne: `retired_at`
    nie ma strażnika w DDL (0018), więc jedyną obroną jest rozdział pisarzy — czyli znowu
    konwencja, dokładnie ta sama sytuacja, która kazała dołożyć `offset_hand`.

    Wartość domyślna 0 z tego samego powodu i z tym samym kierunkiem błędu, co przy `offset_hand`."""

    object_hand_frames: tuple | None = None
    """MIGAWKA TOŻSAMOŚCI osi obiektu (E5-1, bramka `sol` Z1): posortowane `frame_id` klatek
    z faktem ręki (`TRANSFERABLE_OBJECT_SOURCES`) - te same klatki, które liczy `object_hand`.

    Po co tożsamość, skoro jest liczba: od E5-1 spadek `object_hand` bywa UPRAWNIONY (karta
    `OBJECT` w pliku potwierdziła zatwierdzony folder, źródło przeszło z `path` na nagłówek).
    Rozstrzygnięcie na SUMACH przepuszczało wtedy prawdziwy ubytek: klatka A przechodzi uprawnienie,
    klatka B traci gest człowieka, nowa klatka C dostaje rękę - suma spada o 1, przejść jest 1,
    „ubytków BRAK". Po tożsamości B zostaje ubytkiem, bo wyjaśnić można wyłącznie KONKRETNĄ klatkę
    konkretnym śladem w dzienniku (`path_to_header_since`).

    `None` = odniesienie zapisane PRZED tą migawką: porównanie wraca do sum i niczego nie wyjaśnia
    (zachowanie sprzed E5-1 - przejście uprawnione pokaże się jako ubytek, prawdziwy nie zniknie)."""

    event_watermark: int | None = field(default=None, compare=False)
    """`max(event.id)` w chwili spisu - granica, od której dziennik może WYJAŚNIĆ zniknięcie faktu
    ręki (`path_to_header_since`). Poza porównaniem równości spisów: dwa spisy o tych samych
    faktach ręki są równe, choćby między nimi przybyło zdarzeń bez związku z ręką."""

    def __post_init__(self):
        # Odniesienie z JSON-a niesie listę; spis z bazy krotkę. Jedna postać, żeby równość spisów
        # mówiła o faktach, a nie o drodze, którą przyszły.
        if self.object_hand_frames is not None:
            object.__setattr__(self, "object_hand_frames",
                               tuple(sorted(int(i) for i in self.object_hand_frames)))

    @property
    def counts(self):
        """Spis jako `{oś: liczba}` — do porównania i do raportu, w jednej kolejności."""
        return {"object_hand": self.object_hand, "object_cleared": self.object_cleared,
                "config_hand": self.config_hand, "lineage_inputs": self.lineage_inputs,
                "lineage_excluded": self.lineage_excluded,
                "calibration_facts": self.calibration_facts,
                "calibration_links": self.calibration_links,
                "offset_hand": self.offset_hand,
                "retired_hand": self.retired_hand}

    @property
    def snapshot(self):
        """Spis do zapisu jako ODNIESIENIE (`human-facts --json`): liczby osi + migawka tożsamości
        osi obiektu + znak wodny dziennika. `HumanFacts(**snapshot)` odtwarza spis w całości."""
        return {**self.counts,
                "object_hand_frames": (None if self.object_hand_frames is None
                                       else list(self.object_hand_frames)),
                "event_watermark": self.event_watermark}

    def reka_obiektu(self, wczesniej, przejete=frozenset()):
        """Rozbiór zniknięć faktu ręki osi obiektu PO TOŻSAMOŚCI - `(utracone, przejete_przez_naglowek)`
        jako posortowane krotki `frame_id`, albo `None`, gdy któryś spis nie niesie migawki.

        Zniknięcie = klatka z migawki `wczesniej`, której nie ma w migawce bieżącej. Wyjaśnione
        (nie ubytek) wyłącznie wtedy, gdy klatka jest w `przejete` - czyli dziennik PO znaku
        wodnym odniesienia niesie dowód przejścia `path → nagłówek` z TYM SAMYM obiektem."""
        if wczesniej.object_hand_frames is None or self.object_hand_frames is None:
            return None
        zniknely = set(wczesniej.object_hand_frames) - set(self.object_hand_frames)
        return tuple(sorted(zniknely - przejete)), tuple(sorted(zniknely & przejete))

    def spadki(self, wczesniej, przejete=frozenset()):
        """Osie, na których fakt ręki UBYŁ wobec wcześniejszego spisu — `{oś: (było, jest)}`.

        Pusty słownik == warunek dotrzymany. WZROST NIE JEST NARUSZENIEM: nowy materiał wolno
        opatrzyć ręką, a przeniesienie faktu na następczynię (`repo.transfer_human_facts`) też
        podnosi licznik osi obiektu. Pytamy wyłącznie o UBYTEK, bo tylko on jest wycofaniem.

        OŚ OBIEKTU PO TOŻSAMOŚCI, gdy oba spisy niosą migawkę (E5-1): ubytkiem jest KAŻDA klatka,
        która fakt ręki straciła, poza wyjaśnionymi śladem przejścia (`reka_obiektu`) - także gdy
        suma nie spadła, bo nowa ręka gdzie indziej nie oddaje utraconej. Bez migawki (stare
        odniesienie) - sumy, jak przed E5-1, bez żadnego tłumienia. Para `(było, jest)` to liczby
        osi; listę klatek podaje `reka_obiektu`."""
        ubytki = {k: (v, self.counts[k]) for k, v in wczesniej.counts.items() if self.counts[k] < v}
        rozbior = self.reka_obiektu(wczesniej, przejete)
        if rozbior is not None:
            ubytki.pop("object_hand", None)
            if rozbior[0]:
                ubytki["object_hand"] = (wczesniej.object_hand, self.object_hand)
        return ubytki


def path_to_header_since(con, watermark):
    """Klatki, których potwierdzenie ze ścieżki przeszło do nagłówka BEZ zmiany obiektu PO znaku
    wodnym `watermark` - `frozenset(frame_id)`. READ-ONLY. `None` (odniesienie bez znaku) → pusty
    zbiór: nie wiadomo, od kiedy czytać, więc niczego nie wyjaśniamy.

    JEDYNY DOWÓD to ślad zapisany W CHWILI przepięcia przez klingę (`repo.assign_object`, w tej
    samej transakcji): `object.unassigned` ze źródłem słabym i stanem PO w `next_object_id`,
    równym obiektowi sprzed. Rekonstrukcja z ogólnego odpięcia i BIEŻĄCEGO stanu (bramka `sol` Z2)
    brała za przejście późniejsze `nagłówek:B → nagłówek:A` i odpięcie słownikowe - tamte
    zdarzenia kluczy stanu PO nie niosą."""
    if watermark is None:
        return frozenset()
    return frozenset(int(r[0]) for r in con.execute(
        "SELECT DISTINCT CAST(substr(target, 7) AS INTEGER) FROM event "
        "WHERE id > ? AND verb = 'object.unassigned' AND target LIKE 'frame:%' "
        "AND json_extract(payload, '$.object_source') IN (SELECT value FROM json_each(?)) "
        "AND json_extract(payload, '$.next_object_id') = json_extract(payload, '$.object_id')",
        (watermark, json.dumps(sorted(WEAK_OBJECT_SOURCES)))).fetchall())


def human_facts_census(con):
    """Policz `HumanFacts` na tej bazie. READ-ONLY, jak cały moduł.

    ZBIORY ŹRÓDEŁ BIERZEMY OD ICH WŁAŚCICIELI (`TRANSFERABLE_OBJECT_SOURCES`,
    `STICKY_CONFIG_SOURCES`), nie z literałów: spis, który zna własną listę źródeł, przestałby
    liczyć pierwszy nowy gest w dniu, w którym ten gest powstaje — czyli dokładnie wtedy, gdy
    warunek najbardziej potrzebuje pomiaru.

    NAGROBEK LICZY SIĘ OSOBNO, choć `object_hand` już go obejmuje jako źródło: „ta klatka obiektu
    NIE ma" jest werdyktem tak samo jak wskazanie nazwy, ale jego zniknięcie wygląda w sumie
    identycznie jak zniknięcie przypisania — a to dwie różne szkody i dwie różne drogi naprawy."""
    zrodla_obiektu = json.dumps(sorted(TRANSFERABLE_OBJECT_SOURCES))
    zrodla_configu = json.dumps(sorted(STICKY_CONFIG_SOURCES))
    # Znak wodny PRZED migawką: zdarzenie dopisane między dwoma odczytami trafi najwyżej do okna
    # następnego porównania, a nie wypadnie z obu (spis bywa robiony na żywej bazie).
    znak = con.execute("SELECT COALESCE(max(id), 0) FROM event").fetchone()[0]
    reka = tuple(int(r[0]) for r in con.execute(
        "SELECT id FROM frame WHERE object_source IN (SELECT value FROM json_each(?)) ORDER BY id",
        (zrodla_obiektu,)).fetchall())
    return HumanFacts(
        object_hand=len(reka),                    # liczba i migawka z JEDNEGO odczytu (SPOT)
        object_hand_frames=reka,
        event_watermark=znak,
        object_cleared=con.execute(
            "SELECT count(*) FROM frame WHERE object_source = 'user_cleared'").fetchone()[0],
        config_hand=con.execute(
            "SELECT count(*) FROM frame WHERE config_source IN (SELECT value FROM json_each(?))",
            (zrodla_configu,)).fetchone()[0],
        lineage_inputs=con.execute(
            "SELECT count(*) FROM integration_input WHERE asserted_by = 'user'").fetchone()[0],
        lineage_excluded=con.execute(
            "SELECT count(*) FROM integration_input WHERE asserted_by = 'user' "
            "AND excluded = 1").fetchone()[0],
        calibration_facts=con.execute(
            "SELECT count(*) FROM calibration_fact WHERE source = 'user'").fetchone()[0],
        calibration_links=con.execute(
            "SELECT count(*) FROM calibration WHERE asserted_by = 'user'").fetchone()[0],
        offset_hand=con.execute(
            "SELECT count(*) FROM integration WHERE utc_offset_min IS NOT NULL").fetchone()[0],
        retired_hand=con.execute(
            "SELECT count(*) FROM frame WHERE retired_at IS NOT NULL").fetchone()[0],
    )
