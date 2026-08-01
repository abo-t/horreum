"""Zeznanie gotowego stacku (`resolve.stack`, segment I-2a paczki P-I).

Bramką tego segmentu jest TOŻSAMOŚĆ zbioru wejść, nie ich licznik — pierwotny projekt porównywał
`rows == len(okno)` i przechodził dla dwóch różnych zbiorów tej samej liczności (znalezisko recenzji
`sol`/`kimi`). Testy niżej pinują trzy pułapki zmierzone na realnych plikach: dwie tabele `<tr>`
w historii, dwa warianty nazwy WBPP i okno zdegenerowane (23 z 84 masterów archiwum).
"""
import pytest

from horreum.naming import header_dt
from horreum.resolve import stack

# Kształt 1:1 z realnego mastera (CTB1/Ha): własność `PixInsight:ProcessingHistory` niesie XML
# zaescape'owany, tabela `images` ma wejścia, tabela `imageData` własne wiersze z własnym `enabled`.
_WBPP = ("D:/ASTROFOTY/_A2_OBIEKTY/CTB1_/wbpp4/registered/"
         "CTB 1_LIGHT_GRP-MM20250823_FILTER-H_600.00s_{idx}_2.98_0.56_{temp}C_c_r.xisf")
_WBPP_KROTKI = ("D:/ASTROFOTY/_A2_OBIEKTY/CTB1_/wbpp4/registered/"
                "CTB 1_LIGHT_GRP-MM20250823_FILTER-H_600.00s_{idx}_c_r.xisf")


def _wiersz(path, *, enabled="true", drizzle=True):
    td = f'&lt;td id="enabled" value="{enabled}"/&gt;&lt;td id="path"&gt;{path}&lt;/td&gt;'
    if drizzle:
        td += f'&lt;td id="drizzlePath"&gt;{path[:-5]}.xdrz&lt;/td&gt;'
    return f"&lt;tr&gt;{td}&lt;/tr&gt;"


def _xml(wejscia, *, imagedata=2, historia=True, sygnatura=True):
    """Buduje nagłówek XISF o realnym kształcie. `imagedata` = ile wierszy ma DRUGA tabela
    (te mają `enabled="false"` — pułapka, na której potknęła się pierwsza sonda)."""
    czesci = []
    if sygnatura:
        czesci.append('<Property id="PCL:Signature:Integration" type="String">'
                      'process=ImageIntegration,version=1.7.1,'
                      'timestamp=2025-09-25T08:28:00.823Z</Property>')
    if historia:
        wiersze = "".join(_wiersz(p) for p in wejscia)
        inne = "".join('&lt;tr&gt;&lt;td id="enabled" value="false"/&gt;'
                       '&lt;td id="weightRK" value="0.65"/&gt;&lt;/tr&gt;' for _ in range(imagedata))
        czesci.append(
            '<Property id="PixInsight:ProcessingHistory" type="String">'
            "&lt;ProcessingHistory version=&quot;1.0&quot;&gt;"
            "&lt;instance class=&quot;ImageIntegration&quot;&gt;"
            f'&lt;table id="images" rows="{len(wejscia)}"&gt;{wiersze}&lt;/table&gt;'
            f'&lt;table id="imageData" rows="{imagedata}"&gt;{inne}&lt;/table&gt;'
            "&lt;/instance&gt;&lt;/ProcessingHistory&gt;</Property>")
    return "<xisf>" + "".join(czesci) + "</xisf>"


def _naglowek(**nadpisz):
    h = {"IMAGETYP": "Master Light", "OBJECT": "CTB 1", "FILTER": "H", "EXPTIME": 600.0,
         "TELESCOP": "A140R", "INSTRUME": "ZWO ASI2600MM Pro",
         "DATE-OBS": "2025-08-30T19:45:02.608", "DATE-END": "2025-08-31T02:44:03.851"}
    h.update(nadpisz)
    return h


