// SPDX-License-Identifier: MIT
// Copyright 2026 Denys Kachalenko

#pragma once

#include <bit>
#include <cstddef>
#include <cstdint>
#include <string>
#include <string_view>
#include <type_traits>
#include <vector>

namespace RB
{
	using int32 = std::int32_t;
	using int64 = std::int64_t;
	using uint8 = std::uint8_t;
	using uint16 = std::uint16_t;
	using uint32 = std::uint32_t;
	using uint64 = std::uint64_t;
	using byte = std::byte;

	template<typename Type>
	inline constexpr bool AlwaysFalse = false;

	struct FByteWriter
	{
		std::vector<byte> Buffer;

		void PutBytes(const void* Data, int64 Size)
		{
			const byte* Bytes = static_cast<const byte*>(Data);
			Buffer.insert(Buffer.end(), Bytes, Bytes + Size);
		}

		void PutU8(uint8 Value)
		{
			Buffer.push_back(byte{Value});
		}

		template<typename UnsignedType>
			requires std::is_unsigned_v<UnsignedType>
		void PutUIntLE(UnsignedType Value)
		{
			for (int32 Index = 0; Index < static_cast<int32>(sizeof(UnsignedType)); ++Index)
			{
				Buffer.push_back(byte(static_cast<uint8>(Value >> (8 * Index))));
			}
		}

		void PutU64(uint64 Value)
		{
			PutUIntLE(Value);
		}

		template<typename Type>
		void PutScalar(const Type& Value)
		{
			if constexpr (std::is_same_v<Type, bool>)
			{
				PutU8(Value ? 1 : 0);
			}
			else if constexpr (std::is_integral_v<Type>)
			{
				PutUIntLE(static_cast<std::make_unsigned_t<Type>>(Value));
			}
			else if constexpr (std::is_floating_point_v<Type>)
			{
				if constexpr (sizeof(Type) == 4)
				{
					PutUIntLE(std::bit_cast<uint32>(Value));
				}
				else if constexpr (sizeof(Type) == 8)
				{
					PutUIntLE(std::bit_cast<uint64>(Value));
				}
				else
				{
					static_assert(AlwaysFalse<Type>, "Unsupported floating-point width");
				}
			}
			else
			{
				static_assert(AlwaysFalse<Type>, "PutScalar: non-arithmetic type");
			}
		}

		void PutString(std::string_view String)
		{
			PutU64(String.size());
			PutBytes(String.data(), static_cast<int64>(String.size()));
		}
	};
}
