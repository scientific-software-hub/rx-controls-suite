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

import java.util.Comparator;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.TimeUnit;

public class StorageRingDashboard {
    public static void main(String[] args) {
        String controller = args.length > 0 ? args[0] : RingDevices.DEFAULT_CONTROLLER;
        List<String> sectors = RingDevices.sectorDevices(args, 1);
        long intervalMs = 1000L;

        System.out.printf("Storage ring dashboard%ncontroller=%s%nsectors=%d%n%n",
                controller, sectors.size());

        Flowable.interval(0, intervalMs, TimeUnit.MILLISECONDS)
                .concatMapSingle(tick -> Single.zip(
                        RingDevices.readController(controller),
                        RingDevices.readAllSectors(sectors),
                        (controllerSnapshot, sectorSnapshots) -> new DashboardSnapshot(controllerSnapshot, sectorSnapshots)
                ))
                .blockingSubscribe(
                        StorageRingDashboard::printSnapshot,
                        err -> System.err.println("Fatal: " + err.getMessage())
                );
    }

    private static void printSnapshot(DashboardSnapshot snapshot) {
        RingDevices.ControllerSnapshot controller = snapshot.controller();
        RingDevices.SectorSnapshot worstOrbit = snapshot.sectors().stream()
                .max(Comparator.comparingDouble(sector -> Math.abs(sector.orbitX())))
                .orElseThrow();
        RingDevices.SectorSnapshot worstVacuum = snapshot.sectors().stream()
                .max(Comparator.comparingDouble(RingDevices.SectorSnapshot::vacuumPressure))
                .orElseThrow();
        RingDevices.SectorSnapshot worstDose = snapshot.sectors().stream()
                .max(Comparator.comparingDouble(RingDevices.SectorSnapshot::radiationDoseRate))
                .orElseThrow();

        System.out.printf(Locale.ROOT,
                "t=%6.1f s  scenario=%d  current=%6.1f mA  lifetime=%5.2f h  correction=%+4.2f  interlocks=%d%n",
                controller.simulationTime(),
                controller.scenarioId(),
                controller.beamCurrent(),
                controller.lifetimeHours(),
                controller.orbitCorrection(),
                controller.interlockCount());
        System.out.printf(Locale.ROOT, "  worst orbit  : S%02d %+6.1f um%n", worstOrbit.sectorIndex(), worstOrbit.orbitX());
        System.out.printf(Locale.ROOT, "  worst vacuum : S%02d %5.2f nbar%n", worstVacuum.sectorIndex(), worstVacuum.vacuumPressure());
        System.out.printf(Locale.ROOT, "  worst dose   : S%02d %5.2f mSv/h%n", worstDose.sectorIndex(), worstDose.radiationDoseRate());
        System.out.print("  sectors      :");
        for (RingDevices.SectorSnapshot sector : snapshot.sectors()) {
            System.out.printf(Locale.ROOT, "  S%02d orbit=%+5.1f vac=%4.2f loss=%4.2f",
                    sector.sectorIndex(), sector.orbitX(), sector.vacuumPressure(), sector.beamLossFraction());
        }
        System.out.println();
        System.out.println();
    }

    private record DashboardSnapshot(RingDevices.ControllerSnapshot controller,
                                     List<RingDevices.SectorSnapshot> sectors) {
    }
}
