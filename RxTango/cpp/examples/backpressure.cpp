/**
 * Backpressure strategies — fast producer, slow consumer.
 *
 * Demonstrates three strategies for handling a faster producer than consumer:
 *   latest  — sample_with_time: keep only the freshest value in each window
 *   drop    — skip values while consumer is busy (debounce)
 *   buffer  — accumulate into a vector (beware memory growth)
 *
 * Note: RxCpp observables are not reactive-streams Publishers (no request(n)
 * demand protocol).  Backpressure here means rate-limiting the display, not
 * flow-controlling the source — the same honest documentation as the Python version.
 *
 * Mirrors Python's backpressure.py and Java's TangoTestBackpressure.java.
 *
 * Usage:
 *   ./backpressure [strategy: latest|drop|buffer] [device] [attr] [poll-ms] [display-ms]
 *   defaults: latest  sys/tg_test/1  double_scalar  50  500
 */

#include <chrono>
#include <csignal>
#include <iostream>
#include <string>
#include <vector>

#include <rxcpp/rx.hpp>
#include <rxtango/rxtango.hpp>

static volatile sig_atomic_t g_running = 1;

int main(int argc, char* argv[]) {
    const std::string strategy   = argc > 1 ? argv[1] : "latest";
    const std::string device     = argc > 2 ? argv[2] : "tango://localhost:10000/sys/tg_test/1";
    const std::string attr       = argc > 3 ? argv[3] : "double_scalar";
    const int         poll_ms    = argc > 4 ? std::stoi(argv[4]) : 50;
    const int         display_ms = argc > 5 ? std::stoi(argv[5]) : 500;

    std::signal(SIGINT, [](int) { g_running = 0; });

    std::cout << "Backpressure strategy: " << strategy
              << "  poll=" << poll_ms << "ms  display=" << display_ms << "ms  (Ctrl+C to stop)\n\n";

    auto source = rxcpp::observable<>::interval(std::chrono::milliseconds(poll_ms))
        .flat_map([device, attr](long) {
            return rxtango::read_attribute<double>(device, attr);
        });

    if (strategy == "latest") {
        // Keep only the latest value per display window
        source.sample_with_time(std::chrono::milliseconds(display_ms))
              .subscribe(
                  [](double v) { std::cout << "  [latest] " << v << "\n"; },
                  [](std::exception_ptr e) {
                      try { std::rethrow_exception(e); }
                      catch (std::exception& ex) { std::cerr << "  ERROR: " << ex.what() << "\n"; }
                  }
              );
    } else if (strategy == "buffer") {
        // Accumulate all values in the window — prints a vector
        source.buffer_with_time(std::chrono::milliseconds(display_ms))
              .subscribe(
                  [](const std::vector<double>& v) {
                      std::cout << "  [buffer] " << v.size() << " values, latest=" << v.back() << "\n";
                  },
                  [](std::exception_ptr e) {
                      try { std::rethrow_exception(e); }
                      catch (std::exception& ex) { std::cerr << "  ERROR: " << ex.what() << "\n"; }
                  }
              );
    } else {
        // drop: debounce — only fires if nothing arrived for display_ms
        source.debounce(std::chrono::milliseconds(display_ms))
              .subscribe(
                  [](double v) { std::cout << "  [drop] " << v << "\n"; },
                  [](std::exception_ptr e) {
                      try { std::rethrow_exception(e); }
                      catch (std::exception& ex) { std::cerr << "  ERROR: " << ex.what() << "\n"; }
                  }
              );
    }

    while (g_running) std::this_thread::sleep_for(std::chrono::milliseconds(100));
    return 0;
}
