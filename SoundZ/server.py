from typing import Tuple, Iterable
from socketserver import ThreadingTCPServer, StreamRequestHandler
import threading
import socket
import json
import time


SERVER_PORT = 4452

FRAME_RATE = 12000  # Can be 8000, 12000, 24000 or 48000 (see https://tools.ietf.org/html/rfc6716#section-2.1.3)
CHANNELS = 1
FRAME_DURATION_MS = 10  # Can be 2.5, 5, 10, 20, 40, or 60 (see https://tools.ietf.org/html/rfc6716#section-2.1.4)
samples_per_frame = (FRAME_DURATION_MS * FRAME_RATE) // 1000

AUDIO_PARAMS = {'sample_rate': FRAME_RATE, 'channels': CHANNELS, 'samples_per_frame': samples_per_frame}


secret_key = 'Rn7tEf1PKXrmHynD1QBUyluoQJDVZEbNSn7tZ0g5a8MipJEetQ'


class Client:
    def __init__(self, handler):
        self.handler = handler
        self.name = None
        self.in_channel = False
        self.udp_addr_info = None


class ClientManager:
    def __init__(self):
        self._clients = {}

    def _broadcast(self, source_client_id: int, command: bytes, extra_payload: str = None):
        if source_client_id is None:
            for c in self._clients:
                c.handler.write_frame(command, extra_payload)
        else:
            payload = source_client_id.to_bytes(2, 'big') + (extra_payload.encode() if extra_payload else b'')
            for cid, c in self._clients.items():
                if cid == source_client_id:
                    continue
                c.handler.write_frame(command, payload)

    @property
    def taken_ids(self):
        return (cid for cid in self._clients)

    @property
    def taken_names(self):
        return (c.name for c in self._clients.values())

    @property
    def channel_user_list(self):
        return ((cid, c.name) for cid, c in self._clients.items() if c.in_channel)

    def new(self, handler: StreamRequestHandler) -> Tuple[bool, int]:
        if len(self._clients) >= 0xFFFF:
            return False, 'Server is full'
        if not self._clients:
            new_id = 0
        else:
            for new_id, i in enumerate(sorted(self.taken_ids)):
                if new_id != i:
                    break
            else:
                new_id += 1
        self._clients[new_id] = Client(handler)
        return True, new_id.to_bytes(2, 'big')

    def remove(self, client_id: int) -> Tuple[bool, str]:
        self.leave_channel(client_id)
        if self._clients.pop(client_id, None) is None:
            return False, 'Nonexistent client id'
        return True, None

    def set_name(self, client_id: int, name: str) -> Tuple[bool, str]:
        c = self._clients[client_id]
        if not name:
            return False, 'Empty name'
        if name == c.name:
            return False, 'Same name'
        if name in self.taken_names:
            return False, 'Already taken'
        self._clients[client_id].name = name
        self._broadcast(client_id, b'Name', name)
        return True, None

    def list_channel_users(self, client_id: int, channel: str) -> Tuple[bool, str]:  #pylint: disable=unused-argument
        return True, json.dumps(list(self.channel_user_list), separators=(',', ':'))

    def join_channel(self, client_id: int, channel: None) -> Tuple[bool, str]:  #pylint: disable=unused-argument
        c = self._clients[client_id]
        if not c.name:
            return False, 'Empty name'
        if c.in_channel:
            return False, 'Already in channel'
        c.in_channel = True
        self._broadcast(client_id, b'JoinedChannel')
        return True, None

    def leave_channel(self, client_id: int) -> Tuple[bool, str]:
        c = self._clients[client_id]
        if not c.in_channel:
            return False, 'Not in channel'
        c.in_channel = False
        self._broadcast(client_id, b'LeftChannel')
        return True, None

    def audio_received(self, client_id: int, addr_info: Tuple[str, int]) -> Iterable[Tuple[str, int]]:
        for cid, c in self._clients.items():
            if cid == client_id:
                c.udp_addr_info = addr_info
                continue
            yield c.udp_addr_info


