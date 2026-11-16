/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "store_policy.h"
#include <string.h>

static uint32_t u32(const uint8_t *p)
{
    return (uint32_t)p[0] | (uint32_t)p[1]<<8 | (uint32_t)p[2]<<16 | (uint32_t)p[3]<<24;
}

static uint32_t crc32(const uint8_t *data, size_t size, uint32_t seed)
{
    uint32_t crc = ~seed;
    for (size_t i=0; i<size; i++) {
        crc ^= data[i];
        for (int bit=0; bit<8; bit++) crc = (crc>>1) ^ (0xedb88320U & (0U-(crc&1U)));
    }
    return ~crc;
}

static bool key(const uint8_t *entry, const char *expected)
{
    size_t len = strlen(expected);
    return len < 16 && memcmp(entry+8, expected, len)==0 && entry[8+len]==0;
}

static bool written(const uint8_t *page, size_t i)
{
    return ((page[32+i/4] >> ((i%4)*2)) & 3) == 2;
}

static bool header_valid(const uint8_t *e)
{
    uint32_t crc=crc32(e,4,0xffffffffU);
    crc=crc32(e+8,24,crc);
    return crc==u32(e+4);
}

int hk_storage_classify(const uint8_t *data, size_t size)
{
    if (!data || size!=0x4000) return 0;
    bool blank=true;
    for(size_t i=0;i<size;i++) if(data[i]!=0xff){blank=false;break;}
    if(blank) return 1;
    uint8_t ns=0;
    /* Two passes, since the namespace and owner can be on different pages. */
    for(int pass=0;pass<2;pass++) for(size_t base=0;base<size;base+=4096) {
        const uint8_t *page=data+base;
        if(u32(page)==0xffffffffU) {
            for(size_t i=0;i<4096;i++)if(page[i]!=0xff)return 0;
            continue;
        }
        if((u32(page)!=0xfffffffeU && u32(page)!=0xfffffffcU) ||
           crc32(page+4,24,0xffffffffU)!=u32(page+28)) return 0;
        for(size_t i=0;i<126;) {
            const uint8_t *e=page+64+i*32;
            size_t span=e[2];
            if(!written(page,i) || !span || span>126-i || !header_valid(e)){i++;continue;}
            if(pass==0 && e[0]==0 && e[1]==1 && span==1 && key(e,HK_CONTROL_NS)) {
                if(e[24]==0 || (ns && ns!=e[24])) return 0;
                ns=e[24];
            }
            if(pass==1 && ns && e[0]==ns && e[1]==0x21 && span==2 &&
               key(e,"owner") && written(page,i+1)) {
                size_t len=(size_t)e[24] | (size_t)e[25]<<8;
                if(len==sizeof(HK_OWNER) && memcmp(e+32,HK_OWNER,len)==0 &&
                   crc32(e+32,len,0xffffffffU)==u32(e+28)) return 2;
            }
            i+=span;
        }
    }
    return 0;
}

bool hk_namespace_allowed(const char *partition, const char *name_space, bool write)
{
    if(!partition || !name_space || strcmp(partition,HK_PARTITION)) return false;
    return !strcmp(name_space,"hap_main") || !strcmp(name_space,"hap_ctrl") ||
           (!write && !strcmp(name_space,"hap_setup"));
}
