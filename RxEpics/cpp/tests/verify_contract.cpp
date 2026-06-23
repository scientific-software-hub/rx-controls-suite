/**
 * @file verify_contract.cpp
 * @brief ReactiveX Observable contract verification for RxEpics C++ wrappers.
 *
 * The C++ analog of RxTangoPublisherVerification.java (for Tango) — applied here to
 * the EPICS PVXS-based primitives.  This makes RxEpics/cpp the first EPICS subproject
 * in the suite with a reactive conformance test (RxEpics/python has none).
 *
 * Verifies:
 *   [C1]  Grammar: on_next*(on_error|on_completed)? — at most one terminal signal.
 *   [C2]  Single-shot: read_pv/write_pv emit EXACTLY one on_next then on_completed.
 *   [C3]  No signals after terminal — on_completed must silence the stream.
 *   [C4]  Serialized notifications — no concurrent on_next from monitor callbacks.
 *   [C5]  Dispose stops push notifications — PVXS Monitor handle is destroyed.
 *   [C6]  Failed observable: a bad PV name delivers on_error, not a crash.
 *
 * Run against the live softIoc:
 *
 *   docker compose up -d
 *   export EPICS_PVA_ADDR_LIST=localhost
 *   export EPICS_PVA_AUTO_ADDR_LIST=NO
 *   ./build/tests/verify_contract [pv_name]
 *   # default PV: TEST:DOUBLE (static ao record)
 *
 * Exit code: 0 if all rules pass, 1 if any fail.
 */

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <iostream>
#include <mutex>
#include <string>
#include <vector>

#include <rxepics/rxepics.hpp>

// ── helpers ──────────────────────────────────────────────────────────────────

static bool all_pass = true;

static bool wait_done(std::mutex& m, std::condition_variable& cv,
                      bool& done, int timeout_s = 10) {
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
    const std::string pv      = (argc > 1) ? argv[1] : "TEST:DOUBLE";
    const std::string pv_calc = "TEST:CALC";          // oscillating PV for monitor test

    std::cout << "RxEpics C++ — ReactiveX Observable Contract Verification\n"
              << "PV     : " << pv      << "\n"
              << "Monitor: " << pv_calc << "\n\n";

    auto& ctx = rxepics::default_context();

    // ── [C2 + C1] Single-shot read emits exactly one value then completes ────
    {
        std::vector<double> values;
        std::vector<std::exception_ptr> errors;
        int completions = 0;
        std::mutex m; std::condition_variable cv; bool done = false;

        rxepics::read_pv<double>(pv, ctx).subscribe(
            [&](double v)             { values.push_back(v); },
            [&](std::exception_ptr e) {
                errors.push_back(e);
                { std::lock_guard<std::mutex> lk(m); done = true; } cv.notify_one();
            },
            [&]() {
                ++completions;
                { std::lock_guard<std::mutex> lk(m); done = true; } cv.notify_one();
            }
        );

        bool ok = wait_done(m, cv, done);
        report("[C2][C1]", "read_pv: exactly one on_next + on_completed",
               ok && values.size() == 1 && completions == 1 && errors.empty());
    }

    // ── [C3] No signals after terminal ───────────────────────────────────────
    {
        std::atomic<int> after_complete{0};
        int completions = 0;
        std::mutex m; std::condition_variable cv; bool done = false;

        rxepics::read_pv<double>(pv, ctx).subscribe(
            [&](double) { if (completions > 0) ++after_complete; },
            [](std::exception_ptr) {},
            [&]() {
                ++completions;
                { std::lock_guard<std::mutex> lk(m); done = true; } cv.notify_one();
            }
        );

        wait_done(m, cv, done);
        std::this_thread::sleep_for(std::chrono::milliseconds(200));
        report("[C3]", "No on_next signals delivered after on_completed",
               after_complete == 0);
    }

    // ── [C2] Single-shot write re-emits written value then completes ─────────
    {
        double written = 2.718;
        std::vector<double> values;
        int completions = 0;
        std::mutex m; std::condition_variable cv; bool done = false;

        rxepics::write_pv<double>(pv, written, ctx).subscribe(
            [&](double v)             { values.push_back(v); },
            [&](std::exception_ptr e) {
                (void)e;
                { std::lock_guard<std::mutex> lk(m); done = true; } cv.notify_one();
            },
            [&]() {
                ++completions;
                { std::lock_guard<std::mutex> lk(m); done = true; } cv.notify_one();
            }
        );

        bool ok = wait_done(m, cv, done);
        report("[C2]", "write_pv: re-emits written value + on_completed",
               ok && values.size() == 1 && values[0] == written && completions == 1);
    }

    // ── [C4] Monitor: serialized notifications (no concurrent on_next) ────────
    // ── [C5] Dispose stops push notifications ─────────────────────────────────
    {
        std::atomic<int>  count{0};
        std::atomic<bool> concurrent_detected{false};
        std::atomic<bool> in_next{false};
        std::vector<std::exception_ptr> errors;

        auto sub = rxepics::monitor_pv<double>(pv_calc, ctx)
            .subscribe(
                [&](double) {
                    bool already = in_next.exchange(true);
                    if (already) concurrent_detected = true;
                    std::this_thread::sleep_for(std::chrono::milliseconds(10));
                    in_next = false;
                    ++count;
                },
                [&](std::exception_ptr e) { errors.push_back(e); }
            );

        std::this_thread::sleep_for(std::chrono::milliseconds(600));
        int before = count.load();

        sub.unsubscribe();   // → destroy PVXS Monitor → unsubscribe
        std::this_thread::sleep_for(std::chrono::milliseconds(300));
        int after = count.load();

        bool got_events = (before > 0) || !errors.empty();
        report("[C4]", "monitor_pv: serialized (no concurrent on_next)",
               !concurrent_detected);
        if (got_events) {
            report("[C5]", "monitor_pv: dispose stops notifications",
                   after == before);
        } else {
            std::cout << "SKIP  [C5]  monitor: no PV updates received "
                         "(check EPICS_PVA_ADDR_LIST and that TEST:CALC is scanning)\n";
        }
    }

    // ── [C6] Failed observable: bad PV name delivers on_error ────────────────
    {
        std::vector<std::exception_ptr> errors;
        int completions = 0;
        std::mutex m; std::condition_variable cv; bool done = false;

        rxepics::read_pv<double>("DOES:NOT:EXIST:9999", ctx).subscribe(
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

        bool ok = wait_done(m, cv, done, 8);   // PVXS get() times out after ~5 s
        report("[C6]", "Bad PV name → on_error (not a crash), no on_completed",
               ok && !errors.empty() && completions == 0);
    }

    // ── Summary ───────────────────────────────────────────────────────────────
    std::cout << "\n" << (all_pass ? "\033[32mAll rules PASSED\033[0m"
                                   : "\033[31mSome rules FAILED\033[0m") << "\n";
    return all_pass ? 0 : 1;
}
