#pragma once
/**
 * @file rxepics.hpp
 * @brief Umbrella include for the rxepics C++ library.
 *
 * Include this single header to pull in the complete API:
 *
 *   - rxepics::read_pv<T>(name, ctx)          — single-shot read
 *   - rxepics::write_pv<T>(name, value, ctx)  — single-shot write
 *   - rxepics::monitor_pv<T>(name, ctx)       — push observable
 *   - rxepics::EpicsContext                   — context singleton
 *   - rxepics::EpicsClient                    — fluent builder
 *
 * All primitives return rxcpp::observable<T>.  EPICS has no commands —
 * write to a "command PV" (an ao/bo record) instead.
 *
 * Mirrors the Python rxepics package (src/rxepics/__init__.py).
 */

#include "context.hpp"
#include "channel.hpp"
#include "channel_write.hpp"
#include "monitor.hpp"
#include "client.hpp"
