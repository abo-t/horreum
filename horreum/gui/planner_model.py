"""View-model ekranu PLANERA (T5b) — Qt-WOLNY (wzorzec `portfolio.py`/`facet_model.py`; egzekwuje
rglob `test_gui_isolation` + jawna asercja). Zamienia `targets.PlanResult` na gotowe komórki,
noty nagłówka i predykaty akcji; widżet `planner.py` niczego nie liczy ani nie formatuje.

RDZEŃ JEST NIETYKALNY: ten moduł CZYTA `targets`/`sky` i REUŻYWA `targets.recommend_channel`
(tożsamość, nie druga derywacja rady) oraz `portfolio.format_hours` (jedyny właściciel formatu
godzin). Zero SQL, zero Qt, zero zapisu.

CHIP ZESTAWU = SOCZEWKA, NIE FILTR (D-0731-13, wariant C). Zmierzone na kopii żywej pf4
(2026-07-31): `framing` niesie wpis dla KAŻDEGO z 3 zestawów w KAŻDYM z 429 wierszy — bo
`sky.framing` odmawia wyłącznie przy braku FOV, a mozaika liczy się zawsze. Filtr „pokaż cele,
które wchodzą w ten zestaw" nie wyciąłby więc ANI JEDNEGO wiersza (falsyfikator z planu T5
zakładał ~87 i jego arytmetyka padła — sama decyzja nie). Chip robi to, co ma sens: pokazuje
wiersz OCZAMI wybranego zestawu — kadrowanie i rada liczone dla NIEGO, zamiast dla
najlepszego dopasowania. Nic nie znika, więc chip jest w pełni odwracalny.

WYJĄTEK JEST JEDEN I NA ŻĄDANIE - FILTR KADRU (dług T5, PL-1, PL-2): gdy rdzeń liczył z progiem
wypełnienia albo paneli (`PlanResult.rig_filter == 'on'`), soczewka konkretnego zestawu chowa
wiersze, których TEN zestaw nie spełnia - „patrzę oczami RC8, pokaż, co RC8 zrobi w jednym kadrze".
Progi czyta z `PlanResult` (jedno źródło z rdzeniem), predykat to `targets.rig_fits` (ten sam,
którym rdzeń tnie pulę), a liczbę schowanych podaje nota nagłówka. Bez filtra - nic nie znika.

PORZĄDEK RDZENIA JEST DOMYŚLNY, SORT SOCZEWKI ŻYJE W WIDOKU (D-T4-c): `targets._sort_key` ma pięć
członów wywalczonych firsthandem T3 i pozostaje NIETKNIĘTY. `order=ORDER_LENS` przestawia GOTOWE
wiersze — to prezentacja, tak jak sam chip; rdzeń nadal oddaje jedną, deterministyczną kolejność,
a CLI (`horreum plan`) o istnieniu tego porządku nie wie i wiedzieć nie musi.
"""

from __future__ import annotations

from dataclasses import dataclass

from horreum import targets as T
from horreum.gui import i18n, portfolio

# Kolejność kanałów w opisie pokrycia — RGB pierwszy, potem wąskie (jak w CLI `_coverage_text`).
_CHANNELS = (T.RGB,) + T.NARROW_CHANNELS

# Porządki listy. `ORDER_CORE` = rada rdzenia (pięcioczłonowy `targets._sort_key`); `ORDER_LENS` =
# dopasowanie do soczewki, liczone TU (widok), nigdy w rdzeniu.
ORDER_CORE, ORDER_LENS = "core", "lens"

# Powody braku rady (`TargetRow.recommend_reason`) → klucze i18n. Powód JEST odpowiedzią
# („nie ma czego robić" vs „ten zestaw tego nie umie"), więc pusta komórka byłaby stratą faktu.
_REASON_KEYS = {"no_gap": "planner.reason_no_gap",
                "rig_cannot": "planner.reason_rig_cannot",
                "no_rig": "planner.reason_no_rig"}


