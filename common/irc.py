# https://pythonspot.com/building-an-irc-bot/

import socket
import sys


class IRC:
    irc = socket.socket()

    def __init__(self):
        self.irc = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    def send(self, chan, msg):
        self.irc.send(bytes("PRIVMSG " + chan + " " + msg + "\n", encoding='utf-8'))

    def connect(self, server, channel, botnick):
        #defines the socket
        print("connecting to:", server)
        self.irc.connect((server, 6667))                                                         #connects to the server
        self.irc.send(bytes("USER " + botnick + " " + botnick +" " + botnick + " :This is a fun bot!\n", encoding='utf-8')) #user authentication
        self.irc.send(bytes("NICK " + botnick + "\n", encoding='utf-8'))
        self.irc.send(bytes("JOIN " + channel + "\n", encoding='utf-8'))        #join the chan

    def get_text(self):
        text = str(self.irc.recv(2040), encoding='utf-8')  #receive the text
        # if text.find('PING') != -1:
        #     self.irc.send(bytes('PONG ' + text.split() [2] + '\n', encoding='utf-8'))
        return text


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