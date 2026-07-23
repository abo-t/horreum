"""Współdzielone fixture'y pytest. `s8` = deterministyczna baza §8 (PLAN_gui §8) — jeden builder
dla testów logiki read-modelu (5.2) i przyszłych testów GUI; bez Qt, bez plików na dysku."""
import pytest

from fixture_s8 import seed, seed_object_axis

from horreum import db
from horreum.gui import i18n   # Qt-wolny (słownik) — import bezpieczny bez PySide6


@pytest.fixture(autouse=True)
def _reset_i18n_lang():
    """`i18n._LANG` to jedyny PROCESOWO-GLOBALNY stan wpływający na czyste funkcje prezentacji
    (`t`/`t_plural`); test z `set_lang('en')` bez resetu skaziłby kolejne (porażki zależne od
    KOLEJNOŚCI — łamią determinizm baterii). Reset PRZED każdym testem (R-i18n #4). `_missing`
    (zbiór już-zalogowanych braków — log raz) też zerowany: przyszły test „warn raz na klucz"
    inaczej stałby się order-dependent (recenzja fundamentu #1)."""
    i18n.set_lang(i18n.DEFAULT)
    i18n._missing.clear()
    yield


@pytest.fixture
def s8(tmp_path):
    """(con, ids) świeżej bazy §8. `ids` = dict id-ków (A/B/C/D, cam1/cam2, cfg_*, frames)."""
    con = db.open_db(str(tmp_path / "s8.db"))
    ids = seed(con)
    yield con, ids
    con.close()


@pytest.fixture
def s8_obj(tmp_path):
    """(con, ids) bazy §8 rozszerzonej o oś OBIEKT (PLAN_gui_object §8). `ids` dodatkowo: `objects`
    (NGC7000/M42) + frame'y obiektowe (objrev1/2, calib_flat, present0). Telescope-liczniki bez zmian."""
    con = db.open_db(str(tmp_path / "s8_obj.db"))
    ids = seed_object_axis(con)
    yield con, ids
    con.close()
