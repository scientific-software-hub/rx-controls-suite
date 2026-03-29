package org.tango.client.rx;

import org.reactivestreams.Publisher;
import org.reactivestreams.Subscriber;
import org.reactivestreams.Subscription;
import org.tango.client.ez.proxy.EventData;
import org.tango.client.ez.proxy.TangoEvent;
import org.tango.client.ez.proxy.TangoEventListener;
import org.tango.client.ez.proxy.TangoProxy;

import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;

public class RxTangoAttributeChangePublisher<T> implements Publisher<EventData<T>>, TangoEventListener<T> {
    private final TangoProxy proxy;
    private final String name;
    private final TangoEvent event;
    private final List<SubscriberState<T>> subscribers = new CopyOnWriteArrayList<>();

    public RxTangoAttributeChangePublisher(TangoProxy proxy, String name) throws Exception {
        this(proxy, name, TangoEvent.CHANGE);
    }

    public RxTangoAttributeChangePublisher(TangoProxy proxy, String name, TangoEvent event) throws Exception {
        this.proxy = proxy;
        this.name = name;
        this.event = event;
        this.proxy.subscribeToEvent(name, event);
        this.proxy.addEventListener(name, event, this);
    }

    @Override
    public void subscribe(Subscriber<? super EventData<T>> subscriber) {
        if (subscriber == null) throw new NullPointerException("subscriber can not be null");

        SubscriberState<T> state = new SubscriberState<>(subscriber);

        subscriber.onSubscribe(new Subscription() {
            @Override
            public void request(long n) {
                state.request(n);
            }

            @Override
            public void cancel() {
                state.cancel();
                subscribers.remove(state);
            }
        });

        subscribers.add(state);
    }

    @Override
    public void onEvent(EventData<T> eventData) {
        subscribers.forEach(s -> s.onNext(eventData));
    }

    @Override
    public void onError(Exception e) {
        subscribers.forEach(s -> s.onError(e));
        subscribers.clear();
    }

    /**
     * Per-subscriber state wrapper that enforces:
     * - §1.1  demand tracking (events are dropped when requested == 0)
     * - §1.3  serialized delivery (synchronized lock guards against concurrent Tango event threads)
     * - §1.7  terminal state — no signals after onError or cancel
     * - §3.9  request(n <= 0) signals onError(IllegalArgumentException)
     */
    private static final class SubscriberState<T> {
        private final Subscriber<? super EventData<T>> downstream;
        private final AtomicLong    requested = new AtomicLong(0);
        private final AtomicBoolean done      = new AtomicBoolean(false);
        // serializes concurrent onNext calls from different Tango event threads (§1.3)
        private final Object lock = new Object();

        SubscriberState(Subscriber<? super EventData<T>> downstream) {
            this.downstream = downstream;
        }

        void request(long n) {
            if (done.get()) return;
            if (n <= 0) {
                if (done.compareAndSet(false, true)) {
                    synchronized (lock) {
                        downstream.onError(new IllegalArgumentException(
                                "§3.9: n must be > 0, was: " + n));
                    }
                }
                return;
            }
            // accumulate demand, cap at Long.MAX_VALUE to signal unbounded
            long prev, next;
            do {
                prev = requested.get();
                if (prev == Long.MAX_VALUE) return;
                next = prev + n;
                if (next < 0) next = Long.MAX_VALUE; // overflow guard
            } while (!requested.compareAndSet(prev, next));
        }

        void onNext(EventData<T> event) {
            if (done.get()) return;
            if (requested.get() == 0) return; // no demand — drop
            synchronized (lock) {
                if (done.get()) return;
                downstream.onNext(event);
            }
            // don't decrement unbounded demand (Long.MAX_VALUE)
            requested.updateAndGet(r -> r == Long.MAX_VALUE ? r : r - 1);
        }

        void onError(Throwable t) {
            if (done.compareAndSet(false, true)) {
                synchronized (lock) {
                    downstream.onError(t);
                }
            }
        }

        void cancel() {
            done.set(true);
        }
    }
}
