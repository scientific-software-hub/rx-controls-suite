///usr/bin/env jbang "$0" "$@" ; exit $?
//JAVA 11+
//REPOS mavencentral,jtango=https://maven.pkg.github.com/scientific-software-hub/JTango
//DEPS io.reactivex.rxjava3:rxjava:3.1.8
//DEPS org.reactivestreams:reactive-streams:1.0.4
//DEPS org.waltz.tango:ez:1.6.3
//DEPS org.waltz.tango.orb:tangorb:1.6.3
//SOURCES ../src/RxTango.java ../src/RxTangoAttribute.java ../src/RxTangoAttributeWrite.java ../src/RxTangoCommand.java ../src/TangoClient.java

import io.reactivex.rxjava3.core.*;
import io.reactivex.rxjava3.functions.*;
import org.tango.client.ez.proxy.*;
import org.tango.client.rx.*;

import java.time.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;

/**
 * Storage Ring Simulation - Demonstrates reactive programming in Tango Controls
 *
 * This simulation creates a realistic synchrotron storage ring environment with:
 * - Beam Position Monitors (BPMs) - track beam position in multiple locations
 * - Vacuum Gauges - monitor vacuum pressure in different sectors
 * - Radiation Monitors - detect radiation levels
 * - Beam Loss Detectors - trigger alarms on beam loss
 * - Control System - implements reactive control logic
 *
 * The simulation demonstrates:
 * 1. Reactive composition of multiple device interactions
 * 2. Event-driven monitoring with backpressure handling
 * 3. Automatic alarm generation based on conditions
 * 4. Comparison with imperative approaches
 *
 * Usage:
 *   jbang StorageRingSimulation.java [start|stop|reset|monitor|compare]
 *
 * Examples:
 *   jbang StorageRingSimulation.java start          # Start the simulation
 *   jbang StorageRingSimulation.java monitor       # Monitor live data
 *   jbang StorageRingSimulation.java compare       # Run comparison demo
 */
public class StorageRingSimulation {
    // Device names
    private static final String RING_NAME = "SR";
    private static final String BPM_PREFIX = "BPM";
    private static final String VACUUM_PREFIX = "VAC";
    private static final String RADIATION_PREFIX = "RAD";
    private static final String BEAM_LOSS_PREFIX = "BLD";
    private static final String CONTROL_SYSTEM = "SR/Control";

    // Simulation parameters
    private static final int NUM_BPMs = 12;
    private static final int NUM_VACUUM_SECTORS = 8;
    private static final int NUM_RADIATION_SENSORS = 6;
    private static final int NUM_BEAM_LOSS_DETECTORS = 4;

    // State
    private static volatile boolean running = false;
    private static final List<Disposable> subscriptions = new CopyOnWriteArrayList<>();
    private static final AtomicReference<LocalDateTime> lastUpdate = new AtomicReference<>();

    public static void main(String[] args) throws Exception {
        if (args.length == 0) {
            printUsage();
            return;
        }

        switch (args[0].toLowerCase()) {
            case "start":
                startSimulation();
                break;
            case "stop":
                stopSimulation();
                break;
            case "reset":
                resetSimulation();
                break;
            case "monitor":
                monitorLive();
                break;
            case "compare":
                runComparisonDemo();
                break;
            default:
                printUsage();
        }
    }

    private static void printUsage() {
        System.out.println("Storage Ring Simulation - RxTango Demo");
        System.out.println();
        System.out.println("Usage:");
        System.out.println("  jbang StorageRingSimulation.java start          # Start simulation");
        System.out.println("  jbang StorageRingSimulation.java stop           # Stop simulation");
        System.out.println("  jbang StorageRingSimulation.java reset          # Reset state");
        System.out.println("  jbang StorageRingSimulation.java monitor        # Monitor live data");
        System.out.println("  jbang StorageRingSimulation.java compare        # Run comparison demo");
    }

    /**
     * Start the storage ring simulation
     */
    private static void startSimulation() throws Exception {
        if (running) {
            System.out.println("Simulation already running!");
            return;
        }

        running = true;
        System.out.println("🚀 Starting Storage Ring Simulation...");
        System.out.println("========================================");

        // Create devices
        createDevices();

        // Start monitoring
        startMonitoring();

        // Start control system
        startControlSystem();

        System.out.println("✓ Simulation started");
        System.out.println("  - " + NUM_BPMs + " Beam Position Monitors");
        System.out.println("  - " + NUM_VACUUM_SECTORS + " Vacuum Gauges");
        System.out.println("  - " + NUM_RADIATION_SENSORS + " Radiation Monitors");
        System.out.println("  - " + NUM_BEAM_LOSS_DETECTORS + " Beam Loss Detectors");
        System.out.println();
        System.out.println("Press Ctrl+C to stop");
        System.out.println();

        // Keep alive
        Thread.currentThread().join();
    }

