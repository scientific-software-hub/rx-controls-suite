/**
 * Correlated reads — two devices, same polling window; shows diff.
 *
 * Mirrors Python's correlate.py and Java's TangoTestCorrelate.java.
 *
 * Usage:
 *   ./correlate [device1] [attr1] [device2] [attr2] [interval-ms]
 *   defaults: sys/tg_test/1  double_scalar  sys/tg_test/1  double_scalar  500
 */

#include <chrono>
#include <csignal>
#include <iomanip>
#include <iostream>
#include <string>

#include <rxcpp/rx.hpp>
#include <rxtango/rxtango.hpp>

static volatile sig_atomic_t g_running = 1;

int main(int argc, char* argv[]) {
    const std::string dev1  = argc > 1 ? argv[1] : "tango://localhost:10000/sys/tg_test/1";
    const std::string attr1 = argc > 2 ? argv[2] : "double_scalar";
    const std::string dev2  = argc > 3 ? argv[3] : "tango://localhost:10000/sys/tg_test/1";
    const std::string attr2 = argc > 4 ? argv[4] : "double_scalar";
    const int interval_ms   = argc > 5 ? std::stoi(argv[5]) : 500;

    std::signal(SIGINT, [](int) { g_running = 0; });

    std::cout << "Correlating " << dev1 << "/" << attr1
              << " vs " << dev2 << "/" << attr2 << "\n\n"
              << std::setw(16) << attr1 << "  "
              << std::setw(16) << attr2 << "  "
              << std::setw(12) << "diff" << "\n"
              << std::string(48, '-') << "\n";

    auto sub = rxcpp::observable<>::interval(std::chrono::milliseconds(interval_ms))
        .flat_map([dev1, attr1, dev2, attr2](long) {
            return rxcpp::observable<>::zip(
                [](double a, double b) { return std::make_pair(a, b); },
                rxtango::read_attribute<double>(dev1, attr1),
                rxtango::read_attribute<double>(dev2, attr2)
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
