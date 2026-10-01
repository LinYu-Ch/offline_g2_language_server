#pragma once

#include <SDL.h>
#include <SDL_audio.h>

#include <atomic>
#include <cstdint>
#include <vector>
#include <mutex>

//
// SDL Audio capture
//

class audio_async {
public:
    audio_async(int len_ms);
    ~audio_async();

    bool init(int capture_id, int sample_rate);

    // start capturing audio via the provided SDL callback
    // keep last len_ms seconds of audio in a circular buffer
    bool resume();
    bool pause();
    bool clear();

    // callback to be called by SDL
    void callback(uint8_t * stream, int len);

    // get audio data from the circular buffer
    void get(int ms, std::vector<float> & audio);

    // get the audio captured since the previous get_new() or clear(), so that
    // consecutive calls tile the stream with no gaps or repeats. If the caller
    // falls more than len_ms behind, the oldest samples are already overwritten.
    void get_new(std::vector<float> & audio);

private:
    SDL_AudioDeviceID m_dev_id_in = 0;

    int m_len_ms = 0;
    int m_sample_rate = 0;

    std::atomic_bool m_running;
    std::mutex       m_mutex;

    std::vector<float> m_audio;
    size_t             m_audio_pos = 0;
    size_t             m_audio_len = 0;

    uint64_t           m_n_written = 0; // total samples received by callback()
    uint64_t           m_n_read    = 0; // m_n_written as of the last get_new()
};

// Return false if need to quit
bool sdl_poll_events();
