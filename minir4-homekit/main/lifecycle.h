/* SPDX-License-Identifier: GPL-3.0-or-later */
#pragma once
#include <stdbool.h>
#include <stdint.h>
bool hk_can_commit(bool paired,bool seen_on,bool seen_off,bool storage_failed);
bool hk_trial_expired(bool committed,uint32_t elapsed_ms);
