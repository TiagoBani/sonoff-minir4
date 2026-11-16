/* SPDX-License-Identifier: GPL-3.0-or-later */
#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#define HK_PARTITION "reserve"
#define HK_CONTROL_NS "minir4_ctl"
#define HK_OWNER "minir4-hk-v1"
/* 1 = blank, 2 = valid written ownership marker, 0 = refuse. */
int hk_storage_classify(const uint8_t *data, size_t size);
bool hk_namespace_allowed(const char *partition, const char *name_space, bool write);
