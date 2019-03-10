from typing import Tuple, Union, Callable, Any
import argparse
import audioop
import json
import os
import queue
import socket
import sys
import threading
import time

from soundz_audio import Audio, VolumeChangeAudioInput, VoxAudioInputFilter, PushToTalkAudioInputFilter, DEFAULT_VOX_THRESHOLD

# Help opuslib find opus.dll
os.environ['PATH'] = (sys._MEIPASS if hasattr(sys, 'frozen') else '.') + os.pathsep + os.environ['PATH']  #pylint: disable=no-member,protected-access
import opuslib  #pylint: disable=wrong-import-position,wrong-import-order

try:
    import pynput
    _have_pynput = True
except ImportError:
    _have_pynput = False


SERVER_PORT = 4452
SERVER_KEY = 'Rn7tEf1PKXrmHynD1QBUyluoQJDVZEbNSn7tZ0g5a8MipJEetQ'


class UdpSocketIO(socket.socket):
    def __init__(self, ip, port):
        super().__init__(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self.bind(('', 0))
        self._addr_info = (ip, port)

    def read(self):
        return self.recv(0xFFFF)

    def write(self, data):
        return self.sendto(data, self._addr_info)


class UdpAudioClient:
    def __init__(self, _io, client_id: int, sample_rate: int, channels: int, samples_per_frame: int, callback: Callable[[int, bytes], None]):
        self._io = _io

        self._client_id = client_id
        self._client_id_encoded = client_id.to_bytes(2, 'big')

        self.sample_rate = sample_rate
        self.channels = channels
        self.samples_per_frame = samples_per_frame
        self._callback = callback

        self._encoder = opuslib.Encoder(sample_rate, channels, opuslib.APPLICATION_VOIP)
        self._decoder = opuslib.Decoder(sample_rate, channels)

        self._recv_thread = threading.Thread(target=self._recv_thread_func)
        self._recv_thread.daemon = True
        self._stop = False

    @property
    def is_alive(self):
        return self._recv_thread.is_alive()

    def _recv_thread_func(self):
        while not self._stop:
            try:
                self._callback(*self._read_audio_frame())
            except Exception as e:
                print(f'ERROR UdpAudioClient.callback! {e.__class__.__name__}: {e}')

    def _encode_audio_frame(self, frame: bytes) -> bytes:
        return self._encoder.encode(frame, self.samples_per_frame)

    def _decode_audio_frame(self, frame: bytes) -> bytes:
        return self._decoder.decode(frame, self.samples_per_frame)

    def write_audio_frame(self, audio_data: bytes) -> bytes:
        self._io.write(self._client_id_encoded + self._encode_audio_frame(audio_data))
        return audio_data  # Returning data to maintain Audio callback chain

    def _read_audio_frame(self) -> Tuple[int, bytes]:
        try:
            packet = self._io.read()
        except ConnectionError:
            pass
        return int.from_bytes(packet[:2], 'big'), self._decode_audio_frame(packet[2:])

    def start_receiving(self):
        self.write_audio_frame(bytes(self.channels * self.samples_per_frame * 2))
        self._recv_thread.start()

    def __str__(self):
        if self.channels == 1:
            ch_str = 'Mono'
        elif self.channels == 2:
            ch_str = 'Stereo'
        else:
            ch_str = f'{self.channels} channels'
        return f'{self.__class__.__name__}: Sapmle rate: {self.sample_rate / 1000} kHz, {ch_str}, {self.samples_per_frame} samples per frame. Backing IO is {self._io.__class__.__name__}.'


class TcpManagerClient:
    neutral_responses = {b'AudioParams'}

    responses = {b'Auth', b'Name', b'Join', b'List', b'Leave', b'Start', b'Stop'}

    payload_decoders = {b'AudioParams': 'json',
                        b'AuthOk': 'int',
                        b'ListOk': 'json',
                        b'Name': 'int+str',
                        b'JoinedChannel': 'int',
                        b'LeftChannel': 'int'}

    def __init__(self, server_ip: str, events_callback: Callable[[bytes, Any], None] = None):
        self._server_ip = server_ip
        self._sock = socket.socket()
        self._sock.connect((server_ip, SERVER_PORT))

        self._response_queue = queue.Queue()
        self._event_queue = queue.Queue()

        self._main_thread = threading.Thread(target=self._main_loop)
        self._main_thread.daemon = True
        self._main_thread.start()

        self._events_callback = events_callback
        if events_callback:
            self._events_thread = threading.Thread(target=self._event_loop)
            self._events_thread.daemon = True
            self._events_thread.start()

    def _decode_payload(self, decoder: str, payload: bytes) -> Union[None, str, dict, list, int, Tuple[int, str]]:
        if not payload:
            return

        if decoder == 'json':
            return json.loads(payload.decode())

        if decoder == 'int':
            return int.from_bytes(payload, 'big')

        if decoder == 'int+str':
            return int.from_bytes(payload[:2], 'big'), payload[2:].decode()

        return payload.decode()

    def _read_frame(self):
        frame_size = int.from_bytes(self._sock.recv(3), 'big')  # Frame size
        if not frame_size:
            return None, None
        frame = self._sock.recv(frame_size)                     # Frame data
        command, payload = frame[1:frame[0] + 1], frame[frame[0] + 1:]

        decoder = self.payload_decoders.get(command, '')
        payload = self._decode_payload(decoder, payload)

        if (command in self.neutral_responses) or (command.endswith(b'Ok') and command[:-2] in self.responses):
            self._response_queue.put((True, payload))
        elif command.startswith(b'Bad') and command[3:] in self.responses:
            self._response_queue.put((False, payload))
        else:
            self._event_queue.put((command, payload))

    def _main_loop(self) -> None:
        while 1:
            self._read_frame()

    def _event_loop(self) -> None:
        while 1:
            try:
                self._events_callback(*self.get_event())
            except Exception as e:
                print(f'ERROR in TcpManagerClient.events_callback! {e.__class__.__name__}: {e}')
                raise

    def _write_frame(self, command: bytes, payload: Union[bytes, str] = None) -> None:
        if payload is None:
            payload = b''
        elif isinstance(payload, str):
            payload = payload.encode()
        self._sock.send((1 + len(command) + len(payload)).to_bytes(3, 'big'))  # Frame size
        self._sock.send(len(command).to_bytes(1, 'big') + command + payload)   # Frame data

    def _read_response(self) -> Tuple[bytes, Union[None, dict, list, int]]:
        return self._response_queue.get()

    def request(self, command: bytes, payload: str = None) -> Tuple[bytes, Union[None, dict, list, int]]:
        self._write_frame(command, payload)
        return self._read_response()

    def get_event(self, block=True, timeout=None) -> Tuple[bytes, int]:
        return self._event_queue.get(block, timeout)


class User:
    def __init__(self, client_id, name, audio_params, volume_factor=1.0, in_channel=True):
        self.client_id = client_id
        self.name = name
        self.in_channel = in_channel
        self.volume_factor = volume_factor
        self._audio_output = Audio(output_needed=True, **audio_params)

    def play_audio(self, audio_data):
        self._audio_output.playback(audioop.mul(audio_data, self._audio_output.sample_size, self.volume_factor))

    def __del__(self):
        self._audio_output.close()

    def __repr__(self):
        return f'User: client_id={self.client_id} name={self.name} in_channel={self.in_channel}'


class DummyUser:
    def __init__(self, client_id, name):
        self.client_id = client_id
        self.name = name
        self.in_channel = True


class SoundZError(Exception):
    pass


class SoundZClient:
    SERVER_PORT = 4452
    SERVER_KEY = 'Rn7tEf1PKXrmHynD1QBUyluoQJDVZEbNSn7tZ0g5a8MipJEetQ'

    def __init__(self, server_ip, name, output_volume_factor=1.0, input_volume_factor=1.0, user_list_change_callback=None):
        self.server_ip = server_ip
        self._name = name
        self._output_volume_factor = output_volume_factor
        self._input_volume_factor = input_volume_factor
        self._user_list_change_callback = user_list_change_callback
        self._client_id = None

        self._tcp_manager = TcpManagerClient(server_ip, self._events_callback)
        self._udp_stream = None
        self._audio_input = None
        self._input_volume_changer = None

        self._users = {}

        self._audio_params = None

    @property
    def audio_input(self):
        return self._audio_input

    @property
    def output_volume_factor(self):
        return self._output_volume_factor

    @output_volume_factor.setter
    def set_output_volume_factor(self, new_value):
        for user in self._users.values():
            user.volume_factor = user.volume_factor / self._output_volume_factor * new_value
        self._output_volume_factor = new_value

    @property
    def input_volume_factor(self):
        return self._input_volume_factor

    @input_volume_factor.setter
    def set_input_volume_factor(self, new_value):
        if self._input_volume_changer is not None:
            self._input_volume_changer.volume_factor = new_value
        self._input_volume_factor = new_value

    def _channel_user_list_change(self, event=None, user=None):
        if self._user_list_change_callback is not None:
            try:
                return self._user_list_change_callback(event, user, [DummyUser(self._client_id, self._name)] + list(self._users.values()))
            except Exception as e:
                print(f'ERROR in SoundZClient.user_list_change_callback! {e.__class__.__name__}: {e}')

    def _events_callback(self, command, payload):
        if command == b'Name':
            client_id, name = payload
            self._users[client_id] = User(client_id, name, self._audio_params, self._output_volume_factor, in_channel=False)  # TODO: Remember user volume factor
        elif command == b'JoinedChannel':
            self._users[payload].in_channel = True
            self._channel_user_list_change('join', self._users[payload])
        elif command == b'LeftChannel':
            self._users[payload].in_channel = False
            user = self._users.pop(payload, None)
            if user is not None:
                self._channel_user_list_change('leave', user)

    def _audio_callback(self, client_id, frame):
        self._users[client_id].play_audio(frame)

    def _init_audio(self):
        self._udp_stream = UdpAudioClient(UdpSocketIO(self.server_ip, self.SERVER_PORT), self._client_id, callback=self._audio_callback, **self.audio_params)
        self._udp_stream.start_receiving()
        self._audio_input = Audio(input_needed=True, **self.audio_params).add_callback(self._udp_stream.write_audio_frame)
        self._input_volume_changer = VolumeChangeAudioInput(self._audio_input, self._input_volume_factor)
        self._audio_input.start_capture()

    @property
    def audio_params(self):
        if self._audio_params is None:
            self._audio_params = self._tcp_manager.request(b'GetAudioParams')[1]
        return self._audio_params

    def start(self):
        success, payload = self._tcp_manager.request(b'Auth', self.SERVER_KEY)
        if not success:
            raise SoundZError(payload)
        self._client_id = payload

        success, payload = self._tcp_manager.request(b'SetName', self._name)
        if not success:
            raise SoundZError(payload)

        success, payload = self._tcp_manager.request(b'ListChannelUsers')
        if not success:
            raise SoundZError(payload)
        self._users = {client_id: User(client_id, name, self.audio_params) for client_id, name in payload}  # TODO: Remember user volume factor
        self._channel_user_list_change()

        self._init_audio()

        success, payload = self._tcp_manager.request(b'JoinChannel')
        if not success:
            raise SoundZError(payload)


if _have_pynput:
    def get_ptt_key():
        print('Press the key you wish to use for PTT. Press ESC to cancel.')

        key_l = []

        def on_press(key):
            print(f'on_press({key})')
            key_l.append(key)
            return False

        keyboard_listener = pynput.keyboard.Listener(on_press=on_press, suppress=True)
        keyboard_listener.start()
        keyboard_listener.join()

        selected_key = key_l[0]

        if selected_key == pynput.keyboard.Key.esc:
            print('Cancelled.')
            return None

        print(f'{selected_key} was selected.')

        return selected_key


def print_channel_event(event, user, user_list):
    event_str = {'leave': 'left', 'join': 'joined'}.get(event, None)
    name_list = ', '.join(sorted(u.name for u in user_list if u.in_channel))
    if event_str:
        print(f'{user.name} has {event_str} the channel.')
    print(f'Users currently in channel: {name_list}.')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('-p', '--push-to-talk', action='store_true')
    p.add_argument('-P', '--server-port', type=int, default=SERVER_PORT)
    p.add_argument('-s', '--server-ip', default='127.0.0.1')
    p.add_argument('-k', '--server-key', default=SERVER_KEY)
    p.add_argument('-n', '--name', required=True)
    p.add_argument('-v', '--output-volume', type=float, default=1.0)
    p.add_argument('-V', '--input-volume', type=float, default=1.0)
    p.add_argument('-x', '--vox-threshold', type=int, default=DEFAULT_VOX_THRESHOLD)
    p.add_argument('--mute', action='store_true')
    args = p.parse_args()

    print('Hello')
    print()

    ptt_key = None
    if args.push_to_talk:
        if not _have_pynput:
            print('You must install pynput to use the push-to-talk feature.')
            return
        ptt_key = get_ptt_key()

    print(f'Using {"PTT" if ptt_key is not None else "Vox"} filter.')

    soundz_client = SoundZClient(args.server_ip, args.name, args.output_volume, args.input_volume, print_channel_event)
    soundz_client.start()
    _tx_filter = VoxAudioInputFilter(soundz_client.audio_input) if ptt_key is None else PushToTalkAudioInputFilter(soundz_client.audio_input, ptt_key)
    if args.input_volume:
        _volume_changer = VolumeChangeAudioInput(soundz_client.audio_input, args.input_volume)

    try:
        while 1:
            time.sleep(10)
    except (KeyboardInterrupt, SystemExit):
        print('Stop.')


if __name__ == '__main__':
    main()
