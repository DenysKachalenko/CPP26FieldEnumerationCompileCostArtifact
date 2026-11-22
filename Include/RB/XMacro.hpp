// SPDX-License-Identifier: MIT
// Copyright 2026 Denys Kachalenko

#pragma once

#include "RB/Enc.hpp"

namespace RB::Xm
{
	// Nested structs go back through the overloaded WriteXMacro, found by ADL.
	struct FSelf
	{
		template<typename Type>
		static void Struct(FByteWriter& Writer, const Type& V)
		{
			WriteXMacro(Writer, V);
		}
	};

	template<typename Type>
	void Field(FByteWriter& Writer, const Type& V)
	{
		Enc::Any<FSelf>(Writer, V);
	}
}

#define RB_XM_FIELD(Name) RB::Xm::Field(Writer, V.Name);

// One serializer per type under a caller-chosen name. Nested non-leaf members
// recurse through the overloaded WriteXMacro, so a uniquely named serializer
// supports flat types only.
#define RB_XM_SERIALIZER_NAMED(Type, Name, FIELDS)           \
	inline void Name(RB::FByteWriter& Writer, const Type& V) \
	{                                                        \
		FIELDS(RB_XM_FIELD)                                  \
	}

#define RB_XM_SERIALIZER(Type, FIELDS) RB_XM_SERIALIZER_NAMED(Type, WriteXMacro, FIELDS)
