/**
 * Rate control — poll fast, display slow.
 *
 * Reads at high rate but throttles display to a lower rate using sample().
 * Mirrors Python's throttle.py and Java's TangoTestThrottle.java.
 *
 * Usage:
 *   ./throttle [device] [attribute] [poll-ms] [display-ms]
 *   defaults: sys/tg_test/1  double_scalar  100  1000
 */

#include <chrono>
#include <csignal>
#include <iostream>
#include <string>

#include <rxcpp/rx.hpp>
#include <rxtango/rxtango.hpp>

static volatile sig_atomic_t g_running = 1;

int main(int argc, char* argv[]) {
    const std::string device     = argc > 1 ? argv[1] : "tango://localhost:10000/sys/tg_test/1";
    const std::string attr       = argc > 2 ? argv[2] : "double_scalar";
    const int         poll_ms    = argc > 3 ? std::stoi(argv[3]) : 100;
    const int         display_ms = argc > 4 ? std::stoi(argv[4]) : 1000;

    std::signal(SIGINT, [](int) { g_running = 0; });

    std::cout << "Throttle: polling every " << poll_ms << " ms, displaying every "
              << display_ms << " ms  (Ctrl+C to stop)\n\n";

    // Fast poll → throttle via sample() to display rate
    auto sub = rxcpp::observable<>::interval(std::chrono::milliseconds(poll_ms))
        .flat_map([device, attr](long) {
            return rxtango::read_attribute<double>(device, attr);
        })
        .sample_with_time(std::chrono::milliseconds(display_ms))
        .subscribe(
            [](double v) { std::cout << "  displayed: " << v << "\n"; },
            [](std::exception_ptr e) {
                try { std::rethrow_exception(e); }
                catch (std::exception& ex) { std::cerr << "  ERROR: " << ex.what() << "\n"; }
            }
        );

    while (g_running) std::this_thread::sleep_for(std::chrono::milliseconds(100));
    sub.unsubscribe();
    return 0;
}
