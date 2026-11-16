/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "store.h"
#include "store_policy.h"
#include <stdlib.h>
#include <string.h>
#include "esp_partition.h"
#include "nvs.h"
#include "nvs_flash.h"

static bool ready, failed;
static int write_result(esp_err_t result)
{
    if(result!=ESP_OK) failed=true;
    return result==ESP_OK ? 0 : -1;
}

bool hk_storage_ready(void){return ready;}
bool hk_storage_failed(void){return failed;}

bool hk_storage_init(void)
{
    if(ready) return true;
    const esp_partition_t *p=esp_partition_find_first(ESP_PARTITION_TYPE_DATA,ESP_PARTITION_SUBTYPE_DATA_NVS,HK_PARTITION);
    if(!p || p->address!=0x19000 || p->size!=0x4000 || p->encrypted) return false;
    uint8_t *data=malloc(p->size);
    if(!data) return false;
    int classification=0;
    if(esp_partition_read(p,0,data,p->size)==ESP_OK) classification=hk_storage_classify(data,p->size);
    free(data);
    if(!classification) return false;
    /* Do not erase on full/new-version/error. Unknown existing contents never reach init. */
    if(nvs_flash_init_partition(HK_PARTITION)!=ESP_OK) return false;
    nvs_handle_t handle;
    if(nvs_open_from_partition(HK_PARTITION,HK_CONTROL_NS,
                              classification==1 ? NVS_READWRITE : NVS_READONLY,&handle)!=ESP_OK) return false;
    esp_err_t err;
    if(classification==1) {
        err=nvs_set_str(handle,"owner",HK_OWNER);
        if(err==ESP_OK) err=nvs_commit(handle);
    } else {
        char owner[sizeof(HK_OWNER)]; size_t length=sizeof(owner);
        err=nvs_get_str(handle,"owner",owner,&length);
        if(err==ESP_OK && (length!=sizeof(owner) || memcmp(owner,HK_OWNER,sizeof(owner)))) err=ESP_FAIL;
    }
    nvs_close(handle);
    ready=err==ESP_OK;
    return ready;
}

int hk_store_get(const char *part,const char *ns,const char *key,uint8_t *value,size_t *size)
{
    if(!ready || !key || !size || !hk_namespace_allowed(part,ns,false)) return -1;
    nvs_handle_t h;
    if(nvs_open_from_partition(HK_PARTITION,ns,NVS_READONLY,&h)!=ESP_OK) return -1;
    esp_err_t err=nvs_get_blob(h,key,value,size); nvs_close(h);
    return err==ESP_OK ? 0 : -1;
}

int hk_store_set(const char *part,const char *ns,const char *key,const uint8_t *value,size_t size)
{
    if(!ready || !key || !value || !size || !hk_namespace_allowed(part,ns,true)) return -1;
    nvs_handle_t h;
    esp_err_t err=nvs_open_from_partition(HK_PARTITION,ns,NVS_READWRITE,&h);
    if(err!=ESP_OK) return write_result(err);
    err=nvs_set_blob(h,key,value,size);
    if(err==ESP_OK) err=nvs_commit(h);
    nvs_close(h); return write_result(err);
}

static int remove_value(const char *part,const char *ns,const char *key)
{
    if(!ready || !hk_namespace_allowed(part,ns,true)) return -1;
    nvs_handle_t h;
    esp_err_t err=nvs_open_from_partition(HK_PARTITION,ns,NVS_READWRITE,&h);
    if(err!=ESP_OK) return write_result(err);
    err=key ? nvs_erase_key(h,key) : nvs_erase_all(h);
    if(err==ESP_ERR_NVS_NOT_FOUND) err=ESP_OK;
    if(err==ESP_OK) err=nvs_commit(h);
    nvs_close(h); return write_result(err);
}
int hk_store_delete(const char *part,const char *ns,const char *key)
{return key ? remove_value(part,ns,key) : -1;}
int hk_store_delete_namespace(const char *part,const char *ns)
{return remove_value(part,ns,NULL);}

bool hk_committed(const uint8_t hash[32])
{
    if(!ready) return false;
    nvs_handle_t h;
    if(nvs_open_from_partition(HK_PARTITION,HK_CONTROL_NS,NVS_READONLY,&h)!=ESP_OK) return false;
    uint8_t stored[32]; size_t size=sizeof(stored);
    esp_err_t err=nvs_get_blob(h,"committed",stored,&size); nvs_close(h);
    return err==ESP_OK && size==32 && !memcmp(stored,hash,32);
}

static bool change_commit(const uint8_t *hash)
{
    if(!ready || (hash && failed)) return false;
    nvs_handle_t h;
    esp_err_t err=nvs_open_from_partition(HK_PARTITION,HK_CONTROL_NS,NVS_READWRITE,&h);
    if(err!=ESP_OK) return write_result(err)==0;
    err=hash ? nvs_set_blob(h,"committed",hash,32) : nvs_erase_key(h,"committed");
    if(!hash && err==ESP_ERR_NVS_NOT_FOUND) err=ESP_OK;
    if(err==ESP_OK) err=nvs_commit(h);
    nvs_close(h); return write_result(err)==0;
}
bool hk_set_commit(const uint8_t hash[32]){return hash && change_commit(hash);}
bool hk_clear_commit(void){return change_commit(NULL);}

uint8_t hk_boot_stage_read(void)
{
    if(!ready)return 0;
    nvs_handle_t h;if(nvs_open_from_partition(HK_PARTITION,HK_CONTROL_NS,NVS_READONLY,&h)!=ESP_OK)return 0;
    uint8_t value=0;size_t size=1;
    esp_err_t err=nvs_get_blob(h,"boot_stage",&value,&size);nvs_close(h);
    return err==ESP_OK && size==1 ? value : 0;
}
bool hk_boot_stage_write(uint8_t value)
{
    if(!ready || failed || value>8)return false;
    nvs_handle_t h;esp_err_t err=nvs_open_from_partition(HK_PARTITION,HK_CONTROL_NS,NVS_READWRITE,&h);
    if(err!=ESP_OK)return write_result(err)==0;
    err=nvs_set_blob(h,"boot_stage",&value,1);if(err==ESP_OK)err=nvs_commit(h);
    nvs_close(h);return write_result(err)==0;
}