@dataclass(frozen=True)
class ViewRow:
    """Jeden wiersz listy — same gotowe stringi + `source` (oryginalny `TargetRow`) dla panelu
    szczegółu i akcji. `visible` zostaje osobno: wiersz niewidoczny ma być WYSZARZONY, nie
    ukryty (D-0731-14 — Księżyc i horyzont wyceniają, nie wycinają)."""
    canon: str
    type: str
    size: str
    culmination: str
    window: str
    rig: str
    fill: str                      # wypełnienie kadru w soczewce (PL-1): `sky.Framing.frame_fill`
    coverage: str
    coverage_tip: str              # gdzie leżą gotowe obrazy (I-2e) — tooltip, nie kolumna
    cost: str
    recommend: str
    plan: str
    note: str
    visible: bool
    source: object                 # targets.TargetRow
    # Mozaika ma `frame_fill` = 100% z definicji (każdy panel wypełniony), więc ta sama liczba co
    # przy celu idealnie wypełniającym jeden kadr. Widok ją PRZYGASZA i tłumaczy podpowiedzią;
    # miara w `sky.Framing` zostaje jedna dla ekranu, CLI i progu.
    fill_mosaic: bool = False


def rig_choices(result):
    """Nazwy zestawów do chipów, W PORZĄDKU ZESTAWÓW PO LIGHTACH (kontrakt T4 §8a pkt 3) —
    `PlanResult.rigs` jest już posortowane `(-lights, telescope)`, więc bierzemy je JAK JEST.
    Alfabetyczny raport `sky.park` opisuje park, nie ekran: człowiek szuka na górze sprzętu,
    którym realnie pracuje.

    Nazwa to `RigSet.name`, nie sam teleskop: optyka z dwiema kamerami daje DWA chipy
    („ED120R (ASI2600MC/ASI2600MM)", „ED120R (ASI294MC)"), a nie dwa jednakowe, z których oba
    wskazywałyby pierwszy zestaw. Nazwa jest unikalna w obrębie wyniku (`targets.rig_sets`)."""
    return tuple(r.name for r in result.rigs)


def _rig_by_name(result, name):
    return next((r for r in result.rigs if r.name == name), None)


def lens(row, result, rig_name=None):
    """Para `(zestaw, kadrowanie)` widziana przez chip. `rig_name=None` (domyślnie) → najlepsze
    dopasowanie z rdzenia; nazwa zestawu (`rig_choices`) → TEN zestaw, o ile ma kadrowanie tego
    celu. Kadrowanie po tożsamości zestawu (`TargetRow.framing_in`), nie po nazwie teleskopu.
    Zwraca `(RigSet|None, sky.Framing|None)`."""
    rig = row.best_rig if rig_name is None else _rig_by_name(result, rig_name)
    if rig is None:
        return None, None
    return rig, row.framing_in(rig)


def recommendation(row, rig):
    """Rada dla WSKAZANEGO zestawu — `targets.recommend_channel` bit w bit (ta sama funkcja liczy
    radę w CLI i w rdzeniu). Przy soczewce domyślnej oddajemy gotowy wynik rdzenia zamiast liczyć
    go po raz drugi. Zwraca `(kanał|None, powód|None)`."""
    if rig is None or rig is row.best_rig:
        return row.recommend, row.recommend_reason
    return T.recommend_channel(row.coverage, row.cost, rig)


def lens_fits(row, result, rig_name=None):
    """Czy wiersz przechodzi FILTR KADRU w soczewce. Filtr nieczynny (`rig_filter != 'on'`) - zawsze
    tak. Bez soczewki rozstrzyga `best_rig`, który rdzeń wybrał już spośród zestawów spełniających
    próg, więc pula i lista mówią jednym głosem."""
    if result.rig_filter != "on":
        return True
    _rig, fr = lens(row, result, rig_name)
    return T.rig_fits(fr, min_fill=result.min_fill, max_panels=result.max_panels)


def lens_hidden(result, rig_name=None):
    """Ile wierszy wyniku soczewka schowała filtrem kadru - liczba do noty nagłówka."""
    return sum(1 for r in result.rows if not lens_fits(r, result, rig_name))


def view_rows(result, rig_name=None, order=ORDER_CORE):
    """`PlanResult` → krotka `ViewRow`. `order=ORDER_CORE` (domyślnie) zachowuje porządek rdzenia;
    `ORDER_LENS` przestawia wiersze WEDŁUG KADROWANIA w soczewce (patrz `_lens_key`). Włączony
    filtr kadru chowa wiersze, których soczewka nie spełnia (`lens_fits`)."""
    rows = tuple(_view_row(r, result, rig_name) for r in result.rows
                 if lens_fits(r, result, rig_name))
    if order != ORDER_LENS:
        return rows
    # `sorted` jest STABILNY, więc remis (ten sam kadr, to samo wypełnienie) zostaje rozstrzygnięty
    # porządkiem rdzenia — dwa przebiegi dają ten sam plik i nie ma tu drugiego klucza do utrzymania.
    return tuple(sorted(rows, key=lambda v: _lens_key(v, result, rig_name)))


