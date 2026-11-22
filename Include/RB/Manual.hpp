// SPDX-License-Identifier: MIT
// Copyright 2026 Denys Kachalenko

#pragma once

#include "RB/Corpus.hpp"
#include "RB/Enc.hpp"

namespace RB::Manual
{
	inline void Write(FByteWriter& Writer, const FVec3& V)
	{
		Enc::Value(Writer, V.X);
		Enc::Value(Writer, V.Y);
		Enc::Value(Writer, V.Z);
	}

	inline void Write(FByteWriter& Writer, const FPlayer& V)
	{
		Enc::Value(Writer, V.Id);
		Enc::Value(Writer, V.Name);
		Enc::Value(Writer, V.Color);
		Write(Writer, V.Pos);
		Enc::Value(Writer, V.Scores);
		Enc::Value(Writer, V.Clan);

		Enc::Value(Writer, V.bActive);
	}
}
