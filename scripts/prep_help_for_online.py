#!/usr/bin/python3

import os
import re
import sys
import glob
import shutil
import codecs

CLEAR_OLD_DOCS   = False
DELETE_ALL_OLD   = False
PROCESS_MARKDOWN = True
COPY_IMAGES      = True

re_keymap  = re.compile(r'{{(?P<key>.*?)}}')
re_options = re.compile(r'{\[(?P<key>.*?)\]}')
re_table   = re.compile(r'\|(?P<pre> +)(?P<dashes>--+)(?P<post> +)\|')
re_emptyth = re.compile(r'\|( +\|){2,}')
re_input   = re.compile(r'<input[^>]*>[^<]*</input>')
re_image   = re.compile(r'!\[(?P<caption>[^\]]*)\]\((?P<filename>[^ \)]+)(?P<styling>[^\)]*)\)')

def read_file(filename):
    try: return codecs.open(filename, encoding='utf-8').read()
    except: pass
    try: return codecs.open(filename, encoding='utf-16').read()
    except: pass
    return None

def write_file(filename, contents):
    codecs.open(filename, mode='w', encoding='utf-8').write(contents)

def process_mdown(mdown):
    # convert keymaps {{something foo, bar}}  ==>  {{ keymaps.something_foo }}, {{ keymaps.bar }}
    nf = []
    for l in mdown.splitlines():
        current, remaining = '', l
        while remaining:
            m = re_keymap.search(remaining)
            if not m:
                current += remaining
                remaining = ''
                continue
            pre, post = remaining[:m.start()], remaining[m.end():]
            keys = m.group('key').split(',')
            nkeys = []
            for key in keys:
                key = key.strip()
                key = key.replace(' ','_')
                key = '{{ site.data.keymaps.%s }}' % key
                nkeys += [key]
            keys = ', '.join(nkeys)
            current += pre + keys
            remaining = post
        nf += [current]
    mdown = '\n'.join(nf)

    # convert options  {[something foo]}  ==>  {{ options.something_foo }}
    nf = []
    for l in mdown.splitlines():
        current, remaining = '', l
        while remaining:
            m = re_options.search(remaining)
            if not m:
                current += remaining
                remaining = ''
                continue
            pre, post = remaining[:m.start()], remaining[m.end():]
            key = m.group('key')
            key = key.strip()
            key = key.replace(' ', '_')
            key = '{{ site.data.options.%s }}' % key
            current += pre + key
            remaining = post
        nf += [current]
    mdown = '\n'.join(nf)

    # convert tables | --- | --- | --- |  ==>  | :--- | :--- | :--- |
    nf = []
    for l in mdown.splitlines():
        while True:
            m = re_table.search(l)
            if not m: break
            l = l[:m.start()] + '|' + m.group('pre') + ':' + m.group('dashes') + m.group('post') + '|' + l[m.end():]
        nf += [l]
    mdown = '\n'.join(nf)

    # delete empty table headers
    mdown = re_emptyth.sub('', mdown)

    # remove inline image styling
    nf = []
    for l in mdown.splitlines():
        current, remaining = '', l
        while remaining:
            m = re_image.search(remaining)
            if not m:
                current += remaining
                remaining = ''
                continue
            pre, post = remaining[:m.start()], remaining[m.end():]
            img = f"![{m.group('caption')}]({m.group('filename')})"
            current += pre + img
            remaining = post
        nf += [current]
    mdown = '\n'.join(nf)

    # remove <input ...>...</input>
    # found in welcome.md
    nf = []
    for l in mdown.splitlines():
        while True:
            m = re_input.search(l)
            if not m: break
            l = l[:m.start()] + l[m.end():]
        nf += [l]
    mdown = '\n'.join(nf)

    mdown += '\n\n'

    return mdown

def delete_all(path):
    ppath = os.getcwd()
    os.chdir(path)
    for fn in glob.glob('*'):
        fn_full = os.path.join(path, fn)
        if os.path.isdir(fn):
            delete_all(fn_full)
        elif fn.endswith('.png'):
            os.remove(fn_full)
        elif fn.endswith('.md'):
            os.remove(fn_full)
        elif DELETE_ALL_OLD:
            os.remove(fn_full)
    os.chdir(ppath)
    os.rmdir(path)


path_here  = os.path.dirname(__file__)
path_root  = os.path.abspath(os.path.join(path_here, '..'))

path_help  = os.path.join(path_root, 'help')
path_icons = os.path.join(path_root, 'icons')

