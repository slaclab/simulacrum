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
from collections import deque
from functools import partial

#set up python logger
L = simulacrum.util.SimulacrumLog(os.path.splitext(os.path.basename(__file__))[0], level='INFO')

HIST_BUF_SIZE = 2800

class BPMPV(PVGroup):

    pvprop_position = partial(pvproperty,
        value=0.0, read_only=True, record='ai',
        upper_disp_limit=3.0, lower_disp_limit=-3.0,
        precision=4, units='mm'
        )
    pvprop_position_buffer = partial(pvprop_position,
        max_length=HIST_BUF_SIZE
        )

    pvprop_tmit = partial(pvproperty,
        value=0.0, read_only=True, record='ai',
        upper_disp_limit=1.0e10, lower_disp_limit=0
        )
    pvprop_tmit_buffer = partial(pvprop_tmit,
        max_length=HIST_BUF_SIZE
        )

    x       = pvprop_position(name=':X')
    x_hstbr = pvprop_position_buffer(name=':XHSTBR')
    x_hst1  = pvprop_position_buffer(name=':XHST1')
    x_hst2  = pvprop_position_buffer(name=':XHST2')

    y       = pvprop_position(name=':Y')
    y_hstbr = pvprop_position_buffer(name=':YHSTBR')
    y_hst1  = pvprop_position_buffer(name=':YHST1')
    y_hst2  = pvprop_position_buffer(name=':YHST2')

    tmit       = pvprop_tmit(name=':TMIT')
    tmit_hstbr = pvprop_tmit_buffer(name=':TMITHSTBR')
    tmit_hst1  = pvprop_tmit_buffer(name=':TMITHST1')
    tmit_hst2  = pvprop_tmit_buffer(name=':TMITHST2')

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
        self.orbit = self.initialize_orbit(bpms)
        self.history = self.initialize_history_buffers(bpms)
        L.info("Initialization complete.")
    
    def initialize_orbit(self, bpms):
        # First, get the list of BPMs and their Z locations from the model service
        # This is maybe brittle because we use Tao's "show" command, then parse
        # the results, which the Tao authors advise against because the format of the 
        # results might change.  Oh well, I can't figure out a better way to do it.
        # TODO: use tao python command instead.
        L.info("Initializing with data from model service.")
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

    def initialize_history_buffers(self, bpms):
        """
        construct self.history ring buffers for X, Y and TMIT
        We'll need 3 * N_bpms buffers!
        """
        L.info("Initializing history buffers.")
        x_history, y_history, tmit_history = [], [], []
        all_nans = np.full((HIST_BUF_SIZE,), np.nan)
        for i in range(len(bpms)):
            x_history.append(deque(all_nans, maxlen=HIST_BUF_SIZE))
            y_history.append(deque(all_nans, maxlen=HIST_BUF_SIZE))
            tmit_history.append(deque(all_nans, maxlen=HIST_BUF_SIZE))

        return [x_history, y_history, tmit_history]
    
    def fetch_bpm_list(self):
        self.cmd_socket.send_pyobj({"cmd": "tao", "val": "show data orbit.x"})
        orbit_bpms = [row.split()[3] for row in self.cmd_socket.recv_pyobj()['result'][3:-2]]
        self.cmd_socket.send_pyobj({"cmd": "tao", "val": "show ele BPM*,RFB*,CMB*"})
        # filter bpms to use only devices in the 'orbit' datum
        bpms = []
        for bpm in [row.split(None, 3)[1:3] for row in self.cmd_socket.recv_pyobj()['result'][:-1]]:
            if bpm[0] in orbit_bpms: bpms.append(bpm)
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
        for i, row in enumerate(self.orbit):
            if row['device_name']+":X" not in self: continue

            if not row['alive']:
                severity = AlarmSeverity.INVALID_ALARM
            else:
                severity = AlarmSeverity.NO_ALARM

            await self[row['device_name']+":X"].write(row['x'], severity=severity, timestamp=ts)
            await self[row['device_name']+":Y"].write(row['y'], severity=severity, timestamp=ts)
            await self[row['device_name']+":TMIT"].write(row['tmit'], timestamp=ts)

            # update history buffers
            self.history[0][i].append(row['x'])
            self.history[1][i].append(row['y'])
            self.history[2][i].append(row['tmit'])

            x_hst = list(self.history[0][i])
            y_hst = list(self.history[1][i])
            tmit_hst = list(self.history[2][i])

            # 'HST1' and 'HST2' are simple duplicates of the 'HSTBR' buffer to reduce memory cost
            # no simulated timing anyways, so custom EDEFs aren't meaningful

            await self[row['device_name']+":XHSTBR"].write(x_hst, severity=severity, timestamp=ts)
            await self[row['device_name']+":XHST1"].write(x_hst, severity=severity, timestamp=ts)
            await self[row['device_name']+":XHST2"].write(x_hst, severity=severity, timestamp=ts)

            await self[row['device_name']+":YHSTBR"].write(y_hst, severity=severity, timestamp=ts)
            await self[row['device_name']+":YHST1"].write(y_hst, severity=severity, timestamp=ts)
            await self[row['device_name']+":YHST2"].write(y_hst, severity=severity, timestamp=ts)

            await self[row['device_name']+":TMITHSTBR"].write(tmit_hst, timestamp=ts)
            await self[row['device_name']+":TMITHST1"].write(tmit_hst, timestamp=ts)
            await self[row['device_name']+":TMITHST2"].write(tmit_hst, timestamp=ts)

    async def orbit_broadcast(self, async_lib):
        """
        'startup_hook' coroutine, listens for orbit broadcast from model
        'async_lib' arg is a requirement of caproto so that 'startup_hook' is library-agnostic
        but this method only works for asyncio
        """
        await self.publish_z()
        loop = asyncio.get_running_loop()
        loop.call_soon(self.request_orbit)
        loop.create_task(self.recv_orbit_array())

def main():
    service = BPMService()
    _, run_options = ioc_arg_parser(default_prefix='', desc="Simulated BPM Service")
    run(service, **run_options, startup_hook=service.orbit_broadcast)
    
if __name__ == '__main__':
    main()
