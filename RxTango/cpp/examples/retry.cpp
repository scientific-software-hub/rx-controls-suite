/**
 * Retry patterns — how to handle transient failures in a polling pipeline.
 *
 * Three patterns:
 *   fixed   — retry(N) on the inner read; whole pipeline retries N times
 *   backoff — exponential backoff via zip+delay (sketch)
 *   inner   — retry inside flat_map; outer pipeline never sees the error
 *
 * Mirrors Python's retry.py and Java's TangoTestRetry.java.
 *
 * Usage:
 *   ./retry [strategy: fixed|inner] [device] [attr] [retries] [interval-ms]
 *   defaults: inner  sys/tg_test/1  double_scalar  3  500
 */

#include <chrono>
#include <csignal>
#include <iostream>
#include <string>

#include <rxcpp/rx.hpp>
#include <rxtango/rxtango.hpp>

static volatile sig_atomic_t g_running = 1;

int main(int argc, char* argv[]) {
    const std::string strategy   = argc > 1 ? argv[1] : "inner";
    const std::string device     = argc > 2 ? argv[2] : "tango://localhost:10000/sys/tg_test/1";
    const std::string attr       = argc > 3 ? argv[3] : "double_scalar";
    const int         retries    = argc > 4 ? std::stoi(argv[4]) : 3;
    const int         interval_ms= argc > 5 ? std::stoi(argv[5]) : 500;

    std::signal(SIGINT, [](int) { g_running = 0; });

    std::cout << "Retry strategy: " << strategy
              << "  retries=" << retries << "  (Ctrl+C to stop)\n\n";

    if (strategy == "fixed") {
        // retry(N) on the outer polling chain
        rxcpp::observable<>::interval(std::chrono::milliseconds(interval_ms))
            .flat_map([device, attr](long) {
                return rxtango::read_attribute<double>(device, attr);
            })
            .retry(retries)
            .subscribe(
                [](double v) { std::cout << "  value: " << v << "\n"; },
                [](std::exception_ptr e) {
                    try { std::rethrow_exception(e); }
                    catch (std::exception& ex) {
                        std::cerr << "  FINAL ERROR after retries: " << ex.what() << "\n";
                    }
                }
            );
    } else {
        // inner retry — each read retries independently; outer pipeline sees only successes
        rxcpp::observable<>::interval(std::chrono::milliseconds(interval_ms))
            .flat_map([device, attr, retries](long) {
                return rxtango::read_attribute<double>(device, attr)
                    .retry(retries)
                    .on_error_resume_next([](std::exception_ptr) {
                        // exhausted retries → emit NaN so the pipeline continues
                        return rxcpp::observable<>::just(
                            std::numeric_limits<double>::quiet_NaN());
                    });
            })
            .filter([](double v) { return !std::isnan(v); })
            .subscribe(
                [](double v) { std::cout << "  value: " << v << "\n"; },
                [](std::exception_ptr e) {
                    try { std::rethrow_exception(e); }
                    catch (std::exception& ex) { std::cerr << "  ERROR: " << ex.what() << "\n"; }
                }
            );
    }

    while (g_running) std::this_thread::sleep_for(std::chrono::milliseconds(100));
    return 0;
}
