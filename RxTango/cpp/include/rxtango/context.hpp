#pragma once
/**
 * @file context.hpp
 * @brief Shared DeviceProxy cache — the C++ analog of rxtango.context.TangoContext.
 *
 * Provides a process-wide Meyers-singleton cache of Tango::DeviceProxy objects,
 * created lazily on first access and cleaned up on destruction (mirroring
 * Python's atexit-registered TangoContext.close()).
 *
 * Thread-safe: the proxy map is protected by a mutex.  Each DeviceProxy is
 * thread-safe within the cppTango library once created.
 */

#include <map>
#include <memory>
#include <mutex>
#include <string>
#include <tango/tango.h>

namespace rxtango {

/**
 * Process-wide singleton cache of Tango::DeviceProxy objects.
 *
 * Usage:
 * @code
 *   Tango::DeviceProxy& proxy = TangoContext::get_proxy("tango://localhost:10000/sys/tg_test/1");
 *   Tango::DeviceAttribute da = proxy.read_attribute("double_scalar");
 * @endcode
 *
 * Mirrors Python's TangoContext.get_proxy() and Java's TangoProxies.newDeviceProxyWrapper().
 */
class TangoContext {
    std::map<std::string, std::unique_ptr<Tango::DeviceProxy>> cache_;
    std::mutex mtx_;

    TangoContext()  = default;
    ~TangoContext() = default;

public:
    // Non-copyable, non-movable singleton
    TangoContext(const TangoContext&)            = delete;
    TangoContext& operator=(const TangoContext&) = delete;

    /** Return the process-wide singleton instance. */
    static TangoContext& instance() noexcept {
        static TangoContext inst;   // Meyers singleton — thread-safe in C++11+
        return inst;
    }

    /**
     * Return a cached DeviceProxy for @p device, creating it on first access.
     *
     * @param device  TANGO device URL, e.g. "tango://localhost:10000/sys/tg_test/1".
     * @return Reference to the cached proxy (lifetime = process lifetime).
     */
    Tango::DeviceProxy& get_proxy(const std::string& device) {
        std::lock_guard<std::mutex> lock(mtx_);
        auto it = cache_.find(device);
        if (it == cache_.end()) {
            cache_[device] = std::make_unique<Tango::DeviceProxy>(const_cast<std::string&>(
                const_cast<std::string&>(device)));
            return *cache_[device];
        }
        return *it->second;
    }

    /** Release all cached proxies (called automatically on shutdown). */
    void close() {
        std::lock_guard<std::mutex> lock(mtx_);
        cache_.clear();
    }
};

/**
 * Convenience free function — mirrors Python's `TangoContext.get_proxy(device)`.
 * Returns a reference to the cached proxy for @p device.
 */
inline Tango::DeviceProxy& get_proxy(const std::string& device) {
    return TangoContext::instance().get_proxy(device);
}

} // namespace rxtango
