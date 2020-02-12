import pyaudio
import io
import os
import socket
import struct
import time

from ._opuslib import opuslib


# TODO: Calculate samples per frame so opuslib is happy with frame duration
# TODO: Opus bitrate?
# TODO: Handle parameters change in SoundZSyncingStream


FILE_HEADER_MAGIC = b'SndZ'
FILE_HEADER_STRUCT = struct.Struct('<LBBBB')
PACKET_HEADER_MAGIC = b'pktZ'
PACKET_HEADER_STRUCT = struct.Struct('<H')


DEFAULT_SAMPLE_RATE = 12000
DEFAULT_CHANNELS = 1
DEFAULT_SAMPLES_PER_FRAME = 120
DEFAULT_SAMPLE_FORMAT = pyaudio.paInt16
DEFAULT_COMPRESSED = True
DEFAULT_OPUS_APPLICATION = opuslib.APPLICATION_VOIP

DEFAULT_PORT = 4453


sample_format_names = {getattr(pyaudio, f'pa{name}'): name for name in ['Int8', 'UInt8', 'Int16', 'Int24', 'Int32', 'Float32']}


class TcpSocketWrapperIO:
    def __init__(self, sock):
        self._sock = sock

    def write(self, data):
        return self._sock.send(data)

    def read(self, length):
        return self._sock.recv(length)


