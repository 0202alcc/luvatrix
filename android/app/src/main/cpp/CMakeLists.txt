cmake_minimum_required(VERSION 3.22.1)
project(luvatrix_android)

add_library(luvatrix_vulkan_renderer SHARED luvatrix_vulkan_renderer.cpp)
target_compile_options(
    luvatrix_vulkan_renderer
    PRIVATE $<$<CONFIG:Debug>:-O3>
)
find_library(log-lib log)
find_library(android-lib android)
find_library(vulkan-lib vulkan)

target_link_libraries(
    luvatrix_vulkan_renderer
    ${log-lib}
    ${android-lib}
    ${vulkan-lib}
)
