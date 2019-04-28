from ctypes.util import find_library
import sys
import os

if not find_library('opus'):
    pass

try:
    import opuslib
except:
    pass

if 'opuslib' not in sys.modules:
    # Help opuslib find opus.dll
    if sys.platform == 'win32':
        if hasattr(sys, 'frozen') and hasattr(sys, '_MEIPASS'):
            add_to_path = sys._MEIPASS  #pylint: disable=no-member
        else:
            add_to_path = os.path.join(os.path.dirname(__file__), '..')
        os.environ['PATH'] = add_to_path + os.pathsep + os.environ['PATH']

    import opuslib
