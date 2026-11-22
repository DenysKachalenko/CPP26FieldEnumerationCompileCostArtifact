// SPDX-License-Identifier: MIT
// Copyright 2026 Denys Kachalenko

#pragma once

#include <meta>
#include <string>
#include <type_traits>

#include "RB/Annotations.hpp"
#include "RB/Enc.hpp"

namespace RB::Reflect
{
	consteval bool IsTransient(std::meta::info Member)
	{
		return !std::meta::annotations_of_with_type(Member, ^^RB::FTransient).empty();
	}

	template<typename Type>
	void Write(FByteWriter& Writer, const Type& V);

	// Nested structs, also inside vectors and optionals, recurse into Write.
	struct FSelf
	{
		template<typename Type>
		static void Struct(FByteWriter& Writer, const Type& V)
		{
			Reflect::Write(Writer, V);
		}
	};

	template<typename Type>
	void Write(FByteWriter& Writer, const Type& V)
	{
		constexpr auto Context = std::meta::access_context::unchecked();
		template for (constexpr auto Member : std::define_static_array(std::meta::nonstatic_data_members_of(^^Type, Context)))
		{
			if constexpr (!IsTransient(Member))
			{
				Enc::Any<FSelf>(Writer, V.[:Member:]);
			}
		}
	}
}
