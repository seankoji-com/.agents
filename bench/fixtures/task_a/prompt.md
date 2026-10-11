Build a static webpage that recommends where to buy E10 fuel near Greenwich, NSW, based on
the cheapest listed price.

## Inputs (in this repository)

- `data/stations.json`: the search centre and every station's ID, name, brand, address,
  latitude and longitude.
- `data/prices.json`: price records in cents per litre. Each record has `station_id`,
  `fuel`, `price_cpl` and `recorded_at` (ISO 8601 with offset). Records are not in time
  order, and some are for fuels other than E10.
- `vendor/leaflet/`: Leaflet 1.9.4 (`leaflet.js`, `leaflet.css`, `images/`, `LICENSE`).

## Rules

- A station is in range when its haversine distance from the centre in
  `data/stations.json`, using an Earth radius of 6371.0 km, is at most 10.0 km. The limit
  is inclusive.
- Only E10 records count. A station's listed price is its most recent E10 record by
  `recorded_at`.
- Recommend the in-range station with the lowest listed price.
- The overall price history has one point per calendar day that appears in any E10
  `recorded_at` (the date as written in the timestamp). Each point is the mean, over
  in-range stations, of each station's most recent E10 price recorded on or before that
  day. A station with no record yet is left out of that day's mean.

## Output contract

Write everything to `out/`. Do not change `data/` or `vendor/`.

- `out/index.html` is the page. It must work when opened directly from disk.
- Leaflet is vendored: copy `vendor/leaflet/` to `out/vendor/leaflet/` unchanged and load
  `vendor/leaflet/leaflet.css` and `vendor/leaflet/leaflet.js` from the page by relative
  path. No CDN or other remote script or stylesheet.
- The map uses OpenStreetMap tiles from `https://tile.openstreetmap.org/{z}/{x}/{y}.png`
  and shows the attribution `© OpenStreetMap contributors`. Tiles may load online.
- The page shows every in-range station on the map and in a list, with its listed price,
  its distance, and its E10 price history; the overall price history; and the
  recommendation.
- `out/data.json` is the machine-readable copy of what the page shows:

  ```json
  {
    "recommendation": {"station_id": "STN-0000"},
    "stations": [
      {"id": "STN-0000", "name": "...", "lat": 0, "lon": 0, "distance_km": 0,
       "listed_price_cpl": 0,
       "history": [{"recorded_at": "2026-09-01T06:00:00+10:00", "price_cpl": 0}]}
    ],
    "overall_history": [{"date": "2026-09-01", "mean_price_cpl": 0}]
  }
  ```

  `stations` lists in-range stations only, each with its full E10 history.
- Every in-range station ID appears in `out/index.html` or in a local script it loads
  (for example `out/data.js`).
- Mark the recommended station in `out/index.html` with exactly one element carrying
  `data-recommended-station="<station id>"`.
- Out-of-range station IDs must not appear in any file under `out/`.

Commit the result.
