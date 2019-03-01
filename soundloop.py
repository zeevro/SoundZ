from pyaudio import PyAudio, paInt16, paContinue
import time


# TODO: Add tray icon
# TODO: Add hotkey to start/stop
# TODO: Add volume control?


SAMPLE_RATE = 48000
CHANNELS = 1
SAMPLE_FORMAT = paInt16


def main():
    def callback(in_data, frame_count, time_info, status_flags):
        return(in_data, paContinue)

    PyAudio().open(SAMPLE_RATE, CHANNELS, SAMPLE_FORMAT, input=True, output=True, stream_callback=callback, start=True)

    try:
        while 1:
            time.sleep(10)
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == '__main__':
    main()
