///usr/bin/env jbang "$0" "$@" ; exit $?
//JAVA 16+
//REPOS mavencentral,jtango=https://maven.pkg.github.com/scientific-software-hub/JTango
//DEPS io.reactivex.rxjava3:rxjava:3.1.8
//DEPS org.reactivestreams:reactive-streams:1.0.4
//DEPS de.desy.tine:tine:5.3
//DEPS org.waltz.tango:ez:1.6.3
//DEPS org.waltz.tango.orb:tangorb:1.6.3
//SOURCES ../RxTango/java/src/RxTango.java ../RxTango/java/src/RxTangoAttribute.java
//SOURCES ../RxTine/java/src/RxTine.java ../RxTine/java/src/RxTineRead.java

import io.reactivex.rxjava3.core.Flowable;
import io.reactivex.rxjava3.core.Single;
import org.tango.client.rx.RxTangoAttribute;
import org.tine.client.rx.RxTineRead;

import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;

/**
 * X-Ray Fluorescence Scan — cross-system reactive pipeline.
 *
 * Simulates a synchrotron X-ray fluorescence experiment that reads from two
 * separate control systems simultaneously:
 *
 *   TINE  /TEST/JSINESRV/SINEDEV_0  Sine         → I₀  (beam intensity monitor)
 *   Tango sys/tg_test/1             double_scalar → I   (fluorescence detector)
 *
 * Pipeline (all Rx operators, no loops):
 *
 *   interval
 *     → onBackpressureLatest        drop stale ticks if reads are slow
 *     → flatMapSingle(zip(I₀, I))  correlated acquisition, parallel reads
 *     → doOnNext / filter           beam-dump gate, count discards
 *     → map                         dead-time correction + normalization I/I₀
 *     → buffer(N, 1)                overlapping sliding window
 *     → map                         mean of window = smoothed signal
 *     → scan(Welford)               running mean / stddev / SNR, O(1) memory
 *     → throttleLast                decouple display rate from acquisition rate
 *     → take(SCAN_POINTS)           finite scan — complete automatically
 *
 * Prerequisites:
 *   docker compose -f RxTango/java/docker-compose.yml up -d     (Tango stack)
 *   docker compose -f RxTine/java/docker-compose.yml  up -d     (TINE stack)
 *
 * Usage (from repo root):
 *   jbang examples/XRayScan.java [tango-device] [tine-device]
 *
 * Example:
 *   jbang examples/XRayScan.java \
 *       tango://localhost:10000/sys/tg_test/1 \
 *       /TEST/JSINESRV/SINEDEV_0
 */
public class XRayScan {

    // ── Scan configuration ────────────────────────────────────────────────────

    static final int    SCAN_POINTS    = 20;     // valid data points to collect
    static final double BEAM_THRESHOLD = 20.0;   // mA  — below this = beam dump
    static final double DEAD_TIME_FRAC = 0.05;   // detector dead-time fraction τ
    static final int    WINDOW_SIZE    = 5;       // sliding-average window width
    static final double SNR_ALERT      = 5.0;    // print warning if SNR drops below
    static final long   POLL_MS        = 300;    // acquisition interval (ms)
    static final long   DISPLAY_MS     = 300;    // display throttle (ms)
    static final long   TIMEOUT_MS     = 1_500;  // per-read timeout (ms)
    static final int    MAX_RETRIES    = 3;      // per-read retry count

    // ── Counters (updated from pipeline, reported in summary) ─────────────────

    static final AtomicInteger beamDumps   = new AtomicInteger();
    static final AtomicInteger tineErrors  = new AtomicInteger();
    static final AtomicInteger tangoErrors = new AtomicInteger();
    static final AtomicLong    pointIndex  = new AtomicLong();

    // ── Data records ──────────────────────────────────────────────────────────

    record RawPair(long tick, double i0, double det) {}

    record CorrectedPoint(long tick, double i0, double iRaw, double iCorr, double norm) {}

    record SmoothPoint(long tick, double i0, double iRaw, double iCorr,
                       double norm, double smoothed) {}

    /**
     * Welford's online accumulator for streaming mean / variance.
     *
     * Unlike the batch formula  (Σx² − n·mean²) / (n−1),  Welford's algorithm
     * is numerically stable for closely-spaced floating-point values — a common
     * situation with normalized detector signals that differ only in the 4th
     * decimal place.
     *
     * Used with scan() so statistics update after every single sample with O(1)
     * memory — no list is ever allocated.
     */
    record WelfordState(long n, double mean, double m2, SmoothPoint point) {

        static final WelfordState ZERO = new WelfordState(0, 0.0, 0.0, null);

        static WelfordState update(WelfordState s, SmoothPoint p) {
            double x     = p.smoothed();
            long   n     = s.n + 1;
            double delta = x - s.mean;
            double mean  = s.mean + delta / n;
            double m2    = s.m2   + delta * (x - mean);   // Welford M2 step
            return new WelfordState(n, mean, m2, p);
        }

        double stddev() { return n > 1 ? Math.sqrt(m2 / (n - 1)) : 0.0; }

