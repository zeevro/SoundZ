import select
import socket


sock1 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
print(f'sock1 = {sock1}')
sock2 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
print(f'sock2 = {sock2}')

sock1.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock2.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

addr = ('127.0.0.1', 20001)

sock1.bind(addr)
sock2.bind(addr)

sock1.sendto(b'from sock1', addr)
rl, _wl, _xl = select.select([sock1, sock2], [], [])
print(f'{rl[0]} selected')
print(rl[0].recvfrom(1024))

sock2.sendto(b'from sock2', addr)
rl, _wl, _xl = select.select([sock1, sock2], [], [])
print(f'{rl[0]} selected')
print(rl[0].recvfrom(1024))
