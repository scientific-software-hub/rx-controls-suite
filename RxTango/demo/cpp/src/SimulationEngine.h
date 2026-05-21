#pragma once

#include <chrono>
#include <mutex>
#include <vector>

namespace storage_ring {

class SimulationEngine {
public:
    enum Scenario {
        NOMINAL = 0,
        ORBIT_DRIFT = 1,
        VACUUM_BURST = 2,
        BEAM_LOSS = 3
    };

    struct SectorSnapshot {
        int sector_index;
        double beam_current_ma;
        double orbit_x_um;
        double vacuum_pressure_nbar;
        double radiation_dose_rate;
        double beam_loss_fraction;
        bool orbit_alarm;
        bool vacuum_alarm;
        bool radiation_alarm;
    };

    struct ControllerSnapshot {
        long scenario_id;
        double beam_current_target_ma;
        double orbit_correction;
        double simulation_time_s;
        double beam_current_ma;
        double lifetime_hours;
        long interlock_count;
    };

    static SimulationEngine &instance();

    ControllerSnapshot controller_snapshot() const;
    SectorSnapshot sector_snapshot(int sector_index) const;

    void set_scenario(long scenario_id);
    void set_beam_current_target(double beam_current_target_ma);
    void set_orbit_correction(double orbit_correction);

private:
    SimulationEngine();

    double elapsed_seconds_unlocked() const;
    ControllerSnapshot controller_snapshot_unlocked() const;
    SectorSnapshot sector_snapshot_unlocked(int sector_index) const;
    double base_beam_current_unlocked(double elapsed_s) const;
    double orbit_value_unlocked(int sector_index, double elapsed_s) const;
    double vacuum_value_unlocked(int sector_index, double elapsed_s, double orbit_x_um) const;
    double radiation_value_unlocked(double elapsed_s, double orbit_x_um, double vacuum_pressure_nbar) const;
    double loss_value_unlocked(int sector_index, double elapsed_s, double beam_current_ma) const;

    mutable std::mutex mutex_;
    Scenario scenario_;
    double beam_current_target_ma_;
    double orbit_correction_;
    std::chrono::steady_clock::time_point started_at_;
};

}  // namespace storage_ring
