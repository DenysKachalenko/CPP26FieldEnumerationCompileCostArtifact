#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
#
# Build GCC 16.2.0 for the measurement campaign, with recorded provenance.
# Run from an MSYS2 UCRT64 shell:   bash build_gcc.sh
# (from Git Bash: C:/msys64/usr/bin/env.exe MSYSTEM=UCRT64 /usr/bin/bash -lc "bash <this file>")
#
# Procedure: the one proven on this machine for every GCC built here
# (E:/PryzmaEngine/Ideas/GccBuildGuide.md, and gccd's gcc-builds/build_all.sh and
# install_staged.sh, which built 11.5-15.3 with it):
# - the two /mingw/include source patches, with match counts (sed exits 0 on no match);
# - the MinGW CRT in $PREFIX/x86_64-w64-mingw32/lib before make (the target libraries link
#   with -B$PREFIX/x86_64-w64-mingw32/lib/);
# - make -j4 MAKEINFO=true (-j8 ran out of memory; texinfo 7.2 cannot build the docs);
# - install through a DESTDIR stage (a plain install wrote '//home/...' UNC paths on 13/14).
# The configure options are exactly those of the GCC 16.1.0 used so far (its `g++ -v`), with
# a different prefix. Both compilers are non-bootstrapped builds by the same MSYS2 host GCC,
# so a 16.1-vs-16.2 comparison does not mix in a difference in how cc1plus was built.
#
# Parity with the GCC 16.1.0 install:
# - 16.1.0's prefix carries a copy of /ucrt64/include, and that copy is where it finds the
#   MinGW headers (its include search list has no /ucrt64 entry). The same copy goes into this
#   prefix, so both compilers resolve each system header at the same search position.
# - 16.1.0's 13 launch executables are stripped, with the DWARF in a sibling .debug file and
#   a .gnu_debuglink (gccd's Tools/StripToolchain.sh). The same is done here, the same way.
#
# Do NOT run `pacman -Syu` before this build: it would move the host compiler off
# MSYS2 GCC 15.2.0 Rev11 and so change how cc1plus is compiled relative to 16.1.0.
#
# Re-running after a success is a no-op (PROVENANCE.txt exists). After a failure it starts
# over from a fresh build directory and prefix (both belong to this script alone).
set -euo pipefail

VER=16.2.0
ROOT=${ROOT:-/home/kacha/gcc-builds}
PREFIX=${PREFIX:-/home/kacha/gcc-${VER}-install}
REFERENCE=${REFERENCE:-/home/kacha/gcc-16-install}   # the GCC 16.1.0 this build must match
JOBS=${JOBS:-4}
BASE=https://gcc.gnu.org/pub/gcc/releases/gcc-${VER}
SHA512=c51c30ca7422d0cbecf504b2e0f33c3aca31e0f90a76b65217f465163fa6fa17b3f5de39e145c47e5bab90ac0ce7fff3b03c8d553ae36e01faaea5a50f8648d1
# Release signing (sub)key listed in ResearchRefresh.md (GCC 16.2.0 tarball signature).
GPG_KEY=7F74F97C103468EE5D750B583AB00996FC26A641
# The host compiler that built GCC 16.1.0's cc1plus (its .comment strings say so).
EXPECTED_HOST="gcc.exe (Rev11, Built by MSYS2 project) 15.2.0"
CRT_OBJECTS=(dllcrt2.o crt2.o crtbegin.o crtend.o)
CRT_LIBRARIES=(libmingw32.a libmingwex.a libmingwthrd.a libmoldname.a libmsvcrt.a libkernel32.a
               libadvapi32.a libshell32.a libuser32.a libpthread.a libucrt.a libucrtbase.a)

SRC=${ROOT}/src-${VER}
BLD=${ROOT}/build-${VER}
STAGE=${ROOT}/stage-${VER}
LOG=${ROOT}/${VER}.log
STATUS=${ROOT}/${VER}.status.log
LIBEXEC_REL=libexec/gcc/x86_64-w64-mingw32/${VER}
mkdir -p "${ROOT}"
cd "${ROOT}"

stamp() { echo "=== $1 $(date -Iseconds)" | tee -a "${STATUS}"; }
fail() { stamp "FAIL: $1"; exit 1; }

if [ -f "${PREFIX}/PROVENANCE.txt" ]; then
	echo "GCC ${VER} already built: ${PREFIX}/PROVENANCE.txt"
	exit 0
fi