path_keys  = os.path.join(path_root, 'config', 'keymaps.py')
path_opts  = os.path.join(path_root, 'config', 'options.py')
path_human = os.path.join(path_root, 'addon_common', 'common', 'human_readable.py')

path_docs_config = os.path.join(path_root, 'docs_config')
path_docs    = os.path.join(path_root, 'docs')
path_data    = os.path.join(path_docs, '_data')
path_keymaps = os.path.join(path_data, 'keymaps.yml')
path_options = os.path.join(path_data, 'options.yml')

paths_config = {
    ('CNAME',        os.path.join(path_docs)),
    ('Gemfile',      os.path.join(path_docs)),
    ('Gemfile.lock', os.path.join(path_docs)),
    ('_config.yml',  os.path.join(path_docs)),
    ('default.html', os.path.join(path_docs, '_layouts')),
    ('main.css',     os.path.join(path_docs, 'assets', 'css'))
}


os.chdir(path_root)

if CLEAR_OLD_DOCS:
    # get online docs folder ready
    if os.path.exists(path_docs):
        # clear out old online docs
        delete_all(path_docs)

if not os.path.exists(path_docs):
    # create folder for online docs
    os.mkdir(path_docs)
if not os.path.exists(path_data):
    # create jekyll _data folder for variables
    os.mkdir(path_data)

if PROCESS_MARKDOWN:
    # process all markdown files
    os.chdir(path_help)
    for fn in glob.glob('*.md'):
        print(f'Processing: {fn}')
        mdown = read_file(fn)
        mdown = process_mdown(mdown)
        write_file(os.path.join(path_docs, fn), mdown)

if COPY_IMAGES:
    # copy over PNG files (except for thumbnails)
    os.chdir(path_help)
    for fn in glob.glob('*.png'):
        if fn.endswith('.thumb.png'): continue
        print(f'Copying: {fn}')
        shutil.copyfile(fn, os.path.join(path_docs, fn))
    os.chdir(path_icons)
    for fn in glob.glob('*.png'):
        if fn.endswith('.thumb.png'): continue
        print(f'Copying: {fn}')
        shutil.copyfile(fn, os.path.join(path_docs, fn))

# copy docs config files
os.chdir(path_docs_config)
for fn, path in paths_config:
    if not os.path.exists(path):
        os.makedirs(path)
    shutil.copyfile(fn, os.path.join(path, fn))


# load convert_actions_to_human_readable()
human_readable = read_file(path_human)
human_readable = '\n'.join(l for l in human_readable.splitlines() if not re.match(r'(from|import) ', l))
exec(human_readable, globals(), locals())

# load and process default keymaps (assuming LMB Select)
keymaps = read_file(path_keys)
keymaps = '\n'.join(l for l in keymaps.splitlines() if not re.match(r'(from|import) ', l))
exec(keymaps, globals(), locals())
keymaps = dict(default_rf_keymaps)
keymaps.update(left_rf_keymaps)
keymaps.update({
    'blender save': {'CTRL+S'},
    'blender undo': {'CTRL+Z'},
    'blender redo': {'SHIFT+CTRL+Z'},
})
keymaps_data = []
for k,v in keymaps.items():
    k = k.replace(' ', '_')
    # f'{pre}{wrap_pre}' + self.actions.to_human_readable(action, join=f'{wrap_post}{separator}{wrap_pre}', onlyfirst=onlyfirst) + f'{wrap_post}{post}'
    # v = '`' + convert_actions_to_human_readable(v, join='`, `') + '`'
    v = '<code>' + convert_actions_to_human_readable(v, join='</code>, <code>') + '</code>'
    keymaps_data.append(f'{k}: "{v}"')
keymaps_data = '\n'.join(keymaps_data)
write_file(path_keymaps, keymaps_data)


# process options
grab = [
    ('rf_version',          re.compile(r'''retopoflow_version *= *(?P<val>'[^']+'|"[^"]+")''')),
    ('warning_max_sources', re.compile(r''''warning max sources' *: *(?P<val>'[^']+'|"[^"]*")''')),
    ('warning_max_target',  re.compile(r''''warning max target' *: *(?P<val>'[^']+'|"[^"]*")''')),
]
options = read_file(path_opts)
options_data = []
for k,r in grab:
    m = r.search(options)
    if not m:
        print(f'Could not find match for ({k},{r})')
        continue
    options_data.append(f"{k}: {m.group('val')}")
options_data = '\n'.join(options_data)
write_file(path_options, options_data)

