/* SPDX-License-Identifier: GPL-3.0-or-later */
#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define MINIR4_PAIR_INFO_SIZE 176

/* Output is cleared on failure. Values are never logged or persisted here. */
bool minir4_decode_pair_wifi(const uint8_t *blob, size_t length,
                             uint8_t ssid[32], uint8_t password[64]);