class ClientManagerRequestHandler(StreamRequestHandler):
    def setup(self):
        super().setup()
        self._client_id = None

    def handle(self):
        while 1:
            try:
                command, payload = self._read_frame()
            except (ConnectionError, TimeoutError):
                break
            except Exception:
                self.write_frame(b'BadFrame')
                continue

            if command is None:
                break

            command = command.decode()
            handler = getattr(self, f'handle_{command}', None)
            if handler is None:
                self.write_frame(b'BadCommand', command)
                continue

            self.write_frame(*handler(payload))

    def finish(self):
        if self._client_id is not None:
            self.server.client_manager.remove(self._client_id)

    def _read_frame(self) -> Tuple[bytes, bytes]:
        frame_size = int.from_bytes(self.request.recv(3), 'big')  # Frame size
        if not frame_size:
            return None, None
        frame = self.request.recv(frame_size)                     # Frame data
        command, payload_bytes = frame[1:frame[0] + 1], frame[frame[0] + 1:]
        print(f'{"???" if self._client_id is None else self._client_id:3} <-- {command.decode()} {payload_bytes}')
        return command, payload_bytes.decode() if payload_bytes else None

    def write_frame(self, command: bytes, payload: bytes = None) -> None:
        if payload is None:
            payload = b''
        elif isinstance(payload, str):
            payload = payload.encode()
        self.request.send((1 + len(command) + len(payload)).to_bytes(3, 'big'))  # Frame size
        print(f'{"???" if self._client_id is None else self._client_id:3} --> {command.decode()} {payload}')
        self.request.send(len(command).to_bytes(1, 'big') + command + payload)   # Frame data

    def handle_GetAudioParams(self, payload: str) -> Tuple[bytes, str]:  #pylint: disable=unused-argument
        return (b'AudioParams', json.dumps(AUDIO_PARAMS, separators=(',', ':')))

    def handle_Auth(self, payload: str) -> Tuple[bytes, str]:
        if payload != secret_key:
            success, payload = False, 'Wrong key'
        else:
            success, payload = self.server.client_manager.new(self)
            self._client_id = int.from_bytes(payload, 'big')
        return (b'AuthOk' if success else b'BadAuth', payload)

    def handle_SetName(self, payload: str) -> Tuple[bytes, str]:
        if self._client_id is None:
            success, payload = False, 'Not authenticated'
        else:
            success, payload = self.server.client_manager.set_name(self._client_id, payload)
        return (b'NameOk' if success else b'BadName', payload)

    def handle_JoinChannel(self, payload: str) -> Tuple[bytes, str]:
        if self._client_id is None:
            success, payload = False, 'Not authenticated'
        else:
            success, payload = self.server.client_manager.join_channel(self._client_id, payload)
        return (b'JoinOk' if success else b'BadJoin', payload)

    def handle_ListChannelUsers(self, payload: str) -> Tuple[bytes, str]:
        if self._client_id is None:
            success, payload = False, 'Not authenticated'
        else:
            success, payload = self.server.client_manager.list_channel_users(self._client_id, payload)
        return (b'ListOk' if success else b'BadList', payload)

    def handle_LeaveChannel(self, payload: str) -> Tuple[bytes, str]:
        if self._client_id is None:
            success, payload = False, 'Not authenticated'
        else:
            success, payload = self.server.client_manager.leave_channel(self._client_id)
        return (b'LeaveOk' if success else b'BadLeave', payload)


class TCPServer(ThreadingTCPServer):
    def __init__(self, client_manager: ClientManager):
        super().__init__(('0.0.0.0', SERVER_PORT), ClientManagerRequestHandler)
        self.client_manager = client_manager


class UDPServer:
    def __init__(self, client_manager: ClientManager):
        self.client_manager = client_manager

    def serve_forever(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('0.0.0.0', SERVER_PORT))

        tx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        tx_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        tx_sock.bind(('0.0.0.0', SERVER_PORT))

        while 1:
            try:
                frame, rx_addr_info = sock.recvfrom(1024)
            except ConnectionError:
                continue
            client_id = int.from_bytes(frame[:2], 'big')

            for tx_addr_info in self.client_manager.audio_received(client_id, rx_addr_info):
                if tx_addr_info is not None:
                    try:
                        tx_sock.sendto(frame, tx_addr_info)
                    except Exception as e:
                        print(f'ERROR in UDPServer! {e.__class__.__name__}: {e}')


def main():
    client_manager = ClientManager()

    tcp_server = TCPServer(client_manager)
    udp_server = UDPServer(client_manager)

    server_threads = [threading.Thread(target=server.serve_forever) for server in (tcp_server, udp_server)]
    for thread in server_threads:
        thread.daemon = True
        thread.start()

    print('Server started!')
    try:
        while all(thread.is_alive() for thread in server_threads):
            time.sleep(0.5)
    except (KeyboardInterrupt, SystemExit):
        print('Stop')


if __name__ == '__main__':
    main()
