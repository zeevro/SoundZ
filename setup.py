from setuptools import setup
from setuptools.command.install import install
from distutils.spawn import find_executable
from ctypes.util import find_library
from http.client import urlsplit, HTTPConnection, HTTPSConnection
import sys
import os
import subprocess


def find_dll_in_path(fn, additional_paths=None):
    ext = '.dll' if sys.platform == 'win32' else '.so'
    for basepath in os.environ['PATH'].split(os.pathsep) + (additional_paths or []):
        fullpath = os.path.join(basepath, fn + '.' + ext)
        if os.path.exists(fullpath):
            return fullpath


def is_opuslib_ok():
    try:
        import opuslib
    except ModuleNotFoundError:
        return find_dll_in_path('opus')
    except:
        return False
    return True


def get_opuslib_windows(output_path):
    is_64_bit = sys.maxsize > ((1 << 31) - 1)
    url = 'https://discord.foxbot.me/binaries/win{}/opus.dll'.format(64 if is_64_bit else 32)

    print(f'Fetching {url}')
    url_parts = urlsplit(url)
    conn_cls = {'http': HTTPConnection, 'https': HTTPSConnection}[url_parts.scheme]
    conn = conn_cls(url_parts.netloc, url_parts.port)
    conn.request('GET', url_parts.path)
    binary_data = conn.getresponse().read()

    print('Saving file')
    with open(os.path.join(output_path, 'opus.dll'), 'wb') as f:
        f.write(binary_data)
    print('Done')


def get_opuslib_linux():
    package_managers = {'apt-get': ['libopus0', 'portaudio19-dev', 'python3-dev'],
                        'yum': ['opus', 'portaudio', 'portaudio-devel', 'python3-devel']}
    for pm, packages in package_managers.items():
        package_manager = find_executable(pm)
        if not package_manager:
            continue
        subprocess.call([package_manager, '-y', '-q', 'install'] + packages)
        break


class PreInstallCommand(install):
    """Pre-installation for installation mode."""
    def run(self):
        if not is_opuslib_ok():
            if sys.platform == 'win32':
                get_opuslib_windows(os.path.dirname(__file__))
            elif sys.platform == 'linux':
                get_opuslib_linux()

        install.run(self)


setup(cmdclass={'install': PreInstallCommand})
