package org.tine.client.rx;

import de.desy.tine.client.TLink;
import de.desy.tine.dataUtils.TDataType;
import de.desy.tine.definitions.TAccess;
import org.reactivestreams.Subscriber;

import java.util.function.Function;

/**
 * Single-shot TINE property read as a reactive-streams Publisher.
 *
 * Each subscription creates a new TLink, calls executeAndClose(), extracts
 * the value via the supplied extractor function, emits it, and completes.
 *
 * Factory methods cover the common scalar types so most callers need not
 * supply a TDataType or extractor themselves:
 *
 * <pre>
 *   // read a scalar double
 *   Publisher&lt;Double&gt; p = RxTineRead.ofDouble("/HERA/Context/Device", "PROPERTY");
 *
 *   // read a scalar int
 *   Publisher&lt;Integer&gt; p = RxTineRead.ofInt("/HERA/Context/Device", "PROPERTY");
 *
 *   // full control — custom TDataType and extractor
 *   double[] buf = new double[1];
 *   Publisher&lt;Double&gt; p = new RxTineRead<>(
 *       "/HERA/Context/Device", "PROPERTY",
 *       new TDataType(buf),
 *       dout -> { dout.getData(buf); return buf[0]; }
 *   );
 * </pre>
 *
 * For continuous polling use Flowable.interval(...).flatMapSingle(...) as in the examples.
 */
public class RxTineRead<T> extends RxTine<T> {

    private final TDataType dout;

    public RxTineRead(String devName, String property,
                      TDataType dout, Function<TDataType, T> extractor) {
        super(devName, property, extractor);
        this.dout = dout;
    }

    // ── factory methods for common scalar types ───────────────────────────────

    public static RxTineRead<Double> ofDouble(String devName, String property) {
        double[] buf = new double[1];
        return new RxTineRead<>(devName, property,
                new TDataType(buf),
                dout -> { dout.getData(buf); return buf[0]; });
    }

    public static RxTineRead<Integer> ofInt(String devName, String property) {
        int[] buf = new int[1];
        return new RxTineRead<>(devName, property,
                new TDataType(buf),
                dout -> { dout.getData(buf); return buf[0]; });
    }

    public static RxTineRead<String> ofString(String devName, String property) {
        String[] buf = new String[1];
        return new RxTineRead<>(devName, property,
                new TDataType(buf),
                dout -> { dout.getData(buf); return buf[0]; });
    }

    public static RxTineRead<double[]> ofDoubleArray(String devName, String property, int size) {
        double[] buf = new double[size];
        return new RxTineRead<>(devName, property,
                new TDataType(buf),
                dout -> { dout.getData(buf); return buf.clone(); });
    }

    // ── execution ─────────────────────────────────────────────────────────────

    @Override
    protected void execute(Subscriber<? super T> subscriber) throws Exception {
        TLink link = new TLink(devName, property, dout, null, TAccess.CA_READ);
        int status = link.executeAndClose();
        if (status != 0)
            subscriber.onError(tineError(status, link));
        else {
            subscriber.onNext(extractor.apply(dout));
            subscriber.onComplete();
        }
    }
}
