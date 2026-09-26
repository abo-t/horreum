"""Generator bloku `⏭ START TUTAJ` z rejestru długów (`scripts/kolejka_start.py`, paczka `K`).

Skrypt jest dev-owy, a jego pliki (kolejka, rejestr) żyją poza gitem - bateria mierzy go WYŁĄCZNIE
na fiksturach w `tmp_path`, nigdy na plikach prywatnych. Kontrola ma dwie osie i obie są tu
przypięte: ZGODNOŚĆ bloku z rejestrem (bajt w bajt) oraz KOMPLETNOŚĆ (zbiór ID w bloku = zbiór
otwartych w rejestrze, każde `TODO-DŁUG` w kodzie ma blok) - równość bajtowa drugiej nie dowodzi.
"""
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SKRYPT = Path(__file__).resolve().parent.parent / "scripts" / "kolejka_start.py"


def _modul():
    spec = importlib.util.spec_from_file_location("kolejka_start_pod_test", SKRYPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod          # dataclass z adnotacjami odroczonymi szuka modułu tutaj
    spec.loader.exec_module(mod)
    return mod


ks = _modul()

STAN = (
    "## STAN\n"
    "sesja: t1\n"
    "stan: stan testowy\n"
    "nastepny-krok: zrób X\n"
    "model-nastepnej: model / effort\n"
    "nie-wracac: `Z-1`\n"
    "paczki: D E\n"
)


def blok(ident, stan="otwarty", waga="-", paczka="D", extra="", proza="Proza długu."):
    zam = "zamkniete: 2026-01-01 test\n" if stan == "zamkniety" else ""
    return (f"## {ident} · tytuł {ident}\nstan: {stan}\nwaga: {waga}\npaczka: {paczka}\n{zam}{extra}"
            f"\n{proza}\n")


def rejestr(*bloki, stan=STAN):
    return "# Rejestr\n\n" + stan + "\n" + "\n".join(bloki)


KOLEJKA = "# Kolejka\n\n> polityka\n\n## ⏭ START TUTAJ\n\nstary blok\n\n## Inna sekcja\nogon\n"


@pytest.fixture
def repo(tmp_path):
    """Trzy ścieżki jak w repo: rejestr, kolejka, katalog kodu (pusty moduł, zero TODO-DŁUG)."""
    kod = tmp_path / "horreum"
    kod.mkdir()
    (kod / "modul.py").write_text("x = 1\n", encoding="utf-8")
    r = tmp_path / "rejestr_dlugow.md"
    k = tmp_path / "kolejka_sesji.md"
    r.write_bytes(rejestr(blok("A-1"), blok("B-2", paczka="E")).encode("utf-8"))
    k.write_bytes(KOLEJKA.encode("utf-8"))
    return r, k, kod


def uruchom(repo, *argv):
    r, k, kod = repo
    return ks.main(["--rejestr", str(r), "--kolejka", str(k), "--kod", str(kod), *argv])


def rozbior(tekst):
    return ks.rozbierz(tekst)


# --- schemat ---------------------------------------------------------------------------------

def test_poprawny_rejestr_przechodzi_schemat(repo):
    assert uruchom(repo, "sprawdz") == 0


def test_id_w_plotku_kodu_nie_liczy_sie():
    """Przykład bloku w dokumentacji rejestru jest ilustracją, nie drugim ID."""
    przyklad = "## Przykład\n\n```\n## X-9 · ilustracja\nstan: otwarty\nwaga: -\npaczka: D\n```\n"
    rej = rozbior(rejestr(blok("A-1"), przyklad))
    assert not rej.bledy
    assert [b.ident for b in rej.bloki] == ["A-1"]
    assert "X-9" not in "\n".join(ks.generuj_start(rej))


def test_niezamkniety_plotek_to_blad_a_nie_cicha_proza():
    """Płotek bez zamknięcia zrobiłby prozą resztę rejestru przy kodzie 0 (lekcja MYWALLY)."""
    rej = rozbior(rejestr(blok("A-1", proza="```\notwarty płotek"), blok("B-2")))
    assert any("płotek kodu bez zamknięcia" in b for b in rej.bledy)


def test_nieznane_pole_to_blad():
    rej = rozbior(rejestr(blok("A-1", extra="priorytet: wysoki\n")))
    assert any("nieznane pole `priorytet:`" in b for b in rej.bledy)


@pytest.mark.parametrize("pole,zla", [("stan", "otwarta"), ("waga", "zielona"), ("paczka", "Z")])
def test_zla_dziedzina_to_blad(pole, zla):
    tekst = rejestr(blok("A-1")).replace(f"{pole}: " + {"stan": "otwarty", "waga": "-",
                                                        "paczka": "D"}[pole], f"{pole}: {zla}")
    rej = rozbior(tekst)
    assert any(f"`{zla}`" in b for b in rej.bledy), rej.bledy


def test_duplikat_id_to_blad():
    rej = rozbior(rejestr(blok("A-1"), blok("A-1", paczka="E")))
    assert any("duplikat ID" in b for b in rej.bledy)


def test_pusta_linia_pod_naglowkiem_to_blad_nie_proza():
    """Pole po pustej linii nie jest polem - nikt by go nie czytał, a ID zniknęłoby z indeksu."""
    rej = rozbior(rejestr("## A-1 · tytuł\n\nstan: otwarty\nwaga: -\npaczka: D\n"))
    assert any("blok ID bez pól" in b for b in rej.bledy)
    assert any("po pustej linii nie jest polem" in b for b in rej.bledy)


def test_naglowek_wygladajacy_na_id_bez_separatora_to_blad():
    rej = rozbior(rejestr(blok("A-1"), "## B-2 - tytuł bez kropki środkowej\n\nproza\n"))
    assert any("nie ma separatora" in b for b in rej.bledy)


def test_zamkniety_wymaga_pola_zamkniete():
    tekst = rejestr(blok("A-1", stan="zamkniety")).replace("zamkniete: 2026-01-01 test\n", "")
    assert any("chodzą w parze" in b for b in rozbior(tekst).bledy)


def test_krok_zbyt_szeroki_w_polu_stanu_to_fail():
    rej = rozbior(rejestr(blok("A-1"), stan=STAN.replace("zrób X", "x" * 901)))
    assert any("FAIL: krok zbyt szeroki" in b and "nastepny-krok" in b for b in rej.bledy)


def test_paczka_bez_id_nie_moze_przemycac_identyfikatora():
    stan = STAN + "paczka-bez-id: D opis z `Q-7` w środku\n"
    assert any("niesie identyfikator" in b for b in rozbior(rejestr(blok("A-1"), stan=stan)).bledy)


def test_brak_bloku_stanu_to_blad():
    assert any("brak bloku `## STAN`" in b for b in rozbior(blok("A-1")).bledy)


@pytest.mark.parametrize("wciecie", [" ", "  ", "   "])
def test_wciety_naglowek_to_blad_a_nie_cichy_zanik_id(wciecie):
    # Zarzut bramki K (kimi Z1): wcięty `## B-2` bez pól wpadał do prozy A-1 - `sprawdz` 0,
    # B-2 znikał z generatu. Markdown renderuje go jak nagłówek, więc oko niczego nie widzi.
    tekst = rejestr(blok("A-1")) + f"\n{wciecie}## B-2 · tytuł B-2\nProza B-2.\n"
    assert any("wcięty" in b for b in rozbior(tekst).bledy)


@pytest.mark.parametrize("wciecie", ["    ", "\t"])
def test_blok_kodu_wciety_czterema_spacjami_albo_tabem_jest_legalna_proza(wciecie):
    # Runda 2 bramki K (sol Z1): pierwsza naprawa odrzucała legalny blok kodu markdown.
    proza = f"Przykład:\n\n{wciecie}## X-1 · ilustracja, nie wpis"
    assert rozbior(rejestr(blok("A-1", proza=proza))).bledy == []


def test_wciety_naglowek_w_plotku_kodu_nie_jest_bledem_a_poza_nim_jest():
    w_plotku = "Przykład:\n\n```\n  ## X-1 · ilustracja\n```"
    poza = "Przykład:\n\n  ## X-1 · ilustracja"
    assert rozbior(rejestr(blok("A-1", proza=w_plotku))).bledy == []
    assert any("wcięty" in b for b in rozbior(rejestr(blok("A-1", proza=poza))).bledy)


def test_nazwa_paczki_wygladajaca_na_id_to_blad_schematu():
    # Zarzut bramki K (kimi Z3): `K7` w backtickach indeksu czyta się jak ID i kontrola
    # kompletności generatu pękała RuntimeError na zdrowym rejestrze.
    stan = STAN.replace("paczki: D E", "paczki: D K7")
    rej = rozbior(rejestr(blok("A-1"), blok("B-2", paczka="K7"), stan=stan))
    assert any("wygląda na ID" in b for b in rej.bledy)


def test_bom_na_poczatku_rejestru_to_blad():
    assert any("BOM" in b for b in rozbior("\ufeff" + rejestr(blok("A-1"))).bledy)


def test_zrodla_nie_niosa_niewidzialnego_bom():
    # Runda 2 bramki K (sol Z2): literał U+FEFF w źródle znika przy normalizacji edytora.
    for plik in (SKRYPT, Path(__file__)):
        assert "\ufeff" not in plik.read_text(encoding="utf-8"), plik.name


# --- kompletność względem kodu -----------------------------------------------------------------

def test_todo_dlug_bez_bloku_to_blad(repo, capsys):
    (repo[2] / "modul.py").write_text("# TODO-DŁUG(Q-5): coś\n", encoding="utf-8")
    assert uruchom(repo, "sprawdz") == 1
    assert "TODO-DŁUG(Q-5) nie ma bloku" in capsys.readouterr().out


def test_todo_dlug_przy_bloku_zamknietym_to_blad(repo, capsys):
    r = repo[0]
    r.write_bytes(rejestr(blok("A-1"), blok("Q-5", stan="zamkniety")).encode("utf-8"))
    (repo[2] / "modul.py").write_text("# TODO-DŁUG(Q-5): coś\n", encoding="utf-8")
    assert uruchom(repo, "sprawdz") == 1
    assert "żyje w kodzie, a blok jest zamknięty" in capsys.readouterr().out


def test_todo_dlug_z_blokiem_otwartym_przechodzi(repo):
    (repo[2] / "modul.py").write_text("# TODO-DŁUG(A-1): coś\n", encoding="utf-8")
    assert uruchom(repo, "sprawdz") == 0


# --- generat ---------------------------------------------------------------------------------

def test_zamkniety_nie_wchodzi_do_generatu():
    rej = rozbior(rejestr(blok("A-1"), blok("C-3", stan="zamkniety")))
    tekst = "\n".join(ks.generuj_start(rej))
    assert "`A-1`" in tekst and "C-3" not in tekst
    assert "(1; " in tekst                                  # licznik liczy tylko otwarte


def test_zaparkowany_wchodzi_ze_znacznikiem_i_zolta_waga_z_kolkiem():
    rej = rozbior(rejestr(blok("A-1", stan="zaparkowany"), blok("B-2", waga="zolta", paczka="E")))
    tekst = "\n".join(ks.generuj_start(rej))
    assert "`A-1`🅿" in tekst and "`B-2`🟡" in tekst


def test_kolejnosc_paczek_ze_stanu_i_etykiety_stalych():
    rej = rozbior(rejestr(blok("P-1", paczka="poza"), blok("E-1", paczka="E"),
                          blok("D-1", paczka="decyzja"), blok("A-1")))
    indeks = ks.indeks(rej)[0]
    assert indeks.index("`D` `A-1`") < indeks.index("`E` `E-1`") \
        < indeks.index("**poza paczkami** `P-1`") < indeks.index("**decyzje** `D-1`")


def test_paczka_bez_id_pokazana_jako_paczka_a_nie_falszywe_id():
    stan = STAN + "paczka-bez-id: E odroczone UX (sekcja w kolejce)\n"
    rej = rozbior(rejestr(blok("A-1"), stan=stan))
    indeks, n = ks.indeks(rej)
    assert "`E` odroczone UX (sekcja w kolejce)" in indeks and n == 1


def test_czerwona_decyzja_ma_tytul_w_starcie():
    """Niezmiennik 2 skilla: treść decyzji BLOKUJĄCEJ stoi w STARCIE, nie tylko w rejestrze."""
    rej = rozbior(rejestr(blok("A-1", waga="czerwona")))
    tekst = "\n".join(ks.generuj_start(rej))
    assert "Decyzje BLOKUJĄCE" in tekst and "- `A-1` tytuł A-1" in tekst


def test_generat_gubiacy_paczke_wywraca_asercje_kompletnosci(monkeypatch):
    """Falsyfikator drugiej kontroli: filtr, który zgubi paczkę, zgodziłby się ze sobą przy
    równości bajtowej - asercja czyta ID z WYPISANEGO tekstu i nie przepuszcza."""
    rej = rozbior(rejestr(blok("A-1"), blok("B-2", paczka="E")))
    monkeypatch.setattr(ks.Rejestr, "paczki", lambda self: ("E", "poza", "decyzja"))
    with pytest.raises(RuntimeError, match="zgubił"):
        ks.indeks(rej)


def test_zawijanie_do_120_i_bez_dywizu_na_poczatku_linii():
    """Dywiz na początku linii kontynuacji zrobiłby z akapitu punkt listy (DASH §5.2)."""
    for przesuniecie in range(1, 115):          # dywiz trafia w KAŻDĄ kolumnę, także w granicę
        tekst = "słowo " + "x" * przesuniecie + " - dalej " + " ".join(["słowo"] * 30)
        linie = ks.zawin(tekst)
        assert all(len(l) <= 120 for l in linie)
        assert not any(l.startswith("- ") or l == "-" for l in linie[1:]), (przesuniecie, linie)


def test_generat_jest_deterministyczny_i_ma_pojedyncze_linie_do_120():
    rej = rozbior(rejestr(blok("A-1"), blok("B-2", paczka="E")))
    pierwszy, drugi = ks.generuj_start(rej), ks.generuj_start(rozbior(rejestr(blok("A-1"),
                                                                                blok("B-2", paczka="E"))))
    assert pierwszy == drugi and pierwszy[0] == ks.MARKER
    assert all(len(l) <= ks.SZEROKOSC for l in pierwszy)


# --- kolejka: --sprawdz / --zapisz -------------------------------------------------------------

def test_sprawdz_rozjazd_podaje_numer_pierwszej_roznej_linii(repo, capsys):
    assert uruchom(repo, "start", "--sprawdz") == 1
    out = capsys.readouterr().out
    assert "od linii 7 kolejki" in out                       # „stary blok" stoi w linii 7
    assert "kolejka: stary blok" in out


def test_zapisz_potem_sprawdz_zgodny_i_zapisz_idempotentne(repo):
    k = repo[1]
    assert uruchom(repo, "start", "--zapisz") == 0
    po_pierwszym = k.read_bytes()
    assert uruchom(repo, "start", "--sprawdz") == 0
    assert uruchom(repo, "start", "--zapisz") == 0
    assert k.read_bytes() == po_pierwszym
    tekst = po_pierwszym.decode("utf-8")
    assert tekst.startswith("# Kolejka\n\n> polityka\n\n## ⏭ START TUTAJ\n")
    assert tekst.endswith("\n\n## Inna sekcja\nogon\n")     # układ wokół bloku nietknięty


def test_reczna_zmiana_bloku_po_zapisie_zapala_rozjazd(repo, capsys):
    k = repo[1]
    uruchom(repo, "start", "--zapisz")
    k.write_bytes(k.read_bytes().replace("stan testowy".encode(), "stan poprawiony ręcznie".encode()))
    assert uruchom(repo, "start", "--sprawdz") == 1
    assert "poprawiony ręcznie" in capsys.readouterr().out


def test_crlf_w_kolejce_nie_daje_falszywego_rozjazdu_i_zostaje_crlf(repo):
    k = repo[1]
    uruchom(repo, "start", "--zapisz")
    k.write_bytes(k.read_bytes().replace(b"\n", b"\r\n"))
    assert uruchom(repo, "start", "--sprawdz") == 0
    k.write_bytes(k.read_bytes().replace("stan testowy".encode(), b"inny"))
    assert uruchom(repo, "start", "--zapisz") == 0
    bajty = k.read_bytes()
    assert b"stan testowy" in bajty and bajty.count(b"\r\n") == bajty.count(b"\n")


def test_mieszane_konce_wiersza_to_kod_2_i_plik_nietkniety(repo):
    k = repo[1]
    k.write_bytes(KOLEJKA.replace("\n", "\r\n", 2).encode("utf-8"))
    przed = k.read_bytes()
    assert uruchom(repo, "start", "--zapisz") == 2
    assert k.read_bytes() == przed


def test_brak_markera_to_kod_2(repo):
    repo[1].write_bytes(b"# Kolejka\n\nbez startu\n")
    assert uruchom(repo, "start", "--sprawdz") == 2


def test_budzet_przekroczony_kod_1_i_plik_nietkniety(repo, capsys):
    r, k, _ = repo
    stan = STAN + "".join(f"tripwir: pułapka {i}\n" for i in range(ks.LIMIT_LINII_STARTU))
    r.write_bytes(rejestr(blok("A-1"), stan=stan).encode("utf-8"))
    przed = k.read_bytes()
    assert uruchom(repo, "start", "--zapisz") == 1
    assert "FAIL: krok zbyt szeroki" in capsys.readouterr().out
    assert k.read_bytes() == przed


def test_rejestr_z_bledem_schematu_nie_generuje_startu(repo, capsys):
    r, k, _ = repo
    r.write_bytes(rejestr(blok("A-1", extra="priorytet: wysoki\n")).encode("utf-8"))
    przed = k.read_bytes()
    assert uruchom(repo, "start", "--zapisz") == 1
    assert uruchom(repo, "start") == 1
    assert "rejestr oblewa schemat" in capsys.readouterr().out
    assert k.read_bytes() == przed


def test_start_na_stdout_to_generat_z_jednym_koncowym_lf(repo, capsys):
    assert uruchom(repo, "start") == 0
    out = capsys.readouterr().out
    assert out.startswith(ks.MARKER + "\n") and out.endswith(".\n") and not out.endswith("\n\n")


# --- granice bloku START: kontrakt właściciela `domknij.py:znajdz_start` -----------------------
# Przypadki i wyniki ZAMROŻONE z `domknij.py start-blok --kontrakt` (skill `kolejka-sesji`,
# 2026-09-26). Skrypt repo odtwarza regułę, bo musi być hermetyczny; ta tabela mierzy tę kopię.

KONTRAKT = [
    ("naglowek-konczy-naglowek", "## ⏭ START TUTAJ\ntresc\n\n## Inna sekcja\nogon", (0, 3)),
    ("naglowek-do-konca-pliku", "wstep\n## ⏭ START TUTAJ\ntresc\n", (1, 4)),
    ("blockquote-konczy-proza", "> ⏭ **START TUTAJ**\n> tresc\n>\n\nakapit poza blokiem", (0, 4)),
    ("blockquote-konczy-naglowek", "> ⏭ **START TUTAJ**\n> tresc\n## Inna sekcja", (0, 2)),
    ("blockquote-puste-linie-w-bloku", "> ⏭ **START**\n\n> dalej ten sam blok\n\ntekst", (0, 4)),
    ("cytat-w-prozie-nie-jest-markerem", "Czytaj `⏭ START TUTAJ` przed praca.\ntresc", None),
    ("marker-wciety-naglowkiem", "  ## ⏭ START TUTAJ\ntresc\n## Inna sekcja", (0, 2)),
    ("polityka-przed-blokiem",
     "> **Polityka:** czytaj `⏭ START TUTAJ`.\n\n> ⏭ **START**\n> tresc\n\n---", (2, 5)),
    ("dwa-markery-liczy-sie-pierwszy",
     "> ⏭ **START A**\n> tresc\n\n## Inna\n> ⏭ **START B**\n> drugi", (0, 3)),
    ("naglowek-nie-konczy-sie-na-h3",
     "## ⏭ START TUTAJ\n### Podsekcja w bloku\ntresc\n## Inna sekcja", (0, 3)),
    ("blockquote-do-konca-pliku", "> ⏭ **START**\n> tresc\n> ogon", (0, 3)),
    ("blok-pusty-marker-i-nic", "> ⏭ **START**\n\ntekst poza blokiem", (0, 2)),
    ("marker-w-srodku-linii-nie-liczy", "tekst i dopiero ## ⏭ START\ntresc", None),
    ("marker-produkcyjny-generowany",
     "> ⏭ **START TUTAJ - BLOK GENEROWANY** (`python narzedzia\\rejestr.py start`; F113/R4).\n"
     "> ⛔ **Nie edytuj go ręcznie**\n>\n> **Otwarte ID (3):** `D-1-1`\n\n**Ostatnia aktualizacja:** dzis",
     (0, 5)),
]


@pytest.mark.parametrize("nazwa,wejscie,oczekiwane", KONTRAKT, ids=[k[0] for k in KONTRAKT])
def test_granice_startu_wg_kontraktu_wlasciciela(nazwa, wejscie, oczekiwane):
    if oczekiwane is None:
        with pytest.raises(ks.BladPomiaru):
            ks.znajdz_start(wejscie.split("\n"))
    else:
        assert ks.znajdz_start(wejscie.split("\n")) == oczekiwane


def test_kontrakt_zamrozony_zgodny_z_wlascicielem_gdy_dostepny():
    """Drugi kierunek rozjazdu: reguła ruszona u właściciela bez odświeżenia tabeli wyżej.
    Właściciel żyje w skillu poza repo - bez niego test jest pomijany, nie zielony."""
    domknij = Path.home() / ".claude" / "skills" / "kolejka-sesji" / "assets" / "domknij.py"
    if not domknij.is_file():
        pytest.skip("brak skilla kolejka-sesji na tej maszynie")
    wynik = subprocess.run([sys.executable, str(domknij), "start-blok", "--kontrakt"],
                           capture_output=True, timeout=60)
    if wynik.returncode != 0:
        pytest.skip("domknij.py start-blok --kontrakt nie odpowiada")
    wiersze = [l for l in wynik.stdout.decode("utf-8").split("\n") if l and not l.startswith("#")]
    wlasciciel = {}
    for w in wiersze:
        nazwa, _, reszta = w.partition("\t")
        wlasciciel[nazwa] = reszta.rpartition("\t")[2]
    nasz = {n: ("BLAD" if o is None else f"{o[0]}-{o[1]}") for n, _, o in KONTRAKT}
    assert wlasciciel == nasz
