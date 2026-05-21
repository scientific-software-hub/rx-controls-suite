#include "StorageRingSector.h"

#include "SimulationEngine.h"

#include <sstream>

namespace storage_ring {

StorageRingSector::StorageRingSector(Tango::DeviceClass *cl, const char *name)
    : Tango::Device_4Impl(cl, name),
      sector_index_(1) {
    init_device();
}

StorageRingSector::StorageRingSector(Tango::DeviceClass *cl, const char *name, const char *description)
    : Tango::Device_4Impl(cl, name, description),
      sector_index_(1) {
    init_device();
}

StorageRingSector::StorageRingSector(Tango::DeviceClass *cl, std::string &name)
    : Tango::Device_4Impl(cl, name.c_str()),
      sector_index_(1) {
    init_device();
}

StorageRingSector::~StorageRingSector() {
    delete_device();
}

void StorageRingSector::init_device() {
    get_device_properties();
    status_text_ = "Storage ring sector ready";
    refresh_snapshot();
}

void StorageRingSector::delete_device() {
}

Tango::DevState StorageRingSector::dev_state() {
    refresh_snapshot();
    const bool alarm = std::abs(attr_orbit_x_) >= 55.0
                    || attr_vacuum_pressure_ >= 1.55
                    || attr_radiation_dose_rate_ >= 1.10;
    return alarm ? Tango::ALARM : Tango::ON;
}

Tango::ConstDevString StorageRingSector::dev_status() {
    refresh_snapshot();

    std::ostringstream status;
    status << "Sector " << sector_index_
           << ", orbit " << attr_orbit_x_ << " um"
           << ", vacuum " << attr_vacuum_pressure_ << " nbar"
           << ", radiation " << attr_radiation_dose_rate_ << " mSv/h"
           << ", loss " << attr_beam_loss_fraction_;
    status_text_ = status.str();
    return status_text_.c_str();
}

void StorageRingSector::read_sector_index(Tango::Attribute &attr) {
    attr_sector_index_ = sector_index_;
    attr.set_value(&attr_sector_index_);
}

void StorageRingSector::read_beam_current(Tango::Attribute &attr) {
    refresh_snapshot();
    attr.set_value(&attr_beam_current_);
}

void StorageRingSector::read_orbit_x(Tango::Attribute &attr) {
    refresh_snapshot();
    attr.set_value(&attr_orbit_x_);
}

void StorageRingSector::read_vacuum_pressure(Tango::Attribute &attr) {
    refresh_snapshot();
    attr.set_value(&attr_vacuum_pressure_);
}

void StorageRingSector::read_radiation_dose_rate(Tango::Attribute &attr) {
    refresh_snapshot();
    attr.set_value(&attr_radiation_dose_rate_);
}

void StorageRingSector::read_beam_loss_fraction(Tango::Attribute &attr) {
    refresh_snapshot();
    attr.set_value(&attr_beam_loss_fraction_);
}

void StorageRingSector::get_device_properties() {
    Tango::DbData properties;
    properties.push_back(Tango::DbDatum("SectorIndex"));
    get_db_device()->get_property(properties);

    if (!properties[0].is_empty()) {
        properties[0] >> sector_index_;
    }
}

void StorageRingSector::refresh_snapshot() {
    const SimulationEngine::SectorSnapshot snapshot = SimulationEngine::instance().sector_snapshot(sector_index_);

    attr_sector_index_ = snapshot.sector_index;
    attr_beam_current_ = snapshot.beam_current_ma;
    attr_orbit_x_ = snapshot.orbit_x_um;
    attr_vacuum_pressure_ = snapshot.vacuum_pressure_nbar;
    attr_radiation_dose_rate_ = snapshot.radiation_dose_rate;
    attr_beam_loss_fraction_ = snapshot.beam_loss_fraction;
}

}  // namespace storage_ring
