// SPDX-License-Identifier: MIT
// Copyright 2026 Denys Kachalenko

#pragma once

#include <meta>
#include <string>
#include <type_traits>

// Same includes as ReflectPlain.hpp, so the two arms parse the same headers.
#include "RB/Annotations.hpp"
#include "RB/Enc.hpp"

// The same expansion statement as ReflectPlain.hpp, over a constant array instead of the
// std::span that std::define_static_array returns (define_static_array itself is built on
// reflect_constant_array). GCC 16.2.0 expands a range of array type by destructuring, a
// range with begin/end iterator by iterating (cp/pt.cc, finish_expansion_stmt), so the two
// arms differ in how the expansion statement is lowered.
namespace RB::ReflectArray
{
	template<typename Type>
	void Write(FByteWriter& Writer, const Type& V);

	struct FSelf
	{
		template<typename Type>
		static void Struct(FByteWriter& Writer, const Type& V)
		{
			ReflectArray::Write(Writer, V);
		}
	};

	template<typename Type>
	void Write(FByteWriter& Writer, const Type& V)
	{
		constexpr auto Context = std::meta::access_context::unchecked();
		template for (constexpr auto Member : [:std::meta::reflect_constant_array(std::meta::nonstatic_data_members_of(^^Type, Context)):])
		{
			Enc::Any<FSelf>(Writer, V.[:Member:]);
		}
	}
}
