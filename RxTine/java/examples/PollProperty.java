///usr/bin/env jbang "$0" "$@" ; exit $?
//JAVA 11+
//DEPS io.reactivex.rxjava3:rxjava:3.1.8
//DEPS org.reactivestreams:reactive-streams:1.0.4
//DEPS de.desy.tine:tine:5.3
//SOURCES ../src/RxTine.java ../src/RxTineRead.java

import io.reactivex.rxjava3.core.Flowable;
import org.tine.client.rx.RxTineRead;

import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Poll a TINE property on a fixed interval and stream the values.
 *
 * Usage:
 *   jbang PollProperty.java <device> <property> [interval-ms]
 *
 * Example:
 *   jbang PollProperty.java /TEST/JSINESRV/SINEDEV_0@jsinesrv Sine 500
 */
public class PollProperty {
    public static void main(String[] args) throws Exception {
        if (args.length < 2) {
            System.err.println("Usage: PollProperty <device> <property> [interval-ms=500]");
            System.exit(1);
        }

        String device     = args[0];
        String property   = args[1];
        long   intervalMs = args.length > 2 ? Long.parseLong(args[2]) : 500L;

        System.out.printf("Polling %s/%s every %d ms — Ctrl+C to stop%n",
                device, property, intervalMs);

        AtomicLong tick = new AtomicLong(0);

        Flowable.interval(intervalMs, TimeUnit.MILLISECONDS)
                .flatMapSingle(__ ->
                        Flowable.fromPublisher(RxTineRead.ofDouble(device, property))
                                .firstOrError()
                )
                .blockingSubscribe(
                        v   -> System.out.printf("[%4d]  %+.6f%n", tick.incrementAndGet(), v),
                        err -> System.err.println("ERROR: " + err.getMessage())
                );
    }
}
