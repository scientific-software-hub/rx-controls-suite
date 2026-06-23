/**
 * Sliding (rolling) average over a monitored PV stream.
 *
 * Mirrors Python's pv_sliding_average.py.
 *
 * Usage:
 *   EPICS_PVA_ADDR_LIST=localhost ./pv_sliding_average [pv] [window-size]
 *   defaults: TEST:CALC  5
 */

#include <csignal>
#include <iostream>
#include <numeric>
#include <string>
#include <vector>

#include <rxcpp/rx.hpp>
#include <rxepics/rxepics.hpp>

static volatile sig_atomic_t g_running = 1;

int main(int argc, char* argv[]) {
    const std::string pv          = argc > 1 ? argv[1] : "TEST:CALC";
    const int         window_size = argc > 2 ? std::stoi(argv[2]) : 5;

    std::signal(SIGINT, [](int) { g_running = 0; });

    auto& ctx = rxepics::default_context();

    std::cout << "Sliding average (window=" << window_size << ") of " << pv << "  (Ctrl+C to stop)\n\n";

    auto sub = rxepics::monitor_pv<double>(pv, ctx)
        .buffer(window_size, 1)
        .filter([window_size](const std::vector<double>& w) {
            return static_cast<int>(w.size()) == window_size;
        })
        .map([](const std::vector<double>& w) {
            return std::accumulate(w.begin(), w.end(), 0.0) / w.size();
        })
        .subscribe(
            [](double avg) { std::cout << "  avg: " << avg << "\n"; },
            [](std::exception_ptr e) {
                try { std::rethrow_exception(e); }
                catch (std::exception& ex) { std::cerr << "  ERROR: " << ex.what() << "\n"; }
            }
        );

    while (g_running) std::this_thread::sleep_for(std::chrono::milliseconds(100));
    sub.unsubscribe();
    return 0;
}
