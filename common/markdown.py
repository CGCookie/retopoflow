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

class Markdown:
    # markdown line (first line only, ex: table)
    line_tests = {
        'h1':     re.compile(r'# +(?P<text>.+)'),
        'h2':     re.compile(r'## +(?P<text>.+)'),
        'h3':     re.compile(r'### +(?P<text>.+)'),
        'ul':     re.compile(r'(?P<indent> *)- +(?P<text>.+)'),
        'ol':     re.compile(r'(?P<indent> *)\d+\. +(?P<text>.+)'),
        'img':    re.compile(r'!\[(?P<caption>[^\]]*)\]\((?P<filename>[^) ]+)(?P<style>[^)]*)\)'),
        'table':  re.compile(r'\| +(([^|]*?) +\|)+'),
    }

    # markdown inline
    inline_tests = {
        'br':     re.compile(r'<br */?> *'),
        'img':    re.compile(r'!\[(?P<caption>[^\]]*)\]\((?P<filename>[^) ]+)(?P<style>[^)]*)\)'),
        'bold':   re.compile(r'\*(?P<text>.+?)\*'),
        'code':   re.compile(r'`(?P<text>[^`]+)`'),
        'link':   re.compile(r'\[(?P<text>.+?)\]\((?P<link>.+?)\)'),
        'italic': re.compile(r'_(?P<text>.+?)_'),
        'checkbox': re.compile(r'<input (?P<params>.*?type="checkbox".*?)>(?P<innertext>.*?)<\/input>'),
    }

    # https://stackoverflow.com/questions/3809401/what-is-a-good-regular-expression-to-match-a-url
    re_url    = re.compile(r'^((https?)|mailto)://([-a-zA-Z0-9@:%._\+~#=]+\.)*?[-a-zA-Z0-9@:%._+~#=]+\.[a-zA-Z0-9()]{1,6}\b([-a-zA-Z0-9()@:%_+.~#?&/=]*)$')

    @staticmethod
    def preprocess(txt):
        # process message similarly to Markdown
        txt = re.sub(r'<!--.*?-->', r'', txt)   # remove comments
        txt = re.sub(r'^\n*', r'', txt)         # remove leading \n
        txt = re.sub(r'\n*$', r'', txt)         # remove trailing \n
        txt = re.sub(r'\n\n\n*', r'\n\n', txt)  # 2+ \n => \n\n
        txt = re.sub(r'---', r'—', txt)         # em dash
        txt = re.sub(r'--', r'–', txt)          # en dash
        return txt

    @staticmethod
    def is_url(txt): return Markdown.re_url.match(txt) is not None

    @staticmethod
    def match_inline(line):
        #line = line.lstrip()    # ignore leading spaces
        for (t,r) in Markdown.inline_tests.items():
            m = r.match(line)
            if m: return (t, m)
        return (None, None)

    @staticmethod
    def match_line(line):
        line = line.rstrip()    # ignore trailing spaces
        for (t,r) in Markdown.line_tests.items():
            m = r.match(line)
            if m: return (t, m)
        return (None, None)

    @staticmethod
    def split_word(line):
        if ' ' not in line:
            return (line,'')
        i = line.index(' ') + 1
        return (line[:i],line[i:])

