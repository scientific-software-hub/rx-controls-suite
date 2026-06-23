set(EXAMPLES
    read_pv
    poll_pv
    monitor_pv
    multi_pv_snapshot
    pv_correlate
    zip_pvs
    alarm_monitor
    calibration_pipeline
    pv_pipeline
    pv_throttle
    pv_sliding_average
    pv_running_stats
    pv_backpressure
    pv_stats
)

foreach(EX IN LISTS EXAMPLES)
    add_executable(${EX} ${EX}.cpp)
    target_link_libraries(${EX} PRIVATE rxepics)
endforeach()
