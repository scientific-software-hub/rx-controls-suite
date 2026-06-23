/**
 * TangoClient fluent builder showcase — all builder features in one example.
 *
 * Demonstrates: read → map (calibrate) → write → execute → map → subscribe.
 *
 * Mirrors Python's fluent_client.py and Java's FluentClient.java.
 *
 * Usage:
 *   ./fluent_client [device]
 *   defaults: tango://localhost:10000/sys/tg_test/1
 */

#include <any>
#include <condition_variable>
#include <cmath>
#include <iostream>
#include <mutex>
#include <string>

#include <rxtango/rxtango.hpp>

int main(int argc, char* argv[]) {
    const std::string device = argc > 1 ? argv[1] : "tango://localhost:10000/sys/tg_test/1";

    std::cout << "TangoClient showcase on " << device << "\n\n";

    std::mutex              m;
    std::condition_variable cv;
    bool                    done = false;

    rxtango::TangoClient()
        .read(device, "double_scalar")                // 1. read
        .map([](std::any v) -> std::any {             // 2. pure calibration transform
            double d = std::any_cast<double>(v);
            std::cout << "  read: " << d << "\n";
            return std::abs(d) * 2.0 + 1.5;
        })
        .write(device, "double_scalar_w")             // 3. write (passes written value through)
        .map([](std::any v) -> std::any {
            std::cout << "  wrote: " << std::any_cast<double>(v) << "\n";
            return v;
        })
        .execute(device, "DevDouble",                 // 4. command with value from previous step
            [](double prev) { return prev; })
        .map([](std::any v) -> std::any {
            std::cout << "  DevDouble result: " << std::any_cast<double>(v) << "\n";
            return v;
        })
        .subscribe(
            [](std::any v) {
                std::cout << "  final: " << std::any_cast<double>(v) << "\n";
            },
            [&](std::exception_ptr e) {
                try { std::rethrow_exception(e); }
                catch (std::exception& ex) { std::cerr << "  ERROR: " << ex.what() << "\n"; }
                std::lock_guard<std::mutex> lk(m); done = true; cv.notify_one();
            },
            [&]() {
                std::cout << "  Done.\n";
                std::lock_guard<std::mutex> lk(m); done = true; cv.notify_one();
            }
        );

    std::unique_lock<std::mutex> lk(m);
    cv.wait_for(lk, std::chrono::seconds(10), [&]{ return done; });
    return 0;
}
