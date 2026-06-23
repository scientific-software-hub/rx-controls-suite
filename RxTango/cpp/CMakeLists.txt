cmake_minimum_required(VERSION 3.18)
project(RxTango-cpp VERSION 0.1.0 LANGUAGES CXX)

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

# ── cppTango via pkg-config ───────────────────────────────────────────────────
find_package(PkgConfig REQUIRED)
pkg_check_modules(TANGO REQUIRED IMPORTED_TARGET tango)

# ── rxtango interface (header-only library target) ────────────────────────────
add_library(rxtango INTERFACE)
target_include_directories(rxtango INTERFACE include)
target_link_libraries(rxtango INTERFACE rxcpp PkgConfig::TANGO)
target_compile_features(rxtango INTERFACE cxx_std_17)

# ── Sub-directories ───────────────────────────────────────────────────────────
add_subdirectory(examples)
add_subdirectory(tests)
