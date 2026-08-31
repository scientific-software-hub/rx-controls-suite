cmake_minimum_required(VERSION 3.18)
project(RxEpics-cpp VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# ── RxCpp (header-only) via FetchContent ──────────────────────────────────────
# RxCpp v4.1.1's own CMake project unconditionally adds its test and example
# targets, and RxCpp's test sources do not compile under GCC 13 (-Werror=nonnull
# in rx-coordination.hpp).  RxCpp is header-only, so skip its CMakeLists entirely
# (SOURCE_SUBDIR pointed at a dir with no CMakeLists.txt) and define the interface
# target ourselves against the fetched headers.
include(FetchContent)
FetchContent_Declare(
    rxcpp
    GIT_REPOSITORY https://github.com/ReactiveX/RxCpp.git
    GIT_TAG        v4.1.1
    GIT_SHALLOW    TRUE
    SOURCE_SUBDIR  cmake-do-not-build
)
FetchContent_MakeAvailable(rxcpp)

add_library(rxcpp INTERFACE)
target_include_directories(rxcpp INTERFACE "${rxcpp_SOURCE_DIR}/Rx/v2/src")
target_compile_features(rxcpp INTERFACE cxx_std_14)
# RxCpp 4.1.1's rx-coordination.hpp forms decltype expressions through a null
# `this` that GCC 12+ diagnoses under -Wnonnull; on some instantiation paths GCC
# 13 promotes it to a hard error.  The construct is well-defined SFINAE, so
# silence it for every consumer of the header.
if(CMAKE_CXX_COMPILER_ID STREQUAL "GNU")
    target_compile_options(rxcpp INTERFACE -Wno-nonnull -Wno-error=nonnull)
endif()

# ── PVXS (modern EPICS PVA C++ client) ───────────────────────────────────────
# Three discovery paths, in order of preference:
#   1. find_package(PVXS)         — a PVXS build that installed a CMake config
#   2. pkg-config                 — a distro package that shipped a pvxs.pc
#   3. -DPVXS_ROOT / -DEPICS_BASE — a stock `make`-built EPICS support tree
#      (PVXS's own build installs neither a CMake config nor a .pc file, so this
#      is the path the CI `build` job and a from-source install actually take).
set(PVXS_TARGET "")

find_package(PVXS QUIET CONFIG)
if(PVXS_FOUND)
    set(PVXS_TARGET PVXS::pvxs)
endif()

if(NOT PVXS_TARGET)
    find_package(PkgConfig QUIET)
    if(PkgConfig_FOUND)
        pkg_check_modules(PVXS_PC QUIET IMPORTED_TARGET pvxs)
        if(PVXS_PC_FOUND)
            set(PVXS_TARGET PkgConfig::PVXS_PC)
        endif()
    endif()
endif()

if(NOT PVXS_TARGET)
    # EPICS-style tree.  Each root is a -D cache var, also read from the env.
    # NB: not "PVXS_DIR" — find_package(CONFIG) reserves <pkg>_DIR and rewrites it
    # to <pkg>_DIR-NOTFOUND on a failed config search, clobbering the -D value.
    set(PVXS_ROOT  "$ENV{PVXS_ROOT}"  CACHE PATH   "PVXS install / support tree root")
    set(EPICS_BASE "$ENV{EPICS_BASE}" CACHE PATH   "EPICS Base root")
    set(EPICS_HOST_ARCH "$ENV{EPICS_HOST_ARCH}" CACHE STRING "EPICS host arch")
    if(NOT EPICS_HOST_ARCH)
        set(EPICS_HOST_ARCH "linux-x86_64")
    endif()

    find_path(PVXS_INCLUDE_DIR pvxs/client.h
        HINTS "${PVXS_ROOT}" ENV PVXS_ROOT PATH_SUFFIXES include)
    find_library(PVXS_LIBRARY NAMES pvxs
        HINTS "${PVXS_ROOT}" ENV PVXS_ROOT
        PATH_SUFFIXES "lib/${EPICS_HOST_ARCH}" lib)
    find_path(EPICS_BASE_INCLUDE_DIR epicsTime.h
        HINTS "${EPICS_BASE}" ENV EPICS_BASE PATH_SUFFIXES include)
    find_library(EPICS_COM_LIBRARY NAMES Com
        HINTS "${EPICS_BASE}" ENV EPICS_BASE
        PATH_SUFFIXES "lib/${EPICS_HOST_ARCH}" lib)

    if(PVXS_INCLUDE_DIR AND PVXS_LIBRARY AND EPICS_BASE_INCLUDE_DIR AND EPICS_COM_LIBRARY)
        add_library(rxepics_pvxs INTERFACE)
        target_include_directories(rxepics_pvxs INTERFACE
            "${PVXS_INCLUDE_DIR}"
            "${EPICS_BASE_INCLUDE_DIR}"
            "${EPICS_BASE_INCLUDE_DIR}/os/Linux"
            "${EPICS_BASE_INCLUDE_DIR}/compiler/gcc")
        target_link_libraries(rxepics_pvxs INTERFACE
            "${PVXS_LIBRARY}" "${EPICS_COM_LIBRARY}")
        set(PVXS_TARGET rxepics_pvxs)
    endif()
endif()

if(NOT PVXS_TARGET)
    message(FATAL_ERROR
        "PVXS not found.  Install a PVXS providing a CMake config or pvxs.pc, or "
        "pass -DPVXS_ROOT=<pvxs tree> -DEPICS_BASE=<epics-base tree> "
        "(see .github/workflows/rxepics-cpp.yml for the reference invocation).")
endif()

# ── rxepics interface (header-only library target) ────────────────────────────
add_library(rxepics INTERFACE)
target_include_directories(rxepics INTERFACE include)
target_link_libraries(rxepics INTERFACE rxcpp ${PVXS_TARGET})
target_compile_features(rxepics INTERFACE cxx_std_17)

# ── Sub-directories ───────────────────────────────────────────────────────────
add_subdirectory(examples)
add_subdirectory(tests)
