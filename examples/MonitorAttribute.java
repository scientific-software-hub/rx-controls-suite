///usr/bin/env jbang "$0" "$@" ; exit $?
//JAVA 11+
//REPOS mavencentral,jtango=https://maven.pkg.github.com/scientific-software-hub/JTango
//DEPS io.reactivex.rxjava3:rxjava:3.1.8
//DEPS org.reactivestreams:reactive-streams:1.0.4
//DEPS org.waltz.tango:ez:1.6.3
//DEPS org.waltz.tango.orb:tangorb:1.6.3
//SOURCES ../src/RxTango.java ../src/RxTangoAttributeChangePublisher.java

import io.reactivex.rxjava3.core.Observable;
import org.tango.client.ez.proxy.TangoEvent;
import org.tango.client.ez.proxy.TangoProxies;
import org.tango.client.ez.proxy.TangoProxy;
import org.tango.client.rx.RxTangoAttributeChangePublisher;

/**
 * Subscribe to Tango CHANGE events on an attribute and print each update.
 * Supports optional event type override (CHANGE, PERIODIC, ARCHIVE).
 *
 * Usage:
 *   jbang MonitorAttribute.java <device-url> <attribute> [CHANGE|PERIODIC|ARCHIVE]
 *
 * Examples:
 *   jbang MonitorAttribute.java tango://localhost:10000/sys/tg_test/1 State
 *   jbang MonitorAttribute.java tango://localhost:10000/sys/tg_test/1 double_scalar PERIODIC
 */
public class MonitorAttribute {
    public static void main(String[] args) throws Exception {
        if (args.length < 2) {
            System.err.println("Usage: MonitorAttribute <device-url> <attribute> [CHANGE|PERIODIC|ARCHIVE]");
            System.exit(1);
        }

        String device    = args[0];
        String attribute = args[1];
        TangoEvent event = args.length > 2 ? TangoEvent.valueOf(args[2]) : TangoEvent.CHANGE;

        TangoProxy proxy = TangoProxies.newDeviceProxyWrapper(device);

        System.out.printf("Monitoring %s/%s [%s events] — Ctrl+C to stop%n", device, attribute, event);

        Observable.fromPublisher(new RxTangoAttributeChangePublisher<>(proxy, attribute, event))
                .subscribe(
                        eventData -> System.out.printf("[%d] %s%n", eventData.getTime(), eventData.getValue()),
                        err       -> System.err.println("ERROR: " + err.getMessage())
                );

        Thread.currentThread().join(); // keep alive until Ctrl+C
    }
}
