/**
 * Resilient monitor — values, per-update errors, and link state as one merged
 * stream.  Errors and status transitions are messages, not exceptions that stop
 * the process.
 *
 * Mirrors Python's resilient_monitor.py (RxEpics/python/examples/).
 *
 * Run this, then in another shell restart the IOC out from under it:
 *
 *     cd RxEpics/python
 *     docker compose stop epics-ioc
 *     docker compose start epics-ioc
 *
 * The stream survives: link goes DOWN, no traceback, and once the IOC comes back
 * the link goes UP and values resume — PVXS re-arms the subscription on its own,
 * with no client-side action.
 *
 * Usage:
 *   EPICS_PVA_ADDR_LIST=localhost ./resilient_monitor [pv_name]
 *   default: TEST:CALC
 */

#include <chrono>
#include <csignal>
#include <iostream>
#include <string>
#include <vector>

#include <rxcpp/rx.hpp>
#include <rxepics/rxepics.hpp>

static volatile sig_atomic_t g_running = 1;

static long long now_ms() {
    return std::chrono::duration_cast<std::chrono::milliseconds>(
               std::chrono::system_clock::now().time_since_epoch())
        .count();
}

int main(int argc, char* argv[]) {
    const std::string pv = argc > 1 ? argv[1] : "TEST:CALC";

    std::signal(SIGINT, [](int) { g_running = 0; });

    auto& ctx = rxepics::default_context();

    std::cout << "Resilient monitor on " << pv << " — Ctrl+C to stop\n"
              << "Try: (cd RxEpics/python && docker compose stop epics-ioc"
                 " ; docker compose start epics-ioc)\n\n";

    // Three independent streams, tagged and merged into one console view.  Each
    // is a message on the wire, never a terminal notification — a bad update or a
    // dropped link shows up as a line of output, not a crash.  as_dynamic()
    // erases their distinct operator types so they share one vector element type.
    std::vector<rxcpp::observable<std::string>> streams{
        rxepics::monitor_pv<double>(pv, ctx)
            .map([](double v) {
                return "[" + std::to_string(now_ms()) + "]  value       " +
                       std::to_string(v);
            })
            .as_dynamic(),
        rxepics::monitor_errors<double>(pv, ctx)
            .map([](const rxepics::PvUpdateError& e) {
                return "[" + std::to_string(now_ms()) + "]  BAD UPDATE  " +
                       std::string(e.what());
            })
            .as_dynamic(),
        rxepics::connection_status(pv, ctx)
            .map([](bool up) {
                return "[" + std::to_string(now_ms()) + "]  link        " +
                       std::string(up ? "UP" : "DOWN");
            })
            .as_dynamic(),
    };

    auto sub = rxcpp::observable<>::iterate(streams)
        .flat_map([](rxcpp::observable<std::string> s) { return s; })
        .subscribe(
            [](const std::string& line) { std::cout << line << "\n"; },
            [](std::exception_ptr e) {
                try { std::rethrow_exception(e); }
                catch (std::exception& ex) {
                    std::cerr << "FATAL (setup failure): " << ex.what() << "\n";
                }
            });

    while (g_running) std::this_thread::sleep_for(std::chrono::milliseconds(100));
    sub.unsubscribe();
    return 0;
}
