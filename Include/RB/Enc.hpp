// SPDX-License-Identifier: MIT
// Copyright 2026 Denys Kachalenko

#pragma once

#include <optional>
#include <string>
#include <type_traits>
#include <vector>

#include "RB/Format.hpp"

// The shared value encoder every arm routes each field through, so all arms emit the
// same bytes. A non-leaf value (a nested struct, or the element of a vector or optional
// of structs) is handed back to the arm through its Self::Struct.
namespace RB::Enc
{
	template<typename>
	inline constexpr bool bIsVector = false;
	template<typename ElementType, typename AllocatorType>
	inline constexpr bool bIsVector<std::vector<ElementType, AllocatorType>> = true;

	template<typename>
	inline constexpr bool bIsOptional = false;
	template<typename Type>
	inline constexpr bool bIsOptional<std::optional<Type>> = true;

	template<typename Type>
	concept Leaf = std::is_arithmetic_v<Type> || std::is_enum_v<Type> || std::is_same_v<Type, std::string> || bIsVector<Type> || bIsOptional<Type>;

	// Self for callers that only ever encode leaves.
	struct FLeafOnly
	{
		template<typename Type>
		static void Struct(FByteWriter&, const Type&)
		{
			static_assert(AlwaysFalse<Type>, "Enc: a nested struct needs the arm's Struct writer");
		}
	};

	template<typename Self, typename Type>
	void Any(FByteWriter& Writer, const Type& V)
	{
		if constexpr (std::is_same_v<Type, std::string>)
		{
			Writer.PutString(V);
		}
		else if constexpr (std::is_enum_v<Type>)
		{
			Writer.PutScalar(static_cast<std::underlying_type_t<Type>>(V));
		}
		else if constexpr (std::is_arithmetic_v<Type>)
		{
			Writer.PutScalar(V);
		}
		else if constexpr (bIsVector<Type>)
		{
			Writer.PutU64(V.size());
			for (const auto& Element : V)
			{
				Any<Self>(Writer, Element);
			}
		}
		else if constexpr (bIsOptional<Type>)
		{
			Writer.PutU8(V.has_value() ? 1 : 0);
			if (V)
			{
				Any<Self>(Writer, *V);
			}
		}
		else
		{
			Self::Struct(Writer, V);
		}
	}

	template<typename Type>
	void Value(FByteWriter& Writer, const Type& V)
	{
		Any<FLeafOnly>(Writer, V);
	}
}
