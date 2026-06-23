/**
 * Multi-device parallel snapshot — concurrent reads from N devices, collected into a vector.
 *
 * Mirrors Python's multi_device_snapshot.py and Java's MultiDeviceSnapshot.java.
 *
 * All reads fire in parallel; per-device failures are isolated (on_error_return_item)
 * so one bad device never blocks the others.
 *
 * Usage:
 *   ./multi_device_snapshot [attr] [device1] [device2] ...
 *   defaults: double_scalar  sys/tg_test/1  sys/tg_test/1  (same device twice)
 */

#include <condition_variable>
#include <iostream>
#include <mutex>
#include <string>
#include <vector>

#include <rxcpp/rx.hpp>
#include <rxtango/rxtango.hpp>

int main(int argc, char* argv[]) {
    const std::string attr = argc > 1 ? argv[1] : "double_scalar";

    std::vector<std::string> devices;
    for (int i = 2; i < argc; ++i) devices.emplace_back(argv[i]);
    if (devices.empty()) {
        devices = { "tango://localhost:10000/sys/tg_test/1",
                    "tango://localhost:10000/sys/tg_test/1" };
    }

    std::cout << "Snapshot of " << devices.size() << " device(s), attribute: " << attr << "\n\n";

    std::mutex              m;
    std::condition_variable cv;
    bool                    done = false;

    // Mirrors: fromIterable → flat_map (concurrent) → on_error_return → to_list
    rxcpp::observable<>::iterate(devices)
        .flat_map([attr](const std::string& dev) {
            return rxtango::read_attribute<double>(dev, attr)
                .on_error_resume_next([dev](std::exception_ptr) {
                    // Isolate per-device failures with a sentinel value
                    return rxcpp::observable<>::just(std::numeric_limits<double>::quiet_NaN());
                });
        })
        .to_vector()
        .subscribe(
            [&devices, &attr](const std::vector<double>& results) {
                for (size_t i = 0; i < results.size(); ++i) {
                    std::cout << "  [" << i << "] " << devices[i] << "/" << attr
                              << " = " << results[i] << "\n";
                }
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
