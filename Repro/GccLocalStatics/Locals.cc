// 18 block-scope local classes per instantiation, N instantiations.
// g++ -std=c++17 -fsyntax-only -ftime-report -DN=8000 Locals.cc
#include <utility>
#ifndef N
#define N 1000
#endif
#define B { struct L { int v; }; s += int(sizeof(L)) * K; }
template<int K> int f() {
  int s = 0;
  B B B B B B B B B B B B B B B B B B
  return s;
}
template<int... K> int all(std::integer_sequence<int, K...>) { return (0 + ... + f<K>()); }
int g() { return all(std::make_integer_sequence<int, N>{}); }
