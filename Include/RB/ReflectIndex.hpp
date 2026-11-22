// SPDX-License-Identifier: MIT
// Copyright 2026 Denys Kachalenko

#pragma once

#include <meta>
#include <string>
#include <type_traits>

// Same includes as ReflectPlain.hpp, so the two arms parse the same headers and differ only
// in how the members are iterated. (std::make_index_sequence comes from <bits/utility.h>,
// which these headers already include; <utility> itself would add headers to the parse.)
#include "RB/Annotations.hpp"
#include "RB/Enc.hpp"

// Native P2996 enumeration without an expansion statement: the members are spliced through
// a pack of indices, a P1061 structured-binding pack bound from std::make_index_sequence
// through the tuple protocol of std::integer_sequence (one get<j> per element). This is the
// form of reflect-cpp's C++26 path (rfl::internal::cpp26::bind_to_tuple).
namespace RB::ReflectIndex
{
	template<typename Type>
	void Write(FByteWriter& Writer, const Type& V);

	struct FSelf
	{
		template<typename Type>
		static void Struct(FByteWriter& Writer, const Type& V)
		{
			ReflectIndex::Write(Writer, V);
		}
	};

	template<typename Type>
	void Write(FByteWriter& Writer, const Type& V)
	{
		constexpr auto Context = std::meta::access_context::unchecked();
		constexpr auto Members = std::define_static_array(std::meta::nonstatic_data_members_of(^^Type, Context));
		constexpr auto [... I] = std::make_index_sequence<Members.size()>();
		(Enc::Any<FSelf>(Writer, V.[:Members[I]:]), ...);
	}
}
