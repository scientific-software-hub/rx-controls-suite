///usr/bin/env jbang "$0" "$@" ; exit $?
//JAVA 11+
//REPOS mavencentral,jtango=https://maven.pkg.github.com/scientific-software-hub/JTango
//DEPS io.reactivex.rxjava3:rxjava:3.1.8
//DEPS org.reactivestreams:reactive-streams:1.0.4
//DEPS org.waltz.tango:ez:1.6.3
//DEPS org.waltz.tango.orb:tangorb:1.6.3
//SOURCES ../src/RxTango.java ../src/RxTangoAttribute.java

import io.reactivex.rxjava3.core.Flowable;
import org.tango.client.rx.RxTangoAttribute;

import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Poll a Tango attribute at high frequency but process/display at a lower rate.
 *
 * throttleLast(displayMs) keeps only the LATEST value arriving in each display
 * window and silently discards all earlier ones. The device is still read at
 * the full poll rate — the throttle lives in the Rx chain, not on the network.
 *
 * This is the idiomatic Rx answer to "the device updates faster than I can
 * process": no Thread.sleep, no manual frame-drop counter, no synchronized
 * boolean — one operator.
 *
 * Usage:
 *   jbang TangoTestThrottle.java <device> [poll-ms] [display-ms]
 *
 * Example (poll every 50 ms, display every 1000 ms — 95% drop rate):
 *   jbang TangoTestThrottle.java tango://localhost:10000/sys/tg_test/1 50 1000
 */
public class TangoTestThrottle {
    public static void main(String[] args) throws Exception {
        if (args.length < 1) {
            System.err.println("Usage: TangoTestThrottle <device> [poll-ms=50] [display-ms=1000]");
            System.exit(1);
        }
        String device    = args[0];
        long   pollMs    = args.length > 1 ? Long.parseLong(args[1]) : 50L;
        long   displayMs = args.length > 2 ? Long.parseLong(args[2]) : 1000L;

        AtomicLong polled    = new AtomicLong(0);
        AtomicLong displayed = new AtomicLong(0);

        System.out.printf("Polling every %d ms, displaying every %d ms (%.0f%% drop rate) — Ctrl+C to stop%n%n",
                pollMs, displayMs, (1.0 - (double) pollMs / displayMs) * 100);

        Flowable.interval(pollMs, TimeUnit.MILLISECONDS)
                // read on every tick at full poll rate
                .flatMapSingle(tick ->
                        Flowable.fromPublisher(new RxTangoAttribute<>(device, "double_scalar"))
                                .firstOrError()
                                .map(v -> ((Number) v).doubleValue())
                )
                // count every value arriving from the device
                .doOnNext(v -> polled.incrementAndGet())
                // throttleLast: of all values arriving within each displayMs window,
                // emit only the most recent one. All others are dropped here in the
                // chain — the upstream (device reads) is unaffected.
                .throttleLast(displayMs, TimeUnit.MILLISECONDS)
                .doOnNext(v -> displayed.incrementAndGet())
                .blockingSubscribe(
                        v   -> System.out.printf("  %+.6f   (polled %3d, displayed %3d)%n",
                                v, polled.get(), displayed.get()),
                        err -> System.err.println("ERROR: " + err.getMessage())
                );
    }
}
