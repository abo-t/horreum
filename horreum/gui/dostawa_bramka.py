"""Bramka i napis gestu Dostawy BEZ budowy jej strony (AR-335, AR-337, AR-356) - logika Qt-WOLNA. Trzy powierzchnie
spoza widoku Dostawy pytają o fakty, które dotąd mieszkały w `pipeline.py`, więc pierwsze pytanie budowało całą stronę
Dostawy (gospodarz, „Wciągnij z WBPP…” z Domu) albo importowało moduł Dostawy na wątku GUI (podpowiedź wiersza bajtów
na liście Porządków, `tasks.py`; podpowiedź kubełka kopii nieczytelnych na podstronie obiektów Porządków,
`app.ObjectAxisView._load_review`). Ten plik nie importuje PySide6 ani `horreum.gui.pipeline` (Qt-wolność przypina
`tests/test_dostawa_bramka.py`, przechodnio).

* `powod_odmowy_biegu` - JEDYNA reguła bramki złotej akcji: powód, dla którego sekwencja „all” nie może ruszyć TERAZ,
  z trzech faktów podanych przez wołającego. Zbudowany widok podaje własny stan (`PipelineView.powod_odmowy_biegu`),
  gospodarz bez zbudowanej Dostawy - swoje zatrzaski (`MainWindow._on_open_harvest`).
* `etykieta_gestu_kopii` - napis gestu faktów kopii: przycisk Dostawy i podpowiedź wiersza bajtów w Porządkach nazywają
  go tak samo (AR-327).
* `unreadable_kinds_text` - zdanie rozbicia kopii nieczytelnych po rodzaju: raport Dostawy i podpowiedź kubełka na
  podstronie obiektów Porządków (AR-356 - podstrona importowała dla tego zdania moduł Dostawy, omijając bramkę
  „Porządki bez modułu Dostawy”)."""
from __future__ import annotations

from horreum.gui import i18n


def powod_odmowy_biegu(*, baza, bieg, zapis):
    """Powód odmowy sekwencji „all” (klucz katalogu w bieżącym języku) albo `None`, gdy wolno. Kolejność = ważność:
    brak bazy (`baza` fałszywe), bieg Dostawy w toku (`bieg`), zapis nagłówków do plików w toku (`zapis`)."""
    if not baza:
        return i18n.t("pipeline.refuse.no_db")
    if bieg:
        return i18n.t("pipeline.refuse.delivery_running")
    if zapis:
        return i18n.t("pipeline.refuse.writeback")
    return None


def etykieta_gestu_kopii(czeka):
    """Napis gestu faktów kopii z `scan.CopyFactsWaiting` (AR-315) - JEDNO miejsce wyboru: przycisk Dostawy
    (`PipelineView._sync_copy_facts`) i podpowiedź wiersza bajtów w Porządkach (AR-327) nazywają go tak samo."""
    if czeka.facts and czeka.bytes:
        return i18n.t("pipeline.btn.copy_both", fakty=czeka.facts, bajty=czeka.bytes)
    if czeka.bytes:
        return i18n.t("pipeline.btn.copy_bytes", n=czeka.bytes)
    return i18n.t("pipeline.btn.copy_facts", n=czeka.facts)


def unreadable_kinds_text(counts):
    """Zdanie rozbicia kopii nieczytelnych po RODZAJU (P4-2, P4-5) z
    `resolver.unreadable_kind_counts`. Które rodzaje pokazać, rozstrzyga rdzeń
    (`resolver.unreadable_kinds_shown`: oba rodzaje o PLIKU zawsze, „baza" i „bez kodu awarii"
    tylko > 0 - ta sama reguła co raport CLI); tu tylko etykiety i18n.
    Jedyny właściciel zdania: raport Dostawy (`pipeline._review_line`) i podpowiedź kubełka w Porządkach
    (`app.ObjectAxisView._load_review`)."""
    from horreum.resolver import unreadable_kinds_shown
    # Klucze LITERAŁAMI, nie składane z rodzaju - bramka „klucze call-site ⊆ katalog" je widzi.
    etykieta = {"io": lambda n: i18n.t("object.unreadable_kind_io", n=n),
                "parse": lambda n: i18n.t("object.unreadable_kind_parse", n=n),
                "db": lambda n: i18n.t("object.unreadable_kind_db", n=n),
                "unknown": lambda n: i18n.t("object.unreadable_kind_unknown", n=n)}
    parts = [etykieta[k](n) for k, n in unreadable_kinds_shown(counts)]
    return i18n.t("object.unreadable_kinds", parts=" · ".join(parts))
