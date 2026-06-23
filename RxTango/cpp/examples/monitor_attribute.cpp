/**
 * Monitor a Tango attribute using push events — the multi-value, push-based pattern.
 *
 * Mirrors Python's monitor_attribute.py and Java's MonitorAttribute.java.
 * Uses RxTangoAttributeChangePublisher in Java; monitor_attribute<T> here.
 *
 * Note: Tango events require a properly configured event system (ZMQ ports
 * reachable from the client).  Use poll_attribute for polling instead.
 *
 * Usage:
 *   ./monitor_attribute [device] [attribute] [event-type]
 *   defaults: sys/tg_test/1  double_scalar  periodic
 */

#include <csignal>
#include <iostream>
#include <string>

#include <rxtango/rxtango.hpp>

static volatile sig_atomic_t g_running = 1;

int main(int argc, char* argv[]) {
    const std::string device = argc > 1 ? argv[1] : "tango://localhost:10000/sys/tg_test/1";
    const std::string attr   = argc > 2 ? argv[2] : "double_scalar";
    const std::string event  = argc > 3 ? argv[3] : "periodic";

    std::signal(SIGINT, [](int) { g_running = 0; });

    std::cout << "Monitoring " << device << "/" << attr
              << " [" << event << " events]  (Ctrl+C to stop)\n\n";

    auto sub = rxtango::monitor_attribute<double>(device, attr, event)
        .subscribe(
            [](double v) { std::cout << "  event: " << v << "\n"; },
            [](std::exception_ptr e) {
                try { std::rethrow_exception(e); }
                catch (std::exception& ex) { std::cerr << "  ERROR: " << ex.what() << "\n"; }
            }
        );

    while (g_running) std::this_thread::sleep_for(std::chrono::milliseconds(100));
    sub.unsubscribe();   // → unsubscribe_event() called; stream torn down cleanly
    std::cout << "\n  stopped.\n";
    return 0;
}
