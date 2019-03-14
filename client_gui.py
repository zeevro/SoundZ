from typing import Tuple, Callable, Any
import tkinter
import tkinter.ttk
import threading
import queue
import time

from client import SoundZClient
from soundz_audio import Audio, VolumeChangeAudioInput, VoxAudioInputFilter, PushToTalkAudioInputFilter


TK_VAR_PREFIX = 'sndz_'


class NullContext:
    '''Just an easy way to introduce indentation into code in order to improve readability'''

    def __enter__(self):
        pass

    def __exit__(self, *a, **kw):
        pass


class SoundZGUI:
    def __init__(self):
        self._tk = None
        self._window = None
        self._users_list_box = None
        self._users = {}
        self._gui_ready_event = threading.Event()
        self._gui_event_queue = queue.Queue()
        self._gui_thread = None

    def _variable_callback_func(self, var_name, array_index, op):
        self._gui_event_queue.put(('var', var_name, self._tk.globalgetvar(var_name)))

    def _make_click_callback_func(self, name):
        def click_callback_func():
            self._gui_event_queue.put(('click', name, ''))
        return click_callback_func

    @staticmethod
    def _add_volume_frame(master, label):
        var_prefix = f'{TK_VAR_PREFIX}{label.lower()}_'

        frame = tkinter.LabelFrame(master, text=f'{label.title()} volume')
        tkinter.Scale(frame, orient=tkinter.HORIZONTAL, showvalue=False, from_=-20, to=20, resolution=0.1, variable=f'{var_prefix}volume').pack(side=tkinter.LEFT, fill=tkinter.X, expand=True)
        tkinter.Checkbutton(frame, text='Mute', variable=f'{var_prefix}mute').pack(side=tkinter.RIGHT)
        frame.pack(fill=tkinter.X)

    def _create_window(self, show: bool):
        top = tkinter.Tk()
        top.title('SoundZ chat')

        tkinter.Label(top, textvariable=f'{TK_VAR_PREFIX}statusbar_text', bd=1, relief=tkinter.SUNKEN, anchor=tkinter.W).pack(side=tkinter.BOTTOM, fill=tkinter.X)

        with NullContext():
            panels = tkinter.PanedWindow(top)
            with NullContext():
                right_panel_frame = tkinter.LabelFrame(panels, text='Channel users', padx=2, pady=2)
                self._users_list_box = tkinter.Listbox(right_panel_frame, listvariable=f'{TK_VAR_PREFIX}users_list', exportselection=0)
                self._users_list_box.pack(fill=tkinter.BOTH, expand=True)
                panels.add(right_panel_frame, minsize=120)

            with NullContext():
                left_panel_frame = tkinter.Frame(panels)

                with NullContext():
                    self._add_volume_frame(left_panel_frame, 'user')
                    self._add_volume_frame(left_panel_frame, 'mic')
                    self._add_volume_frame(left_panel_frame, 'output')

                with NullContext():
                    settings_frame = tkinter.LabelFrame(left_panel_frame, text='Input settings')

                    with NullContext():
                        input_filter_type_frame = tkinter.Frame(settings_frame)
                        tkinter.Radiobutton(input_filter_type_frame, text='Vox', variable=f'{TK_VAR_PREFIX}input_filter_type', value='vox').pack(side=tkinter.LEFT)
                        tkinter.Radiobutton(input_filter_type_frame, text='Push-to-Talk', variable=f'{TK_VAR_PREFIX}input_filter_type', value='ptt').pack(side=tkinter.LEFT)
                        input_filter_type_frame.pack(fill=tkinter.X)

                    with NullContext():
                        ptt_frame = tkinter.Frame(settings_frame)
                        tkinter.Label(ptt_frame, text='PTT hotkey').pack(side=tkinter.LEFT)
                        tkinter.Entry(ptt_frame, textvar=f'{TK_VAR_PREFIX}ptt_hotkey').pack(side=tkinter.LEFT)
                        ptt_frame.pack(fill=tkinter.X)

                    with NullContext():
                        vox_frame = tkinter.Frame(settings_frame)
                        tkinter.Label(vox_frame, text='Vox threshold').pack(side=tkinter.LEFT)
                        tkinter.Scale(vox_frame, orient=tkinter.HORIZONTAL, showvalue=False, from_=-20, to=20, resolution=0.1, variable=f'{TK_VAR_PREFIX}vox_threshold').pack(side=tkinter.LEFT, fill=tkinter.X, expand=True)
                        vox_frame.pack(fill=tkinter.X)

                    # with NullContext():
                    #     volume_bar_frame = tkinter.Frame(settings_frame)
                    #     tkinter.Label(volume_bar_frame, text='Input volume').pack(side=tkinter.LEFT)
                    #     tkinter.ttk.Progressbar(volume_bar_frame, variable=f'{TK_VAR_PREFIX}input_volume_level').pack(side=tkinter.LEFT, fill=tkinter.X, expand=True)
                    #     volume_bar_frame.pack(fill=tkinter.X)

                    settings_frame.pack(fill=tkinter.X)

                with NullContext():
                    connection_frame = tkinter.LabelFrame(left_panel_frame, text='Connection')
                    tkinter.Label(connection_frame, text='Name:').pack(side=tkinter.LEFT)
                    tkinter.Entry(connection_frame, textvariable=f'{TK_VAR_PREFIX}user_name').pack(side=tkinter.LEFT, fill=tkinter.X)
                    tkinter.Button(connection_frame, text='Connect', command=self._make_click_callback_func('connect')).pack(side=tkinter.LEFT, padx=2, pady=2)
                    tkinter.Button(connection_frame, text='Disconnect', command=self._make_click_callback_func('disconnect')).pack(side=tkinter.LEFT, padx=2, pady=2)
                    connection_frame.pack(fill=tkinter.X)

                panels.add(left_panel_frame, minsize=300)

            panels.pack(fill=tkinter.BOTH, expand=True)

        top.setvar(f'{TK_VAR_PREFIX}input_filter_type', 'vox')
        top.setvar(f'{TK_VAR_PREFIX}statusbar_text', 'Offline')

        top.minsize(width=sum(panels.panecget(panel, 'minsize') for panel in panels.panes()) + panels.cget('borderwidth') + panels.cget('sashpad'), height=312)
        top.focus_force()
        if not show:
            top.withdraw()

        dummy_var = tkinter.Variable(top, name='_dummy')
        variable_callback_name = dummy_var._register(self._variable_callback_func)

        var_names = [v.string for v in top.tk.call('info', 'vars', f'{TK_VAR_PREFIX}*')]
        for var_name in var_names:
            top.tk.call('trace', 'add', 'variable', var_name, 'write', (variable_callback_name,))

        self._window = top
        self._tk = top.tk

        self._gui_ready_event.set()

        top.mainloop()

        self._gui_event_queue.put(None)

    def start(self, show=True, wait_ready=True):
        self._gui_thread = threading.Thread(name='SoundZGUI.gui', target=self._create_window, args=(show,))
        self._gui_thread.start()
        if wait_ready:
            self.wait_for_window()
        return self

    def wait_for_window(self):
        self._gui_ready_event.wait()

    def show_window(self):
        self._window.deiconify()

    def get_event(self, block=True, timeout: float = None):
        return self._gui_event_queue.get(block, timeout)

    @property
    def events(self):
        while 1:
            evt = self.get_event()
            if evt is None:
                return
            yield evt

    def setvar(self, name, value):
        self._window.setvar(f'{TK_VAR_PREFIX}{name}', value)

    def getvar(self, name):
        return self._window.getvar(f'{TK_VAR_PREFIX}{name}')

    __setitem__ = setvar
    __getitem__ = getvar


