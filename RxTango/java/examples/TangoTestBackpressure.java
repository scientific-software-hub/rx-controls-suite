///usr/bin/env jbang "$0" "$@" ; exit $?
//JAVA 11+
//REPOS mavencentral,jtango=https://maven.pkg.github.com/scientific-software-hub/JTango
//DEPS io.reactivex.rxjava3:rxjava:3.1.8
//DEPS org.reactivestreams:reactive-streams:1.0.4
//DEPS org.waltz.tango:ez:1.6.3
//DEPS org.waltz.tango.orb:tangorb:1.6.3
//SOURCES ../src/RxTango.java ../src/RxTangoAttribute.java

import io.reactivex.rxjava3.core.Flowable;
import io.reactivex.rxjava3.schedulers.Schedulers;
import org.tango.client.rx.RxTangoAttribute;

import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Demonstrates backpressure: what happens when a fast producer meets a slow consumer.
 *
 * The producer polls TangoTest at 100 ms (10 Hz).
 * The consumer takes 600 ms per item — 6x slower than the producer.
 *
 * Without a backpressure strategy the internal buffer (128 slots) fills up in
 * ~13 s and the stream crashes with MissingBackpressureException.
 *
 * Three strategies are available via the --strategy argument:
 *
 *   latest (default) — keep only the most recent unprocessed value; the consumer
 *                      always sees fresh data, never stale queued readings.
 *
 *   drop             — drop every value that arrives while the consumer is busy;
 *                      unlike `latest`, even the newest value is dropped if it
 *                      arrives before the previous one is processed.
 *
 *   buffer           — queue up to N values (default 8); crash with
 *                      MissingBackpressureException when the buffer is full.
 *                      Run this to see the exception in action.
 *
 * The skipped counter shows how many values were silently discarded.
 *
 * Usage:
 *   jbang TangoTestBackpressure.java <device> [poll-ms] [process-ms] [--strategy latest|drop|buffer] [--buffer-size N]
 *
 * Examples:
 *   jbang TangoTestBackpressure.java tango://localhost:10000/sys/tg_test/1
 *   jbang TangoTestBackpressure.java tango://localhost:10000/sys/tg_test/1 100 600 --strategy drop
 *   jbang TangoTestBackpressure.java tango://localhost:10000/sys/tg_test/1 100 600 --strategy buffer --buffer-size 5
 */
public class TangoTestBackpressure {
    public static void main(String[] args) throws Exception {
        if (args.length < 1) {
            System.err.println("Usage: TangoTestBackpressure <device> [poll-ms=100] [process-ms=600] [--strategy latest|drop|buffer] [--buffer-size N]");
            System.exit(1);
        }

        String device    = args[0];
        long   pollMs    = args.length > 1 ? Long.parseLong(args[1]) : 100L;
        long   processMs = args.length > 2 ? Long.parseLong(args[2]) : 600L;

        String strategy  = "latest";
        int    bufSize   = 8;
        for (int i = 3; i < args.length; i++) {
            if ("--strategy".equals(args[i]) && i + 1 < args.length)   strategy = args[++i];
            if ("--buffer-size".equals(args[i]) && i + 1 < args.length) bufSize  = Integer.parseInt(args[++i]);
        }

        System.out.printf("Producer: poll every %d ms  |  Consumer: %d ms/item  |  Strategy: %s%n",
                pollMs, processMs, strategy);
        System.out.printf("Producer is %.1fx faster than consumer — Ctrl+C to stop%n%n",
                (double) processMs / pollMs);
        System.out.printf("  %5s  %5s  %6s  %s%n", "prod", "cons", "skip", "value");
        System.out.println("  " + "-".repeat(44));

        AtomicLong produced  = new AtomicLong(0);
        AtomicLong consumed  = new AtomicLong(0);

        // --- fast producer: read Tango attribute at poll rate ---
        Flowable<Double> upstream = Flowable.interval(pollMs, TimeUnit.MILLISECONDS)
                .flatMapSingle(tick ->
                        Flowable.fromPublisher(new RxTangoAttribute<>(device, "double_scalar"))
                                .firstOrError()
                                .map(v -> ((Number) v).doubleValue())
                )
                .doOnNext(v -> produced.incrementAndGet());

        // --- apply backpressure strategy ---
        // Without any of these, flatMapSingle buffers internally (128 items).
        // Once that buffer fills, the stream crashes with MissingBackpressureException.
        Flowable<Double> bounded = switch (strategy) {
            // latest: when consumer is busy, discard all but the newest pending value.
            // The consumer always wakes up to the freshest reading — never to stale data
            // that has been waiting in a queue.
            case "latest" -> upstream.onBackpressureLatest();

            // drop: discard any value that arrives while the consumer is busy.
            // Difference from latest: 'drop' throws away even the most recent value
            // if it arrives before the slot is free; 'latest' replaces the waiting
            // slot with the newest arrival.
            case "drop"   -> upstream.onBackpressureDrop(
                    v -> {}  // called for each dropped value (count via produced - consumed)
            );

            // buffer: queue up to bufSize values; crash when full.
            // Use this to demonstrate the exception — it will occur after
            // (bufSize / (1 - pollMs/processMs)) / pollMs seconds.
            case "buffer" -> upstream.onBackpressureBuffer(bufSize);

            default -> throw new IllegalArgumentException("Unknown strategy: " + strategy);
        };

        // --- slow consumer on a separate thread ---
        // observeOn moves delivery to a single background thread, decoupling
        // producer speed from consumer speed. Without observeOn both run on the
        // same thread and backpressure never builds up.
        bounded
                .observeOn(Schedulers.single())
                .blockingSubscribe(
                        v -> {
                            long c = consumed.incrementAndGet();
                            long p = produced.get();
                            System.out.printf("  %5d  %5d  %6d  %+.6f%n", p, c, p - c, v);
                            // simulate slow downstream work (analysis, database write, etc.)
                            Thread.sleep(processMs);
                        },
                        err -> System.err.printf("%nERROR (%s): %s%n",
                                err.getClass().getSimpleName(), err.getMessage())
                );
    }
}
