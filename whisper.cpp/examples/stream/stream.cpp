// Real-time speech translation with endpointed VAD segmentation.
//
// Rewrite of the whisper.cpp `stream` example for the case where latency is
// unconstrained but dropped audio is unacceptable.
//
// Differences from the stock example:
//   * Utterance endpointing instead of fixed windows. Audio is transcribed
//     exactly once, trimmed to the actual speech span, with no silence
//     padding -- which is what causes the "Thank you." hallucinations.
//   * Hysteretic VAD with an adaptive noise floor, rather than a single
//     fixed energy threshold evaluated over a trailing window.
//   * Inference runs on a worker thread behind an unbounded queue. If the
//     model falls behind, output arrives later; nothing is ever discarded.
//     There is no audio.clear() anywhere in this file.
//   * Dual-pass output: each utterance is decoded twice, once as a
//     source-language transcript and once translated to English, so a
//     hallucinated translation can be spotted against its source.
//   * Emits JSON Lines on stdout, unbuffered, for a downstream bridge.
//
// Build: replace examples/stream/stream.cpp with this file and rebuild.
// No CMakeLists changes required.

#include "common-sdl.h"
#include "common.h"
#include "common-whisper.h"
#include "whisper.h"

#include <atomic>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <cstdio>
#include <deque>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

// ---------------------------------------------------------------------------
// parameters
// ---------------------------------------------------------------------------

struct whisper_params {
    int32_t n_threads   = std::min(8, (int32_t) std::thread::hardware_concurrency());
    int32_t capture_id  = -1;
    int32_t beam_size   = 5;
    int32_t audio_ctx   = 0;      // 0 = full 1500. Do not truncate here.

    // segmentation
    int32_t frame_ms      = 40;   // VAD analysis frame
    int32_t onset_ms      = 200;  // sustained speech required to open an utterance
    int32_t hang_ms       = 900;  // trailing silence required to close one
    int32_t preroll_ms    = 250;  // audio retained from before onset
    int32_t pad_ms        = 200;  // silence retained after offset
    int32_t max_utt_ms    = 25000;// hard cap; Whisper cannot exceed 30 s
    int32_t min_utt_ms    = 200;  // discard blips shorter than this

    float   vad_thold     = 3.0f; // energy multiple over the adaptive floor
    float   abs_floor     = 1e-4f;// absolute RMS gate, kills near-silence

    bool    translate     = true; // emit an English pass
    bool    transcribe    = true; // emit a source-language pass
    bool    no_fallback   = false;// leave temperature fallback ON
    bool    use_gpu       = true;
    bool    flash_attn    = true;
    bool    verbose       = false;
    bool    text_out      = false;// human-readable lines instead of JSONL

    std::string language = "en";  // pin this; auto-detect is unreliable on short clips
    std::string model    = "models/ggml-large-v3-q5_0.bin";
};

static void print_usage(const whisper_params & p) {
    fprintf(stderr, "\noptions:\n");
    fprintf(stderr, "  -m FNAME  model path                      [%s]\n",  p.model.c_str());
    fprintf(stderr, "  -l LANG   source language (pin it)        [%s]\n",  p.language.c_str());
    fprintf(stderr, "  -t N      threads                         [%d]\n",  p.n_threads);
    fprintf(stderr, "  -c ID     capture device id               [%d]\n",  p.capture_id);
    fprintf(stderr, "  -bs N     beam size                       [%d]\n",  p.beam_size);
    fprintf(stderr, "  -ac N     audio context (0 = full)        [%d]\n",  p.audio_ctx);
    fprintf(stderr, "  -vth F    energy multiple over noise floor[%.2f]\n", p.vad_thold);
    fprintf(stderr, "  -hang N   trailing silence to end utt (ms)[%d]\n",  p.hang_ms);
    fprintf(stderr, "  -onset N  speech needed to start utt (ms) [%d]\n",  p.onset_ms);
    fprintf(stderr, "  -maxu N   max utterance length (ms)       [%d]\n",  p.max_utt_ms);
    fprintf(stderr, "  -nt       skip the source-language pass\n");
    fprintf(stderr, "  -ntr      skip the English pass\n");
    fprintf(stderr, "  -nf       disable temperature fallback\n");
    fprintf(stderr, "  -ng       disable GPU\n");
    fprintf(stderr, "  -txt      print readable captions instead of JSON Lines\n");
    fprintf(stderr, "  -v        verbose VAD logging to stderr\n\n");
}

