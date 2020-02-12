import audioop
import time

from pyaudio import PyAudio, get_sample_size, paContinue, paInt16


# TODO: Add tray icon
# TODO: Add hotkey to start/stop
# TODO: Add volume control?


SAMPLE_RATE = 48000
CHANNELS = 1
SAMPLE_FORMAT = paInt16

sample_width = get_sample_size(SAMPLE_FORMAT)
volume_factor = 1.0  # Comfort effective range is between 0.5 and 3


def audio_stream_callback(in_data, frame_count, time_info, status_flags):
    global volume_factor
    frame = audioop.mul(in_data, sample_width, volume_factor)
    return (frame, paContinue)


def main():
    global volume_factor
    stream = PyAudio().open(SAMPLE_RATE, CHANNELS, SAMPLE_FORMAT, input=True, output=True, stream_callback=audio_stream_callback, start=True)

    try:
        while stream.is_active():
            volume_factor = float(input('Volume factor: '))
            #time.sleep(10)
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == '__main__':
    main()
