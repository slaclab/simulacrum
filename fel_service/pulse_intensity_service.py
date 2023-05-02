"""
pulse intensity service: simulates FEL pulse intensity PV using zfel/mingxie

@author: Zack Buschmann (zack@slac.stanford.edu)
"""

import os
import sys
import time
import asyncio
import numpy as np
from collections import deque
from functools import partial

from caproto.server import ioc_arg_parser, run, pvproperty, PVGroup
import simulacrum
import zmq
from zmq.asyncio import Context

from zfel.mingxie import mingxie


L = simulacrum.util.SimulacrumLog(os.path.splitext(os.path.basename(__file__))[0], level='DEBUG')

HIST_BUF_SIZE = 2800

N_PARTICLES = 200
M_ELEC      = 0.51099895000e6 # eV
C           = 2.99792458e8    # m/sec
UNDH_PERIOD = 26.0e-3         # m
UNDS_PERIOD = 39.0e-3         # m


pvprop_pulse_E = partial(pvproperty,
    value=0.0, read_only=True, precision=4, units='mJ'
    )

class HXRPulseIntensity(PVGroup):
    pulse_energy = pvprop_pulse_E(name=':ENRC')
    pulse_history = pvprop_pulse_E(name=':ENRCHSTCUHBR', max_length=HIST_BUF_SIZE)

class SXRPulseIntensity(PVGroup):
    pulse_energy = pvprop_pulse_E(name=':milliJoulesPerPulse')
    pulse_history = pvprop_pulse_E(name=':milliJoulesPerPulseHSTCUSBR', max_length=HIST_BUF_SIZE)