def _lens_key(view_row, result, rig_name):
    """Klucz sortu „po soczewce": (najpierw JEDEN KADR, potem najlepiej wypełniające) — dokładnie
    te dwa człony, którymi rdzeń wybiera `best_rig` (`targets._framing_for`), więc oko dostaje ten
    sam ranking, który stoi za kolumną „Zestaw i kadr". Cel bez kadrowania w tej soczewce idzie na
    KONIEC (nie na początek jako „0 paneli") — brak odpowiedzi nie ma prawa wygrywać z odpowiedzią."""
    _rig, fr = lens(view_row.source, result, rig_name)
    if fr is None:
        return (1, 0, 0.0)
    return (0, fr.panels, -fr.fill)


def _view_row(row, result, rig_name):
    rig, fr = lens(row, result, rig_name)
    channel, reason = recommendation(row, rig)
    t = row.target
    return ViewRow(
        canon=t.canon,
        type=t.type,
        size=i18n.t("planner.arcmin", n=f"{t.major_arcmin:.0f}"),
        culmination=f"{row.window.max_alt_deg:.0f}°",
        window=f"{row.window.hours_above:.1f} h",
        rig=rig_text(rig, fr),
        fill=fill_text(fr),
        coverage=coverage_text(row),
        coverage_tip=coverage_tip(row),
        cost=cost_text(row),
        recommend=recommend_text(channel, reason),
        plan=plan_text(row),
        note=row.note or "",
        visible=row.window.visible,
        source=row,
        fill_mosaic=fr is not None and fr.panels > 1,
    )


def recommend_text(channel, reason):
    """Kanał do zrobienia dziś ALBO powód, dla którego rady nie ma. Powód jest odpowiedzią, nie
    brakiem odpowiedzi: „nie ma czego robić" i „ten zestaw tego nie umie" to dwa różne stany
    i pusta komórka zlałaby je w jeden."""
    if channel:
        return channel
    return i18n.t(_REASON_KEYS.get(reason or "no_rig", "planner.reason_no_rig"))


def rig_text(rig, framing):
    """„A140R · 1 kadr" / „A140R · mozaika 4". Brak zestawu = kreska, nie puste pole: pusta
    komórka czyta się jak „nie policzyłem", a to jest odpowiedź „nie masz czym"."""
    if rig is None or framing is None:
        return "—"
    panels = (i18n.t("planner.one_frame") if framing.panels == 1
              else i18n.t("planner.mosaic", n=framing.panels))
    return f"{rig.name} · {panels}"


def fill_text(framing):
    """„58%": wypełnienie kadru (PL-1), miara `sky.Framing.frame_fill` (0..1, mozaika = 100%).
    Brak kadrowania = kreska, jak w kolumnie zestawu: „nie masz czym", nie „nie policzyłem"."""
    if framing is None:
        return "-"
    return f"{framing.frame_fill * 100:.0f}%"


def coverage_text(row):
    """„u Ciebie: LBN807 · Ha 8.1 h · brak OIII/SII" — kolejno: pod jaką NAZWĄ user ma klatki
    (gdy inna niż kanon celu, D-T2-d), godziny per kanał, luki. Cel nigdy nie fotografowany
    dostaje jawne „bez klatek", nie pustkę.

    Godziny formatuje `portfolio.format_hours` (SPOT — jedyny właściciel formatu; przyjmuje
    SEKUNDY, a pokrycie jest w godzinach, stąd `* 3600`)."""
    cov = row.coverage
    if not cov.known:
        # Cel bez ANI JEDNEJ klatki ma z definicji luki we wszystkich wymaganych kanałach —
        # „brak RGB/Ha/OIII/SII" jest prawdziwe, ale niesie zero informacji ponad „nie masz go
        # wcale". Jedno słowo zamiast wyliczanki (cel nigdy nie fotografowany to WIĘKSZOŚĆ listy,
        # D-0731-1) — luki mają sens dopiero tam, gdzie jest co domykać.
        return i18n.t("planner.no_frames")
    parts = []
    alien = [c for c in cov.archive_canons if c != row.target.canon]
    if alien:
        parts.append(i18n.t("planner.your_name", names="/".join(alien)))
    for ch in _CHANNELS:
        hours = cov.hours_by_channel.get(ch, 0.0)
        if hours > 0:
            parts.append(f"{ch} {portfolio.format_hours(hours * 3600)}")
    # ZINTEGROWANE JEDNĄ LICZBĄ, nie per kanał (I-2e): rozbicie podwoiłoby długość komórki, która
    # i tak jest najszersza w tabeli, a pytanie brzmi „ile z tego jest obrazem", nie „w czym".
    # Rozbicie mieszka w tooltipie razem ze ścieżkami. Zero stosów = MILCZENIE, nie „0 h":
    # większość celów nigdy nie była stackowana i zero przy każdym z nich byłoby szumem.
    if cov.integrated_hours > 0:
        parts.append(i18n.t("planner.integrated",
                            hours=portfolio.format_hours(cov.integrated_hours * 3600)))
    if cov.gaps:
        parts.append(i18n.t("planner.gaps", channels="/".join(cov.gaps)))
    if not parts:
        return i18n.t("planner.no_frames")
    return " · ".join(parts)


