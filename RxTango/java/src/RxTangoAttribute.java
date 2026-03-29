package org.tango.client.rx;

import org.tango.client.ez.proxy.NoSuchAttributeException;
import org.tango.client.ez.proxy.ReadAttributeException;
import org.tango.client.ez.proxy.TangoProxies;
import org.tango.client.ez.proxy.TangoProxy;

import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionException;
import java.util.concurrent.Future;

public class RxTangoAttribute<T> extends RxTango<T> {
    public RxTangoAttribute(String device, String name) throws Exception {
        this(TangoProxies.newDeviceProxyWrapper(device), name);
    }

    public RxTangoAttribute(TangoProxy proxy, String name) {
        super(proxy, name);
    }

    @Override
    protected Future<T> getFuture() {
        return CompletableFuture.supplyAsync(() -> {
            try {
                return proxy.readAttribute(name);
            } catch (ReadAttributeException | NoSuchAttributeException e) {
                throw new CompletionException(e);
            }
        });
    }
}
