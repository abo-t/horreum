"""AR-62: linia raportu obecności w języku UI dla powodów zatrzymania spoza hamulca. Rdzeń niesie
polskie `aborted` dla CLI; widok składa zdanie z `abort_kind` i pól liczbowych. Falsyfikator: wróć
do doklejania `s.aborted` w `_format_presence` - w EN linia niesie polskie „serial woluminu”."""
import pytest

pytest.importorskip("PySide6")

from horreum import presence
from horreum.gui import i18n
from horreum.gui.pipeline import PipelineView

_ROOT = "X:\\ASTRO"


def _linia(**pola):
    s = presence.PresenceSummary(root=_ROOT, volume=pola.pop("volume", "1234-ABCD"),
                                 aborted="polskie zdanie rdzenia dla CLI", **pola)
    return PipelineView._format_presence(PipelineView, s)


def _nie_wykonano(powod):
    """Rama linii z katalogu (bieżący język) - test sprawdza zdanie powodu, nie ramę."""
    return i18n.t("pipeline.fmt.presence.not_done", reason=powod)


_PRZYPADKI = [
    (dict(abort_kind="volume_unknown", volume="?", serial="1234-ABCD"),
     "wolumin nieustalony - obecność zdejmujemy tylko wtedy, gdy wiadomo, czyje drzewo oglądamy; "
     "pod X:\\ASTRO jest wolumin 1234-ABCD",
     "volume undetermined - presence is removed only when we know whose tree we are looking at; "
     "X:\\ASTRO holds volume 1234-ABCD"),
    (dict(abort_kind="serial_unreadable"),
     "nie da się odczytać serialu woluminu pod X:\\ASTRO - podłącz dysk i powtórz",
     "cannot read the volume serial under X:\\ASTRO - connect the drive and try again"),
    (dict(abort_kind="serial_mismatch", serial="9999-0000"),
     "pod X:\\ASTRO jest wolumin 9999-0000, a zakres w bazie należy do 1234-ABCD - podłączony "
     "jest inny dysk",
     "X:\\ASTRO holds volume 9999-0000, but the scope in the database belongs to 1234-ABCD - "
     "a different drive is connected"),
    (dict(abort_kind="gone_set_changed"),
     "zbiór potwierdzonych zniknięć inny niż w sprawdzeniu, które zatwierdzono - dysk zmienił się "
     "od tamtej chwili, nic nie zapisano",
     "the set of confirmed vanished copies differs from the approved check - the disk changed "
     "since then, nothing was written"),
]


@pytest.mark.parametrize("pola,pl,en", _PRZYPADKI)
def test_powod_zatrzymania_w_obu_jezykach(pola, pl, en):
    i18n.set_lang("pl")
    assert _linia(**dict(pola)) == _nie_wykonano(pl)
    i18n.set_lang("en")
    linia = _linia(**dict(pola))
    assert linia == _nie_wykonano(en)
    assert "polskie zdanie" not in linia


@pytest.mark.parametrize("n,pl", [
    (1, "1 zniknięcie"), (2, "2 zniknięcia"), (4, "4 zniknięcia"), (5, "5 zniknięć"),
    (12, "12 zniknięć"), (13, "13 zniknięć"), (14, "14 zniknięć"), (22, "22 zniknięcia"),
    (25, "25 zniknięć"), (0, "0 zniknięć")])
def test_rozjazd_force_odmienia_liczbe_po_polsku(n, pl):
    i18n.set_lang("pl")
    linia = _linia(abort_kind="force_mismatch", force=7, confirmed_gone=n)
    assert linia == _nie_wykonano(f"zatwierdzono 7 do oznaczenia, a dysk potwierdza teraz {pl} "
                                  f"- nic nie zapisano")


@pytest.mark.parametrize("n,en", [(1, "1 vanished copy"), (2, "2 vanished copies"),
                                  (12, "12 vanished copies"), (0, "0 vanished copies")])
def test_rozjazd_force_po_angielsku(n, en):
    i18n.set_lang("en")
    linia = _linia(abort_kind="force_mismatch", force=7, confirmed_gone=n)
    assert linia == _nie_wykonano(f"7 approved for marking, but the disk now confirms {en} "
                                  f"- nothing was written")


def test_nieznany_kod_to_blad_nie_zdanie():
    with pytest.raises(ValueError):
        _linia(abort_kind="cos_nowego")


def test_zdanie_widoku_bez_kodu_idzie_wprost():
    """Pominięcie bez woluminu składa GUI już z katalogu - bez kodu nie ma czego tłumaczyć."""
    i18n.set_lang("en")
    s = presence.PresenceSummary(aborted=i18n.t("pipeline.presence.skipped_no_volume"))
    assert PipelineView._format_presence(PipelineView, s) == _nie_wykonano(
        i18n.t("pipeline.presence.skipped_no_volume"))
