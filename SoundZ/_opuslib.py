import os
import sys
from ctypes.util import find_library


if not find_library('opus'):
    pass

try:
    import opuslib  #pylint: disable=unused-import
except Exception:
    pass

if 'opuslib' not in sys.modules:
    # Help opuslib find opus.dll
    if sys.platform == 'win32':
        if hasattr(sys, 'frozen') and hasattr(sys, '_MEIPASS'):
            add_to_path = sys._MEIPASS  #pylint: disable=no-member,protected-access
        else:
            add_to_path = os.path.join(os.path.dirname(__file__), '..')
        os.environ['PATH'] = add_to_path + os.pathsep + os.environ['PATH']

    import opuslib
