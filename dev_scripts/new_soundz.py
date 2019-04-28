import pyaudio
import struct

from SoundZ._opuslib import opuslib


DEFAULT_SAMPLE_RATE = 12000
DEFAULT_CHANNELS = 1
DEFAULT_SAMPLES_PER_FRAME = 120
DEFAULT_SAMPLE_FORMAT = pyaudio.paInt16
DEFAULT_COMPRESSED = True
DEFAULT_OPUS_APPLICATION = opuslib.APPLICATION_VOIP

MAGIC_SIZE = 4

FILE_HEADER_MAGIC = b'SndZ'
FILE_HEADER_STRUCT = struct.Struct('<LBBBB')
PACKET_HEADER_MAGIC = b'pktZ'
PACKET_HEADER_STRUCT = struct.Struct('<H')


sample_format_names = {getattr(pyaudio, f'pa{name}'): name for name in ['Int8', 'UInt8', 'Int16', 'Int24', 'Int32', 'Float32']}


class SkipPacket(Exception):
    pass


class AbstractSoundZStream:
    def __init__(self, _io, sample_rate=DEFAULT_SAMPLE_RATE, channels=DEFAULT_CHANNELS,
                 frame_samples=DEFAULT_SAMPLES_PER_FRAME, sample_format=DEFAULT_SAMPLE_FORMAT,
                 compressed=DEFAULT_COMPRESSED, opus_app=DEFAULT_OPUS_APPLICATION):
        self._io = _io

        self.sample_rate = sample_rate
        self.channels = channels
        self.frame_samples = frame_samples
        self.sample_format = sample_format
        self.compressed = compressed
        self._opus_app = opus_app

        self._packet_count = 0

        self._encoder = None
        self._decoder = None

    @property
    def packet_count(self):
        return self._packet_count

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
        self.frame_samples = soundz.frame_samples
        self.sample_format = soundz.sample_format
        self.compressed = soundz.compressed
        self._opus_app = soundz._opus_app

    def get_params_from_audio(self, audio):
        self.sample_rate = audio.sample_rate
        self.channels = audio.channels
        self.frame_samples = audio.frame_samples
        self.sample_format = audio.sample_format

    def _frame2packet(self, frame):
        if self.compressed:
            return self._get_encoder().encode(frame, self.frame_samples)
        return frame

    def _packet2frame(self, packet):
        if self.compressed:
            return self._get_decoder().decode(packet, self.frame_samples)
        return packet

    def write_packet(self, frame):
        ret = self._io.write(self._frame2packet(frame))
        self._packet_count += 1
        return ret

    def write_packets(self, packets):
        for packet in packets:
            self.write_packet(packet)

    def iter_packets(self):
        p = self.read_packet()  # pylint: disable=no-member
        while p:
            yield p
            p = self.read_packet()  # pylint: disable=no-member

    __iter__ = iter_packets

    def __str__(self):
        if self.channels == 1:
            ch_str = 'Mono'
        elif self.channels == 2:
            ch_str = 'Stereo'
        else:
            ch_str = f'{self.channels} channels'
        return f'{self.__class__.__name__}: Sapmle rate: {self.sample_rate / 1000} kHz, {ch_str}, {self.frame_samples} samples per frame, {sample_format_names[self.sample_format]}{", Compressed" if self.compressed else ""}. Backing IO is {self._io.__class__.__name__}.'


class DatagramReadPacketMixin:
    def read_packet(self):
        while 1:
            try:
                ret = self._packet2frame(self._io.read())
                self._packet_count += 1  # pylint: disable=no-member
                break
            except SkipPacket:
                pass
        return ret


class PacketHeaderMixin:
    def _frame2packet(self, frame):
        frame = super()._frame2packet(frame)
        return PACKET_HEADER_STRUCT.pack(len(frame)) + frame

    def read_packet(self):
        packet_header = self._io.read(PACKET_HEADER_STRUCT.size)
        if not packet_header:  # EOF
            return b''
        packet_size, = PACKET_HEADER_STRUCT.unpack(packet_header)
        packet = self._io.read(packet_size)
        if self.compressed:
            packet = self._get_decoder().decode(packet, self.frame_samples)
        return packet


class FileHeaderMixin:
    def write_file_header(self):
        self._io.write(FILE_HEADER_MAGIC + FILE_HEADER_STRUCT.pack(self.sample_rate, self.channels, self.frame_samples, self.sample_format, self.compressed))

    def _process_file_header(self, header):
        sample_rate, channels, frame_samples, sample_format, compressed = FILE_HEADER_STRUCT.unpack(header)

        assert sample_rate >= 8000, 'Sample rate must be at least 8 kHz'
        assert channels > 0, 'Must have at least one channel'
        assert sample_format in sample_format_names, 'Invalid sample format'
        assert 0 <= compressed <= 1, 'compressed must be either 1 or 0'

        self.sample_rate = sample_rate
        self.channels = channels
        self.frame_samples = frame_samples
        self.sample_format = sample_format
        self.compressed = bool(compressed)

        return self


class MagicsMixin:
    def _frame2packet(self, frame):
        return PACKET_HEADER_MAGIC + super()._frame2packet(frame)

    def _packet2frame(self, packet):
        magic, packet = packet[:MAGIC_SIZE], packet[MAGIC_SIZE:]
        if magic == PACKET_HEADER_MAGIC:
            return super()._packet2frame(packet)
        elif magic == FILE_HEADER_MAGIC:
            super()._process_file_header(packet)
            raise SkipPacket

    def read_packet(self):
        while 1:
            magic = self._io.read(MAGIC_SIZE)
            if not magic:  # EOF
                return b''
            if magic == PACKET_HEADER_MAGIC:
                return super().read_packet()
            elif magic == FILE_HEADER_MAGIC:
                super()._process_file_header(self._io.read(FILE_HEADER_STRUCT.size))
            else:
                assert f'Bad magic {magic}'


class AutoSyncMixin:
    def write_packet(self, packet):
        if self.packet_count % 100 == 0:
            self.write_file_header()
        super().write_packet(packet)


class SoundZBasicDatagramStream(DatagramReadPacketMixin, AbstractSoundZStream):
    '''The simplest stream imaginable. Only sends the raw frames. Works only on datagram-based IOs (since no packet size is encoded).'''
    pass


class SoundZBasicStream(PacketHeaderMixin, AbstractSoundZStream):
    '''This adds packet headers with payload length so it works on non-datagram IOs.'''
    pass


class SoundZFileHeaderDatagramStream(DatagramReadPacketMixin, MagicsMixin, FileHeaderMixin, AbstractSoundZStream):
    '''This adds a file header with the audio parameters. Different magics are added for packet headers and file headers. Datagram version.'''
    pass


class SoundZFileHeaderStream(MagicsMixin, FileHeaderMixin, PacketHeaderMixin, AbstractSoundZStream):
    '''This adds a file header with the audio parameters. Different magics are added for packet headers and file headers. Non-datagram version.'''
    pass


class SoundZAutoFileHeaderDatagramStream(DatagramReadPacketMixin, AutoSyncMixin, MagicsMixin, FileHeaderMixin, AbstractSoundZStream):
    '''This includes a file header every so often so the stream can be listened to from the middle. Datagram version.'''
    pass


class SoundZAutoFileHeaderStream(AutoSyncMixin, MagicsMixin, FileHeaderMixin, PacketHeaderMixin, AbstractSoundZStream):
    '''This includes a file header every so often so the stream can be listened to from the middle. Non-datagram version.'''
    pass