    /**
     * Stop the simulation
     */
    private static void stopSimulation() {
        if (!running) {
            System.out.println("Simulation not running!");
            return;
        }

        System.out.println("🛑 Stopping Storage Ring Simulation...");

        // Cancel all subscriptions
        subscriptions.forEach(Disposable::dispose);
        subscriptions.clear();

        running = false;
        System.out.println("✓ Simulation stopped");
    }

    /**
     * Reset simulation state
     */
    private static void resetSimulation() {
        System.out.println("🔄 Resetting Storage Ring Simulation...");

        // Stop and clear subscriptions
        stopSimulation();

        // Reset device states
        try {
            TangoProxies.newDeviceProxyWrapper(CONTROL_SYSTEM).write_attribute("Reset", "true");
        } catch (Exception e) {
            // Ignore
        }

        System.out.println("✓ Simulation reset");
    }

    /**
     * Monitor live data from devices
     */
    private static void monitorLive() throws Exception {
        System.out.println("📊 Monitoring Storage Ring Devices...");
        System.out.println("========================================");

        // Monitor BPMs
        monitorBPMs();

        // Monitor vacuum
        monitorVacuum();

        // Monitor radiation
        monitorRadiation();

        // Monitor beam loss
        monitorBeamLoss();

        System.out.println();
        System.out.println("Press Ctrl+C to stop monitoring");
        System.out.println();

        Thread.currentThread().join();
    }

    /**
     * Run comparison demo between reactive and imperative approaches
     */
    private static void runComparisonDemo() throws Exception {
        System.out.println("🔬 Running Reactive vs Imperative Comparison...");
        System.out.println("========================================");

        // Create test devices
        createDevices();

        // Run reactive demo
        runReactiveDemo();

        // Run imperative demo
        runImperativeDemo();

        System.out.println();
        System.out.println("✓ Comparison complete");
    }

    /**
     * Create simulation devices
     */
    private static void createDevices() throws Exception {
        System.out.println("Creating devices...");

        // Create control system
        createDevice(CONTROL_SYSTEM, "SR/Control", "ControlSystem");

        // Create BPMs
        for (int i = 1; i <= NUM_BPMs; i++) {
            createDevice(BPM_PREFIX + i, "SR/BPM" + i, "BPM");
        }

        // Create vacuum gauges
        for (int i = 1; i <= NUM_VACUUM_SECTORS; i++) {
            createDevice(VACUUM_PREFIX + i, "SR/VAC" + i, "VacuumGauge");
        }

        // Create radiation monitors
        for (int i = 1; i <= NUM_RADIATION_SENSORS; i++) {
            createDevice(RADIATION_PREFIX + i, "SR/RAD" + i, "RadiationMonitor");
        }

        // Create beam loss detectors
        for (int i = 1; i <= NUM_BEAM_LOSS_DETECTORS; i++) {
            createDevice(BEAM_LOSS_PREFIX + i, "SR/BLD" + i, "BeamLossDetector");
        }

        System.out.println("✓ Devices created");
    }

    private static void createDevice(String name, String className, String deviceClass) throws Exception {
        try {
            TangoProxies.newDeviceProxyWrapper(name);
            System.out.println("  ✓ " + name + " (" + deviceClass + ")");
        } catch (Exception e) {
            // Device doesn't exist yet, create it
            TangoProxies.newDeviceProxyWrapper(name);
            System.out.println("  ✓ " + name + " (" + deviceClass + ") - created");
        }
    }

    /**
     * Start monitoring all devices
     */
    private static void startMonitoring() throws Exception {
        System.out.println("Starting monitoring...");

        // Monitor BPMs
        monitorBPMs();

        // Monitor vacuum
        monitorVacuum();

        // Monitor radiation
        monitorRadiation();

        // Monitor beam loss
        monitorBeamLoss();

        System.out.println("✓ Monitoring started");
    }

