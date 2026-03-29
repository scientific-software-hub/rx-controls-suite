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

/**
 * Read one or more attributes from a Tango device and print the values.
 *
 * Usage:
 *   jbang ReadAttribute.java <device-url> <attr> [<attr2> ...]
 *
 * Example:
 *   jbang ReadAttribute.java tango://localhost:10000/sys/tg_test/1 double_scalar long_scalar
 */
public class ReadAttribute {
    public static void main(String[] args) throws Exception {
        if (args.length < 2) {
            System.err.println("Usage: ReadAttribute <device-url> <attribute> [<attribute2> ...]");
            System.exit(1);
        }

        String device = args[0];
        for (int i = 1; i < args.length; i++) {
            String attr = args[i];
            Flowable.fromPublisher(new RxTangoAttribute<>(device, attr))
                    .blockingSubscribe(
                            value -> System.out.println(attr + " = " + value),
                            err   -> System.err.println(attr + " ERROR: " + err.getMessage())
                    );
        }
    }
}
