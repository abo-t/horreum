-- 0045 - WERDYKT PLIKÓW OBOK ŚCIEŻKI ŚLADU COFNIĘCIA (AR-127): co zostało obok ścieżki po cofnięciu drogą
-- atomową - kopia wyparta K, kopia zwrotna Z = `_nazwa_zwrotna(K)`, plik tymczasowy T (nazwy z 0044) -
-- utrwalone na wierszu śladu.
--
-- PRZYROST (ADD COLUMN + indeks częściowy) - zero przebudowy, zero ruszonych wierszy, BEZ backfillu:
-- wiersz sprzed tej migracji ma `settled_at` NULL = „nierozstrzygnięty” i rozstrzyga go pierwsze cofnięcie
-- albo commit jego lokacji (na kopii żywej bazy tabela `atomic_undo` jeszcze nie istnieje - baza v43).
-- Krok pomigracyjny nie ma czego liczyć: werdykt zależy od dysku, nie od bazy.
--
-- DLACZEGO: śmierć procesu w oknie podmiany cofnięcia zostawiała pliki obok ścieżki, których nikt nie
-- sprawdzał (sonda 2026-10-18 na plikach prawdziwych, `os._exit` w oknie: T po śmierci przed podmianą,
-- K = plik zastany po śmierci przed rewalidacją, K = wersja INNEGO pisarza po śmierci przed jej powrotem,
-- Z po śmierci przed sprzątnięciem kopii zwrotnej) - a ponowienie domykało cofnięcie i o nich milczało.
-- Teraz każdy taki plik dostaje werdykt i wiersz Porządków „Kopie zostawione do oka”. Automat NICZEGO nie
-- kasuje i nie przenosi - człowiek porównuje pliki i usuwa zbędne (kasowanie dowiedzionego duplikatu to
-- osobny wariant rozwojowy, poza tą migracją):
--   * `outcome` - `kept` (obok ścieżki widziano plik: zostaje do oka) albo `clean` (obok ścieżki nic nie
--     zostało - zapisuje WYŁĄCZNIE proces, który ślad utrwalił, na końcu własnego cofnięcia);
--   * `kept_paths` - przy `kept` zawsze WSZYSTKIE trzy nazwy śladu (lista JSON), nie tylko te widziane:
--     ślad żywego cofnięcia innego procesu może za chwilę wystawić kolejną; wiersz Porządków pokazuje
--     nazwę, dopóki jej brak nie jest dowiedziony (ten sam wiersz co zamiar podmiany 0038);
--   * `settled_at` - chwila werdyktu; NULL = ślad jeszcze nie rozstrzygnięty.
-- Werdykt pisze się RAZ (CAS na `settled_at IS NULL`, przegrany czyta werdykt zwycięzcy); `synced_at` (0044)
-- mówi o bazie, `settled_at` o plikach obok ścieżki - dwa niezależne fakty.
--
-- STRAŻNIK W DDL (wzorzec 0041): werdykt zawsze z chwilą i chwila zawsze z werdyktem, lista niepusta
-- wyłącznie przy `kept` (i przy `kept` zawsze niepusta; `IS`, bo porównanie z NULL przepuściłoby CHECK).
-- Elementów listy CHECK sprawdzić nie może (iteracja JSON to podzapytanie) - niepuste teksty pilnuje klinga
-- `repo.settle_atomic_undo`, a czytelnik Porządków pomija każdy inny element.
ALTER TABLE atomic_undo ADD COLUMN outcome TEXT
    CHECK (outcome IS NULL OR outcome IN ('clean', 'kept'));
ALTER TABLE atomic_undo ADD COLUMN kept_paths TEXT NOT NULL DEFAULT '[]'
    CHECK (json_valid(kept_paths) AND json_type(kept_paths) = 'array'
           AND (outcome IS 'kept') = (json_array_length(kept_paths) > 0));
ALTER TABLE atomic_undo ADD COLUMN settled_at TEXT
    CHECK ((settled_at IS NULL) = (outcome IS NULL)
           AND (settled_at IS NULL OR length(settled_at) > 0));
CREATE INDEX idx_atomic_undo_unsettled ON atomic_undo (backup_id) WHERE settled_at IS NULL;
