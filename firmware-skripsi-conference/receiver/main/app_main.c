#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include <assert.h>
#include <inttypes.h>
#include <stdarg.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/message_buffer.h"
#include "nvs_flash.h"

#include "sdkconfig.h"
#include "esp_mac.h"
#include "esp_log.h"
#include "esp_wifi.h"
#include "esp_netif.h"
#include "esp_now.h"
#include "esp_csi_gain_ctrl.h"
#include "driver/uart.h"

#define CONFIG_LESS_INTERFERENCE_CHANNEL   11
#define CONFIG_WIFI_BAND_MODE               WIFI_BAND_MODE_2G_ONLY
#define CONFIG_WIFI_2G_BANDWIDTHS           WIFI_BW_HT20  // 20 MHz = 256 subcarriers for 802.11ax
#define CONFIG_WIFI_2G_PROTOCOL             WIFI_PROTOCOL_11AX

#define CONFIG_ESP_NOW_PHYMODE              WIFI_PHY_MODE_HE20  // 802.11ax HE SU mode
#define CONFIG_ESP_NOW_RATE                 WIFI_PHY_RATE_MCS0_LGI
#define CONFIG_FORCE_GAIN                   0
#define CONFIG_TX_ID                        4   // Hardcoded TX node identifier

#define CONFIG_CSI_MAX_LEN                  512
#define MSG_BUF_SIZE                        (128 * 1024)
#define UART_WRITE_BUF_SIZE                 (8 * 1024)
#define UART_TX_BUF_SIZE                    (16 * 1024)
#define UART_MAGIC_INTERVAL_MS              1000
#define UART_BAUD_RATE                      CONFIG_ESP_CONSOLE_UART_BAUDRATE
#define UART_TX_GPIO                        CONFIG_ESP_CONSOLE_UART_TX_GPIO
#define UART_RX_GPIO                        CONFIG_ESP_CONSOLE_UART_RX_GPIO
#define UART_PORT_NUM                       UART_NUM_0

#if ESP_IDF_VERSION >= ESP_IDF_VERSION_VAL(6, 0, 0)
#define ESP_IF_WIFI_STA ESP_MAC_WIFI_STA
#endif

static const uint8_t CONFIG_CSI_SEND_MAC[] = {0x1a, 0x00, 0x00, 0x00, 0x00, 0x00};
static const char *TAG = "csi_recv";

typedef struct {
    uint32_t msg_id;
    uint8_t  tx_id;
    int16_t  rssi;
    uint8_t  rate;
    int8_t   noise_floor;
    int8_t   fft_gain;
    uint8_t  agc_gain;
    uint8_t  channel;
    uint8_t  first_word_invalid;
    uint8_t  mac[6];
    uint32_t timestamp;
    uint16_t sig_len;
    uint8_t  rx_state;
    uint16_t len;
    int16_t  csi_buf[CONFIG_CSI_MAX_LEN];
} __attribute__((packed)) csi_binary_msg_t;

static MessageBufferHandle_t s_msg_buf = NULL;
static volatile uint32_t s_drop_count = 0;
static volatile uint32_t s_saved_count = 0;
static volatile uint32_t s_recv_count = 0;
static volatile bool s_uart_stream_enabled = false;

static int log_vprintf_null(const char *fmt, va_list args)
{
    (void)fmt;
    (void)args;
    return 0;
}

static void disable_uart_logging(void)
{
    esp_log_set_vprintf(log_vprintf_null);
    esp_log_level_set("*", ESP_LOG_NONE);
}

static esp_err_t uart_stream_init(void)
{
    const uart_config_t uart_config = {
        .baud_rate = UART_BAUD_RATE,
        .data_bits = UART_DATA_8_BITS,
        .parity = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };

    esp_err_t ret = uart_param_config(UART_PORT_NUM, &uart_config);
    if (ret != ESP_OK) {
        return ret;
    }

    ret = uart_set_pin(UART_PORT_NUM, UART_TX_GPIO, UART_RX_GPIO, UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE);
    if (ret != ESP_OK) {
        return ret;
    }

    ret = uart_driver_install(UART_PORT_NUM, UART_TX_BUF_SIZE, 0, 0, NULL, 0);
    if (ret == ESP_ERR_INVALID_STATE) {
        ret = ESP_OK;
    }
    return ret;
}

static void uart_stream_send_magic(void)
{
    const uint32_t magic = 0xDEADBEEF;
    uart_write_bytes(UART_PORT_NUM, (const char *)&magic, sizeof(magic));
}

