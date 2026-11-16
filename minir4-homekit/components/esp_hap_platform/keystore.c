/* SPDX-License-Identifier: GPL-3.0-or-later
 * Replacement for the SDK keystore; no default-NVS fallback or partition erase.
 */
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include "store.h"
#include "store_policy.h"
char *hap_platform_keystore_get_nvs_partition_name(void){return HK_PARTITION;}
char *hap_platform_keystore_get_factory_nvs_partition_name(void){return HK_PARTITION;}
int hap_platform_keystore_init_partition(const char *part,bool read_only)
{
    (void)read_only;
    return part && !strcmp(part,HK_PARTITION) && hk_storage_ready() ? 0 : -1;
}
int hap_platform_keystore_get(const char *part,const char *ns,const char *key,uint8_t *val,size_t *size)
{return hk_store_get(part,ns,key,val,size);}
int hap_platform_keystore_set(const char *part,const char *ns,const char *key,const uint8_t *val,size_t size)
{return hk_store_set(part,ns,key,val,size);}
int hap_platform_keystore_delete(const char *part,const char *ns,const char *key)
{return hk_store_delete(part,ns,key);}
int hap_platform_keystore_delete_namespace(const char *part,const char *ns)
{return hk_store_delete_namespace(part,ns);}
int hap_platfrom_keystore_erase_partition(const char *part)
{(void)part;return -1;}
