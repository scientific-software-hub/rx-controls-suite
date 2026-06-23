/**
 * Poll an EPICS PV at a fixed interval — no loop, no thread.
 *
 * Mirrors Python's poll_pv.py. Prefer monitor_pv for IOCs with scan records;
 * use this when you need client-side rate control independent of the IOC scan.
 *
 * Usage:
 *   EPICS_PVA_ADDR_LIST=localhost ./poll_pv [pv] [interval-ms]
 *   defaults: TEST:CALC  500
 */

#include <chrono>
#include <csignal>
#include <iostream>
#include <string>

#include <rxcpp/rx.hpp>
#include <rxepics/rxepics.hpp>

static volatile sig_atomic_t g_running = 1;

int main(int argc, char* argv[]) {
    const std::string pv          = argc > 1 ? argv[1] : "TEST:CALC";
    const int         interval_ms = argc > 2 ? std::stoi(argv[2]) : 500;

    std::signal(SIGINT, [](int) { g_running = 0; });

    auto& ctx = rxepics::default_context();

    std::cout << "Polling " << pv << " every " << interval_ms << " ms  (Ctrl+C to stop)\n\n";

    auto sub = rxcpp::observable<>::interval(std::chrono::milliseconds(interval_ms))
        .flat_map([pv, &ctx](long) { return rxepics::read_pv<double>(pv, ctx); })
        .subscribe(
            [](double v) { std::cout << "  " << v << "\n"; },
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
