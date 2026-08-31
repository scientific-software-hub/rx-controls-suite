#pragma once
/**
 * @file rxepics.hpp
 * @brief Umbrella include for the rxepics C++ library.
 *
 * Include this single header to pull in the complete API:
 *
 *   - rxepics::read_pv<T>(name, ctx)          — single-shot read
 *   - rxepics::write_pv<T>(name, value, ctx)  — single-shot write
 *   - rxepics::monitor_pv<T>(name, ctx)       — push observable of values
 *   - rxepics::monitor_errors<T>(name, ctx)   — push observable of per-update
 *                                                failures, as messages
 *   - rxepics::connection_status(name, ctx)   — push observable<bool>, link state
 *   - rxepics::PvUpdateError                  — a bad update carried as a value
 *   - rxepics::EpicsContext                   — context singleton
 *   - rxepics::EpicsClient                    — fluent builder
 *
 * All streaming primitives return rxcpp::observable<T>.  EPICS has no commands —
 * write to a "command PV" (an ao/bo record) instead.
 *
 * Resilience: a transient per-update failure or a connection transition is a
 * *message* on the stream, never a terminal on_error — only a setup failure is
 * terminal.  See README.md § Resilience and CLAUDE.md § PVXS gotchas.
 *
 * Mirrors the Python rxepics package (src/rxepics/__init__.py).
 */

#include "context.hpp"
#include "channel.hpp"
#include "channel_write.hpp"
#include "monitor.hpp"
#include "connection.hpp"
#include "errors.hpp"
#include "client.hpp"
