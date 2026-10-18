"""Small Windows Discord IPC transport with framed reads, deadlines and ACKs."""
import ctypes as C
from ctypes import wintypes as W
import json
import os
import struct
import time
import uuid

K = C.WinDLL("kernel32", use_last_error=True)
K.CreateFileW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, W.LPVOID, W.DWORD, W.DWORD, W.HANDLE]
K.CreateFileW.restype = W.HANDLE
K.ReadFile.argtypes = [W.HANDLE, W.LPVOID, W.DWORD, C.POINTER(W.DWORD), W.LPVOID]
K.WriteFile.argtypes = K.ReadFile.argtypes
K.PeekNamedPipe.argtypes = [W.HANDLE, W.LPVOID, W.DWORD, W.LPVOID, C.POINTER(W.DWORD), W.LPVOID]
K.CloseHandle.argtypes = [W.HANDLE]

class DiscordIPC:
    def __init__(self):
        self.handle = None
        self.client_id = None
        self.last_ack = 0

    def close(self):
        if self.handle is not None:
            K.CloseHandle(self.handle)
        self.handle = None

    def connect(self, client_id):
        self.close()
        for n in range(10):
            h = K.CreateFileW(r"\\?\pipe\discord-ipc-" + str(n), 0xC0000000, 0, None, 3, 0, None)
            if h != C.c_void_p(-1).value:
                self.handle = h
                try:
                    self.send(0, {"v": 1, "client_id": client_id})
                    _, data = self.frame(time.monotonic() + 4)
                    if data.get("evt") != "READY":
                        raise RuntimeError("Discord не подтвердил READY: " + str(data.get("data", {})))
                    self.client_id = client_id
                    return
                except Exception:
                    self.close()
                    raise
        raise ConnectionError("Ожидание запущенного Discord для Windows")

    def send(self, opcode, data):
        body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        packet = struct.pack("<II", opcode, len(body)) + body
        buf = C.create_string_buffer(packet)
        sent = W.DWORD()
        if not K.WriteFile(self.handle, buf, len(packet), C.byref(sent), None) or sent.value != len(packet):
            raise ConnectionError("Соединение Discord закрыто")

    def available(self):
        size = W.DWORD()
        if not K.PeekNamedPipe(self.handle, None, 0, None, C.byref(size), None):
            raise ConnectionError("Соединение Discord закрыто")
        return size.value

    def read(self, size, deadline):
        parts = bytearray()
        while len(parts) < size:
            if time.monotonic() >= deadline:
                raise TimeoutError("Discord не ответил за 4 секунды")
            available = self.available()
            if not available:
                time.sleep(.01)
                continue
            count = min(size - len(parts), available)
            buf, got = C.create_string_buffer(count), W.DWORD()
            if not K.ReadFile(self.handle, buf, count, C.byref(got), None) or not got.value:
                raise ConnectionError("Не удалось прочитать ответ Discord")
            parts.extend(buf.raw[:got.value])
        return bytes(parts)

    def frame(self, deadline):
        while True:
            opcode, size = struct.unpack("<II", self.read(8, deadline))
            if size > 1024 * 1024:
                raise ValueError("Слишком большой ответ Discord")
            data = json.loads(self.read(size, deadline).decode("utf-8"))
            if opcode == 3:
                self.send(4, data)
                continue
            if opcode == 2:
                raise ConnectionError("Discord завершил IPC")
            return opcode, data

    def update(self, activity):
        nonce = str(uuid.uuid4())
        self.send(1, {"cmd": "SET_ACTIVITY", "args": {"pid": os.getpid(), "activity": activity}, "nonce": nonce})
        deadline = time.monotonic() + 4
        while True:
            _, response = self.frame(deadline)
            if response.get("nonce") != nonce:
                continue
            if response.get("evt") == "ERROR":
                raise RuntimeError("Discord: " + str(response.get("data", {})))
            self.last_ack = time.time()
            return response.get("data")

    def pump(self):
        while self.handle and self.available():
            # frame handles incoming PING and returns other unsolicited frames.
            # Avoid waiting for a frame after a PING: drain directly here.
            deadline = time.monotonic() + 1
            opcode, size = struct.unpack("<II", self.read(8, deadline))
            if size > 1024 * 1024:
                raise ValueError("Слишком большой ответ Discord")
            data = json.loads(self.read(size, deadline))
            if opcode == 3:
                self.send(4, data)
            elif opcode == 2:
                raise ConnectionError("Discord завершил IPC")
