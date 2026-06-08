#include "SimulationEngine.h"

#include <algorithm>
#include <cmath>

namespace storage_ring {

namespace {

constexpr int kSectorCount = 8;

}

SimulationEngine::SimulationEngine()
    : scenario_(NOMINAL),
      beam_current_target_ma_(240.0),
      orbit_correction_(0.0),
      started_at_(std::chrono::steady_clock::now()),
      scenario_started_at_(std::chrono::steady_clock::now()) {
}

SimulationEngine &SimulationEngine::instance() {
    static SimulationEngine engine;
    return engine;
}

SimulationEngine::ControllerSnapshot SimulationEngine::controller_snapshot() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return controller_snapshot_unlocked();
}

SimulationEngine::SectorSnapshot SimulationEngine::sector_snapshot(int sector_index) const {
    std::lock_guard<std::mutex> lock(mutex_);
    return sector_snapshot_unlocked(sector_index);
}

void SimulationEngine::set_scenario(long scenario_id) {
    std::lock_guard<std::mutex> lock(mutex_);
    switch (scenario_id) {
        case NOMINAL:
        case ORBIT_DRIFT:
        case VACUUM_BURST:
        case BEAM_LOSS: {
            const auto requested = static_cast<Scenario>(scenario_id);
            // Reset the scenario clock only on an actual change so repeated
            // injection of the same scenario does not restart the ramp.
            if (requested != scenario_) {
                scenario_started_at_ = std::chrono::steady_clock::now();
                scenario_ = requested;
            }
            break;
        }
        default:
            break;
    }
}

void SimulationEngine::set_beam_current_target(double beam_current_target_ma) {
    std::lock_guard<std::mutex> lock(mutex_);
    beam_current_target_ma_ = std::clamp(beam_current_target_ma, 40.0, 320.0);
}

void SimulationEngine::set_orbit_correction(double orbit_correction) {
    std::lock_guard<std::mutex> lock(mutex_);
    orbit_correction_ = std::clamp(orbit_correction, -3.0, 3.0);
}

double SimulationEngine::elapsed_seconds_unlocked() const {
    const auto now = std::chrono::steady_clock::now();
    return std::chrono::duration<double>(now - started_at_).count();
}

double SimulationEngine::scenario_elapsed_seconds_unlocked() const {
    const auto now = std::chrono::steady_clock::now();
    return std::chrono::duration<double>(now - scenario_started_at_).count();
}

SimulationEngine::ControllerSnapshot SimulationEngine::controller_snapshot_unlocked() const {
    const double elapsed_s = elapsed_seconds_unlocked();
    const double beam_current = base_beam_current_unlocked(elapsed_s);

    double total_vacuum = 0.0;
    long interlock_count = 0;
    for (int sector = 1; sector <= kSectorCount; ++sector) {
        const SectorSnapshot snapshot = sector_snapshot_unlocked(sector);
        total_vacuum += snapshot.vacuum_pressure_nbar;
        // Orbit is a quality signal only (see facility.py::is_healthy) — it
        // degrades frame quality but must not trip an interlock. Only vacuum
        // and radiation alarms fan into the interlock count.
        if (snapshot.vacuum_alarm || snapshot.radiation_alarm) {
            ++interlock_count;
        }
    }

    const double average_vacuum = total_vacuum / static_cast<double>(kSectorCount);
    const double lifetime = std::max(0.35, beam_current / (11.0 + 13.0 * average_vacuum));

    return {
        static_cast<long>(scenario_),
        beam_current_target_ma_,
        orbit_correction_,
        elapsed_s,
        beam_current,
        lifetime,
        interlock_count
    };
}

SimulationEngine::SectorSnapshot SimulationEngine::sector_snapshot_unlocked(int sector_index) const {
    const int sector = std::clamp(sector_index, 1, kSectorCount);
    const double elapsed_s = elapsed_seconds_unlocked();
    const double beam_current = base_beam_current_unlocked(elapsed_s);
    const double orbit_x = orbit_value_unlocked(sector, elapsed_s);
    const double vacuum = vacuum_value_unlocked(sector);
    const double radiation = radiation_value_unlocked(vacuum);
    const double loss = loss_value_unlocked(sector, beam_current);

    return {
        sector,
        beam_current,
        orbit_x,
        vacuum,
        radiation,
        loss,
        std::abs(orbit_x) >= 55.0,
        vacuum >= 1.55,
        radiation >= 1.10
    };
}

