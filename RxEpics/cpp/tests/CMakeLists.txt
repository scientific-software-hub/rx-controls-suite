add_executable(verify_contract verify_contract.cpp)
target_link_libraries(verify_contract PRIVATE rxepics)

# Hint: run against the docker softIoc after `docker compose up -d`
# from the RxEpics/cpp directory.
#
# Usage:
#   cmake -S .. -B ../build && cmake --build ../build
#   EPICS_PVA_ADDR_LIST=localhost ./verify_contract [pv_name]
#   # default PV: TEST:DOUBLE
