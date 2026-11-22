// 18 block-scope static variables per instantiation, N instantiations.
// g++ -std=c++17 -fsyntax-only -ftime-report -DN=8000 Statics.cc
#include <utility>
#ifndef N
#define N 1000
#endif
#define B { static constexpr int v = 1; s += v * K; }
template<int K> int f() {
  int s = 0;
  B B B B B B B B B B B B B B B B B B
  return s;
}
template<int... K> int all(std::integer_sequence<int, K...>) { return (0 + ... + f<K>()); }
int g() { return all(std::make_integer_sequence<int, N>{}); }
