try:
    import winsound
    def _play_sound(filename):
        return  winsound.PlaySound(filename, winsound.SND_ASYNC)
except ImportError:
    pass

try:
    import ossaudiodev
    import wave
    def _play_sound(filename):
        dev = ossaudiodev.open('w')

except ImportError:
    pass


def play_sound(filename):
    return _play_sound(filename)
