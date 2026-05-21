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
      started_at_(std::chrono::steady_clock::now()) {
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
        case BEAM_LOSS:
            scenario_ = static_cast<Scenario>(scenario_id);
            break;
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

SimulationEngine::ControllerSnapshot SimulationEngine::controller_snapshot_unlocked() const {
    const double elapsed_s = elapsed_seconds_unlocked();
    const double beam_current = base_beam_current_unlocked(elapsed_s);

    double total_vacuum = 0.0;
    long interlock_count = 0;
    for (int sector = 1; sector <= kSectorCount; ++sector) {
        const SectorSnapshot snapshot = sector_snapshot_unlocked(sector);
        total_vacuum += snapshot.vacuum_pressure_nbar;
        if (snapshot.orbit_alarm || snapshot.vacuum_alarm || snapshot.radiation_alarm) {
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
    const double vacuum = vacuum_value_unlocked(sector, elapsed_s, orbit_x);
    const double radiation = radiation_value_unlocked(elapsed_s, orbit_x, vacuum);
    const double loss = loss_value_unlocked(sector, elapsed_s, beam_current);

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

    switch (scenario_) {
        case NOMINAL:
            break;
        case ORBIT_DRIFT:
            if (elapsed_s > 8.0) {
                beam_current -= 0.9 * (elapsed_s - 8.0);
            }
            break;
        case VACUUM_BURST:
            if (elapsed_s > 10.0) {
                beam_current -= 0.7 * (elapsed_s - 10.0);
            }
            break;
        case BEAM_LOSS:
            if (elapsed_s > 8.0) {
                beam_current -= 11.5 * (elapsed_s - 8.0);
            }
            beam_current = std::max(25.0, beam_current);
            break;
    }

    return beam_current;
}

double SimulationEngine::orbit_value_unlocked(int sector_index, double elapsed_s) const {
    const double phase = sector_index * 0.9 + elapsed_s * 0.32;
    double orbit_x = 18.0 * std::sin(phase)
                   + 6.0 * std::cos(elapsed_s * 0.17 + sector_index * 0.45)
                   - orbit_correction_ * 22.0;

    switch (scenario_) {
        case NOMINAL:
            break;
        case ORBIT_DRIFT:
            if (elapsed_s > 6.0) {
                orbit_x += (elapsed_s - 6.0) * 4.2;
            }
            break;
        case VACUUM_BURST:
            if (sector_index == 5 && elapsed_s > 9.0) {
                orbit_x += 17.0;
            }
            break;
        case BEAM_LOSS:
            if (sector_index >= 6 && elapsed_s > 8.0) {
                orbit_x += 7.0 + 2.6 * (elapsed_s - 8.0);
            }
            break;
    }

    return orbit_x;
}

double SimulationEngine::vacuum_value_unlocked(int sector_index,
                                                double elapsed_s,
                                                double orbit_x_um) const {
    double vacuum = 0.42 + std::abs(orbit_x_um) / 115.0 + 0.025 * sector_index;

    switch (scenario_) {
        case NOMINAL:
        case ORBIT_DRIFT:
            break;
        case VACUUM_BURST:
            if (sector_index == 5 && elapsed_s > 9.0) {
                vacuum += 0.95 + 0.11 * (elapsed_s - 9.0);
            }
            break;
        case BEAM_LOSS:
            if (sector_index >= 6 && elapsed_s > 8.0) {
                vacuum += 0.08 * (elapsed_s - 8.0);
            }
            break;
    }

    return vacuum;
}

double SimulationEngine::radiation_value_unlocked(double elapsed_s,
                                                  double orbit_x_um,
                                                  double vacuum_pressure_nbar) const {
    double radiation = 0.03 + std::max(0.0, std::abs(orbit_x_um) - 28.0) / 40.0;
    radiation += std::max(0.0, vacuum_pressure_nbar - 0.85) * 0.58;

    if (scenario_ == VACUUM_BURST && elapsed_s > 10.0) {
        radiation += 0.16 + 0.03 * (elapsed_s - 10.0);
    }
    if (scenario_ == BEAM_LOSS && elapsed_s > 8.0) {
        radiation += 0.45 + 0.12 * (elapsed_s - 8.0);
    }

    return radiation;
}

double SimulationEngine::loss_value_unlocked(int sector_index,
                                             double elapsed_s,
                                             double beam_current_ma) const {
    if (scenario_ != BEAM_LOSS || elapsed_s <= 8.0 || sector_index < 6) {
        return std::max(0.0, (250.0 - beam_current_ma) / 900.0);
    }
    return std::min(0.98, 0.18 + 0.10 * (elapsed_s - 8.0) + 0.03 * (sector_index - 6));
}

}  // namespace storage_ring
