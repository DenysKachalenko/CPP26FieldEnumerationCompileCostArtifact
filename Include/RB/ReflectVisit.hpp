// SPDX-License-Identifier: MIT
// Copyright 2026 Denys Kachalenko

#pragma once

#include <meta>
#include <string>
#include <type_traits>

// Same includes as ReflectPlain.hpp, so the two arms differ only in API shape.
#include "RB/Annotations.hpp"
#include "RB/Enc.hpp"

// Native P2996 enumeration behind the callback API shape of
// boost::pfr::for_each_field: the serializer passes a generic lambda per type.
namespace RB::ReflectVisit
{
	template<typename Type, typename Callable>
	void ForEachField(const Type& V, Callable&& Func)
	{
		constexpr auto Context = std::meta::access_context::unchecked();
		template for (constexpr auto Member : std::define_static_array(std::meta::nonstatic_data_members_of(^^Type, Context)))
		{
			Func(V.[:Member:]);
		}
	}

	template<typename Type>
	void Write(FByteWriter& Writer, const Type& V);

	struct FSelf
	{
		template<typename Type>
		static void Struct(FByteWriter& Writer, const Type& V)
		{
			ReflectVisit::Write(Writer, V);
		}
	};

	template<typename Type>
	void Write(FByteWriter& Writer, const Type& V)
	{
		ForEachField(V, [&](const auto& Field) { Enc::Any<FSelf>(Writer, Field); });
	}
}
