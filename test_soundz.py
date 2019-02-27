from soundz import *

from binascii import hexlify
import queue


RECORD_TIME = 3


class DummyAudio:
    def __init__(self, *a, **kw):
        pass

    def get_params_from_soundz(self, soundz):
        return self

    def playback(self, *a, **kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a, **kw):
        pass


class BytesPipeIO(queue.Queue):
    def write(self, data):
        for c in data:
            self.put(c)

    def read(self, length):
        ret = []
        for _i in range(length):
            ret.append(self.get())
        return bytes(ret)


def _test_channels_str(channels):
    if channels == 1:
        return 'Mono'
    if channels == 2:
        return 'Stereo'
    return f'{channels} channels'


def test_loopback_nofile():
    print('Testing audio loopback')

    audio = Audio(input_needed=True, output_needed=True)
    audio.add_callback(audio.playback)
    audio.start_capture()

    time.sleep(RECORD_TIME)

    audio.stop_capture()
    audio.close()


def test_record_write(fn='test.sndz', compressed=True):
    print(f'Testing record -> {fn}{" compressed" if compressed else ""}')

    with Audio(input_needed=True) as ac:
        ac.initialize()
        print(f'Input stream specs: Sample rate: {ac.sample_rate / 1000} kHz, {_test_channels_str(ac.channels)}, {ac.frame_samples} samples per frame, {pyaudio.get_sample_size(ac.sample_format)} bytes per sample.')
        with open(fn, 'wb') as f:
            sf = SoundZFileStream(f, compressed=compressed)
            sf.get_params_from_audio(ac)
            sf.write_file_header()

            ac.add_callback(sf.write_packet)
            print('Recording...')
            ac.start_capture()
            while sf.current_timestamp < RECORD_TIME:
                pass
            ac.stop_capture()
            print('OK')

            print(f'Recorded {sf.packet_count} packets with {sf.packet_count * sf.frame_samples} samples for a total duration of {sf.current_timestamp} s')


def test_read_write(source_fn, dest_fn, compressed=None):
    print(f'Testing {source_fn} -> {dest_fn}{" compressed" if compressed else ""}{" retain compression" if compressed is None else ""}')

    with open(source_fn, 'rb') as rf:
        rsf = SoundZFileStream.from_file(rf)
        print(f'File specs: Sample rate: {rsf.sample_rate / 1000} kHz, {_test_channels_str(rsf.channels)}, Frame size: {rsf.frame_samples} samples{", Compressed" if rsf.compressed else ""}.')

        if compressed is None:
            compressed = rsf.compressed

        with open(dest_fn, 'wb') as wf:
            wsf = SoundZFileStream(wf)
            wsf.get_params_from_soundz(rsf)
            wsf.compressed = compressed
            wsf.write_file_header()
            wsf.write_packets(rsf)

        print(f'File had {rsf.packet_count} packets with a total duration of {rsf.current_timestamp:.4f} s')


def test_read(fn='test.sndz', playback=False):
    print(f'Testing read {fn}{" with playback" if playback else ""}')

    audio_class = Audio if playback else DummyAudio

    with open(fn, 'rb') as f:
        sf = SoundZFileStream.from_file(f)
        print(f'File specs: Sample rate: {sf.sample_rate / 1000} kHz, {_test_channels_str(sf.channels)}, {sf.frame_samples} samples per frame, {pyaudio.get_sample_size(sf.sample_format)} bytes per sample{", Compressed" if sf.compressed else ""}.')

        with audio_class(output_needed=True).get_params_from_soundz(sf) as ac:
            ts = 0
            start_time = time.time()
            for packet in sf:
                print(f'[{ts:8.4f}s] <{len(packet)}> {hexlify(packet).decode()}')
                ts = sf.current_timestamp
                ac.playback(packet)
            if playback:
                print(f'Playback took {time.time() - start_time:.4f} s')

        print(f'File had {sf.packet_count} packets with a total duration of {sf.current_timestamp:.4f} s')


