/**
 * main_copy.c - Minimal ESP32C6 ESP-NOW sender (broadcast-only)
 *
 * Purpose:
 *   Simple reference variant of ESP_Send that only broadcasts packets
 *   using ESP-NOW at a fixed frequency.
 *
 * Differences from main/main.c:
 *   - No SD card initialization or logging.
 *   - No receive callback (no CSI listening path).
 *   - No send-done callback wait (fire-and-forget send).
 *
 * Note:
 *   This file is stored under tools/ as a reference and is not part of
 *   the active ESP-IDF build component by default.
 */

#include <stdio.h>
#include <string.h>
#include "nvs_flash.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_wifi.h"
#include "esp_netif.h"
#include "esp_now.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

// ---------------------------------------------------------------------------
// WiFi / ESP-NOW configuration (same baseline as main/main.c)
// ---------------------------------------------------------------------------
#define WIFI_CHANNEL                11
#define WIFI_BAND_MODE              WIFI_BAND_MODE_2G_ONLY
#define WIFI_BANDWIDTH              WIFI_BW_HT20
#define WIFI_PROTOCOL               WIFI_PROTOCOL_11AX
#define WIFI_SECOND_CHAN_MODE       WIFI_SECOND_CHAN_NONE

#define ESP_NOW_PHY_MODE            WIFI_PHY_MODE_HE20
#define ESP_NOW_RATE                WIFI_PHY_RATE_MCS0_LGI
#define SEND_FREQUENCY              100  // Hz

static const uint8_t SENDER_MAC[] = {0x1a, 0x00, 0x00, 0x00, 0x00, 0x00};
static const char *TAG = "csi_send_min";

static void wifi_init(void)
{
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    ESP_ERROR_CHECK(esp_netif_init());

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));

#if ESP_IDF_VERSION >= ESP_IDF_VERSION_VAL(5, 4, 0)
    ESP_ERROR_CHECK(esp_wifi_start());
    ESP_ERROR_CHECK(esp_wifi_set_band_mode(WIFI_BAND_MODE));

    wifi_protocols_t protocols = { .ghz_2g = WIFI_PROTOCOL };
    ESP_ERROR_CHECK(esp_wifi_set_protocols(WIFI_IF_STA, &protocols));

    wifi_bandwidths_t bandwidth = { .ghz_2g = WIFI_BANDWIDTH };
    ESP_ERROR_CHECK(esp_wifi_set_bandwidths(WIFI_IF_STA, &bandwidth));
#else
    ESP_ERROR_CHECK(esp_wifi_set_bandwidth(WIFI_IF_STA, WIFI_BANDWIDTH));
    ESP_ERROR_CHECK(esp_wifi_start());
#endif

    ESP_ERROR_CHECK(esp_wifi_set_max_tx_power(84));
    ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_NONE));
    ESP_ERROR_CHECK(esp_wifi_set_channel(WIFI_CHANNEL, WIFI_SECOND_CHAN_MODE));
    ESP_ERROR_CHECK(esp_wifi_set_mac(WIFI_IF_STA, SENDER_MAC));
}

static void esp_now_init_broadcast(esp_now_peer_info_t *peer)
{
    ESP_ERROR_CHECK(esp_now_init());
    ESP_ERROR_CHECK(esp_now_set_pmk((uint8_t *)"pmk1234567890123"));

    memset(peer, 0, sizeof(*peer));
    peer->channel = WIFI_CHANNEL;
    peer->ifidx = WIFI_IF_STA;
    peer->encrypt = false;
    memset(peer->peer_addr, 0xFF, ESP_NOW_ETH_ALEN);

    ESP_ERROR_CHECK(esp_now_add_peer(peer));

    esp_now_rate_config_t rate_config = {
        .phymode = ESP_NOW_PHY_MODE,
        .rate = ESP_NOW_RATE,
        .ersu = false,
        .dcm = false,
    };
    ESP_ERROR_CHECK(esp_now_set_peer_rate_config(peer->peer_addr, &rate_config));
}

void app_main(void)
{
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(ret);

    wifi_init();

    esp_now_peer_info_t peer;
    esp_now_init_broadcast(&peer);

    ESP_LOGI(TAG, "===== ESP-NOW Broadcast Only =====");
    ESP_LOGI(TAG, "Channel: %d | Freq: %d Hz | MAC: " MACSTR,
             WIFI_CHANNEL, SEND_FREQUENCY, MAC2STR(SENDER_MAC));

    const TickType_t period_ticks = pdMS_TO_TICKS(1000U / SEND_FREQUENCY);
    TickType_t last_wake_time = xTaskGetTickCount();
    int64_t last_log_us = esp_timer_get_time();
    uint32_t last_sent_id = 0;

    for (uint32_t count = 0; ; ++count) {
        ret = esp_now_send(peer.peer_addr, (const uint8_t *)&count, sizeof(count));
        if (ret != ESP_OK) {
            ESP_LOGW(TAG, "esp_now_send failed: %s", esp_err_to_name(ret));
        } else {
            last_sent_id = count;
        }

        int64_t now_us = esp_timer_get_time();
        if (now_us - last_log_us >= 1000000LL) {
            ESP_LOGI(TAG, "Last sent id: %lu", (unsigned long)last_sent_id);
            last_log_us = now_us;
        }

        vTaskDelayUntil(&last_wake_time, period_ticks);
    }
}
