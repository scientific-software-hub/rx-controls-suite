/**
 * Backpressure strategies for a fast-updating PV.
 *
 * Mirrors Python's pv_backpressure.py.
 * Strategies: latest (sample), buffer, drop (debounce).
 *
 * Usage:
 *   EPICS_PVA_ADDR_LIST=localhost ./pv_backpressure [strategy] [pv] [display-ms]
 *   defaults: latest  TEST:CALC  1000
 */

#include <chrono>
#include <csignal>
#include <iostream>
#include <string>
#include <vector>

#include <rxcpp/rx.hpp>
#include <rxepics/rxepics.hpp>

static volatile sig_atomic_t g_running = 1;

int main(int argc, char* argv[]) {
    const std::string strategy   = argc > 1 ? argv[1] : "latest";
    const std::string pv         = argc > 2 ? argv[2] : "TEST:CALC";
    const int         display_ms = argc > 3 ? std::stoi(argv[3]) : 1000;

    std::signal(SIGINT, [](int) { g_running = 0; });

    auto& ctx = rxepics::default_context();

    std::cout << "Backpressure [" << strategy << "] on " << pv
              << "  display=" << display_ms << "ms  (Ctrl+C to stop)\n\n";

    auto source = rxepics::monitor_pv<double>(pv, ctx);

    if (strategy == "buffer") {
        source.buffer_with_time(std::chrono::milliseconds(display_ms))
              .subscribe(
                  [](const std::vector<double>& v) {
                      if (!v.empty())
                          std::cout << "  [buffer] " << v.size() << " updates, last=" << v.back() << "\n";
                  },
                  [](std::exception_ptr e) {
                      try { std::rethrow_exception(e); }
                      catch (std::exception& ex) { std::cerr << "  ERROR: " << ex.what() << "\n"; }
                  }
              );
    } else if (strategy == "drop") {
        source.debounce(std::chrono::milliseconds(display_ms))
              .subscribe(
                  [](double v) { std::cout << "  [drop] " << v << "\n"; },
                  [](std::exception_ptr e) {
                      try { std::rethrow_exception(e); }
                      catch (std::exception& ex) { std::cerr << "  ERROR: " << ex.what() << "\n"; }
                  }
              );
    } else {
        source.sample_with_time(std::chrono::milliseconds(display_ms))
              .subscribe(
                  [](double v) { std::cout << "  [latest] " << v << "\n"; },
                  [](std::exception_ptr e) {
                      try { std::rethrow_exception(e); }
                      catch (std::exception& ex) { std::cerr << "  ERROR: " << ex.what() << "\n"; }
                  }
              );
    }

    while (g_running) std::this_thread::sleep_for(std::chrono::milliseconds(100));
    return 0;
}
