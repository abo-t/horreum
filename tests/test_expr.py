"""Testy `horreum.expr` — bezpieczny ewaluator AST: arytmetyka, funkcje, brak operandu,
dzielenie przez zero, operand 0 != brak, odrzucanie niedozwolonych wezlow przy kompilacji.
Port 1:1 z dawcy fitsmirror (`test_expr.py`) — modul expr bez zmian (zero zaleznosci od schematu)."""

from __future__ import annotations

import pytest

from horreum import expr


def _val(text, env):
    return expr.eval_for(expr.compile_expr(text), env)


def test_arithmetic_and_round():
    r = _val("round(FOCALLEN / FOCRATIO, 2)", {"FOCALLEN": 600.0, "FOCRATIO": 150.0})
    assert r.ok and r.value == 4.0


def test_functions_abs_min_max():
    assert _val("abs(-3)", {}).value == 3
    assert _val("min(A, B, 10)", {"A": 5, "B": 7}).value == 5
    assert _val("max(A, B)", {"A": 5, "B": 7}).value == 7


def test_string_literal_passthrough():
    r = _val("'SkyWatcher EQ6-R Pro'", {})
    assert r.ok and r.value == "SkyWatcher EQ6-R Pro"


def test_missing_operand_skips_with_reason():
    r = _val("FOCALLEN / FOCRATIO", {"FOCALLEN": 600.0})  # brak FOCRATIO
    assert not r.ok and "brak operandu" in r.reason and "FOCRATIO" in r.reason


def test_none_in_env_is_missing_operand():
    r = _val("X + 1", {"X": None})  # puste value_num -> brak operandu
    assert not r.ok and "X" in r.reason


def test_zero_is_a_value_not_missing():
    # operand 0 to WARTOSC: 0 + 5 = 5 (nie "brak operandu")
    r = _val("X + 5", {"X": 0})
    assert r.ok and r.value == 5


def test_division_by_zero_skips():
    r = _val("A / B", {"A": 10, "B": 0})
    assert not r.ok and "zero" in r.reason


def test_type_error_skips_with_reason():
    # tekst tam gdzie liczba -> TypeError zlapany jako powod, nie wyjatek
    r = _val("X / 2", {"X": "EQ6"})
    assert not r.ok and "TypeError" in r.reason


@pytest.mark.parametrize(
    "text",
    [
        "__import__('os')",
        "obj.attr",
        "data[0]",
        "lambda: 1",
        "(x := 5)",
        "open('f')",  # funkcja spoza whitelisty
        "FOCALLEN ** 2",  # pow celowo zabroniony
    ],
)
def test_disallowed_nodes_rejected_at_compile(text):
    with pytest.raises(expr.ExprError):
        expr.compile_expr(text)


def test_empty_expression_rejected():
    with pytest.raises(expr.ExprError):
        expr.compile_expr("   ")
