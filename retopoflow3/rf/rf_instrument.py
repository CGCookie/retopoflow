'''
Copyright (C) 2023 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Williamson, and Patrick Moore

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

import bpy
import json
from queue import Queue


from ...config.options import options

class RetopoFlow_Instrumentation:
    instrument_queue = Queue()
    instrument_thread = None

    def instrument_write(self, action):
        if not options['instrument']: return

        tb_name = options.get_path('instrument_filename')
        if tb_name not in bpy.data.texts: bpy.data.texts.new(tb_name)
        tb = bpy.data.texts[tb_name]

        target_json = self.rftarget.to_json()
        data = {'action': action, 'target': target_json}
        data_str = json.dumps(data, separators=[',',':'], indent=0)
        self.instrument_queue.put(data_str)

        # write data to end of textblock asynchronously
        # TODO: try writing to file (text/binary), because writing to textblock is _very_ slow! :(
        def write_out():
            while True:
                if self.instrument_queue.empty():
                    time.sleep(0.1)
                    continue
                data_str = self.instrument_queue.get()
                data_str = data_str.splitlines()
                tb.write('')        # position cursor to end
                for line in data_str:
                    tb.write(line)
                tb.write('\n')
        if not self.instrument_thread:
            # executor only needed to start the following instrument_thread
            executor = ThreadPoolExecutor()
            self.instrument_thread = executor.submit(write_out)
