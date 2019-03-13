from http.client import urlsplit, HTTPConnection, HTTPSConnection
import sys
import os


def get_windows():
    is_64_bit = sys.maxsize > ((1 << 31) - 1)
    url = f'https://discord.foxbot.me/binaries/win{64 if is_64_bit else 32}/opus.dll'

    print(f'Fetching {url}')
    url_parts = urlsplit(url)
    conn_cls = {'http': HTTPConnection, 'https': HTTPSConnection}[url_parts.scheme]
    conn = conn_cls(url_parts.netloc, url_parts.port)
    conn.request('GET', url_parts.path)
    binary_data = conn.getresponse().read()

    print('Saving file')
    with open(os.path.join(os.path.dirname(__file__), 'opus.dll'), 'wb') as f:
        f.write(binary_data)
    print('Done')


def main():
    if sys.platform == 'win32':
        get_windows()
    else:
        print('Only Windows is supported.')


if __name__ == '__main__':
    main()
