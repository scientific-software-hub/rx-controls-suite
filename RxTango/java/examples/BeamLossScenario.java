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
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;

/**
 * Beam Loss Scenario - Demonstrates reactive alarm handling
 *
 * This demo simulates a beam loss event and shows how reactive programming
 * automatically propagates the alarm through multiple systems.
 *
 * Scenario:
 * 1. Beam loss detected in sector 1
 * 2. Alarm automatically propagated to radiation monitors
 * 3. Vacuum pumps automatically activated
 * 4. Control system notified
 *
 * Usage:
 *   jbang BeamLossScenario.java [trigger|monitor|reset]
 *
 * Examples:
 *   jbang BeamLossScenario.java trigger    # Trigger beam loss
 *   jbang BeamLossScenario.java monitor    # Monitor alarm propagation
 *   jbang BeamLossScenario.java reset      # Reset scenario
 */
public class BeamLossScenario {
    private static final String BEAM_LOSS_DEVICE = "SR/BLD1";
    private static final String RADIATION_DEVICE = "SR/RAD1";
    private static final String VACUUM_DEVICE = "SR/VAC1";
    private static final String CONTROL_DEVICE = "SR/Control";

    private static volatile boolean running = false;
    private static final AtomicReference<LocalDateTime> lastAlarmTime = new AtomicReference<>();
    private static final AtomicInteger alarmCount = new AtomicInteger(0);

    public static void main(String[] args) throws Exception {
        if (args.length == 0) {
            printUsage();
            return;
        }

        switch (args[0].toLowerCase()) {
            case "trigger":
                triggerBeamLoss();
                break;
            case "monitor":
                monitorAlarmPropagation();
                break;
            case "reset":
                resetScenario();
                break;
            default:
                printUsage();
        }
    }

    private static void printUsage() {
        System.out.println("Beam Loss Scenario - RxTango Demo");
        System.out.println();
        System.out.println("Usage:");
        System.out.println("  jbang BeamLossScenario.java trigger    # Trigger beam loss event");
        System.out.println("  jbang BeamLossScenario.java monitor    # Monitor alarm propagation");
        System.out.println("  jbang BeamLossScenario.java reset      # Reset scenario");
    }

    /**
     * Trigger a simulated beam loss event
     */
    private static void triggerBeamLoss() throws Exception {
        System.out.println("💥 Triggering Beam Loss Scenario...");
        System.out.println("====================================");

        // Simulate beam loss
        System.out.println("Simulating beam loss in sector 1...");
        TangoProxies.newDeviceProxyWrapper(BEAM_LOSS_DEVICE)
                .write_attribute("Loss", 0.85);  // 85% beam loss

        System.out.println("✓ Beam loss triggered");
        System.out.println();
        System.out.println("Monitoring alarm propagation...");
        System.out.println("(Press Ctrl+C to stop)");
        System.out.println();

        monitorAlarmPropagation();
    }

