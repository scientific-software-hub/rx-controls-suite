///usr/bin/env jbang "$0" "$@" ; exit $?
//JAVA 11+
//DEPS io.reactivex.rxjava3:rxjava:3.1.8
//DEPS org.reactivestreams:reactive-streams:1.0.4
//DEPS de.desy.tine:tine:4.4
//SOURCES ../src/RxTine.java ../src/RxTineMonitor.java

import io.reactivex.rxjava3.core.Flowable;
import org.tine.client.rx.RxTineMonitor;

/**
 * Subscribe to a TINE CM_POLL monitor and stream values to stdout.
 *
 * Unlike PollProperty (which creates a new TLink on every tick), this example
 * uses RxTineMonitor which keeps a single attached TLink alive and delivers
 * values via a callback — the TINE-native push model.
 *
 * Usage:
 *   jbang MonitorProperty.java <device> <property> [interval-ms]
 *
 * Example:
 *   jbang MonitorProperty.java /HERA/Context/Device SENSOR 500
 */
public class MonitorProperty {
    public static void main(String[] args) throws Exception {
        if (args.length < 2) {
            System.err.println("Usage: MonitorProperty <device> <property> [interval-ms=500]");
            System.exit(1);
        }

        String device     = args[0];
        String property   = args[1];
        int    intervalMs = args.length > 2 ? Integer.parseInt(args[2]) : 500;

        System.out.printf("Monitoring %s/%s (CM_POLL %d ms) — Ctrl+C to stop%n",
                device, property, intervalMs);

        RxTineMonitor<Double> monitor = RxTineMonitor.ofDouble(device, property, intervalMs);

        Flowable.fromPublisher(monitor)
                .subscribe(
                        v   -> System.out.printf("[%d]  %+.6f%n",
                                System.currentTimeMillis(), v),
                        err -> System.err.println("ERROR: " + err.getMessage())
                );

        Runtime.getRuntime().addShutdownHook(new Thread(monitor::close));
        Thread.currentThread().join();
    }
}
