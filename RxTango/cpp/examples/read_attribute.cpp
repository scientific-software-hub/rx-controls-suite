/**
 * Single-shot attribute read — the simplest possible RxTango example.
 *
 * Mirrors Python's read_attribute.py and Java's ReadAttribute.java.
 *
 * Usage:
 *   ./read_attribute [device] [attribute]
 *   defaults: tango://localhost:10000/sys/tg_test/1  double_scalar
 */

#include <condition_variable>
#include <iostream>
#include <mutex>
#include <string>

#include <rxtango/rxtango.hpp>

int main(int argc, char* argv[]) {
    const std::string device = argc > 1 ? argv[1] : "tango://localhost:10000/sys/tg_test/1";
    const std::string attr   = argc > 2 ? argv[2] : "double_scalar";

    std::cout << "Reading " << device << "/" << attr << " ...\n";

    std::mutex              m;
    std::condition_variable cv;
    bool                    done = false;

    rxtango::read_attribute<double>(device, attr).subscribe(
        [](double v) { std::cout << "  value: " << v << "\n"; },
        [&](std::exception_ptr e) {
            try { std::rethrow_exception(e); }
            catch (std::exception& ex) { std::cerr << "  ERROR: " << ex.what() << "\n"; }
            std::lock_guard<std::mutex> lk(m); done = true; cv.notify_one();
        },
        [&]() {
            std::lock_guard<std::mutex> lk(m); done = true; cv.notify_one();
        }
    );

    std::unique_lock<std::mutex> lk(m);
    cv.wait(lk, [&]{ return done; });
    return 0;
}
