///usr/bin/env jbang "$0" "$@" ; exit $?
//JAVA 11+
//REPOS mavencentral,jtango=https://maven.pkg.github.com/scientific-software-hub/JTango
//DEPS io.reactivex.rxjava3:rxjava:3.1.8
//DEPS org.reactivestreams:reactive-streams:1.0.4
//DEPS org.waltz.tango:ez:1.6.3
//DEPS org.waltz.tango.orb:tangorb:1.6.3
//SOURCES ../lib/RingDevices.java ../../java/src/RxTango.java ../../java/src/RxTangoAttribute.java ../../java/src/RxTangoAttributeWrite.java

import io.reactivex.rxjava3.core.Flowable;
import io.reactivex.rxjava3.schedulers.Schedulers;

import java.util.Locale;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicLong;

public class RingBackpressure {
    public static void main(String[] args) {
        String sector = args.length > 0 ? args[0] : RingDevices.DEFAULT_SECTORS.get(4);
        long pollMs = args.length > 1 ? Long.parseLong(args[1]) : 60L;
        long processMs = args.length > 2 ? Long.parseLong(args[2]) : 350L;

        String strategy = "latest";
        int bufferSize = 8;
        for (int i = 3; i < args.length; i++) {
            if ("--strategy".equals(args[i]) && i + 1 < args.length) {
                strategy = args[++i];
            } else if ("--buffer-size".equals(args[i]) && i + 1 < args.length) {
                bufferSize = Integer.parseInt(args[++i]);
            }
        }

        AtomicLong produced = new AtomicLong();
        AtomicLong consumed = new AtomicLong();

        Flowable<RingDevices.SectorSnapshot> upstream = Flowable.interval(0, pollMs, TimeUnit.MILLISECONDS)
                .concatMapSingle(tick -> RingDevices.readSector(sector))
                .doOnNext(snapshot -> produced.incrementAndGet());

        Flowable<RingDevices.SectorSnapshot> bounded = switch (strategy) {
            case "latest" -> upstream.onBackpressureLatest();
            case "drop" -> upstream.onBackpressureDrop();
            case "buffer" -> upstream.onBackpressureBuffer(bufferSize);
            default -> throw new IllegalArgumentException("Unknown strategy: " + strategy);
        };

        System.out.printf("Backpressure demo on %s%n", sector);
        System.out.println("prod  cons  lag   orbit(um)  vacuum(nbar)  loss");
        System.out.println("----  ----  ----  ---------  ------------  ----");

        bounded.observeOn(Schedulers.single())
                .blockingSubscribe(
                        snapshot -> {
                            long p = produced.get();
                            long c = consumed.incrementAndGet();
                            System.out.printf(Locale.ROOT,
                                    "%4d  %4d  %4d  %9.1f  %12.2f  %4.2f%n",
                                    p, c, p - c, snapshot.orbitX(), snapshot.vacuumPressure(), snapshot.beamLossFraction());
                            Thread.sleep(processMs);
                        },
                        err -> System.err.printf("%nERROR (%s): %s%n",
                                err.getClass().getSimpleName(), err.getMessage())
                );
    }
}
