/*
 * EMS Bike 下控 參考程式（簡化版）：第六版模型 + 可寫入參數 + 磁滯補償公式
 *
 * 給下控廠商參考的計算部分，不含 UART 收發與 flash 驅動。
 * 只用 float 與 sqrtf，可直接放進 MCU 專案。
 * 本檔與 tools/reports/test_model_ref.py 逐行對應，數值已用該測試驗證。
 */
#include <stdint.h>
#include <math.h>

#define RATIO    15.0119f   /* 飛輪 RPM / 踏頻 = 52/16 × 97/21 */
#define KP_NM    9.8f       /* 1 kp = 9.8 N·m 淨扭力 */
#define N_PARAM  9

/* ---------- 參數（存 flash；開機讀入，損壞則用預設值） ---------- */
enum {
    P_A = 0,        /* a：煞車強度，duty 每 +1% 約 +a N·m（60 踏頻） */
    P_B,            /* b：飽和彎曲 */
    P_X0,           /* x0：起始 duty，低於此扭力為 0 */
    P_C0,           /* c0：轉速影響 */
    P_T0,           /* tare 常數 N·m */
    P_T1,           /* tare 斜率 N·m / 踏頻 */
    P_GAIN,         /* 扭力倍率：每台出廠校正（VR1 粗調後的細調） */
    P_HYST_K,       /* 磁滯係數 k；0 = 關閉補償 */
    P_HYST_RESET_S  /* duty 0 維持超過此秒數，清除最高 duty 記錄 */
};

static const float PARAM_DEFAULT[N_PARAM] = {
    2.374758f, 0.00899796f, 1.6251f, 12.4604f, 1.5790f, 0.010934f, 1.000f, 0.353f, 2.0f
};
static const float PARAM_MIN[N_PARAM] = { 1.0f, 0.0f,  0.0f,  1.0f, 0.0f, 0.0f,  0.80f, 0.0f, 0.5f };
static const float PARAM_MAX[N_PARAM] = { 4.0f, 0.03f, 10.0f, 50.0f, 6.0f, 0.05f, 1.20f, 1.0f, 30.0f };

float param[N_PARAM];

void params_load_defaults(void)
{
    uint8_t i;
    for (i = 0; i < N_PARAM; i++) param[i] = PARAM_DEFAULT[i];
}

/* SET_PARAM：回傳 ACK_RESULT（0 = ACK_OK，2 = ACK_PARAM_ERROR） */
uint8_t param_set(uint8_t idx, float v)
{
    if (idx >= N_PARAM) return 2;
    if (!(v >= PARAM_MIN[idx] && v <= PARAM_MAX[idx])) return 2;   /* 也擋掉 NaN */
    param[idx] = v;
    return 0;
}

/* ---------- 模型 ---------- */
static float speed_factor(float cad)       /* 60 踏頻時 = 1.000 */
{
    float c0 = param[P_C0];
    return (c0 + 60.0f) / 60.0f * cad / (c0 + cad);
}

static float tare_nm(float cad)            /* duty 0 的機械阻力 */
{
    return param[P_T0] + param[P_T1] * cad;
}

/* duty（%）→ 模型淨扭力（N·m），含倍率，不含磁滯 */
static float net_from_duty(float duty, float cad)
{
    float u = duty - param[P_X0];
    if (u <= 0.0f) return 0.0f;
    return (param[P_A] * u - param[P_B] * u * u) * speed_factor(cad) * param[P_GAIN];
}

#define STATUS_ERG_LIMIT 0x08   /* 原協定已有：duty 100 仍達不到（KP 也用） */

/* 淨扭力 → duty（%），閉式反解 */
static float duty_from_net(float need, float cad, uint8_t *status)
{
    float a = param[P_A], b = param[P_B], x0 = param[P_X0];
    float X, disc, d;
    if (need <= 0.0f) return 0.0f;                         /* 低於空載阻力：duty 0 */
    X = need / (speed_factor(cad) * param[P_GAIN]);
    disc = a * a - 4.0f * b * X;
    if (disc < 0.0f) { *status |= STATUS_ERG_LIMIT; return 100.0f; }
    d = (a - sqrtf(disc)) / (2.0f * b) + x0;
    if (d > 100.0f) { *status |= STATUS_ERG_LIMIT; return 100.0f; }
    return d;
}

/* ---------- 磁滯 ---------- */
static float peak_duty;      /* 上次歸零後到過的最高 duty */
static float zero_time_s;    /* duty 0 已維持的秒數 */

/* 每次輸出 duty 後呼叫（dt_s = 與上次呼叫的間隔秒數） */
void hyst_track(float duty_out, float dt_s)
{
    if (duty_out <= 0.0f) {
        zero_time_s += dt_s;
        if (zero_time_s >= param[P_HYST_RESET_S]) peak_duty = 0.0f;
    } else {
        zero_time_s = 0.0f;
        if (duty_out > peak_duty) peak_duty = duty_out;
    }
}

/* 偏高量 h（0.10 = 10%）= k × ((最高 − 目前) / 最高)² */
static float hyst_excess(float duty)
{
    float x;
    if (duty <= 0.0f || duty >= peak_duty) return 0.0f;
    x = (peak_duty - duty) / peak_duty;
    return param[P_HYST_K] * x * x;
}

/* 目標淨扭力 → duty，含磁滯補償（補償一次即可） */
static float duty_for_net(float need, float cad, uint8_t *status)
{
    float d = duty_from_net(need, cad, status);
    float h = hyst_excess(d);
    if (h > 0.0f) d = duty_from_net(need / (1.0f + h), cad, status);
    return d;
}

/* ---------- 對外介面 ---------- */
/* MODE_ERG：target_w = 騎士總功率；回傳 MODE_DUTY 單位（0.1%） */
uint16_t erg_to_duty_x10(uint16_t target_w, uint16_t flywheel_rpm, uint8_t *status)
{
    float cad = flywheel_rpm / RATIO, w;
    if (cad < 1.0f) return 0;
    w = 2.0f * 3.14159265f * cad / 60.0f;
    return (uint16_t)(duty_for_net((float)target_w / w - tare_nm(cad), cad, status) * 10.0f + 0.5f);
}

/* MODE_KP：mode_kp 單位 0.1 kp；KP 不扣 tare */
uint16_t kp_to_duty_x10(uint16_t mode_kp, uint16_t flywheel_rpm, uint8_t *status)
{
    float cad = flywheel_rpm / RATIO;
    if (cad < 1.0f) return 0;
    return (uint16_t)(duty_for_net(mode_kp * 0.1f * KP_NM, cad, status) * 10.0f + 0.5f);
}

/* STATUS_REPORT 的 est_watt：目前 duty 下騎士的總功率 */
uint16_t est_watt(uint16_t duty_x10, uint16_t flywheel_rpm)
{
    float cad = flywheel_rpm / RATIO, duty = duty_x10 * 0.1f;
    float net = net_from_duty(duty, cad) * (1.0f + hyst_excess(duty));
    return (uint16_t)((net + tare_nm(cad)) * 2.0f * 3.14159265f * cad / 60.0f + 0.5f);
}
