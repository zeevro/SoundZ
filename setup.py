from setuptools import setup, find_packages


setup(
    name='SoundZ',
    version='0.0.1',
    url='https://github.com/zeevro/soundz',
    download_url='https://github.com/zeevro/soundz/archive/master.zip',
    license='None',
    author='Zeev Rotshtein',
    author_email='zeevro@gmail.com',
    keywords=['VoIP', 'voice', 'chat', 'network'],
    zip_safe=True,
    packages=find_packages(),
    python_requires='',
    install_requires=[
        'pyaudio',
        'opuslib',
        'appdirs',
        'pynput',
    ],
    entry_points={
        'console_scripts': [
            'soundz-server = SoundZ.server:main',
        ],
        'gui_scripts': [
            'soundz-client-gui = SoundZ.client_gui:main'
        ],
    },
    classifiers=[
        'Development Status :: 2 - Pre-Alpha'
        'License :: Public Domain',
        'Natural Language :: English',
        'Programming Language :: Python :: Python 3',
    ]
)
