#!/usr/bin/env python3
import os
import sys
import pickle
import pytao
import numpy as np
import asyncio
import zmq
from zmq.asyncio import Context
import simulacrum 

#set up python logger
L = simulacrum.util.SimulacrumLog(os.path.splitext(os.path.basename(__file__))[0], level='INFO')

class ModelService:
    def __init__(self):
        tao_lib = os.environ.get('TAO_LIB', '')
        self.tao = pytao.Tao(so_lib=tao_lib)
        path_to_lattice = os.path.join(os.path.dirname(os.path.realpath(__file__)), "lcls.lat")
        path_to_init = os.path.join(os.path.dirname(os.path.realpath(__file__)), "tao.init")
        self.tao.init("-noplot -lat {lat_path} -init {init_path}".format(lat_path=path_to_lattice, init_path=path_to_init))
        self.ctx = Context.instance()
        self.model_broadcast_socket = zmq.Context().socket(zmq.PUB)
        self.model_broadcast_socket.bind("tcp://*:{}".format(os.environ.get('MODEL_BROADCAST_PORT', 12412)))

    def start(self):
        L.info("Starting Model Service.")
        loop = asyncio.get_event_loop()
        task = loop.create_task(self.recv())
        try:
            loop.run_until_complete(task)
        except KeyboardInterrupt:
            task.cancel()
    
    def set_corrector_strength(self, name, new_strength, axis=None):
        if not axis:
            if name.startswith("XC"):
                axis = "h"
            elif name.startswith("YC"):
                axis = "v"
            else:
                raise Exception("Could not determine if corrector is horizontal or vertical.")
        axis = axis.lower()
        if axis == "x":
            axis = "h"
        elif axis == "y":
            axis = "v"
        if axis not in ["h", "v"]:
            raise Exception("Invalid Axis")
        result = self.tao.cmd("set ele {element} {axis}kick = {strength}".format(element=name, axis=axis, strength=new_strength))
        result = "".join(result)
        if "ERROR" in result:
            raise Exception(result)
        else:
            self.send_orbit()
            self.send_profiles_twiss() 
            self.send_prof_orbit()
            self.send_und_twiss()
        
    
    def get_orbit(self):
        #Get X Orbit
        x_orb_text = self.tao.cmd("show data orbit.x")[3:-2]
        x_orb = _orbit_array_from_text(x_orb_text)
        #Get Y Orbit
        y_orb_text = self.tao.cmd("show data orbit.y")[3:-2]
        y_orb = _orbit_array_from_text(y_orb_text)
        return np.stack((x_orb, y_orb))

    def get_prof_orbit(self):
        #Get X Orbit
        x_orb_text = self.tao.cmd("show data orbit.profx")[3:-2]
        x_orb = _orbit_array_from_text(x_orb_text)
        #Get Y Orbit
        y_orb_text = self.tao.cmd("show data orbit.profy")[3:-2]
        y_orb = _orbit_array_from_text(y_orb_text)
        return np.stack((x_orb, y_orb))
    
  

    def get_twiss(self):
        twiss_text = self.tao.cmd("show lat -no_label_lines -at alpha_a -at beta_a -at alpha_b -at beta_b UNDSTART")
        #format to list of comma separated values
        msg='twiss from get_twiss: {}'.format(twiss_text)
        L.info(msg)
        twiss = twiss_text[0].split()
        return twiss

    def old_get_orbit(self):
        #Get X Orbit
        x_orb_text = self.tao.cmd("python lat_list 1@0>>BPM*|model orbit.vec.1")
        x_orb = _orbit_array_from_text(x_orb_text)
        #Get Y Orbit
        y_orb_text = self.tao.cmd("python lat_list 1@0>>BPM*|model orbit.vec.3")
        y_orb = _orbit_array_from_text(y_orb_text)
        return np.stack((x_orb, y_orb))
   
    #information broadcast by the model is sent as two separate messages:
    #metadata message: sent first with 1) tag describing data for services to filter on, 2) type -optional, 3) size -optional
    #data message: sent either as a python object or a series of bits
    
    def send_orbit(self):
        orb = self.get_orbit()
        metadata = {"tag" : "orbit", "dtype": str(orb.dtype), "shape": orb.shape}
        self.model_broadcast_socket.send_pyobj(metadata, zmq.SNDMORE)
        self.model_broadcast_socket.send(orb)

    def send_prof_orbit(self):
        orb = self.get_prof_orbit()
        metadata = {"tag" : "prof_orbit", "dtype": str(orb.dtype), "shape": orb.shape}
        self.model_broadcast_socket.send_pyobj(metadata, zmq.SNDMORE)
        self.model_broadcast_socket.send(orb)

    def send_profiles_twiss(self):
        L.info('Sending Profile');
        twiss_text = np.asarray(self.tao.cmd("show lat -at beta_a -at beta_b Instrument::OTR*,Instrument::YAG*"))
        metadata = {"tag" : "prof_twiss", "dtype": str(twiss_text.dtype), "shape": twiss_text.shape}
        self.model_broadcast_socket.send_pyobj(metadata, zmq.SNDMORE)
        self.model_broadcast_socket.send(np.stack(twiss_text));        
           
    def send_und_twiss(self):
        twiss = self.get_twiss()
        metadata = {"tag": "und_twiss"}
        self.model_broadcast_socket.send_pyobj(metadata, zmq.SNDMORE)
        self.model_broadcast_socket.send_pyobj(twiss)
    
    async def recv(self):
        s = self.ctx.socket(zmq.REP)
        s.bind("tcp://*:{}".format(os.environ.get('MODEL_PORT', "12412")))
        while True:
            p = await s.recv_pyobj()
            msg = "Got a message: {}".format(p)
            L.info(msg)
            if p['cmd'] == 'corr':
                try:
                    self.set_corrector_strength(name=p['name'], new_strength=p['val'], axis=p.get('axis'))
                    await s.send_pyobj({'status': 'ok'})
                except Exception as e:
                    await s.send_pyobj({'status': 'fail', 'err': e})
            elif p['cmd'] == 'tao':
                try:
                    retval = self.tao.cmd(p['val'])
                    await s.send_pyobj({'status': 'ok', 'result': retval})
                except Exception as e:
                    await s.send_pyobj({'status': 'fail', 'err': e})
            elif p['cmd'] == 'send_orbit':
                try:
                    self.send_orbit()
                    await s.send_pyobj({'status': 'ok'})
                except Exception as e:
                    await s.send_pyobj({'status': 'fail', 'err': e})
            elif p['cmd'] == 'echo':
                    await s.send_pyobj({'status': 'ok', 'result': p['val']})
            elif p['cmd'] == 'send_profiles_twiss':
                self.send_profiles_twiss()
                self.send_prof_orbit()
                await s.send_pyobj({'status': 'ok'})
            elif p['cmd'] == 'send_und_twiss':
                self.send_und_twiss()
                await s.send_pyobj({'status': 'ok'})
    

def _orbit_array_from_text(text):
    return np.array([float(l.split()[5]) for l in text])*1000.0

if __name__=="__main__":
    serv = ModelService()
    serv.start()

