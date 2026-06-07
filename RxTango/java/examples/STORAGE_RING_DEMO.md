# Storage Ring Simulation - RxTango Demo

A comprehensive demonstration of reactive programming in Tango Controls for a synchrotron storage ring environment.

## Overview

This demo showcases how RxTango enables declarative, event-driven control system programming with automatic backpressure handling and clean composition of device interactions.

## Prerequisites

1. **jbang** - Install with: `curl -Ls https://sh.jbang.dev | bash`
2. **Java 11+**
3. **Docker** - For the Tango stack
4. **GitHub Packages access** - For JTango artifacts (one-time setup)

### JTango Setup

Add to `~/.m2/settings.xml`:

```xml
<settings>
  <servers>
    <server>
      <id>jtango</id>
      <username>YOUR_GITHUB_USERNAME</username>
      <password>YOUR_CLASSIC_PAT</password>
    </server>
  </servers>
</settings>
```

## Quick Start

### 1. Start the Tango Stack

```bash
cd /home/ingvord/Projects/rx-controls-suite/RxTango/java
docker compose up -d
```

Wait ~10 seconds for all containers to be healthy.

### 2. Run the Main Demo

```bash
jbang examples/StorageRingSimulation.java start
```

This starts the complete storage ring simulation with:
- 12 Beam Position Monitors (BPMs)
- 8 Vacuum Gauges
- 6 Radiation Monitors
- 4 Beam Loss Detectors
- Control System

Press `Ctrl+C` to stop.

## Demo Scenarios

### Scenario 1: Storage Ring Simulation

**File:** `StorageRingSimulation.java`

**Purpose:** Complete storage ring environment with all devices and monitoring.

**Commands:**
```bash
# Start simulation
jbang examples/StorageRingSimulation.java start

# Monitor live data
jbang examples/StorageRingSimulation.java monitor

# Reset simulation
jbang examples/StorageRingSimulation.java reset

# Run comparison demo
jbang examples/StorageRingSimulation.java compare
```

**What it demonstrates:**
- Device creation and registration
- Reactive monitoring of multiple devices
- Automatic alarm generation
- Control system logic
- Comparison between reactive and imperative approaches

### Scenario 2: Beam Loss Event

**File:** `BeamLossScenario.java`

**Purpose:** Demonstrates reactive alarm propagation during a beam loss event.

**Commands:**
```bash
# Trigger beam loss
jbang examples/BeamLossScenario.java trigger

# Monitor alarm propagation
jbang examples/BeamLossScenario.java monitor

# Reset scenario
jbang examples/BeamLossScenario.java reset
```

**What it demonstrates:**
- Automatic alarm propagation through reactive streams
- Multi-device coordination
- Emergency response simulation
- Event-driven architecture

### Scenario 3: Reactive vs Imperative Comparison

**File:** `ReactiveVsImperative.java`

**Purpose:** Side-by-side comparison of reactive and imperative programming approaches.

**Commands:**
```bash
# Show reactive approach
jbang examples/ReactiveVsImperative.java reactive

# Show imperative approach
jbang examples/ReactiveVsImperative.java imperative

# Show both approaches
jbang examples/ReactiveVsImperative.java both
```

**What it demonstrates:**
- Declarative vs imperative syntax
- Operator composition
- Backpressure handling
- Code readability and maintainability

## Reactive Programming Concepts Demonstrated

### 1. Event-Driven Monitoring

```java
Observable.fromPublisher(
    new RxTangoAttributeChangePublisher<>(
        proxy, attribute, TangoEvent.CHANGE
    )
)
.subscribe(
    value -> System.out.println(value),
    error -> System.err.println(error)
);
```

**Advantage:** Automatic event handling without manual polling.

### 2. Operator Composition

```java
Observable.fromPublisher(...)
    .map(value -> transform(value))
    .filter(condition)
    .distinctUntilChanged()
    .subscribe(...);
```

**Advantage:** Clean, readable transformations.

### 3. Backpressure Handling

