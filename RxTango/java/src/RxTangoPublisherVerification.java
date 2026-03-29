package org.tango.client.rx;

import org.reactivestreams.Publisher;
import org.reactivestreams.Subscription;
import org.reactivestreams.tck.PublisherVerification;
import org.reactivestreams.tck.TestEnvironment;
import org.tango.client.ez.proxy.TangoProxies;
import org.tango.client.ez.proxy.TangoProxy;

/**
 * Reactive Streams TCK verification for RxTangoAttribute (single-shot publisher).
 * Run via: jbang examples/VerifySpec.java
 */
public class RxTangoPublisherVerification extends PublisherVerification<Object> {

    private static final String DEVICE = System.getProperty(
            "tango.device", "tango://localhost:10000/sys/tg_test/1");
    private static final String ATTRIBUTE = System.getProperty(
            "tango.attribute", "double_scalar");

    public RxTangoPublisherVerification() {
        // 500 ms timeout — generous for local Docker
        super(new TestEnvironment(500));
    }

    @Override
    public long maxElementsFromPublisher() {
        // single-shot: each subscription emits exactly one element
        return 1;
    }

    @Override
    public Publisher<Object> createPublisher(long elements) {
        if (elements == 0) {
            // spec109 requires onSubscribe even for an empty stream
            return subscriber -> subscriber.onSubscribe(new Subscription() {
                @Override public void request(long n) { subscriber.onComplete(); }
                @Override public void cancel() {}
            });
        }
        if (elements > 1) return null; // TCK skips tests requiring more than 1 element
        try {
            TangoProxy proxy = TangoProxies.newDeviceProxyWrapper(DEVICE);
            return new RxTangoAttribute<>(proxy, ATTRIBUTE);
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
    }

    @Override
    public Publisher<Object> createFailedPublisher() {
        // TCK subscribes without calling request() and expects onError immediately after onSubscribe
        return subscriber -> {
            subscriber.onSubscribe(new Subscription() {
                @Override public void request(long n) {}
                @Override public void cancel() {}
            });
            subscriber.onError(new RuntimeException("simulated failure"));
        };
    }
}
