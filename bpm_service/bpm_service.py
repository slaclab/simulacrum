import os
import sys
import asyncio
import numpy as np
import time
from caproto.server import ioc_arg_parser, run, pvproperty, PVGroup
from caproto import AlarmStatus, AlarmSeverity
import simulacrum
import zmq
from zmq.asyncio import Context

#set up python logger
L = simulacrum.util.SimulacrumLog(os.path.splitext(os.path.basename(__file__))[0], level='INFO')


class BPMPV(PVGroup):
    x = pvproperty(value=0.0, name=':X', read_only=True, record='ai',
                   upper_disp_limit=3.0, lower_disp_limit=-3.0, precision=4, units='mm')
    y = pvproperty(value=0.0, name=':Y', read_only=True, record='ai',
                   upper_disp_limit=3.0, lower_disp_limit=-3.0, precision=4, units='mm')
    tmit = pvproperty(value=0.0, name=':TMIT', read_only=True, record='ai',
                   upper_disp_limit=1.0e10, lower_disp_limit=0)
    z = pvproperty(value=0.0, name=':Z', read_only=True, precision=2, units='m')
    
class BPMService(simulacrum.Service):
    def __init__(self):
        super().__init__()
        self.ctx = Context.instance()
        #cmd socket is a synchronous socket, we don't want the asyncio context.
        self.cmd_socket = zmq.Context().socket(zmq.REQ)
        self.cmd_socket.connect("tcp://127.0.0.1:{}".format(os.environ.get('MODEL_PORT', 12312)))
        bpms = self.fetch_bpm_list()
        device_names = [simulacrum.util.convert_element_to_device(bpm[0]) for bpm in bpms]
        L.debug(device_names)
        device_name_map = zip(bpms, device_names)
        bpm_pvs = {device_name: BPMPV(prefix=device_name) for device_name in device_names if device_name}
        self.add_pvs(bpm_pvs)
        one_hertz_aliases = {}
        for pv in self:
            if pv.endswith(":X") or pv.endswith(":Y") or pv.endswith(":TMIT"):
                one_hertz_aliases["{}1H".format(pv)] = self[pv]
        self.update(one_hertz_aliases)
        self.orbit = self.initialize_orbit()
        L.info("Initialization complete.")
    
    def initialize_orbit(self):
        # First, get the list of BPMs and their Z locations from the model service
        # This is maybe brittle because we use Tao's "show" command, then parse
        # the results, which the Tao authors advise against because the format of the 
        # results might change.  Oh well, I can't figure out a better way to do it.
        # TODO: use tao python command instead.
        L.info("Initializing with data from model service.")
        bpms = self.fetch_bpm_list()
        orbit = np.zeros(len(bpms), dtype=[('element_name', 'U60'), ('device_name', 'U60'), ('x', 'float32'), ('y', 'float32'), ('tmit', 'float32'), ('alive', 'bool'), ('z', 'float32')])
        for i, row in enumerate(bpms):
            (name, z) = row
            orbit['element_name'][i] = name
            try:
                orbit['device_name'][i] = simulacrum.util.convert_element_to_device(name)
            except KeyError:
                pass
            orbit['z'][i] = float(z)
        orbit = np.sort(orbit,order='z')
        return orbit
    
    def fetch_bpm_list(self):
        self.cmd_socket.send_pyobj({"cmd": "tao", "val": "show ele BPM*,RFB*,CMB*"})
        bpms = [row.split(None, 3)[1:3] for row in self.cmd_socket.recv_pyobj()['result'][:-1]]
        return bpms
    
    async def publish_z(self):
        L.info("Publishing Z PVs")
        for row in self.orbit:
            zpv = row['device_name']+":Z"
            if zpv in self:
                await self[zpv].write(row['z'])
    
    def request_orbit(self):
        self.cmd_socket.send_pyobj({"cmd": "send_orbit"})
        return self.cmd_socket.recv_pyobj()
        
    async def recv_orbit_array(self, flags=0, copy=False, track=False):
        """recv a numpy array"""
        model_broadcast_socket = self.ctx.socket(zmq.SUB)
        model_broadcast_socket.connect('tcp://127.0.0.1:{}'.format(os.environ.get('MODEL_BROADCAST_PORT', 66666)))
        model_broadcast_socket.setsockopt(zmq.SUBSCRIBE, b'')
        while True:
            L.debug("Checking for new orbit data.")
            md = await model_broadcast_socket.recv_pyobj(flags=flags)
            if md.get("tag", None) == "orbit":
                L.debug(f"Orbit data incoming: {md}")
                msg = await model_broadcast_socket.recv(flags=flags, copy=copy, track=track)
                L.debug(msg)
                buf = memoryview(msg)
                A = np.frombuffer(buf, dtype=md['dtype'])
                A = A.reshape(md['shape'])
                self.orbit['x'] = A[0]
                self.orbit['y'] = A[1]
                self.orbit['alive'] = A[2] > 0
                L.debug(self.orbit)
                await self.publish_orbit()
            else: 
                await model_broadcast_socket.recv(flags=flags, copy=copy, track=track)
                 
            
    async def publish_orbit(self):
        ts = time.time()
        for row in self.orbit:
            if row['device_name']+":X" in self:
                if not row['alive']:
                    severity = AlarmSeverity.INVALID_ALARM
                else:
                    severity = AlarmSeverity.NO_ALARM
                await self[row['device_name']+":X"].write(row['x'], severity=severity, timestamp=ts)
                await self[row['device_name']+":Y"].write(row['y'], severity=severity, timestamp=ts)
                await self[row['device_name']+":TMIT"].write(row['tmit'], timestamp=ts)
    
def main():
    service = BPMService()
    loop = asyncio.get_event_loop()
    _, run_options = ioc_arg_parser(
        default_prefix='',
        desc="Simulated BPM Service")
    loop.create_task(service.publish_z())
    loop.create_task(service.recv_orbit_array())
    loop.call_soon(service.request_orbit)
    run(service, **run_options)
    
if __name__ == '__main__':
    main()
