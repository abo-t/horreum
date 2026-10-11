-- 0033 - RANGA `harvest` w rodowodzie stosów (AR-102, decyzja D-1011-2).
--
-- PRZEBUDOWA `integration_input` - WYMUSZONA, nie wybrana: nowy token wchodzi do CHECK-a na
-- `asserted_by`, a SQLite nie umie zmienić CHECK-a inaczej niż przez CREATE new + INSERT SELECT +
-- DROP + RENAME (wzorzec 0016). Tabela jest PEŁNA (żywa pf4 2026-10-10: `history` 1762, `user` 1876,
-- `window` 3890), więc kopiujemy KOMPLET czterech kolumn co do jednej - pominięta kolumna to cicha
-- utrata werdyktów ręki (`excluded`) albo dowodów.
--
-- CO ZNACZY `harvest`: zbiór DOKŁADNY wejść stosu wciągniętego żniwami z wydania Horreum - dowód
-- MANIFESTU wydania (nazwy w historii pliku ↔ nazwy lightów, które Horreum sam położył na stół),
-- a nie zeznanie pliku dopasowane do okna czasu (`history`). Do v33 oba nosiły `history`, więc
-- przebieg rodowodu przy oknie RÓWNEJ liczności (korekta `DATE-OBS` lightu ze zbioru, następczyni,
-- przepięcie osi) przepisywał zbiór dokładny oknem: wstawiał klatkę odrzuconą przez WBPP w miejsce
-- użytej (test bo na scratchu fali 9). Ranga rosnąco: window < history < harvest < user
-- (`repo.RANGA_ASSERT`) - manifest bije okno potwierdzone licznikiem, werdykt ręki bije wszystko.
--
-- PRZERANGOWANIE wierszy sprzed v33: `history` zapisany przez żniwa rozpoznajemy po DZIENNIKU -
-- zdarzenie `integration.linked` aktora `harvest` dla tej samej pary (integracja, klatka). SQL zna
-- ten fakt bez czytania plików, bo `stacks.record_harvest_inputs` emituje je przy każdym nowym
-- wierszu i każdym podniesieniu rangi. GRANICA ŚWIADOMA: wiersz `history`, który zostawiło stare
-- żniwo spoza późniejszego zbioru (Z1 przed v33 zdejmował tylko `window`), też ma takie zdarzenie
-- i przejdzie na `harvest`; populacja żywej bazy w chwili migracji = 0 zdarzeń aktora `harvest`
-- (sonda bn), a nadmiar `history` z przebiegu łańcucha (bez zdarzenia żniw) zostaje `history`
-- i kolejne „Zamknij i przyjmij” go zdejmie (predykat `harvest_lineage_pending` go widzi).

CREATE TABLE integration_input_new (
    integration_id INTEGER NOT NULL REFERENCES integration (id),
    input_frame_id INTEGER NOT NULL REFERENCES frame (id),
    asserted_by    TEXT    NOT NULL CHECK (asserted_by IN ('history', 'window', 'harvest', 'user')),
    excluded       INTEGER NOT NULL DEFAULT 0,
    UNIQUE (integration_id, input_frame_id)
);

INSERT INTO integration_input_new (integration_id, input_frame_id, asserted_by, excluded)
    SELECT ii.integration_id, ii.input_frame_id,
           CASE WHEN ii.asserted_by = 'history' AND EXISTS (
                    SELECT 1 FROM event e
                     WHERE e.verb = 'integration.linked' AND e.actor = 'harvest'
                       AND e.target = 'integration:' || ii.integration_id
                       AND json_extract(e.payload, '$.input_frame_id') = ii.input_frame_id)
                THEN 'harvest' ELSE ii.asserted_by END,
           ii.excluded
      FROM integration_input ii;

DROP TABLE integration_input;
ALTER TABLE integration_input_new RENAME TO integration_input;

CREATE INDEX idx_integration_input_frame ON integration_input (input_frame_id);
