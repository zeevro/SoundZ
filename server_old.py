from flask import Flask, request, Response
from functools import wraps
import json
import threading
import socket
import time
import queue


SERVER_PORT = 4452
CLIENT_PORT = 4453

PACKET_TYPE_AUDIO = 0
PACKET_TYPE_HEARTBEAT = 1
PACKET_TYPE_USER_JOINED = 2
PACKET_TYPE_USER_LEFT = 3
PACKET_TYPE_USER_CHANGED_NAME = 4
PACKET_TYPE_USER_STARTED_TALKING = 5
PACKET_TYPE_USER_STOPPED_TALKING = 6


app = Flask(__name__)


clients = {}
is_speaking = {}
events = queue.Queue()


secret_key = 'Rn7tEf1PKXrmHynD1QBUyluoQJDVZEbNSn7tZ0g5a8MipJEetQ'


def json_endpoint(f):
    @wraps(f)
    def helper(*a, **kw):
        response = f(*a, **kw)
        if isinstance(response, Response):
            return response
        return Response(json.dumps(response), mimetype='application/json')
    return helper


@app.route('/audio_params')
@json_endpoint
def audio_params():
    return {'sample_rate': 12000, 'channels': 1, 'samples_per_frame': 120}


@app.route('/subscribe', methods=['POST'])
@json_endpoint
def subscribe():
    if request.json is None:
        return Response('Request must be JSON', 400)
    if 'key' not in request.json:
        return Response('Request must have a key', 403)
    if request.json['key'] != secret_key:
        return Response('Wrong key', 403)
    addr = request.remote_addr
    client = request.json['username']
    if addr in clients:
        if client != clients[addr]:
            clients[addr]
    if client in clients.values():
        pass
    events.put((PACKET_TYPE_USER_LEFT, client))
    clients[request.remote_addr] = client
    return {'response': 'OK'}


@app.route('/unsubscribe')
@json_endpoint
def unsubscribe():
    client = clients.pop(request.remote_addr, None)
    if client:
        events.put((PACKET_TYPE_USER_LEFT, client))
    return {'response': 'OK'}


@app.route('/clients')
@json_endpoint
def list_clients():
    return {'clients': list(clients.values())}


def udp_audio_loop():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.bind(('0.0.0.0', SERVER_PORT))
    ss = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    while 1:
        data, (addr, _port) = s.recvfrom(1024)
        #print(f'{time.time()} got {len(data)} bytes from {addr}', end='')
        if addr not in clients:
            #print(f' - unauthenticated.')
            continue
        print()
        for k in clients.keys():
            if k == addr:
                continue
            #print(f'sending {len(data)} bytes from {addr} to {k}')
            try:
                ss.sendto(data, (k, CLIENT_PORT))
            except socket.error:
                pass


def main():
    flask_thread = threading.Thread(target=app.run, args=('0.0.0.0', SERVER_PORT))
    flask_thread.daemon = True
    flask_thread.start()

    udp_audio_thread = threading.Thread(target=udp_audio_loop)
    udp_audio_thread.daemon = True
    udp_audio_thread.start()

    while 1:
        flask_thread.join(1)
        udp_audio_thread.join(1)


if __name__ == '__main__':
    main()
