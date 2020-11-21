'''
Copyright (C) 2020 CG Cookie
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

import socket
import sys

'''
Note: this is a work in progress only!
'''

# https://pythonspot.com/building-an-irc-bot/
class IRC:
    def __init__(self):
        self.done = False
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    def __del__(self):
        self.close()

    def send_text(self, text):
        if not text.endswith('\n'): text += '\n'
        self.socket.send(bytes(text, encoding='utf-8'))

    def send(self, chan, msg):
        self.socket.send(bytes("PRIVMSG " + chan + " :" + msg + "\n", encoding='utf-8'))

    def connect(self, server, channel, nickname):
        #defines the socket
        print("connecting to:", server)
        self.socket.connect((server, 6667))                                                         #connects to the server
        self.socket.send(bytes("USER " + nickname + " " + nickname +" " + nickname + " :This is a fun bot!\n", encoding='utf-8')) #user authentication
        self.socket.send(bytes("NICK " + nickname + "\n", encoding='utf-8'))
        self.socket.send(bytes("JOIN " + channel + "\n", encoding='utf-8'))        #join the chan

    def get_text(self, blocking=True):
        self.socket.setblocking(blocking)
        try:
            text = str(self.socket.recv(4096), encoding='utf-8')  #receive the text
        except socket.error:
            text = None
        return text

    def close(self):
        if self.done: return
        self.socket.close()
        self.done = True


if __name__ == '__main__':
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