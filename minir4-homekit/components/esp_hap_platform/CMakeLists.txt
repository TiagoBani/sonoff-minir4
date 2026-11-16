set(REF "${HK_REFERENCE}/components/homekit/esp_hap_platform")
idf_component_register(
    SRCS "${REF}/src/esp_mfi_aes.c" "${REF}/src/esp_mfi_base64.c"
         "${REF}/src/esp_mfi_rand.c" "${REF}/src/esp_mfi_sha.c"
         "${REF}/src/hap_platform_httpd.c" "${REF}/src/hap_platform_memory.c"
         "${REF}/src/hap_platform_os.c" "keystore.c"
    INCLUDE_DIRS "${REF}/include" "../../main"
    REQUIRES esp_http_server
    PRIV_REQUIRES driver mbedtls nvs_flash mdns esp_hap_core esp_partition)
