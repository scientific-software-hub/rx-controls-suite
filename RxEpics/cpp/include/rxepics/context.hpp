#pragma once
/**
 * @file context.hpp
 * @brief Shared PVXS client context — the C++ analog of rxepics.context.EpicsContext.
 *
 * Provides a process-wide Meyers-singleton wrapping a `pvxs::client::Context`.
 * Created from the environment (`PVXS_*` / `EPICS_PVA_*` env vars) on first access
 * and cleaned up automatically on process exit.
 *
 * Thread-safe: `pvxs::client::Context` is internally thread-safe; the singleton
 * itself is protected by C++11 static-local initialization guarantees.
 *
 * Mirrors Python's rxepics.context.EpicsContext.
 */

#include <pvxs/client.h>

namespace rxepics {

/**
 * Process-wide singleton wrapping a `pvxs::client::Context`.
 *
 * Usage:
 * @code
 *   auto& ctx = rxepics::EpicsContext::instance().context();
 *   auto val = ctx.get("TEST:DOUBLE").exec()->wait(5.0);
 * @endcode
 *
 * Mirrors Python's EpicsContext.get() and rxepics.channel.read_pv(name, ctx).
 */
class EpicsContext {
    pvxs::client::Context ctx_;

    EpicsContext()  : ctx_(pvxs::client::Context::fromEnv()) {}
    ~EpicsContext() = default;

public:
    EpicsContext(const EpicsContext&)            = delete;
    EpicsContext& operator=(const EpicsContext&) = delete;

    /** Return the process-wide singleton instance. */
    static EpicsContext& instance() noexcept {
        static EpicsContext inst;   // Meyers singleton — thread-safe in C++11+
        return inst;
    }

    /** Return a reference to the underlying PVXS client context. */
    pvxs::client::Context& context() noexcept { return ctx_; }

    /** Close and release resources (called automatically on shutdown). */
    void close() { ctx_ = pvxs::client::Context{}; }
};

/**
 * Convenience free function — returns the process-wide PVXS context.
 * Mirrors Python's EpicsContext.get() used as a default context argument.
 */
inline pvxs::client::Context& default_context() {
    return EpicsContext::instance().context();
}

} // namespace rxepics