[ "${MSYSTEM:-}" = UCRT64 ] || fail "run in an MSYS2 UCRT64 shell (MSYSTEM=${MSYSTEM:-unset})"
[ "$(command -v gcc)" = /ucrt64/bin/gcc ] || fail "gcc resolves to $(command -v gcc), not /ucrt64/bin/gcc"
host=$(gcc --version | head -1)
[ "${host}" = "${EXPECTED_HOST}" ] || fail "host compiler is '${host}', expected '${EXPECTED_HOST}'"
[ -x "${REFERENCE}/bin/g++.exe" ] || fail "reference GCC 16.1.0 not found at ${REFERENCE}"
command -v gpg >/dev/null 2>&1 || fail "gpg not found (pacman -S gnupg)"
stamp "${VER} start (host ${host}, -j${JOBS})"

# 1. Source: the official release tarball, checked against the pinned and the published
#    sha512 and against the release signature.
if ! echo "${SHA512}  gcc-${VER}.tar.xz" | sha512sum -c --status - 2>/dev/null; then
	rm -f "gcc-${VER}.tar.xz"
	curl -fL --retry 5 --retry-delay 30 -o "gcc-${VER}.tar.xz" "${BASE}/gcc-${VER}.tar.xz"
fi
echo "${SHA512}  gcc-${VER}.tar.xz" | sha512sum -c - || fail "tarball sha512 mismatch"
curl -fsL --retry 5 --retry-delay 30 "${BASE}/sha512.sum" | grep -q "${SHA512}  gcc-${VER}.tar.xz" \
	|| fail "pinned sha512 does not match the published sha512.sum"
curl -fsL --retry 5 --retry-delay 30 -o "gcc-${VER}.tar.xz.sig" "${BASE}/gcc-${VER}.tar.xz.sig"
gpg --batch --list-keys "${GPG_KEY}" >/dev/null 2>&1 \
	|| gpg --batch --keyserver hkps://keyserver.ubuntu.com --recv-keys "${GPG_KEY}" >/dev/null 2>&1 || true
GPG_OUT=$(gpg --batch --status-fd 1 --verify "gcc-${VER}.tar.xz.sig" "gcc-${VER}.tar.xz" 2>/dev/null || true)
grep -q "VALIDSIG ${GPG_KEY}" <<<"${GPG_OUT}" || { echo "${GPG_OUT}"; fail "no valid signature by ${GPG_KEY}"; }
echo "GPG: signature by ${GPG_KEY} verified"

# 2. A fresh source tree with the two header-path patches, each counted.
rm -rf "${SRC}"
mkdir -p "${SRC}"
stamp "${VER} unpack"
tar -xf "gcc-${VER}.tar.xz" -C "${SRC}" --strip-components=1
[ "$(cat "${SRC}/gcc/BASE-VER")" = "${VER}" ] || fail "BASE-VER is $(cat "${SRC}/gcc/BASE-VER")"
MINGW_H="${SRC}/gcc/config/mingw/mingw32.h"
sed -i 's|native_system_header_dir=/mingw/include|native_system_header_dir=/ucrt64/include|g' "${SRC}/gcc/config.gcc"
sed -i 's|#define NATIVE_SYSTEM_HEADER_DIR "/mingw/include"|#define NATIVE_SYSTEM_HEADER_DIR "C:/msys64/ucrt64/include"|' "${MINGW_H}"
OLD_GCC=$(grep -c 'native_system_header_dir=/mingw/include' "${SRC}/gcc/config.gcc" || true)
NEW_GCC=$(grep -c 'native_system_header_dir=/ucrt64/include' "${SRC}/gcc/config.gcc" || true)
NEW_H=$(grep -c '#define NATIVE_SYSTEM_HEADER_DIR "C:/msys64/ucrt64/include"' "${MINGW_H}" || true)
echo "patch counts: config.gcc old=${OLD_GCC} new=${NEW_GCC}; mingw32.h new=${NEW_H}" | tee -a "${STATUS}"
[ "${OLD_GCC}" -eq 0 ] && [ "${NEW_GCC}" -ge 1 ] && [ "${NEW_H}" -eq 1 ] || fail "patch counts"

# 3. A fresh prefix holding the MinGW CRT, and a fresh build directory.
rm -rf "${PREFIX}" "${BLD}" "${STAGE}"
mkdir -p "${PREFIX}/x86_64-w64-mingw32/lib" "${BLD}"
for f in "${CRT_OBJECTS[@]}" "${CRT_LIBRARIES[@]}"; do
	cp "/ucrt64/lib/${f}" "${PREFIX}/x86_64-w64-mingw32/lib/"
done

