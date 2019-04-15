import pyaudio
import wave
import time
from contextlib import closing


FRAMES_PER_CHUNK = 1024


g_pyaudio = pyaudio.PyAudio()


def play_wave_file(filename):
    with wave.open(filename) as wf:
        chunk_size = (wf.getnchannels() * wf.getsampwidth()) * FRAMES_PER_CHUNK
        with closing(g_pyaudio.open(wf.getframerate(), wf.getnchannels(), pyaudio.get_format_from_width(wf.getsampwidth()), output=True)) as player:
            data = bytes(chunk_size)
            while len(data) == chunk_size:
                data = wf.readframes(1024)
                player.write(data)


def play_wave_file_async(filename):
    wf = wave.open(filename)

    chunk_size = (wf.getnchannels() * wf.getsampwidth()) * FRAMES_PER_CHUNK

    def stream_callback(in_data, frame_count, time_info, status_flags):
        data = wf.readframes(1024)
        if len(data) < chunk_size:
            wf.close()
            res = pyaudio.paAbort
            data += bytes(chunk_size - len(data))
        else:
            res = pyaudio.paContinue
        return data, res

    return g_pyaudio.open(wf.getframerate(), wf.getnchannels(), pyaudio.get_format_from_width(wf.getsampwidth()), output=True, stream_callback=stream_callback, start=True)


# for i in range(1):
#     play_wave_file(r'F:\ZEEV-PC\Archive\VSE600ENU1\VFP98\GALLERY\MEDIA\CHIMES.WAV')

for i in range(1):
    play_wave_file_async(r'F:\ZEEV-PC\Archive\VSE600ENU1\VFP98\GALLERY\MEDIA\CHIMES.WAV')
    time.sleep(1)
