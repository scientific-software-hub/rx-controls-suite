#pragma once
/**
 * @file command.hpp
 * @brief Single-shot Tango command execution as an Observable.
 *
 * Mirrors Python's rxtango.command.execute_command() and Java's RxTangoCommand<T,V>.
 * EPICS has no commands — this is Tango-specific.
 *
 * Observable contract:
 *   on_next(argout) → on_completed()   on success
 *   on_error(e)                         on any Tango exception
 *   Exactly one on_next — single-shot.
 */

#include <exception>
#include <optional>
#include <string>
#include <thread>

#include <rxcpp/rx.hpp>
#include <tango/tango.h>

#include "context.hpp"

namespace rxtango {

/**
 * Execute command @p cmd on @p device and emit the argout as @p ResultT.
 *
 * @tparam ResultT   Type to extract from the result DeviceData (default: double).
 * @tparam ArginT    Type of the optional input argument (default: double).
 * @param device     TANGO device URL.
 * @param cmd        Command name (e.g. "DevDouble", "State").
 * @param argin      Optional input argument; std::nullopt → command called with no input.
 *
 * Example — run the DevDouble command (doubles a value):
 * @code
 *   rxtango::execute_command<double, double>(device, "DevDouble", 3.14)
 *       .subscribe([](double v) { std::cout << "result: " << v << "\n"; });
 * @endcode
 */
template<typename ResultT = double, typename ArginT = double>
rxcpp::observable<ResultT> execute_command(const std::string&           device,
                                            const std::string&           cmd,
                                            std::optional<ArginT>        argin = std::nullopt) {
    return rxcpp::observable<>::create<ResultT>(
        [device, cmd, argin](rxcpp::subscriber<ResultT> sub) {
            std::thread([device, cmd, argin, sub]() mutable {
                try {
                    Tango::DeviceProxy& proxy = TangoContext::instance().get_proxy(device);
                    Tango::DeviceData result;
                    if (argin.has_value()) {
                        Tango::DeviceData dd;
                        dd << argin.value();
                        result = proxy.command_inout(const_cast<std::string&>(cmd), dd);
                    } else {
                        result = proxy.command_inout(const_cast<std::string&>(cmd));
                    }
                    ResultT value;
                    result >> value;
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
