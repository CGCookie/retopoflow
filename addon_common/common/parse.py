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

import re


#####################################################################################
# below are helper classes for converting input to character stream,
# and for converting character stream to token stream

class Parse_CharStream:
    def __init__(self, charstream):
        self.i_char = 0
        self.i_line = 0
        self.charstream = charstream

    def numberoflines(self):
        return self.charstream.count('\n')

    def endofstream(self):
        return self.i_char >= len(self.charstream)

    def peek(self, l=1):
        if self.endofstream(): return ''
        return self.charstream[self.i_char:self.i_char+l]

    def peek_restofline(self):
        if self.endofstream(): return ''
        i = self.charstream.find('\n', self.i_char)
        if i == -1: return self.charstream[self.i_char:]
        return self.charstream[self.i_char:i]

    def peek_remaining(self):
        if self.endofstream(): return ''
        return self.charstream[self.i_char:]

    def consume(self, m=None, l=None):
        if l is None: l = 1 if m is None else len(m)
        o = self.peek(l=l)
        if m is not None: assert o == m
        self.i_char += l
        self.i_line += o.count('\n')
        return o

    def consume_while_in(self, s):
        w = ''
        while self.peek() in s: w += self.consume()
        return w


class Parse_Lexer:
    '''
    Converts character stream input into a stream of tokens
    '''
    def __init__(self, charstream:Parse_CharStream, token_rules):
        token_rules = [(tname, conv, list(map(re.compile, retokens))) for (tname,conv,retokens) in token_rules]

        self.tokens = []
        self.i = 0
        self.max_lines = charstream.numberoflines()

        while not charstream.endofstream():
            rest = charstream.peek_remaining()
            i_line = charstream.i_line+1

            # match against all possible tokens
            matches = [(tname, conv, retoken.match(rest)) for (tname,conv,retokens) in token_rules for retoken in retokens]
            # filter out non-matches
            matches = list(filter(lambda nm: nm[2] is not None, matches))
            assert matches, 'syntax error on line %d: "%s"' % (i_line, charstream.peek_restofline())
            # find longest match
            longest = max(len(m.group(0)) for (tname,conv,m) in matches)
            # filter out non-longest matches
            matches = list(filter(lambda nm: len(nm[2].group(0))==longest, matches))
            matches = {k:(c,v) for (k,c,v) in matches}

            charstream.consume(l=longest)

            # convert token to python/blender types
            for k,(conv,v) in list(matches.items()):
                v = conv(v)
                if v is None: del matches[k]
                else: matches[k] = v
            if not matches: continue

            ks = set(matches.keys())
            v = list(matches.values())[0]
            self.tokens.append((ks, v, i_line))

    def current_line(self):
        tts,tv,ti_line = self.tokens[self.i]
        return ti_line

    def match_t_v(self, t):
        assert self.i < len(self.tokens), 'hit end on token stream'
        tts,tv,ti_line = self.tokens[self.i]
        t = {t} if type(t) is str else set(t)
        assert tts & t, 'expected type(s) "%s" but saw "%s" (text: "%s", line: %d)' % ('","'.join(t), '","'.join(tts), tv, ti_line)
        self.i += 1
        return tv

    def match_v_v(self, v):
        assert self.i < len(self.tokens), 'hit end on token stream'
        tts,tv,ti_line = self.tokens[self.i]
        v = {v} if type(v) is str else set(v)
        assert tv in v, 'expected value(s) "%s" but saw "%s" (type: "%s", line: %d)' % ('","'.join(v), tv, '","'.join(tts), ti_line)
        self.i += 1
        return tv

    def next_t(self):
        assert self.i < len(self.tokens), 'hit end of token stream'
        tts,tv,ti_line = self.tokens[self.i]
        self.i += 1
        return tts

    def next_v(self):
        assert self.i < len(self.tokens), 'hit end of token stream'
        tts,tv,ti_line = self.tokens[self.i]
        self.i += 1
        return tv

    def peek(self):
        if self.i == len(self.tokens): return ('eof','eof',self.max_lines)
        return self.tokens[self.i]

    def peek_t(self):
        if self.i == len(self.tokens): return 'eof'
        tts,tv,ti_line = self.tokens[self.i]
        return tts

    def peek_v(self):
        if self.i == len(self.tokens): return 'eof'
        tts,tv,ti_line = self.tokens[self.i]
        return tv



