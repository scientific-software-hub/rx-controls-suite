cmake_minimum_required(VERSION 3.16)
project(StorageRingSim LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

find_package(PkgConfig REQUIRED)
find_package(Threads REQUIRED)
pkg_check_modules(TANGO REQUIRED tango)

add_executable(StorageRingSim
    src/ClassFactory.cpp
    src/SimulationEngine.cpp
    src/StorageRingController.cpp
    src/StorageRingControllerClass.cpp
    src/StorageRingSector.cpp
    src/StorageRingSectorClass.cpp
    src/main.cpp
)

target_include_directories(StorageRingSim PRIVATE
    ${TANGO_INCLUDE_DIRS}
    ${CMAKE_CURRENT_SOURCE_DIR}/src
)

target_link_directories(StorageRingSim PRIVATE ${TANGO_LIBRARY_DIRS})
target_link_libraries(StorageRingSim PRIVATE ${TANGO_LIBRARIES} Threads::Threads)
target_compile_options(StorageRingSim PRIVATE ${TANGO_CFLAGS_OTHER})