def test_parse_history_czyta_wejscia_i_narzedzie():
    xml = _xml([_WBPP.format(idx="0012", temp="-10.00"), _WBPP.format(idx="0013", temp="-9.90")])
    rows, inputs, tool = stack.parse_history(xml)
    assert rows == 2 and len(inputs) == 2
    assert inputs[0].set_temp_c == -10.0 and inputs[1].set_temp_c == -9.9
    assert inputs[0].enabled is True and inputs[0].has_drizzle is True
    assert "ImageIntegration" in tool and "1.7.1" in tool


def test_parse_history_ignoruje_tabele_imagedata():
    """PUŁAPKA 2: `imageData` ma własne `<tr>` z `enabled="false"`. Parser bez zawężenia do tabeli
    `images` naliczył 36 nieistniejących „klatek odrzuconych" — tu 2 wejścia i ani jednego więcej."""
    xml = _xml([_WBPP.format(idx="0012", temp="-10.00"),
                _WBPP.format(idx="0013", temp="-10.00")], imagedata=5)
    rows, inputs, _ = stack.parse_history(xml)
    assert rows == 2 and len(inputs) == 2
    assert all(i.enabled for i in inputs)          # żaden odrzut nie przeciekł z drugiej tabeli


def test_parse_history_dwa_warianty_nazwy():
    """PUŁAPKA 3: nazwa bez temperatury (`_1008_c_r`) jest LEGALNA i musi wejść jako wejście
    z `set_temp_c=None`, bo inaczej licznik przestaje się domykać."""
    xml = _xml([_WBPP.format(idx="0012", temp="-10.00"), _WBPP_KROTKI.format(idx="1008")])
    t = stack.read_testimony(_naglowek(), xml)
    assert t.rows == 2 and len(t.inputs) == 2
    assert t.declared_temps == [-10.0]
    assert t.unreadable_inputs == 1


def test_read_testimony_bez_historii_zostaje_samo_okno():
    """81 z 85 masterów archiwum nie niesie historii — zeznanie ma być KOMPLETNE mimo to."""
    t = stack.read_testimony(_naglowek(), _xml([], historia=False, sygnatura=False))
    assert t.rows is None and t.inputs == ()
    assert t.object_raw == "CTB 1" and t.filter_raw == "H" and t.telescop == "A140R"
    assert t.window_span_s == pytest.approx(25141.0, abs=1)
    assert t.degenerate is False


def test_read_testimony_bez_xml_w_ogole():
    t = stack.read_testimony(_naglowek(), None)
    assert (t.rows, t.inputs, t.tool) == (None, (), None)
    assert t.window_start == header_dt("2025-08-30T19:45:02.608")


@pytest.mark.parametrize("date_end, exptime, oczekiwane", [
    ("2025-08-31T02:44:03.851", 600.0, False),      # realny stack: okno 7 h wobec 600 s ekspozycji
    ("2025-08-30T19:55:02.608", 600.0, True),       # span == exptime — nagłówek opisuje JEDNĄ klatkę
    ("2025-08-30T20:05:02.608", 600.0, True),       # span == 2× exptime — nadal nie stack
    ("2025-08-30T20:05:03.000", 600.0, False),      # sekunda ponad próg — już stack
    (None, 600.0, True),                            # brak DATE-END — nie ma czym ograniczyć doboru
    ("2025-08-31T02:44:03.851", None, True),        # brak EXPTIME — jw.
])
def test_okno_zdegenerowane(date_end, exptime, oczekiwane):
    """23 z 84 masterów starszego rocznika ma `DATE-END == DATE-OBS + EXPTIME`. Taki stack MUSI
    zostać bez relacji — okno wybrałoby jeden sub i wyglądałoby to wiarygodnie."""
    t = stack.read_testimony(_naglowek(**{"DATE-END": date_end, "EXPTIME": exptime}), None)
    assert t.degenerate is oczekiwane


