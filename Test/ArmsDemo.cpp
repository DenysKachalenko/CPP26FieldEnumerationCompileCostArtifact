// SPDX-License-Identifier: MIT
// Copyright 2026 Denys Kachalenko

#include <cstdio>
#include <optional>
#include <string>
#include <vector>

#include "RB/Enc.hpp"
#include "RB/Format.hpp"
#include "RB/GlazeArm.hpp"
#include "RB/P1061.hpp"
#include "RB/P1061Visit.hpp"
#include "RB/PfrArm.hpp"
#include "RB/Reflect.hpp"
#include "RB/ReflectArray.hpp"
#include "RB/ReflectIndex.hpp"
#include "RB/ReflectPlain.hpp"
#include "RB/ReflectSeq.hpp"
#include "RB/ReflectVisit.hpp"
#include "RB/RflArm.hpp"
#include "RB/XMacro.hpp"

namespace Demo
{
	struct FInner
	{
		RB::int32 P;
		float Q;
	};

	struct FRecord
	{
		RB::int32 A;
		std::string S;
		std::vector<RB::int32> Vec;
		std::optional<RB::int32> Opt;
		FInner Inner;
		bool bFlag;
	};

	inline void WriteManual(RB::FByteWriter& Writer, const FInner& V)
	{
		RB::Enc::Value(Writer, V.P);
		RB::Enc::Value(Writer, V.Q);
	}

	inline void WriteManual(RB::FByteWriter& Writer, const FRecord& V)
	{
		RB::Enc::Value(Writer, V.A);
		RB::Enc::Value(Writer, V.S);
		RB::Enc::Value(Writer, V.Vec);
		RB::Enc::Value(Writer, V.Opt);
		WriteManual(Writer, V.Inner);
		RB::Enc::Value(Writer, V.bFlag);
	}

	inline void WriteManualFInner(RB::FByteWriter& Writer, const FInner& V)
	{
		RB::Enc::Value(Writer, V.P);
		RB::Enc::Value(Writer, V.Q);
	}

	inline void WriteManualFRecord(RB::FByteWriter& Writer, const FRecord& V)
	{
		RB::Enc::Value(Writer, V.A);
		RB::Enc::Value(Writer, V.S);
		RB::Enc::Value(Writer, V.Vec);
		RB::Enc::Value(Writer, V.Opt);
		WriteManualFInner(Writer, V.Inner);
		RB::Enc::Value(Writer, V.bFlag);
	}

#define INNER_FIELDS(X) X(P) X(Q)
	RB_XM_SERIALIZER(FInner, INNER_FIELDS)

#define RECORD_FIELDS(X) X(A) X(S) X(Vec) X(Opt) X(Inner) X(bFlag)
	RB_XM_SERIALIZER(FRecord, RECORD_FIELDS)
}

namespace
{
	int Failures = 0;

	template<typename WriteFn>
	void Same(const char* Arm, const RB::FByteWriter& Ref, WriteFn&& Write)
	{
		RB::FByteWriter W;
		Write(W);
		if (W.Buffer != Ref.Buffer)
		{
			std::printf("MISMATCH %s (%zu vs %zu bytes)\n", Arm, W.Buffer.size(), Ref.Buffer.size());
			++Failures;
		}
	}
}

int main()
{
	const Demo::FRecord Record{1, "hi", {10, 20, 30}, 42, {7, 3.5f}, true};

	RB::FByteWriter Ref;
	Demo::WriteManualFRecord(Ref, Record);

	Same("reflect", Ref, [&](RB::FByteWriter& W) { RB::Reflect::Write(W, Record); });
	Same("reflect_plain", Ref, [&](RB::FByteWriter& W) { RB::ReflectPlain::Write(W, Record); });
	Same("reflect_visit", Ref, [&](RB::FByteWriter& W) { RB::ReflectVisit::Write(W, Record); });
	Same("reflect_array", Ref, [&](RB::FByteWriter& W) { RB::ReflectArray::Write(W, Record); });
	Same("reflect_index", Ref, [&](RB::FByteWriter& W) { RB::ReflectIndex::Write(W, Record); });
	Same("reflect_seq", Ref, [&](RB::FByteWriter& W) { RB::ReflectSeq::Write(W, Record); });
	Same("p1061", Ref, [&](RB::FByteWriter& W) { RB::P1061::Write(W, Record); });
	Same("p1061_visit", Ref, [&](RB::FByteWriter& W) { RB::P1061Visit::Write(W, Record); });
	Same("manual", Ref, [&](RB::FByteWriter& W) { Demo::WriteManual(W, Record); });
	Same("xmacro", Ref, [&](RB::FByteWriter& W) { Demo::WriteXMacro(W, Record); });
	Same("pfr", Ref, [&](RB::FByteWriter& W) { RB::Pfr::Write(W, Record); });
	Same("rflcpp", Ref, [&](RB::FByteWriter& W) { RB::Rfl::Write(W, Record); });
	Same("glaze", Ref, [&](RB::FByteWriter& W) { RB::Glaze::Write(W, Record); });

	if (Failures != 0)
	{
		std::printf("FAIL: %d arm(s) disagree\n", Failures);
		return 1;
	}
	std::printf("OK: 13 arms == manual_unique (%zu bytes, nested + containers)\n", Ref.Buffer.size());
	return 0;
}
