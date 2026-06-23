#pragma once
/**
 * @file client.hpp
 * @brief Fluent EpicsClient — mirrors rxepics.client.EpicsClient (Python).
 *
 * EPICS has no commands — EpicsClient has no execute() method.
 * write() passes a context reference; the builder was constructed with a context.
 *
 * Mirrors Python's EpicsClient (constructed with ctx).
 */

#include <any>
#include <functional>
#include <stdexcept>
#include <string>

#include <rxcpp/rx.hpp>
#include <pvxs/client.h>

#include "channel.hpp"
#include "channel_write.hpp"
#include "monitor.hpp"
#include "context.hpp"

namespace rxepics {

/**
 * Fluent builder for sequential EPICS PV operations.
 *
 * Constructed with a PVXS context reference (defaults to the singleton).
 * Each method appends a step to an internal `rxcpp::observable<std::any>` chain.
 * Nothing executes until `subscribe()` is called.
 *
 * EPICS has no commands — use write_pv() to set a command PV instead.
 *
 * Example — read, calibrate, write back:
 * @code
 *   EpicsClient()
 *       .read("TEST:DOUBLE")
 *       .map([](std::any v) -> std::any { return std::any_cast<double>(v) * 2.0; })
 *       .write("TEST:DOUBLE")
 *       .subscribe(
 *           [](std::any v) { std::cout << std::any_cast<double>(v) << "\n"; },
 *           [](std::exception_ptr e) { ... },
 *           []() { std::cout << "done\n"; }
 *       );
 * @endcode
 *
 * Mirrors Python's EpicsClient.
 */
class EpicsClient {
    pvxs::client::Context&      ctx_;
    rxcpp::observable<std::any> chain_;
    bool                        has_chain_{false};

    template<typename T>
    static rxcpp::observable<std::any> wrap(rxcpp::observable<T> obs) {
        return obs.map([](T v) -> std::any { return v; });
    }

public:
    explicit EpicsClient(pvxs::client::Context& ctx = default_context()) : ctx_(ctx) {}

    // ------------------------------------------------------------------
    // read
    // ------------------------------------------------------------------

    /** Read PV @p name; seeds the chain if first step, otherwise discards prev value. */
    EpicsClient& read(const std::string& name) {
        auto& ctx  = ctx_;
        auto  step = wrap(read_pv<double>(name, ctx));
        if (!has_chain_) {
            chain_     = step;
            has_chain_ = true;
        } else {
            chain_ = chain_.flat_map([step](std::any) { return step; });
        }
        return *this;
    }

    // ------------------------------------------------------------------
    // monitor
    // ------------------------------------------------------------------

    /** Subscribe to PV updates (push, multi-value).  Must be the first step. */
    EpicsClient& monitor(const std::string& name) {
        if (has_chain_)
            throw std::runtime_error("monitor() must be the first step in an EpicsClient chain");
        auto& ctx  = ctx_;
        chain_     = wrap(monitor_pv<double>(name, ctx));
        has_chain_ = true;
        return *this;
    }

    // ------------------------------------------------------------------
    // write
    // ------------------------------------------------------------------

    /** Write the previous step's value to PV @p name (passes it through). */
    EpicsClient& write(const std::string& name) {
        auto& ctx = ctx_;
        chain_ = chain_.flat_map([name, &ctx](std::any prev) {
            double v = std::any_cast<double>(prev);
            return wrap(write_pv<double>(name, v, ctx));
        });
        return *this;
    }

    /** Write a static @p value; ignores the previous step's value. */
    EpicsClient& write(const std::string& name, double value) {
        auto& ctx = ctx_;
        chain_ = chain_.flat_map([name, value, &ctx](std::any) {
            return wrap(write_pv<double>(name, value, ctx));
        });
        return *this;
    }

    /** Write a value computed from the previous step. */
    EpicsClient& write(const std::string& name, std::function<double(double)> fn) {
        auto& ctx = ctx_;
        chain_ = chain_.flat_map([name, fn, &ctx](std::any prev) {
            double v = fn(std::any_cast<double>(prev));
            return wrap(write_pv<double>(name, v, ctx));
        });
        return *this;
    }

    // ------------------------------------------------------------------
    // map
    // ------------------------------------------------------------------

    /** Apply a pure transformation.  Use std::any_cast<T> to unwrap. */
    EpicsClient& map(std::function<std::any(std::any)> fn) {
        chain_ = chain_.map(fn);
        return *this;
    }

    // ------------------------------------------------------------------
    // Terminal
    // ------------------------------------------------------------------

    rxcpp::composite_subscription subscribe(
        std::function<void(std::any)>           on_next      = {},
        std::function<void(std::exception_ptr)> on_error     = {},
        std::function<void()>                   on_completed = {}) {
        if (!has_chain_)
            throw std::runtime_error(
                "EpicsClient chain is empty — add at least one step before subscribing");
        return chain_.subscribe(on_next, on_error, on_completed);
    }
};

} // namespace rxepics
