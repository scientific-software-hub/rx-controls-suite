package org.tine.client.rx;

import de.desy.tine.client.TLink;
import de.desy.tine.dataUtils.TDataType;
import de.desy.tine.definitions.TAccess;
import org.reactivestreams.Subscriber;

/**
 * Single-shot TINE property write as a reactive-streams Publisher.
 *
 * Each subscription creates a new TLink, executes the write, and emits
 * the written value on success so the value can flow into the next step
 * of a pipeline.
 *
 * <pre>
 *   // write a scalar double
 *   Publisher&lt;Double&gt; p = RxTineWrite.ofDouble("/HERA/Context/Device", "SETPOINT", 42.0);
 * </pre>
 *
 * For a read-then-write pipeline:
 * <pre>
 *   Flowable.fromPublisher(RxTineRead.ofDouble(dev, "SENSOR"))
 *       .map(v -> v * gainFactor + offset)
 *       .flatMapSingle(calibrated ->
 *           Flowable.fromPublisher(RxTineWrite.ofDouble(dev, "SETPOINT", calibrated))
 *                   .firstOrError()
 *       )
 *       .blockingSubscribe(v -> System.out.println("wrote: " + v));
 * </pre>
 */
public class RxTineWrite<T> extends RxTine<T> {

    private final TDataType din;
    private final T value;

    public RxTineWrite(String devName, String property, TDataType din, T value) {
        super(devName, property, ignored -> value);
        this.din   = din;
        this.value = value;
    }

    // ── factory methods ───────────────────────────────────────────────────────

    public static RxTineWrite<Double> ofDouble(String devName, String property, double value) {
        double[] buf = { value };
        return new RxTineWrite<>(devName, property, new TDataType(buf), value);
    }

    public static RxTineWrite<Integer> ofInt(String devName, String property, int value) {
        int[] buf = { value };
        return new RxTineWrite<>(devName, property, new TDataType(buf), value);
    }

    public static RxTineWrite<String> ofString(String devName, String property, String value) {
        return new RxTineWrite<>(devName, property, new TDataType(value), value);
    }

    // ── execution ─────────────────────────────────────────────────────────────

    @Override
    protected void execute(Subscriber<? super T> subscriber) throws Exception {
        TLink link = new TLink(devName, property, null, din, TAccess.CA_WRITE);
        int status = link.execute();
        link.cancel();
        if (status != 0)
            subscriber.onError(tineError(status, link));
        else {
            subscriber.onNext(value);
            subscriber.onComplete();
        }
    }
}
