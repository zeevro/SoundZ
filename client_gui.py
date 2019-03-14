from typing import Tuple, Callable, Any
import tkinter
import tkinter.ttk
import tkinter.simpledialog
import threading
import queue
import math
import os
import json
import time

from client import SoundZClient, DummyUser
from soundz_audio import VoxAudioInputFilter, PushToTalkAudioInputFilter, MeasureVolumeCallback, AUDIO_INPUT_CALLBACK_TYPE_PROTOCOL, AUDIO_INPUT_CALLBACK_TYPE_FILTER
import appdirs


# TODO: Figure out a way to update the input volume level bar and the TX marker on the bottom left corner without consuming CPU
# TODO: Fix the issues with the server address input dialog
# TODO: General instability issues


TK_VAR_PREFIX = 'sndz_'


class SettingsManager(object):
    def __init__(self, minimum_save_interval=0.1):
        self._minimum_save_interval = minimum_save_interval
        self._filename = os.path.join(appdirs.user_config_dir(roaming=True), 'soundz_client_settings.conf')
        self._cache = {}
        self._last_save = 0

    def __del__(self):
        self._save_to_file()

    def _load_from_file(self):
        try:
            with open(self._filename) as f:
                for line in f:
                    k, v = line.strip().split(maxsplit=1)
                    self._cache[k] = v
        except Exception:
            self._cache = {}

    def _save_to_file(self):
        with open(self._filename, 'w') as f:
            for k, v in self._get_data().items():
                print(k, v, file=f)
        self._last_save = time.time()

    def _get_data(self):
        if not self._cache:
            self._load_from_file()
        return self._cache

    def get(self, name, default=None):
        return self._get_data().get(name, default)

    def put(self, name, value):
        self._get_data()[name] = value
        if self._last_save + self._minimum_save_interval <= time.time():
            self._save_to_file()

    __getitem__ = get
    __setitem__ = put

    def __iter__(self):
        return iter(self._get_data().items())


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
        self._gui_event_queue.put(('var', var_name[len(TK_VAR_PREFIX):], self._tk.globalgetvar(var_name)))

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

        with NullContext():
            statusbar_frame = tkinter.Frame(top)
            tkinter.Label(statusbar_frame, textvariable=f'{TK_VAR_PREFIX}statusbar_tx', bd=1, relief=tkinter.SUNKEN, width=2).pack(side=tkinter.LEFT)
            tkinter.Label(statusbar_frame, textvariable=f'{TK_VAR_PREFIX}statusbar_text', bd=1, relief=tkinter.SUNKEN, anchor=tkinter.W).pack(side=tkinter.LEFT, fill=tkinter.X, expand=True)
            statusbar_frame.pack(side=tkinter.BOTTOM, fill=tkinter.X)

        with NullContext():
            menubar = tkinter.Menu(top)

            with NullContext():
                servermenu = tkinter.Menu(menubar, tearoff=0)
                servermenu.add_command(label='Address...', command=self._make_click_callback_func('set_server_address'))
                menubar.add_cascade(label='Server', menu=servermenu)

            with NullContext():
                optionsmenu = tkinter.Menu(menubar, tearoff=0)
                optionsmenu.add_checkbutton(label='Display volume level', variable=f'{TK_VAR_PREFIX}display_input_volume_level')
                menubar.add_cascade(label='Options', menu=optionsmenu)

            top.config(menu=menubar)

        with NullContext():
            panels = tkinter.PanedWindow(top)
            with NullContext():
                right_panel_frame = tkinter.LabelFrame(panels, text='Channel users', padx=2, pady=2)
                users_list = tkinter.Listbox(right_panel_frame, listvariable=f'{TK_VAR_PREFIX}users_list', exportselection=0)
                users_list.pack(fill=tkinter.BOTH, expand=True)
                users_list.bind('<<ListboxSelect>>', lambda evt: self._gui_event_queue.put(('list_sel', 'users', evt.widget.curselection()[0])))
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
                        tkinter.Scale(vox_frame, orient=tkinter.HORIZONTAL, showvalue=False, from_=0, to=3000, resolution=1, variable=f'{TK_VAR_PREFIX}vox_threshold').pack(side=tkinter.LEFT, fill=tkinter.X, expand=True)
                        vox_frame.pack(fill=tkinter.X)

                    with NullContext():
                        volume_bar_frame = tkinter.Frame(settings_frame)
                        tkinter.Label(volume_bar_frame, text='Input volume').pack(side=tkinter.LEFT)
                        tkinter.ttk.Progressbar(volume_bar_frame, variable=f'{TK_VAR_PREFIX}input_volume_level', maximum=0x7FFF).pack(side=tkinter.LEFT, fill=tkinter.X, expand=True)
                        volume_bar_frame.pack(fill=tkinter.X)

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


def gain2db(gain):
    return 20 * math.log10(gain)


def db2gain(db):
    return 10 ** (db / 20)