static bool params_parse(int argc, char ** argv, whisper_params & p) {
    for (int i = 1; i < argc; i++) {
        std::string a = argv[i];
        if      (a == "-h" || a == "--help")     { print_usage(p); exit(0); }
        else if (a == "-m")                      { p.model      = argv[++i]; }
        else if (a == "-l")                      { p.language   = argv[++i]; }
        else if (a == "-t")                      { p.n_threads  = std::stoi(argv[++i]); }
        else if (a == "-c")                      { p.capture_id = std::stoi(argv[++i]); }
        else if (a == "-bs")                     { p.beam_size  = std::stoi(argv[++i]); }
        else if (a == "-ac")                     { p.audio_ctx  = std::stoi(argv[++i]); }
        else if (a == "-vth")                    { p.vad_thold  = std::stof(argv[++i]); }
        else if (a == "-hang")                   { p.hang_ms    = std::stoi(argv[++i]); }
        else if (a == "-onset")                  { p.onset_ms   = std::stoi(argv[++i]); }
        else if (a == "-maxu")                   { p.max_utt_ms = std::stoi(argv[++i]); }
        else if (a == "-nt")                     { p.transcribe = false; }
        else if (a == "-ntr")                    { p.translate  = false; }
        else if (a == "-nf")                     { p.no_fallback= true; }
        else if (a == "-ng")                     { p.use_gpu    = false; }
        else if (a == "-v")                      { p.verbose    = true; }
        else if (a == "-txt")                    { p.text_out   = true; }
        else {
            fprintf(stderr, "unknown argument: %s\n", a.c_str());
            print_usage(p);
            exit(1);
        }
    }
    return true;
}

// ---------------------------------------------------------------------------
// utterance queue -- unbounded on purpose
// ---------------------------------------------------------------------------

struct utterance {
    int                id;
    std::vector<float> pcm;
    int64_t            t_start_ms;
};

class utterance_queue {
public:
    void push(utterance && u) {
        {
            std::lock_guard<std::mutex> lk(m_mutex);
            m_q.push_back(std::move(u));
        }
        m_cv.notify_one();
    }

    // Returns false only once the queue is closed AND drained.
    bool pop(utterance & out) {
        std::unique_lock<std::mutex> lk(m_mutex);
        m_cv.wait(lk, [this] { return !m_q.empty() || m_closed; });
        if (m_q.empty()) return false;
        out = std::move(m_q.front());
        m_q.pop_front();
        return true;
    }

    void close() {
        {
            std::lock_guard<std::mutex> lk(m_mutex);
            m_closed = true;
        }
        m_cv.notify_all();
    }

    size_t size() {
        std::lock_guard<std::mutex> lk(m_mutex);
        return m_q.size();
    }

private:
    std::mutex              m_mutex;
    std::condition_variable m_cv;
    std::deque<utterance>   m_q;
    bool                    m_closed = false;
};

// ---------------------------------------------------------------------------
// VAD segmenter
// ---------------------------------------------------------------------------
//
// Frame-level RMS against an adaptive noise floor, with separate onset and
// offset hysteresis. The floor tracks ambient level during silence, so this
// survives a change of room without retuning -vth.
//
// This is a drop-in point for Silero: replace frame_is_speech() with a call
// to whisper_vad_detect_speech() and keep the state machine as-is.

class segmenter {
public:
    segmenter(const whisper_params & p)
        : m_p(p)
        , m_frame_n((p.frame_ms * WHISPER_SAMPLE_RATE) / 1000)
        , m_onset_frames(std::max(1, p.onset_ms / p.frame_ms))
        , m_hang_frames (std::max(1, p.hang_ms  / p.frame_ms))
        , m_preroll_n((p.preroll_ms * WHISPER_SAMPLE_RATE) / 1000)
        , m_pad_n    ((p.pad_ms     * WHISPER_SAMPLE_RATE) / 1000)
        , m_max_n    ((int64_t)p.max_utt_ms * WHISPER_SAMPLE_RATE / 1000)
        , m_min_n    ((int64_t)p.min_utt_ms * WHISPER_SAMPLE_RATE / 1000)
    {}

