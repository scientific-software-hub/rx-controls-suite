/**
 * Sliding (rolling) average using buffer_with_time / window operator.
 *
 * Uses rxcpp's buffer(N, skip=1) to create overlapping windows, then maps
 * each window to its mean.  Identical to the Python sliding-window pattern:
 *   ops.buffer_with_count(N, 1) → ops.map(mean)
 *
 * Mirrors Python's sliding_average.py and Java's TangoTestSlidingAverage.java.
 *
 * Usage:
 *   ./sliding_average [device] [attribute] [window-size] [interval-ms]
 *   defaults: sys/tg_test/1  double_scalar  5  200
 */

#include <chrono>
#include <csignal>
#include <iostream>
#include <numeric>
#include <string>
#include <vector>

#include <rxcpp/rx.hpp>
#include <rxtango/rxtango.hpp>

static volatile sig_atomic_t g_running = 1;

int main(int argc, char* argv[]) {
    const std::string device      = argc > 1 ? argv[1] : "tango://localhost:10000/sys/tg_test/1";
    const std::string attr        = argc > 2 ? argv[2] : "double_scalar";
    const int         window_size = argc > 3 ? std::stoi(argv[3]) : 5;
    const int         interval_ms = argc > 4 ? std::stoi(argv[4]) : 200;

    std::signal(SIGINT, [](int) { g_running = 0; });

    std::cout << "Sliding average (window=" << window_size << ") of "
              << device << "/" << attr << "  (Ctrl+C to stop)\n\n";

    auto sub = rxcpp::observable<>::interval(std::chrono::milliseconds(interval_ms))
        .flat_map([device, attr](long) {
            return rxtango::read_attribute<double>(device, attr);
        })
        // Overlapping windows of size N, advancing by 1 each step
        .buffer(window_size, 1)
        // Skip partial leading windows (size < window_size)
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
