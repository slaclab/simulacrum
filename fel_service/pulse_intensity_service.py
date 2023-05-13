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

M_ELEC      = 0.51099895000e6 # eV
C           = 2.99792458e8    # m/sec
HC          = 1240            # eV nm


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

        tao_setup_cmds = [
            'show global',
            'show lat -no_slaves -at L_PERIOD UMA*',
            'set global init_lat_sigma_from_beam  = T',
            'set global lattice_calc_on = T',
            'set global lattice_calc_on = F',
            ]
        self.cmd_socket.send_pyobj({'cmd':'tao_batch', 'val':tao_setup_cmds})
        tao_setup_resp = self.cmd_socket.recv_pyobj()['result']

        init_path = tao_setup_resp[0][-2]
        und_params = tao_setup_resp[1][2:-2]

        # provide HXR/SXR GDET PV based on the model service beamline
        # determine beamline by checking which tao.init file the model service is using
        init_dir, init_f = os.path.split(init_path.split()[1])
        assert init_f == 'tao.init'
        self.beamline = init_dir.split('/')[-1].upper()
        self.und_line = self.beamline[-3:]
        if self.und_line not in ['HXR', 'SXR']:
            raise RuntimeError('Invalid model beamline. Must be HXR,SXR')
        elif self.und_line == 'HXR':
            self.und_start = 'BEGUNDH'
            device_name = 'GDET:FEE1:241'
            pulse_PV = HXRPulseIntensity(prefix=device_name)
        elif self.und_line == 'SXR':
            self.und_start = 'BEGUNDS'
            device_name = 'EM1K0:GMD:HPS'
            pulse_PV = SXRPulseIntensity(prefix=device_name)

        self.L_und = sum([float(row.split()[4]) for row in und_params])
        self.und_period = float(und_params[0].split()[5])

        self.add_pvs({device_name: pulse_PV})

        self.pulse_E_name = sorted(self.keys())[0]
        self.pulse_hist_name = sorted(self.keys())[1]

        self.pulse_history = deque(np.full((HIST_BUF_SIZE,), np.nan), maxlen=HIST_BUF_SIZE)

        L.info(f'FEL pulse intensity service running for {self.beamline} beamline.')

    def calculate_pulse_intensity(self):
        """
        uses Ming Xie formulas to get FEL saturation length, calculates pulse energy in mJ
        known blind spots:
         - no dependence on orbit
         - no UND tapering simulation
         - no 3D effects included
        """
        model_update_cmds = [
            f'show beam -lat {self.und_start}',
            f'python ele:param {self.und_start}|model e_tot',
            'show lat -no_slaves -at B_MAX UMA*',
            f'python ele:twiss {self.und_start}|model',
            # f'show beam {self.und_start}',
            # f'show emittance -ele {self.und_start}',
            ]
        self.cmd_socket.send_pyobj({'cmd':'tao_batch', 'val':model_update_cmds})
        model_update_resp = self.cmd_socket.recv_pyobj()['result']

        sigma_vec  = model_update_resp[0][3].split()[1:]
        E_tot      = float(model_update_resp[1][0].split(';')[3])
        und_params = model_update_resp[2][2:-2]
        und_twiss  = model_update_resp[3]

        sigma_x   = float(sigma_vec[0])
        sigma_y   = float(sigma_vec[2])
        sigma_z   = float(sigma_vec[4])
        sigma_pz  = float(sigma_vec[5])

        Q_bunch = 180e-12

        gamma = E_tot / M_ELEC

        beta = np.sqrt(1 - (1/gamma**2))
        dt = sigma_z / (beta*C)
        I_peak = Q_bunch / dt

        beta_x = float(und_twiss[1].split(';')[3])
        eta_x  = float(und_twiss[5].split(';')[3])
        beta_y = float(und_twiss[7].split(';')[3])
        eta_y  = float(und_twiss[11].split(';')[3])
        delta = sigma_pz / E_tot

        emit_x = (sigma_x**2 + eta_x**2 * delta**2) / beta_x
        emit_y = (sigma_y**2 + eta_y**2 * delta**2) / beta_y
        n_emit = gamma * beta * np.sqrt(emit_x * emit_y)

        und_bmax_all = [float(row.split()[5]) for row in und_params]
        und_K_all = [((0.026*C)/(2*np.pi*M_ELEC)) * B_max for B_max in und_bmax_all]

        mx_out = mingxie(
            sigma_x=sigma_x, und_lambda=self.und_period, und_k=und_K_all[0],
            current=I_peak, gamma=gamma, norm_emit=n_emit, sigma_E=sigma_pz
            )

        E_FEL = HC / (mx_out['fel_wavelength']*1e9)

        L_gain = mx_out['gain_length']
        L_sat = mx_out['saturation_length']
        rho = mx_out['pierce_parameter']

        E_pulse_sat = rho * E_tot * Q_bunch * 1e3

        # Exponential power gain until saturation,
        # roughly linear gain after (assuming sensible UND taper)
        if self.L_und < L_sat:
            E_pulse = E_pulse_sat * np.exp(-(L_sat - self.L_und)/L_gain)
        else:
            E_pulse = E_pulse_sat * (self.L_und/L_sat)

        machine_summary = \
            f'    UND length  = {self.L_und:.3f} m\n' + \
            f'    UND period  = {self.und_period*1e3:.3f} cm\n' + \
            f'    start K     = {und_K_all[0]:.3f}'

        beam_summary = \
            f'    Q           = {Q_bunch*1e12:.3f} pC\n' + \
            f'    E           = {E_tot*1e-6:.3f} MeV\n' + \
            f'    sigma x     = {sigma_x*1e6:.3f} um\n' + \
            f'    norm emit   = {n_emit*1e6:.3f} mm-mrad \n' + \
            f'    bunch len   = {dt*1e15:.3f} fs\n' + \
            f'    I           = {I_peak:.3f} A\n' + \
            f'    sigma E     = {sigma_pz*1e-3:.3f} keV\n' + \
            f'    start K     = {und_K_all[0]:.3f}'

        output_summary = \
            f"    gain length = {L_gain:.3f} m\n" + \
            f"    sat. length = {L_sat:.3f} m\n" + \
            f"    sat. power  = {mx_out['saturation_power']:.3e} W\n" + \
            f"    lambda_FEL  = {mx_out['fel_wavelength']*1e9:.3e} nm\n" + \
            f"    E_FEL       = {E_FEL:.1f} eV\n" + \
            f"    rho         = {rho:.3e}\n" + \
            f"    E_pulse     = {E_pulse:.3f} mJ"

        update_summary = \
            f'Simulated FEL pulse energy updated\n' + \
            f'  Machine Inputs:\n{machine_summary}\n' + \
            f'  Beam Inputs:\n{beam_summary}\n' + \
            f'  Outputs:\n{output_summary}'

        L.debug(update_summary)

        return E_pulse

    async def update_pulse_intensity(self):
        E_pulse = self.calculate_pulse_intensity()
        ts = time.time()
        await self[self.pulse_E_name].write(E_pulse, timestamp=ts)
        self.pulse_history.append(E_pulse)
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