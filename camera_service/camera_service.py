import os
import sys
import asyncio
import numpy as np
from caproto.server import ioc_arg_parser, run, pvproperty, PVGroup
import simulacrum
import zmq
import time
from zmq.asyncio import Context
import pickle
from scipy.stats import gaussian_kde
#set up python logger
L = simulacrum.util.SimulacrumLog(os.path.splitext(os.path.basename(__file__))[0], level='INFO')

class ProfMonService(simulacrum.Service):
    default_image_dim = 1024
    util_pvs = ['EVR:IN20:PM01:CTRL.DG0E', 'EVR:IN20:PM02:CTRL.DG1E', 'EVR:IN20:PM02:CTRL.DG0E',
                'EVR:IN20:PM03:CTRL.DG0E', 'EVR:IN20:PM03:CTRL.DG1E', 'EVR:IN20:PM04:CTRL.DG1E',
                'EVR:IN20:PM04:CTRL.DG0E', 'EVR:IN20:PM05:CTRL.DG1E', 'EVR:IN20:PM05:CTRL.DG0E',
                'EVR:IN20:PM06:CTRL.DG1E', 'EVR:IN20:PM06:CTRL.DG0E', 'EVR:LI21:PM01:CTRL.DG1E', 
                'EVR:LI21:PM01:CTRL.DG0E', 'EVR:LI24:PM01:CTRL.DG1E', 'EVR:LI24:PM01:CTRL.DG0E', 
                'EVR:LTU1:PM01:CTRL.DG0E', 'EVR:UND1:PM03:CTRL.DG1E', 'EVR:UND1:PM03:CTRL.DG0E',
                'EVR:UND1:PM01:CTRL.DG0E', 'EVR:IN20:PM01:CTRL.DG1E', 'YAGS:IN20:841:FRAME_RATE', 
                'YAGS:IN20:351:FRAME_RATE', 'OTRS:IN20:541:FRAME_RATE', 'OTRS:IN20:621:FRAME_RATE',
                'YAGS:IN20:921:FRAME_RATE', 'OTRS:LI21:291:FRAME_RATE', 'OTRS:LI25:342:FRAME_RATE', 
                'CTHD:IN20:206:FRAME_RATE', 'OTRS:DMPH:695:Acquire'] #last one not strictly necessary but speeds up matlab init

    def __init__(self):
        L.info('Initializing PVs')
        super().__init__()

        #load Profmon properties from file
        path_to_screen_props = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'screenProps.dat')
        with open(path_to_screen_props, 'rb') as file_handle:
            screens = pickle.load(file_handle)

        #build dicts to translate element name/device name
        self.ele2dev = {}
        self.dev2ele = {}
        self.profiles = {}
        for screenProps in screens:
                self.ele2dev[screenProps['element_name']] = screenProps['device_name']
                self.dev2ele[screenProps['device_name']] = screenProps['element_name']
                self.profiles[screenProps['device_name']] = {'props': screenProps}

        def ProfMonPVClassMaker(screenProps):
            pvLen = len(screenProps['device_name'])
            image_name = screenProps['image_name'][pvLen:]

            if not screenProps['values'][6]*screenProps['values'][7]:
                screenProps['values'][[0, 1, 6, 7]] = self.default_image_dim
                #screenProps['values'][2] = self.default_image_dim
                #screenProps['values'][6] = self.default_image_dim
                #screenProps['values'][7] = self.default_image_dim

            image_size = int(screenProps['values'][6] * screenProps['values'][7])
            image= pvproperty(value=np.zeros(image_size).tolist(), name = image_name, read_only=True, mock_record='ai')
            
            #dummy pv for EVR acquisition 
            acquire = pvproperty(value = "Acquire", name = ':Acquisition', read_only=False, mock_record='ai');
            frame_rate = pvproperty(value = 0, name = ':FRAME_RATE', read_only=True, mock_record='ai');
            buf_idx =  pvproperty(value = 0, name = ':IMG_BUF_IDX', read_only=False, mock_record='ai');
            img_save = pvproperty(value = 0, name = ':SAVE_IMG', read_only=False, mock_record='ai');
            try:
                pvProps = { screenProps['props'][i].split(':')[3]: pvproperty(value = float(screenProps['values'][i]), name = ':' + screenProps['props'][i].split(':')[3], read_only=False, mock_record='ai') 
                            for i in range(0, len(screenProps['props'])) if screenProps['props'][i]
                        }
            except IndexError:
                msg = '{} has an invalid device name'.format(screen)
                L.info(msg)
                return None
            pvProps.update({'acquire': acquire, 'frame_rate': frame_rate, 'buf_idx': buf_idx, 'img_save': img_save, 'image': image})
            return type(screenProps['device_name'], (PVGroup,), pvProps)

        def UtilPVClassMaker(PVName):
            pv = pvproperty(value = 0, name = PVName, read_only=False, mock_record='ai');
            return type(PVName, (PVGroup,), {'pv': pv})

        screen_pvs = {}         
        util_pvs = {} 

        for screen in self.profiles:
            msg='PV: {} {}'.format(screen, self.dev2ele[screen])
            ProfClass = ProfMonPVClassMaker(self.profiles[screen]['props'])
            if(ProfClass):
                screen_pvs[screen] = ProfClass(prefix = screen)

        for pv in self.util_pvs:
            prefix = ':'.join(pv.split(':')[0:3])
            suffix = pv.split(':')[3]
            UtilPVClass = UtilPVClassMaker(':' + suffix)
            screen_pvs[pv] = UtilPVClass(prefix = prefix)

        self.add_pvs(screen_pvs)
        self.add_pvs(util_pvs)
        self.ctx = Context.instance()
        #cmd socket is a synchronous socket, we don't want the asyncio context.
        self.cmd_socket = zmq.Context().socket(zmq.REQ)
        self.cmd_socket.connect("tcp://127.0.0.1:{}".format(os.environ.get('MODEL_PORT', 12312)))
        
        L.info("Initialization complete.")

    def request_profiles(self):
        self.cmd_socket.send_pyobj({"cmd": "send_profiles_twiss"})
        return self.cmd_socket.recv_pyobj()
       
    ################### 04.26 Jane added tag metadata filtering. Small possibility that last two blocks of this function may crash if data with another tag comes in and result/orbit are never assigned. Did not get a chance to test yet. 
    async def recv_profiles(self, flags=0, copy=False, track=False):
        model_broadcast_socket = self.ctx.socket(zmq.SUB)
        model_broadcast_socket.connect('tcp://127.0.0.1:{}'.format(os.environ.get('MODEL_BROADCAST_PORT', 66666)))
        model_broadcast_socket.setsockopt(zmq.SUBSCRIBE, b'')
        while True:
            L.debug("Checking for new profile data.")
            md = await model_broadcast_socket.recv_pyobj(flags=flags)
            particles = False
            if md.get("tag", None) == "part_positions":
                particles = True;
                L.info("Got new particle positions")
                screens = await model_broadcast_socket.recv_pyobj(flags=flags)
                for screen in screens:
                    devName = self.ele2dev[screen]
                    if devName not in self.profiles:
                        continue
                    beamProps = { 'particlePos': screens[screen]}
                    image = self.gen_beam_image(beamProps, self.profiles[devName]['props']['values'], img_type="positions")
                    self.profiles[devName]['image'] = image.tolist()
            elif md.get("tag", None) == "prof_data" and particles == False:
                msg ="Profile data incoming: {}".format(md)
                L.info(msg)
                msg = await model_broadcast_socket.recv(flags=flags, copy=copy, track=track)
                buf = memoryview(msg)
                A = np.frombuffer(buf, dtype=md['dtype'])
                result = np.rot90(A.reshape(md['shape']))
                for i in range(result.shape[0]):
                    orbit_x, orbit_y, beta_a, beta_b, e, name  = result[i]
                    L.debug(beta_a)
                    L.debug(beta_b)
                    L.debug(name)
                    devName = self.ele2dev[name]
                    if devName not in self.profiles:
                        continue
                    #CGI
                    beamProps = {'beta_a': float(beta_a), 'beta_b': float(beta_b), 'x': float(orbit_x), 'y': float(orbit_y), 'e': float(e)}
                    image = self.gen_beam_image(beamProps, self.profiles[devName]['props']['values'], img_type = "not_smooth")
                    self.profiles[devName]['image'] = image.tolist()
            else: 
                md = await model_broadcast_socket.recv(flags=flags, copy=copy, track=track)
                
           # L.info("Checking for new profile orbits.")
           # md = await model_broadcast_socket.recv_pyobj(flags=flags)            
           # if md.get("tag", None) == "prof_orbit":
           #     msg="Profile orbit incoming: {}".format( md)
           #     L.info(msg)
           #     msg = await model_broadcast_socket.recv(flags=flags, copy=copy, track=track)
           #     buf = memoryview(msg)
           #     A = np.frombuffer(buf, dtype=md['dtype'])
           #     orbit = A.reshape(md['shape'])
           # else:
           #     await model_broadcast_socket.recv(flags=flags, copy=copy, track=track)
            
            
               #devName = self.ele2dev[name]
                #if devName not in self.profiles:
                #    continue
                #CGI
                #beamProps = {'beta_a': float(beta_a), 'beta_b': float(beta_b), 'x': orbit[0][i], 'y': orbit[1][i]}
                #image = self.gen_beam_image(beamProps, self.profiles[devName]['props']['values'], smooth=False)
                #self.profiles[devName]['image'] = image.tolist()
            
            await self.publish_profiles()

    async def publish_profiles(self):
        for key, profile in self.profiles.items():
            pvName = profile['props']['image_name']
            if pvName in self:
                try:
                    await self[pvName].write(profile['image'])
                except:
                    continue

    # Generate 2D gaussian from orbit & betas.
    def gen_beam_image(self, beamProps, camProps, img_type = "smooth"):

        # image parameters
        imageX = camProps[0]
        imageY = camProps[1]
        bit_depth = camProps[2]
        cal = (camProps[3]*1e-6 if camProps[3] else 1e-5)   # resolution ie  calibration in m/pixel  
        roiX = camProps[6]
        roiY = camProps[7]
        centerX = camProps[10]
        centerY = camProps[11]
        if(roiX*roiY == 0): 
            roiX = imageX
            roiY = imageY
        if(centerX== 0 or centerY == 0):
            centerX = roiX/2
            centerY = roiY/2

        #Estimate camera intensity, see profmon_simulCreate.m. basically # of e- * quantum efficiency / attenuation factor
        q = .2e-9
        e0 = 1.6e-19
        qe = 2e-3
        atten = 4
        intensity = (q/e0)*qe/atten
        
        #print("Cal: %f, dimX: %d, dimY: %d, centerX: %d, centerX: %d" % (cal, dimX, dimY, centerX, centerY))
        # beam parameters
        if(img_type == "positions"):
            pos = np.rot90(beamProps['particlePos'])
            px = pos[0]/cal
            py = pos[1]/cal
            n_part = len(py)
            if(n_part < 1e4):
                px = px + centerX
                py = py + centerY
                img = intensity*self.KDEimage(px, py, int(roiX), int(roiY))
            else:
                x = np.arange(1, roiX+1) - centerX
                y = np.arange(1, roiY+1) - centerY 
                x = np.append(x - 0.5, x[-1]+0.5)
                y = np.append(y - 0.5, y[-1]+0.5)
                (h, _,_) = np.histogram2d(py, px, bins = (y, x))
                img = intensity/n_part*h
            #print(img)
        else:
            beta_a, beta_b, x, y, e = beamProps['beta_a'], beamProps['beta_b'], beamProps['x'], beamProps['y'], beamProps['e']
            emittance = 1e-6#0.4e-6 
            gamma = e/0.511e6
            beam_size_x = np.sqrt(beta_a*emittance/gamma)
            beam_size_y = np.sqrt(beta_b*emittance/gamma)
            #beam parameters in pixels
            sig_x = beam_size_x/cal
            sig_y = beam_size_y/cal
            xPos = 1e-3*x/cal
            yPos = 1e-3*y/cal
            #normalization of uncorrelated 2D gaussian.
            A = 1./np.pi/sig_x/sig_y
            n_part = int(1e6)
            #generate image. TODO: get particle orbit and offset in x and y
            x = np.arange(1, roiX+1) - centerX - xPos
            y = np.arange(1, roiY+1) - centerY - yPos
            if(img_type == "smooth"):
                x2 = -((x/sig_x)**2)/2
                y2 = -((y/sig_y)**2)/2
                xx2, yy2 = np.meshgrid(x2, y2)
                img = intensity*A*np.exp(xx2 + yy2)
            else:
                px = np.random.normal(0, sig_x, n_part)
                py = np.random.normal(0, sig_y, n_part)
                x = np.append(x - 0.5, x[-1]+0.5)
                y = np.append(y - 0.5, y[-1]+0.5)
                (h, _,_) = np.histogram2d(py, px, bins = (y, x))
                img = intensity/n_part*h
        img = img.astype(np.uint8) if bit_depth <= 8 else img.astype(np.uint16) 
        img_flat = np.minimum(img.ravel(), 2**bit_depth - 1) 
        return img_flat
    
    def KDEimage(self, x, y, roiY, roiX):
        xmin = int(x.min())
        xmax = int(x.max())
        ymin = int(y.min())
        ymax = int(y.max())
        X, Y = np.mgrid[xmin:xmax, ymin:ymax]
        positions = np.vstack([X.ravel(), Y.ravel()])
        values = np.vstack([x, y])
        kernel = gaussian_kde(values)
        Z = np.reshape(kernel(positions).T, X.shape)
        img = np.zeros((roiX, roiY));
        img[xmin:xmax, ymin:ymax] = Z
        return img
        
def main():
    service = ProfMonService()
    loop = asyncio.get_event_loop()
    _, run_options = ioc_arg_parser(
        default_prefix='',
        desc="Simulated Profile Monitor Service")
    loop.create_task(service.recv_profiles())
    loop.call_soon(service.request_profiles)
    run(service, **run_options)
    
if __name__ == '__main__':
    main()
