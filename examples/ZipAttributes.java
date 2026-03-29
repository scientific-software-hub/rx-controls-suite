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
 * Poll two attributes from two (possibly different) devices on a fixed interval,
 * zip the latest values, and print them as a pair.
 *
 * This demo shows the core Rx value proposition: combining data from multiple
 * heterogeneous sources with a single expression.
 *
 * Usage:
 *   jbang ZipAttributes.java <device1> <attr1> <device2> <attr2> [interval-ms]
 *
 * Examples:
 *   # Same device, two attributes, default 1 s interval
 *   jbang ZipAttributes.java \
 *       tango://localhost:10000/sys/tg_test/1 double_scalar \
 *       tango://localhost:10000/sys/tg_test/1 long_scalar
 *
 *   # Two different devices, 500 ms interval
 *   jbang ZipAttributes.java \
 *       tango://host1:10000/domain/family/1 temperature \
 *       tango://host2:10000/domain/family/2 pressure \
 *       500
 */
public class ZipAttributes {
    public static void main(String[] args) throws Exception {
        if (args.length < 4) {
            System.err.println("Usage: ZipAttributes <device1> <attr1> <device2> <attr2> [interval-ms]");
            System.exit(1);
        }

        String device1 = args[0], attr1 = args[1];
        String device2 = args[2], attr2 = args[3];
        long   intervalMs = args.length > 4 ? Long.parseLong(args[4]) : 1000L;

        System.out.printf("Zipping %s/%s + %s/%s every %d ms — Ctrl+C to stop%n",
                device1, attr1, device2, attr2, intervalMs);

        Flowable.interval(intervalMs, TimeUnit.MILLISECONDS)
                .flatMapSingle(tick -> Single.zip(
                        Flowable.fromPublisher(new RxTangoAttribute<>(device1, attr1)).firstOrError(),
                        Flowable.fromPublisher(new RxTangoAttribute<>(device2, attr2)).firstOrError(),
                        (v1, v2) -> String.format("[%d] %s=%s  |  %s=%s",
                                System.currentTimeMillis(), attr1, v1, attr2, v2)
                ))
                .blockingSubscribe(
                        System.out::println,
                        err -> System.err.println("ERROR: " + err.getMessage())
                );
    }
}
