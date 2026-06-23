/**
 * Live O(1) running statistics using Welford's online algorithm via scan().
 *
 * No buffer needed — scan() accumulates (count, mean, M2) in constant space.
 * On each new value: count++, update mean and variance.
 *
 * Mirrors Python's running_stats.py and Java's TangoTestRunningStats.java.
 *
 * Usage:
 *   ./running_stats [device] [attribute] [interval-ms]
 *   defaults: sys/tg_test/1  double_scalar  200
 */

#include <chrono>
#include <csignal>
#include <cmath>
#include <iostream>
#include <string>
#include <tuple>

#include <rxcpp/rx.hpp>
#include <rxtango/rxtango.hpp>

static volatile sig_atomic_t g_running = 1;

// Welford accumulator: (count, mean, M2)
using Stats = std::tuple<int, double, double>;

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
    const std::string device      = argc > 1 ? argv[1] : "tango://localhost:10000/sys/tg_test/1";
    const std::string attr        = argc > 2 ? argv[2] : "double_scalar";
    const int         interval_ms = argc > 3 ? std::stoi(argv[3]) : 200;

    std::signal(SIGINT, [](int) { g_running = 0; });

    std::cout << "Running stats for " << device << "/" << attr << "  (Ctrl+C to stop)\n\n"
              << std::setw(8) << "N" << std::setw(14) << "mean"
              << std::setw(14) << "stddev" << "\n"
              << std::string(38, '-') << "\n";

    auto sub = rxcpp::observable<>::interval(std::chrono::milliseconds(interval_ms))
        .flat_map([device, attr](long) {
            return rxtango::read_attribute<double>(device, attr);
        })
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
