#include "StorageRingSectorClass.h"

namespace storage_ring {

StorageRingSectorClass *StorageRingSectorClass::instance_ = nullptr;

void SectorIndexAttr::read(Tango::DeviceImpl *dev, Tango::Attribute &att) {
    static_cast<StorageRingSector *>(dev)->read_sector_index(att);
}

bool SectorIndexAttr::is_allowed(Tango::DeviceImpl *, Tango::AttReqType) {
    return true;
}

void SectorBeamCurrentAttr::read(Tango::DeviceImpl *dev, Tango::Attribute &att) {
    static_cast<StorageRingSector *>(dev)->read_beam_current(att);
}

bool SectorBeamCurrentAttr::is_allowed(Tango::DeviceImpl *, Tango::AttReqType) {
    return true;
}

void OrbitXAttr::read(Tango::DeviceImpl *dev, Tango::Attribute &att) {
    static_cast<StorageRingSector *>(dev)->read_orbit_x(att);
}

bool OrbitXAttr::is_allowed(Tango::DeviceImpl *, Tango::AttReqType) {
    return true;
}

void VacuumPressureAttr::read(Tango::DeviceImpl *dev, Tango::Attribute &att) {
    static_cast<StorageRingSector *>(dev)->read_vacuum_pressure(att);
}

bool VacuumPressureAttr::is_allowed(Tango::DeviceImpl *, Tango::AttReqType) {
    return true;
}

void RadiationDoseRateAttr::read(Tango::DeviceImpl *dev, Tango::Attribute &att) {
    static_cast<StorageRingSector *>(dev)->read_radiation_dose_rate(att);
}

bool RadiationDoseRateAttr::is_allowed(Tango::DeviceImpl *, Tango::AttReqType) {
    return true;
}

void BeamLossFractionAttr::read(Tango::DeviceImpl *dev, Tango::Attribute &att) {
    static_cast<StorageRingSector *>(dev)->read_beam_loss_fraction(att);
}

bool BeamLossFractionAttr::is_allowed(Tango::DeviceImpl *, Tango::AttReqType) {
    return true;
}

StorageRingSectorClass *StorageRingSectorClass::init(const char *name) {
    if (instance_ == nullptr) {
        std::string class_name(name);
        instance_ = new StorageRingSectorClass(class_name);
    }
    return instance_;
}

StorageRingSectorClass *StorageRingSectorClass::instance() {
    return instance_;
}

StorageRingSectorClass::~StorageRingSectorClass() {
    instance_ = nullptr;
}

StorageRingSectorClass::StorageRingSectorClass(std::string &name)
    : Tango::DeviceClass(name) {
    set_type(name);
}

void StorageRingSectorClass::command_factory() {
}

void StorageRingSectorClass::attribute_factory(std::vector<Tango::Attr *> &att_list) {
    att_list.push_back(new SectorIndexAttr());
    att_list.push_back(new SectorBeamCurrentAttr());
    att_list.push_back(new OrbitXAttr());
    att_list.push_back(new VacuumPressureAttr());
    att_list.push_back(new RadiationDoseRateAttr());
    att_list.push_back(new BeamLossFractionAttr());
}

void StorageRingSectorClass::device_factory(const Tango::DevVarStringArray *devlist) {
    for (unsigned long index = 0; index < devlist->length(); ++index) {
        auto *device = new StorageRingSector(this, (*devlist)[index].in());
        device_list.push_back(device);
        export_device(device);
    }
}

}  // namespace storage_ring