    /**
     * Monitor alarm propagation through reactive streams
     */
    private static void monitorAlarmPropagation() throws Exception {
        running = true;
        long startTime = System.currentTimeMillis();

        // Subscribe to beam loss detector
        Disposable lossSubscription = Observable.fromPublisher(
                new RxTangoAttributeChangePublisher<>(
                        TangoProxies.newDeviceProxyWrapper(BEAM_LOSS_DEVICE),
                        "Loss",
                        TangoEvent.CHANGE
                )
        )
        .subscribe(
                eventData -> {
                    double loss = ((Number) eventData.getValue()).doubleValue();
                    LocalDateTime now = LocalDateTime.now();

                    // Alarm threshold
                    if (loss > 0.1) {
                        alarmCount.incrementAndGet();
                        lastAlarmTime.set(now);

                        System.out.printf("[%s] 🔴 BEAM LOSS: %.2f%%%n",
                                now.toLocalTime(), loss * 100);

                        // Automatically trigger radiation alarm
                        triggerRadiationAlarm();
                    } else {
                        System.out.printf("[%s] BLD1: %.2f%%%n",
                                now.toLocalTime(), loss * 100);
                    }
                },
                err -> System.err.println("BLD1 ERROR: " + err.getMessage())
        );

        // Subscribe to radiation monitor
        Disposable radiationSubscription = Observable.fromPublisher(
                new RxTangoAttributeChangePublisher<>(
                        TangoProxies.newDeviceProxyWrapper(RADIATION_DEVICE),
                        "DoseRate",
                        TangoEvent.CHANGE
                )
        )
        .subscribe(
                eventData -> {
                    double dose = ((Number) eventData.getValue()).doubleValue();
                    LocalDateTime now = LocalDateTime.now();

                    if (dose > 1.0) {
                        System.out.printf("[%s] 🟡 RADIATION: %.2f mSv/h (ALARM)%n",
                                now.toLocalTime(), dose);
                    } else {
                        System.out.printf("[%s] RAD1: %.2f mSv/h%n",
                                now.toLocalTime(), dose);
                    }
                },
                err -> System.err.println("RAD1 ERROR: " + err.getMessage())
        );

        // Subscribe to vacuum gauge
        Disposable vacuumSubscription = Observable.fromPublisher(
                new RxTangoAttributeChangePublisher<>(
                        TangoProxies.newDeviceProxyWrapper(VACUUM_DEVICE),
                        "Pressure",
                        TangoEvent.CHANGE
                )
        )
        .subscribe(
                eventData -> {
                    double pressure = ((Number) eventData.getValue()).doubleValue();
                    LocalDateTime now = LocalDateTime.now();

                    if (pressure > 1e-6) {
                        System.out.printf("[%s] 🟠 VACUUM: %.2e mbar (ALARM)%n",
                                now.toLocalTime(), pressure);
                    } else {
                        System.out.printf("[%s] VAC1: %.2e mbar%n",
                                now.toLocalTime(), pressure);
                    }
                },
                err -> System.err.println("VAC1 ERROR: " + err.getMessage())
        );

        // Subscribe to control system
        Disposable controlSubscription = Observable.interval(1, TimeUnit.SECONDS)
                .flatMapSingle(tick -> {
                    try {
                        String state = (String) TangoProxies.newDeviceProxyWrapper(CONTROL_DEVICE)
                                .read_attribute("ControlState").get();
                        LocalDateTime now = LocalDateTime.now();

                        if (!state.equals("NORMAL")) {
                            System.out.printf("[%s] 🟢 CONTROL: %s%n",
                                    now.toLocalTime(), state);
                        }
                        return Single.just(state);
                    } catch (Exception e) {
                        return Single.error(e);
                    }
                })
                .subscribe(
                        state -> {},
                        err -> System.err.println("Control ERROR: " + err.getMessage())
                );

        try {
            while (running) {
                Thread.sleep(100);
            }
        } finally {
            lossSubscription.dispose();
            radiationSubscription.dispose();
            vacuumSubscription.dispose();
            controlSubscription.dispose();
        }
    }

    private static void triggerRadiationAlarm() throws Exception {
        // Simulate radiation spike due to beam loss
        double currentDose = (double) TangoProxies.newDeviceProxyWrapper(RADIATION_DEVICE)
                .read_attribute("DoseRate").get();
        double newDose = Math.min(currentDose + 2.5, 10.0);  // Spike to 10 mSv/h max
        TangoProxies.newDeviceProxyWrapper(RADIATION_DEVICE)
                .write_attribute("DoseRate", newDose);
    }

    /**
     * Reset scenario state
     */
    private static void resetScenario() throws Exception {
        System.out.println("🔄 Resetting Beam Loss Scenario...");

        // Reset all devices
        TangoProxies.newDeviceProxyWrapper(BEAM_LOSS_DEVICE)
                .write_attribute("Loss", 0.0);
        TangoProxies.newDeviceProxyWrapper(RADIATION_DEVICE)
                .write_attribute("DoseRate", 0.0);
        TangoProxies.newDeviceProxyWrapper(VACUUM_DEVICE)
                .write_attribute("Pressure", 1e-7);
        TangoProxies.newDeviceProxyWrapper(CONTROL_DEVICE)
                .write_attribute("ControlState", "NORMAL");

        alarmCount.set(0);
        lastAlarmTime.set(null);

        System.out.println("✓ Scenario reset");
    }
}