package org.tango.client.rx;

import io.reactivex.rxjava3.core.Flowable;
import io.reactivex.rxjava3.core.Single;
import io.reactivex.rxjava3.disposables.Disposable;
import io.reactivex.rxjava3.functions.Consumer;

import java.util.function.Function;

/**
 * Fluent builder for sequential Tango operations.
 *
 * Each method appends a step to an internal Rx chain. Steps are NOT executed
 * until a terminal method (subscribe / blockingGet) is called.
 *
 * Results flow through the chain: each step receives the result of the
 * previous step, allowing later steps to compute their inputs dynamically.
 *
 * Example — read, calibrate, write back:
 * <pre>
 *   new TangoClient()
 *       .readAttribute(device, "raw_temperature")
 *       .writeAttribute(device, "calibrated", v -> ((Number) v).doubleValue() * 1.05 + 0.3)
 *       .subscribe(result -> System.out.println("wrote: " + result),
 *                  Throwable::printStackTrace);
 * </pre>
 *
 * Example — multi-device pipeline:
 * <pre>
 *   new TangoClient()
 *       .executeCommand(device1, "Init")
 *       .readAttribute(device2, "status")
 *       .writeAttribute(device3, "setpoint", v -> ((Number) v).doubleValue() * factor)
 *       .blockingGet();
 * </pre>
 */
public class TangoClient {

    // Sentinel seed — ignored by the first step, but must be non-null for RxJava3.
    private static final Object SEED = new Object();
    private Single<Object> chain = Single.just(SEED);

    // -------------------------------------------------------------------------
    // readAttribute
    // -------------------------------------------------------------------------

    /** Read an attribute. The read value becomes the input for the next step. */
    public TangoClient readAttribute(String device, String attribute) {
        chain = chain.flatMap(__ ->
                Flowable.fromPublisher(new RxTangoAttribute<>(device, attribute))
                        .firstOrError()
                        .cast(Object.class)
        );
        return this;
    }

    // -------------------------------------------------------------------------
    // writeAttribute
    // -------------------------------------------------------------------------

    /** Write a static value. The written value becomes the input for the next step. */
    public TangoClient writeAttribute(String device, String attribute, Object value) {
        chain = chain.flatMap(__ ->
                Flowable.fromPublisher(new RxTangoAttributeWrite<>(device, attribute, value))
                        .ignoreElements()
                        .andThen(Single.just(value))
                        .cast(Object.class)
        );
        return this;
    }

    /**
     * Write a value computed from the previous step's result.
     * The written value becomes the input for the next step.
     *
     * Use {@code Function.identity()} to pass the previous result through unchanged.
     */
    public TangoClient writeAttribute(String device, String attribute, Function<Object, Object> valueFromPrev) {
        chain = chain.flatMap(prev -> {
            Object value = valueFromPrev.apply(prev);
            return Flowable.fromPublisher(new RxTangoAttributeWrite<>(device, attribute, value))
                    .ignoreElements()
                    .andThen(Single.just(value))
                    .cast(Object.class);
        });
        return this;
    }

    // -------------------------------------------------------------------------
    // executeCommand
    // -------------------------------------------------------------------------

    /** Execute a command with no input. The command result becomes the input for the next step. */
    public TangoClient executeCommand(String device, String command) {
        chain = chain.flatMap(__ ->
                Flowable.fromPublisher(new RxTangoCommand<>(device, command))
                        .firstOrError()
                        .cast(Object.class)
        );
        return this;
    }

    /** Execute a command with a static argument. */
    public TangoClient executeCommand(String device, String command, Object argin) {
        chain = chain.flatMap(__ ->
                Flowable.fromPublisher(new RxTangoCommand<Object, Object>(device, command, argin))
                        .firstOrError()
                        .cast(Object.class)
        );
        return this;
    }

    /**
     * Execute a command, computing the argument from the previous step's result.
     * Use this to feed the output of one operation into the input of another.
     */
    public TangoClient executeCommand(String device, String command, Function<Object, Object> arginFromPrev) {
        chain = chain.flatMap(prev ->
                Flowable.fromPublisher(new RxTangoCommand<Object, Object>(device, command, arginFromPrev.apply(prev)))
                        .firstOrError()
                        .cast(Object.class)
        );
        return this;
    }

    // -------------------------------------------------------------------------
    // map — arbitrary in-chain transformation (no Tango I/O)
    // -------------------------------------------------------------------------

    /** Apply a pure transformation to the current value without any Tango call. */
    public TangoClient map(Function<Object, Object> transform) {
        chain = chain.map(transform::apply);
        return this;
    }

    // -------------------------------------------------------------------------
    // Terminal operators
    // -------------------------------------------------------------------------

    /**
     * Subscribe to the chain. Execution starts immediately.
     * Returns a Disposable that can be used to cancel an in-flight operation.
     */
    public Disposable subscribe(Consumer<Object> onSuccess, Consumer<Throwable> onError) {
        return chain.subscribe(onSuccess, onError);
    }

    /**
     * Execute the chain synchronously and return the final result.
     * Blocks until the chain completes or throws on error.
     */
    public Object blockingGet() {
        return chain.blockingGet();
    }
}