    // Feed captured audio. Completed utterances are appended to `out`.
    void feed(const std::vector<float> & pcm, std::vector<utterance> & out) {
        m_carry.insert(m_carry.end(), pcm.begin(), pcm.end());

        size_t off = 0;
        while (m_carry.size() - off >= (size_t) m_frame_n) {
            const float * f = m_carry.data() + off;
            process_frame(f, out);
            off += m_frame_n;
            m_total_n += m_frame_n;
        }
        m_carry.erase(m_carry.begin(), m_carry.begin() + off);
    }

    // Called on shutdown so a half-spoken utterance still gets emitted.
    void flush(std::vector<utterance> & out) {
        if (m_in_speech) finalize(out);
    }

private:
    static float rms(const float * x, int n) {
        double s = 0.0;
        for (int i = 0; i < n; i++) s += (double) x[i] * x[i];
        return (float) std::sqrt(s / n);
    }

    bool frame_is_speech(float e) {
        // Adaptive floor: track ambient during non-speech only, so a long
        // utterance cannot drag the floor up and cut itself off.
        if (m_floor <= 0.0f) m_floor = std::max(e, m_p.abs_floor);

        const bool speech = (e > m_floor * m_p.vad_thold) && (e > m_p.abs_floor);

        if (!speech) {
            // Asymmetric: rise slowly, fall quickly, so the floor settles to
            // the quiet part of the ambient distribution.
            const float a = (e < m_floor) ? 0.15f : 0.01f;
            m_floor = (1.0f - a) * m_floor + a * e;
            m_floor = std::max(m_floor, m_p.abs_floor * 0.5f);
        }
        return speech;
    }

    void process_frame(const float * f, std::vector<utterance> & out) {
        const float e      = rms(f, m_frame_n);
        const bool  speech = frame_is_speech(e);

        if (!m_in_speech) {
            // Maintain a rolling pre-roll so we don't clip the first phoneme.
            m_preroll.insert(m_preroll.end(), f, f + m_frame_n);
            if ((int) m_preroll.size() > m_preroll_n) {
                m_preroll.erase(m_preroll.begin(),
                                m_preroll.begin() + (m_preroll.size() - m_preroll_n));
            }

            m_run = speech ? m_run + 1 : 0;

            if (m_run >= m_onset_frames) {
                m_in_speech  = true;
                m_silence_run = 0;
                m_utt.clear();
                m_utt.insert(m_utt.end(), m_preroll.begin(), m_preroll.end());
                m_utt_start_ms = (int64_t)(m_total_n * 1000 / WHISPER_SAMPLE_RATE)
                                 - m_p.preroll_ms;
                if (m_utt_start_ms < 0) m_utt_start_ms = 0;
                m_preroll.clear();
                m_run = 0;
                if (m_p.verbose) fprintf(stderr, "[vad] onset (floor=%.5f e=%.5f)\n", m_floor, e);
            }
            return;
        }

        // in speech
        m_utt.insert(m_utt.end(), f, f + m_frame_n);
        m_silence_run = speech ? 0 : m_silence_run + 1;

        if (m_silence_run >= m_hang_frames) {
            finalize(out);
            return;
        }

        if ((int64_t) m_utt.size() >= m_max_n) {
            if (m_p.verbose) fprintf(stderr, "[vad] max length, forcing cut\n");
            finalize(out);
        }
    }

    void finalize(std::vector<utterance> & out) {
        // Trim the trailing silence down to pad_ms. This is the whole point:
        // the model must not see a long silent tail.
        const int64_t tail = (int64_t) m_silence_run * m_frame_n;
        int64_t keep = (int64_t) m_utt.size() - tail + m_pad_n;
        if (keep < 0)                        keep = 0;
        if (keep > (int64_t) m_utt.size())   keep = m_utt.size();
        m_utt.resize(keep);

        if ((int64_t) m_utt.size() >= m_min_n) {
            utterance u;
            u.id         = m_next_id++;
            u.pcm        = std::move(m_utt);
            u.t_start_ms = m_utt_start_ms;
            out.push_back(std::move(u));
            if (m_p.verbose) {
                fprintf(stderr, "[vad] utterance %d, %.2f s\n",
                        u.id, keep / (float) WHISPER_SAMPLE_RATE);
            }
        } else if (m_p.verbose) {
            fprintf(stderr, "[vad] discarded blip\n");
        }

        m_utt.clear();
        m_in_speech   = false;
        m_silence_run = 0;
        m_run         = 0;
    }

