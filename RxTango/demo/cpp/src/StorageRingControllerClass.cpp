#include "StorageRingControllerClass.h"

namespace storage_ring {

StorageRingControllerClass *StorageRingControllerClass::instance_ = nullptr;

void ScenarioIdAttr::read(Tango::DeviceImpl *dev, Tango::Attribute &att) {
    static_cast<StorageRingController *>(dev)->read_scenario_id(att);
}

void ScenarioIdAttr::write(Tango::DeviceImpl *dev, Tango::WAttribute &att) {
    static_cast<StorageRingController *>(dev)->write_scenario_id(att);
}

bool ScenarioIdAttr::is_allowed(Tango::DeviceImpl *dev, Tango::AttReqType type) {
    return static_cast<StorageRingController *>(dev)->is_scenario_id_allowed(type);
}

void BeamCurrentTargetAttr::read(Tango::DeviceImpl *dev, Tango::Attribute &att) {
    static_cast<StorageRingController *>(dev)->read_beam_current_target(att);
}

void BeamCurrentTargetAttr::write(Tango::DeviceImpl *dev, Tango::WAttribute &att) {
    static_cast<StorageRingController *>(dev)->write_beam_current_target(att);
}

bool BeamCurrentTargetAttr::is_allowed(Tango::DeviceImpl *dev, Tango::AttReqType type) {
    return static_cast<StorageRingController *>(dev)->is_beam_current_target_allowed(type);
}

void OrbitCorrectionAttr::read(Tango::DeviceImpl *dev, Tango::Attribute &att) {
    static_cast<StorageRingController *>(dev)->read_orbit_correction(att);
}

void OrbitCorrectionAttr::write(Tango::DeviceImpl *dev, Tango::WAttribute &att) {
    static_cast<StorageRingController *>(dev)->write_orbit_correction(att);
}

bool OrbitCorrectionAttr::is_allowed(Tango::DeviceImpl *dev, Tango::AttReqType type) {
    return static_cast<StorageRingController *>(dev)->is_orbit_correction_allowed(type);
}

void SimulationTimeAttr::read(Tango::DeviceImpl *dev, Tango::Attribute &att) {
    static_cast<StorageRingController *>(dev)->read_simulation_time(att);
}

bool SimulationTimeAttr::is_allowed(Tango::DeviceImpl *, Tango::AttReqType) {
    return true;
}

void BeamCurrentAttr::read(Tango::DeviceImpl *dev, Tango::Attribute &att) {
    static_cast<StorageRingController *>(dev)->read_beam_current(att);
}

bool BeamCurrentAttr::is_allowed(Tango::DeviceImpl *, Tango::AttReqType) {
    return true;
}

void LifetimeHoursAttr::read(Tango::DeviceImpl *dev, Tango::Attribute &att) {
    static_cast<StorageRingController *>(dev)->read_lifetime_hours(att);
}

bool LifetimeHoursAttr::is_allowed(Tango::DeviceImpl *, Tango::AttReqType) {
    return true;
}

void InterlockCountAttr::read(Tango::DeviceImpl *dev, Tango::Attribute &att) {
    static_cast<StorageRingController *>(dev)->read_interlock_count(att);
}

bool InterlockCountAttr::is_allowed(Tango::DeviceImpl *, Tango::AttReqType) {
    return true;
}

StorageRingControllerClass *StorageRingControllerClass::init(const char *name) {
    if (instance_ == nullptr) {
        std::string class_name(name);
        instance_ = new StorageRingControllerClass(class_name);
    }
    return instance_;
}

StorageRingControllerClass *StorageRingControllerClass::instance() {
    return instance_;
}

StorageRingControllerClass::~StorageRingControllerClass() {
    instance_ = nullptr;
}

StorageRingControllerClass::StorageRingControllerClass(std::string &name)
    : Tango::DeviceClass(name) {
    set_type(name);
}

void StorageRingControllerClass::command_factory() {
}

void StorageRingControllerClass::attribute_factory(std::vector<Tango::Attr *> &att_list) {
    att_list.push_back(new ScenarioIdAttr());
    att_list.push_back(new BeamCurrentTargetAttr());
    att_list.push_back(new OrbitCorrectionAttr());
    att_list.push_back(new SimulationTimeAttr());
    att_list.push_back(new BeamCurrentAttr());
    att_list.push_back(new LifetimeHoursAttr());
    att_list.push_back(new InterlockCountAttr());
}

void StorageRingControllerClass::device_factory(const Tango::DevVarStringArray *devlist) {
    for (unsigned long index = 0; index < devlist->length(); ++index) {
        auto *device = new StorageRingController(this, (*devlist)[index].in());
        device_list.push_back(device);
        export_device(device);
    }
}

}  // namespace storage_ring