double SimulationEngine::base_beam_current_unlocked(double elapsed_s) const {
    double beam_current = beam_current_target_ma_ + 9.0 * std::sin(elapsed_s / 7.5);
    const double st = scenario_elapsed_seconds_unlocked();

    switch (scenario_) {
        case NOMINAL:
        case ORBIT_DRIFT:
            // Orbit drift degrades quality only — it must not pull current
            // below the health gate, so beam current stays nominal.
            break;
        case VACUUM_BURST:
            // Gentle sag, floored well above the 50 mA gate: the abort comes
            // from the interlock, not from the beam-loss health check.
            beam_current = std::max(120.0, beam_current - 6.0 * st);
            break;
        case BEAM_LOSS:
            // Fast decay to a 25 mA floor → crosses the 50 mA gate in ~2.5 s
            // and pauses the scan (no interlock).
            beam_current = std::max(25.0, beam_current - 75.0 * st);
            break;
    }

    return beam_current;
}

double SimulationEngine::orbit_value_unlocked(int sector_index, double elapsed_s) const {
    const double phase = sector_index * 0.9 + elapsed_s * 0.32;
    double orbit_x = 18.0 * std::sin(phase)
                   + 6.0 * std::cos(elapsed_s * 0.17 + sector_index * 0.45)
                   - orbit_correction_ * 22.0;

    if (scenario_ == ORBIT_DRIFT) {
        // Ramp a bounded DC offset so |OrbitX| reliably clears the 55 µm
        // quality threshold within a few seconds despite the ±24 µm swing.
        // Orbit feeds quality only (decoupled from vacuum/radiation/interlock),
        // so a large value never aborts the scan.
        const double st = scenario_elapsed_seconds_unlocked();
        orbit_x += std::min(95.0, 22.0 * st);
    }

    return orbit_x;
}

double SimulationEngine::vacuum_value_unlocked(int sector_index) const {
    // Nominal vacuum is well below the 1.55 nbar alarm. Only a vacuum burst,
    // localized to sector 5, drives it over the alarm threshold. Orbit no
    // longer feeds vacuum — the scenarios are kept independent.
    double vacuum = 0.42 + 0.025 * sector_index;

    if (scenario_ == VACUUM_BURST && sector_index == 5) {
        const double st = scenario_elapsed_seconds_unlocked();
        vacuum += std::min(1.6, 0.55 + 0.25 * st);   // clears 1.55 in ~1.8 s
    }

    return vacuum;
}

double SimulationEngine::radiation_value_unlocked(double vacuum_pressure_nbar) const {
    // Radiation tracks vacuum and, during a vacuum burst, an extra dose term.
    // It is independent of orbit so orbit drift cannot trip the radiation alarm.
    double radiation = 0.03 + std::max(0.0, vacuum_pressure_nbar - 0.85) * 0.58;

    if (scenario_ == VACUUM_BURST) {
        const double st = scenario_elapsed_seconds_unlocked();
        radiation += std::min(0.9, 0.25 + 0.12 * st);
    }

    return radiation;
}

double SimulationEngine::loss_value_unlocked(int sector_index,
                                             double beam_current_ma) const {
    // Pure diagnostic readout (not part of any alarm). Tracks the current
    // deficit, with an extra localized term during a beam-loss event.
    double loss = std::max(0.0, (250.0 - beam_current_ma) / 900.0);

    if (scenario_ == BEAM_LOSS && sector_index >= 6) {
        const double st = scenario_elapsed_seconds_unlocked();
        loss = std::min(0.98, loss + 0.10 * st + 0.03 * (sector_index - 6));
    }

    return loss;
}

}  // namespace storage_ring
