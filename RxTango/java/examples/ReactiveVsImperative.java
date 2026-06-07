///usr/bin/env jbang "$0" "$@" ; exit $?
//JAVA 11+
//REPOS mavencentral,jtango=https://maven.pkg.github.com/scientific-software-hub/JTango
//DEPS io.reactivex.rxjava3:rxjava:3.1.8
//DEPS org.reactivestreams:reactive-streams:1.0.4
//DEPS org.waltz.tango:ez:1.6.3
//DEPS org.waltz.tango.orb:tangorb:1.6.3
//SOURCES ../src/RxTango.java ../src/RxTangoAttribute.java ../src/RxTangoAttributeChangePublisher.java

import io.reactivex.rxjava3.core.*;
import io.reactivex.rxjava3.functions.*;
import org.tango.client.ez.proxy.*;
import org.tango.client.rx.*;

import java.time.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;

/**
 * Reactive vs Imperative Comparison - Demonstrates advantages of reactive programming
 *
 * This demo shows two approaches to the same task:
 *
 * TASK: Monitor multiple devices and trigger alarms when conditions are met
 *
 * IMPERATIVE APPROACH:
 * - Manual polling with callbacks
 * - Explicit error handling
 * - State management required
 * - Code is imperative and sequential
 *
 * REACTIVE APPROACH:
 * - Automatic event handling
 * - Declarative composition
 * - Backpressure support
 * - Code is declarative and functional
 *
 * Usage:
 *   jbang ReactiveVsImperative.java [reactive|imperative|both]
 *
 * Examples:
 *   jbang ReactiveVsImperative.java reactive    # Show reactive approach
 *   jbang ReactiveVsImperative.java imperative  # Show imperative approach
 *   jbang ReactiveVsImperative.java both        # Show both approaches
 */
public class ReactiveVsImperative {
    private static final String BPM_DEVICE = "SR/BPM1";
    private static final String VACUUM_DEVICE = "SR/VAC1";
    private static final String RADIATION_DEVICE = "SR/RAD1";
    private static final String BEAM_LOSS_DEVICE = "SR/BLD1";

    private static final double VACUUM_THRESHOLD = 1e-6;
    private static final double RADIATION_THRESHOLD = 1.0;
    private static final double BEAM_LOSS_THRESHOLD = 0.1;

    public static void main(String[] args) throws Exception {
        if (args.length == 0) {
            printUsage();
            return;
        }

        switch (args[0].toLowerCase()) {
            case "reactive":
                runReactiveDemo();
                break;
            case "imperative":
                runImperativeDemo();
                break;
            case "both":
                runComparisonDemo();
                break;
            default:
                printUsage();
        }
    }

    private static void printUsage() {
        System.out.println("Reactive vs Imperative Comparison - RxTango Demo");
        System.out.println();
        System.out.println("Usage:");
        System.out.println("  jbang ReactiveVsImperative.java reactive    # Show reactive approach");
        System.out.println("  jbang ReactiveVsImperative.java imperative  # Show imperative approach");
        System.out.println("  jbang ReactiveVsImperative.java both        # Show both approaches");
    }

    /**
     * Run reactive programming demo
     */
    private static void runReactiveDemo() throws Exception {
        System.out.println("=== REACTIVE PROGRAMMING APPROACH ===\n");

        System.out.println("Task: Monitor devices and trigger alarms when conditions are met");
        System.out.println();
        System.out.println("Declarative code - compose operations declaratively:");
        System.out.println();

        // Reactive pipeline
        Disposable subscription = Observable.fromPublisher(
                new RxTangoAttributeChangePublisher<>(
                        TangoProxies.newDeviceProxyWrapper(BPM_DEVICE),
                        "X_Position",
                        TangoEvent.CHANGE
                )
        )
        .map(eventData -> {
            double value = ((Number) eventData.getValue()).doubleValue();
            return new DeviceReading("BPM1", value, "m");
        })
        .filter(reading -> Math.abs(reading.value) > 0.5)
        .map(reading -> {
            reading.value *= 100;
            return reading;
        })
        .distinctUntilChanged()
        .subscribe(
                reading -> System.out.printf("  ✓ %s: %.2f%n", reading.name, reading.value),
                err -> System.err.println("ERROR: " + err.getMessage())
        );

        System.out.println("\n✓ Reactive pipeline active (Ctrl+C to stop)");
        System.out.println("\nAdvantages:");
        System.out.println("  ✓ Declarative - what to do, not how");
        System.out.println("  ✓ Composable - operators chain naturally");
        System.out.println("  ✓ Automatic backpressure handling");
        System.out.println("  ✓ Clean separation of concerns");

        Thread.sleep(5000);
        subscription.dispose();
    }

