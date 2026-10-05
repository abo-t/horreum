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
    "tory: T1 T2\n"
)


def blok(ident, stan="otwarty", waga="-", tor="T1", extra="", proza="Proza długu.", paczka=None):
    zam = "zamkniete: 2026-01-01 test\n" if stan == "zamkniety" else ""
    pola = (f"tor: {tor}\n" if tor else "") + (f"paczka: {paczka}\n" if paczka else "")
    return (f"## {ident} · tytuł {ident}\nstan: {stan}\nwaga: {waga}\n{pola}{zam}{extra}"
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
    r.write_bytes(rejestr(blok("A-1"), blok("B-2", tor="T2")).encode("utf-8"))
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
    przyklad = "## Przykład\n\n```\n## X-9 · ilustracja\nstan: otwarty\nwaga: -\ntor: T1\n```\n"
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


@pytest.mark.parametrize("pole,zla", [("stan", "otwarta"), ("waga", "zielona"), ("tor", "T99")])
def test_zla_dziedzina_to_blad(pole, zla):
    tekst = rejestr(blok("A-1")).replace(f"{pole}: " + {"stan": "otwarty", "waga": "-",
                                                        "tor": "T1"}[pole], f"{pole}: {zla}")
    rej = rozbior(tekst)
    assert any(f"`{zla}`" in b for b in rej.bledy), rej.bledy


def test_otwarty_blok_bez_toru_to_blad():
    rej = rozbior(rejestr(blok("A-1", tor=None)))
    assert any("brak pola `tor:`" in b for b in rej.bledy), rej.bledy


@pytest.mark.parametrize("stan", ["otwarty", "zaparkowany"])
def test_paczka_w_bloku_otwartym_to_blad_bo_jest_polem_historycznym(stan):
    rej = rozbior(rejestr(blok("A-1", stan=stan, paczka="D")))
    assert any("pole historyczne" in b for b in rej.bledy), rej.bledy


def test_zamkniety_zachowuje_paczke_historyczna_bez_toru():
    assert rozbior(rejestr(blok("A-1"), blok("C-3", stan="zamkniety", tor=None,
                                             paczka="P"))).bledy == []


def test_zamkniety_z_paczka_spoza_dziedziny_historycznej_to_blad():
    rej = rozbior(rejestr(blok("A-1"), blok("C-3", stan="zamkniety", tor=None, paczka="Z")))
    assert any("paczka `Z` spoza dziedziny historycznej" in b for b in rej.bledy), rej.bledy


def test_tor_decyzja_jest_w_dziedzinie_bez_wpisu_w_tory():
    assert rozbior(rejestr(blok("A-1", tor="decyzja"))).bledy == []


def test_duplikat_id_to_blad():
    rej = rozbior(rejestr(blok("A-1"), blok("A-1", tor="T2")))
    assert any("duplikat ID" in b for b in rej.bledy)


def test_pusta_linia_pod_naglowkiem_to_blad_nie_proza():
    """Pole po pustej linii nie jest polem - nikt by go nie czytał, a ID zniknęłoby z indeksu."""
    rej = rozbior(rejestr("## A-1 · tytuł\n\nstan: otwarty\nwaga: -\ntor: T1\n"))
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


def test_tor_bez_id_nie_moze_przemycac_identyfikatora():
    stan = STAN + "tor-bez-id: T1 opis z `Q-7` w środku\n"
    assert any("niesie identyfikator" in b for b in rozbior(rejestr(blok("A-1"), stan=stan)).bledy)


def test_tor_bez_id_spoza_dziedziny_to_blad():
    stan = STAN + "tor-bez-id: T9 opis\n"
    assert any("tor-bez-id `T9` spoza" in b for b in rozbior(rejestr(blok("A-1"), stan=stan)).bledy)


def test_paczki_w_stanie_to_nieznane_pole():
    stan = STAN + "paczki: D E\n"
    assert any("nieznane pole `paczki:`" in b for b in rozbior(rejestr(blok("A-1"), stan=stan)).bledy)


FALE = "fala: 1 rdzeń | T1 | A-1\nfala: 2 ekran | T2 | -\n"


def test_poprawne_fale_przechodza_i_sa_rozebrane():
    rej = rozbior(rejestr(blok("A-1"), blok("B-2", tor="T2"), stan=STAN + FALE))
    assert rej.bledy == []
    assert [(f.nr, f.nazwa, f.tory, f.przed) for f in rej.fale] == [
        (1, "rdzeń", ["T1"], ["A-1"]), (2, "ekran", ["T2"], [])]


@pytest.mark.parametrize("fala,blad", [
    ("fala: 1 x | T9 | -", "tor `T9` spoza"),
    ("fala: 1 x | decyzja | -", "tor `decyzja` spoza"),
    ("fala: 1 x | T1 | -\nfala: 2 y | T1 | -", "stoi już w fali 1"),
    ("fala: 1 x | T1 | -\nfala: 1 y | T2 | -", "fala 1 powtórzona"),
    ("fala: 1 x | T1 | Q-9", "`Q-9` nie jest otwartym ID"),
    ("fala: 1 x | T1", "format"),
    ("fala: jeden | T1 | -", "numer fali to liczba"),
])
def test_zla_fala_to_blad_schematu(fala, blad):
    rej = rozbior(rejestr(blok("A-1"), stan=STAN + fala + "\n"))
    assert any(blad in b for b in rej.bledy), rej.bledy


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


def test_nazwa_toru_wygladajaca_na_id_nie_psuje_kontroli_kompletnosci():
    # Zarzut bramki K (kimi Z3) przy paczkach: etykieta `K7` w backtickach czytała się jak ID
    # i kontrola kompletności pękała. Tor stoi w indeksie GOŁY, więc `T1` jest legalny.
    rej = rozbior(rejestr(blok("A-1"), blok("B-2", tor="T2")))
    tekst, n = ks.indeks(rej)
    assert rej.bledy == [] and n == 2 and "`T1`" not in tekst and "T1 `A-1`" in tekst


def test_nazwa_toru_ze_znakiem_markdown_to_blad_schematu():
    stan = STAN.replace("tory: T1 T2", "tory: T1 `T2`")
    assert any("nazwa toru spoza" in b for b in rozbior(rejestr(blok("A-1"), stan=stan)).bledy)


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
    rej = rozbior(rejestr(blok("A-1", stan="zaparkowany"), blok("B-2", waga="zolta", tor="T2")))
    tekst = "\n".join(ks.generuj_start(rej))
    assert "`A-1`🅿" in tekst and "`B-2`🟡" in tekst


def test_bez_fal_kolejnosc_torow_ze_stanu_i_decyzje_na_koncu():
    rej = rozbior(rejestr(blok("D-1", tor="decyzja"), blok("E-1", tor="T2"), blok("A-1")))
    indeks = ks.indeks(rej)[0]
    assert indeks.index("**poza falami:** T1 `A-1`") < indeks.index("T2 `E-1`") \
        < indeks.index("**decyzje** `D-1`")


def test_indeks_po_falach_potem_poza_falami_potem_decyzje():
    stan = STAN.replace("tory: T1 T2", "tory: T1 T2 T3") + "fala: 1 a | T2 | -\nfala: 2 b | T1 | -\n"
    rej = rozbior(rejestr(blok("A-1"), blok("B-2", tor="T2"), blok("C-3", tor="T3"),
                          blok("D-1", tor="decyzja"), stan=stan))
    assert rej.bledy == []
    indeks = ks.indeks(rej)[0]
    assert indeks.index("**fala 1:** T2 `B-2`") < indeks.index("**fala 2:** T1 `A-1`") \
        < indeks.index("**poza falami:** T3 `C-3`") < indeks.index("**decyzje** `D-1`")
    assert indeks.startswith("**Otwarte ID wg fal i torów (4; ")


def test_tor_bez_id_pokazany_przy_torze_a_siedziba_tylko_w_tory():
    stan = STAN + "tor-bez-id: T2 odroczone UX (sekcja w kolejce) | `horreum/gui/x.py`\n"
    rej = rozbior(rejestr(blok("A-1"), stan=stan))
    indeks, n = ks.indeks(rej)
    assert "T2 odroczone UX (sekcja w kolejce)" in indeks and n == 1
    assert "x.py" not in indeks


def test_czerwona_decyzja_ma_tytul_w_starcie():
    """Niezmiennik 2 skilla: treść decyzji BLOKUJĄCEJ stoi w STARCIE, nie tylko w rejestrze."""
    rej = rozbior(rejestr(blok("A-1", waga="czerwona")))
    tekst = "\n".join(ks.generuj_start(rej))
    assert "Decyzje BLOKUJĄCE" in tekst and "- `A-1` tytuł A-1" in tekst


def test_generat_gubiacy_tor_wywraca_asercje_kompletnosci(monkeypatch):
    """Falsyfikator drugiej kontroli: filtr, który zgubi tor, zgodziłby się ze sobą przy
    równości bajtowej - asercja czyta ID z WYPISANEGO tekstu i nie przepuszcza."""
    rej = rozbior(rejestr(blok("A-1"), blok("B-2", tor="T2")))
    monkeypatch.setattr(ks.Rejestr, "tory", lambda self: ("T2", "decyzja"))
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
    rej = rozbior(rejestr(blok("A-1"), blok("B-2", tor="T2")))
    pierwszy, drugi = ks.generuj_start(rej), ks.generuj_start(rozbior(rejestr(blok("A-1"),
                                                                                blok("B-2", tor="T2"))))
    assert pierwszy == drugi and pierwszy[0] == ks.MARKER
    assert all(len(l) <= ks.SZEROKOSC for l in pierwszy)


# --- tory: szwy plików w fali ------------------------------------------------------------------

STAN_FAL = (STAN.replace("tory: T1 T2", "tory: T1 T2 T3")
            + "fala: 1 a | T1 T2 | -\nfala: 2 b | T3 | -\n")


def siedziba(*sciezki):
    return "siedziba: " + ", ".join(f"`{s}`" for s in sciezki) + "\n"


def tory(repo, capsys, *bloki, stan=STAN_FAL, argv=()):
    repo[0].write_bytes(rejestr(*bloki, stan=stan).encode("utf-8"))
    kod = uruchom(repo, "tory", *argv)
    return kod, capsys.readouterr().out


def test_tory_kolizja_dwoch_torow_jednej_fali_to_fail_z_fala_para_i_plikiem(repo, capsys):
    kod, out = tory(repo, capsys, blok("A-1", extra=siedziba("horreum/repo.py")),
                    blok("B-2", tor="T2", extra=siedziba("horreum/repo.py")),
                    blok("C-3", tor="T3", extra=siedziba("horreum/c.py")))
    assert kod == 1
    assert "FAIL fala 1: T1 × T2 · horreum/repo.py (T1: A-1; T2: B-2)" in out


def test_tory_plik_z_listy_dozwolonych_przechodzi(repo, capsys):
    kod, out = tory(repo, capsys, blok("A-1", extra=siedziba("horreum/gui/grid.py",
                                                             "horreum/gui/i18n_catalog.py")),
                    blok("B-2", tor="T2", extra=siedziba("horreum/gui/grid.py",
                                                         "horreum/gui/i18n_catalog.py")),
                    blok("C-3", tor="T3", extra=siedziba("horreum/c.py")))
    assert (kod, out) == (0, "")


def test_tory_wspolny_plik_torow_z_roznych_fal_przechodzi(repo, capsys):
    kod, out = tory(repo, capsys, blok("A-1", extra=siedziba("horreum/repo.py")),
                    blok("B-2", tor="T2", extra=siedziba("horreum/b.py")),
                    blok("C-3", tor="T3", extra=siedziba("horreum/repo.py")))
    assert (kod, out) == (0, "")


@pytest.mark.parametrize("pole,powod", [("", "brak `siedziba:`"),
                                        ("siedziba: kolejka, sekcja X; `symbol_bez_pliku`\n",
                                         "siedziba bez ścieżki pliku")])
def test_tory_szew_nieznany_to_fail(repo, capsys, pole, powod):
    kod, out = tory(repo, capsys, blok("A-1", extra=pole),
                    blok("B-2", tor="T2", extra=siedziba("horreum/b.py")),
                    blok("C-3", tor="T3", extra=siedziba("horreum/c.py")))
    assert kod == 1 and f"SZEW NIEZNANY T1: A-1 ({powod})" in out


def test_tory_tor_bez_id_bez_siedziby_to_szew_nieznany_a_z_siedziba_wchodzi_do_skladu(repo, capsys):
    stan = STAN_FAL + "tor-bez-id: T3 5 pozycji UX\n"
    kod, out = tory(repo, capsys, blok("A-1", extra=siedziba("horreum/a.py")),
                    blok("B-2", tor="T2", extra=siedziba("horreum/b.py")), stan=stan)
    assert kod == 1 and "SZEW NIEZNANY T3: 5 pozycji UX (brak `siedziba:`)" in out
    stan = STAN_FAL + "tor-bez-id: T2 5 pozycji UX | `horreum/a.py` `f`\n"
    kod, out = tory(repo, capsys, blok("A-1", extra=siedziba("horreum/a.py")),
                    blok("C-3", tor="T3", extra=siedziba("horreum/c.py")), stan=stan)
    assert kod == 1 and "FAIL fala 1: T1 × T2 · horreum/a.py (T1: A-1; T2: 5 pozycji UX)" in out


def test_tory_normalizacja_sciezki_z_sufiksem_funkcji_i_linii_oraz_golej_nazwy(repo, capsys):
    """Sufiks w tym samym backticku (`:45`, ` _f`, `::f`, nawias) odpada, kropka bez rozszerzenia
    pliku to symbol, a goła nazwa jedynego pliku w repo dostaje pełną ścieżkę."""
    (repo[2] / "gui").mkdir()
    (repo[2] / "gui" / "jedyny.py").write_text("x = 1\n", encoding="utf-8")
    assert ks.pliki_siedziby("`horreum/a.py:45` `horreum/b.py _f` `horreum\\c.py::g` "
                             "`horreum/d.py (ok. 12)` `tasks.copies_unread_tip` `jedyny.py` "
                             "`brief/PLAN.md:45` `f` `horreum/a.pyc`", repo[2].parent) == (
        {"horreum/a.py", "horreum/b.py", "horreum/c.py", "horreum/d.py", "horreum/gui/jedyny.py",
         "brief/PLAN.md"}, [])
    kod, out = tory(repo, capsys, blok("A-1", extra="siedziba: `horreum/gui/jedyny.py` `f`\n"),
                    blok("B-2", tor="T2", extra="siedziba: `jedyny.py:12`\n"),
                    blok("C-3", tor="T3", extra=siedziba("horreum/c.py")))
    assert kod == 1 and "FAIL fala 1: T1 × T2 · horreum/gui/jedyny.py" in out


def test_tory_gola_nazwa_niejednoznaczna_to_szew_nieznany(repo, capsys):
    for kat in ("a", "b"):
        (repo[2] / kat).mkdir()
        (repo[2] / kat / "dwa.py").write_text("x = 1\n", encoding="utf-8")
    kod, out = tory(repo, capsys, blok("A-1", extra="siedziba: `dwa.py`\n"),
                    blok("B-2", tor="T2", extra=siedziba("horreum/b.py")),
                    blok("C-3", tor="T3", extra=siedziba("horreum/c.py")))
    assert kod == 1 and "goła nazwa dwa.py (2 trafień)" in out


def test_tory_fala_ogranicza_zakres_a_fala_spoza_stanu_to_kod_2(repo, capsys):
    bloki = (blok("A-1", extra=siedziba("horreum/repo.py")),
             blok("B-2", tor="T2", extra=siedziba("horreum/repo.py")),
             blok("C-3", tor="T3"))                               # szew nieznany w fali 2
    assert tory(repo, capsys, *bloki, argv=("--fala", "2"))[0] == 1
    kod, out = tory(repo, capsys, *bloki, argv=("--fala", "2"))
    assert "FAIL fala 1" not in out and "SZEW NIEZNANY T3: C-3" in out
    assert tory(repo, capsys, *bloki, argv=("--fala", "7"))[0] == 2


def test_tory_pokaz_wypisuje_sklad_torow(repo, capsys):
    kod, out = tory(repo, capsys, blok("A-1", extra=siedziba("horreum/a.py")),
                    blok("B-2", tor="T2", extra=siedziba("horreum/b.py")),
                    blok("C-3", tor="T3", extra=siedziba("horreum/c.py")), argv=("--pokaz",))
    assert kod == 0
    assert out.split("\n")[:3] == ["fala 1 a (przed: -)", "  T1: horreum/a.py", "  T2: horreum/b.py"]


def test_tory_rejestr_z_bledem_schematu_to_kod_1(repo, capsys):
    kod, out = tory(repo, capsys, blok("A-1", tor="T9"))
    assert kod == 1 and "rejestr oblewa schemat" in out


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
