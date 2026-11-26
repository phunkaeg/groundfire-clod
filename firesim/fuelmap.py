"""Read-only tiled fuel maps, with explicit unknown and provenance policies."""
from collections import OrderedDict
import json
import math
from pathlib import Path
import sqlite3
from urllib.parse import quote
import zlib

class FuelMap:
    def __init__(self,path,cache_tiles=24):
        self.path=Path(path).resolve()
        if not self.path.is_file():raise FileNotFoundError(self.path)
        if cache_tiles<1:raise ValueError('Cache must hold at least one tile')
        self.db=sqlite3.connect('file:'+quote(self.path.as_posix(),safe='/:')+'?mode=ro',uri=True)
        self.metadata={k:json.loads(v) for k,v in self.db.execute('SELECT key,value FROM metadata')}
        if self.metadata['schema']!=1:
            self.close();raise ValueError('Unsupported fuel-map schema')
        self.classes={c['id']:c for c in self.metadata['classes']}
        self.cache=OrderedDict();self.cache_tiles=cache_tiles

    def close(self):self.db.close()

    def sample(self,x,y):
        if not(math.isfinite(x) and math.isfinite(y)):raise ValueError('Non-finite map position')
        m=self.metadata
        ix=math.floor((x-m['origin_x_m'])/m['pixel_size_m'])
        iy=m['height']-1-math.floor((y-m['origin_y_m'])/m['pixel_size_m'])
        if not(0<=ix<m['width'] and 0<=iy<m['height']):
            return {'id':0,'name':'outside_map','kind':None,'moisture':None,'pixel':None}
        side=m['tile_size'];key=(ix//side,iy//side)
        if key not in self.cache:
            row=self.db.execute('SELECT width,height,classes FROM tiles WHERE tx=? AND ty=?',key).fetchone()
            if row is None:raise ValueError(f'Missing fuel tile {key}')
            w,h,packed=row;raw=zlib.decompress(packed)
            if len(raw)!=w*h:raise ValueError('Invalid fuel tile size')
            self.cache[key]=(w,h,raw)
            if len(self.cache)>self.cache_tiles:self.cache.popitem(last=False)
        else:self.cache.move_to_end(key)
        w,h,raw=self.cache[key];value=raw[(iy%side)*w+ix%side]
        return {**self.classes[value],'pixel':[ix,iy],'game_position_m':[x,y],
                'source_resolution_m':m['pixel_size_m'],'dataset_id':m['dataset_id'],
                'landcover_evidence':m.get('landcover_evidence'),'fuel_evidence':m.get('fuel_properties_evidence')}

    def provider_identity(self,sim_cell_size=10,*,unknown_policy='error'):
        return f"{self.metadata['dataset_id']}:cell{sim_cell_size:g}:unknown-{unknown_policy}:flat"

    def provider(self,sim_cell_size=10,*,unknown_policy='error'):
        if unknown_policy not in ('error','inert') or not math.isfinite(sim_cell_size) or sim_cell_size<=0:
            raise ValueError('Invalid provider policy/resolution')
        def fuel_at(ix,iy):
            sample=self.sample((ix+.5)*sim_cell_size,(iy+.5)*sim_cell_size)
            if sample['kind'] is None:
                if unknown_policy=='error':raise ValueError(f'Unclassified fuel at cell {ix},{iy}')
                # Explicit inert backend surrogate, not a claim this is a road.
                return {'kind':'road'}
            values={'kind':sample['kind'],'moisture':sample['moisture']}
            if sample.get('load_kg_m2') is not None:
                values['fuel_load']=sample['load_kg_m2']
            return values
        return fuel_at