        /** Signal-to-noise: mean / σ.  Larger = cleaner signal. */
        double snr()    { return stddev() > 1e-12 ? mean / stddev() : Double.POSITIVE_INFINITY; }
    }

    // ── Main ──────────────────────────────────────────────────────────────────

    public static void main(String[] args) throws Exception {

        String tangoDevice = args.length > 0 ? args[0]
                : "tango://localhost:10000/sys/tg_test/1";
        String tineDevice  = args.length > 1 ? args[1]
                : "/TEST/JSINESRV/SINEDEV_0";

        printHeader(tangoDevice, tineDevice);

        Flowable.interval(POLL_MS, TimeUnit.MILLISECONDS)

            // ── Stage 1: backpressure guard ───────────────────────────────────
            //
            // If a pair of reads takes longer than POLL_MS, the interval
            // accumulates pending ticks.  onBackpressureLatest() keeps only the
            // most recent unprocessed tick and discards the rest — the scan
            // always acquires the freshest moment, never stale queued ticks.
            .onBackpressureLatest()

            // ── Stage 2: correlated acquisition ──────────────────────────────
            //
            // Single.zip fires I₀ (TINE) and I (Tango) in parallel and delivers
            // them as an atomic pair only when BOTH complete.  Sequential reads
            // (read A; read B) would be vulnerable to a value update between the
            // two calls — the pair would be temporally torn.  zip prevents that.
            //
            // Each source independently:
            //   - retries up to MAX_RETRIES times on transient errors
            //   - times out after TIMEOUT_MS and returns NaN as a sentinel
            //
            // A NaN from one source does not stall or kill the other.
            // maxConcurrency=1 ensures one acquisition at a time (no overlap).
            .flatMapSingle(tick -> Single.zip(
                    readI0(tineDevice),
                    readDetector(tangoDevice),
                    (i0, det) -> new RawPair(tick, i0, det)
            ), /*delayErrors=*/false, /*maxConcurrency=*/1)

            // ── Stage 3: beam-dump gate ───────────────────────────────────────
            //
            // A synchrotron beam dumps periodically (injection, trip, etc.).
            // During a dump I₀ drops to near zero, making I/I₀ meaningless.
            // doOnNext counts discards before filter removes them so the final
            // report can include beam-dump statistics.
            .doOnNext(p -> {
                if (Double.isNaN(p.i0()) || Double.isNaN(p.det()) || p.i0() < BEAM_THRESHOLD)
                    beamDumps.incrementAndGet();
            })
            .filter(p -> !Double.isNaN(p.i0()) && !Double.isNaN(p.det())
                      && p.i0() >= BEAM_THRESHOLD)

            // ── Stage 4: dead-time correction + normalization ─────────────────
            //
            // Fluorescence detectors are paralyzable: at high count rates, each
            // arriving photon extends the dead window, causing the measured rate
            // to *decrease* above saturation.  The correction is:
            //
            //   I_corr = I_measured / (1 − I_measured × τ)
            //
            // where τ is the dead-time fraction (device-specific calibration
            // constant).  After correction, normalize by beam current: I_corr/I₀
            // removes machine fluctuations from the measured signal.
            .map(p -> {
                double iCorr = deadTimeCorrect(p.det(), DEAD_TIME_FRAC);
                double norm  = iCorr / p.i0();
                return new CorrectedPoint(p.tick(), p.i0(), p.det(), iCorr, norm);
            })

            // ── Stage 5: sliding window average ──────────────────────────────
            //
            // buffer(N, 1) emits overlapping lists of N consecutive samples,
            // advancing by 1 each tick.  No circular buffer, no index arithmetic.
            //   tick N:   [v₁..vN]
            //   tick N+1: [v₂..vN+1]
            //
            // Averaging the window gives a noise-reduced signal without
            // introducing a scan-speed penalty.  Output only starts once the
            // first full window has accumulated.
            .buffer(WINDOW_SIZE, 1)
            .filter(w -> w.size() == WINDOW_SIZE)
            .map(w -> {
                CorrectedPoint last     = w.get(w.size() - 1);
                double         smoothed = w.stream()
                                          .mapToDouble(CorrectedPoint::norm)
                                          .average()
                                          .orElse(Double.NaN);
                return new SmoothPoint(last.tick(), last.i0(), last.iRaw(),
                                       last.iCorr(), last.norm(), smoothed);
            })

            // ── Stage 6: running SNR — Welford's algorithm via scan() ─────────
            //
            // scan() is the streaming counterpart of reduce(): it emits the
            // accumulated result after every single value rather than waiting for
            // the stream to complete.  Combined with WelfordState it gives live
            // mean / stddev / SNR that update in real time with O(1) memory and
            // without ever allocating a growing list.
            .scan(WelfordState.ZERO, WelfordState::update)
            .filter(s -> s.n() > 0)    // skip the empty seed emitted by scan()

            // ── Stage 7: display throttle ─────────────────────────────────────
            //
            // throttleLast decouples the acquisition rate (POLL_MS) from the
            // display rate (DISPLAY_MS).  Of all WelfordState items arriving
            // within each DISPLAY_MS window, only the most recent is printed —
            // the terminal is never flooded even if acquisition outpaces display.
            .throttleLast(DISPLAY_MS, TimeUnit.MILLISECONDS)

            // ── Stage 8: collect exactly SCAN_POINTS valid data points ────────
            //
            // take(N) limits the stream to N items then completes it cleanly.
            // blockingSubscribe drives the pipeline synchronously so main()
            // returns only after the scan is done.
            .take(SCAN_POINTS)

            .blockingSubscribe(
                XRayScan::printScanPoint,
                err -> System.err.printf("%nPIPELINE ERROR: %s%n", err.getMessage()),
                XRayScan::printSummary
            );
    }

