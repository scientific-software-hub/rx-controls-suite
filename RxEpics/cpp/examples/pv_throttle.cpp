/**
 * Rate control — monitor fast, display slow via sample.
 *
 * Mirrors Python's pv_throttle.py.
 *
 * Usage:
 *   EPICS_PVA_ADDR_LIST=localhost ./pv_throttle [pv] [display-ms]
 *   defaults: TEST:CALC  1000
 */

#include <chrono>
#include <csignal>
#include <iostream>
#include <string>

#include <rxcpp/rx.hpp>
#include <rxepics/rxepics.hpp>

static volatile sig_atomic_t g_running = 1;

int main(int argc, char* argv[]) {
    const std::string pv         = argc > 1 ? argv[1] : "TEST:CALC";
    const int         display_ms = argc > 2 ? std::stoi(argv[2]) : 1000;

    std::signal(SIGINT, [](int) { g_running = 0; });

    auto& ctx = rxepics::default_context();

    std::cout << "Throttle " << pv << " → display every " << display_ms << " ms  (Ctrl+C to stop)\n\n";

    auto sub = rxepics::monitor_pv<double>(pv, ctx)
        .sample_with_time(std::chrono::milliseconds(display_ms))
        .subscribe(
            [](double v) { std::cout << "  displayed: " << v << "\n"; },
            [](std::exception_ptr e) {
                try { std::rethrow_exception(e); }
                catch (std::exception& ex) { std::cerr << "  ERROR: " << ex.what() << "\n"; }
            }
        );

    while (g_running) std::this_thread::sleep_for(std::chrono::milliseconds(100));
    sub.unsubscribe();
    return 0;
}
