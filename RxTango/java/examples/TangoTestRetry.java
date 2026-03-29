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

import java.util.Map;
import java.util.concurrent.TimeUnit;

/**
 * Demonstrates three retry patterns for resilient Tango attribute reads.
 *
 * In a real control system, reads can fail transiently: a device restarts,
 * a network blip drops the connection, the hardware is momentarily busy.
 * Rx retry operators turn fragile one-shot reads into self-healing operations
 * with no manual loop or exception handling.
 *
 * Three patterns, in increasing sophistication:
 *
 *   1. retry(n)          — immediate retries, N attempts maximum.
 *                          Fastest; use when errors are rare and transient.
 *
 *   2. retryWhen backoff — exponential backoff: wait base * 2^(attempt-1) ms
 *                          before each retry, then fall back to NaN.
 *                          Use when the device needs time to recover (restart,
 *                          hardware initialisation).
 *
 *   3. Resilient poll    — per-tick retry inside flatMapSingle.
 *                          Critical point: retry belongs INSIDE flatMapSingle,
 *                          not on the outer interval stream.  Outside means a
 *                          single bad tick restarts the whole polling sequence
 *                          from tick 0.  Inside means each tick is independently
 *                          resilient; the polling cadence is never interrupted.
 *
 * Patterns 1 and 2 deliberately read a non-existent attribute so that retries
 * actually fire and you can observe the behaviour.  Pattern 3 uses a real
 * attribute with retry as a safety net.
 *
 * Usage:
 *   jbang TangoTestRetry.java <device> [max-retries] [base-delay-ms] [poll-ms]
 *
 * Example:
 *   jbang TangoTestRetry.java tango://localhost:10000/sys/tg_test/1
 *   jbang TangoTestRetry.java tango://localhost:10000/sys/tg_test/1 3 500 1000
 */
public class TangoTestRetry {

    static final String GOOD_ATTR = "double_scalar";
    static final String BAD_ATTR  = "__nonexistent__";   // always fails → retries fire

    public static void main(String[] args) throws Exception {
        if (args.length < 1) {
            System.err.println("Usage: TangoTestRetry <device> [max-retries=3] [base-delay-ms=500] [poll-ms=1000]");
            System.exit(1);
        }

        String device      = args[0];
        int    maxRetries  = args.length > 1 ? Integer.parseInt(args[1]) : 3;
        long   baseDelayMs = args.length > 2 ? Long.parseLong(args[2])   : 500L;
        long   pollMs      = args.length > 3 ? Long.parseLong(args[3])   : 1000L;

        // ── helper: single-shot read wrapped as Single<Double> ────────────────
        // Reused across all three demos.
        // attr is a parameter so we can swap good/bad attribute names easily.

        // ── Demo 1: retry(n) — immediate retries ─────────────────────────────
        System.out.printf("%n── Demo 1: retry(%d) — immediate retries ──────────────────────────%n", maxRetries);
        System.out.printf("  Reading '%s' from %s%n", BAD_ATTR, device);
        System.out.printf("  (attribute does not exist — all attempts will fail)%n%n");

        Double result1 = readAttr(device, BAD_ATTR)
                .doOnError(e -> System.out.printf("  attempt failed: %s%n", e.getMessage()))
                .retry(maxRetries)
                .onErrorReturnItem(Double.NaN)
                .blockingGet();

        System.out.printf("%n  result after %d attempts: %s%n", maxRetries + 1, formatValue(result1));

        // ── Demo 2: retryWhen — exponential backoff ───────────────────────────
        System.out.printf("%n── Demo 2: retryWhen — exponential backoff (base %d ms) ───────────%n", baseDelayMs);
        System.out.printf("  Reading '%s' from %s%n", BAD_ATTR, device);
        System.out.printf("  Delays: %.1f s, %.1f s, %.1f s, ...%n%n",
                baseDelayMs / 1000.0, baseDelayMs * 2 / 1000.0, baseDelayMs * 4 / 1000.0);

        Double result2 = readAttr(device, BAD_ATTR)
                .retryWhen(errors ->
                        errors
                            .zipWith(Flowable.range(1, maxRetries + 1),
                                     (err, attempt) -> Map.entry(err, attempt))
                            .flatMap(e -> {
                                int attempt = e.getValue();
                                if (attempt > maxRetries)
                                    return Flowable.error(e.getKey());     // retries exhausted
                                long delayMs = (long)(Math.pow(2, attempt - 1) * baseDelayMs);
                                System.out.printf("  [retry %d/%d] waiting %d ms — %s%n",
                                        attempt, maxRetries, delayMs, e.getKey().getMessage());
                                return Flowable.timer(delayMs, TimeUnit.MILLISECONDS);
                            })
                )
                .onErrorReturnItem(Double.NaN)   // exhausted → safe fallback sentinel
                .blockingGet();

        System.out.printf("%n  result after backoff: %s%n", formatValue(result2));

        // ── Demo 3: resilient polling loop — retry inside flatMapSingle ───────
        System.out.printf("%n── Demo 3: resilient poll every %d ms (retry inside tick) ──────────%n", pollMs);
        System.out.printf("  Reading '%s' from %s%n", GOOD_ATTR, device);
        System.out.printf("  Each tick: up to %d retries, then NaN if all fail.%n", maxRetries);
        System.out.printf("  The polling cadence is never interrupted. Ctrl+C to stop.%n%n");
        System.out.printf("  %5s  %12s%n", "tick", GOOD_ATTR);
        System.out.println("  " + "-".repeat(20));

        Flowable.interval(pollMs, TimeUnit.MILLISECONDS)
                .flatMapSingle(tick ->
                        readAttr(device, GOOD_ATTR)
                                // retry(n) is INSIDE flatMapSingle → each tick is independently
                                // resilient.  A failing tick emits NaN; the next tick fires
                                // on schedule regardless.
                                //
                                // If retry were on the outer Flowable.interval(...).retry(n),
                                // a single bad tick would restart the counter from tick 0,
                                // breaking the polling cadence and losing all progress.
                                .retry(maxRetries)
                                .onErrorReturnItem(Double.NaN)
                                .map(v -> Map.entry(tick, v))
                )
                .blockingSubscribe(
                        e  -> System.out.printf("  %5d  %+12.6f%n", e.getKey(), e.getValue()),
                        err -> System.err.println("Fatal: " + err.getMessage())
                );
    }

    // ── helpers ───────────────────────────────────────────────────────────────

    static Single<Double> readAttr(String device, String attribute) {
        return Flowable.fromPublisher(new RxTangoAttribute<>(device, attribute))
                .firstOrError()
                .map(v -> ((Number) v).doubleValue());
    }

    static String formatValue(double v) {
        return Double.isNaN(v) ? "NaN (all retries exhausted — fallback sentinel)" : String.format("%.6f", v);
    }
}
