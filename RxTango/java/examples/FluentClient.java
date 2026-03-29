///usr/bin/env jbang "$0" "$@" ; exit $?
//JAVA 11+
//REPOS mavencentral,jtango=https://maven.pkg.github.com/scientific-software-hub/JTango
//DEPS io.reactivex.rxjava3:rxjava:3.1.8
//DEPS org.reactivestreams:reactive-streams:1.0.4
//DEPS org.waltz.tango:ez:1.6.3
//DEPS org.waltz.tango.orb:tangorb:1.6.3
//SOURCES ../src/RxTango.java ../src/RxTangoAttribute.java ../src/RxTangoAttributeWrite.java
//SOURCES ../src/RxTangoCommand.java ../src/TangoClient.java

/**
 * Demonstrates the TangoClient fluent builder.
 *
 * Usage:
 *   jbang FluentClient.java <device-url>
 *
 * Example:
 *   jbang FluentClient.java tango://localhost:10000/sys/tg_test/1
 */
public class FluentClient {
    public static void main(String[] args) throws Exception {
        if (args.length < 1) {
            System.err.println("Usage: FluentClient <device-url>");
            System.exit(1);
        }

        String device = args[0];

        // ── Demo 1: simple read ───────────────────────────────────────────────
        System.out.println("── Demo 1: read ─────────────────────────────");
        Object value = new org.tango.client.rx.TangoClient()
                .readAttribute(device, "double_scalar")
                .blockingGet();
        System.out.println("double_scalar = " + value);

        // ── Demo 2: read → transform → write back ────────────────────────────
        System.out.println("\n── Demo 2: read → calibrate → write ─────────");
        new org.tango.client.rx.TangoClient()
                .readAttribute(device, "double_scalar")
                .map(v -> ((Number) v).doubleValue() * 2.0 + 10.0)
                .writeAttribute(device, "double_scalar_w", v -> v)
                .subscribe(
                        result -> System.out.println("calibrated and wrote: " + result),
                        err    -> System.err.println("ERROR: " + err.getMessage())
                );

        Thread.sleep(500); // let async subscribe finish before next demo

        // ── Demo 3: multi-step cross-device pipeline ──────────────────────────
        // Each step feeds its result to the next.
        // (Using the same device here since we only have one TangoTest,
        //  but device1/device2/device3 can all be different.)
        System.out.println("\n── Demo 3: command → read → write (pipeline) ─");
        Object finalResult = new org.tango.client.rx.TangoClient()
                .executeCommand(device, "State")
                .readAttribute(device, "double_scalar")
                .writeAttribute(device, "double_scalar_w",
                        v -> ((Number) v).doubleValue() * -1.0)  // negate
                .blockingGet();
        System.out.println("pipeline complete, last written value: " + finalResult);
    }
}