def coverage_tip(row):
    """GDZIE LEŻY GOTOWY OBRAZ (I-2e) — tooltip komórki pokrycia; pusty string, gdy stosów nie ma.

    Ścieżki idą do tooltipa, a nie do kolumny, z dwóch powodów naraz: mają po sto znaków (kolumna
    rozjechałaby tabelę, której podłogę szerokości Zdzin ustalił świadomie — D-0801-1), a odpowiedź
    „gdzie to jest" potrzebna jest RAZ, przy sięganiu po plik, nie przy każdym skanowaniu listy.

    Stos bez obecnej kopii dostaje jawne „(brak kopii pod ręką)" zamiast pustej linii: „obraz jest,
    ale nie mam go teraz" to inna odpowiedź niż „obrazu nie ma", i tylko ta pierwsza mówi
    użytkownikowi, że ma podłączyć dysk."""
    cov = row.coverage
    if not cov.stacks:
        return ""
    lines = [i18n.t("planner.stacks_header", n=len(cov.stacks))]
    lines += [path or i18n.t("planner.stack_no_copy") for _fid, path in cov.stacks]
    integrated = [f"{ch} {portfolio.format_hours(h * 3600)}"
                  for ch in _CHANNELS for h in (cov.integrated_by_channel.get(ch, 0.0),) if h > 0]
    if integrated:
        lines.append(i18n.t("planner.integrated_by_channel", parts=" · ".join(integrated)))
    return "\n".join(lines)


def cost_text(row):
    """Koszt czasu per paleta „B/D/W" (broadband/duoband/wąskopasmowy) — trzy liczby w stałym
    porządku, bo kolumna jest do PORÓWNYWANIA między wierszami, nie do czytania zdaniem."""
    c = row.cost
    return f"{c['broadband']:.1f} / {c['duoband']:.1f} / {c['narrowband']:.1f}"


def plan_text(row):
    """Kuratela w jednej komórce: status + priorytet („planned 2"). Cel nietknięty = kreska —
    `None` znaczy „user tego nie tknął", nie „odrzucił" (T4)."""
    if row.plan_status is None:
        return "—"
    label = i18n.t(f"planner.status_{row.plan_status}")
    return label if row.priority is None else f"{label} {row.priority}"


def can_show_frames(row):
    """Czy „Pokaż klatki celu →" ma prawo być aktywne (D-0731-7). Warunek to POKRYCIE, nie
    istnienie celu: bez kanonów archiwum most oddałby gridowi pusty filtr, a grid pokazałby
    PEŁNĄ bazę i skłamał (falsyfikator decyzji)."""
    return bool(row.coverage.archive_canons)


# Filtr kadru poproszony, ale nieczynny (`PlanResult.rig_filter`) → klucz noty. Tryb `find` noty
# nie dostaje: ekran mówi już, że szukanie pomija progi (`planner.find_note`).
_RIG_FILTER_OFF_KEYS = {"no_park": "planner.rig_filter_no_park",
                        "no_rigs": "planner.rig_filter_no_rigs"}


def rig_filter_text(result):
    """Progi filtra kadru jednym napisem („wypełnienie ≥30%, maks. paneli 1") - do licznika,
    not i tytułu paska. Progi z `PlanResult`, nie z kontrolek: napis opisuje POLICZONY wynik."""
    parts = []
    if result.min_fill is not None:
        parts.append(i18n.t("planner.rig_filter_fill", pct=f"{result.min_fill * 100:.0f}"))
    if result.max_panels is not None:
        parts.append(i18n.t("planner.rig_filter_panels", n=result.max_panels))
    return ", ".join(parts)


