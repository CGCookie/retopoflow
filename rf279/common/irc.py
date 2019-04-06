import socket
import sys


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