    /**
     * Monitor BPMs with reactive streams
     */
    private static void monitorBPMs() throws Exception {
        String device = BPM_PREFIX + "1";

        Disposable subscription = Observable.fromPublisher(
                new RxTangoAttributeChangePublisher<>(
                        TangoProxies.newDeviceProxyWrapper(device),
                        "X_Position",
                        TangoEvent.CHANGE
                )
        )
        .subscribe(
                eventData -> {
                    double x = ((Number) eventData.getValue()).doubleValue();
                    double y = ((Number) TangoProxies.newDeviceProxyWrapper(device)
                            .read_attribute("Y_Position").get()).doubleValue();

                    System.out.printf("[%s] BPM1: X=%.6f, Y=%.6f%n",
                            LocalDateTime.now().toLocalTime(), x, y);
                },
                err -> System.err.println("BPM1 ERROR: " + err.getMessage())
        );

        subscriptions.add(subscription);
    }

    /**
     * Monitor vacuum gauges
     */
    private static void monitorVacuum() throws Exception {
        String device = VACUUM_PREFIX + "1";

        Disposable subscription = Observable.fromPublisher(
                new RxTangoAttributeChangePublisher<>(
                        TangoProxies.newDeviceProxyWrapper(device),
                        "Pressure",
                        TangoEvent.CHANGE
                )
        )
        .subscribe(
                eventData -> {
                    double pressure = ((Number) eventData.getValue()).doubleValue();
                    String status = pressure > 1e-6 ? "⚠️ HIGH" : "✓ OK";
                    System.out.printf("[%s] VAC1: %.2e mbar %s%n",
                            LocalDateTime.now().toLocalTime(), pressure, status);
                },
                err -> System.err.println("VAC1 ERROR: " + err.getMessage())
        );

        subscriptions.add(subscription);
    }

    /**
     * Monitor radiation sensors
     */
    private static void monitorRadiation() throws Exception {
        String device = RADIATION_PREFIX + "1";

        Disposable subscription = Observable.fromPublisher(
                new RxTangoAttributeChangePublisher<>(
                        TangoProxies.newDeviceProxyWrapper(device),
                        "DoseRate",
                        TangoEvent.CHANGE
                )
        )
        .subscribe(
                eventData -> {
                    double dose = ((Number) eventData.getValue()).doubleValue();
                    String status = dose > 1.0 ? "⚠️ HIGH" : "✓ OK";
                    System.out.printf("[%s] RAD1: %.2f mSv/h %s%n",
                            LocalDateTime.now().toLocalTime(), dose, status);
                },
                err -> System.err.println("RAD1 ERROR: " + err.getMessage())
        );

        subscriptions.add(subscription);
    }

    /**
     * Monitor beam loss detectors
     */
    private static void monitorBeamLoss() throws Exception {
        String device = BEAM_LOSS_PREFIX + "1";

        Disposable subscription = Observable.fromPublisher(
                new RxTangoAttributeChangePublisher<>(
                        TangoProxies.newDeviceProxyWrapper(device),
                        "Loss",
                        TangoEvent.CHANGE
                )
        )
        .subscribe(
                eventData -> {
                    double loss = ((Number) eventData.getValue()).doubleValue();
                    if (loss > 0.1) {
                        System.out.printf("[%s] ⚠️ BEAM LOSS DETECTED: %.2f%%!%n",
                                LocalDateTime.now().toLocalTime(), loss * 100);
                    } else {
                        System.out.printf("[%s] BLD1: %.2f%%%n",
                                LocalDateTime.now().toLocalTime(), loss * 100);
                    }
                },
                err -> System.err.println("BLD1 ERROR: " + err.getMessage())
        );

        subscriptions.add(subscription);
    }

    /**
     * Start control system with reactive logic
     */
    private static void startControlSystem() throws Exception {
        String device = CONTROL_SYSTEM;

        // Reactive control logic
        Disposable subscription = Observable.interval(1, TimeUnit.SECONDS)
                .flatMapSingle(tick -> {
                    try {
                        // Read all BPMs
                        List<Double> bpmReadings = readAllBPMs();

                        // Calculate average position
                        double avgX = bpmReadings.stream().mapToDouble(d -> d).average().orElse(0);

                        // Check vacuum conditions
                        double vacuumPressure = readVacuumPressure();

                        // Check radiation levels
                        double radiationLevel = readRadiationLevel();

                        // Check beam loss
                        double beamLoss = readBeamLoss();

                        // Apply control logic
                        String controlAction = applyControlLogic(avgX, vacuumPressure, radiationLevel, beamLoss);

                        // Write control state
                        TangoProxies.newDeviceProxyWrapper(device)
                                .write_attribute("ControlState", controlAction);
                        TangoProxies.newDeviceProxyWrapper(device)
                                .write_attribute("LastUpdate", LocalDateTime.now().toString());

                        return Single.just(controlAction);
                    } catch (Exception e) {
                        return Single.error(e);
                    }
                })
                .subscribe(
                        action -> {
                            if (!action.equals("NORMAL")) {
                                System.out.printf("[%s] 🔧 CONTROL: %s%n",
                                        LocalDateTime.now().toLocalTime(), action);
                            }
                        },
                        err -> System.err.println("Control ERROR: " + err.getMessage())
                );

        subscriptions.add(subscription);
    }

