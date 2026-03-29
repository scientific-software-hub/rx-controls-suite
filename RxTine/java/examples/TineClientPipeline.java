///usr/bin/env jbang "$0" "$@" ; exit $?
//JAVA 11+
//DEPS io.reactivex.rxjava3:rxjava:3.1.8
//DEPS org.reactivestreams:reactive-streams:1.0.4
//DEPS de.desy.tine:tine:5.3
//SOURCES ../src/RxTine.java ../src/RxTineRead.java ../src/RxTineWrite.java ../src/TineClient.java

import org.tine.client.rx.TineClient;

/**
 * Fluent TineClient pipeline: read → calibrate → write → read-back.
 *
 * Each step's result feeds directly into the next.
 * No threads. No callbacks. No intermediate variables.
 *
 * Usage:
 *   jbang TineClientPipeline.java <device>
 *
 * Example:
 *   jbang TineClientPipeline.java /TEST/JSINESRV/SINEDEV_0@jsinesrv
 */
public class TineClientPipeline {
    public static void main(String[] args) throws Exception {
        if (args.length < 1) {
            System.err.println("Usage: TineClientPipeline <device>");
            System.exit(1);
        }
        String device = args[0];

        Object result = new TineClient()

                // 1. read current sine value
                .read(device, "Sine")
                .map(v -> { System.out.printf("  [1] read    Sine       =  %s%n", v); return v; })

                // 2. derive new amplitude from sine (abs + scale) — no I/O
                .map(v -> Math.abs(((Number) v).doubleValue()) * 2.0 + 1.5)
                .map(v -> { System.out.printf("  [2] new Amplitude      =  %s%n", v); return v; })

                // 3. write new amplitude
                .write(device, "Amplitude")
                .map(v -> { System.out.printf("  [3] wrote  Amplitude   =  %s%n", v); return v; })

                // 4. read back to confirm what the device actually has
                .read(device, "Amplitude")

                .blockingGet();

        System.out.printf("%n  Pipeline complete.%n  Confirmed on device: %s%n", result);
    }
}
