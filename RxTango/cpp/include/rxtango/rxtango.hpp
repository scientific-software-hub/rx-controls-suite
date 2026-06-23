#pragma once
/**
 * @file rxtango.hpp
 * @brief Umbrella include for the rxtango C++ library.
 *
 * Include this single header to pull in the complete API:
 *
 *   - rxtango::read_attribute<T>(device, attr)         — single-shot read
 *   - rxtango::write_attribute<T>(device, attr, value) — single-shot write
 *   - rxtango::execute_command<R,A>(device, cmd, argin)— single-shot command
 *   - rxtango::monitor_attribute<T>(device, attr)      — push observable
 *   - rxtango::TangoContext                            — proxy cache singleton
 *   - rxtango::TangoClient                             — fluent builder
 *
 * All primitives return rxcpp::observable<T> backed by standard RxCpp operators.
 * No framework lock-in: the library only depends on RxCpp and cppTango headers.
 *
 * Mirrors the Python rxtango package (src/rxtango/__init__.py) and the Java
 * org.tango.client.rx package (RxTango/java/src/).
 */

#include "context.hpp"
#include "attribute.hpp"
#include "attribute_write.hpp"
#include "command.hpp"
#include "monitor.hpp"
#include "client.hpp"
