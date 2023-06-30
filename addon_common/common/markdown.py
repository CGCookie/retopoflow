'''
Copyright (C) 2023 CG Cookie
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

# markdown line (first line only, ex: table)
line_tests = {
    'h1':     re.compile(r'(?<!#)# +(?P<text>.+)'),
    'h2':     re.compile(r'(?<!#)## +(?P<text>.+)'),
    'h3':     re.compile(r'(?<!#)### +(?P<text>.+)'),
    'ul':     re.compile(r'(?P<indent> *)- +(?P<text>.+)'),
    'ol':     re.compile(r'(?P<indent> *)\d+\. +(?P<text>.+)'),
    'img':    re.compile(r'!\[(?P<caption>[^\]]*)\]\((?P<filename>[^) ]+)(?P<style>[^)]*)\)'),
    'table':  re.compile(r'\| +(([^|]*?) +\|)+'),
}

# markdown inline
inline_tests = {
    'br':       re.compile(r'<br */?> *'),
    'img':      re.compile(r'!\[(?P<caption>[^\]]*)\]\((?P<filename>[^) ]+)(?P<style>[^)]*)\)'),
    'bold':     re.compile(r'\*(?P<text>.+?)\*'),
    'code':     re.compile(r'`(?P<text>[^`]+)`'),
    'link':     re.compile(r'\[(?P<text>.+?)\]\((?P<link>.+?)\)'),
    'italic':   re.compile(r'_(?P<text>.+?)_'),
    'html':     re.compile(r'''<((?P<tagname>[a-zA-Z]+)(?P<params>( +(?P<key>[a-zA-Z_]+(=(?P<val>"[^"]*"|'[^']*'|[^"' >]+))?)))*)(>(?P<contents>.*?)(?P<closetag></\2>)|(?P<selfclose> +/>))'''),
    # 'checkbox': re.compile(r'<input (?P<params>.*?type="checkbox".*?)>(?P<innertext>.*?)<\/input>'),
    # 'number':   re.compile(r'<input (?P<params>.*?type="number".*?)>'),
    # 'button':   re.compile(r'<button(?P<params>[^>]*)>(?P<innertext>.*?)<\/button>'),
    # 'progress': re.compile(r'<progress(?P<params>.*?)(>(?P<innertext>.*?)<\/progress>| \/>)'),

    # https://www.toptal.com/designers/htmlarrows/arrows/
    'arrow':    re.compile(r'&(?P<dir>uarr|darr|larr|rarr|harr|varr|uArr|dArr|lArr|rArr|hArr|vArr); *'),
}

# process markdown text similarly to Markdown
preprocessing = [
    (r'<!--.*?-->', r''),       # remove comments
    (r'^\n*',       r''),       # remove leading \n
    (r'\n*$',       r''),       # remove trailing \n
    (r'\n\n\n*',    r'\n\n'),   # 2+ \n => \n\n
    (r'---',        r'—'),      # em dash
    (r'(?<!-)--',   r'–'),      # en dash
]

# https://stackoverflow.com/questions/3809401/what-is-a-good-regular-expression-to-match-a-url
re_url = re.compile(r'^((https?)|mailto)://([-a-zA-Z0-9@:%._\+~#=]+\.)*?[-a-zA-Z0-9@:%._+~#=]+\.[a-zA-Z0-9()]{1,6}\b([-a-zA-Z0-9()@:%_+.~#?&/=]*)$')
re_html_char = re.compile(r'(?P<pre>[^ ]*?)(?P<code>&([a-zA-Z]+|#x?[0-9A-Fa-f]+);)(?P<post>.*)')
re_embedded_code = re.compile(r'(?P<pre>[^ `]+)(?P<code>`[^`]*`)(?P<post>.*)')

class Markdown:
    @staticmethod
    def preprocess(txt):
        for m,r in preprocessing:
            txt = re.sub(m, r, txt)
        return txt

    @staticmethod
    def is_url(txt): return re_url.match(txt) is not None

    @staticmethod
    def match_inline(line):
        #line = line.lstrip()    # ignore leading spaces
        for (t,r) in inline_tests.items():
            m = r.match(line)
            if m: return (t, m)
        return (None, None)

    @staticmethod
    def match_line(line):
        line = line.rstrip()    # ignore trailing spaces
        for (t,r) in line_tests.items():
            m = r.match(line)
            if m: return (t, m)
        return (None, None)

    @staticmethod
    def split_word(line, allow_empty_pre=False):
        # search for html characters, like &nbsp;
        m = re_html_char.match(line)
        if m:
            pr = m.group('pre')
            co = m.group('code')
            po = m.group('post')
            if co == '&nbsp;':
                # &nbsp; must get handled specially later!
                # for now, consider &nbsp; part of the pre
                npr,npo = Markdown.split_word(po, allow_empty_pre=True)
                return (f'{pr}{co}{npr}', npo)
            if pr or allow_empty_pre:
                return (pr, f'{co}{po}')
            return (co, po)
        # search for embedded code in word, like (`-`)
        m = re_embedded_code.match(line)
        if m:
            pr = m.group('pre')
            co = m.group('code')
            po = m.group('post')
            return (pr, f'{co}{po}')
        if ' ' not in line:
            return (line,'')
        i = line.index(' ') + 1
        return (line[:i],line[i:])

