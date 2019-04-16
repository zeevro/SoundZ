import io
import audioop
import time
import pyaudio
import wave
from operator import itemgetter
from enum import Enum
from contextlib import closing


try:
    import pynput
    _have_pynput = True
except ImportError:
    _have_pynput = False


# TODO: Calculate samples per frame so opuslib is happy with frame duration
# TODO: Write real tests


DEFAULT_SAMPLE_RATE = 12000
DEFAULT_CHANNELS = 1
DEFAULT_SAMPLES_PER_FRAME = 120
DEFAULT_SAMPLE_FORMAT = pyaudio.paInt16

DEFAULT_VOX_THRESHOLD = 800
DEFAULT_VOX_TIMEOUT = 0.4

DEFAULT_KEEPALIVE_TIME = 8

AUDIO_INPUT_CALLBACK_TYPE_MEASURE = 1
AUDIO_INPUT_CALLBACK_TYPE_FILTER = 2
AUDIO_INPUT_CALLBACK_TYPE_EFFECT = 3
AUDIO_INPUT_CALLBACK_TYPE_PROTOCOL = 4
AUDIO_INPUT_CALLBACK_TYPE_TRANSPORT = 5

WAVE_FILE_FRAMES_PER_CHUNK = 1024


sample_format_names = {getattr(pyaudio, f'pa{name}'): name for name in ['Int8', 'UInt8', 'Int16', 'Int24', 'Int32', 'Float32']}


g_pyaudio = pyaudio.PyAudio()


def play_wave_file(filename):
    with wave.open(filename) as wf:
        chunk_size = (wf.getnchannels() * wf.getsampwidth()) * WAVE_FILE_FRAMES_PER_CHUNK
        with closing(g_pyaudio.open(wf.getframerate(), wf.getnchannels(), pyaudio.get_format_from_width(wf.getsampwidth()), output=True)) as player:
            data = bytes(chunk_size)
            while len(data) == chunk_size:
                data = wf.readframes(1024)
                player.write(data)  # pylint: disable=no-member


def play_wave_file_async(filename):
    wf = wave.open(filename)

    chunk_size = (wf.getnchannels() * wf.getsampwidth()) * WAVE_FILE_FRAMES_PER_CHUNK

    def stream_callback(in_data, frame_count, time_info, status_flags):
        data = wf.readframes(1024)
        if len(data) < chunk_size:
            wf.close()
            res = pyaudio.paAbort
            data += bytes(chunk_size - len(data))
        else:
            res = pyaudio.paContinue
        return data, res

    return g_pyaudio.open(wf.getframerate(), wf.getnchannels(), pyaudio.get_format_from_width(wf.getsampwidth()), output=True, stream_callback=stream_callback, start=True)


class Audio:
    def __init__(self, input_needed=False, output_needed=False,
                 sample_rate=DEFAULT_SAMPLE_RATE, channels=DEFAULT_CHANNELS,
                 samples_per_frame=DEFAULT_SAMPLES_PER_FRAME, sample_format=DEFAULT_SAMPLE_FORMAT):
        self.sample_rate = sample_rate
        self.channels = channels
        self.samples_per_frame = samples_per_frame
        self.sample_format = sample_format

        self.sample_size = pyaudio.get_sample_size(sample_format)
        self.frame_bytes = samples_per_frame * channels * self.sample_size

        self._input_needed = input_needed
        self._output_needed = output_needed

        self._input_stream = None
        self._output_stream = None

        self.callback_chain = []

    def _input_callback(self, in_data, _frame_count, _time_info, _status_flags):
        buf = io.BytesIO(in_data)
        while 1:
            frame = buf.read(self.frame_bytes)
            if not frame:
                break
            for callback_type, func in self.callback_chain:
                try:
                    if (not frame) and callback_type == AUDIO_INPUT_CALLBACK_TYPE_TRANSPORT:
                        break
                    frame = func(frame or b'')
                except Exception as e:
                    print(f'ERROR in Audio.callback! {e.__class__.__name__}: {e}')
        return (None, 0)

    def get_params_from_stream(self, stream):
        self.sample_rate = stream.sample_rate
        self.channels = stream.channels
        self.samples_per_frame = stream.samples_per_frame
        self.sample_format = stream.sample_format

        return self

    def initialize(self):
        if self._input_needed and self._input_stream is None:
            self._input_stream = g_pyaudio.open(format=self.sample_format,
                                                channels=self.channels,
                                                rate=self.sample_rate,
                                                input=True,
                                                frames_per_buffer=self.samples_per_frame,
                                                input_device_index=g_pyaudio.get_default_input_device_info()['index'],
                                                stream_callback=self._input_callback)

        if self._output_needed and self._output_stream is None:
            self._output_stream = g_pyaudio.open(format=self.sample_format,
                                                 channels=self.channels,
                                                 rate=self.sample_rate,
                                                 output=True,
                                                 frames_per_buffer=self.samples_per_frame,
                                                 input_device_index=g_pyaudio.get_default_output_device_info()['index'])

    def add_callback(self, callback, callback_type=AUDIO_INPUT_CALLBACK_TYPE_TRANSPORT):
        if hasattr(callback, 'callback_type') and hasattr(callback, 'callback') and callable(callback.callback):
            func = callback.callback
            callback_type = callback.callback_type
        else:
            func = callback
        self.callback_chain.append((callback_type, func))
        self.callback_chain.sort(key=itemgetter(0))
        return self

    def remove_callback(self, callback_func):
        for n, (type_, func) in enumerate(self.callback_chain):  # pylint: disable=unused-variable
            if func == callback_func:
                del self.callback_chain[n]
                break

    def remove_callbacks_by_type(self, callback_type):
        to_remove = []
        for n, (type_, func) in enumerate(self.callback_chain):  # pylint: disable=unused-variable
            if type_ == callback_type:
                to_remove.append(n)
        for i in to_remove:
            del self.callback_chain[i]

    def start_capture(self):
        assert self.callback_chain, 'No input callbacks'
        self.initialize()
        self._input_stream.start_stream()
        return self

    def stop_capture(self):
        self._input_stream.stop_stream()
        self._input_stream = None
        return self

    def playback(self, data):
        self.initialize()
        self._output_stream.write(data)

    def close(self):
        if self._output_stream is not None:
            if not self._output_stream.is_stopped():
                try:
                    self._output_stream.stop_stream()
                except:
                    pass
            self._output_stream.close()
            self._output_stream = None

        if self._input_stream is not None:
            if not self._input_stream.is_stopped():
                try:
                    self._input_stream.stop_stream()
                except:
                    pass
            self._input_stream.close()
            self._input_stream = None

    def __enter__(self):
        self.initialize()
        return self

    def __exit__(self, *a):
        self.close()


