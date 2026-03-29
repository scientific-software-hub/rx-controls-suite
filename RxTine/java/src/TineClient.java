package org.tine.client.rx;

import io.reactivex.rxjava3.core.Flowable;
import io.reactivex.rxjava3.core.Single;
import io.reactivex.rxjava3.disposables.Disposable;
import io.reactivex.rxjava3.functions.Consumer;

import java.util.function.Function;

/**
 * Fluent builder for sequential TINE property operations.
 *
 * Each method appends a step to an internal Rx chain. Steps are NOT executed
 * until a terminal method (subscribe / blockingGet) is called. Results flow
 * through the chain so later steps can compute their inputs dynamically.
 *
 * TINE has no commands — write to a property instead (no executeCommand here).
 *
 * Example — read, calibrate, write back:
 * <pre>
 *   new TineClient()
 *       .read("/HERA/Context/Device", "SENSOR")
 *       .map(v -> ((Number) v).doubleValue() * 1.05 + 0.3)
 *       .write("/HERA/Context/Device", "SETPOINT")
 *       .subscribe(
 *           result -> System.out.println("wrote: " + result),
 *           Throwable::printStackTrace
 *       );
 * </pre>
 *
 * Example — multi-step pipeline:
 * <pre>
 *   new TineClient()
 *       .read(devA, "CURRENT")
 *       .map(v -> ((Number) v).doubleValue() * calibFactor)
 *       .write(devB, "SETPOINT", v -> v)
 *       .read(devB, "READBACK")
 *       .blockingGet();
 * </pre>
 */
public class TineClient {

    private static final Object SEED = new Object();
    private Single<Object> chain = Single.just(SEED);

    // ── read ──────────────────────────────────────────────────────────────────

    /** Read a scalar double property. The value becomes the input for the next step. */
    public TineClient read(String devName, String property) {
        chain = chain.flatMap(__ ->
                Flowable.fromPublisher(RxTineRead.ofDouble(devName, property))
                        .firstOrError()
                        .cast(Object.class)
        );
        return this;
    }

    // ── write ─────────────────────────────────────────────────────────────────

    /** Write the result of the previous step to a property. The written value continues downstream. */
    public TineClient write(String devName, String property) {
        chain = chain.flatMap(prev -> {
            double value = ((Number) prev).doubleValue();
            return Flowable.fromPublisher(RxTineWrite.ofDouble(devName, property, value))
                    .firstOrError()
                    .cast(Object.class);
        });
        return this;
    }

    /** Write a static value, ignoring the previous step's result. */
    public TineClient write(String devName, String property, double value) {
        chain = chain.flatMap(__ ->
                Flowable.fromPublisher(RxTineWrite.ofDouble(devName, property, value))
                        .firstOrError()
                        .cast(Object.class)
        );
        return this;
    }

    /** Write a value computed from the previous step's result. */
    public TineClient write(String devName, String property, Function<Object, Double> valueFromPrev) {
        chain = chain.flatMap(prev ->
                Flowable.fromPublisher(
                                RxTineWrite.ofDouble(devName, property, valueFromPrev.apply(prev)))
                        .firstOrError()
                        .cast(Object.class)
        );
        return this;
    }

    // ── map ───────────────────────────────────────────────────────────────────

    /** Apply a pure transformation — no I/O. */
    public TineClient map(Function<Object, Object> transform) {
        chain = chain.map(transform::apply);
        return this;
    }

    // ── terminal operators ────────────────────────────────────────────────────

    /** Subscribe and start execution. Returns a Disposable for cancellation. */
    public Disposable subscribe(Consumer<Object> onSuccess, Consumer<Throwable> onError) {
        return chain.subscribe(onSuccess, onError);
    }

    /** Execute synchronously and return the final result. Blocks until complete. */
    public Object blockingGet() {
        return chain.blockingGet();
    }
}
