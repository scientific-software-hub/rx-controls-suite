/**
 * Correlated reads — zip two PVs, show their values and difference.
 *
 * Mirrors Python's pv_correlate.py and rxtango correlate.cpp.
 *
 * Usage:
 *   EPICS_PVA_ADDR_LIST=localhost ./pv_correlate [pv1] [pv2] [interval-ms]
 *   defaults: TEST:DOUBLE TEST:CALC 500
 */

#include <chrono>
#include <csignal>
#include <iomanip>
#include <iostream>
#include <string>

#include <rxcpp/rx.hpp>
#include <rxepics/rxepics.hpp>

static volatile sig_atomic_t g_running = 1;

int main(int argc, char* argv[]) {
    const std::string pv1         = argc > 1 ? argv[1] : "TEST:DOUBLE";
    const std::string pv2         = argc > 2 ? argv[2] : "TEST:CALC";
    const int         interval_ms = argc > 3 ? std::stoi(argv[3]) : 500;

    std::signal(SIGINT, [](int) { g_running = 0; });

    auto& ctx = rxepics::default_context();

    std::cout << "Correlating " << pv1 << " vs " << pv2
              << " every " << interval_ms << " ms  (Ctrl+C to stop)\n\n"
              << std::setw(16) << pv1 << "  "
              << std::setw(16) << pv2 << "  "
              << std::setw(12) << "diff" << "\n"
              << std::string(46, '-') << "\n";

    auto sub = rxcpp::observable<>::interval(std::chrono::milliseconds(interval_ms))
        .flat_map([pv1, pv2, &ctx](long) {
            return rxcpp::observable<>::zip(
                [](double a, double b) { return std::make_pair(a, b); },
                rxepics::read_pv<double>(pv1, ctx),
                rxepics::read_pv<double>(pv2, ctx)
            );
        })
        .subscribe(
            [](std::pair<double,double> p) {
                std::cout << std::setw(16) << p.first << "  "
                          << std::setw(16) << p.second << "  "
                          << std::setw(12) << (p.first - p.second) << "\n";
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