def main():
    settings = SettingsManager()

    gui = SoundZGUI().start(show=False)
    for k, v in settings:
        if k.startswith('gui_'):
            gui[k[4:]] = v
    gui.show_window()

    gui_list_ids_by_client_id = {}
    users_by_gui_list_id = {}
    selected_user = DummyUser()
    old_input_filter_type = None
    input_filter = None
    last_volume_level_update = [0]

    def user_list_event(event, user, new_list):
        new_sorted_list = sorted(new_list, key=lambda u: u.name.lower())

        gui['users_list'] = [u.name for u in new_sorted_list]

        gui_list_ids_by_client_id.clear()
        gui_list_ids_by_client_id.update({u.client_id: n for n, u in enumerate(new_sorted_list)})
        users_by_gui_list_id.clear()
        users_by_gui_list_id.update({n: u for n, u in enumerate(new_sorted_list)})

    def display_input_volume_level(vol):
        if last_volume_level_update[0] + 0.2 < time.time():
            gui['input_volume_level'] = vol
            last_volume_level_update.pop()
            last_volume_level_update.append(time.time())

    def display_is_transmitting(frame):
        gui['statusbar_tx'] = 'X' * bool(frame)
        return frame

    client = None
    for event, name, value in gui.events:
        #print(event, name, repr(value), type(value))
        if event == 'click':
            if name == 'connect':
                if client is None:
                    try:
                        assert settings['server_address'], 'No server address'
                        client = SoundZClient(settings['server_address'], gui['user_name'], user_list_change_callback=user_list_event)
                        gui['statusbar_text'] = 'Connecting...'
                        client.start()
                        client.input_volume_factor = db2gain(float(gui['mic_volume']))
                        if int(gui['mic_mute']):
                            client._audio_input.stop_capture()
                        client.output_volume_factor = db2gain(float(gui['output_volume']))
                        client.muted = bool(int(gui['output_mute']))
                        if gui['input_filter_type'] == 'vox':
                            input_filter = VoxAudioInputFilter(client.audio_input, int(gui['vox_threshold']))
                        elif gui['input_filter_type'] == 'ptt':
                            input_filter = PushToTalkAudioInputFilter(client.audio_input, gui['ptt_hotkey'])
                        old_input_filter_type = value
                        #if int(gui['display_input_volume_level']):
                        #    MeasureVolumeCallback(client.audio_input, display_input_volume_level)
                        #client.audio_input.add_callback(display_is_transmitting, AUDIO_INPUT_CALLBACK_TYPE_PROTOCOL)
                        gui['statusbar_text'] = 'Online'
                    except Exception as err:
                        if client is not None:
                            client.stop()
                            client = None
                            input_filter = None
                        gui['statusbar_text'] = f'Offline [ERROR: {err}]'
                        gui['users_list'] = []
                        gui_list_ids_by_client_id = {}
                        users_by_gui_list_id = {}

            elif name == 'disconnect':
                if client is not None:
                    gui['statusbar_text'] = 'Disconnecting...'
                    client.stop()
                    client = None
                    input_filter = None
                    gui['statusbar_text'] = 'Offline'
                    gui['users_list'] = []
                    gui_list_ids_by_client_id = {}
                    users_by_gui_list_id = {}

            elif name == 'set_server_address':
                _temp_root = tkinter.Tk()
                _temp_root.withdraw()
                settings['server_address'] = tkinter.simpledialog.askstring('SoundZ', 'Server address:', initialvalue=settings['server_address'], parent=_temp_root) or settings['server_address']
                _temp_root.destroy()

        elif event == 'list_sel':
            if name == 'users':
                selected_user = users_by_gui_list_id[int(value)]
                gui['user_volume'] = gain2db(selected_user.volume_factor)
                gui['user_mute'] = selected_user.muted

        elif event == 'var':
            if name in ('mic_volume', 'mic_mute', 'output_volume', 'output_mute', 'input_filter_type', 'vox_threshold', 'ptt_hotkey', 'display_input_volume_level', 'user_name'):
                settings.put(f'gui_{name}', value)

            if name == 'user_volume':
                if isinstance(selected_user, DummyUser) and float(value) != 0:
                    gui[name] = 0
                else:
                    selected_user.volume_factor = db2gain(float(value))

            elif name == 'user_mute':
                if isinstance(selected_user, DummyUser) and bool(int(value)) != False:
                    gui[name] = False
                else:
                    selected_user.muted = bool(int(value))

            elif name == 'mic_volume':
                if client is not None:
                    client.input_volume_factor = db2gain(float(value))

            elif name == 'mic_mute':
                if client is not None:
                    if int(value):
                        client._audio_input.stop_capture()
                    else:
                        client._audio_input.start_capture()

            elif name == 'output_volume':
                if client is not None:
                    client.output_volume_factor = db2gain(float(value))

            elif name == 'output_mute':
                if client is not None:
                    client.muted = bool(int(value))

            elif name == 'input_filter_type':
                if client is not None:
                    if value != old_input_filter_type:
                        old_input_filter_type = value
                        input_filter.stop()
                        if value == 'vox':
                            input_filter = VoxAudioInputFilter(client.audio_input, int(gui['vox_threshold']))
                        elif value == 'ptt':
                            input_filter = PushToTalkAudioInputFilter(client.audio_input, gui['ptt_hotkey'])

            elif name == 'vox_threshold':
                if isinstance(input_filter, VoxAudioInputFilter):
                    input_filter.threshold = int(value)

            elif name == 'ptt_hotkey':
                if isinstance(input_filter, PushToTalkAudioInputFilter):
                    input_filter.key = value

            # elif name == 'display_input_volume_level':
            #     if client is not None:
            #         if int(value):
            #             #client.audio_input.add_callback(display_input_volume_level)

            #         else:
            #             #client.audio_input.remove_callback(display_input_volume_level)

    if client is not None:
        client.stop()


if __name__ == "__main__":
    main()
