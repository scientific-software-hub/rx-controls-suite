/**
 * Poll a Tango attribute at a fixed interval — no loop, no thread.
 *
 * Mirrors the Java pattern:
 *   Flowable.interval(ms).flatMapSingle(read_attribute)
 *
 * Mirrors Python's poll_attribute.py and Java's PollAttribute.java.
 *
 * Usage:
 *   ./poll_attribute [device] [attribute] [interval-ms]
 *   defaults: sys/tg_test/1  double_scalar  500
 */

#include <chrono>
#include <csignal>
#include <iostream>
#include <string>

#include <rxcpp/rx.hpp>
#include <rxtango/rxtango.hpp>

static volatile sig_atomic_t g_running = 1;

int main(int argc, char* argv[]) {
    const std::string device      = argc > 1 ? argv[1] : "tango://localhost:10000/sys/tg_test/1";
    const std::string attr        = argc > 2 ? argv[2] : "double_scalar";
    const int         interval_ms = argc > 3 ? std::stoi(argv[3]) : 500;

    std::signal(SIGINT, [](int) { g_running = 0; });

    std::cout << "Polling " << device << "/" << attr
              << " every " << interval_ms << " ms  (Ctrl+C to stop)\n\n"
              << "  " << std::setw(20) << "value" << "\n"
              << "  " << std::string(22, '-') << "\n";

    // Interval on a new-thread scheduler; flat_map into single-shot reads.
    // Mirrors: Flowable.interval(ms).flatMapSingle(i -> read)
    auto sub = rxcpp::observable<>::interval(std::chrono::milliseconds(interval_ms))
        .flat_map([device, attr](long) {
            return rxtango::read_attribute<double>(device, attr);
        })
        .subscribe(
            [](double v) { std::cout << "  " << std::setw(+20) << v << "\n"; },
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
