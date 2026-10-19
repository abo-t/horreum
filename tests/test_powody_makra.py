"""Powody bramek celu i makra z KODEM (AR-181): każde miejsce, w którym `macro` (i `expr.eval_for`,
który makro woła) rodzi powód pominięcia albo odmowy, oddaje `PowodPozycji` - zdanie PL znak w znak
jak dotąd (CLI, testy, sklejenia biorą je jak tekst), kod `macro_*` i parametry, a okno mówi je
w języku UI (`gui.wb_worker.tekst_powodu`).

Test złoty: zdanie PL każdej drogi jest LITERAŁEM (zmiana znaku = czerwień; polskie znaki od AR-228)
i zdanie EN jest DOKŁADNE - część polszczyzny makra nie ma polskich liter (`brak obecnej kopii`,
`frame nieobecny w bazie`), więc sam brak polskich liter nie odróżniłby powrotu do surowej prozy od
tłumaczenia. Powód wyrażenia (`compute`/`assign`) jedzie
parametrem `inner`: z kodem, gdy to brak operandu albo dzielenie przez zero, prozą-granicą, gdy to
tekst wyjątku Pythona."""
import pytest

from horreum import expr, macro
from horreum.item_reasons import PowodPozycji


def _cel(**kw):
    """Wiersz `queries.writeback_frame_targets` jednej klatki z jedną obecną kopią."""
    w = {"frame_id": 1, "filetype": "fits", "sha1_data_uncomputable": 0, "location_id": 7,
         "path": "X:/L/a.fits", "header_hash": "hh", "hdu_index": 0, "compressed": 0, "n_sum": 0}
    w.update(kw)
    return w


def _karta(keyword, raw, *, num=None, vtype="str", idx=0):
    return {"keyword": keyword, "idx": idx, "value_raw": raw, "value_num": num,
            "value_type": vtype, "comment": None}


def _makro(keyword, op, wyrazenie, karty, computes=()):
    """Powód pominięcia jedynej klatki przebiegu makra nad `karty`."""
    md = macro.MacroDef(assign=macro.Assign(keyword=keyword, op=op, expr=wyrazenie),
                        computes=[macro.ComputeStep(n, e) for n, e in computes])
    run = macro.run_macro(md, [1], targets_fn=lambda ids: [_cel()], cards_fn=lambda fid: karty)
    assert not run.touched, run.touched
    (s,) = run.skipped
    return s.reason


def _cel_odmowa(**kw):
    return macro.resolve_target([_cel(**kw)])[1]


_OGNISKOWA = [_karta("FOCALLEN", "600", num=600.0, vtype="float")]
_HISTORIA = [_karta("HISTORY", "a"), _karta("HISTORY", "b", idx=1)]

