'''
Copyright (C) 2018 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Williamson

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
'''

import re
import random

from ..common.irc import IRC
from ..common import ui

'''
channel = "#retopoflow"
server = "irc.freenode.net"
nickname = "rftester"

irc = IRC()
irc.connect(server, channel, nickname)

while 1:
    text = irc.get_text()
    if text: print(text)

    if "PRIVMSG" in text and channel in text and "hello" in text:
        irc.send(channel, "Hello!")
'''

class RFIRCChat:
    def get_nickname(self): return self.nickname
    def set_nickname(self, v): self.nickname = v

    def get_message(self): return self.message
    def set_message(self, v): self.message = v

    def login(self):
        self.win.set_title('IRC: ' + self.nickname)
        self.irc = IRC()
        self.irc.connect(self.server, self.channel, self.nickname)
        self.interval_id = self.wm.register_interval_callback(self.receive_message, 1.0)
        self.ui_login.visible = False
        self.ui_message.visible = True
        self.ui_message_footer.visible = True

    def add_message(self, nick, msg):
        self.ui_messages.add(ui.UI_WrappedLabel('%s: %s' % (nick, msg), max_size=(400,40000)))
        self.ui_vscroll_messages.scroll_to_bottom()

    def send_message(self):
        if not self.message: return
        self.irc.send(self.channel, self.message)
        self.add_message(self.nickname, self.message)
        self.message = ''

    def _get_nickname(self, part):
        m = re.match(r'^:[@]?(?P<nick>[^!]+)!.*$', part)
        return m.group('nick')

    def receive_message(self):
        data = ''
        while True:
            next_data = self.irc.get_text(blocking=False)
            if next_data is None: break
            data += next_data
        if not data: return
        for line in data.splitlines():
            print('line (%s): "%s"' % (self.nickname, line))
            parts = line.split(' ')
            if parts[0] == 'PING':
                text = 'PONG %s' % (' '.join(line.split()[1:]),)
                print('send: "%s"' % text)
                self.irc.send_text(text)
            if parts[1] == '353':
                self.nicks = [re.sub(r'^@', '', n) for n in ' '.join(parts[5:])[1:].split()]
                self.update_nick_list()
            if parts[1] == 'JOIN' and parts[2] == self.channel:
                nick = self._get_nickname(parts[0])
                self.nicks += [nick]
                self.update_nick_list()
            if parts[1] == 'QUIT' or (parts[1] == 'PART' and parts[2] == self.channel):
                nick = self._get_nickname(parts[0])
                self.nicks = [n for n in self.nicks if n != nick]
                self.update_nick_list()
            if parts[1] == 'PRIVMSG' and parts[2] == self.channel:
                nick = self._get_nickname(parts[0])
                msg = ' '.join(parts[3:])[1:]
                self.add_message(nick, msg)
            #self.ui_messages_vscroll.

    def update_nick_list(self):
        self.ui_nicks.clear()
        for nick in sorted(self.nicks):
            self.ui_nicks.add(ui.UI_Label(nick))

    def quit(self):
        if self.done: return
        self.wm.delete_window(self.win)
        self.wm.unregister_interval_callback(self.interval_id)
        del self.win
        del self.irc
        self.done = True

    def __init__(self, wm):
        self.done = False
        self.server = 'irc.freenode.net'
        self.channel = '#retopoflow'
        self.nickname = 'rfuser_%d' % random.randint(0, 10000)
        self.nicks = []
        self.message = ''
        self.wm = wm

        opts = {
            'pos':8,
            'movable':True,
            'bgcolor': (0.2, 0.2, 0.2, 0.5),
        }
        self.win = self.wm.create_window('IRC', opts)

        self.ui_login = self.win.add(ui.UI_Container())
        self.ui_login.add(ui.UI_Textbox(self.get_nickname, self.set_nickname, label="Nickname", allow_chars='abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ-_0123456789'))
        self.ui_login.add(ui.UI_Button('Login', self.login))

        self.ui_message = self.win.add(ui.UI_Container(vertical=False, min_size=(450, 100)))
        self.ui_vscroll_messages = self.ui_message.add(ui.UI_VScrollable(min_size=(400, 0), max_size=(400, 10000)))
        self.ui_messages = self.ui_vscroll_messages.set_ui_item(ui.UI_Container())
        self.ui_vscroll_nicks = self.ui_message.add(ui.UI_VScrollable(min_size=(50, 0), max_size=(50, 10000)))
        self.ui_nicks = self.ui_vscroll_nicks.set_ui_item(ui.UI_Container())
        self.ui_message.visible = False

        self.ui_message_footer = self.win.add(ui.UI_Container(vertical=False), footer=True)
        self.ui_message_text = self.ui_message_footer.add(ui.UI_Textbox(self.get_message, self.set_message, fn_enter=self.send_message, always_commit=True, min_size=(400,12)))
        self.ui_message_footer.add(ui.UI_Button('Send', self.send_message))
        self.ui_message_footer.add(ui.UI_Button('Quit', self.quit))
        self.ui_message_footer.visible = False

    def __del__(self):
        self.quit()