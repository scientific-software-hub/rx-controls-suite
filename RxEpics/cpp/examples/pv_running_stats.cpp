/**
 * Live O(1) running statistics (Welford's algorithm) via scan().
 *
 * Mirrors Python's pv_running_stats.py.
 *
 * Usage:
 *   EPICS_PVA_ADDR_LIST=localhost ./pv_running_stats [pv]
 *   defaults: TEST:CALC
 */

#include <cmath>
#include <csignal>
#include <iomanip>
#include <iostream>
#include <string>
#include <tuple>

#include <rxcpp/rx.hpp>
#include <rxepics/rxepics.hpp>

static volatile sig_atomic_t g_running = 1;

using Stats = std::tuple<int, double, double>;   // (count, mean, M2)

static Stats welford_update(Stats acc, double x) {
    auto [n, mean, M2] = acc;
    ++n;
    double delta  = x - mean;
    mean         += delta / n;
    double delta2 = x - mean;
    M2           += delta * delta2;
    return {n, mean, M2};
}

int main(int argc, char* argv[]) {
    const std::string pv = argc > 1 ? argv[1] : "TEST:CALC";

    std::signal(SIGINT, [](int) { g_running = 0; });

    auto& ctx = rxepics::default_context();

    std::cout << "Running stats for " << pv << "  (Ctrl+C to stop)\n\n"
              << std::setw(8) << "N" << std::setw(14) << "mean"
              << std::setw(14) << "stddev" << "\n"
              << std::string(38, '-') << "\n";

    auto sub = rxepics::monitor_pv<double>(pv, ctx)
        .scan(Stats{0, 0.0, 0.0}, welford_update)
        .subscribe(
            [](Stats s) {
                auto [n, mean, M2] = s;
                double stddev = (n > 1) ? std::sqrt(M2 / (n - 1)) : 0.0;
                std::cout << std::setw(8) << n
                          << std::setw(14) << mean
                          << std::setw(14) << stddev << "\n";
            },
            [](std::exception_ptr e) {
                try { std::rethrow_exception(e); }
                catch (std::exception& ex) { std::cerr << "  ERROR: " << ex.what() << "\n"; }
            }
        );

    while (g_running) std::this_thread::sleep_for(std::chrono::milliseconds(100));
    sub.unsubscribe();
    return 0;
}