static void wifi_init()
{
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    ESP_ERROR_CHECK(esp_netif_init());
    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));

    ESP_ERROR_CHECK(esp_wifi_start());
    esp_wifi_set_band_mode(CONFIG_WIFI_BAND_MODE);
    wifi_protocols_t protocols = {
        .ghz_2g = CONFIG_WIFI_2G_PROTOCOL,
    };
    ESP_ERROR_CHECK(esp_wifi_set_protocols(ESP_IF_WIFI_STA, &protocols));
    wifi_bandwidths_t bandwidth = {
        .ghz_2g = CONFIG_WIFI_2G_BANDWIDTHS,
    };
    ESP_ERROR_CHECK(esp_wifi_set_bandwidths(ESP_IF_WIFI_STA, &bandwidth));

    ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_NONE));
    if (CONFIG_WIFI_BAND_MODE == WIFI_BAND_MODE_2G_ONLY && CONFIG_WIFI_2G_BANDWIDTHS == WIFI_BW_HT20) {
        ESP_ERROR_CHECK(esp_wifi_set_channel(CONFIG_LESS_INTERFERENCE_CHANNEL, WIFI_SECOND_CHAN_NONE));
    } else {
        ESP_ERROR_CHECK(esp_wifi_set_channel(CONFIG_LESS_INTERFERENCE_CHANNEL, WIFI_SECOND_CHAN_BELOW));
    }
    // Jangan override MAC — setiap RX node harus pakai factory MAC uniknya sendiri.
    // CONFIG_CSI_SEND_MAC hanya dipakai sebagai filter untuk mengidentifikasi paket dari TX.
}

static void wifi_esp_now_init(esp_now_peer_info_t peer)
{
    ESP_ERROR_CHECK(esp_now_init());
    ESP_ERROR_CHECK(esp_now_set_pmk((uint8_t *)"pmk1234567890123"));
    esp_now_rate_config_t rate_config = {
        .phymode = CONFIG_ESP_NOW_PHYMODE,
        .rate = CONFIG_ESP_NOW_RATE,//  WIFI_PHY_RATE_MCS0_LGI,
        .ersu = false,
        .dcm = false
    };
    ESP_ERROR_CHECK(esp_now_add_peer(&peer));
    ESP_ERROR_CHECK(esp_now_set_peer_rate_config(peer.peer_addr, &rate_config));

}

static void uart_write_task(void *arg)
{
    (void)arg;
    uint8_t *write_buf = malloc(UART_WRITE_BUF_SIZE);
    assert(write_buf != NULL);

    size_t write_buf_used = 0;
    static uint8_t pkt_buf[sizeof(csi_binary_msg_t)];
    TickType_t last_magic_tick = xTaskGetTickCount();
    const TickType_t magic_interval = pdMS_TO_TICKS(UART_MAGIC_INTERVAL_MS);

    while (1) {
        size_t recv = xMessageBufferReceive(s_msg_buf, pkt_buf, sizeof(pkt_buf), pdMS_TO_TICKS(200));
        TickType_t now = xTaskGetTickCount();
        if ((now - last_magic_tick) >= magic_interval) {
            uart_stream_send_magic();
            last_magic_tick = now;
        }

        if (recv > 0) {
            if (write_buf_used + recv > UART_WRITE_BUF_SIZE) {
                int written = uart_write_bytes(UART_PORT_NUM, (const char *)write_buf, write_buf_used);
                if (written < 0 || (size_t)written < write_buf_used) {
                    s_drop_count++;
                }
                write_buf_used = 0;
            }

            memcpy(write_buf + write_buf_used, pkt_buf, recv);
            write_buf_used += recv;
            s_saved_count++;
        }

        if (write_buf_used > 0 && recv == 0) {
            int written = uart_write_bytes(UART_PORT_NUM, (const char *)write_buf, write_buf_used);
            if (written < 0 || (size_t)written < write_buf_used) {
                s_drop_count++;
            }
            write_buf_used = 0;
        }
    }
}

