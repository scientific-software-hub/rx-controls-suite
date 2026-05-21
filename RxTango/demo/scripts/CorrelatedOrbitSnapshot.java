///usr/bin/env jbang "$0" "$@" ; exit $?
//JAVA 11+
//REPOS mavencentral,jtango=https://maven.pkg.github.com/scientific-software-hub/JTango
//DEPS io.reactivex.rxjava3:rxjava:3.1.8
//DEPS org.reactivestreams:reactive-streams:1.0.4
//DEPS org.waltz.tango:ez:1.6.3
//DEPS org.waltz.tango.orb:tangorb:1.6.3
//SOURCES ../lib/RingDevices.java ../../java/src/RxTango.java ../../java/src/RxTangoAttribute.java ../../java/src/RxTangoAttributeWrite.java

import io.reactivex.rxjava3.core.Flowable;
import io.reactivex.rxjava3.core.Single;

import java.util.Locale;
import java.util.concurrent.TimeUnit;

public class CorrelatedOrbitSnapshot {
    public static void main(String[] args) {
        String controller = args.length > 0 ? args[0] : RingDevices.DEFAULT_CONTROLLER;
        String sector = args.length > 1 ? args[1] : RingDevices.DEFAULT_SECTORS.get(4);
        long intervalMs = args.length > 2 ? Long.parseLong(args[2]) : 500L;

        System.out.printf("Correlated reads between %s and %s%n", controller, sector);
        System.out.println("time(s)  beam(mA)  lifetime(h)  orbit(um)  vacuum(nbar)  dose(mSv/h)");
        System.out.println("-------  --------  -----------  ---------  ------------  -----------");

        Flowable.interval(0, intervalMs, TimeUnit.MILLISECONDS)
                .concatMapSingle(tick -> Single.zip(
                        RingDevices.readController(controller),
                        RingDevices.readSector(sector),
                        (ctrl, sec) -> new Snapshot(ctrl, sec)
                ))
                .blockingSubscribe(
                        snapshot -> System.out.printf(Locale.ROOT,
                                "%7.1f  %8.1f  %11.2f  %9.1f  %12.2f  %11.2f%n",
                                snapshot.controller().simulationTime(),
                                snapshot.controller().beamCurrent(),
                                snapshot.controller().lifetimeHours(),
                                snapshot.sector().orbitX(),
                                snapshot.sector().vacuumPressure(),
                                snapshot.sector().radiationDoseRate()),
                        err -> System.err.println("Fatal: " + err.getMessage())
                );
    }

    private record Snapshot(RingDevices.ControllerSnapshot controller,
                            RingDevices.SectorSnapshot sector) {
    }
}
