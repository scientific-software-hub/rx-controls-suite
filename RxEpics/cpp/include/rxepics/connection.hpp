#pragma once
/**
 * @file connection.hpp
 * @brief EPICS PVA channel connection state as a push Observable<bool>.
 *
 * Mirrors Python's rxepics.connection.connection_status().
 *
 * A connection transition is a *message*, never a terminal notification: the
 * observable emits one bool per (dis)connect and never completes or errors.
 * Built on PVXS's Channel-cache handle (Context::connect), the direct analog of
 * caproto's connection_state_callback.
 *
 * Observable contract:
 *   on_next(bool)* — true while connected, false while not; never completes.
 *   Disposing destroys the PVXS Connect handle (its dtor synchronizes with any
 *   in-flight callback — ConnectBuilder::syncCancel defaults to true).
 */

#include <memory>
#include <mutex>
#include <string>

#include <rxcpp/rx.hpp>
#include <pvxs/client.h>

#include "context.hpp"

namespace rxepics {

/**
 * Return a push Observable of bool — true while @p name is connected over PVA.
 *
 * Emits a synthetic `false` immediately on subscribe (PVXS does not report the
 * current state until the Channel-cache entry is created, so this keeps the
 * observable total instead of silent until first connect), then one value per
 * transition, de-duplicated with distinct_until_changed().  Never completes.
 *
 * Composes directly as a Bluesky suspender signal or a status LED:
 * @code
 *   rxepics::connection_status("TEST:CALC")
 *       .subscribe([](bool up) { set_link_led(up); });
 * @endcode
 */
inline rxcpp::observable<bool>
connection_status(const std::string&     name,
                  pvxs::client::Context& ctx = default_context()) {
    return rxcpp::observable<>::create<bool>(
        [name, &ctx](rxcpp::subscriber<bool> sub) {
            auto sub_ptr = std::make_shared<rxcpp::subscriber<bool>>(sub);
            auto mtx_ptr = std::make_shared<std::mutex>();

            {
                std::lock_guard<std::mutex> lock(*mtx_ptr);
                if (sub_ptr->is_subscribed())
                    sub_ptr->on_next(false);
            }

            auto emit = [sub_ptr, mtx_ptr](bool state) {
                std::lock_guard<std::mutex> lock(*mtx_ptr);
                if (sub_ptr->is_subscribed())
                    sub_ptr->on_next(state);
            };

            std::shared_ptr<pvxs::client::Connect> conn;
            try {
                conn = ctx.connect(name)
                    .onConnect([emit]() { emit(true); })
                    .onDisconnect([emit]() { emit(false); })
                    .exec();
            } catch (...) {
                if (sub.is_subscribed())
                    sub.on_error(std::current_exception());
                return;
            }

            // Hold the handle alive until unsubscribe; its dtor blocks on any
            // in-flight callback, so it is safe to drop from this path (never
            // from inside the callback itself).
            sub.get_subscription().add([conn, sub_ptr]() {
                (void)conn;
                (void)sub_ptr;
            });
        })
        .distinct_until_changed();
}

} // namespace rxepics
