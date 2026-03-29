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

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.TimeUnit;

/**
 * Fan-in alarm monitor: polls N attributes from N (possibly different) devices,
 * merges all streams into one, and emits an alarm line whenever any value
 * exceeds the threshold.
 *
 * Each device is polled independently. A failure on one device does not affect
 * the others — the stream simply logs the error and continues.
 *
 * This is the fan-in pattern: N independent sources → 1 unified alarm stream.
 *
 * Usage:
 *   jbang AlarmMonitor.java <threshold> <interval-ms> <device> <attr> [<device> <attr> ...]
 *
 * Example (alert when |value| > 200, poll every 500 ms):
 *   jbang AlarmMonitor.java 200 500 \
 *       tango://localhost:10000/sys/tg_test/1 double_scalar \
 *       tango://localhost:10000/sys/tg_test/1 long_scalar
 */
public class AlarmMonitor {

    record Target(String device, String attribute) {}

    public static void main(String[] args) throws Exception {
        if (args.length < 4) {
            System.err.println("Usage: AlarmMonitor <threshold> <interval-ms> <device> <attr> [<device> <attr> ...]");
            System.exit(1);
        }

        double threshold = Double.parseDouble(args[0]);
        long   intervalMs = Long.parseLong(args[1]);

        List<Target> targets = new ArrayList<>();
        for (int i = 2; i + 1 < args.length; i += 2)
            targets.add(new Target(args[i], args[i + 1]));

        if (targets.isEmpty()) {
            System.err.println("No device/attribute pairs found.");
            System.exit(1);
        }

        System.out.printf("Monitoring %d source(s), threshold ±%.2f, poll every %d ms — Ctrl+C to stop%n",
                targets.size(), threshold, intervalMs);

        // Build one polling stream per target, then merge them all into a single alarm stream.
        // Each stream is independent: an error on one device doesn't kill the others.
        List<Flowable<String>> streams = new ArrayList<>();
        for (Target t : targets) {
            Flowable<String> stream = Flowable.interval(intervalMs, TimeUnit.MILLISECONDS)
                    .flatMapSingle(tick ->
                            Flowable.fromPublisher(new RxTangoAttribute<>(t.device(), t.attribute()))
                                    .firstOrError()
                                    .map(v -> ((Number) v).doubleValue())
                    )
                    .filter(v -> Math.abs(v) > threshold)
                    .map(v -> String.format("ALARM  [%s]  %s/%s = %.4f  (threshold ±%.2f)",
                            Instant.now(), t.attribute(), t.device(), v, threshold))
                    .onErrorResumeNext(err -> {
                        System.err.printf("Stream error for %s/%s: %s — continuing%n",
                                t.device(), t.attribute(), err.getMessage());
                        return Flowable.empty();
                    });
            streams.add(stream);
        }

        Flowable.merge(streams)
                .blockingSubscribe(
                        System.out::println,
                        err -> System.err.println("Fatal: " + err.getMessage())
                );
    }
}
