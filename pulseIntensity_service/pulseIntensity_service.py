import os
import asyncio
import numpy as np
from caproto.server import ioc_arg_parser, run, pvproperty, PVGroup
import simulacrum
import zmq
from zmq.asyncio import Context
from statistics import mean
from pulseIntensity import FELparameters

class GDETPV(PVGroup):
    enrc = pvproperty(value=0.0, name=':ENRC', read_only=True, mock_record='ai' )

class pulseIntensityService(simulacrum.Service):    
    def __init__(self):
        super().__init__()
        #gdet_pvs = {device_name: GDETPV(prefix=device_name) for device_name in simulacrum.util.device_names if device_name.startswith("GDET")}  #TODO use this line
        gdet_pvs = {'GDET:FEE1:241','GDET:FEE1:242','GDET:FEE1:243','GDET:FEE1:361','GDET:FEE1:362','GDET:FEE1:363','GDET:FEE1:364'}
        self.add_pvs(bpm_pvs)
        self.ctx = Context.instance()
        #cmd socket is a synchronous socket, we don't want the asyncio context.
        self.cmd_socket = zmq.Context().socket(zmq.REQ)        
        self.cmd_socket.connect("tcp://127.0.0.1:{}".format(os.environ.get('MODEL_PORT', 12312)))
        print("Initialization complete.")

    def get_parameters(self): #Im Here
        param = {}
        for (attr, dev_list, parse_func) in [("ENLD_MeV", "O_K*", _parse_klys_table)]:
            self.cmd_socket.send_pyobj({"cmd": "tao", "val": "show lat -no_label_lines -attribute ENLD_MeV -attribute Phase_Deg O_K*"})

            table = self.cmd_socket.recv_pyobj()
            init_vals.update(parse_func(table['result']))
        return param


Questions for Matt:

#Need to make Undulator Betas data, how to edit model init and stay in sync
#Commit klystron service
#


