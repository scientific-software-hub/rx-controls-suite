/**
 * @file verify_contract.cpp
 * @brief ReactiveX Observable contract verification for RxTango C++ wrappers.
 *
 * This is the C++ analog of RxTangoPublisherVerification.java (reactive-streams TCK)
 * and examples/VerifySpec.java in the Java subproject.
 *
 * It verifies that the four RxTango primitives honour the ReactiveX Observable
 * contract — the same numbered rules the Java TCK enforces via PublisherVerification:
 *
 *   [C1]  Grammar:  on_next*(on_error|on_completed)? — at most one terminal signal.
 *   [C2]  Single-shot: read/write/command emit EXACTLY one on_next then on_completed.
 *   [C3]  No signals after terminal — on_completed must silence the stream.
 *   [C4]  Serialized notifications — no concurrent on_next (esp. from monitor thread).
 *   [C5]  Dispose stops push notifications — monitor unsubscribe_event is called.
 *   [C6]  Failed observable: a bad device/attr delivers on_error, not a crash.
 *
 * Run against the live docker TangoTest device:
 *
 *   docker compose up -d      # from RxTango/cpp/ (uses java/docker-compose.yml)
 *   ./build/tests/verify_contract [device] [attr]
 *   # defaults: tango://localhost:10000/sys/tg_test/1  double_scalar
 *
 * Exit code: 0 if all rules pass, 1 if any fail.
 *
 * Mirrors Java's `jbang verify-spec@.` alias.
 */

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <future>
#include <iostream>
#include <mutex>
#include <string>
#include <vector>

#include <rxtango/rxtango.hpp>

// ── helpers ──────────────────────────────────────────────────────────────────

static bool all_pass = true;

struct Result {
    std::vector<double>               values;
    std::vector<std::exception_ptr>   errors;
    std::atomic<int>                  completions{0};
};

/** Block until done is set or timeout_s seconds elapse. Returns false on timeout. */
static bool wait_for(std::mutex& m, std::condition_variable& cv,
                     bool& done, int timeout_s = 5) {
    std::unique_lock<std::mutex> lk(m);
    return cv.wait_for(lk, std::chrono::seconds(timeout_s), [&]{ return done; });
}

static void report(const char* rule, const char* desc, bool pass) {
    std::cout << (pass ? "\033[32mPASS\033[0m" : "\033[31mFAIL\033[0m")
              << "  " << rule << "  " << desc << "\n";
    if (!pass) all_pass = false;
}

// ── main ─────────────────────────────────────────────────────────────────────

