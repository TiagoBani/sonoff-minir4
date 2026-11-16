cmake_minimum_required(VERSION 3.16.0)
set(PROJECT_VER "0.2.0")
set(HK_REFERENCE "${CMAKE_CURRENT_LIST_DIR}/../esp-homekit-reference")
execute_process(COMMAND git rev-parse HEAD WORKING_DIRECTORY "${HK_REFERENCE}"
    OUTPUT_VARIABLE HK_REV OUTPUT_STRIP_TRAILING_WHITESPACE)
if(NOT HK_REV STREQUAL "2985547b3ebb99e1e31350d369bc543327fe7e49")
    message(FATAL_ERROR "Unexpected ESP HomeKit SDK revision")
endif()
set(EXTRA_COMPONENT_DIRS
    "${HK_REFERENCE}/components/homekit/esp_hap_core"
    "${HK_REFERENCE}/components/homekit/esp_hap_apple_profiles"
    "${HK_REFERENCE}/components/homekit/hkdf-sha"
    "${HK_REFERENCE}/components/homekit/mu_srp")
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(minir4_homekit)