def test_okno_lapie_klatke_graniczna_mimo_ulamkow_sekund():
    """REGRESJA: master zapisuje `…02.608`, klatka `…02.6075262`. Porównanie po STRINGU wycina
    pierwszy sub (zmierzone: 36 spada do 35), po `header_dt` — nie."""
    t = stack.read_testimony(_naglowek(), None)
    surowy_master, surowa_klatka = "2025-08-30T19:45:02.608", "2025-08-30T19:45:02.6075262"
    assert surowa_klatka < surowy_master                       # po STRINGU klatka wypada z okna…
    assert t.window_start <= header_dt(surowa_klatka) <= t.window_end      # …po header_dt wpada


def test_inputs_contained_zgodne():
    xml = _xml([_WBPP.format(idx="0012", temp="-10.00"), _WBPP.format(idx="0013", temp="-9.90"),
                _WBPP_KROTKI.format(idx="1008")])
    t = stack.read_testimony(_naglowek(), xml)
    ok, poza, nadwyzka = stack.inputs_contained(t, [-10.0, -9.9, -10.0])
    assert ok is True and poza == {} and nadwyzka == 1        # nadwyżka == jedna nazwa nieczytelna


def test_inputs_contained_obala_gdy_deklarowana_klatka_poza_oknem():
    """Falsyfikator właściwy: licznik się zgadza (3 == 3), a zbiory NIE — dokładnie przypadek,
    którego stara bramka „rows == len(okno)" nie widziała."""
    xml = _xml([_WBPP.format(idx="0012", temp="-10.00"), _WBPP.format(idx="0013", temp="-9.90"),
                _WBPP.format(idx="0014", temp="-9.80")])
    t = stack.read_testimony(_naglowek(), xml)
    ok, poza, _ = stack.inputs_contained(t, [-10.0, -9.9, -20.0])
    assert ok is False and poza == {-9.8: 1}


def test_inputs_contained_obala_gdy_nadwyzka_wieksza_niz_nazwy_nieczytelne():
    xml = _xml([_WBPP.format(idx="0012", temp="-10.00")])
    t = stack.read_testimony(_naglowek(), xml)
    ok, poza, nadwyzka = stack.inputs_contained(t, [-10.0, -10.0, -9.9])
    assert ok is False and poza == {} and nadwyzka == 2       # zero nazw nieczytelnych, a okno +2


def test_inputs_contained_znosi_szum_zmiennoprzecinkowy():
    """Z nazwy przychodzi `-10.00`, z nagłówka `-10.000000001` — bez zaokrąglenia wielozbiory
    rozjechałyby się na równości floatów."""
    xml = _xml([_WBPP.format(idx="0012", temp="-10.00")])
    t = stack.read_testimony(_naglowek(), xml)
    ok, _, _ = stack.inputs_contained(t, [-10.000000001])
    assert ok is True


def test_zmierzony_przypadek_ngc4826_zdaje_bramke():
    """KOTWICA POMIARU (fakt 18 briefu): realny stack 190 wejść, 189 nazw czytelnych, rozkład na
    pięciu temperaturach zgodny z archiwum, nadwyżka okna == 1 == liczba nazw nieczytelnych."""
    rozklad = {-10.0: 11, -9.9: 55, -9.8: 105, -9.7: 8, -9.6: 10}       # 189 czytelnych
    wejscia = [_WBPP.format(idx=f"{i:04d}", temp=f"{t:.2f}")
               for t, n in rozklad.items() for i in range(n)]
    wejscia.append(_WBPP_KROTKI.format(idx="0276"))                     # 190. nazwa bez temperatury
    t = stack.read_testimony(_naglowek(**{"EXPTIME": 120.0}), _xml(wejscia))
    assert t.rows == 190 and t.unreadable_inputs == 1
    okno = [temp for temp, n in rozklad.items() for _ in range(n)] + [-9.7]
    ok, poza, nadwyzka = stack.inputs_contained(t, okno)
    assert ok is True and poza == {} and nadwyzka == 1
