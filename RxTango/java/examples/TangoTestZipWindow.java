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

import java.util.List;
import java.util.concurrent.TimeUnit;

/**
 * Synchronizing multiple Tango sources: three patterns.
 *
 * Plain zip() pairs sources by position (1st with 1st, 2nd with 2nd).
 * That works perfectly when you control both reads — but breaks in two ways:
 *
 *   a) A source misbehaves (error, timeout, or too slow):
 *      zip stalls waiting for the missing item; the other source buffers
 *      indefinitely.  One bad source head-of-line blocks the whole pipeline.
 *
 *   b) Sources run at different natural rates (events, not polling):
 *      zip pairs by count, not by time.  Source A emits 3 times while B
 *      emits once — A's 2nd and 3rd values sit in a buffer waiting for
 *      B's 2nd item, which may arrive much later.
 *
 * This example demonstrates three strategies to address both problems:
 *
 *   Demo A — Shielded zip
 *     Per-source timeout + onErrorReturnItem wraps each read before zipping.
 *     A dead or slow source returns a NaN sentinel instead of stalling.
 *     The zip always makes forward progress; NaN tells you which reading is stale.
 *
 *   Demo B — combineLatest
 *     Fires on every update from any source, always combining with the
 *     most recently cached value from the others.
 *     Semantics: you always see the latest value from each source together;
 *     fast sources cause more frequent emissions; no value is ever dropped.
 *     Sources A (200 ms) and B (500 ms) run at deliberately different rates
 *     so you can see which source triggered each emission.
 *
 *   Demo C — buffer(windowMs) + zip
 *     Both sources are buffered into fixed time windows.
 *     The windows from all sources are zipped by position (same window slot).
 *     Result: you get all values that co-occurred within each window, and
 *     you can take the latest, average, or count of each slot.
 *     Semantics: strict temporal alignment — two values are "the same moment"
 *     only if they fell in the same window.  An empty window yields NaN.
 *
 * Usage:
 *   jbang TangoTestZipWindow.java <device> [timeout-ms] [window-ms] [fast-ms] [slow-ms]
 *
 * Example:
 *   jbang TangoTestZipWindow.java tango://localhost:10000/sys/tg_test/1
 *   jbang TangoTestZipWindow.java tango://localhost:10000/sys/tg_test/1 300 500 200 500
 */
public class TangoTestZipWindow {

    static final String ATTR_A = "double_scalar";
    static final String ATTR_B = "long_scalar";
    static final String BAD_ATTR = "__nonexistent__";  // always fails — makes Demo A visible

    public static void main(String[] args) throws Exception {
        if (args.length < 1) {
            System.err.println("Usage: TangoTestZipWindow <device> [timeout-ms=300] [window-ms=500] [fast-ms=200] [slow-ms=500]");
            System.exit(1);
        }

        String device    = args[0];
        long timeoutMs   = args.length > 1 ? Long.parseLong(args[1]) : 300L;
        long windowMs    = args.length > 2 ? Long.parseLong(args[2]) : 500L;
        long fastMs      = args.length > 3 ? Long.parseLong(args[3]) : 200L;
        long slowMs      = args.length > 4 ? Long.parseLong(args[4]) : 500L;

        demoA(device, timeoutMs);
        demoB(device, fastMs, slowMs);
        demoC(device, fastMs, windowMs);
    }

    // ── Demo A: Shielded zip ──────────────────────────────────────────────────

    static void demoA(String device, long timeoutMs) {
        System.out.printf("%n── Demo A: shielded zip (timeout %d ms + NaN fallback) ─────────────%n", timeoutMs);
        System.out.printf("  Source A: %s  (always succeeds)%n", ATTR_A);
        System.out.printf("  Source B: %s  (always fails — timeout fires, NaN returned)%n%n", BAD_ATTR);
        System.out.printf("  %20s  %20s%n", ATTR_A, BAD_ATTR + " (shielded)");
        System.out.println("  " + "-".repeat(44));

        // Each source is independently protected before it reaches zip().
        // A timeout ensures zip never waits more than timeoutMs for any one source.
        // onErrorReturnItem(NaN) converts any failure — timeout, device error,
        // attribute not found — into a safe sentinel value.
        // zip makes forward progress on every tick regardless of source health.
        Flowable.interval(600, TimeUnit.MILLISECONDS)
                .take(5)
                .flatMapSingle(tick ->
                        Single.zip(
                                readDouble(device, ATTR_A)
                                        .timeout(timeoutMs, TimeUnit.MILLISECONDS)
                                        .onErrorReturnItem(Double.NaN),   // A is healthy

                                readDouble(device, BAD_ATTR)
                                        .timeout(timeoutMs, TimeUnit.MILLISECONDS)
                                        .onErrorReturnItem(Double.NaN),   // B always fails → NaN

                                (a, b) -> String.format("  %+20.6f  %20s", a, fmtVal(b))
                        )
                )
                .blockingSubscribe(
                        System.out::println,
                        err -> System.err.println("  ERROR: " + err.getMessage())
                );
    }

