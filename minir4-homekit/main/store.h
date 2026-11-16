/* SPDX-License-Identifier: GPL-3.0-or-later */
#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
bool hk_storage_init(void);
bool hk_storage_ready(void);
bool hk_storage_failed(void);
int hk_store_get(const char *part, const char *ns, const char *key, uint8_t *value, size_t *size);
int hk_store_set(const char *part, const char *ns, const char *key, const uint8_t *value, size_t size);
int hk_store_delete(const char *part, const char *ns, const char *key);
int hk_store_delete_namespace(const char *part, const char *ns);
bool hk_committed(const uint8_t hash[32]);
bool hk_set_commit(const uint8_t hash[32]);
bool hk_clear_commit(void);

/* Non-secret startup breadcrumb, confined to the private control namespace. */
uint8_t hk_boot_stage_read(void);
bool hk_boot_stage_write(uint8_t stage);