    const whisper_params & m_p;

    const int     m_frame_n;
    const int     m_onset_frames;
    const int     m_hang_frames;
    const int     m_preroll_n;
    const int     m_pad_n;
    const int64_t m_max_n;
    const int64_t m_min_n;

    std::vector<float> m_carry;
    std::vector<float> m_preroll;
    std::vector<float> m_utt;

    float   m_floor        = 0.0f;
    int     m_run          = 0;
    int     m_silence_run  = 0;
    bool    m_in_speech    = false;
    int64_t m_total_n      = 0;
    int64_t m_utt_start_ms = 0;
    int     m_next_id      = 0;
};

// ---------------------------------------------------------------------------
// output
// ---------------------------------------------------------------------------

static std::string json_escape(const std::string & s) {
    std::string o;
    o.reserve(s.size() + 16);
    for (unsigned char c : s) {
        switch (c) {
            case '"':  o += "\\\""; break;
            case '\\': o += "\\\\"; break;
            case '\n': o += "\\n";  break;
            case '\r': o += "\\r";  break;
            case '\t': o += "\\t";  break;
            default:
                if (c < 0x20) { char b[8]; snprintf(b, sizeof(b), "\\u%04x", c); o += b; }
                else          { o += (char) c; }
        }
    }
    return o;
}

static std::string run_pass(whisper_context * ctx,
                            const whisper_params & p,
                            const std::vector<float> & pcm,
                            bool translate) {
    whisper_full_params wp = whisper_full_default_params(
        p.beam_size > 1 ? WHISPER_SAMPLING_BEAM_SEARCH : WHISPER_SAMPLING_GREEDY);

    wp.print_progress   = false;
    wp.print_special    = false;
    wp.print_realtime   = false;
    wp.print_timestamps = false;
    wp.translate        = translate;
    wp.single_segment   = false;
    wp.max_tokens       = 0;
    wp.language         = p.language.c_str();
    wp.n_threads        = p.n_threads;
    wp.audio_ctx        = p.audio_ctx;
    wp.beam_search.beam_size = p.beam_size;

    // No cross-utterance prompt: consecutive utterances come from unrelated
    // speakers, and carrying context bends each one toward the last.
    wp.prompt_tokens   = nullptr;
    wp.prompt_n_tokens = 0;

    if (p.no_fallback) wp.temperature_inc = 0.0f;

    if (whisper_full(ctx, wp, pcm.data(), (int) pcm.size()) != 0) {
        return "";
    }

    std::string text;
    const int n = whisper_full_n_segments(ctx);
    for (int i = 0; i < n; i++) {
        text += whisper_full_get_segment_text(ctx, i);
    }
    return trim(text);
}

// ---------------------------------------------------------------------------
// main
// ---------------------------------------------------------------------------

