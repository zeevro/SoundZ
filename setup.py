import os
import subprocess
import sys
from distutils.spawn import find_executable
from http.client import HTTPConnection, HTTPSConnection, urlsplit

from setuptools import setup
from setuptools.command.install import install


def find_dll_in_path(fn, additional_paths=None):
    ext = '.dll' if sys.platform == 'win32' else '.so'
    for basepath in os.environ['PATH'].split(os.pathsep) + (additional_paths or []):
        fullpath = os.path.join(basepath, fn + '.' + ext)
        if os.path.exists(fullpath):
            return fullpath


def is_opuslib_ok():
    try:
        import opuslib  # pylint: disable=unused-import,import-outside-toplevel
    except ImportError:
        return find_dll_in_path('opus')
    except Exception:
        return False
    return True


def get_opuslib_windows(output_path):
    is_64_bit = sys.maxsize > ((1 << 31) - 1)
    url = 'https://discord.foxbot.me/binaries/win{}/opus.dll'.format(64 if is_64_bit else 32)

    print('Fetching {}'.format(url))
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


setup(
    name='SoundZ',
    version='0.0.1',
    url='https://github.com/zeevro/soundz',
    download_url='https://github.com/zeevro/soundz/archive/master.zip',
    author='Zeev Rotshtein',
    author_email='zeevro@gmail.com',
    maintainer='Zeev Rotshtein',
    maintainer_email='zeevro@gmail.com',
    classifiers=[
        'Development Status :: 2 - Pre-Alpha',
        'License :: Public Domain',
        'Natural Language :: English',
        'Programming Language :: Python :: Python 3',
    ],
    license=None,
    description='A small VoIP library with a server and client for multi-user voice channels',
    keywords=[
        'VoIP',
        'voice',
        'chat',
        'network',
    ],
    include_package_data=True,
    zip_safe=False,
    packages=[
        'SoundZ',
    ],
    install_requires=[
        'pyaudio',
        'opuslib',
        'appdirs',
        'pynput',
    ],
    entry_points=dict(
        console_scripts=[
            'soundz-server = SoundZ.server:main',
        ],
        gui_scripts=[
            'soundz-client-gui = SoundZ.client_gui:main',
        ],
    ),
    cmdclass=dict(
        install=PreInstallCommand,
    ),
)