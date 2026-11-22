// SPDX-License-Identifier: MIT
// Copyright 2026 Denys Kachalenko

#pragma once

#include <optional>
#include <string>
#include <vector>

#include "RB/Annotations.hpp"
#include "RB/Format.hpp"

namespace RB
{

	enum class EColor : uint8
	{
		Red,
		Green,
		Blue
	};

	struct FVec3
	{
		float X;
		float Y;
		float Z;
	};

	struct FPlayer
	{
		uint32 Id;
		std::string Name;
		EColor Color;
		FVec3 Pos;
		std::vector<int32> Scores;
		std::optional<std::string> Clan;
		[[=FTransient{}]] uint64 Cache;
		bool bActive;
	};
}
