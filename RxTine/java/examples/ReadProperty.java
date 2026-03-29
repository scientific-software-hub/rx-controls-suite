///usr/bin/env jbang "$0" "$@" ; exit $?
//JAVA 11+
//DEPS io.reactivex.rxjava3:rxjava:3.1.8
//DEPS org.reactivestreams:reactive-streams:1.0.4
//DEPS de.desy.tine:tine:4.4         <-- adjust version; install jar in ~/.m2 if not on Central
//SOURCES ../src/RxTine.java ../src/RxTineRead.java

import io.reactivex.rxjava3.core.Flowable;
import org.tine.client.rx.RxTineRead;

/**
 * Read one or more TINE properties and print the values.
 *
 * Usage:
 *   jbang ReadProperty.java <device> <property> [<property2> ...]
 *
 * Example:
 *   jbang ReadProperty.java /TEST/JSINESRV/SINEDEV_0@jsinesrv Sine Amplitude
 */
public class ReadProperty {
    public static void main(String[] args) throws Exception {
        if (args.length < 2) {
            System.err.println("Usage: ReadProperty <device> <property> [<property2> ...]");
            System.exit(1);
        }

        String device = args[0];
        for (int i = 1; i < args.length; i++) {
            String property = args[i];
            Flowable.fromPublisher(RxTineRead.ofDouble(device, property))
                    .blockingSubscribe(
                            value -> System.out.printf("%s/%s = %.6f%n", device, property, value),
                            err   -> System.err.printf("%s/%s ERROR: %s%n",
                                    device, property, err.getMessage())
                    );
        }
    }
}
