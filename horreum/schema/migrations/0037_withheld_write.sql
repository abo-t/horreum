-- 0037 - ZAPIS Z ZEZNANIEM WSTRZYMANYM (AR-82): plik zapisany, a zeznanie klatki (`header`/`cards`)
-- nie przyjęło jego nagłówka, bo głosem klatki mówi inna obecna kopia (reguła kopii wiodącej, AR-4).
--
-- PRZYROST (jedna nowa tabela + dwie kolumny `ADD COLUMN`) - zero przebudowy, zero ruszonych wierszy.
--
-- Dawniej commit meldował taki plik jako 'applied', wpisy stagingu dostawały 'applied', a nagrobek
-- ręki gasł - choć zeznanie zostało przy innej kopii. Teraz wynik to 'withheld', wpisy 'failed'
-- z wiązaniem `withheld_id`, nagrobek żyje, a wiersz `withheld_write` czeka na dokończenie:
-- przejęcie zeznania tej kopii (gest „Ta kopia prowadzi”, etap Dostawy) albo pełny odczyt pliku,
-- przy którym zeznanie płynie z tej kopii. Dokończenie i rozliczenie robi WYŁĄCZNIE klinga `repo`.
--
-- `kind`: `commit` - zapis zmiany; `undo` - cofnięcie, którego nagłówek nie wrócił do zeznania
-- (bez wpisów stagingu i bez nagrobka - cofnięcie odtwarza go samo).
-- `header_hash` = nagłówek, który plik niósł po zapisie: dokończenie wymaga go na dysku.
-- `reason` = zdanie dla człowieka z chwili wstrzymania (cofnięcie nie ma wpisów stagingu, które by je
-- niosły; sterownik cofnięcia gestu czyta je stąd po wznowieniu).
-- `hand_version` = wersja decyzji ręki o obiekcie klatki (najnowsze zdarzenie ustanawiające nagrobek,
-- `0` = klatka bez nagrobka) utrwalona PRZED pierwszym bajtem zapisu (`header_backups.hand_version`) -
-- dokończenie gasi nagrobek wyłącznie przy tej samej wersji; nowsza decyzja człowieka zostaje, a NULL
-- (backup sprzed 0037) to wersja nieznana - nagrobek zostaje do oka.
-- `actor` = aktor zapisu; pod nim skan dociąga zeznanie przy dokończeniu, nie pod własnym.
-- `settled_how`: `completed` (zeznanie przyjęło zapis), `undone` (commit cofnięty, zanim zeznanie
-- go przyjęło), `superseded` (pełny odczyt pliku dowiódł nowszego stanu lokacji: inny nagłówek albo
-- lokacja przepięta na inną klatkę - zapis już nie leży na dysku tej klatki).
CREATE TABLE withheld_write (
    id            INTEGER PRIMARY KEY,
    kind          TEXT    NOT NULL CHECK (kind IN ('commit', 'undo')),
    location_id   INTEGER NOT NULL REFERENCES location (id),
    frame_id      INTEGER NOT NULL REFERENCES frame (id),
    commit_id     INTEGER NOT NULL REFERENCES commits (id),
    inplace_op_id INTEGER REFERENCES inplace_op (id),
    item_id       INTEGER REFERENCES pending_object_change (id),
    header_hash   TEXT    NOT NULL CHECK (length(header_hash) > 0),
    object_written INTEGER NOT NULL CHECK (object_written IN (0, 1)),
    hand_version  INTEGER,
    reason        TEXT    NOT NULL CHECK (length(reason) > 0),
    actor         TEXT    NOT NULL CHECK (length(actor) > 0),
    opened_at     TEXT    NOT NULL CHECK (length(opened_at) > 0),
    settled_at    TEXT,
    settled_how   TEXT CHECK (settled_how IN ('completed', 'undone', 'superseded')),
    CHECK ((settled_at IS NULL) = (settled_how IS NULL)),
    CHECK (kind = 'commit' OR (object_written = 0 AND hand_version IS NULL))
);
CREATE INDEX idx_withheld_open ON withheld_write (location_id) WHERE settled_at IS NULL;
CREATE INDEX idx_withheld_commit ON withheld_write (commit_id, location_id);

-- Wpisy stagingu próby, której zeznanie wstrzymano: status 'failed' (CHECK `pending_changes` bez
-- zmian), a wiązanie odróżnia je od porażki zapisu - skan potwierdzający (`confirm_failed_commit_by_scan`)
-- ich nie rusza, ich właścicielem jest dokończenie wstrzymania.
ALTER TABLE pending_changes ADD COLUMN withheld_id INTEGER REFERENCES withheld_write (id);

-- Wersja decyzji ręki o obiekcie klatki w chwili utrwalenia backupu (obie drogi zapisu: atomowa
-- `insert_header_backup`, w miejscu `begin_inplace_commit`) - przed pierwszym bajtem mutacji pliku.
-- `0` = klatka bez nagrobka w tej chwili; NULL = backup sprzed 0037 (wersja nieznana).
ALTER TABLE header_backups ADD COLUMN hand_version INTEGER;