# (droga, powód z prawdziwego wywołania, kod, zdanie PL - polskie znaki od AR-228, zdanie EN)
_DROGI = [
    ("resolve_target RAW", lambda: _cel_odmowa(filetype="raw"), "macro_raw",
     "plik RAW (DSLR) -- Horreum go NIE zapisuje (read-only)",
     "RAW file (DSLR) - Horreum does NOT write it (read-only)"),
    ("resolve_target bez obecnej kopii", lambda: _cel_odmowa(location_id=None),
     "macro_no_present_copy", "brak obecnej kopii do zapisu (wszystkie present=0)",
     "no present copy to write (all present=0)"),
    ("resolve_target wiele kopii", lambda: macro.resolve_target([_cel(), _cel(location_id=8)])[1],
     "macro_many_copies", "wiele obecnych kopii (2) -- writeback poza v1 (D-W1)",
     "several present copies (2) - writeback outside v1 (D-W1)"),
    ("resolve_target kompresja", lambda: _cel_odmowa(compressed=1), "macro_compressed",
     "skompresowany master -- edycja poza krokiem 4 (T6)",
     "compressed master - editing is outside step 4 (T6)"),
    ("resolve_target degenerat", lambda: _cel_odmowa(sha1_data_uncomputable=1), "macro_degenerate",
     "tożsamość nieobliczalna (degenerat) -- zapis rozdwoiłby klatkę (D-X-13)",
     "identity cannot be computed (degenerate) - a write would split the frame (D-X-13)"),
    ("resolve_target bez header_hash", lambda: _cel_odmowa(header_hash=None),
     "macro_no_header_hash", "brak header_hash (plik nieczytelny) -- brak kontroli zapisu",
     "no header_hash (unreadable file) - no write control"),
    ("run_macro klatka znikła", lambda: macro.run_macro(
        {"assign": {"keyword": "TELESCOP", "op": "set", "expr": "'X'"}}, [1],
        targets_fn=lambda ids: [], cards_fn=lambda fid: []).skipped[0].reason,
     "macro_frame_gone", "frame nieobecny w bazie", "frame missing from the database"),
    ("plan_manual_change klatka znikła",
     lambda: macro.plan_manual_change([], "TELESCOP", "X", cards_fn=lambda lid: [])[1],
     "macro_frame_gone", "frame nieobecny w bazie", "frame missing from the database"),
    ("_evaluate_change set bez karty", lambda: _makro("TELESCOP", "set", "'RC8'", _OGNISKOWA),
     "macro_set_missing", "brak karty 'TELESCOP' do modyfikacji (użyj add)",
     "no card 'TELESCOP' to modify (use add)"),
    ("_evaluate_change wiele wystąpień", lambda: _makro("HISTORY", "set", "'x'", _HISTORIA),
     "macro_idx_required", "keyword 'HISTORY' ma wiele wystąpień -- wymagany jawny idx",
     "keyword 'HISTORY' occurs more than once - an explicit idx is required"),
    ("_evaluate_change wystąpienie spoza nagłówka", lambda: macro.run_macro(
        macro.MacroDef(assign=macro.Assign(keyword="HISTORY", op="set", expr="'x'", idx=2)), [1],
        targets_fn=lambda ids: [_cel()], cards_fn=lambda fid: _HISTORIA).skipped[0].reason,
     "card_idx_missing", "karta 'HISTORY' nie ma wystąpienia [2] - w nagłówku jest ich 2",
     "card 'HISTORY' has no occurrence [2] - the header has 2"),
    ("_evaluate_change add na istniejącej", lambda: _makro("FOCALLEN", "add", "800", _OGNISKOWA),
     "macro_add_exists", "karta 'FOCALLEN' już istnieje (użyj set)",
     "card 'FOCALLEN' already exists (use set)"),
    ("_evaluate_change compute bez operandu", lambda: _makro(
        "FOCALLEN", "set", "round(new, 2)", _OGNISKOWA, [("new", "FOCALLEN / FOCRATIO")]),
     "macro_compute", "compute new: brak operandu: FOCRATIO", "compute new: missing operand: FOCRATIO"),
    ("_evaluate_change compute przez zero", lambda: _makro(
        "FOCALLEN", "set", "round(new, 2)", _OGNISKOWA, [("new", "FOCALLEN / 0")]),
     "macro_compute", "compute new: dzielenie przez zero", "compute new: division by zero"),
    ("_evaluate_change assign przez zero", lambda: _makro("FOCALLEN", "set", "FOCALLEN / 0",
                                                          _OGNISKOWA),
     "macro_assign", "assign: dzielenie przez zero", "assign: division by zero"),
    ("_evaluate_change assign wyjątek Pythona", lambda: _makro("FOCALLEN", "set", "FOCALLEN + 'x'",
                                                               _OGNISKOWA),
     "macro_assign", "assign: TypeError: unsupported operand type(s) for +: 'float' and 'str'",
     "assign: TypeError: unsupported operand type(s) for +: 'float' and 'str'"),
    ("_evaluate_change wynik niecałkowity", lambda: _makro(
        "NAXIS1", "set", "2.5", [_karta("NAXIS1", "4", num=4.0, vtype="int")]),
     "macro_not_int", "wynik niecałkowity (2.5) dla keyworda 'NAXIS1' typu int",
     "non-integer result (2.5) for int keyword 'NAXIS1'"),
    ("_evaluate_change typ", lambda: _makro(
        "FOCRATIO", "set", "abc", [_karta("FOCRATIO", "7.5", num=7.5, vtype="float")]),
     "macro_type_mismatch", "wartość 'abc' nie pasuje do typu 'float'",
     "value 'abc' does not match type 'float'"),
    ("evaluate_manual_change wiele wystąpień",
     lambda: macro.evaluate_manual_change(_HISTORIA, "HISTORY", "x").reason, "macro_manual_many",
     "keyword 'HISTORY' ma wiele wystąpień -- edycja ręczna poza krokiem 4",
     "keyword 'HISTORY' occurs more than once - manual editing is outside step 4"),
    ("evaluate_manual_change wynik niecałkowity", lambda: macro.evaluate_manual_change(
        [_karta("NAXIS1", "4", num=4.0, vtype="int")], "NAXIS1", "2.5").reason,
     "macro_manual_not_int", "wynik niecałkowity (2.5) dla keyworda typu int",
     "non-integer result (2.5) for an int keyword"),
    ("evaluate_manual_change typ", lambda: macro.evaluate_manual_change(
        [_karta("FOCRATIO", "7.5", num=7.5, vtype="float")], "FOCRATIO", "abc").reason,
     "macro_type_mismatch", "wartość 'abc' nie pasuje do typu 'float'",
     "value 'abc' does not match type 'float'"),
]
_IDS = [d[0] for d in _DROGI]


