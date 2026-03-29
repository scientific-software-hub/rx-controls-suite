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

import java.util.List;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * Collect N samples of double_scalar at a fixed rate and compute statistics.
 *
 * No loop. No counter. No list management. The Rx chain handles all of it:
 *   interval → take(N) → read each tick → collect → reduce to stats
 *
 * Usage:
 *   jbang TangoTestStats.java <device> [samples] [interval-ms]
 *
 * Example:
 *   jbang TangoTestStats.java tango://localhost:10000/sys/tg_test/1
 *   jbang TangoTestStats.java tango://localhost:10000/sys/tg_test/1 50 500
 */
public class TangoTestStats {
    public static void main(String[] args) throws Exception {
        if (args.length < 1) {
            System.err.println("Usage: TangoTestStats <device> [samples] [interval-ms]");
            System.exit(1);
        }
        String device     = args[0];
        int    n          = args.length > 1 ? Integer.parseInt(args[1]) : 20;
        long   intervalMs = args.length > 2 ? Long.parseLong(args[2]) : 500L;

        System.out.printf("Collecting %d samples of double_scalar @ %d ms intervals...%n%n", n, intervalMs);

        AtomicInteger counter = new AtomicInteger(0);

        List<Double> samples = Flowable.interval(intervalMs, TimeUnit.MILLISECONDS)
                .take(n)
                .flatMapSingle(tick ->
                        Flowable.fromPublisher(new RxTangoAttribute<>(device, "double_scalar"))
                                .firstOrError()
                                .map(v -> ((Number) v).doubleValue())
                )
                .doOnNext(v -> System.out.printf("  [%2d]  %+.6f%n", counter.incrementAndGet(), v))
                .toList()
                .blockingGet();

        double sum = 0, sumSq = 0, min = Double.MAX_VALUE, max = -Double.MAX_VALUE;
        for (double x : samples) {
            sum += x;
            sumSq += x * x;
            if (x < min) min = x;
            if (x > max) max = x;
        }
        double mean   = sum / n;
        double stddev = Math.sqrt(Math.max(0.0, sumSq / n - mean * mean));

        System.out.printf("%n  n      = %d%n", n);
        System.out.printf("  min    = %+.6f%n", min);
        System.out.printf("  max    = %+.6f%n", max);
        System.out.printf("  mean   = %+.6f%n", mean);
        System.out.printf("  stddev = %.6f%n",  stddev);
    }
}
