cmake_minimum_required(VERSION 3.18)
project(RxEpics-cpp VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# ── RxCpp (header-only) via FetchContent ──────────────────────────────────────
include(FetchContent)
FetchContent_Declare(
    rxcpp
    GIT_REPOSITORY https://github.com/ReactiveX/RxCpp.git
    GIT_TAG        v4.1.1
)
FetchContent_MakeAvailable(rxcpp)

# ── PVXS (modern EPICS PVA C++ client) ───────────────────────────────────────
# PVXS ships a CMake config; fall back to pkg-config if not found.
find_package(PVXS QUIET)
if(PVXS_FOUND)
    set(PVXS_TARGET PVXS::pvxs)
else()
    find_package(PkgConfig REQUIRED)
    pkg_check_modules(PVXS REQUIRED IMPORTED_TARGET pvxs)
    set(PVXS_TARGET PkgConfig::PVXS)
endif()

# ── rxepics interface (header-only library target) ────────────────────────────
add_library(rxepics INTERFACE)
target_include_directories(rxepics INTERFACE include)
target_link_libraries(rxepics INTERFACE rxcpp ${PVXS_TARGET})
target_compile_features(rxepics INTERFACE cxx_std_17)

# ── Sub-directories ───────────────────────────────────────────────────────────
add_subdirectory(examples)
add_subdirectory(tests)
