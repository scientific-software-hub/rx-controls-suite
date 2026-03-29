///usr/bin/env jbang "$0" "$@" ; exit $?
//JAVA 11+
//REPOS mavencentral,jtango=https://maven.pkg.github.com/scientific-software-hub/JTango
//DEPS io.reactivex.rxjava3:rxjava:3.1.8
//DEPS org.reactivestreams:reactive-streams:1.0.4
//DEPS org.waltz.tango:ez:1.6.3
//DEPS org.waltz.tango.orb:tangorb:1.6.3
//SOURCES ../src/RxTango.java ../src/RxTangoAttribute.java ../src/RxTangoAttributeWrite.java

import io.reactivex.rxjava3.core.Flowable;
import io.reactivex.rxjava3.core.Single;
import org.tango.client.rx.RxTangoAttribute;
import org.tango.client.rx.RxTangoAttributeWrite;

import java.util.concurrent.TimeUnit;

/**
 * Read-transform-write pipeline: reads a source attribute, applies a linear
 * calibration (gain * value + offset), and writes the result to a destination
 * attribute — all expressed as a single Rx chain.
 *
 * Demonstrates how Rx turns a multi-step, error-prone imperative sequence into
 * a composable, readable pipeline with no manual thread management.
 *
 * Usage:
 *   jbang CalibrationPipeline.java \
 *       <src-device> <src-attr> \
 *       <dst-device> <dst-attr> \
 *       <gain> <offset> [<interval-ms>]
 *
 * Example (TangoTest double_scalar → scale × 2 + 10 → double_scalar_w, every 1 s):
 *   jbang CalibrationPipeline.java \
 *       tango://localhost:10000/sys/tg_test/1 double_scalar \
 *       tango://localhost:10000/sys/tg_test/1 double_scalar_w \
 *       2.0 10.0 1000
 */
public class CalibrationPipeline {
    public static void main(String[] args) throws Exception {
        if (args.length < 6) {
            System.err.println("Usage: CalibrationPipeline " +
                    "<src-device> <src-attr> <dst-device> <dst-attr> <gain> <offset> [interval-ms]");
            System.exit(1);
        }

        String srcDevice = args[0], srcAttr = args[1];
        String dstDevice = args[2], dstAttr = args[3];
        double gain      = Double.parseDouble(args[4]);
        double offset    = Double.parseDouble(args[5]);
        long   intervalMs = args.length > 6 ? Long.parseLong(args[6]) : 1000L;

        System.out.printf("Pipeline: %s/%s  →  (× %.2f + %.2f)  →  %s/%s  every %d ms%n",
                srcDevice, srcAttr, gain, offset, dstDevice, dstAttr, intervalMs);
        System.out.println("Ctrl+C to stop");

        Flowable.interval(intervalMs, TimeUnit.MILLISECONDS)
                // 1. read
                .flatMapSingle(tick ->
                        Flowable.fromPublisher(new RxTangoAttribute<>(srcDevice, srcAttr))
                                .firstOrError()
                                .map(raw -> ((Number) raw).doubleValue())
                )
                // 2. transform
                .map(raw -> raw * gain + offset)
                // 3. write
                .flatMapSingle(calibrated ->
                        Flowable.fromPublisher(new RxTangoAttributeWrite<>(dstDevice, dstAttr, calibrated))
                                .ignoreElements()
                                .andThen(Single.just(calibrated))
                )
                // 4. confirm
                .blockingSubscribe(
                        v   -> System.out.printf("[%d]  wrote  %.6f  →  %s/%s%n",
                                System.currentTimeMillis(), v, dstDevice, dstAttr),
                        err -> System.err.println("ERROR: " + err.getMessage())
                );
    }
}
