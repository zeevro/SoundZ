from SoundZ.streams import SoundZMinimalStream, UdpSocketIO, DEFAULT_PORT
import threading

from SoundZ.audio import Audio


class SoundZUdpMinReceiver:
    def __init__(self, port=DEFAULT_PORT, interface=None):
        self._port = port
        self._interface = interface
        self._socket = UdpSocketIO()
        self._stream = SoundZMinimalStream(self._socket)
        self._audio = Audio(output_needed=True).get_params_from_stream(self._stream)
        self._thread = None
        self._stopped = False

    def _thread_func(self):
        for frame in self._stream:
            self._audio.playback(frame)
            if self._stopped:
                break

    def start(self):
        self._socket.rx(self._port, self._interface)
        self._thread = threading.Thread(target=self._thread_func)
        self._thread.start()

    def stop(self):
        if self._thread is not None and not self._stopped:
            self._stopped = True
            self._thread.join(0.5)
            self._thread = None

    def join(self, timeout):
        self._thread.join(timeout)

    def close(self):
        self.stop()
        self._audio.close()
        self._socket.close()


def main():
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument('-p', '--port', type=int, default=DEFAULT_PORT)
    p.add_argument('-i', '--interface')
    args = p.parse_args()

    s = SoundZUdpMinReceiver(args.port, args.interface)
    print(s._stream)

    print('Starting.')
    s.start()

    try:
        while 1:
            s.join(0.5)
    except (KeyboardInterrupt, SystemExit):
        print('Stopping.')
    finally:
        s.close()

    print('Done.')


if __name__ == "__main__":
    main()
