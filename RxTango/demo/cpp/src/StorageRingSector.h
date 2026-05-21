#pragma once

#include <tango.h>

#include <string>

namespace storage_ring {

class StorageRingSector : public Tango::Device_4Impl {
public:
    StorageRingSector(Tango::DeviceClass *cl, const char *name);
    StorageRingSector(Tango::DeviceClass *cl, const char *name, const char *description);
    StorageRingSector(Tango::DeviceClass *cl, std::string &name);
    ~StorageRingSector() override;

    void init_device() override;
    void delete_device() override;
    Tango::DevState dev_state() override;
    Tango::ConstDevString dev_status() override;

    void read_sector_index(Tango::Attribute &attr);
    void read_beam_current(Tango::Attribute &attr);
    void read_orbit_x(Tango::Attribute &attr);
    void read_vacuum_pressure(Tango::Attribute &attr);
    void read_radiation_dose_rate(Tango::Attribute &attr);
    void read_beam_loss_fraction(Tango::Attribute &attr);

    void get_device_properties();

private:
    void refresh_snapshot();

    int sector_index_;
    Tango::DevLong attr_sector_index_;
    Tango::DevDouble attr_beam_current_;
    Tango::DevDouble attr_orbit_x_;
    Tango::DevDouble attr_vacuum_pressure_;
    Tango::DevDouble attr_radiation_dose_rate_;
    Tango::DevDouble attr_beam_loss_fraction_;
    std::string status_text_;
};

}  // namespace storage_ring
