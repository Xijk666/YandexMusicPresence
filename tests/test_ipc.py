"""Real local named-pipe tests on isolated test pipes, never the user's Discord."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import ctypes as C
from ctypes import wintypes as W
import json
import struct
import threading
import time
import unittest
import uuid
from discord_ipc import DiscordIPC, K

K.CreateNamedPipeW.argtypes = [W.LPCWSTR,W.DWORD,W.DWORD,W.DWORD,W.DWORD,W.DWORD,W.DWORD,W.LPVOID]
K.CreateNamedPipeW.restype = W.HANDLE
K.ConnectNamedPipe.argtypes = [W.HANDLE,W.LPVOID]
K.DisconnectNamedPipe.argtypes = [W.HANDLE]

def read_exact(handle, size):
    result = bytearray()
    while len(result) < size:
        n = size-len(result)
        buf, count = C.create_string_buffer(n), W.DWORD()
        if not K.ReadFile(handle,buf,n,C.byref(count),None) or not count.value:
            raise RuntimeError('test server disconnected')
        result.extend(buf.raw[:count.value])
    return bytes(result)

def write(handle, opcode, payload, fragmented=False):
    body = json.dumps(payload).encode()
    packet = struct.pack('<II',opcode,len(body))+body
    chunks = [packet[i:i+3] for i in range(0,len(packet),3)] if fragmented else [packet]
    for chunk in chunks:
        buf, n = C.create_string_buffer(chunk), W.DWORD()
        if not K.WriteFile(handle,buf,len(chunk),C.byref(n),None):
            raise RuntimeError('test server write failed')
        if fragmented:
            time.sleep(.001)

class PipeTests(unittest.TestCase):
    def run_server(self, behavior):
        path = r'\\?\pipe\ym-presence-test-' + uuid.uuid4().hex
        server = K.CreateNamedPipeW(path,3,0,1,65536,65536,0,None)
        self.assertNotEqual(server,C.c_void_p(-1).value)
        errors = []
        def worker():
            try:
                if not K.ConnectNamedPipe(server,None) and C.get_last_error()!=535:
                    raise RuntimeError('ConnectNamedPipe failed')
                opcode,size = struct.unpack('<II',read_exact(server,8))
                request = json.loads(read_exact(server,size))
                behavior(server,request)
            except Exception as e:
                errors.append(e)
            finally:
                K.DisconnectNamedPipe(server)
                K.CloseHandle(server)
        thread=threading.Thread(target=worker,daemon=True)
        thread.start()
        client=DiscordIPC()
        client.handle=K.CreateFileW(path,0xC0000000,0,None,3,0,None)
        self.assertNotEqual(client.handle,C.c_void_p(-1).value)
        return client,thread,errors

    def test_fragmented_frame_and_ping(self):
        def behavior(h,r):
            write(h,3,{'test':'ping'},True)
            op,size=struct.unpack('<II',read_exact(h,8))
            self.assertEqual(op,4)
            self.assertEqual(json.loads(read_exact(h,size)),{'test':'ping'})
            write(h,1,{'nonce':r['nonce'],'evt':None,'data':{'accepted':True}},True)
            time.sleep(.1)
        c,t,errors=self.run_server(behavior)
        try:
            self.assertEqual(c.update({'type':2,'details':'Тест'}),{'accepted':True})
            self.assertGreater(c.last_ack,0)
        finally:
            c.close();t.join(2)
        self.assertFalse(t.is_alive())
        self.assertEqual(errors,[])

    def test_error_is_not_success(self):
        def behavior(h,r):
            write(h,1,{'nonce':r['nonce'],'evt':'ERROR','data':{'code':4000,'message':'rejected'}})
            time.sleep(.1)
        c,t,errors=self.run_server(behavior)
        try:
            with self.assertRaisesRegex(RuntimeError,'rejected'):
                c.update(None)
            self.assertEqual(c.last_ack,0)
        finally:
            c.close();t.join(2)
        self.assertEqual(errors,[])

    def test_remote_disconnect(self):
        c,t,errors=self.run_server(lambda h,r: None)
        try:
            with self.assertRaises(ConnectionError):
                c.update(None)
        finally:
            c.close();t.join(2)
        self.assertEqual(errors,[])

if __name__=='__main__':
    unittest.main()
