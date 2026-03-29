package org.tango.client.rx;

import org.tango.client.ez.proxy.ExecuteCommandException;
import org.tango.client.ez.proxy.NoSuchCommandException;
import org.tango.client.ez.proxy.TangoProxies;
import org.tango.client.ez.proxy.TangoProxy;

import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionException;
import java.util.concurrent.Future;

public class RxTangoCommand<T, V> extends RxTango<T> {

    private final V input;

    public RxTangoCommand(TangoProxy proxy, String name) {
        super(proxy, name);
        this.input = null;
    }

    public RxTangoCommand(TangoProxy proxy, String name, V input) {
        super(proxy, name);
        this.input = input;
    }

    public RxTangoCommand(String device, String name) throws Exception {
        this(TangoProxies.newDeviceProxyWrapper(device), name);
    }

    public RxTangoCommand(String device, String name, V input) throws Exception {
        this(TangoProxies.newDeviceProxyWrapper(device), name, input);
    }

    @Override
    protected Future<T> getFuture() {
        return CompletableFuture.supplyAsync(() -> {
            try {
                if (this.input != null)
                    return proxy.executeCommand(name, input);
                else
                    return proxy.executeCommand(name);
            } catch (ExecuteCommandException | NoSuchCommandException e) {
                throw new CompletionException(e);
            }
        });
    }
}
