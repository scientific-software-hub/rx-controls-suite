# C++ Tango Storage Ring Demo

This demo package replaces the earlier `TangoTest`-based mock with a real
C++ Tango device server.

## Simulator layout

- `cpp/`
  C++ `cppTango` device server source and Docker build.
- `docker-compose.yml`
  Starts Tango DB, registers devices, and runs the simulator server.
- `scripts/*.java`
  `jbang` live demos that talk to the real simulated devices.

## Tango devices

- `sr/demo/controller`
  Global machine controls and derived machine-wide metrics.
- `sr/demo/sector01` .. `sr/demo/sector08`
  Sector devices exposing orbit, vacuum, radiation, and beam-loss values.

## Controller attributes

- `ScenarioId` (`rw`)
  `0=nominal`, `1=orbit_drift`, `2=vacuum_burst`, `3=beam_loss`
- `BeamCurrentTarget` (`rw`)
- `OrbitCorrection` (`rw`)
- `SimulationTime` (`ro`)
- `BeamCurrent` (`ro`)
- `LifetimeHours` (`ro`)
- `InterlockCount` (`ro`)

## Sector attributes

- `SectorIndex`
- `BeamCurrent`
- `OrbitX`
- `VacuumPressure`
- `RadiationDoseRate`
- `BeamLossFraction`

## Quick start

```bash
docker compose up -d --build
docker compose ps
```

The compose stack intentionally runs `tango-db`, `tango-dbds`, and the
simulator server on host networking so the Tango database and the exported
device IORs resolve the same control-plane addresses during a host-side
`jbang` demo.

Then run the live demos:

```bash
jbang ring-scenario@. nominal
jbang ring-dashboard@.
```
```bash
jbang ring-scenario@. orbit_drift
jbang ring-correlation@.
```
```bash
jbang ring-scenario@. nominal
jbang ring-smoothing@.
```
```bash
jbang ring-scenario@. beam_loss
jbang ring-interlocks@.
```
```bash
jbang ring-scenario@. nominal
jbang ring-backpressure@.
```

## Presentation flow

1. `ring-dashboard`
   Open with the machine overview.
2. `ring-scenario orbit_drift`
   Push the machine into a controlled orbit fault.
3. `ring-correlation`
   Show atomic multi-device reads with `Single.zip`.
4. `ring-scenario nominal`
   Clear the fault and go back to a stable current decay profile.
5. `ring-smoothing`
   Show stream processing plus guarded write-back to `OrbitCorrection`.
6. `ring-scenario beam_loss`
   Trigger a loss event before the interlock fan-in demo.
7. `ring-interlocks`
   Show alarm fan-in across sectors.
8. `ring-scenario nominal`
   Reset the machine before the final demo.
9. `ring-backpressure`
   Show explicit overload policy.

## Smoke test

```bash
./smoke-test.sh
```

This validates compose syntax, builds the Java scripts, and tries to build the
simulator image.
