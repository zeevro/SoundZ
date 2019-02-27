import soundz as sz
import pynput


class SoundZUdpSender:
    def __init__(self, ip, port=sz.DEFAULT_PORT, compressed=sz.DEFAULT_COMPRESSED, ptt_key=None):
        self._stream = sz.SoundZMinimalStream(sz.UdpSocketIO().tx(ip, port), compressed=compressed)
        self._audio = sz.Audio(input_needed=True).get_params_from_soundz(self._stream).add_callback(self._stream.write_packet)
        sz.AudioInputKeepAlive(self._audio)
        if ptt_key is None:
            sz.VoxAudioInputFilter(self._audio)
        else:
            sz.PushToTalkAudioInputFilter(self._audio, ptt_key)

    def start(self):
        self._audio.start_capture()

    def stop(self):
        self._audio.stop_capture()

    def close(self):
        self.stop()
        self._audio.close()


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


def main():
    import argparse
    import time

    p = argparse.ArgumentParser()
    p.add_argument('-k', '--push-to-talk', action='store_true')
    p.add_argument('-r', '--sample-rate', type=int, default=sz.DEFAULT_SAMPLE_RATE)
    p.add_argument('-u', '--raw', action='store_true')
    p.add_argument('-p', '--port', type=int, default=sz.DEFAULT_PORT)
    p.add_argument('ip', nargs='?', default='127.0.0.1')
    args = p.parse_args()

    ptt_key = None
    if args.push_to_talk:
        ptt_key = get_ptt_key()

    s = SoundZUdpSender(args.ip, args.port, not args.raw, ptt_key)
    print(s._stream)
    if ptt_key is None:
        print('Using vox filter.')
    else:
        print(f'Using Push-To-Talk filter with the {ptt_key} key.')

    print('Starting.')
    s.start()

    try:
        while s._audio._input_stream.is_active():
            time.sleep(0.5)
    except (KeyboardInterrupt, SystemExit):
        print('Stopping.')
    finally:
        s.close()

    print('Done.')


if __name__ == "__main__":
    main()
