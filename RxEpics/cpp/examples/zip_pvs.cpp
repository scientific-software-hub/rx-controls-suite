/**
 * Zip two PVs — atomic correlated pair.
 *
 * Mirrors Python's zip_pvs.py. Pair is only produced when BOTH reads complete.
 *
 * Usage:
 *   EPICS_PVA_ADDR_LIST=localhost ./zip_pvs [pv1] [pv2]
 *   defaults: TEST:DOUBLE TEST:LONG
 */

#include <condition_variable>
#include <iomanip>
#include <iostream>
#include <mutex>
#include <string>

#include <rxcpp/rx.hpp>
#include <rxepics/rxepics.hpp>

int main(int argc, char* argv[]) {
    const std::string pv1 = argc > 1 ? argv[1] : "TEST:DOUBLE";
    const std::string pv2 = argc > 2 ? argv[2] : "TEST:LONG";

    auto& ctx = rxepics::default_context();

    std::cout << "Zipping " << pv1 << " + " << pv2 << " ...\n\n";

    std::mutex              m;
    std::condition_variable cv;
    bool                    done = false;

    rxcpp::observable<>::zip(
        [](double a, double b) { return std::make_pair(a, b); },
        rxepics::read_pv<double>(pv1, ctx),
        rxepics::read_pv<double>(pv2, ctx)
    ).subscribe(
        [&pv1, &pv2](std::pair<double,double> p) {
            std::cout << "  " << pv1 << " = " << p.first << "\n"
                      << "  " << pv2 << " = " << p.second << "\n"
                      << "  diff = " << (p.first - p.second) << "\n";
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
