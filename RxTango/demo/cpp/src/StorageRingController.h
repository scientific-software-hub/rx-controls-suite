#pragma once

#include <tango.h>

#include <string>

namespace storage_ring {

class StorageRingController : public Tango::Device_4Impl {
public:
    StorageRingController(Tango::DeviceClass *cl, const char *name);
    StorageRingController(Tango::DeviceClass *cl, const char *name, const char *description);
    StorageRingController(Tango::DeviceClass *cl, std::string &name);
    ~StorageRingController() override;

    void init_device() override;
    void delete_device() override;
    Tango::DevState dev_state() override;
    Tango::ConstDevString dev_status() override;

    void read_scenario_id(Tango::Attribute &attr);
    void write_scenario_id(Tango::WAttribute &attr);
    bool is_scenario_id_allowed(Tango::AttReqType type);

    void read_beam_current_target(Tango::Attribute &attr);
    void write_beam_current_target(Tango::WAttribute &attr);
    bool is_beam_current_target_allowed(Tango::AttReqType type);

    void read_orbit_correction(Tango::Attribute &attr);
    void write_orbit_correction(Tango::WAttribute &attr);
    bool is_orbit_correction_allowed(Tango::AttReqType type);

    void read_simulation_time(Tango::Attribute &attr);
    void read_beam_current(Tango::Attribute &attr);
    void read_lifetime_hours(Tango::Attribute &attr);
    void read_interlock_count(Tango::Attribute &attr);

private:
    void refresh_snapshot();

    Tango::DevLong attr_scenario_id_;
    Tango::DevDouble attr_beam_current_target_;
    Tango::DevDouble attr_orbit_correction_;
    Tango::DevDouble attr_simulation_time_;
    Tango::DevDouble attr_beam_current_;
    Tango::DevDouble attr_lifetime_hours_;
    Tango::DevLong attr_interlock_count_;
    std::string status_text_;
};

}  // namespace storage_ring
