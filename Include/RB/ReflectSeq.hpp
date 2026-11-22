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

// Native P2996 enumeration without an expansion statement or a structured-binding pack:
// a C++20 index-sequence helper splices each member of a static member array.
namespace RB::ReflectSeq
{
	template<typename Type>
	constexpr auto Members = std::define_static_array(
		std::meta::nonstatic_data_members_of(^^Type, std::meta::access_context::unchecked()));

	template<typename Type>
	void Write(FByteWriter& Writer, const Type& V);

	struct FSelf
	{
		template<typename Type>
		static void Struct(FByteWriter& Writer, const Type& V)
		{
			ReflectSeq::Write(Writer, V);
		}
	};

	template<typename Type, std::size_t... I>
	void WriteMembers(FByteWriter& Writer, const Type& V, std::index_sequence<I...>)
	{
		(Enc::Any<FSelf>(Writer, V.[:Members<Type>[I]:]), ...);
	}

	template<typename Type>
	void Write(FByteWriter& Writer, const Type& V)
	{
		ReflectSeq::WriteMembers(Writer, V, std::make_index_sequence<Members<Type>.size()>());
	}
}
