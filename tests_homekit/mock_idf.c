#include "nvs.h"
#include "esp_partition.h"
#include <string.h>
int mock_init_error,mock_set_error,mock_commit_error,mock_init_calls,mock_write_calls,mock_erase_calls,mock_open_calls;
uint8_t mock_flash[0x4000];
esp_partition_t mock_partition={0x19000,0x4000,false};
static uint8_t committed[32],boot_stage;static bool has_commit,has_boot_stage;
const esp_partition_t *esp_partition_find_first(int type,int subtype,const char *name)
{return type==1 && subtype==2 && !strcmp(name,"reserve") ? &mock_partition : 0;}
int esp_partition_read(const esp_partition_t *p,size_t offset,void *out,size_t size)
{if(p!=&mock_partition || offset+size>sizeof(mock_flash))return -1;memcpy(out,mock_flash+offset,size);return 0;}
int nvs_flash_init_partition(const char *name)
{mock_init_calls++;return strcmp(name,"reserve") ? -1 : mock_init_error;}
int nvs_open_from_partition(const char *part,const char *ns,int mode,nvs_handle_t *h)
{(void)mode;mock_open_calls++;if(strcmp(part,"reserve"))return -1;*h=!strcmp(ns,"minir4_ctl") ? 1 : 2;return 0;}
int nvs_set_str(nvs_handle_t h,const char *key,const char *value)
{(void)h;(void)key;(void)value;mock_write_calls++;return mock_set_error;}
int nvs_get_str(nvs_handle_t h,const char *key,char *value,size_t *size)
{(void)h;(void)key;const char owner[]="minir4-hk-v1";if(*size<sizeof(owner))return -1;memcpy(value,owner,sizeof(owner));*size=sizeof(owner);return 0;}
int nvs_get_blob(nvs_handle_t h,const char *key,void *value,size_t *size)
{if(h==1 && !strcmp(key,"boot_stage") && has_boot_stage && *size>=1){*(uint8_t*)value=boot_stage;*size=1;return 0;}if(h!=1 || strcmp(key,"committed") || !has_commit)return ESP_ERR_NVS_NOT_FOUND;if(*size<32)return -1;memcpy(value,committed,32);*size=32;return 0;}
int nvs_set_blob(nvs_handle_t h,const char *key,const void *value,size_t size)
{mock_write_calls++;if(mock_set_error)return mock_set_error;if(h==1 && !strcmp(key,"boot_stage") && size==1){boot_stage=*(const uint8_t*)value;has_boot_stage=true;}if(h==1 && !strcmp(key,"committed") && size==32){memcpy(committed,value,32);has_commit=true;}return 0;}
int nvs_commit(nvs_handle_t h){(void)h;return mock_commit_error;}
int nvs_erase_key(nvs_handle_t h,const char *key)
{mock_erase_calls++;if(h==1 && !strcmp(key,"committed"))has_commit=false;return 0;}
int nvs_erase_all(nvs_handle_t h){(void)h;mock_erase_calls++;return 0;}
void nvs_close(nvs_handle_t h){(void)h;}
