///usr/bin/env jbang "$0" "$@" ; exit $?
//JAVA 11+
//REPOS mavencentral,jtango=https://maven.pkg.github.com/scientific-software-hub/JTango
//DEPS io.reactivex.rxjava3:rxjava:3.1.8
//DEPS org.reactivestreams:reactive-streams:1.0.4
//DEPS org.waltz.tango:ez:1.6.3
//DEPS org.waltz.tango.orb:tangorb:1.6.3
//SOURCES ../src/RxTango.java ../src/RxTangoAttribute.java ../src/RxTangoAttributeWrite.java
//SOURCES ../src/RxTangoCommand.java ../src/TangoClient.java

import org.tango.client.rx.TangoClient;

/**
 * Demonstrates the TangoClient fluent pipeline on TangoTest.
 *
 * The pipeline:
 *   1. Read   double_scalar   — raw sensor value
 *   2. Run    DevDouble       — round-trip through the device (proves the value
 *                               physically traveled to the device and back)
 *   3. Map    |x| * 2 + 1.5  — apply calibration in client
 *   4. Run    DevString       — format the calibrated double as a string
 *                               via another device command
 *   5. Write  string_scalar   — store the result (string_scalar holds its value)
 *   6. Read   string_scalar   — read back to confirm what is on the device
 *
 * Each step's result feeds directly into the next.
 * No threads. No callbacks. No intermediate variables.
 *
 * Usage:
 *   jbang TangoTestPipeline.java <device>
 *
 * Example:
 *   jbang TangoTestPipeline.java tango://localhost:10000/sys/tg_test/1
 */
public class TangoTestPipeline {
    public static void main(String[] args) throws Exception {
        if (args.length < 1) {
            System.err.println("Usage: TangoTestPipeline <device>");
            System.exit(1);
        }
        String device = args[0];

        Object result = new TangoClient()

                // 1. read raw sensor value
                .readAttribute(device, "double_scalar")
                .map(v -> { System.out.printf("  [1] read    double_scalar  =  %s%n", v); return v; })

                // 2. round-trip through device (DevDouble echoes the input)
                .executeCommand(device, "DevDouble", v -> v)
                .map(v -> { System.out.printf("  [2] DevDouble returned     =  %s%n", v); return v; })

                // 3. apply calibration
                .map(v -> Math.abs(((Number) v).doubleValue()) * 2.0 + 1.5)
                .map(v -> { System.out.printf("  [3] calibrated             =  %s%n", v); return v; })

                // 4. format as string via device command (cross-type step)
                .executeCommand(device, "DevString", v -> String.format("calibrated=%.4f", v))
                .map(v -> { System.out.printf("  [4] DevString returned     =  %s%n", v); return v; })

                // 5. write to string_scalar (persists on TangoTest)
                .writeAttribute(device, "string_scalar", v -> v)
                .map(v -> { System.out.printf("  [5] wrote   string_scalar  =  %s%n", v); return v; })

                // 6. read back to confirm
                .readAttribute(device, "string_scalar")

                .blockingGet();

        System.out.printf("%n  Pipeline complete.%n  Confirmed on device: \"%s\"%n", result);
    }
}
