#pragma once
/**
 * @file attribute.hpp
 * @brief Single-shot Tango attribute read as an Observable.
 *
 * Mirrors Python's rxtango.attribute.read_attribute() and Java's RxTangoAttribute<T>.
 *
 * Observable contract:
 *   on_next(value) → on_completed()    on success
 *   on_error(e)                         on any Tango exception
 *   Exactly one on_next — single-shot.
 */

#include <exception>
#include <string>
#include <thread>

#include <rxcpp/rx.hpp>
#include <tango/tango.h>

#include "context.hpp"

namespace rxtango {

/**
 * Return an Observable that reads attribute @p name from @p device and emits one value.
 *
 * The cppTango call runs on a background thread (analog of Python's run_in_executor),
 * so the subscribe call is non-blocking.  The Observable value type @p T must be
 * extractable from Tango::DeviceAttribute via operator>>.
 *
 * Common types: double, float, Tango::DevLong, std::string, std::vector<double>.
 *
 * Example — read double_scalar:
 * @code
 *   rxtango::read_attribute<double>("tango://localhost:10000/sys/tg_test/1", "double_scalar")
 *       .subscribe(
 *           [](double v) { std::cout << v << "\n"; },
 *           [](std::exception_ptr e) { ... },
 *           []() { ... }
 *       );
 * @endcode
 */
template<typename T = double>
rxcpp::observable<T> read_attribute(const std::string& device, const std::string& name) {
    return rxcpp::observable<>::create<T>([device, name](rxcpp::subscriber<T> sub) {
        // Run cppTango (blocking) on a detached background thread — analog of asyncio run_in_executor
        std::thread([device, name, sub]() mutable {
            try {
                Tango::DeviceProxy& proxy = TangoContext::instance().get_proxy(device);
                Tango::DeviceAttribute da  = proxy.read_attribute(const_cast<std::string&>(name));
                T value;
                da >> value;
                if (sub.is_subscribed()) {
                    sub.on_next(value);
                    sub.on_completed();
                }
            } catch (...) {
                if (sub.is_subscribed()) {
                    sub.on_error(std::current_exception());
                }
            }
        }).detach();
    });
}

} // namespace rxtango
