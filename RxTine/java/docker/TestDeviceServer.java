import de.desy.tine.server.equipment.TEquipmentModule;
import de.desy.tine.server.equipment.TExportProperty;
import de.desy.tine.definitions.TAccess;
import de.desy.tine.definitions.TFormat;

import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

/**
 * Minimal TINE test device server — analogous to TangoTest and the EPICS soft IOC.
 *
 * Exports four properties on device TESTDEV_0 … TESTDEV_{N-1} in context TEST:
 *
 *   DOUBLE    — oscillating sine value, read-only
 *   LONG      — incrementing counter, read-only
 *   STRING    — status string, read-only
 *   SETPOINT  — writable double with immediate readback, read-write
 *
 * Values are updated every 200 ms by a background scheduler.
 *
 * Context / server identity is read from fecid.csv in tine.home.
 * Properties are declared in exports.csv.
 * Device names are declared in RXTEST-devices.csv.
 *
 * Direct addressing (no TNS required):
 *   client address = /TEST/RXTEST/TESTDEV_0@<hostname>
 *
 * Usage:
 *   java -Dtine.home=/tine-config -cp tine.jar:. TestDeviceServer [nDevices]
 */
public class TestDeviceServer {

    static final int    UPDATE_INTERVAL_MS = 200;
    static final double TWO_PI             = 2.0 * Math.PI;

    public static void main(String[] args) throws Exception {
        int nDevices = args.length > 0 ? Integer.parseInt(args[0]) : 1;

        // ── per-device data arrays ─────────────────────────────────────────────
        // TEquipmentModule maps each array index to one device.
        // All reads/writes go through these arrays.
        float[]  doubleData  = new float[nDevices];
        int[]    longData    = new int[nDevices];
        String[] stringData  = new String[nDevices];
        float[]  setpoint    = new float[nDevices];

        for (int i = 0; i < nDevices; i++)
            stringData[i] = "OK";

        // ── equipment module (server identity from fecid.csv) ─────────────────
        TEquipmentModule eq = new TEquipmentModule("RXTEST");

        // ── exported properties ────────────────────────────────────────────────
        // Each TExportProperty binds a name to a data array and an access mode.
        // The array index corresponds to device index (TESTDEV_0 → index 0, etc.).
        eq.addExportedProperty(new TExportProperty("DOUBLE",   doubleData, TAccess.CA_READ));
        eq.addExportedProperty(new TExportProperty("LONG",     longData,   TAccess.CA_READ));
        eq.addExportedProperty(new TExportProperty("STRING",   stringData, TAccess.CA_READ));
        eq.addExportedProperty(new TExportProperty("SETPOINT", setpoint,   TAccess.CA_RDWR));

        eq.initialize();

        System.out.printf("TINE test server started: context=TEST  server=RXTEST  devices=%d%n", nDevices);
        System.out.printf("Direct addressing: /TEST/RXTEST/TESTDEV_0@<host>%n");
        System.out.printf("Properties: DOUBLE (sine), LONG (counter), STRING (status), SETPOINT (rw)%n");
        System.out.println("Ctrl+C to stop");

        // ── background update thread ───────────────────────────────────────────
        ScheduledExecutorService scheduler = Executors.newSingleThreadScheduledExecutor(r -> {
            Thread t = new Thread(r, "tine-updater");
            t.setDaemon(true);
            return t;
        });

        long[] tick = { 0 };

        scheduler.scheduleAtFixedRate(() -> {
            tick[0]++;
            double t = tick[0] * UPDATE_INTERVAL_MS / 1000.0;

            for (int i = 0; i < nDevices; i++) {
                // DOUBLE: sine wave, amplitude 500, frequency 0.1 Hz (period 10 s)
                doubleData[i] = (float)(500.0 * Math.sin(TWO_PI * 0.1 * t + i * Math.PI / nDevices));

                // LONG: seconds counter
                longData[i] = (int)(tick[0] * UPDATE_INTERVAL_MS / 1000);

                // STRING: oscillating status
                stringData[i] = doubleData[i] >= 0 ? "POSITIVE" : "NEGATIVE";

                // SETPOINT: writable — value persists as written; no update here
            }
        }, 0, UPDATE_INTERVAL_MS, TimeUnit.MILLISECONDS);

        Runtime.getRuntime().addShutdownHook(new Thread(() -> {
            scheduler.shutdown();
            eq.terminate();
        }));

        Thread.currentThread().join();
    }
}
