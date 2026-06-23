add_executable(verify_contract verify_contract.cpp)
target_link_libraries(verify_contract PRIVATE rxtango)

# Hint: run against the docker TangoTest device after `docker compose up -d`
# from the RxTango/cpp directory.
#
# Usage:
#   cmake -S .. -B ../build && cmake --build ../build
#   ./verify_contract [device] [attribute]
#   # defaults: tango://localhost:10000/sys/tg_test/1  double_scalar
