// SPDX-License-Identifier: MIT
// Copyright 2026 Denys Kachalenko

#pragma once

#include "RB/Enc.hpp"

// P1061 enumeration behind the callback API shape of boost::pfr::for_each_field,
// so it differs from P1061.hpp only in API shape.
namespace RB::P1061Visit
{
	template<typename Type, typename Callable>
	void ForEachField(const Type& V, Callable&& Func)
	{
		const auto& [... Members] = V;
		(Func(Members), ...);
	}

	template<typename Type>
	void Write(FByteWriter& Writer, const Type& V);

	struct FSelf
	{
		template<typename Type>
		static void Struct(FByteWriter& Writer, const Type& V)
		{
			P1061Visit::Write(Writer, V);
		}
	};

	template<typename Type>
	void Write(FByteWriter& Writer, const Type& V)
	{
		ForEachField(V, [&](const auto& Field) { Enc::Any<FSelf>(Writer, Field); });
	}
}