# 4. Configure and build, same options as GCC 16.1.0. configure is called through a
#    RELATIVE path, as every build on this machine did (16.1.0: ../source/configure): with
#    an absolute MSYS path the native generator programs get '/home/...' file names they
#    cannot open (gengtype: "/home/.../libcpp/include/line-map.h: No such file").
cd "${BLD}"
: > "${LOG}"
stamp "${VER} configure"
"../src-${VER}/configure" --prefix="${PREFIX}" \
	--with-native-system-header-dir=/ucrt64/include --with-local-prefix=/ucrt64/local \
	--build=x86_64-w64-mingw32 --host=x86_64-w64-mingw32 --target=x86_64-w64-mingw32 \
	--enable-languages=c,c++ --enable-threads=mcf --enable-shared --enable-static \
	--enable-lto --enable-plugin --enable-checking=release --disable-multilib \
	--disable-nls --disable-werror --disable-bootstrap --with-tune=native \
	--with-system-zlib --with-zstd >>"${LOG}" 2>&1 || fail "configure (see ${LOG})"
stamp "${VER} make -j${JOBS}"
make -j"${JOBS}" MAKEINFO=true >>"${LOG}" 2>&1 || fail "make (see ${LOG})"
if grep -qE '^Cannot compile std(\.compat)? module' "${LOG}"; then
	fail "libstdc++ could not compile the std module (see ${LOG})"
fi

# 5. Install through a stage, add the CRT, check that the staged compiler runs, swap it in.
stamp "${VER} install (staged)"
make install DESTDIR="${STAGE}" MAKEINFO=true >"${ROOT}/${VER}.install.log" 2>&1 \
	|| fail "staged install (see ${ROOT}/${VER}.install.log)"
STAGED="${STAGE}${PREFIX}"
mkdir -p "${STAGED}/x86_64-w64-mingw32/lib"
for f in "${CRT_OBJECTS[@]}" "${CRT_LIBRARIES[@]}"; do
	cp "/ucrt64/lib/${f}" "${STAGED}/x86_64-w64-mingw32/lib/"
done
[ "$("${STAGED}/bin/gcc" -dumpfullversion)" = "${VER}" ] || fail "the staged compiler does not run"
rm -rf "${PREFIX}"
mv "${STAGED}" "${PREFIX}"
rm -rf "${STAGE}"

# 6. The /ucrt64/include copy that GCC 16.1.0's prefix carries (no-clobber: GCC's own files win).
cp -rn /ucrt64/include/. "${PREFIX}/include/"

# 7. Strip the 13 launch executables exactly as gccd's Tools/StripToolchain.sh stripped 16.1.0:
#    DWARF into <name>.debug, a .gnu_debuglink to it, the PE timestamp and mtime kept.
STRIP_TARGETS=("${LIBEXEC_REL}/"{cc1,cc1plus,lto1,lto-wrapper,collect2}.exe
               bin/{gcc,g++,c++,cpp}.exe
               "bin/x86_64-w64-mingw32-"{gcc,"gcc-${VER}",g++,c++}.exe)
for rel in "${STRIP_TARGETS[@]}"; do
	exe="${PREFIX}/${rel}"
	dbg="${exe%.exe}.debug"
	[ -f "${exe}" ] || fail "missing ${exe}"
	header=$(od -An -t u4 -j 60 -N 4 "${exe}" | tr -d ' ')
	export SOURCE_DATE_EPOCH=$(od -An -t u4 -j $((header + 8)) -N 4 "${exe}" | tr -d ' ')
	objcopy --only-keep-debug "${exe}" "${dbg}"
	(cd "$(dirname "${exe}")" && objcopy --strip-debug --add-gnu-debuglink="$(basename "${dbg}")" \
		"$(basename "${exe}")" "$(basename "${exe}").stripped")
	touch -r "${exe}" "${exe}.stripped" "${dbg}"
	mv -f "${exe}.stripped" "${exe}"
done
unset SOURCE_DATE_EPOCH
stamp "${VER} stripped ${#STRIP_TARGETS[@]} executables"

# 8. Checks that must all hold (GccBuildGuide.md update step 11, plus parity with 16.1.0).
CC1PLUS="${PREFIX}/${LIBEXEC_REL}/cc1plus.exe"
[ "$("${PREFIX}/bin/g++.exe" -dumpfullversion)" = "${VER}" ] || fail "g++ -dumpfullversion"
[ "$(grep -c activeCodePage "${CC1PLUS}")" -ge 1 ] || fail "cc1plus has no UTF-8 manifest"
[ "$(grep -c activeCodePage "${PREFIX}/bin/g++.exe")" -ge 1 ] || fail "g++ has no UTF-8 manifest"
test -s "${PREFIX}/include/c++/${VER}/bits/std.cc" || fail "bits/std.cc missing"
test -s "${PREFIX}/include/c++/${VER}/meta" || fail "<meta> missing"
search_list() { echo | "$1" -E -x c++ - -v 2>&1 | tr -d '\r' | sed -n '/search starts here/,/End of search/p'; }
SEARCH=$(search_list "${PREFIX}/bin/g++.exe")
echo "${SEARCH}"
grep -q "/gcc-${VER}-install/lib/gcc/x86_64-w64-mingw32/${VER}/../../../../include\$" <<<"${SEARCH}" \
	|| fail "the prefix include directory is not on the search list"
