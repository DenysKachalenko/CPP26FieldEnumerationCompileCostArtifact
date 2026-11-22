# SerializationCompileCost — reproducible build of the correctness tests.
# Compile-time *measurements* are driven by Harness/campaign.py (direct compiler
# invocation), not by this build; CMake fetches the pinned libraries and lets a
# reviewer build and run the correctness tests with one command.
#
# Requires a C++26 compiler with P2996 static reflection (GCC 16 with -freflection).
# Point CMAKE_CXX_COMPILER at it (see CMakePresets.json).
cmake_minimum_required(VERSION 3.24)
project(SerializationCompileCost CXX)

set(CMAKE_CXX_STANDARD 26)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
add_compile_options(-freflection)
if(MINGW)
  # Large TUs exceed the PE/COFF section limit (spurious undefined references at link).
  add_compile_options(-Wa,-mbig-obj)
endif()
cmake_policy(SET CMP0135 NEW)

include(FetchContent)

# Libraries: Deps.json is the single pin file, shared with Harness/deps.py. Each pin
# is the GitHub tarball of one commit, verified by sha256. SOURCE_SUBDIR points at a
# non-existent dir so the sources are populated without configuring each library.
file(READ "${CMAKE_CURRENT_SOURCE_DIR}/Deps.json" RB_DEPS_JSON)
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/Deps.json")
set(RB_DEP_INCLUDES "")
string(JSON dep_count LENGTH "${RB_DEPS_JSON}" deps)
math(EXPR dep_last "${dep_count} - 1")
foreach(dep_index RANGE ${dep_last})
  string(JSON dep MEMBER "${RB_DEPS_JSON}" deps ${dep_index})
  string(JSON dep_url GET "${RB_DEPS_JSON}" deps ${dep} url)
  string(JSON dep_sha GET "${RB_DEPS_JSON}" deps ${dep} sha256)
  string(JSON dep_inc GET "${RB_DEPS_JSON}" deps ${dep} include)
  string(MAKE_C_IDENTIFIER "${dep}" dep_id)
  FetchContent_Declare(${dep_id} URL ${dep_url} URL_HASH SHA256=${dep_sha} SOURCE_SUBDIR do-not-add)
  FetchContent_MakeAvailable(${dep_id})
  list(APPEND RB_DEP_INCLUDES "${${dep_id}_SOURCE_DIR}/${dep_inc}")
endforeach()

add_library(rb_deps INTERFACE)
target_include_directories(rb_deps INTERFACE ${CMAKE_CURRENT_SOURCE_DIR}/Include ${RB_DEP_INCLUDES})

enable_testing()

# FPlayer: native reflection honours the P3394 Transient annotation; == hand-written.
add_executable(correctness Test/Correctness.cpp)
target_link_libraries(correctness PRIVATE rb_deps)
add_test(NAME correctness COMMAND correctness)

# Every arm on a nested record with containers, under each library backend.
# (The synthetic-corpus oracle for every arm and variant runs in Harness/preflight.py.)
set(RB_DEMO_VARIANTS
  "default|"
  "pfr_classic|BOOST_PFR_USE_CPP26=0"
  "pfr_native|BOOST_PFR_USE_CPP26_REFLECTION=1"
  "rflcpp_native|REFLECTCPP_USE_CPP26_REFLECTION"
  "glaze_classic|GLZ_REFLECTION26=0")
foreach(variant IN LISTS RB_DEMO_VARIANTS)
  string(REPLACE "|" ";" parts "${variant}")
  list(GET parts 0 name)
  list(LENGTH parts n)
  set(target arms_demo_${name})
  add_executable(${target} Test/ArmsDemo.cpp)
  target_link_libraries(${target} PRIVATE rb_deps)
  if(n GREATER 1)
    list(GET parts 1 define)
    if(define)
      target_compile_definitions(${target} PRIVATE ${define})
    endif()
  endif()
  add_test(NAME ${target} COMMAND ${target})
endforeach()