class CalculateVolumeMixin:
    def _calculate_volume(self, frame):
        return audioop.rms(frame, self._audio.sample_size)


class AudioInputCallbackBase:
    callback_type = None

    def __init__(self, audio):
        self._stop = False
        self._audio = audio
        audio.add_callback(self.callback, self.callback_type)

    def callback(self, frame):
        return frame

    def stop(self):
        self._audio.remove_callback(self.callback)
        self._stop = True

    def __del__(self):
        self.stop()


class AudioInputMeasureBase(AudioInputCallbackBase):
    callback_type = AUDIO_INPUT_CALLBACK_TYPE_MEASURE

    def callback(self, frame):
        self.measure(frame)
        return frame

    def measure(self, frame):
        raise NotImplementedError()


class MeasureVolumeCallback(CalculateVolumeMixin, AudioInputMeasureBase):
    def __init__(self, audio, result_callback):
        super().__init__(audio)
        self._callback = result_callback

    def measure(self, frame):
        self._callback(self._calculate_volume(frame))


class AudioInputKeepAlive(AudioInputCallbackBase):
    callback_type = AUDIO_INPUT_CALLBACK_TYPE_PROTOCOL

    def __init__(self, audio):
        super().__init__(audio)
        self._last_active = 0

    def callback(self, frame):
        if frame:
            if self._last_active:
                self._last_active = 0
            return frame

        if not self._last_active:
            self._last_active = time.time()
            return frame

        if time.time() - self._last_active >= DEFAULT_KEEPALIVE_TIME:
            self._last_active = time.time()
            return bytes(self._audio.frame_bytes)

        return frame


class AudioInputFilterBase(AudioInputCallbackBase):
    callback_type = AUDIO_INPUT_CALLBACK_TYPE_FILTER

    def callback(self, frame):
        if self.filter(frame):
            return frame

    def filter(self, frame):
        raise NotImplementedError()


class VoxAudioInputFilter(CalculateVolumeMixin, AudioInputFilterBase):
    def __init__(self, audio, threshold=DEFAULT_VOX_THRESHOLD, timeout=DEFAULT_VOX_TIMEOUT):
        super().__init__(audio)
        self.threshold = threshold
        self.timeout = timeout
        self._breach_timestamp = None

    def filter(self, frame):
        volume = self._calculate_volume(frame)
        if volume < self.threshold:
            if self._breach_timestamp is None:
                self._breach_timestamp = time.time()
            elif self._breach_timestamp + self.timeout < time.time():
                return False
        else:
            self._breach_timestamp = None

        return True


if _have_pynput:
    class PushToTalkAudioInputFilter(AudioInputFilterBase):
        def __init__(self, audio, sequence):
            super().__init__(audio)
            self.sequence = sequence
            self._listener = pynput.keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
            self._listener_started = False
            self._pressed = set()
            self._breached = False

        @property
        def sequence(self):
            return self._sequence

        @sequence.setter
        def sequence(self, seq):
            if isinstance(seq, str):
                self._sequence = set(seq.lower().replace('win', 'cmd').split('+'))
            else:
                self._sequence = set(seq)

        @staticmethod
        def _get_key_names(key):
            if isinstance(key, Enum):
                return (k for k in dir(pynput.keyboard.Key) if key.name.startswith(k))
            return (key.char,)

        def _is_breached(self):
            return self._pressed.issuperset(self.sequence)

        def _on_press(self, key):
            self._pressed.update(self._get_key_names(key))
            self._breached = self._is_breached()
            return self._audio._input_stream.is_active() and not self._stop

        def _on_release(self, key):
            self._pressed.difference_update(self._get_key_names(key))
            self._breached = self._is_breached()
            return self._audio._input_stream.is_active() and not self._stop

        def stop(self):
            super().stop()
            self._listener.stop()

        def filter(self, frame):
            if not self._listener_started:
                self._listener.start()
                self._listener_started = True
            return self._breached
else:
    class PushToTalkAudioInputFilter:
        def __init__(self, *a, **kw):
            raise NotImplementedError()


class AudioInputEffectBase(AudioInputCallbackBase):
    callback_type = AUDIO_INPUT_CALLBACK_TYPE_EFFECT


class VolumeChangeAudioInput(AudioInputEffectBase):
    def __init__(self, audio, volume_factor=1.0):
        super().__init__(audio)
        self.volume_factor = volume_factor

    def callback(self, frame):
        return audioop.mul(frame, self._audio.sample_size, self.volume_factor)