int main(int argc, char ** argv) {
    ggml_backend_load_all();

    whisper_params params;
    if (!params_parse(argc, argv, params)) return 1;

    // stdout goes to a pipe in normal use; without this the C runtime block
    // buffers and transcripts arrive in bursts instead of immediately.
    setvbuf(stdout, nullptr, _IONBF, 0);

    if (params.language != "auto" && whisper_lang_id(params.language.c_str()) == -1) {
        fprintf(stderr, "error: unknown language '%s'\n", params.language.c_str());
        return 1;
    }

    // Ring buffer well above the max utterance so a slow poll cannot lose audio.
    audio_async audio(params.max_utt_ms + 5000);
    if (!audio.init(params.capture_id, WHISPER_SAMPLE_RATE)) {
        fprintf(stderr, "error: audio.init() failed\n");
        return 1;
    }

    whisper_context_params cparams = whisper_context_default_params();
    cparams.use_gpu    = params.use_gpu;
    cparams.flash_attn = params.flash_attn;

    whisper_context * ctx = whisper_init_from_file_with_params(params.model.c_str(), cparams);
    if (ctx == nullptr) {
        fprintf(stderr, "error: failed to initialize whisper context\n");
        return 2;
    }

    if (!whisper_is_multilingual(ctx)) {
        if (params.language != "en") {
            fprintf(stderr, "error: model is English-only -- cannot use -l %s.\n", params.language.c_str());
            fprintf(stderr, "       use ggml-large-v3 (NOT large-v3-turbo, which cannot translate)\n");
            whisper_free(ctx);
            return 3;
        }
        // An English-only model on English audio: the "English pass" would
        // just repeat the transcript, so run a single transcription pass.
        if (params.translate) {
            fprintf(stderr, "note: English-only model, translation pass disabled\n");
            params.translate  = false;
            params.transcribe = true;
        }
    }

    fprintf(stderr, "\n%s: lang=%s translate=%d transcribe=%d beam=%d threads=%d\n",
            __func__, params.language.c_str(), params.translate, params.transcribe,
            params.beam_size, params.n_threads);
    fprintf(stderr, "%s: onset=%dms hang=%dms preroll=%dms pad=%dms max=%dms\n\n",
            __func__, params.onset_ms, params.hang_ms, params.preroll_ms,
            params.pad_ms, params.max_utt_ms);

    utterance_queue    queue;
    std::atomic<bool>  running{true};

    // --- inference worker -------------------------------------------------
    std::thread worker([&]() {
        utterance u;
        while (queue.pop(u)) {
            const double dur = u.pcm.size() / (double) WHISPER_SAMPLE_RATE;
            const auto   t0  = std::chrono::high_resolution_clock::now();

            std::string src, eng;
            if (params.transcribe) src = run_pass(ctx, params, u.pcm, false);
            if (params.translate)  eng = run_pass(ctx, params, u.pcm, true);

            const auto t1 = std::chrono::high_resolution_clock::now();
            const auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(t1 - t0).count();

            if (src.empty() && eng.empty()) continue;

            if (params.text_out) {
                const int s = (int) (u.t_start_ms / 1000);
                const std::string & first = src.empty() ? eng : src;
                printf("[%02d:%02d] %s\n", s / 60, s % 60, first.c_str());
                if (!src.empty() && !eng.empty() && eng != src) {
                    printf("        -> %s\n", eng.c_str());
                }
                continue;
            }

            printf("{\"id\":%d,\"t\":%lld,\"dur\":%.2f,\"infer_ms\":%lld,"
                   "\"lang\":\"%s\",\"source\":\"%s\",\"english\":\"%s\"}\n",
                   u.id,
                   (long long) u.t_start_ms,
                   dur,
                   (long long) ms,
                   params.language.c_str(),
                   json_escape(src).c_str(),
                   json_escape(eng).c_str());
        }
    });

    // --- capture + segmentation ------------------------------------------
    audio.resume();

    // Discard the first moments; SDL emits a burst of garbage on open.
    std::this_thread::sleep_for(std::chrono::milliseconds(300));
    audio.clear();   // the ONLY clear in this file, before any speech exists

    segmenter seg(params);
    std::vector<utterance> ready;
    std::vector<float>     chunk;

    fprintf(stderr, "[listening]\n");

    while (running.load()) {
        if (!sdl_poll_events()) break;

        std::this_thread::sleep_for(std::chrono::milliseconds(40));

        // Take exactly the samples captured since the last read, so
        // consecutive reads tile the timeline without gaps or duplication.
        // (Reading the last N wall-clock ms does not: SDL delivers audio in
        // 64 ms blocks, so fixed-length reads repeat some blocks and skip others.)
        audio.get_new(chunk);

        if (chunk.empty()) continue;

        ready.clear();
        seg.feed(chunk, ready);
        for (auto & u : ready) {
            queue.push(std::move(u));
        }
    }

    // --- shutdown ---------------------------------------------------------
    fprintf(stderr, "\n[draining] %zu utterance(s) still queued\n", queue.size());

    audio.pause();

    ready.clear();
    seg.flush(ready);
    for (auto & u : ready) queue.push(std::move(u));

    queue.close();
    worker.join();

    whisper_print_timings(ctx);
    whisper_free(ctx);
    return 0;
}
