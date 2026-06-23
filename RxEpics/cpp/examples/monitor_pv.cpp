/**
 * Monitor an EPICS PV using PVXS push subscriptions — the primary streaming primitive.
 *
 * The IOC pushes updates at its own scan rate; no client-side polling needed.
 * Mirrors Python's monitor_pv.py (rxepics.monitor.monitor_pv).
 *
 * Usage:
 *   EPICS_PVA_ADDR_LIST=localhost ./monitor_pv [pv]
 *   defaults: TEST:CALC
 */

#include <csignal>
#include <iostream>
#include <string>

#include <rxepics/rxepics.hpp>

static volatile sig_atomic_t g_running = 1;

int main(int argc, char* argv[]) {
    const std::string pv = argc > 1 ? argv[1] : "TEST:CALC";

    std::signal(SIGINT, [](int) { g_running = 0; });

    auto& ctx = rxepics::default_context();

    std::cout << "Monitoring " << pv << "  (Ctrl+C to stop)\n\n";

    auto sub = rxepics::monitor_pv<double>(pv, ctx)
        .subscribe(
            [](double v) { std::cout << "  update: " << v << "\n"; },
            [](std::exception_ptr e) {
                try { std::rethrow_exception(e); }
                catch (std::exception& ex) { std::cerr << "  ERROR: " << ex.what() << "\n"; }
            }
        );

    while (g_running) std::this_thread::sleep_for(std::chrono::milliseconds(100));
    sub.unsubscribe();
    std::cout << "\n  stopped.\n";
    return 0;
}
