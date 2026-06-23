/**
 * Continuous calibration pipeline — read → calibrate → write, forever.
 *
 * The same three reactive operators Java/Python use — interval · flat_map · map:
 *   interval  →  read double_scalar
 *              →  calibrate (abs(v) * 2.0 + 1.5)
 *              →  write double_scalar_w
 *
 * Mirrors Python's calibration_pipeline.py and Java's CalibrationPipeline.java.
 *
 * Usage:
 *   ./calibration_pipeline [device] [interval-ms]
 *   defaults: sys/tg_test/1  500
 */

#include <chrono>
#include <csignal>
#include <cmath>
#include <iostream>
#include <string>

#include <rxcpp/rx.hpp>
#include <rxtango/rxtango.hpp>

static volatile sig_atomic_t g_running = 1;

int main(int argc, char* argv[]) {
    const std::string device      = argc > 1 ? argv[1] : "tango://localhost:10000/sys/tg_test/1";
    const int         interval_ms = argc > 2 ? std::stoi(argv[2]) : 500;

    std::signal(SIGINT, [](int) { g_running = 0; });

    std::cout << "Calibration pipeline on " << device
              << "  every " << interval_ms << " ms  (Ctrl+C to stop)\n\n";

    auto sub = rxcpp::observable<>::interval(std::chrono::milliseconds(interval_ms))
        .flat_map([device](long) {
            return rxtango::read_attribute<double>(device, "double_scalar");
        })
        .map([](double v) { return std::abs(v) * 2.0 + 1.5; })
        .flat_map([device](double calibrated) {
            return rxtango::write_attribute<double>(device, "double_scalar_w", calibrated);
        })
        .subscribe(
            [](double written) {
                std::cout << "  wrote: " << written << "\n";
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