@pytest.mark.parametrize("droga, wywolanie, kod, pl, _en", _DROGI, ids=_IDS)
def test_ZLOTE_powody_makra_PL_znak_w_znak_z_kodem(droga, wywolanie, kod, pl, _en):
    """Każda droga rodzenia powodu w `macro` (18 miejsc) i dwa powody `expr.eval_for`: zdanie PL
    = literał (polskie znaki od AR-228), `PowodPozycji` z kodem drogi. Falsyfikator: jeden znak zdania
    w `macro.py` zmieniony (`--` → `-`) albo miejsce z gołym f-stringiem → czerwień."""
    powod = wywolanie()
    assert str(powod) == pl, (droga, str(powod))
    assert isinstance(powod, PowodPozycji) and powod.code == kod, (droga, powod)


@pytest.mark.parametrize("droga, wywolanie, kod, pl, en", _DROGI, ids=_IDS)
def test_powody_makra_mowia_w_UI_PL_znak_w_znak_a_EN_dokladnie(droga, wywolanie, kod, pl, en):
    """Okno mówi powód makra w języku UI: PL = zdanie rdzenia, EN = DOKŁADNE zdanie katalogu, także
    z powodem wyrażenia w środku (`compute`/`assign` - zlokalizowany `inner`, tekst wyjątku Pythona
    znak w znak). Falsyfikator: miejsce z gołym f-stringiem albo `inner` bez kodu → EN po polsku."""
    pytest.importorskip("PySide6")
    from horreum.gui import i18n
    from horreum.gui.wb_worker import tekst_powodu
    powod = wywolanie()
    try:
        i18n.set_lang("pl")
        assert tekst_powodu(powod) == pl, (droga, tekst_powodu(powod))
        i18n.set_lang("en")
        assert tekst_powodu(powod) == en, (droga, tekst_powodu(powod))
    finally:
        i18n.set_lang("pl")


