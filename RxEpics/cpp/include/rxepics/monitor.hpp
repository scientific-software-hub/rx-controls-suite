#pragma once
/**
 * @file monitor.hpp
 * @brief EPICS PV monitor subscription as a push Observable.
 *
 * Mirrors Python's rxepics.monitor — monitor_pv() (values) and monitor_errors()
 * (per-update failures as messages).
 *
 * Observable contract:
 *   on_next(value)* — emits on every PV update; never calls on_completed.
 *   on_error(e)     — ONLY on a setup failure (the PVXS subscription cannot be
 *                     created).  A transient per-update failure is a *message*,
 *                     never a terminal notification — see the resilience note in
 *                     README.md and CLAUDE.md.
 *   Disposing destroys the PVXS Subscription handle, which cancels the monitor.
 *
 * PVXS callbacks arrive on a PVXS internal thread.  The shared mutex serializes
 * concurrent updates, mirroring rxtango::monitor_attribute's EventCallback mutex
 * and Python's call_soon_threadsafe.
 *
 * Note: prefer monitor_pv() over interval+read_pv() when the IOC has PVA monitors
 * configured — the IOC pushes updates rather than the client polling.  This is the
 * primary streaming primitive (mirrors Python: "monitor_pv() is the primary
 * streaming primitive").
 */

#include <exception>
#include <functional>
#include <iostream>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>

#include <rxcpp/rx.hpp>
#include <pvxs/client.h>
#include <pvxs/data.h>

#include "context.hpp"
#include "errors.hpp"

