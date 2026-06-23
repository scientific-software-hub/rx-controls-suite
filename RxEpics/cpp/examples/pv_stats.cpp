/**
 * Collect N samples from a PV and print batch statistics, then exit.
 *
 * Mirrors Python's pv_stats.py.
 *
 * Usage:
 *   EPICS_PVA_ADDR_LIST=localhost ./pv_stats [pv] [N] [interval-ms]
 *   defaults: TEST:CALC  20  200
 */

#include <algorithm>
#include <chrono>
#include <condition_variable>
#include <cmath>
#include <iostream>
#include <mutex>
#include <numeric>
#include <string>
#include <vector>

#include <rxcpp/rx.hpp>
#include <rxepics/rxepics.hpp>

int main(int argc, char* argv[]) {
    const std::string pv          = argc > 1 ? argv[1] : "TEST:CALC";
    const int         N           = argc > 2 ? std::stoi(argv[2]) : 20;
    const int         interval_ms = argc > 3 ? std::stoi(argv[3]) : 200;

    std::cout << "Collecting " << N << " samples of " << pv << " ...\n\n";

    auto& ctx = rxepics::default_context();

    std::mutex              m;
    std::condition_variable cv;
    bool                    done = false;

    rxcpp::observable<>::interval(std::chrono::milliseconds(interval_ms))
        .flat_map([pv, &ctx](long) { return rxepics::read_pv<double>(pv, ctx); })
        .take(N)
        .to_vector()
        .subscribe(
            [N](std::vector<double> samples) {
                double sum  = std::accumulate(samples.begin(), samples.end(), 0.0);
                double mean = sum / N;
                double var  = 0.0;
                for (double x : samples) var += (x - mean) * (x - mean);
                var /= (N - 1);

                std::cout << "  N      = " << N << "\n"
                          << "  min    = " << *std::min_element(samples.begin(), samples.end()) << "\n"
                          << "  max    = " << *std::max_element(samples.begin(), samples.end()) << "\n"
                          << "  mean   = " << mean << "\n"
                          << "  stddev = " << std::sqrt(var) << "\n";
            },
            [&](std::exception_ptr e) {
                try { std::rethrow_exception(e); }
                catch (std::exception& ex) { std::cerr << "  ERROR: " << ex.what() << "\n"; }
                std::lock_guard<std::mutex> lk(m); done = true; cv.notify_one();
            },
            [&]() { std::lock_guard<std::mutex> lk(m); done = true; cv.notify_one(); }
        );

    std::unique_lock<std::mutex> lk(m);
    cv.wait(lk, [&]{ return done; });
    return 0;
}
