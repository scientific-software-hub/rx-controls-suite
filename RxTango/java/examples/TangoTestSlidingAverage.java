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

/**
 * Apply a sliding (rolling) average to a stream of Tango attribute readings.
 *
 * buffer(N, 1) emits overlapping windows of exactly N consecutive values,
 * advancing by one sample per tick:
 *
 *   tick 5: [v1, v2, v3, v4, v5]  → mean of window 1
 *   tick 6: [v2, v3, v4, v5, v6]  → mean of window 2
 *   tick 7: [v3, v4, v5, v6, v7]  → mean of window 3
 *
 * Each window is mapped to its mean. The result is a smoothed signal: high-
 * frequency noise averages out while slow trends remain clearly visible.
 * The "delta" column shows how far each raw reading is from its smoothed value.
 *
 * No circular buffer, no index arithmetic, no manual window management —
 * just buffer(N, 1) and a mean calculation.
 *
 * Usage:
 *   jbang TangoTestSlidingAverage.java <device> [window-size] [interval-ms]
 *
 * Example:
 *   jbang TangoTestSlidingAverage.java tango://localhost:10000/sys/tg_test/1 5 400
 */
public class TangoTestSlidingAverage {
    public static void main(String[] args) throws Exception {
        if (args.length < 1) {
            System.err.println("Usage: TangoTestSlidingAverage <device> [window=5] [interval-ms=400]");
            System.exit(1);
        }
        String device     = args[0];
        int    window     = args.length > 1 ? Integer.parseInt(args[1]) : 5;
        long   intervalMs = args.length > 2 ? Long.parseLong(args[2]) : 400L;

        System.out.printf("Sliding average  window=%d  interval=%d ms — Ctrl+C to stop%n", window, intervalMs);
        System.out.printf("(first output after %d samples)%n%n", window);
        System.out.printf("  %-16s  %-18s  %s%n", "raw", "smoothed(n=" + window + ")", "noise (raw - smooth)");
        System.out.println("  " + "-".repeat(62));

        Flowable.interval(intervalMs, TimeUnit.MILLISECONDS)
                // one read per tick
                .flatMapSingle(tick ->
                        Flowable.fromPublisher(new RxTangoAttribute<>(device, "double_scalar"))
                                .firstOrError()
                                .map(v -> ((Number) v).doubleValue())
                )
                // buffer(N, 1): sliding window of size N, step 1.
                // Each emission is a List<Double> containing the last N values.
                // No output until the first full window has accumulated (N ticks).
                .buffer(window, 1)
                // compute window mean; keep the latest raw value for comparison
                .map(buf -> {
                    double sum = 0;
                    for (double x : buf) sum += x;
                    double raw      = buf.get(buf.size() - 1); // most recent sample
                    double smoothed = sum / buf.size();
                    return new double[]{ raw, smoothed };
                })
                .blockingSubscribe(
                        pair -> System.out.printf("  %+16.6f  %+18.6f  %+.6f%n",
                                pair[0], pair[1], pair[0] - pair[1]),
                        err  -> System.err.println("ERROR: " + err.getMessage())
                );
    }
}