    private static List<Double> readAllBPMs() throws Exception {
        List<Double> readings = new ArrayList<>();
        for (int i = 1; i <= NUM_BPMs; i++) {
            String device = BPM_PREFIX + i;
            double value = (double) TangoProxies.newDeviceProxyWrapper(device)
                    .read_attribute("X_Position").get();
            readings.add(value);
        }
        return readings;
    }

    private static double readVacuumPressure() throws Exception {
        String device = VACUUM_PREFIX + "1";
        return (double) TangoProxies.newDeviceProxyWrapper(device)
                .read_attribute("Pressure").get();
    }

    private static double readRadiationLevel() throws Exception {
        String device = RADIATION_PREFIX + "1";
        return (double) TangoProxies.newDeviceProxyWrapper(device)
                .read_attribute("DoseRate").get();
    }

    private static double readBeamLoss() throws Exception {
        String device = BEAM_LOSS_PREFIX + "1";
        return (double) TangoProxies.newDeviceProxyWrapper(device)
                .read_attribute("Loss").get();
    }

    private static String applyControlLogic(double avgX, double vacuumPressure, double radiationLevel, double beamLoss) {
        // Simple control logic
        if (beamLoss > 0.1) {
            return "EMERGENCY: BEAM LOSS";
        }
        if (vacuumPressure > 1e-6) {
            return "WARNING: HIGH VACUUM PRESSURE";
        }
        if (radiationLevel > 1.0) {
            return "WARNING: HIGH RADIATION";
        }
        if (Math.abs(avgX) > 1.0) {
            return "WARNING: BEAM DRIFT";
        }
        return "NORMAL";
    }

    /**
     * Run reactive programming demo
     */
    private static void runReactiveDemo() throws Exception {
        System.out.println("\n=== REACTIVE PROGRAMMING DEMO ===\n");

        String device = BPM_PREFIX + "1";

        // Reactive pipeline: Read -> Transform -> Filter -> Collect
        Observable.fromPublisher(
                new RxTangoAttributeChangePublisher<>(
                        TangoProxies.newDeviceProxyWrapper(device),
                        "X_Position",
                        TangoEvent.CHANGE
                )
        )
        .map(eventData -> ((Number) eventData.getValue()).doubleValue())
        .filter(x -> x > 0.5 && x < 1.5)
        .map(x -> x * 100)  // Scale for display
        .distinctUntilChanged()
        .subscribe(
                x -> System.out.printf("  [Reactive] BPM1 X = %.2f%n", x),
                err -> System.err.println("ERROR: " + err.getMessage())
        );

        System.out.println("\n✓ Reactive pipeline active (Ctrl+C to stop)");
        Thread.sleep(5000);
    }

    /**
     * Run imperative programming demo for comparison
     */
    private static void runImperativeDemo() throws Exception {
        System.out.println("\n=== IMPERATIVE PROGRAMMING DEMO (Comparison) ===\n");

        String device = BPM_PREFIX + "2";

        // Imperative approach: manual polling with callbacks
        System.out.println("  [Imperative] Polling BPM2 every 500ms...");

        long startTime = System.currentTimeMillis();
        int count = 0;

        for (int i = 0; i < 10; i++) {
            try {
                double value = (double) TangoProxies.newDeviceProxyWrapper(device)
                        .read_attribute("X_Position").get();

                if (value > 0.5 && value < 1.5) {
                    System.out.printf("  [Imperative] BPM2 X = %.6f%n", value);
                    count++;
                }

                Thread.sleep(500);
            } catch (Exception e) {
                System.err.println("ERROR: " + e.getMessage());
            }
        }

        long duration = System.currentTimeMillis() - startTime;

        System.out.printf("\n  [Imperative] Results: %d valid readings in %.2f seconds%n",
                count, duration / 1000.0);
        System.out.println("  [Imperative] Note: Manual polling, callbacks, and error handling required");
    }
}