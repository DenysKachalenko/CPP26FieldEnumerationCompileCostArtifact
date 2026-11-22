// Iterating vs destructuring expansion statement over the same 16 constants.
// g++ -std=c++26 -fsyntax-only -ftime-report -DRANGE=A  ExpansionRange.cc   // array: destructuring
// g++ -std=c++26 -fsyntax-only -ftime-report -DRANGE=SP ExpansionRange.cc   // std::span: iterating
// g++ -std=c++26 -fsyntax-only -ftime-report -DRANGE=PR ExpansionRange.cc   // pointer begin/end: iterating
#include <span>
#include <utility>

constexpr int A[16] = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16};
constexpr std::span<const int> SP{A};
struct ptr_range {
  const int *b, *e;
  constexpr const int* begin() const { return b; }
  constexpr const int* end() const { return e; }
};
constexpr ptr_range PR{A, A + 16};

#ifndef N
#define N 1000
#endif

template<int K> int f() {
  int s = 0;
  template for (constexpr int x : RANGE) s += x * K;
  return s;
}
template<int... K> int all(std::integer_sequence<int, K...>) { return (0 + ... + f<K>()); }
int g() { return all(std::make_integer_sequence<int, N>{}); }
