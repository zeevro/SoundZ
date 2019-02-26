from soundz import SoundZSyncingStreamDatagram, UdpSocketIO, Audio, Vox, DEFAULT_PORT
import time


class SoundZUdpSender:
    def __init__(self, ip, port=DEFAULT_PORT):
        self._stream = SoundZSyncingStreamDatagram(UdpSocketIO().sending(ip, port))
        self._audio = Audio(input_needed=True).get_params_from_soundz(self._stream).set_callback(self._stream.write_packet)
        self._vox = Vox().attach_to_audio(self._audio)

    def start(self):
        self._audio.start_capture()

    def stop(self):
        self._audio.stop_capture()

    def close(self):
        self._audio.close()


def main():
    print('Start.')

    s = SoundZUdpSender('127.0.0.1')
    s.start()

    while 1:
        time.sleep(1)

    s.stop()

    print('Done.')


if __name__ == "__main__":
    main()
