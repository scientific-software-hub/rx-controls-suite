/**
 * Window-synchronized zip — two streams read in fixed windows, then zipped pairwise.
 *
 * Buffers N samples from each stream, then zips the two buffers.  Useful for
 * comparing frequency-domain snapshots or batch statistics across two devices.
 *
 * Mirrors Python's zip_window.py and Java's TangoTestZipWindow.java.
 *
 * Usage:
 *   ./zip_window [device] [attr1] [attr2] [window] [interval-ms]
 *   defaults: sys/tg_test/1  double_scalar  double_scalar  5  100
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
    const std::string attr1       = argc > 2 ? argv[2] : "double_scalar";
    const std::string attr2       = argc > 3 ? argv[3] : "double_scalar";
    const int         window_size = argc > 4 ? std::stoi(argv[4]) : 5;
    const int         interval_ms = argc > 5 ? std::stoi(argv[5]) : 100;

    std::signal(SIGINT, [](int) { g_running = 0; });

    std::cout << "Window-zip: window=" << window_size
              << "  " << attr1 << " × " << attr2 << "  (Ctrl+C to stop)\n\n";

    // Buffer N from each stream, zip the buffer pairs, compute means
    auto stream1 = rxcpp::observable<>::interval(std::chrono::milliseconds(interval_ms))
        .flat_map([device, attr1](long) {
            return rxtango::read_attribute<double>(device, attr1);
        })
        .buffer(window_size);

    auto stream2 = rxcpp::observable<>::interval(std::chrono::milliseconds(interval_ms))
        .flat_map([device, attr2](long) {
            return rxtango::read_attribute<double>(device, attr2);
        })
        .buffer(window_size);

    auto sub = rxcpp::observable<>::zip(
        [](const std::vector<double>& a, const std::vector<double>& b) {
            double mean_a = std::accumulate(a.begin(), a.end(), 0.0) / a.size();
            double mean_b = std::accumulate(b.begin(), b.end(), 0.0) / b.size();
            return std::make_pair(mean_a, mean_b);
        },
        stream1, stream2
    ).subscribe(
        [](std::pair<double,double> p) {
            std::cout << "  mean1=" << p.first << "  mean2=" << p.second
                      << "  diff=" << (p.first - p.second) << "\n";
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
