/**
 * Collect N samples, compute batch statistics, then exit.
 *
 * Mirrors Python's stats.py and Java's TangoTestStats.java.
 *
 * Usage:
 *   ./stats [device] [attribute] [N] [interval-ms]
 *   defaults: sys/tg_test/1  double_scalar  20  200
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
#include <rxtango/rxtango.hpp>

int main(int argc, char* argv[]) {
    const std::string device      = argc > 1 ? argv[1] : "tango://localhost:10000/sys/tg_test/1";
    const std::string attr        = argc > 2 ? argv[2] : "double_scalar";
    const int         N           = argc > 3 ? std::stoi(argv[3]) : 20;
    const int         interval_ms = argc > 4 ? std::stoi(argv[4]) : 200;

    std::cout << "Collecting " << N << " samples of " << device << "/" << attr << " ...\n\n";

    std::mutex              m;
    std::condition_variable cv;
    bool                    done = false;

    rxcpp::observable<>::interval(std::chrono::milliseconds(interval_ms))
        .flat_map([device, attr](long) {
            return rxtango::read_attribute<double>(device, attr);
        })
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
