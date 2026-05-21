import io.reactivex.rxjava3.core.Flowable;
import io.reactivex.rxjava3.core.Single;
import org.tango.client.rx.RxTangoAttribute;
import org.tango.client.rx.RxTangoAttributeWrite;

import java.util.ArrayList;
import java.util.List;

final class RingDevices {
    static final String DEFAULT_CONTROLLER = "tango://localhost:10000/sr/demo/controller";
    static final List<String> DEFAULT_SECTORS = List.of(
            "tango://localhost:10000/sr/demo/sector01",
            "tango://localhost:10000/sr/demo/sector02",
            "tango://localhost:10000/sr/demo/sector03",
            "tango://localhost:10000/sr/demo/sector04",
            "tango://localhost:10000/sr/demo/sector05",
            "tango://localhost:10000/sr/demo/sector06",
            "tango://localhost:10000/sr/demo/sector07",
            "tango://localhost:10000/sr/demo/sector08"
    );

    record ControllerSnapshot(long scenarioId,
                              double beamCurrentTarget,
                              double orbitCorrection,
                              double simulationTime,
                              double beamCurrent,
                              double lifetimeHours,
                              long interlockCount) {
    }

    record SectorSnapshot(String device,
                          long sectorIndex,
                          double beamCurrent,
                          double orbitX,
                          double vacuumPressure,
                          double radiationDoseRate,
                          double beamLossFraction) {
    }

    private RingDevices() {
    }

    static Single<ControllerSnapshot> readController(String device) {
        return Single.zip(
                readLong(device, "ScenarioId"),
                readDouble(device, "BeamCurrentTarget"),
                readDouble(device, "OrbitCorrection"),
                readDouble(device, "SimulationTime"),
                readDouble(device, "BeamCurrent"),
                readDouble(device, "LifetimeHours"),
                readLong(device, "InterlockCount"),
                ControllerSnapshot::new
        );
    }

    static Single<SectorSnapshot> readSector(String device) {
        return Single.zip(
                readLong(device, "SectorIndex"),
                readDouble(device, "BeamCurrent"),
                readDouble(device, "OrbitX"),
                readDouble(device, "VacuumPressure"),
                readDouble(device, "RadiationDoseRate"),
                readDouble(device, "BeamLossFraction"),
                (sectorIndex, beamCurrent, orbitX, vacuumPressure, radiationDoseRate, beamLossFraction) ->
                        new SectorSnapshot(device, sectorIndex, beamCurrent, orbitX, vacuumPressure, radiationDoseRate, beamLossFraction)
        );
    }

    static Single<List<SectorSnapshot>> readAllSectors(List<String> devices) {
        return Flowable.fromIterable(devices)
                .concatMapSingle(RingDevices::readSector)
                .toList();
    }

    static Single<Double> writeOrbitCorrection(String device, double value) {
        return Single.defer(() -> Flowable.fromPublisher(new RxTangoAttributeWrite<>(device, "OrbitCorrection", value))
                .ignoreElements()
                .andThen(Single.just(value)));
    }

    static Single<Long> writeScenario(String device, long scenarioId) {
        return Single.defer(() -> Flowable.fromPublisher(new RxTangoAttributeWrite<>(device, "ScenarioId", (int) scenarioId))
                .ignoreElements()
                .andThen(Single.just(scenarioId)));
    }

    static long maxLossSector(List<SectorSnapshot> sectors) {
        SectorSnapshot best = sectors.get(0);
        for (SectorSnapshot sector : sectors) {
            if (sector.beamLossFraction() > best.beamLossFraction()) {
                best = sector;
            }
        }
        return best.sectorIndex();
    }

    static List<String> sectorDevices(String[] args, int startIndex) {
        List<String> devices = new ArrayList<>();
        for (int i = startIndex; i < args.length; i++) {
            devices.add(args[i]);
        }
        return devices.isEmpty() ? DEFAULT_SECTORS : List.copyOf(devices);
    }

    private static Single<Double> readDouble(String device, String attribute) {
        return Single.defer(() -> Flowable.fromPublisher(new RxTangoAttribute<>(device, attribute))
                .firstOrError()
                .map(value -> ((Number) value).doubleValue()));
    }

    private static Single<Long> readLong(String device, String attribute) {
        return Single.defer(() -> Flowable.fromPublisher(new RxTangoAttribute<>(device, attribute))
                .firstOrError()
                .map(value -> ((Number) value).longValue()));
    }
}