namespace rxepics {

namespace detail {

/// One warning line to std::cerr — the closest analog to Python's
/// logging.warning(), whose default handler also writes to stderr.  Callers who
/// want these in-band should use rxepics::monitor_errors() instead.
inline void monitor_warn(const std::string& pv, const std::string& msg,
                         std::exception_ptr cause = nullptr) {
    std::string line = msg;
    if (cause) {
        try {
            std::rethrow_exception(cause);
        } catch (const std::exception& e) {
            line += std::string(": ") + e.what();
        } catch (...) {
            line += ": unknown error";
        }
    }
    std::cerr << "[rxepics::monitor] " << pv << ": " << line << "\n";
}

/**
 * Shared PVA-subscription plumbing for the update-driven observables — the direct
 * analog of Python's rxepics.monitor._monitor_updates().
 *
 * @p handler is invoked once per update outcome: exactly one of
 *   - @p update is valid()             (a successful pop), or
 *   - @p cause is non-null             (pop() threw — a RemoteError or a
 *                                        client-side failure)
 * holds on each call.  The handler decides how that outcome becomes (or does not
 * become) a message on the stream; it never terminates the stream on its own.
 *
 * Only a failure of MonitorBuilder::exec() — the subscription cannot be created —
 * reaches on_error.  That is the sole terminal path, matching Python.
 *
 * Connected/Disconnected events are masked: the value stream carries values only,
 * and link state belongs to rxepics::connection_status().  PVXS re-establishes a
 * dropped monitor on reconnect on its own (as caproto does for CA), so no
 * client-side reconnect logic is needed here.
 *
 * NOTE — divergence from Python: caproto dedupes Subscription objects by
 * parameters, so Python's monitor_pv() and monitor_errors() on the same PV share
 * one CA subscription.  PVXS has no such cache — each call here opens its own PVA
 * subscription.  To share one, publish a single monitor_updates() stream
 * (.publish().ref_count()).
 */
template<typename E>
rxcpp::observable<E> monitor_updates(
        const std::string&                                       name,
        pvxs::client::Context&                                   ctx,
        std::function<void(const rxcpp::subscriber<E>&,
                           const pvxs::Value&,
                           std::exception_ptr)>                  handler) {
    return rxcpp::observable<>::create<E>(
        [name, &ctx, handler](rxcpp::subscriber<E> sub) {
            auto sub_ptr = std::make_shared<rxcpp::subscriber<E>>(sub);
            auto mtx_ptr = std::make_shared<std::mutex>();

            std::shared_ptr<pvxs::client::Subscription> mon;
            try {
                mon = ctx.monitor(name)
                    .maskConnected(true)
                    .maskDisconnected(true)
                    .event([sub_ptr, mtx_ptr, handler](pvxs::client::Subscription& s) {
                        std::lock_guard<std::mutex> lock(*mtx_ptr);
                        if (!sub_ptr->is_subscribed()) return;
                        // Drain the event queue — PVXS fires event() on an
                        // empty->non-empty transition, so a single pop() per
                        // callback would stall the stream after the first update.
                        while (true) {
                            pvxs::Value update;
                            try {
                                update = s.pop();
                            } catch (const pvxs::client::Finished&) {
                                return;   // server ended the subscription
                            } catch (...) {
                                // Transient: hand it to the handler as a message
                                // and keep draining — never terminate.
                                handler(*sub_ptr, pvxs::Value(),
                                        std::current_exception());
                                continue;
                            }
                            if (!update) return;   // queue drained
                            handler(*sub_ptr, update, nullptr);
                        }
                    })
                    .exec();
            } catch (...) {
                // Setup failure — the one terminal path.
                if (sub.is_subscribed())
                    sub.on_error(std::current_exception());
                return;
            }

            // Keep the handle alive until unsubscribe; its dtor cancels the monitor.
            sub.get_subscription().add([mon, sub_ptr]() {
                (void)mon;
                (void)sub_ptr;
            });
        });
}

} // namespace detail

/**
 * Return a push Observable that emits the PV value on every PVXS update.
 *
 * @tparam T    Scalar type extracted from the "value" field (default: double).
 * @param name  PV name, e.g. "TEST:CALC".
 * @param ctx   PVXS client context.
 *
 * The Observable never completes — it runs until the returned subscription is
 * disposed, at which point the PVXS Subscription handle is destroyed and the
 * monitor is cancelled.
 *
 * A value that fails to convert to @p T, or an update PVXS itself rejects, is
 * written as one line to std::cerr and skipped — it does NOT terminate the
 * stream.  Use rxepics::monitor_errors<T>() to observe these as messages
 * instead.  Only a *setup* failure (the subscription cannot be created) is
 * terminal and reaches on_error.
 *
 * Example:
 * @code
 *   auto sub = rxepics::monitor_pv<double>("TEST:CALC")
 *       .subscribe([](double v) { std::cout << v << "\n"; });
 *   // ...
 *   sub.unsubscribe();   // destroys the PVXS handle → monitor cancelled
 * @endcode
 */
template<typename T = double>
rxcpp::observable<T> monitor_pv(const std::string&     name,
                                pvxs::client::Context& ctx = default_context()) {
    return detail::monitor_updates<T>(
        name, ctx,
        [name](const rxcpp::subscriber<T>& sub, const pvxs::Value& update,
               std::exception_ptr cause) {
            if (cause) {
                detail::monitor_warn(name, "monitor update error", cause);
                return;
            }
            try {
                sub.on_next(update["value"].as<T>());
            } catch (const std::exception& e) {
                detail::monitor_warn(
                    name, std::string("failed to convert monitor update: ") + e.what());
            }
        });
}

/**
 * Return a push Observable of rxepics::PvUpdateError — one message per bad update.
 *
 * @tparam T  The scalar type the paired monitor_pv<T>() converts to; this stream
 *            validates the *same* conversion so it flags exactly the updates
 *            monitor_pv<T>() would drop (default: double).
 *
 * Never completes and never calls on_error for a per-update failure — only a
 * setup failure is terminal, matching monitor_pv().  Opens its own PVA
 * subscription (PVXS does not dedupe as caproto does).
 *
 * Example — values plus errors in one view:
 * @code
 *   rxcpp::observable<>::merge(
 *       rxepics::monitor_pv<double>("TEST:CALC")
 *           .map([](double v) { return "value  " + std::to_string(v); }),
 *       rxepics::monitor_errors<double>("TEST:CALC")
 *           .map([](const rxepics::PvUpdateError& e) {
 *               return std::string("BAD    ") + e.what(); })
 *   ).subscribe([](const std::string& line) { std::cout << line << "\n"; });
 * @endcode
 */
template<typename T = double>
rxcpp::observable<PvUpdateError>
monitor_errors(const std::string&     name,
               pvxs::client::Context& ctx = default_context()) {
    return detail::monitor_updates<PvUpdateError>(
        name, ctx,
        [name](const rxcpp::subscriber<PvUpdateError>& sub, const pvxs::Value& update,
               std::exception_ptr cause) {
            if (cause) {
                std::string detail;
                try {
                    std::rethrow_exception(cause);
                } catch (const std::exception& e) {
                    detail = e.what();
                } catch (...) {
                    detail = "unknown error";
                }
                sub.on_next(PvUpdateError(name, detail, cause));
                return;
            }
            try {
                (void)update["value"].as<T>();
            } catch (const std::exception& e) {
                sub.on_next(PvUpdateError(
                    name, std::string("unconvertible update: ") + e.what(),
                    std::current_exception()));
            }
        });
}

} // namespace rxepics