static void wifi_csi_rx_cb(void *ctx, wifi_csi_info_t *info)
{
    (void)ctx;

    if (!info || !info->buf) {
        return;
    }

    if (memcmp(info->mac, CONFIG_CSI_SEND_MAC, 6)) {
        return;
    }

    if (!s_msg_buf || !s_uart_stream_enabled) {
        return;
    }

    if (info->len <= 0 || info->len > CONFIG_CSI_MAX_LEN) {
        return;
    }

    const wifi_pkt_rx_ctrl_t *rx_ctrl = &info->rx_ctrl;
    static uint32_t s_gain_count = 0;
    static uint8_t agc_gain = 0;
    static int8_t fft_gain = 0;
    static uint8_t agc_gain_baseline = 0;
    static int8_t fft_gain_baseline = 0;

    esp_csi_gain_ctrl_get_rx_gain(rx_ctrl, &agc_gain, &fft_gain);
    if (s_gain_count < 100) {
        esp_csi_gain_ctrl_record_rx_gain(agc_gain, fft_gain);
    } else if (s_gain_count == 100) {
        esp_csi_gain_ctrl_get_rx_gain_baseline(&agc_gain_baseline, &fft_gain_baseline);
#if CONFIG_FORCE_GAIN
        esp_csi_gain_ctrl_set_rx_force_gain(agc_gain_baseline, fft_gain_baseline);
        ESP_LOGD(TAG, "fft_force %d, agc_force %d", fft_gain_baseline, agc_gain_baseline);
#endif
    }

    csi_binary_msg_t msg = {0};
    if (info->payload && rx_ctrl->sig_len >= 19) {
        memcpy(&msg.msg_id, info->payload + 15, sizeof(msg.msg_id));
    }

    msg.tx_id = CONFIG_TX_ID;
    msg.rssi = rx_ctrl->rssi;
    msg.rate = rx_ctrl->rate;
    msg.noise_floor = rx_ctrl->noise_floor;
    msg.fft_gain = fft_gain;
    msg.agc_gain = agc_gain;
    msg.channel = rx_ctrl->channel;
    msg.first_word_invalid = info->first_word_invalid;
    memcpy(msg.mac, info->mac, sizeof(msg.mac));
    msg.timestamp = rx_ctrl->timestamp;
    msg.sig_len = rx_ctrl->sig_len;
    msg.rx_state = rx_ctrl->rx_state;
    msg.len = (uint16_t)info->len;

    for (int i = 0; i < info->len; i++) {
        msg.csi_buf[i] = (int16_t)info->buf[i];
    }

    size_t pkt_size = offsetof(csi_binary_msg_t, csi_buf) + msg.len * sizeof(int16_t);
    BaseType_t sent = xMessageBufferSend(s_msg_buf, &msg, pkt_size, 0);
    if (sent == 0) {
        s_drop_count++;
    } else {
        s_recv_count++;
    }

    s_gain_count++;
}

static void wifi_csi_init()
{
    ESP_ERROR_CHECK(esp_wifi_set_promiscuous(true));

    wifi_csi_config_t csi_config = {
        .enable                 = true,
        .acquire_csi_legacy     = false,  // Disable 802.11b/g
        .acquire_csi_ht20       = false,  // Disable 802.11n 20MHz
        .acquire_csi_ht40       = false,  // Disable 802.11n 40MHz
        .acquire_csi_su         = true,   // Enable 802.11ax HE SU (256 subcarriers @ 20MHz)
        .acquire_csi_mu         = false,  // Disable MU-MIMO for now
        .acquire_csi_dcm        = true,   // Enable Dual Carrier Modulation
        .acquire_csi_beamformed = true,   // Enable beamformed packets
        .acquire_csi_he_stbc    = 2,      // HE STBC mode
        .val_scale_cfg          = false,
        .dump_ack_en            = false,
        .reserved               = false
    };
    ESP_ERROR_CHECK(esp_wifi_set_csi_config(&csi_config));
    ESP_ERROR_CHECK(esp_wifi_set_csi_rx_cb(wifi_csi_rx_cb, NULL));
    ESP_ERROR_CHECK(esp_wifi_set_csi(true));
}

void app_main()
{
    /**
     * @brief Initialize NVS
     */
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(ret);

    disable_uart_logging();

    s_msg_buf = xMessageBufferCreate(MSG_BUF_SIZE);
    assert(s_msg_buf != NULL);

    /**
     * @brief Initialize Wi-Fi
     */
    wifi_init();

    /**
     * @brief Initialize ESP-NOW
     *        ESP-NOW protocol see: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/network/esp_now.html
     */

    esp_now_peer_info_t peer = {
        .channel   = CONFIG_LESS_INTERFERENCE_CHANNEL,
        .ifidx     = WIFI_IF_STA,
        .encrypt   = false,
        .peer_addr = {0xff, 0xff, 0xff, 0xff, 0xff, 0xff},
    };

    wifi_esp_now_init(peer);

    esp_err_t uart_ret = uart_stream_init();
    if (uart_ret == ESP_OK) {
        uart_stream_send_magic();
        BaseType_t task_ok = xTaskCreatePinnedToCore(uart_write_task,
                                                     "uart_write_task",
                                                     4096,
                                                     NULL,
                                                     2,
                                                     NULL,
                                                     0);
        if (task_ok == pdPASS) {
            s_uart_stream_enabled = true;
        }
    }

    wifi_csi_init();
}
