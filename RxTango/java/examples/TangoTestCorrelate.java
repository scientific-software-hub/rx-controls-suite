///usr/bin/env jbang "$0" "$@" ; exit $?
//JAVA 11+
//REPOS mavencentral,jtango=https://maven.pkg.github.com/scientific-software-hub/JTango
//DEPS io.reactivex.rxjava3:rxjava:3.1.8
//DEPS org.reactivestreams:reactive-streams:1.0.4
//DEPS org.waltz.tango:ez:1.6.3
//DEPS org.waltz.tango.orb:tangorb:1.6.3
//SOURCES ../src/RxTango.java ../src/RxTangoAttribute.java

import io.reactivex.rxjava3.core.Flowable;
import io.reactivex.rxjava3.core.Single;
import org.tango.client.rx.RxTangoAttribute;

import java.util.concurrent.TimeUnit;

/**
 * Read double_scalar and long_scalar simultaneously on each tick and print
 * both values with their difference.
 *
 * The two reads are issued in parallel by Single.zip — no threads, no futures,
 * no locks. Both values arrive in the same tick, always in sync.
 *
 * Compare with the naive approach: two sequential reads that can be torn by
 * a value update between them.
 *
 * Usage:
 *   jbang TangoTestCorrelate.java <device> [interval-ms]
 *
 * Example:
 *   jbang TangoTestCorrelate.java tango://localhost:10000/sys/tg_test/1 500
 */
public class TangoTestCorrelate {
    public static void main(String[] args) throws Exception {
        if (args.length < 1) {
            System.err.println("Usage: TangoTestCorrelate <device> [interval-ms]");
            System.exit(1);
        }
        String device     = args[0];
        long   intervalMs = args.length > 1 ? Long.parseLong(args[1]) : 500L;

        System.out.printf("%-14s  %-14s  %s%n", "double_scalar", "long_scalar", "difference");
        System.out.println("-".repeat(50));

        Flowable.interval(intervalMs, TimeUnit.MILLISECONDS)
                .flatMapSingle(tick -> Single.zip(
                        // issued in parallel — both reads happen on the same tick
                        Flowable.fromPublisher(new RxTangoAttribute<>(device, "double_scalar"))
                                .firstOrError()
                                .map(v -> ((Number) v).doubleValue()),
                        Flowable.fromPublisher(new RxTangoAttribute<>(device, "long_scalar"))
                                .firstOrError()
                                .map(v -> ((Number) v).longValue()),
                        (d, l) -> String.format("%+14.4f  %14d  %+.4f", d, l, d - l)
                ))
                .blockingSubscribe(
                        System.out::println,
                        err -> System.err.println("ERROR: " + err.getMessage())
                );
    }
}
