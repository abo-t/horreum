"""Qt-WOLNA logika progresu (`horreum.gui.progress`) — throttling i migawka liczników. BEZ
`importorskip` (chodzi w izolowanym clone bez PySide6, jak `test_gui_isolation`): to dowód, że
logika progresu jest naprawdę Qt-free i testowalna bez okna."""
from horreum.gui.progress import counts_snapshot, should_emit
from horreum.scan import ScanSummary


def test_should_emit_pierwszy_ostatni_i_co_n():
    assert should_emit(1, 1000) is True                 # pierwszy → pasek rusza
    assert should_emit(1000, 1000) is True              # ostatni → domyka 100%
    assert should_emit(50, 1000, every=50) is True      # co `every`
    assert should_emit(51, 1000, every=50) is False     # pomiędzy → przerzedzone
    assert should_emit(0, 0) is False                   # puste drzewo → nic do pokazania


def test_counts_snapshot_to_kopia_nie_zywy_obiekt():
    """Migawka = DICT-kopia; mutacja `summary` PO snapshocie nie zmienia wcześniejszego dicta
    (inaczej slot w głównym wątku czytałby pola w trakcie mutacji przez worker → race)."""
    s = ScanSummary(files=5, frames_new=3, skipped=1)
    snap = counts_snapshot(s)
    assert snap["files"] == 5 and snap["frames_new"] == 3 and snap["skipped"] == 1
    s.files = 99                                         # worker mutuje dalej w pętli
    assert snap["files"] == 5                            # migawka NIENARUSZONA
