from SoundZ.streams import UdpSocketIO
from SoundZ.audio import Audio

import queue
import time
import os

import new_soundz
from inspect import isclass


RECORD_TIME = 2


class BytesPipeIO(queue.Queue):
    def write(self, data):
        for c in data:
            self.put(c)

    def read(self, length):
        ret = []
        for _i in range(length):
            ret.append(self.get())
        return bytes(ret)


def test_pipe(cls, file_header=False):
    print(f'Testing {cls.__name__} through byte-pipe{" with file header" if file_header else ""}')
    if 1:
        print('skip')
        return

    pipe = BytesPipeIO()

    receiver_stream = cls(pipe)
    sender_stream = cls(pipe)
    if file_header:
        sender_stream.write_file_header()

    audio = Audio(input_needed=True, output_needed=True)
    audio.get_params_from_stream(sender_stream)
    audio.add_callback(sender_stream.write_packet)
    audio.start_capture()

    stop_time = time.time() + RECORD_TIME
    for packet in receiver_stream:
        audio.playback(packet)
        if time.time() >= stop_time:
            break

    audio.stop_capture()
    audio.close()


def test_with_file(cls, record=True, playback=True):
    fn = os.path.join(os.path.dirname(__file__), f'test_{cls.__name__}.sndz')
    print(f'Testing {cls.__name__} recording to file {fn}')

    if record:
        with open(fn, 'wb') as file:
            stream = cls(file)

            audio = Audio(input_needed=True)
            audio.get_params_from_stream(stream)
            audio.add_callback(stream.write_packet)
            audio.start_capture()

            time.sleep(RECORD_TIME)

            audio.stop_capture()
            audio.close()

    if playback:
        with open(fn, 'rb') as file:
            stream = cls(file)

            audio = Audio(output_needed=True)
            audio.get_params_from_stream(stream)

            for packet in stream:
                audio.playback(packet)

            audio.close()


def test_udp(cls, file_header=False):
    print(f'Testing {cls.__name__} through UDP{" with file header" if file_header else ""}')
    if 1:
        print('skip')
        return

    receiver_stream = cls(UdpSocketIO().rx())
    sender_stream = cls(UdpSocketIO().tx('127.0.0.1'))
    if file_header:
        sender_stream.write_file_header()

    audio = Audio(input_needed=True, output_needed=True)
    audio.get_params_from_stream(sender_stream)
    audio.add_callback(sender_stream.write_packet)
    audio.start_capture()

    stop_time = time.time() + RECORD_TIME
    for packet in receiver_stream:
        audio.playback(packet)
        if time.time() >= stop_time:
            break

    audio.stop_capture()
    audio.close()


def run_all_tests():
    print('Start.')

    for name in dir(new_soundz):
        o = getattr(new_soundz, name)

        if (not isclass(o)) or (name is 'AbstractSoundZStream') or (not issubclass(o, new_soundz.AbstractSoundZStream)):
            continue

        if name.endswith('DatagramStream'):
            test_func = test_udp
        elif name.endswith('Stream'):
            test_func = test_pipe
        else:
            continue

        print('-' * 30)
        test_func(o)

        if issubclass(o, new_soundz.FileHeaderMixin):
            print('-' * 30)
            test_func(o, file_header=True)

        if test_func == test_pipe:
            print('-' * 30)
            test_with_file(o)

    print('Done.')


if __name__ == "__main__":
    run_all_tests()
