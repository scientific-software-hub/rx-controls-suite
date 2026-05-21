///usr/bin/env jbang "$0" "$@" ; exit $?
//JAVA 11+
//REPOS mavencentral,jtango=https://maven.pkg.github.com/scientific-software-hub/JTango
//DEPS io.reactivex.rxjava3:rxjava:3.1.8
//DEPS org.reactivestreams:reactive-streams:1.0.4
//DEPS org.waltz.tango:ez:1.6.3
//DEPS org.waltz.tango.orb:tangorb:1.6.3
//SOURCES ../lib/RingDevices.java ../../java/src/RxTango.java ../../java/src/RxTangoAttribute.java ../../java/src/RxTangoAttributeWrite.java

import java.util.Locale;

public class SetStorageRingScenario {
    public static void main(String[] args) {
        String controller = RingDevices.DEFAULT_CONTROLLER;
        String scenario = args.length > 0 ? args[0] : "nominal";
        long scenarioId = parseScenario(scenario);

        RingDevices.writeScenario(controller, scenarioId)
                .blockingSubscribe(
                        written -> System.out.printf(Locale.ROOT,
                                "Scenario set to %d (%s) on %s%n",
                                written,
                                describeScenario(written),
                                controller),
                        err -> System.err.println("Fatal: " + err.getMessage())
                );
    }

    private static long parseScenario(String value) {
        String normalized = value.trim().toLowerCase(Locale.ROOT);
        return switch (normalized) {
            case "0", "nominal" -> 0L;
            case "1", "orbit", "orbit_drift" -> 1L;
            case "2", "vacuum", "vacuum_burst" -> 2L;
            case "3", "loss", "beam_loss" -> 3L;
            default -> throw new IllegalArgumentException(
                    "Unsupported scenario: " + value + ". Use nominal|orbit_drift|vacuum_burst|beam_loss");
        };
    }

    private static String describeScenario(long scenarioId) {
        return switch ((int) scenarioId) {
            case 0 -> "nominal";
            case 1 -> "orbit_drift";
            case 2 -> "vacuum_burst";
            case 3 -> "beam_loss";
            default -> "unknown";
        };
    }
}