    // ── Instrumented reads ────────────────────────────────────────────────────

    /**
     * Read beam current from TINE with retry and timeout.
     *
     * Converts the jsineServer Sine value [-1, +1] to an absolute beam current
     * [0, 100 mA] to simulate a realistic I₀ monitor signal.
     */
    static Single<Double> readI0(String device) {
        return Flowable.fromPublisher(RxTineRead.ofDouble(device, "Sine"))
                .firstOrError()
                .retry(MAX_RETRIES)
                .timeout(TIMEOUT_MS, TimeUnit.MILLISECONDS)
                .map(sine -> Math.abs(sine) * 100.0)
                .doOnError(e -> tineErrors.incrementAndGet())
                .onErrorReturnItem(Double.NaN);
    }

    /**
     * Read detector signal from Tango with retry and timeout.
     *
     * Single.defer() wraps the RxTangoAttribute constructor (which may throw)
     * so that construction errors are properly channelled into the reactive
     * error path and trigger the retry logic rather than escaping as exceptions.
     */
    static Single<Double> readDetector(String device) {
        return Single.defer(() -> {
            try {
                return Flowable.fromPublisher(new RxTangoAttribute<Object>(device, "double_scalar"))
                        .firstOrError()
                        .map(v -> ((Number) v).doubleValue());
            } catch (Exception e) {
                return Single.error(e);
            }
        })
        .retry(MAX_RETRIES)
        .timeout(TIMEOUT_MS, TimeUnit.MILLISECONDS)
        .doOnError(e -> tangoErrors.incrementAndGet())
        .onErrorReturnItem(Double.NaN);
    }

    // ── Dead-time correction ──────────────────────────────────────────────────

    /**
     * Paralyzable-model dead-time correction for a fluorescence detector:
     *
     *   I_corrected = I_measured / (1 − |I_measured| × τ_fraction)
     *
     * Returns 0 when the detector is saturated (|I| × τ ≥ 1), preserving the
     * sign of the measured value for the corrected output.
     */
    static double deadTimeCorrect(double iMeasured, double tauFraction) {
        double denominator = 1.0 - Math.abs(iMeasured) * tauFraction;
        return denominator > 0 ? iMeasured / denominator : 0.0;
    }

    // ── Output ────────────────────────────────────────────────────────────────

    static void printHeader(String tangoDevice, String tineDevice) {
        System.out.println();
        System.out.println("=== X-Ray Fluorescence Scan =============================================");
        System.out.printf ("  TINE  %-46s (I0 beam monitor)%n", tineDevice + "/Sine");
        System.out.printf ("  Tango %-46s (detector)%n",        tangoDevice + "/double_scalar");
        System.out.printf ("  beam threshold: %.0f mA  |  dead-time: %.0f%%  |  "
                         + "window: %d  |  SNR alert: %.1f%n",
                BEAM_THRESHOLD, DEAD_TIME_FRAC * 100, WINDOW_SIZE, SNR_ALERT);
        System.out.println("=========================================================================");
        System.out.printf ("  %4s  %8s  %8s  %8s  %10s  %10s  %8s%n",
                "pt", "I0(mA)", "I_raw", "I_corr", "I/I0", "smoothed", "SNR");
        System.out.printf ("  %4s  %8s  %8s  %8s  %10s  %10s  %8s%n",
                "----", "------", "------", "------", "--------", "--------", "-------");
    }

    static void printScanPoint(WelfordState s) {
        long        pt      = pointIndex.incrementAndGet();
        SmoothPoint p       = s.point();
        String      snrStr  = s.n() > WINDOW_SIZE
                ? String.format("%8.1f", s.snr()) : "     ---";
        String      alert   = (s.n() > WINDOW_SIZE && s.snr() < SNR_ALERT)
                ? "  [!] low SNR" : "";
        System.out.printf("  %4d  %8.2f  %8.4f  %8.4f  %10.6f  %10.6f  %s%s%n",
                pt, p.i0(), p.iRaw(), p.iCorr(), p.norm(), p.smoothed(), snrStr, alert);
    }

    static void printSummary() {
        System.out.println("=========================================================================");
        System.out.printf ("  Scan complete: %d points  |  beam dumps: %d  "
                         + "|  TINE errors: %d  |  Tango errors: %d%n",
                SCAN_POINTS, beamDumps.get(), tineErrors.get(), tangoErrors.get());
        System.out.println();
    }
}
