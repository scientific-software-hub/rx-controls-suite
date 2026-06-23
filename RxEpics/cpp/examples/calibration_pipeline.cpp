/**
 * Continuous calibration pipeline — read → calibrate → write, forever.
 *
 * Mirrors Python's calibration_pipeline.py (EPICS edition).
 * EPICS has no commands — writes are used instead.
 *
 * Usage:
 *   EPICS_PVA_ADDR_LIST=localhost ./calibration_pipeline [src_pv] [dst_pv] [interval-ms]
 *   defaults: TEST:CALC  TEST:DOUBLE  500
 */

#include <chrono>
#include <csignal>
#include <cmath>
#include <iostream>
#include <string>

#include <rxcpp/rx.hpp>
#include <rxepics/rxepics.hpp>

static volatile sig_atomic_t g_running = 1;

int main(int argc, char* argv[]) {
    const std::string src_pv      = argc > 1 ? argv[1] : "TEST:CALC";
    const std::string dst_pv      = argc > 2 ? argv[2] : "TEST:DOUBLE";
    const int         interval_ms = argc > 3 ? std::stoi(argv[3]) : 500;

    std::signal(SIGINT, [](int) { g_running = 0; });

    auto& ctx = rxepics::default_context();

    std::cout << src_pv << " → calibrate → " << dst_pv
              << "  every " << interval_ms << " ms  (Ctrl+C to stop)\n\n";

    auto sub = rxcpp::observable<>::interval(std::chrono::milliseconds(interval_ms))
        .flat_map([src_pv, &ctx](long) {
            return rxepics::read_pv<double>(src_pv, ctx);
        })
        .map([](double v) { return std::abs(v) * 2.0 + 1.5; })
        .flat_map([dst_pv, &ctx](double calibrated) {
            return rxepics::write_pv<double>(dst_pv, calibrated, ctx);
        })
        .subscribe(
            [](double written) { std::cout << "  wrote: " << written << "\n"; },
            [](std::exception_ptr e) {
                try { std::rethrow_exception(e); }
                catch (std::exception& ex) { std::cerr << "  ERROR: " << ex.what() << "\n"; }
            }
        );

    while (g_running) std::this_thread::sleep_for(std::chrono::milliseconds(100));
    sub.unsubscribe();
    return 0;
}
