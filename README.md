# TTN NOC prototype

Local first implementation of the FIC Cerezas Network Operations Center,
assuming The Things Network (TTN) as the LoRaWAN backend.

This prototype is intentionally independent from the production website and
reporting pipeline. It does not write to MongoDB and does not change any
server container.

## What it provides

- Gateway inventory and online/offline state.
- Gateway latitude, longitude and altitude from the TTN registry.
- A two-tab dashboard for `Gateways` and `Sensors`, with status and last communication time.
- A live OpenStreetMap gateway map with pan/zoom controls, blue online pins and red offline pins;
  clicking a pin shows gateway details and links to the TTN Cloud console and Google Maps. The viewer has no JavaScript map-library
  dependency and includes OpenStreetMap attribution.
- Coordinates are clickable links to Google Maps; this uses the public URL interface and does
  not require a Google Maps API key.
- TTN Cloud links use `TTN_REGION` by default (for example,
  `https://nam1.cloud.thethings.network/console/gateways/<gateway-id>`). Set
  `TTN_CONSOLE_BASE_URL` only if the console host differs from the configured cluster.
- Configurable gateway exclusions through `NOC_IGNORED_GATEWAYS` (case-insensitive substring
  matching against the gateway ID or display name).
- The current exclusions include rehabilitation gateways, UOH Ganaderia, Requinoa, and Rapel
  gateway identifiers.
- Sensor inventory is read from the configured TTN applications. Sensor locations are read from
  TTN device locations. The sensor map and table show only devices with valid TTN coordinates,
  and the sensor tab can be filtered between all located sensors and one application at a time.
- Site and gateway association from `config/sites.yaml`.
- A JSON API and a small dashboard that refreshes every 30 seconds.
- UOH Cerezas branding reused from the report website, including its header logo and light portal-style layout.
- Mock mode for local development without TTN credentials.
- TTN HTTP gateway inventory plus optional TTN MQTT uplink ingestion.

## Run locally with mock data

```bash
cd /Users/ignacio/repos/fic/repos/ttn_noc
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
NOC_MODE=mock python app.py
```

Open `http://127.0.0.1:8060`.

Useful endpoints:

```text
GET /api/health
GET /api/status
GET /api/gateways
GET /api/sensors
```

## TTN gateway and sensor mode

The live mode requires the TTN region, tenant and read-only API key. Gateway and
end-device registry requests use `TTN_IDENTITY_REGION=eu1`,
because the TTN Cloud Identity Server is hosted in `eu1`, even when the traffic
cluster is another region such as `nam1`.

`TTN_API_KEY` must contain the raw token (for example, `NNSXS...`), without the
`Bearer ` prefix, angle brackets or surrounding explanatory text.

Configure the sensor applications as a comma-separated list:

```dotenv
TTN_SENSOR_APPLICATIONS=fic2-rengo-eltotoral,fic2-rengo-donajaviera,fic2-graneros-agrofurore,fic2-rengo-agritorre,fic2-rapel-talhuenal,fic2-peumo-greenex,fic2-rengo-agricura,fic2-rengo-elperal,fic2-sanfernando-liceoagricola
```

The API key must be allowed to list end devices and read `last_seen_at` and
location fields for those applications. MQTT credentials are optional; when
configured, uplinks update sensor last-seen state in real time.

The live adapter expects the API key and optional TTN MQTT integration to be
configured externally. Never commit these values.

The repository includes a local `.env` template (ignored by Git). Replace its
placeholders with the real TTN values and update `config/sites.yaml` with the
gateway/device mapping. Compose loads this file automatically:

```bash
vim .env
vim config/sites.yaml
docker compose up --build -d
```

```bash
export NOC_MODE=ttn
export TTN_REGION=eu1
export TTN_TENANT=ttn
export TTN_API_KEY='N2I...'
python app.py
```

The API key must have only the permissions required to read gateway
information, gateway connection statistics, and the configured end-device
inventory. The MQTT credentials are used only to consume uplinks. Sensor status
falls back to the registry `last_seen_at` field when MQTT is not configured.
The first live version keeps telemetry in memory;
persistent consolidation belongs to the next data-integration phase.

## Current limitations

- No production deployment, alert delivery or authentication yet.
- The live map requires the browser to reach `tile.openstreetmap.org`; if that service is blocked,
  the gateway table and Google Maps links remain available.
- TTN gateway/end-device status and field names must be verified against the actual TTN
  tenant before production use.
- The thresholds are configurable through environment variables.

Run tests with:

```bash
python -m unittest discover -s tests -v
```

## Synchronize sensor locations from the installation spreadsheet

The spreadsheet-derived file `config/sensor_locations.csv` contains 80 sensors
with their TTN application, end-device ID, latitude, longitude and terrain
altitude. It contains no API credentials. The corresponding
`tools/update_ttn_locations.py` script is separate from the NOC application;
the NOC remains read-only.

The spreadsheet contains devices for eight applications. It has no rows for
`fic2-rapel-talhuenal`, so that application is intentionally not modified by
this import.

Run the comparison first from the repository root:

```bash
python3 tools/update_ttn_locations.py \
  --csv config/sensor_locations.csv
```

The default mode only reads TTN and reports `UNCHANGED` or `UPDATE` entries.
To apply the reviewed differences, use an API key with end-device update
permissions and explicitly provide both flags:

```bash
export TTN_API_KEY='write-enabled-token'
python3 tools/update_ttn_locations.py \
  --csv config/sensor_locations.csv \
  --apply --yes
```

The script preserves existing TTN location sources and replaces only the
spreadsheet-managed `locations.user` entry. After each update it performs a
second GET and reports whether the coordinates were verified. The
`altitude` column comes from the spreadsheet's `t_altitud_m` (terrain altitude)
column; `s_altitud_m` is a relative sensor-height value and is not sent to
TTN. TTN stores altitude as an integer number of meters, so decimal terrain
values are rounded to the nearest meter.
