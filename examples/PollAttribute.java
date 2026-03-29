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
 * Poll a Tango attribute on a fixed interval and stream the values.
 * No events or polling configuration required on the device side.
 *
 * Usage:
 *   jbang PollAttribute.java <device-url> <attribute> [interval-ms]
 *
 * Examples:
 *   jbang PollAttribute.java tango://localhost:10000/sys/tg_test/1 State
 *   jbang PollAttribute.java tango://localhost:10000/sys/tg_test/1 double_scalar 500
 */
public class PollAttribute {
    public static void main(String[] args) throws Exception {
        if (args.length < 2) {
            System.err.println("Usage: PollAttribute <device-url> <attribute> [interval-ms]");
            System.exit(1);
        }

        String device      = args[0];
        String attribute   = args[1];
        long   intervalMs  = args.length > 2 ? Long.parseLong(args[2]) : 1000L;

        System.out.printf("Polling %s/%s every %d ms — Ctrl+C to stop%n", device, attribute, intervalMs);

        Flowable.interval(intervalMs, TimeUnit.MILLISECONDS)
                .flatMapSingle(tick ->
                        Flowable.fromPublisher(new RxTangoAttribute<>(device, attribute))
                                .firstOrError()
                )
                .blockingSubscribe(
                        value -> System.out.printf("[%d] %s%n", System.currentTimeMillis(), value),
                        err   -> System.err.println("ERROR: " + err.getMessage())
                );
    }
}