def test_tcp():
    print('Testing audio loopback using SoundZFileStream through TCP')

    sender = socket.socket()
    receiver_server = socket.socket()

    receiver_server.bind(('127.0.0.1', DEFAULT_PORT))
    receiver_server.listen(0)
    sender.connect(('127.0.0.1', DEFAULT_PORT))
    receiver, _ = receiver_server.accept()
    receiver_server.close()

    sender_sndz = SoundZFileStream(TcpSocketWrapperIO(sender))
    sender_sndz.write_file_header()

    receiver_sndz = SoundZFileStream.from_file(TcpSocketWrapperIO(receiver))

    audio = Audio(input_needed=True, output_needed=True)
    audio.get_params_from_soundz(sender_sndz)
    audio.add_callback(sender_sndz.write_packet)
    audio.start_capture()

    stop_time = time.time() + RECORD_TIME
    for packet in receiver_sndz:
        audio.playback(packet)
        if time.time() >= stop_time:
            break

    audio.stop_capture()
    audio.close()

    receiver.close()


def test_pipe():
    print('Testing audio loopback using SoundZFileStream through pipe')

    pipe = BytesPipeIO()

    sender_sndz = SoundZFileStream(pipe)
    sender_sndz.write_file_header()

    receiver_sndz = SoundZFileStream.from_file(pipe)

    audio = Audio(input_needed=True, output_needed=True)
    audio.get_params_from_soundz(sender_sndz)
    audio.add_callback(sender_sndz.write_packet)
    audio.start_capture()

    stop_time = time.time() + RECORD_TIME
    for packet in receiver_sndz:
        audio.playback(packet)
        if time.time() >= stop_time:
            break

    audio.stop_capture()
    audio.close()


def test_syncing_stream_pipe():
    print('Testing audio loopback using SoundZFileStream through pipe')

    pipe = BytesPipeIO()

    receiver_sndz = SoundZSyncingStream(pipe)
    sender_sndz = SoundZSyncingStream(pipe)

    audio = Audio(input_needed=True, output_needed=True)
    audio.get_params_from_soundz(sender_sndz)
    audio.add_callback(sender_sndz.write_packet)
    audio.start_capture()

    stop_time = time.time() + RECORD_TIME
    for packet in receiver_sndz:
        audio.playback(packet)
        if time.time() >= stop_time:
            break

    audio.stop_capture()
    audio.close()


def test_syncing_stream_udp():
    print('Testing audio loopback using SoundZFileStream through UDP')

    receiver_sndz = SoundZSyncingStreamDatagram(UdpSocketIO().listening())
    sender_sndz = SoundZSyncingStreamDatagram(UdpSocketIO().sending('127.0.0.1'))

    audio = Audio(input_needed=True, output_needed=True)
    audio.get_params_from_soundz(sender_sndz)
    audio.add_callback(sender_sndz.write_packet)
    audio.start_capture()

    stop_time = time.time() + RECORD_TIME
    for packet in receiver_sndz:
        audio.playback(packet)
        if time.time() >= stop_time:
            break

    audio.stop_capture()
    audio.close()


def test_vox():
    volume_values = [1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 6, 6, 6, 6, 7, 7, 7, 7, 6, 6, 6, 3, 3, 6, 6, 6, 6, 6, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 7, 7, 7, 7, 7, 7, 7, 7, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3]
    tx_expected = [1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    vox = Vox(threshold=5, timeout=0.05)
    start_time = time.time()
    for volume, expected in zip(volume_values, tx_expected):
        tx = int(vox.is_breached(volume))  # The int() is just so I could write "assert tx is expected" in the next line :)
        assert tx is expected, f'Expected {expected} but found {tx}'
        print(f'[{int((time.time() - start_time) * 100):2}] volume={volume}', end='')
        if tx:
            print(' TX', end='')
        print()
        time.sleep(0.01)


def run_all_tests():
    print('Start.')

    os.chdir(os.path.abspath(os.path.dirname(__file__)))

    test_loopback_nofile()  # Just a sanity check to see that the audio works
    test_record_write('test_raw.sndz', False)
    test_read('test_raw.sndz', True)
    test_read_write('test_raw.sndz', 'test_compressed.sndz', compressed=True)
    test_read('test_compressed.sndz', True)
    test_read_write('test_compressed.sndz', 'test_raw_2.sndz', compressed=False)
    test_read('test_raw_2.sndz', True)
    test_tcp()
    test_pipe()
    test_syncing_stream_pipe()
    test_syncing_stream_udp()
    test_vox()

    print('Done.')


if __name__ == "__main__":
    run_all_tests()
