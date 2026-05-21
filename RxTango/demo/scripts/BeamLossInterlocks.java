///usr/bin/env jbang "$0" "$@" ; exit $?
//JAVA 11+
//REPOS mavencentral,jtango=https://maven.pkg.github.com/scientific-software-hub/JTango
//DEPS io.reactivex.rxjava3:rxjava:3.1.8
//DEPS org.reactivestreams:reactive-streams:1.0.4
//DEPS org.waltz.tango:ez:1.6.3
//DEPS org.waltz.tango.orb:tangorb:1.6.3
//SOURCES ../lib/RingDevices.java ../../java/src/RxTango.java ../../java/src/RxTangoAttribute.java ../../java/src/RxTangoAttributeWrite.java

import io.reactivex.rxjava3.core.Flowable;

import java.util.List;
import java.util.Locale;
import java.util.concurrent.TimeUnit;

public class BeamLossInterlocks {
    public static void main(String[] args) {
        List<String> sectors = RingDevices.sectorDevices(args, 0);
        long intervalMs = 700L;

        System.out.println("Interlock fan-in from sector devices");

        Flowable.interval(0, intervalMs, TimeUnit.MILLISECONDS)
                .concatMapSingle(tick -> RingDevices.readAllSectors(sectors))
                .publish(shared -> Flowable.mergeArray(
                        shared.flatMapIterable(list -> list)
                                .filter(sector -> sector.beamLossFraction() >= 0.40)
                                .map(sector -> String.format(Locale.ROOT,
                                        "LOSS     S%02d %.0f%% beam loss",
                                        sector.sectorIndex(), sector.beamLossFraction() * 100.0)),
                        shared.flatMapIterable(list -> list)
                                .filter(sector -> sector.vacuumPressure() >= 1.55)
                                .map(sector -> String.format(Locale.ROOT,
                                        "VACUUM   S%02d %.2f nbar",
                                        sector.sectorIndex(), sector.vacuumPressure())),
                        shared.flatMapIterable(list -> list)
                                .filter(sector -> sector.radiationDoseRate() >= 1.10)
                                .map(sector -> String.format(Locale.ROOT,
                                        "RADIATION S%02d %.2f mSv/h",
                                        sector.sectorIndex(), sector.radiationDoseRate()))
                ))
                .distinctUntilChanged()
                .blockingSubscribe(
                        System.out::println,
                        err -> System.err.println("Fatal: " + err.getMessage())
                );
    }
}
