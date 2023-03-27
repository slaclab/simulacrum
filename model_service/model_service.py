#!/usr/bin/env python3
import os
import argparse
import sys
import pickle
import asyncio
import time
import numpy as np
import zmq
import pytao
from p4p.nt import NTTable
from p4p.server import Server as PVAServer
from p4p.server.asyncio import SharedPV
from zmq.asyncio import Context
import simulacrum


model_service_dir = os.path.dirname(os.path.realpath(__file__))
#set up python logger
L = simulacrum.util.SimulacrumLog(os.path.splitext(os.path.basename(__file__))[0], level='INFO')

class ModelService:
    def __init__(self, init_file, name, enable_jitter=False, plot=False):
        self.name = name
        tao_lib = os.environ.get('TAO_LIB', '')
        self.tao = pytao.Tao(so_lib=tao_lib)
        L.debug("Initializing Tao...")
        if plot: 
            self.tao.init("-init {init_file}".format(init_file=init_file))
        else:
            self.tao.init("-noplot -init {init_file}".format(init_file=init_file))
        L.debug("Tao initialization complete!")
        self.tao.cmd("set global lattice_calc_on = F")
        self.tao.cmd('set global var_out_file = " "')
        self.ctx = Context.instance()
        self.model_broadcast_socket = zmq.Context().socket(zmq.PUB)
        self.model_broadcast_socket.bind("tcp://*:{}".format(os.environ.get('MODEL_BROADCAST_PORT', 66666)))
        self.loop = asyncio.get_event_loop()
        self.jitter_enabled = enable_jitter
        self.twiss_table = NTTable([("element", "s"), ("device_name", "s"),
                                       ("s", "d"), ("length", "d"), ("p0c", "d"),
                                       ("alpha_x", "d"), ("beta_x", "d"), ("eta_x", "d"), ("etap_x", "d"), ("psi_x", "d"),
                                       ("alpha_y", "d"), ("beta_y", "d"), ("eta_y", "d"), ("etap_y", "d"), ("psi_y", "d")])
        self.rmat_table = NTTable([("element", "s"), ("device_name", "s"), ("s", "d"), ("length", "d"),
                              ("r11", "d"), ("r12", "d"), ("r13", "d"), ("r14", "d"), ("r15", "d"), ("r16", "d"),
                              ("r21", "d"), ("r22", "d"), ("r23", "d"), ("r24", "d"), ("r25", "d"), ("r26", "d"),
                              ("r31", "d"), ("r32", "d"), ("r33", "d"), ("r34", "d"), ("r35", "d"), ("r36", "d"),
                              ("r41", "d"), ("r42", "d"), ("r43", "d"), ("r44", "d"), ("r45", "d"), ("r46", "d"),
                              ("r51", "d"), ("r52", "d"), ("r53", "d"), ("r54", "d"), ("r55", "d"), ("r56", "d"),
                              ("r61", "d"), ("r62", "d"), ("r63", "d"), ("r64", "d"), ("r65", "d"), ("r66", "d")])
        initial_twiss_table, initial_rmat_table = self.get_twiss_table()
        sec, nanosec = divmod(float(time.time()), 1.0)
        initial_twiss_table = self.twiss_table.wrap(initial_twiss_table)
        initial_twiss_table['timeStamp']['secondsPastEpoch'] = sec
        initial_twiss_table['timeStamp']['nanoseconds'] = nanosec
        initial_rmat_table = self.rmat_table.wrap(initial_rmat_table)
        initial_rmat_table['timeStamp']['secondsPastEpoch'] = sec
        initial_rmat_table['timeStamp']['nanoseconds'] = nanosec
        self.live_twiss_pv = SharedPV(nt=self.twiss_table, 
                           initial=initial_twiss_table,
                           loop=self.loop)
        self.design_twiss_pv = SharedPV(nt=self.twiss_table, 
                           initial=initial_twiss_table,
                           loop=self.loop)
        self.live_rmat_pv = SharedPV(nt=self.rmat_table, 
                           initial=initial_rmat_table,
                           loop=self.loop)
        self.design_rmat_pv = SharedPV(nt=self.rmat_table, 
                           initial=initial_rmat_table,
                           loop=self.loop)
        self.screens = self.get_screens()
        self.bpms = self.get_bpms()
        self.recalc_needed = False
        self.pva_needs_refresh = False
        self.need_zmq_broadcast = False
    
    def start(self):
        L.info("Starting %s Model Service.", self.name)
        pva_server = PVAServer(providers=[{f"SIMULACRUM:SYS0:1:{self.name}:LIVE:TWISS": self.live_twiss_pv,
                                           f"SIMULACRUM:SYS0:1:{self.name}:DESIGN:TWISS": self.design_twiss_pv,
                                           f"SIMULACRUM:SYS0:1:{self.name}:LIVE:RMAT": self.live_rmat_pv,
                                           f"SIMULACRUM:SYS0:1:{self.name}:DESIGN:RMAT": self.design_rmat_pv,}])
        try:
            zmq_task = self.loop.create_task(self.recv())
            pva_refresh_task = self.loop.create_task(self.refresh_pva_table())
            broadcast_task = self.loop.create_task(self.broadcast_model_changes())
            jitter_task = self.loop.create_task(self.add_jitter())
            self.loop.run_forever()
        except KeyboardInterrupt:
            L.info("Shutting down Model Service.")
            zmq_task.cancel()
            pva_refresh_task.cancel()
            broadcast_task.cancel()
            pva_server.stop()
        finally:
            self.loop.close()
            L.info("Model Service shutdown complete.")
    
    def get_twiss_table(self):
        """
        Queries Tao for model and RMAT info.
        Returns: A (twiss_table, rmat_table) tuple.
        """
        start_time = time.time()
        #First we get a list of all the elements.
        #NOTE: the "-no_slaves" option for python lat_list only works in Tao 2019_1112 or above.
        element_name_list = self.tao.cmd("python lat_list -track_only 1@0>>*|model ele.name")
        L.debug(element_name_list)
        for row in element_name_list:
            assert "ERROR" not in element_name_list, "Fetching element names failed.  This is probably because a version of Tao older than 2019_1112 is being used."
        last_element_index = 0
        for i, row in enumerate(reversed(element_name_list)):
            if row == "END":
                last_element_index = len(element_name_list)-1-i
                break
        element_data = {}
        attrs = ("ele.s", "ele.l", "orbit.energy", "ele.a.alpha", "ele.a.beta", "ele.x.eta", "ele.x.etap", "ele.a.phi", "ele.b.alpha", "ele.b.beta", "ele.y.eta", "ele.y.etap", "ele.b.phi", "ele.mat6")
        for attr in attrs:
            element_data[attr] = self.tao.cmd_real("python lat_list -track_only 1@0>>*|model real:{}".format(attr))
            if attr == 'ele.mat6':
                element_data[attr] = element_data[attr].reshape((-1, 6, 6))
            assert len(element_data[attr]) == len(element_name_list), "Number of elements in model data for {} doesn't match number of element names.".format(attr)
        
        combined_rmat = np.identity(6)
        twiss_table_rows = []
        rmat_table_rows = []
        for i in range(0,last_element_index+1):
            element_name = element_name_list[i]
            try:
                device_name = simulacrum.util.convert_element_to_device(element_name.split("#")[0])
            except KeyError:
                device_name = ""
            element_rmat = element_data['ele.mat6'][i]
            rmat = np.matmul(element_rmat, combined_rmat)
            combined_rmat = rmat
            twiss_table_rows.append({"element": element_name, "device_name": device_name, "s": element_data['ele.s'][i], "length": element_data['ele.l'][i], "p0c": element_data['orbit.energy'][i],
                               "alpha_x": element_data['ele.a.alpha'][i], "beta_x": element_data['ele.a.beta'][i], "eta_x": element_data['ele.x.eta'][i], "etap_x": element_data['ele.x.etap'][i], "psi_x": element_data['ele.a.phi'][i],
                               "alpha_y": element_data['ele.b.alpha'][i], "beta_y": element_data['ele.b.beta'][i], "eta_y": element_data['ele.y.eta'][i], "etap_y": element_data['ele.y.etap'][i], "psi_y": element_data['ele.b.phi'][i]})
            rmat_table_rows.append({
                               "element": element_name, "device_name": device_name, "s": element_data['ele.s'][i], "length": element_data['ele.l'][i],
                               "r11": rmat[0,0], "r12": rmat[0,1], "r13": rmat[0,2], "r14": rmat[0,3], "r15": rmat[0,4], "r16": rmat[0,5],
                               "r21": rmat[1,0], "r22": rmat[1,1], "r23": rmat[1,2], "r24": rmat[1,3], "r25": rmat[1,4], "r26": rmat[1,5],
                               "r31": rmat[2,0], "r32": rmat[2,1], "r33": rmat[2,2], "r34": rmat[2,3], "r35": rmat[2,4], "r36": rmat[2,5],
                               "r41": rmat[3,0], "r42": rmat[3,1], "r43": rmat[3,2], "r44": rmat[3,3], "r45": rmat[3,4], "r46": rmat[3,5],
                               "r51": rmat[4,0], "r52": rmat[4,1], "r53": rmat[4,2], "r54": rmat[4,3], "r55": rmat[4,4], "r56": rmat[4,5],
                               "r61": rmat[5,0], "r62": rmat[5,1], "r63": rmat[5,2], "r64": rmat[5,3], "r65": rmat[5,4], "r66": rmat[5,5]})
        end_time = time.time()
        L.debug("get_twiss_table took %f seconds", end_time - start_time)
        return twiss_table_rows, rmat_table_rows
    
    async def refresh_pva_table(self):
        """
        This loop continuously checks if the PVAccess table needs to be refreshed,
        and publishes a new table if it does.  The pva_needs_refresh flag is
        usually set when a tao command beginning with 'set' occurs.
        """
        while True:
            if self.pva_needs_refresh:
                sec, nanosec = divmod(float(time.time()), 1.0)
                new_twiss_table, new_rmat_table = self.get_twiss_table()
                new_twiss_table = self.twiss_table.wrap(new_twiss_table)
                new_twiss_table['timeStamp']['secondsPastEpoch'] = sec
                new_twiss_table['timeStamp']['nanoseconds'] = nanosec
                new_rmat_table = self.rmat_table.wrap(new_rmat_table)
                new_rmat_table['timeStamp']['secondsPastEpoch'] = sec
                new_rmat_table['timeStamp']['nanoseconds'] = nanosec
                self.live_twiss_pv.post(new_twiss_table)
                self.live_rmat_pv.post(new_rmat_table)
                self.pva_needs_refresh = False
            await asyncio.sleep(1.0)
        
    async def add_jitter(self):
        while True:
            if self.jitter_enabled:
                x0 = np.random.normal(0.0, 0.12*0.001)
                y0 = np.random.normal(0.0, 0.12*0.001)
                self.tao.cmd(f"set particle_start x = {x0}")
                self.tao.cmd(f"set particle_start y = {y0}")
                self.recalc_needed = True
                self.need_zmq_broadcast = True
            await asyncio.sleep(1.0)
    
    async def broadcast_model_changes(self):
        """
        This loop broadcasts new orbits, twiss parameters, etc. over ZMQ.
        """
        while True:
            if self.recalc_needed:
                self.tao.cmd("set global lattice_calc_on = T")
                self.tao.cmd("set global lattice_calc_on = F")
                self.recalc_needed = False
            if self.need_zmq_broadcast:
                try:
                    self.send_orbit()
                except Exception as e:
                    L.warning("SEND ORBIT FAILED: %s", e)
                try:
                    self.send_profiles_data()
                except Exception as e:
                    L.warning("SEND PROF DATA FAILED: %s", e)
                try:
                    self.send_und_twiss()
                except Exception as e:
                    L.warning("SEND UND TWISS FAILED: %s", e)

                self.need_zmq_broadcast = False
            await asyncio.sleep(0.1)
    
    def model_changed(self):
        self.recalc_needed = True
        self.pva_needs_refresh = True
        self.need_zmq_broadcast = True

    def get_bpms(self):
        return [row.split()[3] for row in self.tao_cmd("show data orbit.x")[3:-2]]
    
    def get_orbit(self):
        start_time = time.time()
        #Get X Orbit
        x_orb_text = self.tao_cmd("show data orbit.x")[3:-2]
        x_orb = _orbit_array_from_text(x_orb_text)
        #Get Y Orbit
        y_orb_text = self.tao_cmd("show data orbit.y")[3:-2]
        y_orb = _orbit_array_from_text(y_orb_text)
        #Get e_tot, which we use to see if the single particle beam is dead
        e_text = self.tao_cmd("show data orbit.e")[3:-2]
        e = _orbit_array_from_text(e_text)
        end_time = time.time()
        L.debug("get_orbit took %f seconds", end_time-start_time)
        return np.stack((x_orb, y_orb, e))

    def get_screens(self):
        screen_elements = self.tao_cmd('show ele monitor::YAG*,monitor::OTR*')[:-1]
        zs = [float(row.split()[2]) for row in screen_elements]
        names = [row.split()[1] for row in screen_elements]
        return np.sort(np.array(
            [(z, name) for z, name in zip(zs, names)],
            dtype=[('z', 'float32'), ('ele', 'U60')]), order='z')

    def get_prof_orbit(self):
        #Get X Orbit
        x_orb_text = self.tao_cmd("show data orbit.profx")[3:-2]
        x_orb = _orbit_array_from_text(x_orb_text)
        #Get Y Orbit
        y_orb_text = self.tao_cmd("show data orbit.profy")[3:-2]
        y_orb = _orbit_array_from_text(y_orb_text)
        return np.stack((x_orb, y_orb))
    
    def get_twiss(self):
        twiss_text = self.tao_cmd("show lat -no_label_lines -at alpha_a -at beta_a -at alpha_b -at beta_b UNDSTART")
        if "ERROR" in twiss_text[0]:
            twiss_text = self.tao_cmd("show lat -no_label_lines -at alpha_a -at beta_a -at alpha_b -at beta_b BEGUNDH")
        if "ERROR" in twiss_text[0]:
            twiss_text = self.tao_cmd("show lat -no_label_lines -at alpha_a -at beta_a -at alpha_b -at beta_b BEGUNDS")
        #format to list of comma separated values
        #msg='twiss from get_twiss: {}'.format(twiss_text)
        #L.info(msg)
        twiss = twiss_text[0].split()
        return twiss

    def old_get_orbit(self):
        #Get X Orbit
        x_orb_text = self.tao_cmd("python lat_list 1@0>>BPM*|model orbit.vec.1")
        x_orb = _orbit_array_from_text(x_orb_text)
        #Get Y Orbit
        y_orb_text = self.tao_cmd("python lat_list 1@0>>BPM*|model orbit.vec.3")
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

    def send_profiles_data(self):
        twiss_text = self.tao_cmd("show lat -no_label_lines -at beta_a -at beta_b -at e_tot Monitor::OTR*,Monitor::YAG*")
        prof_beta_x = [float(l.split()[5]) for l in twiss_text]
        prof_beta_y = [float(l.split()[6]) for l in twiss_text]
        prof_e = [float(l.split()[7]) for l in twiss_text]
        prof_names = [l.split()[1] for l in twiss_text]
        prof_orbit = self.get_prof_orbit()
        prof_data = np.concatenate((prof_orbit, np.array([prof_beta_x, prof_beta_y, prof_e,  prof_names])))

        metadata = {"tag" : "prof_data", "dtype": str(prof_data.dtype), "shape": prof_data.shape}
        self.model_broadcast_socket.send_pyobj(metadata, zmq.SNDMORE)
        self.model_broadcast_socket.send(prof_data);

    def send_particle_positions(self):
        twiss_text = self.tao_cmd("show lat -no_label_lines -at beta_a -at beta_b -at e_tot Monitor::OTR*,Monitor::YAG*")
        prof_names = [l.split()[1] for l in twiss_text]
        positions_all = {}
        for screen in prof_names:
            positions = self.get_particle_positions(screen);
            if not positions:
                continue
            positions_all[screen] = [[float(position.split()[1]), float(position.split()[3])] for position in positions]
        metadata = {"tag": "part_positions"}
        self.model_broadcast_socket.send_pyobj(metadata, zmq.SNDMORE)
        self.model_broadcast_socket.send_pyobj(positions_all)

    def get_particle_positions(self, screen):
        L.debug("Getting particle positions")
        cmd = "show particle -all -ele {screen}".format(screen=screen)
        results = self.tao_cmd(cmd);
        if(len(results) < 3):
            return False
        return results[2:]

    def send_und_twiss(self):
        twiss = self.get_twiss()
        metadata = {"tag": "und_twiss"}
        self.model_broadcast_socket.send_pyobj(metadata, zmq.SNDMORE)
        self.model_broadcast_socket.send_pyobj(twiss)
    
    def tao_cmd(self, cmd):
        if cmd.startswith("exit"):
            return "Please stop trying to exit the model service's Tao, you jerk!"
        result = self.tao.cmd(cmd)
        if cmd.startswith("set"):
            self.model_changed()
        return result
    
    def tao_batch(self, cmds):
        L.info("Starting command batch.")
        results = [self.tao_cmd(cmd) for cmd in cmds]
        L.info("Batch complete.")
        return results
    
    async def recv(self):
        s = self.ctx.socket(zmq.REP)
        s.bind("tcp://*:{}".format(os.environ.get('MODEL_PORT', "12312")))
        while True:
            p = await s.recv_pyobj()
            msg = "Got a message: {}".format(p)
            L.debug(msg)
            if p['cmd'] == 'tao':
                try:
                    retval = self.tao_cmd(p['val'])
                    await s.send_pyobj({'status': 'ok', 'result': retval})
                except Exception as e:
                    L.error("Tao command failed: {}".format(e))
                    await s.send_pyobj({'status': 'fail', 'err': e})
            elif p['cmd'] == 'send_orbit':
                self.model_changed() #Sets the flag that will cause an orbit broadcast
                await s.send_pyobj({'status': 'ok'})
            elif p['cmd'] == 'echo':
                    await s.send_pyobj({'status': 'ok', 'result': p['val']})
            elif p['cmd'] == 'send_profiles_twiss':
                self.model_changed() #Sets the flag that will cause a prof broadcast
                #self.send_profiles_twiss()
                #self.send_prof_orbit()
                await s.send_pyobj({'status': 'ok'})
            elif p['cmd'] == 'send_und_twiss':
                self.model_changed() #Sets the flag that will cause an und twiss broadcast
                #self.send_und_twiss()
                await s.send_pyobj({'status': 'ok'})
            elif p['cmd'] == 'tao_batch':
                try:
                    results = self.tao_batch(p['val'])
                    await s.send_pyobj({'status': 'ok', 'result': results})
                except Exception as e:
                    L.error("Tao batch command failed: {}".format(e))
                    await s.send_pyobj({'status': 'fail', 'err': e})

