// Copyright (c) 2011-2019 Columbia University, System Level Design Group
// SPDX-License-Identifier: Apache-2.0

#include <random>
#include <sstream>
#include "system.hpp"

// Helper random generator
static std::uniform_real_distribution<float> *dis;
static std::random_device rd;
static std::mt19937 *gen;


static void init_random_distribution(void)
{
    const float LO = -5.0;
    const float HI = 5.0;

    gen = new std::mt19937(rd());
    dis = new std::uniform_real_distribution<float>(LO, HI);
}

static float gen_random_float(void)
{
    return (*dis)(*gen);
}



// Process
void system_t::config_proc()
{

    // Reset
    {
        conf_done.write(false);
        conf_info.write(conf_info_t());
        wait();
    }

    ESP_REPORT_TIME(VON, sc_time_stamp(), "reset done");

    // Config
    load_memory();
    {
        conf_info_t config;
        // Custom configuration
        /* <<--params-->> */
        config.do_peak = do_peak;
        config.do_bitrev = do_bitrev;
        config.log_len = log_len;

        wait(); conf_info.write(config);
        conf_done.write(true);

        ESP_REPORT_TIME(VON, sc_time_stamp(), "config(): config.do_peak = %d, config.do_bitrev = %d, config.log_len = %d", config.do_peak, config.do_bitrev, config.log_len);

    }

    ESP_REPORT_TIME(VON, sc_time_stamp(), "config done");

    // Compute
    {
        // Print information about begin time
        sc_time begin_time = sc_time_stamp();
        ESP_REPORT_TIME(VON, begin_time, "run fft: BEGIN");

        ESP_REPORT_TIME(VON, sc_time_stamp(), "waiting for acc_done");

        // Wait the termination of the accelerator
        do { wait(); } while (!acc_done.read());
        debug_info_t debug_code = debug.read();

        // Print information about end time
        sc_time end_time = sc_time_stamp();
        ESP_REPORT_TIME(VON, end_time, "run fft: END");

        ESP_REPORT_TIME(VON, sc_time_stamp(), "debug code: %u", debug_code);

        wait(); conf_done.write(false);
    }

    // Validate
    {
        const int ERROR_COUNT_TH = 0.001;
        dump_memory(); // store the output in more suitable data structure if needed
        // check the results with the golden model
        if ((validate() / len) > ERROR_COUNT_TH)
        {
            ESP_REPORT_TIME(VON, sc_time_stamp(), "validation: FAIL (exceeding error count threshold)");
        } else
        {
            ESP_REPORT_TIME(VON, sc_time_stamp(), "validation: PASS");
        }
    }

    // Conclude
    {
        sc_stop();
    }
}

// Functions
void system_t::load_memory()
{
    // Input data and golden output (aligned to DMA_WIDTH makes your life easier)
#if (DMA_WORD_PER_BEAT == 0)
    in_words_adj = 2 * len;
    out_words_adj = 2 * len;
#else
    in_words_adj = round_up(2 * len, DMA_WORD_PER_BEAT);
    out_words_adj = round_up(2 * len, DMA_WORD_PER_BEAT);
#endif

    in_size = in_words_adj;
    out_size = out_words_adj;

    init_random_distribution();
    in = new float[in_size];
    for (int j = 0; j < 2 * len; j++) {
        in[j] = gen_random_float();
    }

    // preprocess with bitreverse (fast in software anyway)
    if (!do_bitrev)
        fft_bit_reverse(in, len, log_len);

    // Compute golden output
    gold = new float[out_size];
    memcpy(gold, in, out_size * sizeof(float));
    fft_comp(gold, len, log_len,  -1,  do_bitrev);

    // Memory initialization:
#if (DMA_WORD_PER_BEAT == 0)
    for (unsigned i = 0; i < in_size; i++)  {
        sc_dt::sc_bv<DATA_WIDTH> data_bv(fp2bv<FPDATA, WORD_SIZE>(FPDATA(in[i])));
        for (unsigned j = 0; j < DMA_BEAT_PER_WORD; j++)
            mem[DMA_BEAT_PER_WORD * i + j] = data_bv.range((j + 1) * DMA_WIDTH - 1, j * DMA_WIDTH);
    }
#else
    for (unsigned i = 0; i < in_size / DMA_WORD_PER_BEAT; i++)  {
        sc_dt::sc_bv<DMA_WIDTH> data_bv;
        for (unsigned j = 0; j < DMA_WORD_PER_BEAT; j++) {
            data_bv.range((j+1) * DATA_WIDTH - 1, j * DATA_WIDTH) = fp2bv<FPDATA, WORD_SIZE>(FPDATA(in[i * DMA_WORD_PER_BEAT + j]));
            ESP_REPORT_TIME(VOFF, sc_time_stamp(), "mem[%i] := %f", i, in[i * DMA_WORD_PER_BEAT + j]);
        }
        mem[i] = data_bv;
        ESP_REPORT_TIME(VOFF, sc_time_stamp(), "mem[%i] := %016llX", i, mem[i].to_uint64());
    }
#endif

    ESP_REPORT_TIME(VON, sc_time_stamp(), "load memory completed");
}

void system_t::dump_memory()
{
    // Get results from memory
    out = new float[out_size];
    uint32_t offset = 0;

#if (DMA_WORD_PER_BEAT == 0)
    offset = offset * DMA_BEAT_PER_WORD;
    for (unsigned i = 0; i < out_size; i++)  {
        sc_dt::sc_bv<DATA_WIDTH> data_bv;

        for (unsigned j = 0; j < DMA_BEAT_PER_WORD; j++)
            data_bv.range((j + 1) * DMA_WIDTH - 1, j * DMA_WIDTH) = mem[offset + DMA_BEAT_PER_WORD * i + j];

        FPDATA out_fx = bv2fp<FPDATA, WORD_SIZE>(data_bv);
        out[i] = (float) out_fx;
    }
#else
    offset = offset / DMA_WORD_PER_BEAT;
    for (unsigned i = 0; i < out_size / DMA_WORD_PER_BEAT; i++)
        for (unsigned j = 0; j < DMA_WORD_PER_BEAT; j++) {
            ac_fixed<64, 42, true> out_fx = bv2fp<FPDATA, WORD_SIZE>(mem[offset + i].range((j + 1) * DATA_WIDTH - 1, j * DATA_WIDTH));
            out[i * DMA_WORD_PER_BEAT + j] = out_fx.to_double();
        }
#endif

    ESP_REPORT_TIME(VON, sc_time_stamp(), "dump memory completed");
}


int system_t::validate()
{
    // Check for mismatches
    uint32_t errors = 0;
    const float ERR_TH = 0.05;

    for (int j = 0; j < 2 * len; j++) {

        bool flag_error = (fabs(gold[j] - out[j]) / fabs(gold[j])) > ERR_TH;
        if (flag_error) {
            errors++;
        }

        ESP_REPORT_TIME(VOFF, sc_time_stamp(), "[%d]: %f (expected %f): %s", j, out[j], gold[j], (flag_error?" !!!":""));
    }

    ESP_REPORT_TIME(VON, sc_time_stamp(), "relative error > %.02f for %llu output values out of %llu", ERR_TH, ESP_TO_UINT64(errors), 2*len);

    delete [] in;
    delete [] out;
    delete [] gold;

    return errors;
}
