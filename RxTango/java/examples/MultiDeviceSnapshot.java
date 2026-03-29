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

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.TimeUnit;

/**
 * Read attributes from multiple devices IN PARALLEL and print a combined snapshot.
 *
 * All reads are issued concurrently via flatMapSingle — no threads, no locks,
 * no CountDownLatch. The snapshot is only printed once ALL reads complete.
 *
 * Usage (one-shot):
 *   jbang MultiDeviceSnapshot.java <device> <attr> [<device> <attr> ...]
 *
 * Usage (continuous, repeat every N ms):
 *   jbang MultiDeviceSnapshot.java <interval-ms> <device> <attr> [<device> <attr> ...]
 *
 * Examples:
 *   jbang MultiDeviceSnapshot.java \
 *       tango://localhost:10000/sys/tg_test/1 double_scalar \
 *       tango://localhost:10000/sys/tg_test/1 long_scalar \
 *       tango://localhost:10000/sys/tg_test/1 string_scalar
 *
 *   jbang MultiDeviceSnapshot.java 2000 \
 *       tango://localhost:10000/sys/tg_test/1 double_scalar \
 *       tango://localhost:10000/sys/tg_test/1 long_scalar
 */
public class MultiDeviceSnapshot {

    record Target(String device, String attribute) {}

    public static void main(String[] args) throws Exception {
        if (args.length < 2) {
            System.err.println("Usage: MultiDeviceSnapshot [interval-ms] <device> <attr> [<device> <attr> ...]");
            System.exit(1);
        }

        long intervalMs = 0;
        int start = 0;
        try {
            intervalMs = Long.parseLong(args[0]);
            start = 1;
        } catch (NumberFormatException ignored) { /* no interval, one-shot */ }

        List<Target> targets = new ArrayList<>();
        for (int i = start; i + 1 < args.length; i += 2)
            targets.add(new Target(args[i], args[i + 1]));

        if (targets.isEmpty()) {
            System.err.println("No device/attribute pairs found.");
            System.exit(1);
        }

        Single<List<String>> snapshot = Flowable.fromIterable(targets)
                .flatMapSingle(t ->
                        Flowable.fromPublisher(new RxTangoAttribute<>(t.device(), t.attribute()))
                                .firstOrError()
                                .map(v -> String.format("  %-40s = %s",
                                        t.attribute() + "  [" + t.device() + "]", v))
                                .onErrorReturn(e -> String.format("  %-40s ! ERROR: %s",
                                        t.attribute() + "  [" + t.device() + "]", e.getMessage()))
                )
                .toList();

        if (intervalMs <= 0) {
            // one-shot
            snapshot.blockingSubscribe(
                    lines -> { System.out.println("Snapshot @ " + Instant.now()); lines.forEach(System.out::println); },
                    err   -> System.err.println("Fatal: " + err.getMessage())
            );
        } else {
            // continuous
            System.out.printf("Polling every %d ms — Ctrl+C to stop%n", intervalMs);
            Flowable.interval(0, intervalMs, TimeUnit.MILLISECONDS)
                    .flatMapSingle(tick -> snapshot)
                    .blockingSubscribe(
                            lines -> { System.out.println("\nSnapshot @ " + Instant.now()); lines.forEach(System.out::println); },
                            err   -> System.err.println("Fatal: " + err.getMessage())
                    );
        }
    }
}
