// SPDX-License-Identifier: MIT
// Copyright 2026 Denys Kachalenko

#pragma once

// The narrowest header that provides glz::for_each_field (not the glaze.hpp umbrella).
#include <glaze/core/reflect.hpp>

#include "RB/Enc.hpp"

namespace RB::Glaze
{
	template<typename Type>
	void Write(FByteWriter& Writer, const Type& V);

	struct FSelf
	{
		template<typename Type>
		static void Struct(FByteWriter& Writer, const Type& V)
		{
			Glaze::Write(Writer, V);
		}
	};

	template<typename Type>
	void Write(FByteWriter& Writer, const Type& V)
	{
		glz::for_each_field(V, [&](const auto& Field) { Enc::Any<FSelf>(Writer, Field); });
	}
}