def _orbit_array_from_text(text):
    return np.array([float(l.split()[5]) for l in text])*1000.0

def find_model(model_name):
    """
    Helper routine to find models using standard environmental variables:
    $LCLS_CLASSIC_LATTICE   should point to a checkout of https://github.com/slaclab/lcls-classic-lattice 
    $LCLS_LATTICE  should point to a checkout of https://github.com/slaclab/lcls-lattice
    
    Availble models:
        lcls_classic
        cu_hxr
        cu_spec
        cu_sxr
        sc_hxr
        sc_sxr
    
    """
    if model_name == 'lcls_classic':
        tao_initfile = os.path.join(os.environ['LCLS_CLASSIC_LATTICE'], 'bmad/model/tao.init')
    elif model_name in ['cu_hxr', 'cu_sxr', 'cu_spec', 'sc_sxr', 'sc_hxr']:
        root = os.environ['LCLS_LATTICE']
        tao_initfile = os.path.join(root, 'bmad/models/', model_name, 'tao.init')  
    else:
        raise ValueError('Not a valid model: {}'.format(model_name))
    assert os.path.exists(tao_initfile), 'Error: file does not exist: ' + tao_initfile
    return tao_initfile

if __name__=="__main__":
    parser = argparse.ArgumentParser(description="Simulacrum Model Service")
    parser.add_argument(
        'model_name',
        help='Name of a Tao model from either lcls-lattice or lcls-classic-lattice.  Must be one of: ' + 
             'lcls_classic, cu_hxr, cu_spec, cu_sxr, sc_sxr, or sc_hxr'
    )
    parser.add_argument(
        '--enable-jitter',
        action='store_true',
        help='Apply jitter on every model update tick (10 Hz).  This will significantly increase CPU usage.'
    )
    parser.add_argument(
        '--plot',
        action='store_true',
        help='Show tao plot'
    )
    model_service_args = parser.parse_args()
    tao_init_file = find_model(model_service_args.model_name)
    serv = ModelService(init_file=tao_init_file, name=model_service_args.model_name.upper(), enable_jitter=model_service_args.enable_jitter, 
                        plot=model_service_args.plot)
    serv.start()

