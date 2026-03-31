# RxTine/java

Reactive Streams wrappers for the [TINE](https://tine.desy.de) control system
(Three-fold Integrated Networking Environment, DESY).
Built with [jbang](https://www.jbang.dev/) + RxJava3 + the TINE Java client API.

---

## Prerequisites

| Tool | Notes |
|------|-------|
| Java 11+ | any distribution |
| [jbang](https://www.jbang.dev/) | `sdk install jbang` |
| Docker + Compose | for the local test server |
| `tine.jar` in `~/.m2` | not on Maven Central — download from https://tine.desy.de |

Install the TINE jar once:

```bash
mvn install:install-file -Dfile=tine-5.3.jar \
    -DgroupId=de.desy.tine -DartifactId=tine -Dversion=5.3 -Dpackaging=jar
```

---

## Minimal local TINE environment (no ENS)

TINE normally relies on an Equipment Name Server (ENS) for address resolution —
similar to `TANGO_HOST` in Tango or a DNS in web services.
For local development you don't need it: three CSV files are enough to make a
standalone server discoverable by clients.

### How it works

```
client                         server (Docker)
──────                         ───────────────
TINE_HOME=client-config/       tine.properties → nameservice.disable=true
  tine.properties              fecid.csv       → server identity
    nameservice.disable=true   exports.csv     → property ↔ EQM mapping
  eqpdbase.csv                 SJNEQM-devices.csv → device list
    JSINESRV → SJNEQM          fecaddr.csv     → (own IP for self-registration)
  fecaddr.csv
    JSINESRV → 172.25.0.11:8503
```

**Address resolution path (client side):**
1. ENS disabled → skip name service
2. Read `eqpdbase.csv` → resolve `/TEST/JSINESRV` to FEC name `JSINESRV`
3. Read `fecaddr.csv` → resolve `JSINESRV` to `172.25.0.11:8503`

### The three essential CSV files

#### `docker/fecid.csv` — server identity

Tells `_SystemInit()` the server's exported name and context.
**Must have the header row — TINE looks up columns by name.**

```csv
FEC_NAME,CONTEXT,EXPORT_NAME,PORT_OFFSET,SUBSYSTEM,DESCRIPTION,LOCATION,HARDWARE,RESPONSIBLE
JSINESRV,TEST,JSINESRV,0,TEST,Sine wave test server,Docker,Docker,local
```

#### `docker/exports.csv` — property ↔ equipment-module binding

Maps the internal equipment module (`LOCAL_NAME`) to the exported server name
(`EXPORT_NAME`) and declares every property the server exposes.
**Without this file, `_SystemInit()` registers the EQM with an empty export name
and all client requests return "illegal property".**

```csv
EXPORT_NAME,LOCAL_NAME,PROPERTY,PROPERTY_SIZE,FORMAT,ACCESS,DESCRIPTION
JSINESRV,SJNEQM,Sine,1,float,READ,Sine wave value
JSINESRV,SJNEQM,Amplitude,1,float,READ|WRITE,Amplitude of the sine wave
JSINESRV,SJNEQM,Frequency,1,float,READ|WRITE,Frequency of the sine wave
JSINESRV,SJNEQM,Noise,1,float,READ,Noise level
```

#### `client-config/eqpdbase.csv` — client address cache

Maps a `/CONTEXT/SERVER` path to a FEC name so the client can resolve the address
without querying the ENS.

```csv
NAME,CONTEXT,EQPMODULE,FECNAME
JSINESRV,TEST,SJNEQM,JSINESRV
```

---

## Quickstart

### 1. Supply the TINE jars

```bash
cp /path/to/tine.jar       docker/
cp /path/to/jsineServer.jar docker/
```

These are not in Maven Central and are not committed to the repo (`.gitignore`d).

### 2. Start the test server

```bash
docker compose up -d
```

The `jsinesrv` container starts a sine-wave device server on the fixed IP
`172.25.0.11` (bridge network `172.25.0.0/24`).
No ENS container is needed.

### 3. Verify the server is up

```bash
docker compose ps          # should show jsinesrv healthy
docker exec jsinesrv grep "open TCP" /tine-config/fec.log.0
# → open TCP server socket at port 8503
```

### 4. Read a property

```bash
TINE_HOME=$(pwd)/client-config jbang examples/ReadProperty.java \
    /TEST/JSINESRV/SINEDEV_0 Sine
# → /TEST/JSINESRV/SINEDEV_0/Sine = 0.842820
```

### 5. Run the full examples

```bash
cd RxTine/java   # all jbang commands run from here

# single read
TINE_HOME=$(pwd)/client-config jbang examples/ReadProperty.java \
    /TEST/JSINESRV/SINEDEV_0 Sine

# poll every 500 ms
TINE_HOME=$(pwd)/client-config jbang examples/PollProperty.java \
    /TEST/JSINESRV/SINEDEV_0 Sine 500

# push monitor (server-side polling)
TINE_HOME=$(pwd)/client-config jbang examples/MonitorProperty.java \
    /TEST/JSINESRV/SINEDEV_0 Sine 500
```

---

## Test device reference

| Address | `/TEST/JSINESRV/SINEDEV_0` … `SINEDEV_9` |
|---------|-------------------------------------------|
| Context | `TEST` |
| Server  | `JSINESRV` |
| Devices | `SINEDEV_0` … `SINEDEV_9` (10 sine generators) |

| Property    | Type    | Access | Description                         |
|-------------|---------|--------|-------------------------------------|
| `Sine`      | float   | R      | Propagating sine wave (per device)  |
| `Amplitude` | float   | R/W    | Amplitude of the sine wave          |
| `Frequency` | float   | R/W    | Frequency of the sine wave          |
| `Noise`     | float   | R      | Noise level                         |

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `illegal property` | `exports.csv` missing header or wrong `LOCAL_NAME` | Check `EXPORT_NAME,LOCAL_NAME` header and that `LOCAL_NAME` matches the EQM (`SJNEQM`) |
| `FEC Name unknown at start time` | `fecid.csv` missing header row | Add `FEC_NAME,CONTEXT,EXPORT_NAME,...` header |
| `Could not resolve address` | stale host TINE cache | `rm -rf /var/tmp/tine/cache/` |
| `link timeout` | wrong IP in `client-config/fecaddr.csv` | Confirm `JSINESRV,172.25.0.11,0` and that the Docker bridge is `172.25.0.0/24` |
| No log output from container | TINE logs to file, not stdout | `docker exec jsinesrv cat /tine-config/fec.log.0` |

---

## Project layout

```
src/            Library source (included via jbang //SOURCES)
examples/       Runnable jbang demo scripts
docker/         jsineServer Dockerfile + config CSVs
  fecid.csv         server identity
  exports.csv       property ↔ EQM binding  ← critical
  SJNEQM-devices.csv  device names
  tine.properties   standalone mode (nameservice.disable=true)
  fecaddr.csv       server's own IP (for self-registration)
  eqpdbase.csv      server-side address cache pre-population
client-config/  TINE_HOME for running examples on the host
  tine.properties   nameservice.disable=true
  cshosts.csv       ENS addresses (required by TINE client even in standalone mode)
  eqpdbase.csv      /TEST/JSINESRV → FEC JSINESRV
  fecaddr.csv       JSINESRV → 172.25.0.11:8503
docker-compose.yml
```