    /**
     * Run imperative programming demo
     */
    private static void runImperativeDemo() throws Exception {
        System.out.println("\n=== IMPERATIVE PROGRAMMING APPROACH ===\n");

        System.out.println("Task: Monitor devices and trigger alarms when conditions are met");
        System.out.println();
        System.out.println("Imperative code - explicit control flow:");
        System.out.println();

        long startTime = System.currentTimeMillis();
        int alarmCount = 0;

        System.out.println("Polling BPM1 every 500ms...");

        for (int i = 0; i < 10; i++) {
            try {
                // Read BPM
                double bpmValue = (double) TangoProxies.newDeviceProxyWrapper(BPM_DEVICE)
                        .read_attribute("X_Position").get();

                // Read vacuum
                double vacuumValue = (double) TangoProxies.newDeviceProxyWrapper(VACUUM_DEVICE)
                        .read_attribute("Pressure").get();

                // Read radiation
                double radiationValue = (double) TangoProxies.newDeviceProxyWrapper(RADIATION_DEVICE)
                        .read_attribute("DoseRate").get();

                // Read beam loss
                double beamLossValue = (double) TangoProxies.newDeviceProxyWrapper(BEAM_LOSS_DEVICE)
                        .read_attribute("Loss").get();

                // Manual condition checking
                boolean vacuumAlarm = vacuumValue > VACUUM_THRESHOLD;
                boolean radiationAlarm = radiationValue > RADIATION_THRESHOLD;
                boolean beamLossAlarm = beamLossValue > BEAM_LOSS_THRESHOLD;

                LocalDateTime now = LocalDateTime.now();

                if (vacuumAlarm) {
                    System.out.printf("  [%s] 🟠 VACUUM ALARM: %.2e mbar%n",
                            now.toLocalTime(), vacuumValue);
                    alarmCount++;
                }

                if (radiationAlarm) {
                    System.out.printf("  [%s] 🟡 RADIATION ALARM: %.2f mSv/h%n",
                            now.toLocalTime(), radiationValue);
                    alarmCount++;
                }

                if (beamLossAlarm) {
                    System.out.printf("  [%s] 🔴 BEAM LOSS ALARM: %.2f%%%n",
                            now.toLocalTime(), beamLossValue * 100);
                    alarmCount++;
                }

                if (!vacuumAlarm && !radiationAlarm && !beamLossAlarm) {
                    System.out.printf("  [%s] BPM1: %.6f m (OK)%n",
                            now.toLocalTime(), bpmValue);
                }

                Thread.sleep(500);

            } catch (Exception e) {
                System.err.println("ERROR: " + e.getMessage());
            }
        }

        long duration = System.currentTimeMillis() - startTime;

        System.out.println("\n✓ Imperative polling complete");
        System.out.printf("\nResults: %d alarms detected in %.2f seconds%n",
                alarmCount, duration / 1000.0);
        System.out.println("\nDisadvantages:");
        System.out.println("  ✗ Imperative - how to do, not what to do");
        System.out.println("  ✗ No composition - code is sequential");
        System.out.println("  ✗ Manual backpressure required");
        System.out.println("  ✗ State management required");
    }

    /**
     * Run comparison demo
     */
    private static void runComparisonDemo() throws Exception {
        System.out.println("🔬 REACTIVE vs IMPERATIVE COMPARISON");
        System.out.println("====================================\n");

        // Create devices
        createDevices();

        // Run reactive demo
        runReactiveDemo();

        // Run imperative demo
        runImperativeDemo();

        System.out.println("\n=== SUMMARY ===");
        System.out.println();
        System.out.println("Reactive Programming Advantages:");
        System.out.println("  1. Declarative syntax - easier to read and maintain");
        System.out.println("  2. Operator composition - powerful transformations");
        System.out.println("  3. Automatic backpressure - prevents overload");
        System.out.println("  4. Event-driven - responds to changes automatically");
        System.out.println("  5. Functional style - avoids mutable state");
        System.out.println();
        System.out.println("Imperative Programming Disadvantages:");
        System.out.println("  1. Verbose - lots of boilerplate");
        System.out.println("  2. Sequential - hard to compose");
        System.out.println("  3. Manual error handling");
        System.out.println("  4. State management complexity");
        System.out.println("  5. Callback hell in complex scenarios");
    }

    private static void createDevices() throws Exception {
        try {
            TangoProxies.newDeviceProxyWrapper(BPM_DEVICE);
            TangoProxies.newDeviceProxyWrapper(VACUUM_DEVICE);
            TangoProxies.newDeviceProxyWrapper(RADIATION_DEVICE);
            TangoProxies.newDeviceProxyWrapper(BEAM_LOSS_DEVICE);
        } catch (Exception e) {
            // Devices don't exist yet
        }
    }

    static class DeviceReading {
        String name;
        double value;
        String unit;

        DeviceReading(String name, double value, String unit) {
            this.name = name;
            this.value = value;
            this.unit = unit;
        }
    }
}