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

import java.util.List;
import java.util.Locale;
import java.util.concurrent.TimeUnit;

public class SmoothedCurrentWriter {
    public static void main(String[] args) {
        String controller = args.length > 0 ? args[0] : RingDevices.DEFAULT_CONTROLLER;
        long intervalMs = args.length > 1 ? Long.parseLong(args[1]) : 300L;
        int window = args.length > 2 ? Integer.parseInt(args[2]) : 5;
        double relativeDelta = args.length > 3 ? Double.parseDouble(args[3]) : 0.05;

        System.out.printf("Smoothed write-back to %s%n", controller);
        System.out.println("time(s)  raw(mA)  mean(mA)  orbitCorrection");
        System.out.println("-------  -------  --------  ---------------");

        Flowable.interval(0, intervalMs, TimeUnit.MILLISECONDS)
                .concatMapSingle(tick -> RingDevices.readController(controller))
                .buffer(window, 1)
                .filter(samples -> samples.size() == window)
                .map(SmoothedCurrentWriter::toAction)
                .distinctUntilChanged((left, right) ->
                        relativeChange(left.meanCurrent(), right.meanCurrent()) < relativeDelta)
                .concatMapSingle(action -> RingDevices.writeOrbitCorrection(controller, action.meanCurrent() / 120.0 - 2.0)
                        .map(written -> action.withCorrection(written)))
                .blockingSubscribe(
                        action -> System.out.printf(Locale.ROOT,
                                "%7.1f  %7.1f  %8.1f  %+15.3f%n",
                                action.time(),
                                action.rawCurrent(),
                                action.meanCurrent(),
                                action.orbitCorrection()),
                        err -> System.err.println("Fatal: " + err.getMessage())
                );
    }

    private static Action toAction(List<RingDevices.ControllerSnapshot> samples) {
        RingDevices.ControllerSnapshot last = samples.get(samples.size() - 1);
        double mean = samples.stream().mapToDouble(RingDevices.ControllerSnapshot::beamCurrent).average().orElse(0.0);
        return new Action(last.simulationTime(), last.beamCurrent(), mean, Double.NaN);
    }

    private static double relativeChange(double previous, double current) {
        return Math.abs(previous - current) / Math.max(1.0, Math.abs(previous));
    }

    private record Action(double time, double rawCurrent, double meanCurrent, double orbitCorrection) {
        Action withCorrection(double correction) {
            return new Action(time, rawCurrent, meanCurrent, correction);
        }
    }
}
