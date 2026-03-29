package org.tine.client.rx;

import de.desy.tine.client.TLink;
import de.desy.tine.client.TLinkCallback;
import de.desy.tine.dataUtils.TDataType;
import de.desy.tine.definitions.TMode;
import org.reactivestreams.Publisher;
import org.reactivestreams.Subscriber;
import org.reactivestreams.Subscription;

import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;
import java.util.function.Function;

/**
 * Push publisher for a TINE property monitor.
 *
 * Wraps TLink.attach(TMode.CM_POLL, callback, intervalMs): the TINE client
 * polls the property at the given interval and delivers values to all current
 * subscribers via a fan-out TLinkCallback.
 *
 * The TLink is created eagerly at construction time; subscribers are added
 * and removed dynamically. The underlying poll continues until close() is
 * called or the last subscriber cancels and autoClose is enabled.
 *
 * <pre>
 *   RxTineMonitor&lt;Double&gt; monitor = RxTineMonitor.ofDouble(
 *       "/HERA/Context/Device", "PROPERTY", 500);  // poll every 500 ms
 *
 *   Flowable.fromPublisher(monitor)
 *       .subscribe(v -> System.out.println(v));
 *
 *   Thread.currentThread().join(); // keep alive until Ctrl+C
 *   monitor.close();
 * </pre>
 *
 * Thread safety: callbacks arrive on TINE's internal thread pool.
 * The per-subscriber lock (§1.3) serializes delivery to each downstream.
 */
public class RxTineMonitor<T> implements Publisher<T>, TLinkCallback {

    private final TLink link;
    private final Function<TDataType, T> extractor;
    private final List<SubscriberState<T>> subscribers = new CopyOnWriteArrayList<>();

    public RxTineMonitor(String devName, String property,
                         TDataType dout, Function<TDataType, T> extractor,
                         int intervalMs) throws Exception {
        this.extractor = extractor;
        this.link = new TLink(devName, property, dout, null,
                de.desy.tine.definitions.TAccess.CA_READ);
        int status = link.attach(TMode.CM_POLL, this, intervalMs);
        if (status < 0)
            throw new RuntimeException(String.format(
                    "RxTineMonitor attach failed for %s/%s: %s",
                    devName, property, link.getLastError()));
    }

    // ── factory methods ───────────────────────────────────────────────────────

    public static RxTineMonitor<Double> ofDouble(String devName, String property,
                                                  int intervalMs) throws Exception {
        double[] buf = new double[1];
        return new RxTineMonitor<>(devName, property,
                new TDataType(buf),
                dout -> { dout.getData(buf); return buf[0]; },
                intervalMs);
    }

    public static RxTineMonitor<Integer> ofInt(String devName, String property,
                                                int intervalMs) throws Exception {
        int[] buf = new int[1];
        return new RxTineMonitor<>(devName, property,
                new TDataType(buf),
                dout -> { dout.getData(buf); return buf[0]; },
                intervalMs);
    }

    // ── Publisher ─────────────────────────────────────────────────────────────

    @Override
    public void subscribe(Subscriber<? super T> subscriber) {
        if (subscriber == null) throw new NullPointerException("subscriber cannot be null");

        SubscriberState<T> state = new SubscriberState<>(subscriber);

        subscriber.onSubscribe(new Subscription() {
            @Override public void request(long n) { state.request(n); }
            @Override public void cancel()        { state.cancel(); subscribers.remove(state); }
        });

        subscribers.add(state);
    }

    /** Stop the underlying TINE poll and complete all active subscribers. */
    public void close() {
        link.cancel();
        subscribers.forEach(SubscriberState::complete);
        subscribers.clear();
    }

    // ── TLinkCallback ─────────────────────────────────────────────────────────

    @Override
    public void callback(TLink lnk) {
        if (lnk.getLinkStatus() != 0) {
            RuntimeException err = new RuntimeException(
                    "TINE monitor error: " + lnk.getLastError());
            subscribers.forEach(s -> s.onError(err));
            subscribers.clear();
            return;
        }
        T value;
        try {
            value = extractor.apply(lnk.getOutputDataObject());
        } catch (Exception e) {
            subscribers.forEach(s -> s.onError(e));
            subscribers.clear();
            return;
        }
        subscribers.forEach(s -> s.onNext(value));
    }

    // ── per-subscriber state ──────────────────────────────────────────────────

    private static final class SubscriberState<T> {
        private final Subscriber<? super T> downstream;
        private final AtomicLong    requested = new AtomicLong(0);
        private final AtomicBoolean done      = new AtomicBoolean(false);
        private final Object lock = new Object();   // §1.3: serialized delivery

        SubscriberState(Subscriber<? super T> downstream) { this.downstream = downstream; }

        void request(long n) {
            if (done.get()) return;
            if (n <= 0) {
                if (done.compareAndSet(false, true))
                    synchronized (lock) {
                        downstream.onError(new IllegalArgumentException(
                                "§3.9: n must be > 0, was: " + n));
                    }
                return;
            }
            long prev, next;
            do {
                prev = requested.get();
                if (prev == Long.MAX_VALUE) return;
                next = prev + n;
                if (next < 0) next = Long.MAX_VALUE;
            } while (!requested.compareAndSet(prev, next));
        }

        void onNext(T value) {
            if (done.get()) return;
            if (requested.get() == 0) return;   // no demand — drop
            synchronized (lock) {
                if (done.get()) return;
                downstream.onNext(value);
            }
            requested.updateAndGet(r -> r == Long.MAX_VALUE ? r : r - 1);
        }

        void onError(Throwable t) {
            if (done.compareAndSet(false, true))
                synchronized (lock) { downstream.onError(t); }
        }

        void complete() {
            if (done.compareAndSet(false, true))
                synchronized (lock) { downstream.onComplete(); }
        }

        void cancel() { done.set(true); }
    }
}
