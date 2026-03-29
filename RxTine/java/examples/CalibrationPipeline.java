///usr/bin/env jbang "$0" "$@" ; exit $?
//JAVA 11+
//DEPS io.reactivex.rxjava3:rxjava:3.1.8
//DEPS org.reactivestreams:reactive-streams:1.0.4
//DEPS de.desy.tine:tine:4.4
//SOURCES ../src/RxTine.java ../src/RxTineRead.java ../src/RxTineWrite.java

import io.reactivex.rxjava3.core.Flowable;
import io.reactivex.rxjava3.core.Single;
import org.tine.client.rx.RxTineRead;
import org.tine.client.rx.RxTineWrite;

import java.util.concurrent.TimeUnit;

/**
 * Continuous read-calibrate-write pipeline on TINE properties.
 *
 *   interval → read source → (gain * value + offset) → write destination
 *
 * Usage:
 *   jbang CalibrationPipeline.java \
 *       <src-device> <src-property> \
 *       <dst-device> <dst-property> \
 *       <gain> <offset> [interval-ms]
 *
 * Example:
 *   jbang CalibrationPipeline.java \
 *       /HERA/Context/DeviceA SENSOR \
 *       /HERA/Context/DeviceB SETPOINT \
 *       2.0 10.0 1000
 */
public class CalibrationPipeline {
    public static void main(String[] args) throws Exception {
        if (args.length < 6) {
            System.err.println("Usage: CalibrationPipeline " +
                    "<src-dev> <src-prop> <dst-dev> <dst-prop> <gain> <offset> [interval-ms=1000]");
            System.exit(1);
        }

        String srcDevice   = args[0], srcProp = args[1];
        String dstDevice   = args[2], dstProp = args[3];
        double gain        = Double.parseDouble(args[4]);
        double offset      = Double.parseDouble(args[5]);
        long   intervalMs  = args.length > 6 ? Long.parseLong(args[6]) : 1000L;

        System.out.printf("Pipeline: %s/%s → (×%.2f +%.2f) → %s/%s every %d ms%n",
                srcDevice, srcProp, gain, offset, dstDevice, dstProp, intervalMs);
        System.out.println("Ctrl+C to stop");

        Flowable.interval(intervalMs, TimeUnit.MILLISECONDS)
                // Step 1: read
                .flatMapSingle(__ ->
                        Flowable.fromPublisher(RxTineRead.ofDouble(srcDevice, srcProp))
                                .firstOrError()
                )
                // Step 2: calibrate
                .map(raw -> raw * gain + offset)
                // Step 3: write and pass value downstream
                .flatMapSingle(calibrated ->
                        Flowable.fromPublisher(RxTineWrite.ofDouble(dstDevice, dstProp, calibrated))
                                .firstOrError()
                )
                .blockingSubscribe(
                        v   -> System.out.printf("[%d]  wrote %.6f → %s/%s%n",
                                System.currentTimeMillis(), v, dstDevice, dstProp),
                        err -> System.err.println("ERROR: " + err.getMessage())
                );
    }
}
