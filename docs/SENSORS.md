# Capture node and sensor records

Developer: **Vinay Chittora**.

The Raspberry Pi is always the acquisition node. Camera, microphone and sensors
connect to it; the separate GPU computer runs FALCON, retains evidence and serves
the interface. The connection can be Ethernet or local Wi-Fi. Internet is not
required for local monitoring. The physical Pi and sensor models can change.

## Stable software boundary

- Video and audio arrive through the provisioned RTSP stream. A microphone track
  must be configured explicitly; a CSI camera alone supplies no audio.
- Each sensor driver converts its measurements into explicit units and a stable
  sensor identifier before transmission. Never put I²C addresses or vendor-driver
  logic into inference or review code.
- Poll sensors independently of wildlife inference. A reasonable initial polling
  interval is 30 seconds, subject to the selected sensor's timing requirements.
- No Pi backlog is required. Failed delivery may be dropped, leaving a visible
  gap. Reconnection resumes current readings; it must not invent missing samples.

The current version supports temperature (°C), relative humidity (%) and pressure
(hPa); any subset is accepted. Adding another measurement type requires an explicit
versioned schema, units, validation and UI/export mapping. Unknown fields are
rejected rather than silently lost. A replacement temperature sensor can use the
existing schema without a server database migration.

## Ingestion and storage

Set a random `SENSOR_INGEST_TOKEN` in the inference computer's private `.env`, and
provision the same secret only to the authorized node bridge. The token is never
returned by the API. Set `SENSOR_ID` to the sensor/node whose readings should be
attached to camera detections; if multiple sensor IDs exist without that choice,
event association is unavailable rather than guessed. `SENSOR_STALE_AFTER_SECONDS`
defaults to 120.

`POST /api/sensors/readings` requires the `X-Falcon-Sensor-Key` header and a local
connection. FALCON's web API remains loopback-only. A deliberately provisioned SSH
forward or local receiver can bridge the Pi; Tailscale admin browser access does
not grant sensor-writing access. The node installer/driver provisioning is not
implemented yet. Do not expose port 8000 publicly to make sensors connect.

Example request body (illustrative measurements, never automatically ingested):

```json
{
  "schema_version": "1.0",
  "reading_id": "unique-node-boot-and-sequence",
  "sensor_id": "field-node-1",
  "observed_at": "2026-01-01T10:30:00Z",
  "temperature_c": 24.5,
  "humidity_percent": 45.2,
  "pressure_hpa": 1004.8,
  "quality": "valid"
}
```

Identifiers are required and timestamps must include a timezone. Identical retries
are idempotent; conflicting reuse of an ID returns 409. Invalid/nonfinite values
and timestamps more than the allowed clock tolerance ahead of the server are
rejected. `quality` can be `valid`, `suspect` or `invalid`, with an optional note.
The server adds its own `received_at`; it does not replace the measurement time.

SQLite retains readings independently of observations. `/api/sensors/history`
supports pagination, sensor ID and time bounds. `/api/sensors/current` reports
the latest eligible reading and freshness. Event association selects the latest
measurement at or before the event, retaining its age. Suspect/invalid data remains
in history but is not presented as valid event weather. File tests never receive
current sensor readings.

The field interface shows periodic history. The full field export includes these
independent records; session-filtered exports require a known sensor and trustworthy
session bounds. See [data export](DATA_EXPORT.md) and [field deployment](FIELD_DEPLOYMENT.md).

No physical sensor has been selected or validated yet. A deployment must verify
driver support, calibration, exposure/shielding and both machine clocks before
treating measurements as scientific field data.
