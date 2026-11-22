// SPDX-License-Identifier: MIT
// Copyright 2026 Denys Kachalenko

#pragma once

#include "RB/Enc.hpp"

// Minimal enumeration with C++26 structured-binding packs (P1061), no library:
// the language feature Boost.PFR's C++26 path is built on.
namespace RB::P1061
{
	template<typename Type>
	void Write(FByteWriter& Writer, const Type& V);

	struct FSelf
	{
		template<typename Type>
		static void Struct(FByteWriter& Writer, const Type& V)
		{
			P1061::Write(Writer, V);
		}
	};

	template<typename Type>
	void Write(FByteWriter& Writer, const Type& V)
	{
		const auto& [... Members] = V;
		(Enc::Any<FSelf>(Writer, Members), ...);
	}
}
