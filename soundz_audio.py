import io
import audioop
import time
import pyaudio
from operator import itemgetter


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

AUDIO_INPUT_CALLBACK_TYPE_FILTER = 1
AUDIO_INPUT_CALLBACK_TYPE_EFFECT = 2
AUDIO_INPUT_CALLBACK_TYPE_PROTOCOL = 3
AUDIO_INPUT_CALLBACK_TYPE_TRANSPORT = 4


sample_format_names = {getattr(pyaudio, f'pa{name}'): name for name in ['Int8', 'UInt8', 'Int16', 'Int24', 'Int32', 'Float32']}


g_pyaudio = pyaudio.PyAudio()


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

    def get_params_from_stream(self, soundz):
        self.sample_rate = soundz.sample_rate
        self.channels = soundz.channels
        self.samples_per_frame = soundz.frame_samples
        self.sample_format = soundz.sample_format

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

    def start_capture(self):
        assert self.callback_chain, 'No input callbacks'
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

    def __enter__(self):
        self.initialize()
        return self

    def __exit__(self, *a):
        self.close()


class AudioInputCallbackBase:
    callback_type = None

    def __init__(self, audio):
        self._audio = audio
        audio.add_callback(self.callback, self.callback_type)

    def callback(self, frame):
        return frame


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


class VoxAudioInputFilter(AudioInputFilterBase):
    def __init__(self, audio, threshold=DEFAULT_VOX_THRESHOLD, timeout=DEFAULT_VOX_TIMEOUT):
        super().__init__(audio)
        self.threshold = threshold
        self.timeout = timeout
        self._breach_timestamp = None

    def _calculate_volume(self, frame):
        return audioop.rms(frame, self._audio.sample_size)

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
        def __init__(self, audio, key):
            super().__init__(audio)
            self._key = key
            self._listener = pynput.keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
            self._listener_started = False
            self._pressed = False

        def _on_press(self, key):
            if key == self._key:
                self._pressed = True
            return self._audio._input_stream.is_active()

        def _on_release(self, key):
            if key == self._key:
                self._pressed = False
            return self._audio._input_stream.is_active()

        def filter(self, frame):
            if not self._listener_started:
                self._listener.start()
                self._listener_started = True
            return self._pressed
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
