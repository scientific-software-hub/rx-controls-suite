/**
 * Alarm fan-in — watch N PVs via monitors, fire when any exceeds a threshold.
 *
 * Mirrors Python's alarm_monitor.py (EPICS edition).
 *
 * Usage:
 *   EPICS_PVA_ADDR_LIST=localhost ./alarm_monitor [threshold] [pv1] [pv2] ...
 *   defaults: threshold=100  TEST:CALC  TEST:CALC
 */

#include <cmath>
#include <csignal>
#include <iostream>
#include <string>
#include <vector>

#include <rxcpp/rx.hpp>
#include <rxepics/rxepics.hpp>

static volatile sig_atomic_t g_running = 1;

int main(int argc, char* argv[]) {
    const double threshold = argc > 1 ? std::stod(argv[1]) : 100.0;

    std::vector<std::string> pvs;
    for (int i = 2; i < argc; ++i) pvs.emplace_back(argv[i]);
    if (pvs.empty()) pvs = {"TEST:CALC", "TEST:CALC"};

    std::signal(SIGINT, [](int) { g_running = 0; });

    auto& ctx = rxepics::default_context();

    std::cout << "Alarm fan-in: threshold=" << threshold << "  (Ctrl+C to stop)\n\n";

    std::vector<rxcpp::observable<std::pair<std::string,double>>> streams;
    for (auto& pv : pvs) {
        streams.push_back(
            rxepics::monitor_pv<double>(pv, ctx)
                .map([pv](double v) { return std::make_pair(pv, v); })
        );
    }

    rxcpp::observable<>::iterate(streams)
        .flat_map([](rxcpp::observable<std::pair<std::string,double>> s) { return s; })
        .filter([threshold](std::pair<std::string,double> p) {
            return std::abs(p.second) > threshold;
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
