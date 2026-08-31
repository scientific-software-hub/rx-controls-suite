#pragma once
/**
 * @file errors.hpp
 * @brief Per-update monitor failures, carried as messages rather than exceptions.
 *
 * Mirrors Python's rxepics.errors.PvUpdateError.
 *
 * The suite's design principle: errors and status transitions are *messages*
 * carried on the stream, not exceptions that stop the process
 * (Khokhriakov et al., J. Synchrotron Rad. 29, 644-653, 2022).  Rx's on_error is
 * a *terminal* notification, so a single bad monitor update must never travel
 * that path — it is delivered as a value on rxepics::monitor_errors() instead.
 */

#include <chrono>
#include <exception>
#include <stdexcept>
#include <string>

namespace rxepics {

/**
 * A single PV monitor update that failed to convert, or that PVXS itself
 * rejected (a RemoteError from the server, a client-side decode failure).
 *
 * Derives from std::runtime_error so it composes with code that expects an
 * exception, but it is only ever delivered as a *value* on
 * rxepics::monitor_errors() — never thrown, never routed through on_error —
 * because one bad update must not terminate a long-lived monitor.
 *
 * Copyable (rxcpp requires observed types to be copy-constructible).
 */
struct PvUpdateError : std::runtime_error {
    std::string                           pv_name;
    /// The underlying PVXS/std exception, if the failure came with one.
    /// Null when the update was structurally fine but unconvertible to T
    /// only in a way we detected ourselves.
    std::exception_ptr                    cause;
    std::chrono::system_clock::time_point timestamp;

    PvUpdateError(std::string pv, std::string detail,
                  std::exception_ptr c = nullptr)
        : std::runtime_error(pv + ": " + detail)
        , pv_name(std::move(pv))
        , cause(std::move(c))
        , timestamp(std::chrono::system_clock::now()) {}
};

} // namespace rxepics
