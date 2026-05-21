#pragma once

#include <tango.h>

#include "StorageRingSector.h"

namespace storage_ring {

class SectorIndexAttr : public Tango::Attr {
public:
    SectorIndexAttr() : Tango::Attr("SectorIndex", Tango::DEV_LONG, Tango::READ) {}
    void read(Tango::DeviceImpl *dev, Tango::Attribute &att) override;
    bool is_allowed(Tango::DeviceImpl *dev, Tango::AttReqType type) override;
};

class SectorBeamCurrentAttr : public Tango::Attr {
public:
    SectorBeamCurrentAttr() : Tango::Attr("BeamCurrent", Tango::DEV_DOUBLE, Tango::READ) {}
    void read(Tango::DeviceImpl *dev, Tango::Attribute &att) override;
    bool is_allowed(Tango::DeviceImpl *dev, Tango::AttReqType type) override;
};

class OrbitXAttr : public Tango::Attr {
public:
    OrbitXAttr() : Tango::Attr("OrbitX", Tango::DEV_DOUBLE, Tango::READ) {}
    void read(Tango::DeviceImpl *dev, Tango::Attribute &att) override;
    bool is_allowed(Tango::DeviceImpl *dev, Tango::AttReqType type) override;
};

class VacuumPressureAttr : public Tango::Attr {
public:
    VacuumPressureAttr() : Tango::Attr("VacuumPressure", Tango::DEV_DOUBLE, Tango::READ) {}
    void read(Tango::DeviceImpl *dev, Tango::Attribute &att) override;
    bool is_allowed(Tango::DeviceImpl *dev, Tango::AttReqType type) override;
};

class RadiationDoseRateAttr : public Tango::Attr {
public:
    RadiationDoseRateAttr() : Tango::Attr("RadiationDoseRate", Tango::DEV_DOUBLE, Tango::READ) {}
    void read(Tango::DeviceImpl *dev, Tango::Attribute &att) override;
    bool is_allowed(Tango::DeviceImpl *dev, Tango::AttReqType type) override;
};

class BeamLossFractionAttr : public Tango::Attr {
public:
    BeamLossFractionAttr() : Tango::Attr("BeamLossFraction", Tango::DEV_DOUBLE, Tango::READ) {}
    void read(Tango::DeviceImpl *dev, Tango::Attribute &att) override;
    bool is_allowed(Tango::DeviceImpl *dev, Tango::AttReqType type) override;
};

class StorageRingSectorClass : public Tango::DeviceClass {
public:
    static StorageRingSectorClass *init(const char *name);
    static StorageRingSectorClass *instance();
    ~StorageRingSectorClass() override;

protected:
    explicit StorageRingSectorClass(std::string &name);
    static StorageRingSectorClass *instance_;

    void command_factory() override;
    void attribute_factory(std::vector<Tango::Attr *> &att_list) override;

private:
    void device_factory(const Tango::DevVarStringArray *devlist) override;
};

}  // namespace storage_ring
