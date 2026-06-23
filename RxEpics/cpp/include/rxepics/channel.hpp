#pragma once
/**
 * @file channel.hpp
 * @brief Single-shot EPICS PV read as an Observable.
 *
 * Mirrors Python's rxepics.channel.read_pv() and Java has no EPICS equivalent.
 *
 * Observable contract:
 *   on_next(value) → on_completed()    on success
 *   on_error(e)                         on any PVXS exception
 *   Exactly one on_next — single-shot.
 *
 * PVXS returns a `pvxs::Value` struct; we extract the scalar field "value"
 * as type T — equivalent to caproto's `reading.data[0]`.
 */

#include <exception>
#include <string>
#include <thread>

#include <rxcpp/rx.hpp>
#include <pvxs/client.h>

#include "context.hpp"

namespace rxepics {

/**
 * Return an Observable that reads PV @p name and emits one value.
 *
 * @tparam T    Scalar type to extract from the PV value (default: double).
 *              The PVXS field "value" is cast via `.as<T>()`.
 * @param name  PV name, e.g. "TEST:DOUBLE".
 * @param ctx   PVXS client context (defaults to the process singleton).
 *
 * The PVXS call runs on a background thread (non-blocking subscribe).
 * Arrays: take index [0] for scalars — EPICS may return array types.
 *
 * Example:
 * @code
 *   rxepics::read_pv<double>("TEST:DOUBLE")
 *       .subscribe([](double v) { std::cout << v << "\n"; });
 * @endcode
 */
template<typename T = double>
rxcpp::observable<T> read_pv(const std::string&          name,
                               pvxs::client::Context&      ctx = default_context()) {
    return rxcpp::observable<>::create<T>([name, &ctx](rxcpp::subscriber<T> sub) {
        std::thread([name, &ctx, sub]() mutable {
            try {
                auto val = ctx.get(name).exec()->wait(5.0);
                T value  = val["value"].as<T>();
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

} // namespace rxepics
