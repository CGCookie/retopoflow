'''
Copyright (C) 2024 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Lampel

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
import bmesh
from bmesh.types import BMVert, BMEdge, BMFace

def get_all_selected(bm):
    return {
        BMVert: get_all_selected_bmverts(bm),
        BMEdge: get_all_selected_bmedges(bm),
        BMFace: get_all_selected_bmfaces(bm),
    }

def get_all_selected_bmverts(bm):
    return { bmv for bmv in bm.verts if bmv.select and not bmv.hide }
def get_all_selected_bmedges(bm):
    return { bme for bme in bm.edges if bme.select and not bme.hide }
def get_all_selected_bmfaces(bm):
    return { bmf for bmf in bm.faces if bmf.select and not bmf.hide }

def deselect_all(bm):
    bm.select_history.clear()
    for bmv in bm.verts: bmv.select_set(False)
def select_set(bm, bmelem, selected):
    if selected: select(bm, bmelem)
    else: deselect(bm, bmelem)
def select(bm, bmelem):
    bm.select_history.add(bmelem)
    bmelem.select_set(True)
def deselect(bm, bmelem):
    bm.select_history.discard(bmelem)
    bmelem.select_set(False)
def reselect(bm, bmelem):
    deselect(bm, bmelem)
    select(bm, bmelem)

def flush_selection(bm, emesh):
    bm.select_flush(True)
    bm.select_flush(False)
    bmesh.update_edit_mesh(emesh)

def shared_link_edges(bmvs):
    bmes = None
    for bmv in bmvs:
        if bmes is None:
            bmes = set(bmv.link_edges)
        else:
            bmes &= set(bmv.link_edges)
    return bmes

def shared_link_faces(bmvs):
    bmfs = None
    for bmv in bmvs:
        if bmfs is None:
            bmfs = set(bmv.link_faces)
        else:
            bmfs &= set(bmv.link_faces)
    return bmfs