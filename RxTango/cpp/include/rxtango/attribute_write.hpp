#pragma once
/**
 * @file attribute_write.hpp
 * @brief Single-shot Tango attribute write as an Observable.
 *
 * Mirrors Python's rxtango.attribute_write.write_attribute() and Java's
 * RxTangoAttributeWrite<T>.
 *
 * Observable contract:
 *   on_next(written_value) → on_completed()   on success
 *   on_error(e)                                on any Tango exception
 *
 * Re-emitting the written value (rather than nothing) allows writes to be
 * chained into subsequent pipeline steps — the same design as the Python
 * write_attribute() and Java's ignoreElements().andThen() idiom.
 */

#include <exception>
#include <string>
#include <thread>

#include <rxcpp/rx.hpp>
#include <tango/tango.h>

#include "context.hpp"

namespace rxtango {

/**
 * Write @p value to attribute @p name on @p device and emit the written value.
 *
 * The cppTango write runs on a background thread.  The Observable completes
 * immediately after the write, emitting the written value so the next pipeline
 * step can use it (e.g. further writes, reads, or formatting steps).
 *
 * Example — write double_scalar_w then print confirmation:
 * @code
 *   rxtango::write_attribute("sys/tg_test/1", "double_scalar_w", 3.14)
 *       .flat_map([](double v) { return rxtango::read_attribute<double>("sys/tg_test/1", "double_scalar_w"); })
 *       .subscribe([](double v) { std::cout << "confirmed: " << v << "\n"; });
 * @endcode
 */
template<typename T>
rxcpp::observable<T> write_attribute(const std::string& device,
                                      const std::string& name,
                                      T                  value) {
    return rxcpp::observable<>::create<T>([device, name, value](rxcpp::subscriber<T> sub) {
        std::thread([device, name, value, sub]() mutable {
            try {
                Tango::DeviceProxy&    proxy = TangoContext::instance().get_proxy(device);
                Tango::DeviceAttribute da(const_cast<std::string&>(name), value);
                proxy.write_attribute(da);
                if (sub.is_subscribed()) {
                    sub.on_next(value);        // re-emit so the chain can continue
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