def header_notes(result, rig_name=None):
    """Noty nagłówka nocy jako pary `(waga, tekst)`; waga `warn` dla stanów, które FAŁSZUJĄ
    rachunek, `info` dla tych, które go tylko zawężają. Każda mówi, czego liczba NIE obejmuje —
    cichy ubytek zestawu albo celu to ta sama klasa błędu co cichy sufit listy.

    `rig_name` = bieżąca soczewka: przy włączonym filtrze kadru nota mówi, ile wierszy schowała
    soczewka PONAD to, co schował rdzeń."""
    notes = []
    if result.rig_filter in _RIG_FILTER_OFF_KEYS:
        notes.append(("warn", i18n.t(_RIG_FILTER_OFF_KEYS[result.rig_filter],
                                     filter=rig_filter_text(result))))
    if result.park_source == "none":
        notes.append(("warn", i18n.t("planner.park_unset")))
    else:
        notes.append(("info", i18n.t(
            "planner.park_source_db" if result.park_source == "db" else "planner.park_source_arg",
            park=", ".join(result.park))))
    if result.park_without_rigs:
        notes.append(("warn", i18n.t("planner.park_without_rigs",
                                     names=", ".join(result.park_without_rigs))))
    if result.unfiltered_mono:
        notes.append(("warn", i18n.t("planner.unfiltered_mono", n=result.unfiltered_mono)))
    if result.counts.get("hidden_by_status"):
        notes.append(("info", i18n.t("planner.hidden_by_status",
                                     n=result.counts["hidden_by_status"])))
    for rig in result.skipped_rigs:
        notes.append(("info", i18n.t("planner.rig_skipped", name=rig.telescope,
                                     reason=rig.reason)))
    hidden = lens_hidden(result, rig_name) if rig_name is not None else 0
    if hidden:
        notes.append(("info", i18n.t_plural("planner.lens_hidden", hidden, name=rig_name)))
    return tuple(notes)


def night_text(result):
    """Główna linia nagłówka: noc, stanowisko, ciemność żeglarska, Księżyc. Bierze `PlanResult`,
    nie pierwszy wiersz — przy pustej liście nagłówek nadal musi mieć z czego powstać."""
    site = result.site
    return i18n.t(
        "planner.night_header",
        night=result.night_date.isoformat(),
        site=site.name or i18n.t("planner.site_unnamed"),
        dark=f"{_hhmm(result.night.dark_start)}–{_hhmm(result.night.dark_end)}",
        moon=f"{result.moon.illumination * 100:.0f}%",
        alt=f"{result.moon.alt_deg:.0f}°")


def counts_text(result, rig_name=None):
    """Lejek celów w jednej linii: pula → po progach → nad horyzontem → widoczne. Liczniki opisują
    NOC, nie długość ekranu (kontrakt T3 - dlatego liczone przed limitem).

    Wyjątek to liczba WIERSZY przy soczewce, która chowa (filtr kadru + chip): „wierszy: 222" nad
    listą 99 wierszy byłoby nieprawdą o ekranie, więc obok stoi to, co widać („w soczewce A140R:
    99"), a nota nagłówka (`header_notes`) mówi dlaczego. Bez chowania napis jest ten sam co bez
    soczewki."""
    c = result.counts
    rows = c["rows"]
    hidden = lens_hidden(result, rig_name) if rig_name is not None else 0
    if hidden:
        rows = i18n.t("planner.rows_in_lens", rows=c["rows"], name=rig_name,
                      shown=len(result.rows) - hidden)
    if result.rig_filter == "on":
        # Filtr kadru zmienia ZNACZENIE licznika („wykonalne twoim sprzętem") - napis idzie razem
        # z semantyką, a liczba schowanych stoi obok, żeby odsiew nie wyglądał jak ubogi katalog.
        return i18n.t("planner.counts_rig", pool=c["pool"], feasible=c["feasible"],
                      filter=rig_filter_text(result),
                      hidden=i18n.t_plural("planner.rig_hidden", c["hidden_by_rig"]),
                      above=c["above_horizon"], visible=c["visible"], rows=rows)
    return i18n.t("planner.counts", pool=c["pool"], feasible=c["feasible"],
                  above=c["above_horizon"], visible=c["visible"], rows=rows)


def _hhmm(dt):
    return "—" if dt is None else dt.strftime("%H:%M")
