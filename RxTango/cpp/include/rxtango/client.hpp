#pragma once
/**
 * @file client.hpp
 * @brief Fluent TangoClient — mirrors rxtango.client.TangoClient (Python).
 *
 * Each method appends a step to an internal rx chain.  Nothing executes until
 * subscribe() is called.  Results flow through the chain via std::any, so each
 * step receives the value produced by the previous step.
 *
 * write() and execute() can take the previous step's value, a static value, or
 * a callable that transforms the previous value.
 */

#include <any>
#include <functional>
#include <optional>
#include <stdexcept>
#include <string>

#include <rxcpp/rx.hpp>

#include "attribute.hpp"
#include "attribute_write.hpp"
#include "command.hpp"
#include "monitor.hpp"

namespace rxtango {

/**
 * Fluent builder for sequential Tango operations.
 *
 * Steps are NOT executed until subscribe() is called.  Each step's result
 * (wrapped in std::any) becomes the input to the next step.  Use map() to
 * apply pure transformations; use std::any_cast<T> inside map() to unwrap.
 *
 * Example — read, calibrate, write back:
 * @code
 *   TangoClient()
 *       .read(device, "double_scalar")
 *       .map([](std::any v) -> std::any { return std::any_cast<double>(v) * 2.0 + 1.5; })
 *       .write(device, "double_scalar_w")
 *       .subscribe(
 *           [](std::any v) { std::cout << std::any_cast<double>(v) << "\n"; },
 *           [](std::exception_ptr e) { ... },
 *           []() { std::cout << "done\n"; }
 *       );
 * @endcode
 *
 * Mirrors Python's TangoClient and Java's TangoClient fluent builder.
 */
class TangoClient {
    rxcpp::observable<std::any> chain_;
    bool                        has_chain_{false};

    // Helper: wrap an observable<T> as observable<std::any>
    template<typename T>
    static rxcpp::observable<std::any> wrap(rxcpp::observable<T> obs) {
        return obs.map([](T v) -> std::any { return v; });
    }

public:
    TangoClient() = default;

    // ------------------------------------------------------------------
    // read
    // ------------------------------------------------------------------

    /**
     * Read attribute @p attr from @p device.
     * If first step: seeds the chain.  Otherwise: discards previous value and reads.
     */
    TangoClient& read(const std::string& device, const std::string& attr) {
        auto step = wrap(read_attribute<double>(device, attr));
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

    /**
     * Subscribe to Tango events for @p attr on @p device (push, multi-value).
     * Must be the first step; chaining after another step is not supported.
     */
    TangoClient& monitor(const std::string& device,
                          const std::string& attr,
                          const std::string& event = "change") {
        if (has_chain_)
            throw std::runtime_error("monitor() must be the first step in a TangoClient chain");
        chain_     = wrap(monitor_attribute<double>(device, attr, event));
        has_chain_ = true;
        return *this;
    }

    // ------------------------------------------------------------------
    // write  (three overloads mirroring Python's value/None/callable modes)
    // ------------------------------------------------------------------

    /** Write the previous step's value to @p attr (passes it through). */
    TangoClient& write(const std::string& device, const std::string& attr) {
        chain_ = chain_.flat_map([device, attr](std::any prev) {
            double v = std::any_cast<double>(prev);
            return wrap(write_attribute<double>(device, attr, v));
        });
        return *this;
    }

    /** Write a static @p value; ignores the previous step's value. */
    TangoClient& write(const std::string& device, const std::string& attr, double value) {
        chain_ = chain_.flat_map([device, attr, value](std::any) {
            return wrap(write_attribute<double>(device, attr, value));
        });
        return *this;
    }

    /**
     * Write a value computed from the previous step.
     * @p fn receives the previous value as double and returns the value to write.
     */
    TangoClient& write(const std::string&                device,
                       const std::string&                attr,
                       std::function<double(double)>     fn) {
        chain_ = chain_.flat_map([device, attr, fn](std::any prev) {
            double v = fn(std::any_cast<double>(prev));
            return wrap(write_attribute<double>(device, attr, v));
        });
        return *this;
    }

    // ------------------------------------------------------------------
    // execute
    // ------------------------------------------------------------------

    /** Execute command @p cmd with no argument; emits argout (double). */
    TangoClient& execute(const std::string& device, const std::string& cmd) {
        if (!has_chain_) {
            chain_     = wrap(execute_command<double>(device, cmd));
            has_chain_ = true;
        } else {
            chain_ = chain_.flat_map([device, cmd](std::any) {
                return wrap(execute_command<double>(device, cmd));
            });
        }
        return *this;
    }

    /** Execute command @p cmd with a static @p argin. */
    TangoClient& execute(const std::string& device, const std::string& cmd, double argin) {
        if (!has_chain_) {
            chain_     = wrap(execute_command<double, double>(device, cmd, argin));
            has_chain_ = true;
        } else {
            chain_ = chain_.flat_map([device, cmd, argin](std::any) {
                return wrap(execute_command<double, double>(device, cmd, argin));
            });
        }
        return *this;
    }

    /** Execute command @p cmd with argin computed from the previous step. */
    TangoClient& execute(const std::string&              device,
                          const std::string&              cmd,
                          std::function<double(double)>   argin_fn) {
        chain_ = chain_.flat_map([device, cmd, argin_fn](std::any prev) {
            double argin = argin_fn(std::any_cast<double>(prev));
            return wrap(execute_command<double, double>(device, cmd, argin));
        });
        return *this;
    }

    // ------------------------------------------------------------------
    // map
    // ------------------------------------------------------------------

    /**
     * Apply a pure transformation to the current value without any I/O.
     * @p fn receives and returns std::any; use std::any_cast<T> to unwrap.
     */
    TangoClient& map(std::function<std::any(std::any)> fn) {
        chain_ = chain_.map(fn);
        return *this;
    }

    // ------------------------------------------------------------------
    // Terminal
    // ------------------------------------------------------------------

    /**
     * Subscribe to the chain.  Execution starts immediately.
     * Returns a composite_subscription that can be used to cancel the chain.
     *
     * @throws std::runtime_error if the chain is empty (no steps added).
     */
    rxcpp::composite_subscription subscribe(
        std::function<void(std::any)>          on_next      = {},
        std::function<void(std::exception_ptr)> on_error    = {},
        std::function<void()>                  on_completed = {}) {
        if (!has_chain_)
            throw std::runtime_error(
                "TangoClient chain is empty — add at least one step before subscribing");
        return chain_.subscribe(on_next, on_error, on_completed);
    }
};

} // namespace rxtango
