#include <tango.h>

#include "StorageRingControllerClass.h"
#include "StorageRingSectorClass.h"

void Tango::DServer::class_factory() {
    add_class(storage_ring::StorageRingControllerClass::init("StorageRingController"));
    add_class(storage_ring::StorageRingSectorClass::init("StorageRingSector"));
}
