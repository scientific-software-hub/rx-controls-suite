package org.tango.client.rx;

import org.tango.client.ez.proxy.NoSuchAttributeException;
import org.tango.client.ez.proxy.TangoProxies;
import org.tango.client.ez.proxy.TangoProxy;
import org.tango.client.ez.proxy.WriteAttributeException;

import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionException;
import java.util.concurrent.Future;

public class RxTangoAttributeWrite<T> extends RxTango<Void> {
    private final T value;

    public RxTangoAttributeWrite(TangoProxy proxy, String name, T value) {
        super(proxy, name);
        this.value = value;
    }

    public RxTangoAttributeWrite(String device, String name, T value) throws Exception {
        this(TangoProxies.newDeviceProxyWrapper(device), name, value);
    }

    @Override
    protected Future<Void> getFuture() {
        return CompletableFuture.supplyAsync(() -> {
            try {
                proxy.writeAttribute(name, value);
                return null;
            } catch (WriteAttributeException | NoSuchAttributeException e) {
                throw new CompletionException(e);
            }
        });
    }
}
