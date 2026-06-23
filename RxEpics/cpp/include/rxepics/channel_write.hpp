#pragma once
/**
 * @file channel_write.hpp
 * @brief Single-shot EPICS PV write as an Observable.
 *
 * Mirrors Python's rxepics.channel_write.write_pv().
 *
 * Observable contract:
 *   on_next(written_value) → on_completed()   on success
 *   on_error(e)                                on any PVXS exception
 *
 * Re-emitting the written value allows writes to chain naturally into subsequent
 * pipeline steps — the same design as rxtango::write_attribute.
 */

#include <exception>
#include <string>
#include <thread>

#include <rxcpp/rx.hpp>
#include <pvxs/client.h>

#include "context.hpp"

namespace rxepics {

/**
 * Write @p value to PV @p name and emit the written value.
 *
 * @tparam T    Scalar type to write (default: double).
 * @param name  PV name.
 * @param value Value to write.
 * @param ctx   PVXS client context.
 *
 * Example:
 * @code
 *   rxepics::write_pv<double>("TEST:DOUBLE", 3.14)
 *       .flat_map([](double v) { return rxepics::read_pv<double>("TEST:DOUBLE"); })
 *       .subscribe([](double v) { std::cout << "confirmed: " << v << "\n"; });
 * @endcode
 */
template<typename T = double>
rxcpp::observable<T> write_pv(const std::string&        name,
                                T                         value,
                                pvxs::client::Context&    ctx = default_context()) {
    return rxcpp::observable<>::create<T>([name, value, &ctx](rxcpp::subscriber<T> sub) {
        std::thread([name, value, &ctx, sub]() mutable {
            try {
                ctx.put(name).set("value", value).exec()->wait(5.0);
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

} // namespace rxepics