def test_powod_wyrazenia_z_kodem_a_tekst_wyjatku_proza():
    """`expr.eval_for`: brak operandu i dzielenie przez zero mają kod (nazwa operandu parametrem),
    tekst wyjątku Pythona zostaje prozą - jawna granica, jak tekst systemu u pisarza; `missing_operand`
    bez zmian (makro po nim przechodzi na literał). Falsyfikator: `eval_for` z gołym f-stringiem."""
    brak = expr.eval_for(expr.compile_expr("A / B"), {"A": 1})
    assert brak.missing_operand and brak.reason.code == "macro_missing_operand"
    assert dict(brak.reason.params) == {"name": "B"} and str(brak.reason) == "brak operandu: B"
    zero = expr.eval_for(expr.compile_expr("A / 0"), {"A": 1})
    assert not zero.missing_operand and zero.reason.code == "macro_zero_division"
    typ = expr.eval_for(expr.compile_expr("A + 'x'"), {"A": 1})
    assert not isinstance(typ.reason, PowodPozycji) and typ.reason.startswith("TypeError: ")


# ============================ AR-194: błędy definicji makra i wyrażenia z kodem


def _blad(wywolanie):
    """Wyjątek definicji z prawdziwego wywołania (`ExprError` albo `ValueError` makra)."""
    with pytest.raises((expr.ExprError, ValueError)) as info:
        wywolanie()
    return info.value


def _wezel_store():
    """`Name(Store)` wprost - z tekstu nieosiągalne (`NamedExpr` pada wcześniej, zmierzone), więc
    drzewo budowane ręką; `_validate` to prawdziwa straż."""
    import ast
    drzewo = ast.Expression(body=ast.Name(id="X", ctx=ast.Store()))
    return expr._validate(drzewo)


def _eval_wezla():
    import ast
    return expr._eval(ast.List(elts=[], ctx=ast.Load()), {})


# (droga, wywołanie rzucające, kod, zdanie PL - polskie znaki od AR-228, zdanie EN)
_DEFINICJE = [
    ("compile_expr puste", lambda: expr.compile_expr("   "), "expr_empty", "puste wyrażenie",
     "empty expression"),
    ("compile_expr składnia", lambda: expr.compile_expr("1 +"), "expr_syntax",
     "błąd składni: invalid syntax (<unknown>, line 1)",
     "syntax error: invalid syntax (<unknown>, line 1)"),
    ("_validate stała", lambda: expr.compile_expr("None"), "expr_bad_const",
     "niedozwolona stała: None", "constant not allowed: None"),
    ("_validate przypisanie", _wezel_store, "expr_store", "przypisanie w wyrażeniu niedozwolone",
     "assignment inside an expression is not allowed"),
    ("_validate wywołanie spoza listy", lambda: expr.compile_expr("foo(1)"), "expr_call_not_allowed",
     "dozwolone tylko wywołania z białej listy funkcji",
     "only calls of allowed functions are permitted"),
    ("_validate nazwane", lambda: expr.compile_expr("min(a=1)"), "expr_kwargs",
     "argumenty nazwane niedozwolone", "keyword arguments are not allowed"),
    ("_validate rozpakowanie", lambda: expr.compile_expr("max(*A)"), "expr_starred",
     "rozpakowanie argumentów niedozwolone", "argument unpacking is not allowed"),
    ("_validate element", lambda: expr.compile_expr("A.b"), "expr_bad_node",
     "niedozwolony element wyrażenia: Attribute", "element not allowed in an expression: Attribute"),
    ("_eval element", _eval_wezla, "expr_bad_node", "niedozwolony element wyrażenia: List",
     "element not allowed in an expression: List"),
    ("from_dict bez assign", lambda: macro.MacroDef.from_dict({"name": "x"}), "macro_def_no_assign",
     "definicja makra wymaga pola 'assign'", "the macro definition needs an 'assign' field"),
    ("from_dict assign bez pola", lambda: macro.MacroDef.from_dict(
        {"assign": {"keyword": "OBJECT", "op": "set"}}), "macro_def_bad_assign",
     "niepoprawne 'assign': 'expr'", "invalid 'assign': 'expr'"),
    ("from_dict operacja", lambda: macro.MacroDef.from_dict(
        {"assign": {"keyword": "OBJECT", "op": "del", "expr": "1"}}), "macro_def_bad_op",
     "niedozwolona operacja: 'del'", "operation not allowed: 'del'"),
]
_IDS_DEF = [d[0] for d in _DEFINICJE]