class PulseIntensityService(simulacrum.Service):
    def __init__(self):
        super().__init__()
        self.ctx = Context.instance()
        self.cmd_socket = zmq.Context().socket(zmq.REQ)
        self.cmd_socket.connect("tcp://127.0.0.1:{}".format(os.environ.get('MODEL_PORT', 12312)))

        # provide HXR/SXR GDET PV based on the model service beamline
        # determine beamline by checking which tao.init file the model service is using
        self.cmd_socket.send_pyobj({'cmd': 'tao', 'val': 'show global'})
        init_path = self.cmd_socket.recv_pyobj()['result'][-2]
        init_dir, init_f = os.path.split(init_path.split()[1])
        assert init_f == 'tao.init'
        self.beamline = init_dir.split('/')[-1].upper()
        self.und_line = self.beamline[-3:]
        if self.und_line not in ['HXR', 'SXR']:
            raise RuntimeError('Invalid model beamline. Must be HXR,SXR')

        if self.und_line == 'HXR':
            self.und_start = 'BEGUNDH'
            self.und_period = UNDH_PERIOD
            device_name = 'GDET:FEE1:241'
            pulse_PV = HXRPulseIntensity(prefix=device_name)
        elif self.und_line == 'SXR':
            self.und_start = 'BEGUNDS'
            self.und_period = UNDS_PERIOD
            device_name = 'EM1K0:GMD:HPS'
            pulse_PV = SXRPulseIntensity(prefix=device_name)

        self.add_pvs({device_name: pulse_PV})

        self.pulse_E_name = sorted(self.keys())[0]
        self.pulse_hist_name = sorted(self.keys())[1]

        self.pulse_history = deque(np.full((HIST_BUF_SIZE,), np.nan), maxlen=HIST_BUF_SIZE)

        # configure model for multi-particle tracking, force recalculation
        L.debug(f'Enabling Tao multi-particle tracking with N = {N_PARTICLES}.')
        cmds = [
            'set global track_type = beam',
            f'set beam_init n_particle = {N_PARTICLES}',
            'set global lattice_calc_on = T',
            'set global lattice_calc_on = F',
            ]
        self.cmd_socket.send_pyobj({'cmd':'tao_batch', 'val':cmds})
        output = self.cmd_socket.recv_pyobj()

        L.info(f'FEL pulse intensity service running for {self.beamline} beamline.')

    def calculate_pulse_intensity(self):
        """
        uses Ming Xie formulas to get FEL saturation power, calculates pulse energy in mJ
        known blind spots:
         - assumes the FEL process will reach saturation i.e. gain length <= UND length
         - no dependence on orbit
         - no UND tapering simulation
         - no 3D effects included
        """
        cmds = [
            f'python bunch_params {self.und_start}|model',
            'show lat -no_slaves -at B_MAX UMA*',
            # f'show beam {self.und_start}',
            # f'show emittance -ele {self.und_start}',
            ]
        self.cmd_socket.send_pyobj({'cmd':'tao_batch', 'val':cmds})
        output = self.cmd_socket.recv_pyobj()

        bunch_params = output['result'][0]
        sigma_x  = float(bunch_params[  6].split(';')[3])
        n_emit_x = float(bunch_params[  9].split(';')[3])
        n_emit_y = float(bunch_params[ 19].split(';')[3])
        sigma_z  = float(bunch_params[ 26].split(';')[3])
        E_tot    = float(bunch_params[-12].split(';')[3])
        beta     = float(bunch_params[-11].split(';')[3])
        Q_bunch  = float(bunch_params[ -5].split(';')[3])

        und_params   = output['result'][1]
        und_bmax_all = [float(row.split()[5]) for row in und_params[2:-2]]

        dt = sigma_z / (beta*C)
        I_peak = Q_bunch / dt

        # questionable averaging to get normalized emittance
        n_emit = (n_emit_x + n_emit_y) / 2

        gamma = E_tot / M_ELEC

        # not sure where to find rms E-spread. Spitball 1e-5 for now
        sigma_e_rel = 1e-5
        sigma_e = sigma_e_rel * E_tot

        und_K_all = [((0.026*C)/(2*np.pi*M_ELEC)) * B_max for B_max in und_bmax_all]

        input_summary = \
            f'    Q         = {Q_bunch*1e12:.3f} pC\n' + \
            f'    E         = {E_tot:.3f} MeV\n' + \
            f'    sigma x   = {sigma_x*1e6:.3f} um\n' + \
            f'    norm emit = {n_emit*1e6:.3f} mm-mrad \n' + \
            f'    bunch len = {dt*1e15:.3f} fs\n' + \
            f'    I         = {I_peak:.3f} A\n' + \
            f'    sigma E   = {sigma_e*1e-3:.3f} keV\n' + \
            f'    start K   = {und_K_all[0]:.3f}'

        output = mingxie(
            sigma_x=sigma_x, und_lambda=self.und_period, und_k=und_K_all[0],
            current=I_peak, gamma=gamma, norm_emit=n_emit, sigma_E=sigma_e
            )

        E_FEL = 1240 / (output['fel_wavelength']*1e9)
        pulse_intensity = 1e3 * output['saturation_power'] * dt

        output_summary = \
            f"    gain length = {output['gain_length']:.3f} m\n" + \
            f"    sat. length = {output['saturation_length']:.3f} m\n" + \
            f"    sat. power  = {output['saturation_power']:.3e} W\n" + \
            f"    lambda_FEL  = {output['fel_wavelength']*1e9:.3e} nm\n" + \
            f"    E_FEL       = {E_FEL:.1f} eV\n" + \
            f"    rho         = {output['pierce_parameter']:.3e}\n" + \
            f"    E_pulse     = {pulse_intensity:.3f} mJ"

        update_summary = \
            f'Simulated FEL pulse energy updated\n' + \
            f'  Beam Inputs:\n{input_summary}\n' + \
            f'  Outputs:\n{output_summary}'

        L.debug(update_summary)

        return pulse_intensity

    async def update_pulse_intensity(self):
        pulse_E = self.calculate_pulse_intensity()
        ts = time.time()
        await self[self.pulse_E_name].write(pulse_E, timestamp=ts)
        self.pulse_history.append(pulse_E)
        await self[self.pulse_hist_name].write(list(self.pulse_history), timestamp=ts)

    async def watch_model(self, flags=0, copy=False, track=False):
        model_broadcast_socket = self.ctx.socket(zmq.SUB)
        model_broadcast_socket.connect(
            'tcp://127.0.0.1:{}'.format(os.environ.get('MODEL_BROADCAST_PORT', 66666))
            )
        model_broadcast_socket.setsockopt(zmq.SUBSCRIBE, b'')

        while True:
            md = await model_broadcast_socket.recv_pyobj(flags=flags)
            if md.get('tag', None) == 'model_update':
                L.info('Model updated. Recalculating pulse intensity.')
                await self.update_pulse_intensity()
            else:
                await model_broadcast_socket.recv(flags=flags)

    async def fel_broadcast(self, async_lib):
        await self.update_pulse_intensity()
        loop = asyncio.get_running_loop()
        loop.create_task(self.watch_model())


def main():
    service = PulseIntensityService()
    _, run_options = ioc_arg_parser(default_prefix='', desc="Simulated FEL pulse inensity service")
    run(service, **run_options, startup_hook=service.fel_broadcast)
    return

if __name__ == '__main__':
    main()