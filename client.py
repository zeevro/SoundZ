from typing import Tuple, Union, Callable
from soundz_audio import Audio, VoxAudioInputFilter, PushToTalkAudioInputFilter, AUDIO_INPUT_CALLBACK_TYPE_PROTOCOL
import threading
import time
import argparse
import pynput
import socket
import json
import queue
import os
import sys


if hasattr(sys, 'frozen'):
    os.environ['PATH'] = sys._MEIPASS + os.pathsep + os.environ['PATH']


try:
    import opuslib
except ImportError:
    # Help poor opuslib to fine opus.dll
    if os.name == 'nt':
        os.environ['PATH'] = '.' + os.pathsep + os.environ['PATH']
    import opuslib


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
                raise
                print(f'ERROR! {e.__class__.__name__}: {e}')

    def _encode_audio_frame(self, frame: bytes) -> bytes:
        frame = self._encoder.encode(frame, self.samples_per_frame)
        return frame

    def _decode_audio_frame(self, frame: bytes) -> bytes:
        frame = self._decoder.decode(frame, self.samples_per_frame)
        return frame

    def write_audio_frame(self, audio_data: bytes) -> bytes:
        self._io.write(self._client_id_encoded + self._encode_audio_frame(audio_data))
        return audio_data

    def _read_audio_frame(self) -> Tuple[int, bytes]:
        packet = self._io.read()
        return int.from_bytes(packet[:2], 'big'), self._decode_audio_frame(packet[2:])

    def start_receiving(self):
        self._recv_thread.start()

    def __str__(self):
        if self.channels == 1:
            ch_str = 'Mono'
        elif self.channels == 2:
            ch_str = 'Stereo'
        else:
            ch_str = f'{self.channels} channels'
        return f'{self.__class__.__name__}: Sapmle rate: {self.sample_rate / 1000} kHz, {ch_str}, {self.samples_per_frame} samples per frame. Backing IO is {self._io.__class__.__name__}.'


neutral_responses = {b'AudioParams'}

responses = {b'Auth', b'Name', b'Join', b'List', b'Leave', b'Start', b'Stop'}

payload_decoders = {b'AudioParams': 'json',
                    b'AuthOk': 'int',
                    b'ListOk': 'json',
                    b'Name': 'int+str',
                    b'JoinedChannel': 'int',
                    b'LeftChannel': 'int'}


class TcpManagerClient:
    def __init__(self, server_ip: str, events_callback: Callable[[bytes, int], None]=None):
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

        if (command in neutral_responses) \
                or (command.endswith(b'Ok') and command[:-2] in responses) \
                or (command.startswith(b'Bad') and command[3:] in responses):
            is_response = True
        else:
            is_response = False

        decoder = payload_decoders.get(command, '')

        payload = self._decode_payload(decoder, payload)

        (self._response_queue if is_response else self._event_queue).put((command, payload))

    def _main_loop(self) -> None:
        while 1:
            self._read_frame()

    def _event_loop(self) -> None:
        while 1:
            try:
                self._events_callback(*self.get_event())
            except Exception:
                pass

    def _write_frame(self, command: bytes, payload: Union[bytes, str]=None) -> None:
        if payload is None:
            payload = b''
        elif isinstance(payload, str):
            payload = payload.encode()
        self._sock.send((1 + len(command) + len(payload)).to_bytes(3, 'big'))  # Frame size
        self._sock.send(len(command).to_bytes(1, 'big') + command + payload)   # Frame data

    def _read_response(self) -> Tuple[bytes, Union[None, dict, list, int]]:
        return self._response_queue.get()

    def request(self, command: bytes, payload: str=None) -> Tuple[bytes, Union[None, dict, list, int]]:
        self._write_frame(command, payload)
        return self._read_response()

    def get_event(self, block=True, timeout=None) -> Tuple[bytes, int]:
        return self._event_queue.get(block, timeout)


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

    selected_key, = key_l

    if selected_key == pynput.keyboard.Key.esc:
        print('Cancelled.')
        return None

    print(f'{selected_key} was selected.')

    return selected_key


def tx_status_callback(frame):
    print('TX' if frame else '  ', end='\r')
    return frame


def get_network_stream_callback(audio):
    def network_stream_callback(client_id, frame):
        audio.playback(frame)
    return network_stream_callback


def main():
    p = argparse.ArgumentParser()
    p.add_argument('-p', '--push-to-talk', action='store_true')
    p.add_argument('-P', '--server-port', type=int, default=SERVER_PORT)
    p.add_argument('-s', '--server-ip', default='127.0.0.1')
    p.add_argument('-k', '--server-key', default=SERVER_KEY)
    p.add_argument('-n', '--name', required=True)
    p.add_argument('--mute', action='store_true')
    args = p.parse_args()

    print('Hello')
    print()

    ptt_key = None
    if args.push_to_talk:
        ptt_key = get_ptt_key()

    print(f'Using {"PTT" if ptt_key is not None else "Vox"} filter.')

    manager_client = TcpManagerClient(args.server_ip, events_callback=print)

    print('Getting audio parameters from server...', end='')
    audio_params = manager_client.request(b'GetAudioParams')[1]
    print(' OK')

    print('Authenticating to server...', end='')
    command, payload = manager_client.request(b'Auth', SERVER_KEY)
    if command != b'AuthOk':
        print(' FAIL')
        print(f'Authentication process failed! {payload}')
        return
    client_id = payload
    print(' OK')
    print(f'My client ID is {client_id}')

    print('Initialising audio system...', end='')
    audio = Audio(input_needed=not args.mute, output_needed=True, **audio_params)
    network_stream = UdpAudioClient(UdpSocketIO(args.server_ip, args.server_port), client_id, callback=get_network_stream_callback(audio), **audio_params)
    audio.add_callback(network_stream.write_audio_frame)
    _tx_filter = VoxAudioInputFilter(audio) if ptt_key is None else PushToTalkAudioInputFilter(audio, ptt_key)
    #audio.add_callback(tx_status_callback, AUDIO_INPUT_CALLBACK_TYPE_PROTOCOL)
    print(' OK')

    print('Setting your name...', end='')
    command, payload = manager_client.request(b'SetName', args.name)
    if command != b'NameOk':
        print(' FAIL')
        print(f'Setting name failed! {payload}')
        return
    print(' OK')

    print('Joining voice channel...', end='')
    command, payload = manager_client.request(b'JoinChannel')
    if command != b'JoinOk':
        print(' FAIL')
        print(f'Join failed! {payload}')
        return
    print(' OK')

    print('Listing users in channel...', end='')
    command, payload = manager_client.request(b'ListChannelUsers')
    if command != b'ListOk':
        print(' FAIL')
        print(f'Listing failed! {payload}')
        return
    print(' OK')

    print()
    print('User list:')
    for user in payload:
        print(user)

    print()
    print('Start.')
    network_stream._io.write(network_stream._client_id_encoded)
    if not args.mute:
        audio.start_capture()
    network_stream.start_receiving()

    try:
        while 1:
            time.sleep(10)
    except (KeyboardInterrupt, SystemExit):
        print('Stop.')


if __name__ == '__main__':
    main()
