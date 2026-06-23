/**
 * Single-shot PV read — the simplest possible RxEpics example.
 *
 * Mirrors Python's read_pv.py (rxepics.channel.read_pv).
 *
 * Usage:
 *   EPICS_PVA_ADDR_LIST=localhost ./read_pv [pv_name ...]
 *   defaults: TEST:DOUBLE TEST:LONG
 */

#include <condition_variable>
#include <iostream>
#include <mutex>
#include <string>
#include <vector>

#include <rxcpp/rx.hpp>
#include <rxepics/rxepics.hpp>

int main(int argc, char* argv[]) {
    std::vector<std::string> pvs;
    for (int i = 1; i < argc; ++i) pvs.emplace_back(argv[i]);
    if (pvs.empty()) pvs = {"TEST:DOUBLE", "TEST:LONG"};

    auto& ctx = rxepics::default_context();

    for (const auto& pv : pvs) {
        std::mutex              m;
        std::condition_variable cv;
        bool                    done = false;

        std::cout << "Reading " << pv << " ...\n";
        rxepics::read_pv<double>(pv, ctx).subscribe(
            [](double v) { std::cout << "  value: " << v << "\n"; },
            [&](std::exception_ptr e) {
                try { std::rethrow_exception(e); }
                catch (std::exception& ex) { std::cerr << "  ERROR: " << ex.what() << "\n"; }
                std::lock_guard<std::mutex> lk(m); done = true; cv.notify_one();
            },
            [&]() { std::lock_guard<std::mutex> lk(m); done = true; cv.notify_one(); }
        );

        std::unique_lock<std::mutex> lk(m);
        cv.wait(lk, [&]{ return done; });
    }
    return 0;
}
