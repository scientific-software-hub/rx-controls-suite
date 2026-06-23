/**
 * Atomic correlated reads — zip two attributes from the same device.
 *
 * Every tick fires two reads in parallel; the pair is only processed when
 * BOTH arrive.  If either fails the pair is dropped — no half-processed data.
 *
 * Mirrors Python's zip_attributes.py and Java's ZipAttributes.java / TangoTestCorrelate.java.
 *
 * Usage:
 *   ./zip_attributes [device] [attr1] [attr2] [interval-ms]
 *   defaults: sys/tg_test/1  double_scalar  double_scalar  500
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
    const std::string device      = argc > 1 ? argv[1] : "tango://localhost:10000/sys/tg_test/1";
    const std::string attr1       = argc > 2 ? argv[2] : "double_scalar";
    const std::string attr2       = argc > 3 ? argv[3] : "double_scalar";
    const int         interval_ms = argc > 4 ? std::stoi(argv[4]) : 500;

    std::signal(SIGINT, [](int) { g_running = 0; });

    std::cout << "Correlated reads: " << attr1 << " × " << attr2
              << " every " << interval_ms << " ms  (Ctrl+C to stop)\n\n"
              << std::setw(20) << attr1 << "  " << std::setw(20) << attr2 << "\n"
              << std::string(44, '-') << "\n";

    // Mirrors Java: Flowable.interval().flatMapSingle(tick -> Single.zip(readA, readB, combiner))
    auto sub = rxcpp::observable<>::interval(std::chrono::milliseconds(interval_ms))
        .flat_map([device, attr1, attr2](long) {
            // zip two concurrent reads — pair only produced when BOTH complete
            return rxcpp::observable<>::zip(
                [](double a, double b) { return std::make_pair(a, b); },
                rxtango::read_attribute<double>(device, attr1),
                rxtango::read_attribute<double>(device, attr2)
            );
        })
        .subscribe(
            [](std::pair<double,double> p) {
                std::cout << std::setw(20) << p.first
                          << "  " << std::setw(20) << p.second << "\n";
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
