#include "StorageRingController.h"

#include "SimulationEngine.h"

#include <sstream>

namespace storage_ring {

StorageRingController::StorageRingController(Tango::DeviceClass *cl, const char *name)
    : Tango::Device_4Impl(cl, name) {
    init_device();
}

StorageRingController::StorageRingController(Tango::DeviceClass *cl, const char *name, const char *description)
    : Tango::Device_4Impl(cl, name, description) {
    init_device();
}

StorageRingController::StorageRingController(Tango::DeviceClass *cl, std::string &name)
    : Tango::Device_4Impl(cl, name.c_str()) {
    init_device();
}

StorageRingController::~StorageRingController() {
    delete_device();
}

void StorageRingController::init_device() {
    status_text_ = "Storage ring controller ready";
    refresh_snapshot();
}

void StorageRingController::delete_device() {
}

Tango::DevState StorageRingController::dev_state() {
    refresh_snapshot();
    return attr_interlock_count_ > 0 ? Tango::ALARM : Tango::ON;
}

Tango::ConstDevString StorageRingController::dev_status() {
    refresh_snapshot();

    std::ostringstream status;
    status << "Scenario " << attr_scenario_id_
           << ", current " << attr_beam_current_ << " mA"
           << ", lifetime " << attr_lifetime_hours_ << " h"
           << ", interlocks " << attr_interlock_count_;
    status_text_ = status.str();
    return status_text_.c_str();
}

void StorageRingController::read_scenario_id(Tango::Attribute &attr) {
    refresh_snapshot();
    attr.set_value(&attr_scenario_id_);
}

void StorageRingController::write_scenario_id(Tango::WAttribute &attr) {
    Tango::DevLong value = 0;
    attr.get_write_value(value);
    SimulationEngine::instance().set_scenario(value);
    refresh_snapshot();
}

bool StorageRingController::is_scenario_id_allowed(Tango::AttReqType) {
    return true;
}

void StorageRingController::read_beam_current_target(Tango::Attribute &attr) {
    refresh_snapshot();
    attr.set_value(&attr_beam_current_target_);
}

void StorageRingController::write_beam_current_target(Tango::WAttribute &attr) {
    Tango::DevDouble value = 0.0;
    attr.get_write_value(value);
    SimulationEngine::instance().set_beam_current_target(value);
    refresh_snapshot();
}

bool StorageRingController::is_beam_current_target_allowed(Tango::AttReqType) {
    return true;
}

void StorageRingController::read_orbit_correction(Tango::Attribute &attr) {
    refresh_snapshot();
    attr.set_value(&attr_orbit_correction_);
}

void StorageRingController::write_orbit_correction(Tango::WAttribute &attr) {
    Tango::DevDouble value = 0.0;
    attr.get_write_value(value);
    SimulationEngine::instance().set_orbit_correction(value);
    refresh_snapshot();
}

bool StorageRingController::is_orbit_correction_allowed(Tango::AttReqType) {
    return true;
}

void StorageRingController::read_simulation_time(Tango::Attribute &attr) {
    refresh_snapshot();
    attr.set_value(&attr_simulation_time_);
}

void StorageRingController::read_beam_current(Tango::Attribute &attr) {
    refresh_snapshot();
    attr.set_value(&attr_beam_current_);
}

void StorageRingController::read_lifetime_hours(Tango::Attribute &attr) {
    refresh_snapshot();
    attr.set_value(&attr_lifetime_hours_);
}

void StorageRingController::read_interlock_count(Tango::Attribute &attr) {
    refresh_snapshot();
    attr.set_value(&attr_interlock_count_);
}

void StorageRingController::refresh_snapshot() {
    const SimulationEngine::ControllerSnapshot snapshot = SimulationEngine::instance().controller_snapshot();

    attr_scenario_id_ = snapshot.scenario_id;
    attr_beam_current_target_ = snapshot.beam_current_target_ma;
    attr_orbit_correction_ = snapshot.orbit_correction;
    attr_simulation_time_ = snapshot.simulation_time_s;
    attr_beam_current_ = snapshot.beam_current_ma;
    attr_lifetime_hours_ = snapshot.lifetime_hours;
    attr_interlock_count_ = snapshot.interlock_count;
}

}  // namespace storage_ring