int main(int argc, char* argv[]) {
    const std::string device  = (argc > 1) ? argv[1] : "tango://localhost:10000/sys/tg_test/1";
    const std::string attr    = (argc > 2) ? argv[2] : "double_scalar";
    const std::string wr_attr = "double_scalar_w";   // writable attribute on TangoTest
    const std::string cmd     = "DevDouble";          // doubles its input on TangoTest

    std::cout << "RxTango C++ — ReactiveX Observable Contract Verification\n"
              << "Device : " << device << "\n"
              << "Attr   : " << attr   << "\n\n";

    // ── [C2 + C1] Single-shot read emits exactly one value then completes ────
    {
        std::vector<double> values;
        std::vector<std::exception_ptr> errors;
        int completions = 0;
        std::mutex m; std::condition_variable cv; bool done = false;

        rxtango::read_attribute<double>(device, attr).subscribe(
            [&](double v)           { values.push_back(v); },
            [&](std::exception_ptr e) {
                errors.push_back(e);
                { std::lock_guard<std::mutex> lk(m); done = true; } cv.notify_one();
            },
            [&]() {
                ++completions;
                { std::lock_guard<std::mutex> lk(m); done = true; } cv.notify_one();
            }
        );

        bool ok = wait_for(m, cv, done);
        report("[C2][C1]", "read_attribute: exactly one on_next + on_completed",
               ok && values.size() == 1 && completions == 1 && errors.empty());
    }

    // ── [C3] No signals after terminal ───────────────────────────────────────
    {
        std::atomic<int> after_complete{0};
        int completions = 0;
        std::mutex m; std::condition_variable cv; bool done = false;

        rxtango::read_attribute<double>(device, attr).subscribe(
            [&](double) { if (completions > 0) ++after_complete; },
            [](std::exception_ptr) {},
            [&]() {
                ++completions;
                { std::lock_guard<std::mutex> lk(m); done = true; } cv.notify_one();
            }
        );

        wait_for(m, cv, done);
        // Brief wait to detect any spurious post-terminal signals
        std::this_thread::sleep_for(std::chrono::milliseconds(200));
        report("[C3]", "No on_next signals delivered after on_completed",
               after_complete == 0);
    }

    // ── [C2] Single-shot write re-emits written value then completes ─────────
    {
        double written = 3.14159;
        std::vector<double> values;
        int completions = 0;
        std::mutex m; std::condition_variable cv; bool done = false;

        rxtango::write_attribute<double>(device, wr_attr, written).subscribe(
            [&](double v) { values.push_back(v); },
            [&](std::exception_ptr) { { std::lock_guard<std::mutex> lk(m); done = true; } cv.notify_one(); },
            [&]() {
                ++completions;
                { std::lock_guard<std::mutex> lk(m); done = true; } cv.notify_one();
            }
        );

        bool ok = wait_for(m, cv, done);
        report("[C2]", "write_attribute: re-emits written value + on_completed",
               ok && values.size() == 1 && values[0] == written && completions == 1);
    }

    // ── [C2] Single-shot command emits argout then completes ─────────────────
    {
        double argin = 2.0;
        std::vector<double> values;
        int completions = 0;
        std::mutex m; std::condition_variable cv; bool done = false;

        rxtango::execute_command<double, double>(device, cmd, argin).subscribe(
            [&](double v) { values.push_back(v); },
            [&](std::exception_ptr) { { std::lock_guard<std::mutex> lk(m); done = true; } cv.notify_one(); },
            [&]() {
                ++completions;
                { std::lock_guard<std::mutex> lk(m); done = true; } cv.notify_one();
            }
        );

        bool ok = wait_for(m, cv, done);
        // DevDouble command doubles its input
        report("[C2]", "execute_command: emits argout (DevDouble 2.0 → 4.0) + on_completed",
               ok && values.size() == 1 && values[0] == argin * 2.0 && completions == 1);
    }

    // ── [C4] Monitor: serialized notifications (no concurrent on_next) ────────
    // ── [C5] Dispose stops push notifications ─────────────────────────────────
    {
        // Subscribe to PERIODIC events (always fire regardless of value changes)
        std::atomic<int> count{0};
        std::atomic<bool> concurrent_detected{false};
        std::atomic<bool> in_next{false};
        std::vector<std::exception_ptr> errors;

        auto sub = rxtango::monitor_attribute<double>(device, attr, "periodic")
            .subscribe(
                [&](double) {
                    // Detect concurrent invocations — would violate [C4]
                    bool already = in_next.exchange(true);
                    if (already) concurrent_detected = true;
                    std::this_thread::sleep_for(std::chrono::milliseconds(10));
                    in_next = false;
                    ++count;
                },
                [&](std::exception_ptr e) { errors.push_back(e); }
            );

        // Let a few events arrive
        std::this_thread::sleep_for(std::chrono::milliseconds(500));
        int count_before_dispose = count.load();

        // [C5] Dispose
        sub.unsubscribe();
        std::this_thread::sleep_for(std::chrono::milliseconds(300));
        int count_after_dispose = count.load();

        bool got_events = (count_before_dispose > 0) || !errors.empty();
        bool disposed_ok = (count_after_dispose == count_before_dispose);

        report("[C4]", "monitor_attribute: serialized (no concurrent on_next)",
               !concurrent_detected);
        // Only report [C5] as meaningful if Tango events fired; skip if event system unavailable
        if (got_events) {
            report("[C5]", "monitor_attribute: dispose stops notifications",
                   disposed_ok);
        } else {
            std::cout << "SKIP  [C5]  monitor: no PERIODIC events received "
                         "(Tango event system may not be configured)\n";
        }
    }

    // ── [C6] Failed observable: bad device delivers on_error ─────────────────
    {
        std::vector<std::exception_ptr> errors;
        int completions = 0;
        std::mutex m; std::condition_variable cv; bool done = false;

        rxtango::read_attribute<double>("tango://localhost:10000/no/such/device", "attr")
            .subscribe(
                [](double) {},
                [&](std::exception_ptr e) {
                    errors.push_back(e);
                    { std::lock_guard<std::mutex> lk(m); done = true; } cv.notify_one();
                },
                [&]() {
                    ++completions;
                    { std::lock_guard<std::mutex> lk(m); done = true; } cv.notify_one();
                }
            );

        bool ok = wait_for(m, cv, done);
        report("[C6]", "Bad device → on_error (not a crash), no on_completed",
               ok && !errors.empty() && completions == 0);
    }

    // ── Summary ───────────────────────────────────────────────────────────────
    std::cout << "\n" << (all_pass ? "\033[32mAll rules PASSED\033[0m"
                                   : "\033[31mSome rules FAILED\033[0m") << "\n";
    return all_pass ? 0 : 1;
}