@pytest.mark.parametrize("droga, wywolanie, kod, pl, _en", _DEFINICJE, ids=_IDS_DEF)
def test_ZLOTE_bledy_definicji_PL_znak_w_znak_z_kodem(droga, wywolanie, kod, pl, _en):
    """Każde miejsce, w którym `expr` odrzuca wyrażenie, i każda odmowa `MacroDef.from_dict`: `str`
    wyjątku = zdanie PL z polskimi znakami (AR-228), `powod` z kodem drogi, klasa wyjątku bez zmian
    (`ExprError` nie jest `ValueError`, odmowa definicji jest). Falsyfikator: `raise` z gołym
    f-stringiem albo znak zdania zmieniony."""
    exc = _blad(wywolanie)
    assert str(exc) == pl, (droga, str(exc))
    assert isinstance(exc.powod, PowodPozycji) and exc.powod.code == kod, (droga, exc.powod)
    assert str(exc.powod) == pl
    assert isinstance(exc, ValueError) == kod.startswith("macro_def_"), (droga, type(exc))


@pytest.mark.parametrize("droga, wywolanie, kod, pl, en", _DEFINICJE, ids=_IDS_DEF)
def test_bledy_definicji_mowia_w_UI_PL_znak_w_znak_a_EN_dokladnie(droga, wywolanie, kod, pl, en):
    """Okno mówi błąd definicji przez `tekst_powodu(powod_wyjatku(exc))` - jak `grid._run`: PL =
    zdanie rdzenia, EN = DOKŁADNE zdanie katalogu (tekst `SyntaxError` Pythona znak w znak).
    Falsyfikator: wpis EN = kopia PL albo `raise` bez powodu → PL w EN."""
    pytest.importorskip("PySide6")
    from horreum.gui import i18n
    from horreum.gui.wb_worker import tekst_powodu
    from horreum.item_reasons import powod_wyjatku
    exc = _blad(wywolanie)
    try:
        i18n.set_lang("pl")
        assert tekst_powodu(powod_wyjatku(exc)) == pl, droga
        i18n.set_lang("en")
        assert tekst_powodu(powod_wyjatku(exc)) == en, droga
    finally:
        i18n.set_lang("pl")


def test_meta_bledy_definicji_tylko_z_kodem():
    """Bramka AST (żeby nie wracało): każdy `raise ExprError(...)` w `expr` niesie `PowodPozycji(...)`,
    a każdy `raise` w `MacroDef.from_dict` - `OdmowaZPowodem(PowodPozycji(...))`; liczby miejsc
    jak w zbiorze (9 i 3). Falsyfikator: `raise ExprError("puste wyrażenie")`."""
    import ast
    import inspect
    import textwrap

    def _z_powodem(wywolanie, klasa):
        return (isinstance(wywolanie, ast.Call) and getattr(wywolanie.func, "id", None) == klasa
                and len(wywolanie.args) == 1 and isinstance(wywolanie.args[0], ast.Call)
                and getattr(wywolanie.args[0].func, "id", None) == "PowodPozycji")
    raises = [w.exc for w in ast.walk(ast.parse(inspect.getsource(expr))) if isinstance(w, ast.Raise)
              and w.exc is not None and getattr(getattr(w.exc, "func", None), "id", None) == "ExprError"]
    assert len(raises) == 9 and all(_z_powodem(r, "ExprError") for r in raises), \
        [ast.unparse(r)[:60] for r in raises]
    zrodlo = textwrap.dedent(inspect.getsource(macro.MacroDef.from_dict))
    raises = [w.exc for w in ast.walk(ast.parse(zrodlo)) if isinstance(w, ast.Raise)]
    assert len(raises) == 3 and all(_z_powodem(r, "OdmowaZPowodem") for r in raises), \
        [ast.unparse(r)[:60] for r in raises]


