from SoundZ.streams import SoundZSyncingStreamDatagram, UdpSocketIO, DEFAULT_PORT
from SoundZ.audio import Audio
import threading


class SoundZUdpReceiver:
    def __init__(self, port=DEFAULT_PORT, interface=None):
        self._port = port
        self._interface = interface
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
        self._socket.rx(self._port, self._interface)
        self._stream.wait_for_sync()
        print('Got sync!')
        print(self._stream)
        self._audio.get_params_from_stream(self._stream)
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

    print('Start.')

    s = SoundZUdpReceiver(args.port, args.interface)
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
