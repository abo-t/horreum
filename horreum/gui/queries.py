"""Read-model osi TELESKOP (PLAN_gui §5 — read path). Czyste funkcje `con → list[Row]`,
testowalne BEZ Qt. ODCZYT nie jest „jedną klingą" (klinga dotyczy ZAPISU emitującego event) —
SELECT wolno wszędzie; zapis usera idzie WYŁĄCZNIE przez `horreum.repo`.

TWARDE OGRANICZENIE (PLAN_gui §4, rec. nr 6): wyłącznie **SQL-LITERAŁY + parametry `?`** oraz
wyłącznie **`con.execute`** (bez pandas/ORM/`read_sql` — ścieżki niewidziane przez meta-test AST,
`EXEC_METHODS=execute*`). Dynamiczny SQL (f-string) w tym pliku WYSADZIŁBY bramkę §7.1, mimo że to
czysty odczyt: `_first_sql_verb` zwraca `None` dla nie-literału, a `None` poza `repo.py`/`db.py`
= offender. Warianty/filtry => parametry `?` w stałym literale albo OSOBNE literały w gałęziach `if`,
NIGDY składanie stringa SQL.
"""


def active_telescopes(con):
    """Aktywne (KANONICZNE) teleskopy z licznością klatek — lista główna GUI.

    Filtr kanoniczności JAWNY (`WHERE t.merged_into IS NULL`, rec.R2 nr 2): widok
    `telescope_canonical` zwraca WSZYSTKIE wiersze (kanon + scalone z ich `canon_id`), więc sam join
    przez widok nie odsiewa scalonych — bez tego WHERE scalony `approved` wyciekłby jako osobny wiersz
    (§3b). Licznik agreguje po `canon_id` ścieżką `telescope_canonical → config → frame` (rec. nr 7):
    klatki scalonych członków rolują się pod kanon, kolizja kamery (dwa configi tej samej kamery)
    sumuje się pod jednym kanonem. `LEFT JOIN` => teleskop bez klatek ma `frame_count=0` (nie znika).
    Frame z `config_id IS NULL` (review) NIE dołącza się do żadnego configu => poza sumą (poprawne —
    jest w delcie, nie na osi). Zwraca wiersze: id, label, status, f_ratio_nominal, focal_nominal,
    frame_count."""
    return con.execute(
        "SELECT t.id, t.label, t.status, t.f_ratio_nominal, t.focal_nominal, "
        "       COUNT(fr.id) AS frame_count "
        "FROM telescope t "
        "LEFT JOIN telescope_canonical tc ON tc.canon_id = t.id "
        "LEFT JOIN config c ON c.telescope_id = tc.id "
        "LEFT JOIN frame fr ON fr.config_id = c.id "
        "WHERE t.merged_into IS NULL "
        "GROUP BY t.id "
        "ORDER BY t.id"
    ).fetchall()


def merged_under(con, canon_id):
    """Teleskopy scalone „pod" danym kanonem (widok szczegółu — co zwinięto w ten teleskop). Dzięki
    inwariantowi głębokość ≤ 1 (§3a) wszystkie są BEZPOŚREDNIMI członkami (`merged_into = canon_id`),
    więc prosty filtr po kolumnie wystarcza — nie ma głębszych łańcuchów do rozwijania. Zwraca wiersze:
    id, label, status, f_ratio_nominal, focal_nominal (puste, gdy `canon_id` nic nie scala)."""
    return con.execute(
        "SELECT id, label, status, f_ratio_nominal, focal_nominal "
        "FROM telescope WHERE merged_into = ? ORDER BY id",
        (canon_id,),
    ).fetchall()


def axis_events(con, telescope_id=None, limit=200):
    """Podgląd eventów osi teleskopu (audyt — kto/kiedy/before→after). `telescope_id=None` => cała oś
    (`target LIKE 'telescope:%'`, w tym `telescope.proposed/review` od groupera); inaczej historia
    JEDNEGO teleskopu (`target = 'telescope:<id>'`). Najnowsze pierwsze (`id DESC`), ucięte do `limit`.

    Dwie OSOBNE gałęzie z literałami SQL (nie jeden f-string) — wariant filtra przez parametr `?`
    w stałym literale, zgodnie z §4 (dynamiczny SQL wysadziłby bramkę). `target` składamy w Pythonie
    i wiążemy jako `?` — to wartość parametru, nie tekst SQL (literał pozostaje stały)."""
    if telescope_id is None:
        return con.execute(
            "SELECT id, ts, actor, verb, target, payload, reason FROM event "
            "WHERE target LIKE 'telescope:%' ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return con.execute(
        "SELECT id, ts, actor, verb, target, payload, reason FROM event "
        "WHERE target = ? ORDER BY id DESC LIMIT ?",
        (f"telescope:{telescope_id}", limit),
    ).fetchall()
