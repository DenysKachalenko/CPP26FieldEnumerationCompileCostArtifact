// SPDX-License-Identifier: MIT
// Copyright 2026 Denys Kachalenko

#pragma once

#include <meta>
#include <string>
#include <type_traits>

// Same includes as Reflect.hpp, so the two arms differ only in the P3394 query.
#include "RB/Annotations.hpp"
#include "RB/Enc.hpp"

namespace RB::ReflectPlain
{
	template<typename Type>
	void Write(FByteWriter& Writer, const Type& V);

	struct FSelf
	{
		template<typename Type>
		static void Struct(FByteWriter& Writer, const Type& V)
		{
			ReflectPlain::Write(Writer, V);
		}
	};

	template<typename Type>
	void Write(FByteWriter& Writer, const Type& V)
	{
		constexpr auto Context = std::meta::access_context::unchecked();
		template for (constexpr auto Member : std::define_static_array(std::meta::nonstatic_data_members_of(^^Type, Context)))
		{
			Enc::Any<FSelf>(Writer, V.[:Member:]);
		}
	}
}
