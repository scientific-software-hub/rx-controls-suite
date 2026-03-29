package org.tine.client.rx;

import de.desy.tine.client.TLink;
import de.desy.tine.dataUtils.TDataType;
import de.desy.tine.definitions.TAccess;
import de.desy.tine.definitions.TErrorList;
import org.reactivestreams.Publisher;
import org.reactivestreams.Subscriber;
import org.reactivestreams.Subscription;

import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.Function;

/**
 * Abstract base for single-shot TINE property publishers.
 *
 * Each subscription creates a new TLink, calls executeAndClose(), maps the
 * result through the extractor, and emits exactly one item followed by
 * onComplete — or onError if the status code is non-zero.
 *
 * Subclasses supply the TDataType and TAccess flag; this class handles
 * the reactive-streams contract (§1.1, §1.7, §3.9).
 *
 * Production code depends only on org.reactivestreams interfaces.
 * Use RxJava3's Flowable.fromPublisher(new RxTineRead<>(...)) to access
 * the full RxJava operator set.
 */
public abstract class RxTine<T> implements Publisher<T> {

    protected final String devName;
    protected final String property;
    protected final Function<TDataType, T> extractor;

    protected RxTine(String devName, String property, Function<TDataType, T> extractor) {
        this.devName   = devName;
        this.property  = property;
        this.extractor = extractor;
    }

    @Override
    public void subscribe(Subscriber<? super T> subscriber) {
        if (subscriber == null) throw new NullPointerException("subscriber cannot be null");

        subscriber.onSubscribe(new Subscription() {
            private final AtomicBoolean done = new AtomicBoolean(false);

            @Override
            public void request(long n) {
                if (n <= 0) {
                    if (done.compareAndSet(false, true))
                        subscriber.onError(new IllegalArgumentException(
                                "§3.9: n must be > 0, was: " + n));
                    return;
                }
                if (!done.compareAndSet(false, true)) return;
                try {
                    execute(subscriber);
                } catch (Exception e) {
                    subscriber.onError(e);
                }
            }

            @Override
            public void cancel() {
                done.set(true);
            }
        });
    }

    /**
     * Subclasses implement the actual TLink operation here.
     * Must call exactly one of subscriber.onNext + onComplete, or subscriber.onError.
     */
    protected abstract void execute(Subscriber<? super T> subscriber) throws Exception;

    // ── shared helpers ────────────────────────────────────────────────────────

    /** Convert a non-zero TINE status code into an exception. */
    protected static RuntimeException tineError(int status, TLink link) {
        return new RuntimeException(String.format(
                "TINE error %d: %s", status, link.getLastError()));
    }
}
