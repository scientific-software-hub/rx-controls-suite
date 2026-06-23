/**
 * Alarm fan-in — watch N devices, fire when any exceeds a threshold.
 *
 * One poll stream per device; merge() fans them into a single alarm stream;
 * on_error_resume_next() isolates per-device failures.
 *
 * Mirrors Python's alarm_monitor.py and Java's AlarmMonitor.java.
 *
 * Usage:
 *   ./alarm_monitor [threshold] [interval-ms] [device1] [device2] ...
 *   defaults: threshold=0.5  interval=500  (two reads from sys/tg_test/1)
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
    const double threshold   = argc > 1 ? std::stod(argv[1]) : 0.5;
    const int    interval_ms = argc > 2 ? std::stoi(argv[2]) : 500;

    std::vector<std::string> devices;
    for (int i = 3; i < argc; ++i) devices.emplace_back(argv[i]);
    if (devices.empty())
        devices = { "tango://localhost:10000/sys/tg_test/1",
                    "tango://localhost:10000/sys/tg_test/1" };

    std::signal(SIGINT, [](int) { g_running = 0; });

    std::cout << "Alarm monitor — threshold = " << threshold << "  (Ctrl+C to stop)\n\n";

    // Build one poll stream per device, merge all into one alarm stream
    std::vector<rxcpp::observable<std::pair<std::string,double>>> streams;
    for (auto& dev : devices) {
        streams.push_back(
            rxcpp::observable<>::interval(std::chrono::milliseconds(interval_ms))
                .flat_map([dev](long) {
                    return rxtango::read_attribute<double>(dev, "double_scalar")
                        .map([dev](double v) { return std::make_pair(dev, v); })
                        .on_error_resume_next([dev](std::exception_ptr) {
                            // isolate per-device failure; return sentinel pair
                            return rxcpp::observable<>::just(
                                std::make_pair(dev, std::numeric_limits<double>::quiet_NaN()));
                        });
                })
        );
    }

    // Merge all streams and filter for alarms
    rxcpp::observable<>::iterate(streams)
        .flat_map([](rxcpp::observable<std::pair<std::string,double>> s) { return s; })
        .filter([threshold](std::pair<std::string,double> p) {
            return !std::isnan(p.second) && std::abs(p.second) > threshold;
        })
        .subscribe(
            [](std::pair<std::string,double> p) {
                std::cout << "  ALARM  " << p.first << " = " << p.second << "\n";
            },
            [](std::exception_ptr e) {
                try { std::rethrow_exception(e); }
                catch (std::exception& ex) { std::cerr << "  ERROR: " << ex.what() << "\n"; }
            }
        );

    while (g_running) std::this_thread::sleep_for(std::chrono::milliseconds(100));
    return 0;
}
