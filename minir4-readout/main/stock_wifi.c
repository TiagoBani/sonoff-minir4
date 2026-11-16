/* SPDX-License-Identifier: GPL-3.0-or-later
 * MINIR4 stock 1.2.0: pair/info layout verified from its app and owner dump.
 * Magic/version checked by vendor code at 0x400f317f/0x400f31c9.
 * SSID/password pointers at 0x400dd471-0x400dd477 are base+71/base+104.
 */
#include "stock_wifi.h"
#include <string.h>

bool minir4_decode_pair_wifi(const uint8_t *blob, size_t length,
                             uint8_t ssid[32], uint8_t password[64])
{
    if (!ssid || !password) return false;
    memset(ssid, 0, 32);
    memset(password, 0, 64);
    if (!blob || length != MINIR4_PAIR_INFO_SIZE ||
        blob[0] != 0xaa || blob[1] != 0x55 || blob[2] != 2 || blob[3] != 0) return false;
    const uint8_t *ssid_end = memchr(blob + 71, 0, 33);
    const uint8_t *password_end = memchr(blob + 104, 0, 65);
    if (!ssid_end || !password_end || ssid_end == blob + 71) return false;
    memcpy(ssid, blob + 71, (size_t)(ssid_end - (blob + 71)));
    memcpy(password, blob + 104, (size_t)(password_end - (blob + 104)));
    return true;
}
