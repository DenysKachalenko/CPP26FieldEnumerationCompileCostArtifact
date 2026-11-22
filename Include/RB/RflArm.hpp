// SPDX-License-Identifier: MIT
// Copyright 2026 Denys Kachalenko

#pragma once

// The narrowest header that provides rfl::to_view (not the rfl.hpp umbrella).
#include <rfl/to_view.hpp>

#include "RB/Enc.hpp"

namespace RB::Rfl
{
	template<typename Type>
	void Write(FByteWriter& Writer, const Type& V);

	struct FSelf
	{
		template<typename Type>
		static void Struct(FByteWriter& Writer, const Type& V)
		{
			Rfl::Write(Writer, V);
		}
	};

	template<typename Type>
	void Write(FByteWriter& Writer, const Type& V)
	{
		rfl::to_view(V).apply([&](const auto& Field) { Enc::Any<FSelf>(Writer, *Field.value()); });
	}
}
