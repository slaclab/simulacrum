import os
#For simulacrum 
import zmq
from zmq.asyncio import Context
cmd_socket = zmq.Context().socket(zmq.REQ)
cmd_socket.connect("tcp://127.0.0.1:{}".format(os.environ.get('MODEL_PORT', 12312)))




def taoCmd(cmd, terse = False):
   cmd_socket.send_pyobj({"cmd": "tao", "val": cmd})
   v = cmd_socket.recv_pyobj()
   for l in v['result']:
       if not terse:
           print(l)
   return v
def taoEcho(echo):
    cmd_socket.send_pyobj({"cmd": "echo", "val": echo})
    v = cmd_socket.recv_pyobj()
    return v



    