```java
Observable.interval(1, TimeUnit.SECONDS)
    .flatMapSingle(tick -> readDevice())
    .subscribe(...);
```

**Advantage:** Automatic flow control prevents overload.

### 4. Automatic Error Handling

```java
.subscribe(
    value -> handle(value),
    error -> log(error)
);
```

**Advantage:** Centralized error handling.

## Storage Ring Device Model

### Beam Position Monitors (BPM)
- **Device:** `SR/BPM1` through `SR/BPM12`
- **Attributes:** `X_Position`, `Y_Position`
- **Purpose:** Track beam position in storage ring

### Vacuum Gauges (VAC)
- **Device:** `SR/VAC1` through `SR/VAC8`
- **Attributes:** `Pressure`
- **Purpose:** Monitor vacuum pressure in sectors

### Radiation Monitors (RAD)
- **Device:** `SR/RAD1` through `SR/RAD6`
- **Attributes:** `DoseRate`
- **Purpose:** Detect radiation levels

### Beam Loss Detectors (BLD)
- **Device:** `SR/BLD1` through `SR/BLD4`
- **Attributes:** `Loss`
- **Purpose:** Trigger alarms on beam loss

### Control System
- **Device:** `SR/Control`
- **Attributes:** `ControlState`, `LastUpdate`
- **Purpose:** Implement control logic

## Comparison: Reactive vs Imperative

### Imperative Approach
```java
for (int i = 0; i < 10; i++) {
    try {
        double value = readDevice();
        if (condition) {
            triggerAlarm();
        }
        Thread.sleep(500);
    } catch (Exception e) {
        handleError(e);
    }
}
```

**Disadvantages:**
- Verbose and sequential
- Manual error handling
- State management required
- No composition

### Reactive Approach
```java
Observable.fromPublisher(device)
    .filter(condition)
    .subscribe(
        value -> handle(value),
        error -> handleError(error)
    );
```

**Advantages:**
- Declarative and composable
- Automatic error handling
- Event-driven
- Clean separation of concerns

## Presentation Tips

### Key Points to Emphasize

1. **Declarative Syntax**
   - "What to do" instead of "how to do"
   - Easier to read and maintain

2. **Operator Composition**
   - Chain transformations naturally
   - Powerful and flexible

3. **Backpressure**
   - Automatic flow control
   - Prevents overload

4. **Event-Driven**
   - Responds to changes automatically
   - No manual polling needed

5. **Clean Architecture**
   - Separation of concerns
   - Functional programming style

### Demo Flow for Presentation

1. **Introduction** (2 min)
   - Explain RxTango purpose
   - Show code snippets

2. **Basic Demo** (3 min)
   - Run `StorageRingSimulation.java start`
   - Show device monitoring

3. **Scenario Demo** (3 min)
   - Run `BeamLossScenario.java trigger`
   - Show alarm propagation

4. **Comparison Demo** (4 min)
   - Run `ReactiveVsImperative.java both`
   - Explain advantages

5. **Q&A** (3 min)

## Troubleshooting

### Docker Issues
```bash
# Stop and remove containers
docker compose down

# Restart
docker compose up -d

# Check status
docker compose ps
```

### jbang Issues
```bash
# Update jbang
curl -Ls https://sh.jbang.dev | bash

# Clear cache
rm -rf ~/.jbang/cache
```

### Device Not Found
```bash
# Check if devices exist
tango-admin -l | grep SR

# Create devices
tango-admin -c SR/BPM1 BPM
tango-admin -c SR/VAC1 VacuumGauge
# ... etc
```

## Additional Resources

- [RxTango GitHub](https://github.com/scientific-software-hub/RxTango)
- [Reactive Streams Spec](https://github.com/reactive-streams/reactive-streams-jvm)
- [Tango Controls Documentation](https://tango-controls.org/)
- [RxJava Documentation](https://github.com/ReactiveX/RxJava)

## License

AGPL-3.0 - See LICENSE file for details