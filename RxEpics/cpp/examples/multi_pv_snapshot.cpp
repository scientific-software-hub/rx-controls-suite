/**
 * Multi-PV parallel snapshot — concurrent reads from N PVs, collected into a vector.
 *
 * Mirrors Python's multi_pv_snapshot.py.
 *
 * Usage:
 *   EPICS_PVA_ADDR_LIST=localhost ./multi_pv_snapshot [pv1] [pv2] ...
 *   defaults: TEST:DOUBLE TEST:LONG TEST:CALC
 */

#include <condition_variable>
#include <iostream>
#include <limits>
#include <mutex>
#include <string>
#include <vector>

#include <rxcpp/rx.hpp>
#include <rxepics/rxepics.hpp>

int main(int argc, char* argv[]) {
    std::vector<std::string> pvs;
    for (int i = 1; i < argc; ++i) pvs.emplace_back(argv[i]);
    if (pvs.empty()) pvs = {"TEST:DOUBLE", "TEST:LONG", "TEST:CALC"};

    auto& ctx = rxepics::default_context();

    std::cout << "Snapshot of " << pvs.size() << " PV(s)\n\n";

    std::mutex              m;
    std::condition_variable cv;
    bool                    done = false;

    rxcpp::observable<>::iterate(pvs)
        .flat_map([&ctx](const std::string& pv) {
            return rxepics::read_pv<double>(pv, ctx)
                .on_error_resume_next([](std::exception_ptr) {
                    return rxcpp::observable<>::just(
                        std::numeric_limits<double>::quiet_NaN());
                });
        })
        .to_vector()
        .subscribe(
            [&pvs](const std::vector<double>& results) {
                for (size_t i = 0; i < results.size(); ++i)
                    std::cout << "  " << pvs[i] << " = " << results[i] << "\n";
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