def test_blad_wyrazenia_w_obliczeniu_jedzie_z_kodem_a_reszta_bez_zmian():
    """`eval_for`: `ExprError` z obliczenia (węzeł spoza listy w `_eval`) oddaje powód z kodem
    `expr_bad_node` - makro wstawia go parametrem `inner`; brak operandu, dzielenie przez zero
    i `TypeError` - tekst i typ powodu bez zmian. Falsyfikator: `reason=str(exc)`."""
    import ast
    obce = expr.Expr(text="[]", node=ast.Expression(body=ast.List(elts=[], ctx=ast.Load())),
                     names=frozenset())
    wynik = expr.eval_for(obce, {})
    assert not wynik.ok and isinstance(wynik.reason, PowodPozycji)
    assert wynik.reason.code == "expr_bad_node" and str(wynik.reason) == "niedozwolony element wyrażenia: List"
    brak = expr.eval_for(expr.compile_expr("A / B"), {"A": 1})
    assert (brak.missing_operand, brak.reason.code, str(brak.reason)) == (
        True, "macro_missing_operand", "brak operandu: B")
    zero = expr.eval_for(expr.compile_expr("A / 0"), {"A": 1})
    assert (zero.missing_operand, zero.reason.code, str(zero.reason)) == (
        False, "macro_zero_division", "dzielenie przez zero")
    typ = expr.eval_for(expr.compile_expr("A + 'x'"), {"A": 1})
    assert type(typ.reason) is str and typ.reason == (
        "TypeError: unsupported operand type(s) for +: 'int' and 'str'")


# ============================ AR-228: zdania z polskimi znakami w stronach kodowych konsoli


def _kody(powod):
    """Kod powodu i kody powodów zagnieżdżonych w parametrach (`inner`)."""
    if not isinstance(powod, PowodPozycji):
        return set()
    return {powod.code}.union(*(_kody(v) for _k, v in powod.params))


def test_zdania_makra_i_wyrazenia_mieszcza_sie_w_cp1250():
    """AR-228: zdania PL powodów makra i wyrażenia niosą polskie znaki - świadoma reguła: mieszczą się
    w stronie ANSI cp1250 (zapis tekstu przy wyjściu przekierowanym na Windows: log, kolumna prozowa,
    przyszły druk). CLI tych zdań dziś nie drukuje, a jego stdout jest UTF-8 (`cli._main`,
    `reconfigure`), więc strony OEM cp852 nie pilnujemy - brakuje w niej typografii („ ”, …), którą
    zdania mogą kiedyś nieść. Kodujemy zdania SFORMATOWANE z prawdziwych dróg (`_DROGI`, `_DEFINICJE`)
    i dwa z próbką z polskimi znakami (wartość pola, nazwa operandu); zbiór dróg pokrywa KAŻDY kod
    `PowodPozycji` z `expr` i `macro` (AST), więc nowa droga bez próbki jest czerwienią. Falsyfikator:
    „→” w zdaniu."""
    import ast
    import inspect
    powody = [w() for _d, w, *_r in _DROGI] + [_blad(w).powod for _d, w, *_r in _DEFINICJE]
    powody += [
        macro.evaluate_manual_change([_karta("FOCRATIO", "7.5", num=7.5, vtype="float")], "FOCRATIO",
                                     "żółć").reason,
        expr.eval_for(expr.compile_expr("A / ŻÓŁW"), {"A": 1}).reason,
    ]
    assert str(powody[-2]) == "wartość 'żółć' nie pasuje do typu 'float'" and str(powody[-1]) == (
        "brak operandu: ŻÓŁW")
    w_zrodle = {w.args[1].value for m in (expr, macro) for w in ast.walk(ast.parse(inspect.getsource(m)))
                if isinstance(w, ast.Call) and getattr(w.func, "id", None) == "PowodPozycji"}
    assert set().union(*(_kody(p) for p in powody)) == w_zrodle
    for zdanie in map(str, powody):
        assert zdanie.encode("cp1250").decode("cp1250") == zdanie, zdanie
