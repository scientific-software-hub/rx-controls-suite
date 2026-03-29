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
 * Live streaming statistics using scan() — O(1) memory, no batch, no waiting.
 *
 * scan() is the streaming counterpart of reduce(). Where reduce() waits for
 * the stream to complete and emits one final result, scan() emits the running
 * accumulation after EVERY new value:
 *
 *   v1 → Stats(n=1, mean=v1, ...)
 *   v2 → Stats(n=2, mean=(v1+v2)/2, ...)
 *   v3 → Stats(n=3, ...)
 *
 * Compare with TangoTestStats: that script collects N samples into a List,
 * then computes once and exits. This one runs indefinitely, never allocates
 * a growing list, and always shows current statistics.
 *
 * Uses Welford's online algorithm for numerically stable mean and variance —
 * avoids catastrophic cancellation that naive sum-of-squares suffers with
 * large values.
 *
 * Usage:
 *   jbang TangoTestRunningStats.java <device> [interval-ms]
 *
 * Example:
 *   jbang TangoTestRunningStats.java tango://localhost:10000/sys/tg_test/1 500
 */
public class TangoTestRunningStats {

    /**
     * Immutable accumulator updated by scan() on each new value.
     * Welford's online algorithm: maintains mean and M2 (sum of squared
     * deviations from the current mean) for O(1) stable stddev.
     */
    record Stats(long n, double latest, double min, double max, double mean, double m2) {
        static Stats update(Stats s, double x) {
            long   n      = s.n + 1;
            double delta  = x - s.mean;
            double mean   = s.mean + delta / n;          // running mean
            double delta2 = x - mean;
            double m2     = s.m2 + delta * delta2;       // Welford M2 accumulator
            return new Stats(n, x, Math.min(s.min, x), Math.max(s.max, x), mean, m2);
        }

        // sample stddev: sqrt(M2 / (n-1)); 0 for n<=1
        double stddev() { return n > 1 ? Math.sqrt(m2 / (n - 1)) : 0.0; }

        static Stats zero() {
            return new Stats(0, 0.0, Double.MAX_VALUE, -Double.MAX_VALUE, 0.0, 0.0);
        }
    }

    public static void main(String[] args) throws Exception {
        if (args.length < 1) {
            System.err.println("Usage: TangoTestRunningStats <device> [interval-ms=500]");
            System.exit(1);
        }
        String device     = args[0];
        long   intervalMs = args.length > 1 ? Long.parseLong(args[1]) : 500L;

        System.out.printf("Live statistics  interval=%d ms — Ctrl+C to stop%n%n", intervalMs);
        System.out.printf("  %5s  %+14s  %+14s  %+14s  %+14s  %14s%n",
                "n", "latest", "mean", "min", "max", "stddev");
        System.out.println("  " + "-".repeat(82));

        Flowable.interval(intervalMs, TimeUnit.MILLISECONDS)
                // read one sample per tick
                .flatMapSingle(tick ->
                        Flowable.fromPublisher(new RxTangoAttribute<>(device, "double_scalar"))
                                .firstOrError()
                                .map(v -> ((Number) v).doubleValue())
                )
                // scan() folds each value into the running Stats accumulator and
                // emits a new Stats after every single sample — unlike reduce()
                // which only emits when the stream completes.
                .scan(Stats.zero(), Stats::update)
                // skip the seed (n=0) emitted before any real data arrives
                .filter(s -> s.n() > 0)
                .blockingSubscribe(
                        s   -> System.out.printf("  %5d  %+14.6f  %+14.6f  %+14.6f  %+14.6f  %14.6f%n",
                                s.n(), s.latest(), s.mean(), s.min(), s.max(), s.stddev()),
                        err -> System.err.println("ERROR: " + err.getMessage())
                );
    }
}
