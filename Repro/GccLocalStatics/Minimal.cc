// N instantiations of a function template that holds one block-scope variable.
// The instantiations come from a binary split of [0, N) (2N - 1 helper classes, depth
// log2 N), so nothing else in the file grows faster than N. No headers, no builtins.
//   g++ -std=c++17 -fsyntax-only -ftime-report -DN=40000 -DSTORAGE=static Minimal.cc
//   g++ -std=c++17 -fsyntax-only -ftime-report -DN=40000 -DSTORAGE=       Minimal.cc
// With "static", "|name lookup" grows quadratically (determine_local_discriminator scans
// one list of all block-scope statics seen so far in the translation unit).
#ifndef N
#define N 10000
#endif
#ifndef STORAGE
#define STORAGE static
#endif

template<int K> int f() { STORAGE int v = K; return v; }

template<int Lo, int Hi> struct Range
{
    static int run()
    {
        if constexpr (Hi - Lo == 1)
            return f<Lo>();
        else
            return Range<Lo, (Lo + Hi) / 2>::run() + Range<(Lo + Hi) / 2, Hi>::run();
    }
};

int g() { return Range<0, N>::run(); }
