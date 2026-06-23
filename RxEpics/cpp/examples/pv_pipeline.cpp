/**
 * Fluent EpicsClient pipeline — read → map → write → read back.
 *
 * The showstopper demo for RxEpics/cpp.
 * Mirrors Python's pv_pipeline.py and rxtango pipeline.cpp.
 *
 * Usage:
 *   EPICS_PVA_ADDR_LIST=localhost ./pv_pipeline [src_pv] [dst_pv]
 *   defaults: TEST:CALC  TEST:DOUBLE
 */

#include <any>
#include <cmath>
#include <condition_variable>
#include <iostream>
#include <mutex>
#include <string>

#include <rxepics/rxepics.hpp>

int main(int argc, char* argv[]) {
    const std::string src_pv = argc > 1 ? argv[1] : "TEST:CALC";
    const std::string dst_pv = argc > 2 ? argv[2] : "TEST:DOUBLE";

    std::cout << "EpicsClient pipeline: " << src_pv << " → calibrate → " << dst_pv << "\n\n";

    std::mutex              m;
    std::condition_variable cv;
    bool                    done = false;

    rxepics::EpicsClient()
        .read(src_pv)
        .map([src_pv](std::any v) -> std::any {
            double d = std::any_cast<double>(v);
            std::cout << "  [1] read    " << src_pv << " = " << d << "\n";
            return d;
        })
        .map([](std::any v) -> std::any {
            double calibrated = std::abs(std::any_cast<double>(v)) * 2.0 + 1.5;
            std::cout << "  [2] calibrated             = " << calibrated << "\n";
            return calibrated;
        })
        .write(dst_pv)
        .map([dst_pv](std::any v) -> std::any {
            std::cout << "  [3] wrote  " << dst_pv << " = " << std::any_cast<double>(v) << "\n";
            return v;
        })
        .read(dst_pv)
        .subscribe(
            [](std::any v) {
                std::cout << "\n  Confirmed on device: " << std::any_cast<double>(v) << "\n";
            },
            [&](std::exception_ptr e) {
                try { std::rethrow_exception(e); }
                catch (std::exception& ex) { std::cerr << "  ERROR: " << ex.what() << "\n"; }
                std::lock_guard<std::mutex> lk(m); done = true; cv.notify_one();
            },
            [&]() {
                std::cout << "  Pipeline complete.\n";
                std::lock_guard<std::mutex> lk(m); done = true; cv.notify_one();
            }
        );

    std::unique_lock<std::mutex> lk(m);
    cv.wait_for(lk, std::chrono::seconds(15), [&]{ return done; });
    return 0;
}
