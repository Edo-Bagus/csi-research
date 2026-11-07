# REQUIRES dipangkas dari CSI_recv_v2: fatfs/sdmmc/led_strip dibuang karena
# jalur SD-card dan LED status tidak dipakai lagi oleh app_main.c.
#   esp_event + lwip  -> event handler WiFi/IP dan ping/ping_sock.h
#   esp_timer         -> dipakai tidak langsung oleh stack ping
idf_component_register(SRC_DIRS "."
                       INCLUDE_DIRS "."
                       REQUIRES nvs_flash esp_wifi esp_netif esp_event esp_timer lwip)
