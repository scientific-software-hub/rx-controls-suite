set(EXAMPLES
    read_attribute
    poll_attribute
    monitor_attribute
    zip_attributes
    multi_device_snapshot
    correlate
    alarm_monitor
    sliding_average
    throttle
    running_stats
    stats
    backpressure
    retry
    zip_window
    calibration_pipeline
    pipeline
    fluent_client
)

foreach(EX IN LISTS EXAMPLES)
    add_executable(${EX} ${EX}.cpp)
    target_link_libraries(${EX} PRIVATE rxtango)
endforeach()