def main():
    gui = SoundZGUI().start(show=False)
    gui['user_name'] = 'Primer'
    gui['input_filter_type'] = 'vox'
    gui.show_window()

    gui_users = {}

    def user_list_event(event, user, new_list):
        new_sorted_list = sorted(new_list, key=lambda u: u.name.lower())
        gui['users_list'] = [u.name for u in new_sorted_list]
        gui_users = {u.client_id: n for n, u in enumerate(new_sorted_list)}

    client = None
    for event, name, value in gui.events:
        print(event, name, value)
        if event == 'click':
            if name == 'connect':
                try:
                    client = SoundZClient('127.0.0.1', gui['user_name'], user_list_change_callback=user_list_event)
                    gui['statusbar_text'] = 'Connecting...'
                    client.start()
                    gui['statusbar_text'] = 'Online'
                except Exception as err:
                    gui['statusbar_text'] = f'Offline [ERROR: {err}]'
            elif name == 'disconnect':
                if client is not None:
                    gui['statusbar_text'] = 'Disconnecting...'
                    client.stop()
                    client = None
                    gui['statusbar_text'] = 'Offline'
                    gui_users = {}
                    gui['users_list'] = []
        elif event == 'var':
            pass

    client.stop()


if __name__ == "__main__":
    main()
