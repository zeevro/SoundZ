from soundz import SoundZSyncingStreamDatagram, UdpSocketIO, Audio, DEFAULT_PORT
import threading
import time


class SoundZUdpReceiver:
    def __init__(self, port=DEFAULT_PORT):
        self._port = port
        self._socket = UdpSocketIO()
        self._stream = SoundZSyncingStreamDatagram(self._socket)
        self._audio = Audio(output_needed=True)
        self._thread = None
        self._stopped = False

    def _thread_func(self):
        for frame in self._stream:
            self._audio.playback(frame)
            if self._stopped:
                break

    def start(self):
        self._socket.listening(self._port)
        self._stream.wait_for_sync()
        self._audio.get_params_from_soundz(self._stream)
        self._thread = threading.Thread(target=self._thread_func)
        self._thread.start()

    def stop(self):
        if self._thread is not None and not self._stopped:
            self._stopped = True
            self._thread.join(0.5)
            self._thread = None

    def close(self):
        self.stop()
        self._audio.close()
        self._socket.close()


def main():
    print('Start.')

    s = SoundZUdpReceiver()
    s.start()

    while 1:
        time.sleep(1)

    s.stop()

    print('Done.')


if __name__ == "__main__":
    main()
