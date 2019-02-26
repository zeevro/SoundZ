import pyaudio
import struct
import io
import socket
import audioop
import time
import os

try:
    import opuslib
except ImportError:
    # Help poor opuslib to fine opus.dll
    if os.name == 'nt':
        os.environ['PATH'] = os.path.dirname(__file__) + os.pathsep + os.environ['PATH']
    import opuslib


# TODO: Calculate the right buffer size for the input stream
# TODO: Calculate samples per frame so opuslib is happy with frame duration
# TODO: Opus bitrate?
# TODO: Play around with parameters in general - namely sample rate
# TODO: Write real tests
# TODO: Handle parameters change in SoundZSyncingStream


FILE_HEADER_MAGIC = b'SndZ'
FILE_HEADER_STRUCT = struct.Struct('<LBBBB')
PACKET_HEADER_MAGIC = b'pktZ'
PACKET_HEADER_STRUCT = struct.Struct('<H')


DEFAULT_PORT = 4453


class TcpSocketWrapperIO:
    def __init__(self, sock):
        self._sock = sock

    def write(self, data):
        return self._sock.send(data)

    def read(self, length):
        return self._sock.recv(length)


class UdpSocketIO(socket.socket):
    def __init__(self, timeout=10):
        super(UdpSocketIO, self).__init__(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self.settimeout(timeout)
        self._target = None

    def listening(self, port=DEFAULT_PORT, interface=None):
        if interface is None:
            interface = '0.0.0.0'
        self.bind((interface, port))
        return self

    def sending(self, ip, port=DEFAULT_PORT):
        self._target = (ip, port)
        return self

    def write(self, data):
        return self.sendto(data, self._target)

    def read(self, length):
        return self.recv(0xFFFF)


class _datagram_io:
    '''Wraps a SoundZBasicStream's datagram-based IO and turns it into a stream-like IO'''

    def __init__(self, parent):
        self._parent = parent

    def __enter__(self):
        self._write_buf = io.BytesIO()
        self._read_buf = io.BytesIO()
        self._orig_parent_io = self._parent._io
        self._actual_io = self._orig_parent_io
        while isinstance(self._actual_io, self.__class__):
            self._actual_io = self._actual_io._orig_parent_io
        self._parent._io = self

    def write(self, data):
        return self._write_buf.write(data)

    def read(self, length):
        ret = self._read_buf.read(length)
        while len(ret) < length:
            self._read_buf = io.BytesIO(self._actual_io.read(0xFFFF))
            ret += self._read_buf.read(length - len(ret))
        return ret

    def __exit__(self, *a):
        self._parent._io = self._orig_parent_io

        written = self._write_buf.getvalue()
        if written:
            self._actual_io.write(written)


class DatagramMixin:
    '''Uses _datagram_io to support streaming over datagram-based IOs'''

    def write_file_header(self):
        with _datagram_io(self):
            super(DatagramMixin, self).write_file_header()

    def write_packet(self, packet):
        with _datagram_io(self):
            super(DatagramMixin, self).write_packet(packet)

    def wait_for_sync(self):
        with _datagram_io(self):
            return super(DatagramMixin, self).wait_for_sync()

    def read_packet(self):
        with _datagram_io(self):
            return super(DatagramMixin, self).read_packet()


class SoundZBasicStream:
    '''A dead-simple steramable audio format. Carries no data about the audio inside.'''

    def __init__(self, _io, sample_rate=48000, channels=1, frame_samples=120, sample_format=pyaudio.paInt16, compressed=True, opus_app=opuslib.APPLICATION_VOIP):
        self._io = _io

        self.sample_rate = sample_rate
        self.channels = channels
        self.frame_samples = frame_samples
        self.sample_format = sample_format
        self.compressed = compressed
        self._opus_app = opus_app

        self._packet_count = 0
        self._frame_bytes = channels * frame_samples * pyaudio.get_sample_size(sample_format)

        self._encoder = None
        self._decoder = None

    def _get_encoder(self):
        if self._encoder is None:
            self._encoder = opuslib.Encoder(self.sample_rate, self.channels, self._opus_app)
            self._encoder.bitrate = 192 * 1024  # What is this good for?
        return self._encoder

    def _get_decoder(self):
        if self._decoder is None:
            self._decoder = opuslib.Decoder(self.sample_rate, self.channels)
        return self._decoder

    def get_params_from_soundz(self, soundz):
        self.sample_rate = soundz.sample_rate
        self.channels = soundz.channels
        self.frame_samples = soundz.frame_samples
        self.sample_format = soundz.sample_format
        self.compressed = soundz.compressed
        self._opus_app = soundz._opus_app

    def get_params_from_audio(self, audio):
        self.sample_rate = audio.sample_rate
        self.channels = audio.channels
        self.frame_samples = audio.frame_samples
        self.sample_format = audio.sample_format

    @property
    def frame_bytes(self):
        return self._frame_bytes

    def write_packet(self, packet):
        if self.compressed:
            packet = self._get_encoder().encode(packet, self.frame_samples)
        self._io.write(PACKET_HEADER_STRUCT.pack(len(packet)))
        self._io.write(packet)

    def write_packets(self, packets):
        for packet in packets:
            self.write_packet(packet)

    def read_packet(self):
        packet_header = self._io.read(PACKET_HEADER_STRUCT.size)
        if not packet_header:  # EOF
            return b''
        packet_size, = PACKET_HEADER_STRUCT.unpack(packet_header)
        packet = self._io.read(packet_size)
        if self.compressed:
            packet = self._get_decoder().decode(packet, self.frame_samples)
        return packet

    def iter_packets(self):
        p = self.read_packet()
        while p:
            yield p
            p = self.read_packet()

    __iter__ = iter_packets


class SoundZFileStream(SoundZBasicStream):
    '''This adds a file magic, file header, and packet magic to mark the starts of packets. Can be streamed or saved to a file. Don't forget to call write_file_header()!!'''

    def __init__(self, *a, **kw):
        super(SoundZFileStream, self).__init__(*a, **kw)
        self._packet_count = 0

    @property
    def packet_count(self):
        return self._packet_count

    @property
    def current_timestamp(self):
        return self._packet_count * self.frame_samples / (self.sample_rate * self.channels)

    def write_file_header(self):
        self._io.write(FILE_HEADER_MAGIC)
        self._io.write(FILE_HEADER_STRUCT.pack(self.sample_rate, self.channels, self.frame_samples, self.sample_format, self.compressed))

    def write_packet(self, packet):
        self._io.write(PACKET_HEADER_MAGIC)
        super(SoundZFileStream, self).write_packet(packet)
        self._packet_count += 1

    def _process_file_header(self):
        file_header = self._io.read(FILE_HEADER_STRUCT.size)

        sample_rate, channels, frame_samples, sample_format, compressed = FILE_HEADER_STRUCT.unpack(file_header)

        assert channels > 0, 'Must have at least one channel'
        pyaudio.get_sample_size(sample_format)  # Make sure the format is valid

        self.sample_rate = sample_rate
        self.channels = channels
        self.frame_samples = frame_samples
        self.sample_format = sample_format
        self.compressed = bool(compressed)

        return self

    @classmethod
    def from_file(cls, file):
        assert file.read(len(FILE_HEADER_MAGIC)) == FILE_HEADER_MAGIC, 'Bad file header magic'

        return cls(file)._process_file_header()

    def read_packet(self):
        packet_header_magic = self._io.read(len(PACKET_HEADER_MAGIC))
        if not packet_header_magic:  # EOF
            return b''
        packet = super(SoundZFileStream, self).read_packet()
        self._packet_count += 1
        return packet


class SoundZSyncingStream(SoundZFileStream):
    '''This adds a self-synchronizing element for the stream meta-data by inserting a file header every 100 packets so it can be joined by a listened mid-stream.'''

    def __init__(self, *a, **kw):
        super(SoundZSyncingStream, self).__init__(*a, **kw)
        self._synced = False

    @property
    def is_synced(self):
        return self._synced

    def write_packet(self, packet):
        if self._packet_count % 100 == 0:
            self.write_file_header()
        super(SoundZSyncingStream, self).write_packet(packet)

    def _wait_for_file_header_magic(self):
        while 1:
            for header_c in FILE_HEADER_MAGIC:
                stream_c = self._io.read(1)
                if header_c not in stream_c:  # Works like "==" but between int and bytes
                    break
            else:
                break

    def wait_for_sync(self):
        if (not self._synced) or self._packet_count % 100 == 0:
            self._wait_for_file_header_magic()
            self._process_file_header()
            if not self._synced:
                self._packet_count = 0
            self._synced = True

    def read_packet(self):
        self.wait_for_sync()

        try:
            return super(SoundZSyncingStream, self).read_packet()
        except Exception:
            self._synced = False
            return self.read_packet()


class SoundZBasicStreamDatagram(DatagramMixin, SoundZBasicStream):
    pass


class SoundZFileStreamDatagram(DatagramMixin, SoundZFileStream):
    pass


class SoundZSyncingStreamDatagram(DatagramMixin, SoundZSyncingStream):
    pass


class Audio:
    def __init__(self, input_needed=False, output_needed=False, sample_rate=48000, channels=1, frame_samples=120, sample_format=pyaudio.paInt16):
        self.sample_rate = sample_rate
        self.channels = channels
        self.frame_samples = frame_samples
        self.sample_format = sample_format

        self.sample_size = pyaudio.get_sample_size(sample_format)
        self.frame_bytes = frame_samples * channels * self.sample_size

        self._input_needed = input_needed
        self._output_needed = output_needed

        self._audio = None
        self._input_stream = None
        self._output_stream = None

        self._callback = None

    def _input_callback(self, in_data, frame_count, time_info, status_flags):
        buf = io.BytesIO(in_data)
        while 1:
            frame = buf.read(self.frame_bytes)
            if not frame:
                break
            try:
                self._callback(frame)
            except Exception:
                pass
        return (None, 0)

    def get_params_from_soundz(self, soundz):
        self.sample_rate = soundz.sample_rate
        self.channels = soundz.channels
        self.frame_samples = soundz.frame_samples
        self.sample_format = soundz.sample_format

        return self

    def initialize(self):
        if self._audio is None:
            self._audio = pyaudio.PyAudio()

        if self._input_needed and self._input_stream is None:
            host_api = self._audio.get_default_host_api_info()
            device = self._audio.get_device_info_by_index(host_api['defaultInputDevice'])

            self._input_stream = self._audio.open(format=self.sample_format,
                                                  channels=self.channels,
                                                  rate=self.sample_rate,
                                                  input=True,
                                                  frames_per_buffer=self.frame_samples,  # TODO: Figure this out
                                                  input_device_index=device['index'],
                                                  stream_callback=self._input_callback)

        if self._output_needed and self._output_stream is None:
            host_api = self._audio.get_default_host_api_info()
            device = self._audio.get_device_info_by_index(host_api['defaultOutputDevice'])

            self._output_stream = self._audio.open(format=self.sample_format,
                                                   channels=self.channels,
                                                   rate=self.sample_rate,
                                                   output=True,
                                                   frames_per_buffer=self.frame_samples,
                                                   input_device_index=device['index'])

    def set_callback(self, func):
        self._callback = func
        return self

    def start_capture(self):
        assert self._callback is not None, 'No callback set'
        self.initialize()
        self._input_stream.start_stream()
        return self

    def stop_capture(self):
        self._input_stream.stop_stream()
        return self

    def playback(self, data):
        self.initialize()
        self._output_stream.write(data)

    def close(self):
        if self._output_stream is not None:
            if not self._output_stream.is_stopped():
                self._output_stream.stop_stream()
            self._output_stream.close()
            self._output_stream = None

        if self._input_stream is not None:
            if not self._input_stream.is_stopped():
                self._input_stream.stop_stream()
            self._input_stream.close()
            self._input_stream = None

        if self._audio is not None:
            self._audio.terminate()
            self._audio = None

    def __enter__(self):
        self.initialize()
        return self

    def __exit__(self, *a):
        self.close()


class Vox:
    def __init__(self, threshold=800, timeout=0.4):
        self.threshold = threshold
        self.timeout = timeout
        self._breach_time = None
        self._audio = None

    def _audio_set_callback(self, func):
        self._callback = func

    def _audio_callback(self, frame):
        volume = audioop.rms(frame, self._audio.sample_size)
        if self.is_breached(volume):
            self._callback(frame)

    def is_breached(self, volume):
        if volume < self.threshold:
            if self._breach_time is None:
                self._breach_time = time.time()
            elif self._breach_time + self.timeout < time.time():
                return False
        else:
            self._breach_time = None

        return True

    def attach_to_audio(self, audio):
        self._audio = audio
        self._callback = self._audio._callback
        self._audio._callback = self._audio_callback
        self._audio.set_callback = self._audio_set_callback
        return self
