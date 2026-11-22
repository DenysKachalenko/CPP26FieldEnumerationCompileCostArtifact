// SPDX-License-Identifier: MIT
// Copyright 2026 Denys Kachalenko

#include <cstdio>
#include <optional>
#include <string>
#include <vector>

#include "RB/Corpus.hpp"
#include "RB/Format.hpp"
#include "RB/Manual.hpp"
#include "RB/Reflect.hpp"

int main()
{
	RB::FPlayer Player{
		.Id = 42,
		.Name = "Alice",
		.Color = RB::EColor::Green,
		.Pos = {1.0f, 2.0f, 3.5f},
		.Scores = {10, 20, 30},
		.Clan = std::optional<std::string>{"Knights"},
		.Cache = 999,
		.bActive = true,
	};

	RB::FByteWriter A;
	RB::FByteWriter B;
	RB::Reflect::Write(A, Player);
	RB::Manual::Write(B, Player);

	if (A.Buffer != B.Buffer)
	{
		std::printf("MISMATCH: reflect=%zu bytes, manual=%zu bytes\n", A.Buffer.size(), B.Buffer.size());
		return 1;
	}

	std::printf("OK: reflect == manual, %zu bytes\n", A.Buffer.size());
	return 0;
}
