package org.tango.client.rx;

import org.reactivestreams.Publisher;
import org.reactivestreams.Subscriber;
import org.reactivestreams.Subscription;
import org.tango.client.ez.proxy.TangoProxy;

import java.util.concurrent.ExecutionException;
import java.util.concurrent.Future;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;

public abstract class RxTango<T> implements Publisher<T> {
    protected final TangoProxy proxy;
    protected final String name;

    public RxTango(TangoProxy proxy, String name) {
        this.proxy = proxy;
        this.name = name;
    }

    @Override
    public void subscribe(Subscriber<? super T> subscriber) {
        if (subscriber == null) throw new NullPointerException("subscriber can not be null!");

        AtomicBoolean done      = new AtomicBoolean(false);
        AtomicBoolean cancelled = new AtomicBoolean(false);
        AtomicReference<Future<T>> futureRef = new AtomicReference<>();

        subscriber.onSubscribe(new Subscription() {
            @Override
            public void request(long n) {
                if (cancelled.get()) return;
                // §3.9: must signal onError for non-positive request
                if (n <= 0) {
                    if (done.compareAndSet(false, true))
                        subscriber.onError(new IllegalArgumentException(
                                "§3.9: n must be > 0, was: " + n));
                    return;
                }
                // guard: only emit once regardless of how many times request() is called
                if (!done.compareAndSet(false, true)) return;

                // lazy: start the async operation only when demand arrives
                Future<T> future = getFuture();
                futureRef.set(future);

                try {
                    T value = future.get();
                    if (!cancelled.get()) {
                        subscriber.onNext(value);
                        if (!cancelled.get()) subscriber.onComplete();
                    }
                } catch (InterruptedException | ExecutionException e) {
                    if (!cancelled.get()) subscriber.onError(e);
                }
            }

            @Override
            public void cancel() {
                cancelled.set(true);
                Future<T> f = futureRef.get();
                if (f != null) f.cancel(true);
            }
        });
    }

    protected abstract Future<T> getFuture();
}