class UdpSocketIO(socket.socket):
    def __init__(self, timeout=None):
        super().__init__(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        if timeout:
            self.settimeout(timeout)
        self._target = None

    def rx(self, port=DEFAULT_PORT, interface=None):
        if interface is None:
            interface = '0.0.0.0'
        #print(f'rx {interface}:{port}')
        self.bind((interface, port))
        return self

    def tx(self, ip, port=DEFAULT_PORT):
        #print(f'tx {ip}:{port}')
        self._target = (ip, port)
        return self

    def write(self, data):
        #print(f'send {len(data)} bytes to {self._target[0]}:{self._target[1]}')
        return self.sendto(data, self._target)

    def read(self, length=None):
        #print('recv')
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
            super().write_file_header()

    def write_packet(self, packet):
        with _datagram_io(self):
            super().write_packet(packet)

    def wait_for_sync(self):
        with _datagram_io(self):
            return super().wait_for_sync()

    def read_packet(self):
        with _datagram_io(self):
            return super().read_packet()


class SoundZMinimalStream:
    '''The simplest stream imaginable. Only sends the raw frames. Works only on datagram-based IOs (since no packet size is encoded).'''

    def __init__(self, _io, sample_rate=DEFAULT_SAMPLE_RATE, channels=DEFAULT_CHANNELS,
                 samples_per_frame=DEFAULT_SAMPLES_PER_FRAME, sample_format=DEFAULT_SAMPLE_FORMAT,
                 compressed=DEFAULT_COMPRESSED, opus_app=DEFAULT_OPUS_APPLICATION):
        self._io = _io

        self.sample_rate = sample_rate
        self.channels = channels
        self.samples_per_frame = samples_per_frame
        self.sample_format = sample_format
        self.compressed = compressed
        self._opus_app = opus_app

        self._packet_count = 0

        self._encoder = None
        self._decoder = None

    def _get_encoder(self):
        if self._encoder is None:
            self._encoder = opuslib.Encoder(self.sample_rate, self.channels, self._opus_app)
        return self._encoder

    def _get_decoder(self):
        if self._decoder is None:
            self._decoder = opuslib.Decoder(self.sample_rate, self.channels)
        return self._decoder

    def get_params_from_stream(self, soundz):
        self.sample_rate = soundz.sample_rate
        self.channels = soundz.channels
        self.samples_per_frame = soundz.samples_per_frame
        self.sample_format = soundz.sample_format
        self.compressed = soundz.compressed
        self._opus_app = soundz._opus_app

    def get_params_from_audio(self, audio):
        self.sample_rate = audio.sample_rate
        self.channels = audio.channels
        self.samples_per_frame = audio.samples_per_frame
        self.sample_format = audio.sample_format

    def write_packet(self, frame):
        if self.compressed:
            frame = self._get_encoder().encode(frame, self.samples_per_frame)
        return self._io.write(frame)

    def write_packets(self, packets):
        for packet in packets:
            self.write_packet(packet)

    def read_packet(self):
        frame = self._io.read()
        if self.compressed:
            frame = self._get_decoder().decode(frame, self.samples_per_frame)
        return frame

    def iter_packets(self):
        p = self.read_packet()
        while p:
            yield p
            p = self.read_packet()

    __iter__ = iter_packets

    def __str__(self):
        if self.channels == 1:
            ch_str = 'Mono'
        elif self.channels == 2:
            ch_str = 'Stereo'
        else:
            ch_str = f'{self.channels} channels'
        return f'{self.__class__.__name__}: Sapmle rate: {self.sample_rate / 1000} kHz, {ch_str}, {self.samples_per_frame} samples per frame, {sample_format_names[self.sample_format]}{", Compressed" if self.compressed else ""}. Backing IO is {self._io.__class__.__name__}.'


class SoundZBasicStream(SoundZMinimalStream):
    '''A dead-simple steramable audio format. Carries no data about the audio inside.'''

    def __init__(self, _io, sample_rate=DEFAULT_SAMPLE_RATE, channels=DEFAULT_CHANNELS,
                 samples_per_frame=DEFAULT_SAMPLES_PER_FRAME, sample_format=DEFAULT_SAMPLE_FORMAT,
                 compressed=DEFAULT_COMPRESSED, opus_app=DEFAULT_OPUS_APPLICATION):
        self._io = _io

        self.sample_rate = sample_rate
        self.channels = channels
        self.samples_per_frame = samples_per_frame
        self.sample_format = sample_format
        self.compressed = compressed
        self._opus_app = opus_app

        self._packet_count = 0

        self._encoder = None
        self._decoder = None

    def write_packet(self, packet):
        if self.compressed:
            packet = self._get_encoder().encode(packet, self.samples_per_frame)
        self._io.write(PACKET_HEADER_STRUCT.pack(len(packet)))
        self._io.write(packet)

    def read_packet(self):
        packet_header = self._io.read(PACKET_HEADER_STRUCT.size)
        if not packet_header:  # EOF
            return b''
        packet_size, = PACKET_HEADER_STRUCT.unpack(packet_header)
        packet = self._io.read(packet_size)
        if self.compressed:
            packet = self._get_decoder().decode(packet, self.samples_per_frame)
        return packet


class SoundZFileStream(SoundZBasicStream):
    '''This adds a file magic, file header, and packet magic to mark the starts of packets. Can be streamed or saved to a file. Don't forget to call write_file_header()!!'''

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._packet_count = 0

    @property
    def packet_count(self):
        return self._packet_count

    @property
    def current_timestamp(self):
        return self._packet_count * self.samples_per_frame / (self.sample_rate * self.channels)

    def write_file_header(self):
        self._io.write(FILE_HEADER_MAGIC)
        self._io.write(FILE_HEADER_STRUCT.pack(self.sample_rate, self.channels, self.samples_per_frame, self.sample_format, self.compressed))

    def write_packet(self, packet):
        self._io.write(PACKET_HEADER_MAGIC)
        super().write_packet(packet)
        self._packet_count += 1

    def _process_file_header(self):
        file_header = self._io.read(FILE_HEADER_STRUCT.size)

        sample_rate, channels, samples_per_frame, sample_format, compressed = FILE_HEADER_STRUCT.unpack(file_header)

        assert sample_rate >= 8000, 'Sample rate must be at least 8 kHz'
        assert channels > 0, 'Must have at least one channel'
        assert sample_format in sample_format_names, 'Invalid sample format'
        assert 0 <= compressed <= 1, 'compressed must be either 1 or 0'

        self.sample_rate = sample_rate
        self.channels = channels
        self.samples_per_frame = samples_per_frame
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
        packet = super().read_packet()
        self._packet_count += 1
        return packet


class SoundZSyncingStream(SoundZFileStream):
    '''This adds a self-synchronizing element for the stream meta-data by inserting a file header every 100 packets so it can be joined by a listened mid-stream.'''

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._synced = False

    @property
    def is_synced(self):
        return self._synced

    def write_packet(self, packet):
        if self._packet_count % 100 == 0:
            self.write_file_header()
        super().write_packet(packet)

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
            return super().read_packet()
        except Exception:
            self._synced = False
            return self.read_packet()


class SoundZBasicStreamDatagram(DatagramMixin, SoundZBasicStream):
    pass


class SoundZFileStreamDatagram(DatagramMixin, SoundZFileStream):
    pass


class SoundZSyncingStreamDatagram(DatagramMixin, SoundZSyncingStream):
    pass
