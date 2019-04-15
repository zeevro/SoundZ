from SoundZ.audio import Audio, VoxAudioInputFilter, PushToTalkAudioInputFilter, AUDIO_INPUT_CALLBACK_TYPE_PROTOCOL
from SoundZ.streams import UdpSocketIO
import opuslib
from urllib.request import urlopen, Request
import threading
import json
import socket
import time
import argparse
import pynput


SERVER_PORT = 4452
CLIENT_PORT = 4453

SERVER_KEY = 'Rn7tEf1PKXrmHynD1QBUyluoQJDVZEbNSn7tZ0g5a8MipJEetQ'


PACKET_TYPE_AUDIO = 0
PACKET_TYPE_HEARTBEAT = 1
PACKET_TYPE_USER_JOINED = 2
PACKET_TYPE_USER_LEFT = 3
PACKET_TYPE_USER_CHANGED_NAME = 4
PACKET_TYPE_USER_STARTED_TALKING = 5
PACKET_TYPE_USER_STOPPED_TALKING = 6


class UdpAudioClient:
    def __init__(self, _io, sample_rate:int, channels:int, samples_per_frame:int, audio_callback, events_callback):
        self._io = _io

        self.sample_rate = sample_rate
        self.channels = channels
        self.samples_per_frame = samples_per_frame
        self._audio_callback = audio_callback
        self._events_callback = events_callback

        self._encoder = opuslib.Encoder(sample_rate, channels, opuslib.APPLICATION_VOIP)
        self._decoder = opuslib.Decoder(sample_rate, channels)

        self._recv_thread = threading.Thread(target=self._recv_thread_func)
        self._stop = False

    @property
    def is_alive(self):
        return self._recv_thread.is_alive()

    def _recv_thread_func(self):
        while not self._stop:
            try:
                packet = self._read_packet()
                packet_type, payload = packet[0], packet[1:]
                if packet_type == PACKET_TYPE_AUDIO:
                    self._audio_callback(payload)
                else:
                    self._events_callback(packet_type, payload)
            except Exception as e:
                print(f'ERROR! {e.__class__.__name__}: {e}')

    def _en_encode_audio_fram(self, frame:bytes) -> bytes:
        return self._encoder.encode(frame, self.samples_per_frame)

    def _decode_frame(self, frame:bytes) -> bytes:
        return self._decoder.decode(frame, self.samples_per_frame)

    def _write_packet(self, packet_type:int, payload:bytes=b'') -> int:
        return self._io.write(packet_type.to_bytes(1, 'big') + payload)

    def _read_packet(self) -> bytes:
        return self._io.read()

    def write_audio_frame(self, frame:bytes) -> int:
        return self.write_packet(PACKET_TYPE_AUDIO, self._en_encode_audio_frameame)

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


def network_events_callback(event_type, payload):
    payload = payload.decode()
    print({PACKET_TYPE_USER_JOINED: f'{payload} joined the channel',
           PACKET_TYPE_USER_LEFT: f'{payload} left',
           PACKET_TYPE_USER_STARTED_TALKING: f'{payload} is speaking',
           PACKET_TYPE_USER_STOPPED_TALKING: f'{payload} is quiet'})


def main():
    p = argparse.ArgumentParser()
    p.add_argument('-t', '--push-to-talk', action='store_true')
    p.add_argument('-p', '--client-port', type=int, default=CLIENT_PORT)
    p.add_argument('-P', '--server-port', type=int, default=SERVER_PORT)
    p.add_argument('-s', '--server-ip', default='127.0.0.1')
    p.add_argument('-k', '--key', default=SERVER_KEY)
    p.add_argument('-u', '--username', required=True)
    args = p.parse_args()

    server_base_url = f'http://{args.server_ip}:{args.server_port}'

    ptt_key = None
    if args.push_to_talk:
        ptt_key = get_ptt_key()

    print('Hello')
    print()

    print(f'Using {"PTT" if ptt_key is not None else "Vox"} filter.')

    print('Getting audio parameters from server...', end='')
    audio_params = json.load(urlopen(f'{server_base_url}/audio_params'))
    print(' OK')

    print('Initialising systems...', end='')
    _io = UdpSocketIO().tx(args.server_ip, args.server_port).rx(args.client_port)
    audio = Audio(input_needed=True, output_needed=True, **audio_params)
    network_stream = UdpAudioClient(_io, audio_callback=audio.playback, **audio_params)
    audio.add_callback(network_stream.write_frame)
    tx_filter = VoxAudioInputFilter(audio) if ptt_key is None else PushToTalkAudioInputFilter(audio, ptt_key)
    audio.add_callback(tx_status_callback, AUDIO_INPUT_CALLBACK_TYPE_PROTOCOL)

    def recv_thread_func():
        for frame in rx_stream:
            audio.playback(frame)
    recv_thread = threading.Thread(target=recv_thread_func)
    recv_thread.daemon = True
    print(' OK')

    print('Joining voice channel...', end='')
    req = Request(f'{server_base_url}/subscribe',
                  json.dumps({'username': args.username, 'key': args.key}).encode(),
                  {'Content-Type': 'application/json'})
    json.load(urlopen(req))
    print(' OK')

    print()
    print('Currently in the channel:')
    for user in json.load(urlopen(f'{server_base_url}/clients'))['clients']:
        print(user)

    print()
    print('Start.')
    audio.start_capture()
    network_stream.start_receiving()

    try:
        while 1:
            time.sleep(10)
    except (KeyboardInterrupt, SystemExit):
        print('Stop.')


if __name__ == '__main__':
    main()
