# Proweniencja assetów GUI

## `ne_110m_land.json` — kontury lądów/granic mapy stanowisk (F8)

- **Źródło:** Natural Earth, warstwa `ne_110m_admin_0_countries` (skala 1:110 m).
  Pobrane z `github.com/nvkelso/natural-earth-vector` (`geojson/ne_110m_admin_0_countries.geojson`).
- **Licencja:** domena publiczna (Natural Earth) — atrybucja niewymagana, użycie/redystrybucja
  bez ograniczeń. Kompatybilne z repo MIT.
- **Przetworzenie (odchudzenie, jednorazowe):** z każdej geometrii `Polygon`/`MultiPolygon`
  wyciągnięto ringi jako polilinie (granice krajów = jednocześnie granice lądowe i linie brzegowe),
  współrzędne zaokrąglono do **3 miejsc** (~111 m — kontur to TŁO mapy, nie tożsamość stanowiska),
  odrzucono properties, zdeduplikowano kolejne identyczne punkty. Format wynikowy: goła geometria
  GeoJSON `MultiLineString` (`[lon, lat]`). Rozmiar 838 KB → 173 KB (288 polilinii, 10 593 punkty).
- **Odczyt w kodzie:** `horreum.gui.mapproj.load_land_polylines` przez `importlib.resources`
  (wzorzec `schema/migrations`, `resolve/data`). Rozszerzenie `.json` → `collect_data_files`
  (`packaging/horreum.spec`) wnosi go do frozen automatycznie; `horreum.gui.assets` w `hiddenimports`.
