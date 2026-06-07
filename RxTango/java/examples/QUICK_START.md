# Quick Start Guide - RxTango Storage Ring Demo

## For Your Presentation

This guide will help you run the RxTango storage ring simulation demo during your presentation.

## Before the Presentation

### 1. Set Up the Environment (5 minutes)

```bash
# Navigate to the RxTango directory
cd /home/ingvord/Projects/rx-controls-suite/RxTango/java

# Start the Tango stack
docker compose up -d

# Wait for it to be healthy (about 10 seconds)
docker compose ps
```

### 2. Run the Smoke Test (2 minutes)

```bash
# Run the smoke test to verify everything is working
./examples/smoke-test.sh
```

This will:
- Check prerequisites (jbang, Java, Docker)
- Start the Tango stack if needed
- Create all required devices
- Test the demos

## During the Presentation

### Demo 1: Storage Ring Simulation (3 minutes)

**Command:**
```bash
jbang examples/StorageRingSimulation.java start
```

**What to show:**
1. The simulation starts with all devices
2. Show the live monitoring output
3. Explain the different device types (BPMs, VAC, RAD, BLD)
4. Point out the automatic alarm generation
5. Explain the control system logic

**Key points to mention:**
- "This is a complete storage ring environment"
- "All monitoring is reactive - no manual polling"
- "Alarms are automatically propagated"
- "Control system responds to conditions"

### Demo 2: Beam Loss Scenario (2 minutes)

**Command:**
```bash
jbang examples/BeamLossScenario.java trigger
```

**What to show:**
1. Trigger the beam loss event
2. Watch the alarm propagation
3. Show how radiation and vacuum systems respond
4. Explain the event-driven architecture

**Key points to mention:**
- "When beam loss is detected, alarms propagate automatically"
- "Reactive streams handle the coordination"
- "No manual intervention needed"

### Demo 3: Reactive vs Imperative (3 minutes)

**Command:**
```bash
jbang examples/ReactiveVsImperative.java both
```

**What to show:**
1. Run the reactive demo first
2. Run the imperative demo second
3. Compare the code side-by-side
4. Explain the advantages

**Key points to mention:**
- "Reactive: declarative, composable, event-driven"
- "Imperative: verbose, sequential, manual state management"
- "Reactive code is easier to read and maintain"
- "Backpressure is handled automatically"

## After the Presentation

### Clean Up

```bash
# Stop the simulation (Ctrl+C)
# Stop the Tango stack
docker compose down
```

## Troubleshooting

### If the simulation doesn't start:

1. **Check if Tango stack is running:**
   ```bash
   docker compose ps
   ```

2. **Check if devices exist:**
   ```bash
   tango-admin -l | grep SR
   ```

3. **Recreate devices:**
   ```bash
   tango-admin -c SR/BPM1 BPM
   tango-admin -c SR/VAC1 VacuumGauge
   # ... etc
   ```

### If jbang fails:

1. **Update jbang:**
   ```bash
   curl -Ls https://sh.jbang.dev | bash
   ```

2. **Clear cache:**
   ```bash
   rm -rf ~/.jbang/cache
   ```

## Presentation Flow

### Introduction (2 min)
- Welcome and overview
- What is RxTango?
- Why reactive programming for Tango?

### Demo 1 (3 min)
- Run StorageRingSimulation.java
- Show live monitoring
- Explain the architecture

### Demo 2 (2 min)
- Run BeamLossScenario.java
- Show alarm propagation
- Explain event-driven design

### Demo 3 (3 min)
- Run ReactiveVsImperative.java
- Compare approaches
- Highlight advantages

### Q&A (3 min)

## Key Takeaways

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

## Files Reference

- `StorageRingSimulation.java` - Main demo
- `BeamLossScenario.java` - Beam loss event demo
- `ReactiveVsImperative.java` - Comparison demo
- `STORAGE_RING_DEMO.md` - Detailed documentation
- `smoke-test.sh` - Verification script

## Additional Resources

- [RxTango GitHub](https://github.com/scientific-software-hub/RxTango)
- [Reactive Streams Spec](https://github.com/reactive-streams/reactive-streams-jvm)
- [Tango Controls](https://tango-controls.org/)

Good luck with your presentation! 🚀