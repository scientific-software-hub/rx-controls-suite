#pragma once
/**
 * @file monitor.hpp
 * @brief EPICS PV monitor subscription as a push Observable.
 *
 * Mirrors Python's rxepics.monitor.monitor_pv().
 *
 * Observable contract:
 *   on_next(value)* — emits on every PV update; never calls on_completed.
 *   on_error(e)     — on subscription failure.
 *   Disposing destroys the PVXS Monitor handle, which cancels the subscription.
 *
 * PVXS callbacks arrive on a PVXS internal thread.  The mutex in the lambda
 * serializes concurrent updates, mirroring rxtango::monitor_attribute's EventCallback
 * mutex and Python's call_soon_threadsafe.
 *
 * Note: prefer monitor_pv() over interval+read_pv() when the IOC has CA/PVA
 * monitors configured — the IOC pushes updates rather than the client polling.
 * This is the primary streaming primitive (mirrors Python: "monitor_pv() is the
 * primary streaming primitive").
 */

#include <exception>
#include <memory>
#include <mutex>
#include <string>

#include <rxcpp/rx.hpp>
#include <pvxs/client.h>

#include "context.hpp"

namespace rxepics {

/**
 * Return a push Observable that emits the PV value on every PVXS update.
 *
 * @tparam T    Scalar type extracted from "value" field (default: double).
 * @param name  PV name, e.g. "TEST:CALC".
 * @param ctx   PVXS client context.
 *
 * The Observable never completes — it runs until the returned subscription is
 * disposed, at which point the PVXS Monitor handle is destroyed and the
 * CA/PVA subscription is cancelled.
 *
 * Example:
 * @code
 *   auto sub = rxepics::monitor_pv<double>("TEST:CALC")
 *       .subscribe([](double v) { std::cout << v << "\n"; });
 *   // ...
 *   sub.unsubscribe();   // destroys PVXS Monitor → subscription cancelled
 * @endcode
 */
template<typename T = double>
rxcpp::observable<T> monitor_pv(const std::string&      name,
                                  pvxs::client::Context&  ctx = default_context()) {
    return rxcpp::observable<>::create<T>([name, &ctx](rxcpp::subscriber<T> sub) {
        // Capture subscriber in a shared_ptr so the callback lambda can hold it.
        auto sub_ptr = std::make_shared<rxcpp::subscriber<T>>(sub);
        auto mtx_ptr = std::make_shared<std::mutex>();

        // PVXS Monitor — heap-allocated; shared_ptr drives its lifetime.
        auto monitor_ptr = std::make_shared<pvxs::client::Monitor>(
            ctx.monitor(name)
                .event([sub_ptr, mtx_ptr](pvxs::client::Subscription& s) {
                    std::lock_guard<std::mutex> lock(*mtx_ptr);
                    if (!sub_ptr->is_subscribed()) return;
                    try {
                        auto val = s.pop();
                        if (!val) return;          // null → end-of-batch marker, skip
                        T value = (*val)["value"].as<T>();
                        sub_ptr->on_next(value);
                    } catch (...) {
                        // individual update decode failures are silently dropped
                    }
                })
                .exec()
        );

        // Cleanup: when unsubscribed, destroy the Monitor (→ subscription cancelled).
        sub.get_subscription().add([monitor_ptr, sub_ptr]() {
            // monitor_ptr destructor → pvxs::client::Monitor dtor → unsubscribe
            (void)monitor_ptr;
            (void)sub_ptr;
        });
    });
}

} // namespace rxepics
