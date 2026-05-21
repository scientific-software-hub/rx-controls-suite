#pragma once

#include <tango.h>

#include "StorageRingController.h"

namespace storage_ring {

class ScenarioIdAttr : public Tango::Attr {
public:
    ScenarioIdAttr() : Tango::Attr("ScenarioId", Tango::DEV_LONG, Tango::READ_WRITE) {}
    void read(Tango::DeviceImpl *dev, Tango::Attribute &att) override;
    void write(Tango::DeviceImpl *dev, Tango::WAttribute &att) override;
    bool is_allowed(Tango::DeviceImpl *dev, Tango::AttReqType type) override;
};

class BeamCurrentTargetAttr : public Tango::Attr {
public:
    BeamCurrentTargetAttr() : Tango::Attr("BeamCurrentTarget", Tango::DEV_DOUBLE, Tango::READ_WRITE) {}
    void read(Tango::DeviceImpl *dev, Tango::Attribute &att) override;
    void write(Tango::DeviceImpl *dev, Tango::WAttribute &att) override;
    bool is_allowed(Tango::DeviceImpl *dev, Tango::AttReqType type) override;
};

class OrbitCorrectionAttr : public Tango::Attr {
public:
    OrbitCorrectionAttr() : Tango::Attr("OrbitCorrection", Tango::DEV_DOUBLE, Tango::READ_WRITE) {}
    void read(Tango::DeviceImpl *dev, Tango::Attribute &att) override;
    void write(Tango::DeviceImpl *dev, Tango::WAttribute &att) override;
    bool is_allowed(Tango::DeviceImpl *dev, Tango::AttReqType type) override;
};

class SimulationTimeAttr : public Tango::Attr {
public:
    SimulationTimeAttr() : Tango::Attr("SimulationTime", Tango::DEV_DOUBLE, Tango::READ) {}
    void read(Tango::DeviceImpl *dev, Tango::Attribute &att) override;
    bool is_allowed(Tango::DeviceImpl *dev, Tango::AttReqType type) override;
};

class BeamCurrentAttr : public Tango::Attr {
public:
    BeamCurrentAttr() : Tango::Attr("BeamCurrent", Tango::DEV_DOUBLE, Tango::READ) {}
    void read(Tango::DeviceImpl *dev, Tango::Attribute &att) override;
    bool is_allowed(Tango::DeviceImpl *dev, Tango::AttReqType type) override;
};

class LifetimeHoursAttr : public Tango::Attr {
public:
    LifetimeHoursAttr() : Tango::Attr("LifetimeHours", Tango::DEV_DOUBLE, Tango::READ) {}
    void read(Tango::DeviceImpl *dev, Tango::Attribute &att) override;
    bool is_allowed(Tango::DeviceImpl *dev, Tango::AttReqType type) override;
};

class InterlockCountAttr : public Tango::Attr {
public:
    InterlockCountAttr() : Tango::Attr("InterlockCount", Tango::DEV_LONG, Tango::READ) {}
    void read(Tango::DeviceImpl *dev, Tango::Attribute &att) override;
    bool is_allowed(Tango::DeviceImpl *dev, Tango::AttReqType type) override;
};

class StorageRingControllerClass : public Tango::DeviceClass {
public:
    static StorageRingControllerClass *init(const char *name);
    static StorageRingControllerClass *instance();
    ~StorageRingControllerClass() override;

protected:
    explicit StorageRingControllerClass(std::string &name);
    static StorageRingControllerClass *instance_;

    void command_factory() override;
    void attribute_factory(std::vector<Tango::Attr *> &att_list) override;

private:
    void device_factory(const Tango::DevVarStringArray *devlist) override;
};

}  // namespace storage_ring