probe=$(mktemp -d)
cat > "${probe}/reflect.cpp" <<'EOF'
#include <meta>
#include <cstdio>
#include <string>
struct Player { std::string Name; int Health; float Speed; };
int main()
{
	static constexpr auto Members = std::define_static_array(
		std::meta::nonstatic_data_members_of(^^Player, std::meta::access_context::unchecked()));
	constexpr std::size_t Count = Members.size();
	std::printf("%zu\n", Count);
}
EOF
PATH=/ucrt64/bin:${PATH} "${PREFIX}/bin/g++.exe" -std=c++26 -freflection -BC:/msys64/ucrt64/bin/ -static-libstdc++ \
	-static-libgcc "${probe}/reflect.cpp" -o "${probe}/reflect.exe" || fail "reflection test does not compile"
[ "$("${probe}/reflect.exe" | tr -d '\r')" = 3 ] || fail "reflection test does not print 3"
# Every system header of that test resolves to the same file, relative to its own prefix,
# under 16.1.0 and 16.2.0 (libstdc++'s and GCC's own headers aside, which carry the version).
deps() {
	"$1" -std=c++26 -freflection -BC:/msys64/ucrt64/bin/ -M "${probe}/reflect.cpp" 2>/dev/null | tr -d '\r' \
		| tr ' \\' '\n\n' | sed -n "s|^.*/gcc-$2-install/||p" \
		| sed -E 's|^lib/gcc/x86_64-w64-mingw32/[^/]+/\.\./\.\./\.\./\.\./||' \
		| grep -v "^include/c++/\|^lib/gcc/" | sort -u
}
diff <(deps "${REFERENCE}/bin/g++.exe" 16) <(deps "${PREFIX}/bin/g++.exe" "${VER}") \
	|| fail "MinGW headers resolve differently from 16.1.0"
[ -n "$(deps "${PREFIX}/bin/g++.exe" "${VER}")" ] || fail "no MinGW header resolved from the prefix"
rm -rf "${probe}"
stamp "${VER} checks passed"

# 9. Provenance, next to the installed compiler.
{
	echo "GCC ${VER} built $(date -Iseconds)"
	echo "procedure: Harness/build_gcc.sh (GccBuildGuide.md patches 1-2, CRT in prefix, -j${JOBS} MAKEINFO=true, staged install)"
	echo "source: ${BASE}/gcc-${VER}.tar.xz"
	echo "sha512: ${SHA512}"
	echo "sha256: $(sha256sum "${ROOT}/gcc-${VER}.tar.xz" | cut -d' ' -f1)"
	echo "gpg status:"; echo "${GPG_OUT}"
	echo
	"${PREFIX}/bin/g++.exe" -v 2>&1
	echo
	echo "include search list:"; echo "${SEARCH}"
	echo
	echo "host compiler: ${host}"; gcc -v 2>&1 | tail -3
	echo
	echo "host packages:"
	pacman -Q mingw-w64-ucrt-x86_64-gcc mingw-w64-ucrt-x86_64-binutils \
		mingw-w64-ucrt-x86_64-headers mingw-w64-ucrt-x86_64-crt mingw-w64-ucrt-x86_64-gmp \
		mingw-w64-ucrt-x86_64-mpfr mingw-w64-ucrt-x86_64-mpc mingw-w64-ucrt-x86_64-isl \
		mingw-w64-ucrt-x86_64-zlib mingw-w64-ucrt-x86_64-zstd
	echo
	echo "CFLAGS/CXXFLAGS used for the compiler itself (configure defaults unless set): ${CFLAGS:-default} / ${CXXFLAGS:-default}"
	echo "uname: $(uname -a)"
	echo
	echo "binaries (sha256, bytes) after the debug split:"
	for f in "${PREFIX}/bin/g++.exe" "${CC1PLUS}"; do
		echo "$(sha256sum "${f}" | cut -d' ' -f1)  $(stat -c %s "${f}")  ${f}"
	done
	echo
	echo "compiler that built cc1plus (from its .comment strings):"
	strings "${CC1PLUS}" | grep -m3 'GCC: (' || true
} > "${PREFIX}/PROVENANCE.txt"
stamp "${VER} done: ${PREFIX}/PROVENANCE.txt"
