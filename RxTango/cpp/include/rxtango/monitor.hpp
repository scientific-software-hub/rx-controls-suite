#pragma once
/**
 * @file monitor.hpp
 * @brief Tango event subscription as a push Observable.
 *
 * Mirrors Python's rxtango.monitor.monitor_attribute() and Java's
 * RxTangoAttributeChangePublisher<T>.
 *
 * Observable contract:
 *   on_next(value)* — emits on every Tango event; never calls on_completed.
 *   on_error(e)     — on subscription failure.
 *   Disposing (unsubscribing) calls proxy.unsubscribe_event().
 *
 * Tango event callbacks arrive on a cppTango internal thread.  The mutex in
 * EventCallback serializes concurrent callback invocations, mirroring Java's
 * synchronized(lock) in SubscriberState and Python's call_soon_threadsafe.
 */

#include <algorithm>
#include <exception>
#include <memory>
#include <mutex>
#include <string>

#include <rxcpp/rx.hpp>
#include <tango/tango.h>

#include "context.hpp"

namespace rxtango {

namespace detail {

/**
 * Tango CallBack adapter that forwards push events to an rxcpp subscriber.
 * Heap-allocated and kept alive via shared_ptr for the subscription lifetime.
 */
template<typename T>
class EventCallback : public Tango::CallBack {
    rxcpp::subscriber<T> sub_;
    mutable std::mutex   mtx_;      // serializes concurrent cppTango callback threads

public:
    explicit EventCallback(rxcpp::subscriber<T> sub) : sub_(std::move(sub)) {}

    void push_event(Tango::EventData* ed) override {
        std::lock_guard<std::mutex> lock(mtx_);
        if (!sub_.is_subscribed()) return;
        try {
            if (ed->err) return;     // skip Tango-level error events silently
            T value;
            *ed->attr_value >> value;
            sub_.on_next(value);
        } catch (...) {
            // individual event decode failures are silently dropped
        }
    }
};

inline Tango::EventType event_type_from_string(const std::string& event) {
    std::string ev = event;
    std::transform(ev.begin(), ev.end(), ev.begin(), ::tolower);
    if (ev == "periodic") return Tango::PERIODIC_EVENT;
    if (ev == "archive")  return Tango::ARCHIVE_EVENT;
    return Tango::CHANGE_EVENT;   // default
}

} // namespace detail

/**
 * Return a push Observable that emits the attribute value on every Tango event.
 *
 * @tparam T      Type to extract from the event DeviceAttribute (default: double).
 * @param device  TANGO device URL.
 * @param name    Attribute name.
 * @param event   Event type: "change" (default), "periodic", or "archive".
 *
 * The Observable never completes — it runs until the returned subscription is
 * disposed, at which point unsubscribe_event() is called.
 *
 * Example — monitor double_scalar:
 * @code
 *   auto sub = rxtango::monitor_attribute<double>(device, "double_scalar")
 *       .subscribe([](double v) { std::cout << v << "\n"; });
 *   // ... later ...
 *   sub.unsubscribe();  // tears down the Tango event subscription
 * @endcode
 *
 * Note: Tango events require a properly configured event system (ZMQ ports
 * reachable from the client, event heartbeat).
 */
template<typename T = double>
rxcpp::observable<T> monitor_attribute(const std::string& device,
                                        const std::string& name,
                                        const std::string& event = "change") {
    return rxcpp::observable<>::create<T>([device, name, event](rxcpp::subscriber<T> sub) {
        // Proxy and callback heap-allocated; shared_ptrs keep them alive until cleanup.
        auto proxy    = std::make_shared<Tango::DeviceProxy>(device);
        auto cb       = std::make_shared<detail::EventCallback<T>>(sub);
        auto event_id = std::make_shared<int>(-1);

        Tango::EventType et = detail::event_type_from_string(event);

        try {
            *event_id = proxy->subscribe_event(const_cast<std::string&>(name), et, cb.get());
        } catch (...) {
            sub.on_error(std::current_exception());
            return;
        }

        // Cleanup: runs when the subscriber is unsubscribed.
        // Capture shared_ptrs so proxy and cb remain alive until here.
        sub.get_subscription().add([proxy, cb, event_id]() {
            if (*event_id >= 0) {
                try { proxy->unsubscribe_event(*event_id); } catch (...) {}
                *event_id = -1;
            }
        });
    });
}

} // namespace rxtango