    // ── Demo B: combineLatest ─────────────────────────────────────────────────

    static void demoB(String device, long fastMs, long slowMs) {
        System.out.printf("%n── Demo B: combineLatest (A every %d ms, B every %d ms) ────────────%n",
                fastMs, slowMs);
        System.out.printf("  combineLatest fires on EVERY new value from either source.%n");
        System.out.printf("  Faster source causes more emissions; no value is ever dropped.%n%n");
        System.out.printf("  %7s  %20s  %20s%n", "trigger", ATTR_A + " (fast)", ATTR_B + " (slow)");
        System.out.println("  " + "-".repeat(52));

        // Tag each value with which source produced it so the output shows which
        // source triggered each combineLatest emission.
        Flowable<double[]> streamA = Flowable.interval(fastMs, TimeUnit.MILLISECONDS)
                .flatMapSingle(tick -> readDouble(device, ATTR_A))
                .map(v -> new double[]{v, 0});   // [value, sourceTag=0]

        Flowable<double[]> streamB = Flowable.interval(slowMs, TimeUnit.MILLISECONDS)
                .flatMapSingle(tick -> readDouble(device, ATTR_B))
                .map(v -> new double[]{v, 1});   // [value, sourceTag=1]

        // combineLatest caches the latest value from each source.
        // It emits a new combined value whenever either source emits.
        // The other source contributes its most recently cached value.
        Flowable.combineLatest(
                        streamA,
                        streamB,
                        (a, b) -> new double[]{ a[0], b[0], a[1] == 0 ? 0 : 1 }  // [valA, valB, trigger]
                )
                .take(15)
                .blockingSubscribe(
                        row -> System.out.printf("  %7s  %+20.6f  %+20.6f%n",
                                row[2] == 0 ? "← A" : "     B →",
                                row[0], row[1]),
                        err -> System.err.println("  ERROR: " + err.getMessage())
                );

        System.out.printf("%n  Observe: A-triggered rows are more frequent (A polls %.1fx faster than B).%n",
                (double) slowMs / fastMs);
        System.out.printf("  The cached B value repeats across A-triggered rows until B emits next.%n");
    }

    // ── Demo C: buffer(windowMs) + zip ───────────────────────────────────────

    static void demoC(String device, long pollMs, long windowMs) {
        System.out.printf("%n── Demo C: buffer(%d ms) + zip — time-window aggregation ──────────%n", windowMs);
        System.out.printf("  Both sources polled every %d ms; values collected into %d ms windows.%n",
                pollMs, windowMs);
        System.out.printf("  Zip pairs windows by slot (same %d ms bucket = same moment).%n%n", windowMs);
        System.out.printf("  %5s  %5s  %14s  %5s  %14s%n",
                "#A", "#B", ATTR_A + " (latest)", "#A", ATTR_B + " (latest)");
        System.out.println("  " + "-".repeat(55));

        Flowable<List<Double>> windowA = Flowable.interval(pollMs, TimeUnit.MILLISECONDS)
                .flatMapSingle(tick -> readDouble(device, ATTR_A))
                .buffer(windowMs, TimeUnit.MILLISECONDS);

        Flowable<List<Double>> windowB = Flowable.interval(pollMs, TimeUnit.MILLISECONDS)
                .flatMapSingle(tick -> readDouble(device, ATTR_B))
                .buffer(windowMs, TimeUnit.MILLISECONDS);

        // zip pairs windows by position — window[0] from A with window[0] from B,
        // window[1] from A with window[1] from B, and so on.
        // Since both use the same windowMs, these correspond to the same time slot.
        //
        // From each window we take the latest value (or NaN if the window is empty —
        // which can happen if the device was temporarily unreachable during that slot).
        Flowable.zip(windowA, windowB, (as, bs) -> {
                    double latestA = as.isEmpty() ? Double.NaN : as.get(as.size() - 1);
                    double latestB = bs.isEmpty() ? Double.NaN : bs.get(bs.size() - 1);
                    return new Object[]{ as.size(), bs.size(), latestA, latestB };
                })
                .take(8)
                .blockingSubscribe(
                        row -> System.out.printf("  %5d  %5d  %+14.6f  %5d  %+14.6f%n",
                                row[0], row[1], row[2], row[1], row[3]),
                        err -> System.err.println("  ERROR: " + err.getMessage())
                );

        System.out.printf("%n  #A and #B show how many samples fell in each window (~%d expected at %d ms poll).%n",
                windowMs / pollMs, pollMs);
        System.out.printf("  NaN in a slot means the source was silent during that window.%n");
    }

    // ── helpers ───────────────────────────────────────────────────────────────

    static Single<Double> readDouble(String device, String attribute) {
        return Flowable.fromPublisher(new RxTangoAttribute<>(device, attribute))
                .firstOrError()
                .map(v -> ((Number) v).doubleValue());
    }

    static String fmtVal(double v) {
        return Double.isNaN(v) ? "NaN (shielded)" : String.format("%+.6f", v);
    }
}
