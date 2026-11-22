// SPDX-License-Identifier: MIT
// Copyright 2026 Denys Kachalenko

#pragma once

// The narrowest header that provides boost::pfr::for_each_field.
#include <boost/pfr/core.hpp>

#include "RB/Enc.hpp"

namespace RB::Pfr
{
	template<typename Type>
	void Write(FByteWriter& Writer, const Type& V);

	struct FSelf
	{
		template<typename Type>
		static void Struct(FByteWriter& Writer, const Type& V)
		{
			Pfr::Write(Writer, V);
		}
	};

	template<typename Type>
	void Write(FByteWriter& Writer, const Type& V)
	{
		boost::pfr::for_each_field(V, [&](const auto& Field) { Enc::Any<FSelf>(Writer, Field); });
	}
}
