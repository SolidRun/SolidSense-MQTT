#-------------------------------------------------------------------------------
# Name:        OBD_Clent
# Purpose:  Encpasulate rRPC interface to OBD Vehicle service
#
# Author:      Laurent Carré
#
# Created:     15/03/2020
# Copyright:   (c) Laurent Carré Sterwen Technologies 2020
# Licence:     <your licence>
#-------------------------------------------------------------------------------

import os
import sys
import inspect

cmd_subfolder = os.path.realpath(os.path.abspath(os.path.join(os.path.split(inspect.getfile( inspect.currentframe() ))[0], "../vehicle")))
sys.path.insert(0, cmd_subfolder)

import threading
import logging
import time
import grpc
import json


from OBD_Service_pb2 import *
import OBD_Service_pb2_grpc




class OBD_GRPC_Client() :

    def __init__(self,addr,logger) :

        self._logger=logger
        self._logger.debug("creating grpc channel on:"+addr)
        self._channel= grpc.insecure_channel(addr)
        self._stub= OBD_Service_pb2_grpc.OBD_ServiceStub(self._channel)
        self._streamer=None


    def status(self,option="min"):
        self._logger.info("Vehicle service send status request with option:"+option)
        req=OBD_StatusRequest()
        req.request=option
        try:
            resp=self._stub.Status(req)
        except grpc.RpcError as err:
            self._logger.error(str(err))
            return None
        out={}
        out['connected']=resp.connected
        out['engine_on']=resp.engine_on
        out['autoconnect']=resp.autoconnect
        out['MAC']=resp.MAC
        if resp.connected :
            out['protocol']=resp.protocol
            out['state']=resp.state
            if option != 'min' :
                out['commands']=resp.commands
        return out


    def connect(self,mac):
        self._logger.info("Vehicle service start request on MAC:"+mac)
        req=Start_OBD()
        req.MAC=mac
        try:
            resp=self._stub.Connect(req)
        except grpc.RpcError as err:
            self._logger.error(str(err))
            return None
        self._logger.debug("Connect response:"+resp.error)
        out={}
        out['connected']=resp.connected
        out['engine_on']=resp.engine_on
        out['error']=resp.error
        out['timestamp']=resp.obd_time
        return out


    def startStreaming(self,callback,commands=None,rules=None):
        if self._streamer != None :
            self._logger.info("OBD Streaming request on-going = New request rejected")
            return False
        rules_j=json.dumps(rules)
        self._streamer=ContinuousOBDReader(self,callback,self._logger,commands,rules_j)
        self._streamer.start()
        return True

    def stopStreaming(self):
        if self._streamer == None :
            return
        req=OBD_cmd()
        resp=self._stub.Stop(req)
        self._logger.debug("Stop vehicle streaming acknowledgement OBD connected:"+str(resp.connected))

    def killStreamer(self):
        if self._streamer == None :
            return
        self._logger.debug("Killing OBD streaming thread")
        if not self._streamer.is_alive() :
            self.debug("OBD streamer already stopped")
            self._streamer = None
            return





class ContinuousOBDReader(threading.Thread):
    '''
    this class is used to read a continuous stream of gps event
    and throwing a call for each of them
    '''
    def __init__(self,client,callback,logger,commands=None,rules=None):
        threading.Thread.__init__(self)
        self._client=client
        self._callback=callback
        self._logger=logger
        self._rules=rules
        self._commands=commands

    def run(self):
        req=OBD_cmd()
        if self._rules != None :
            req.rules=self._rules
        if self._commands != None :
            req.commands=self._commands
            req.request=1
        else:
            req.request=0
        try:
            for resp in self._client._stub.Read(req) :
                self._logger.debug("OBD message received with:"+resp.error)
                out={}
                out['connected']=resp.connected
                out['engine_on']=resp.engine_on
                out['error']=resp.error
                out['timestamp']=resp.obd_time
                if resp.engine_on:
                    obd_cmds={}
                    for c in resp.values:
                        cmd={}
                        cmd['type']=c.type
                        if c.type == 0 :
                            cmd['value'] = c.f
                            cmd['unit'] = c.unit
                        else:
                            cmd['value']=c.s
                        obd_cmds[c.cmd]= cmd
                    out['commands']=obd_cmds
                self._callback(out)
        except Exception as err:
            self._logger.error(str(err))
            pass

        self._logger.info("End Vehicle OBD streaming")
        self._client._streamer=None

def main():
    pass

if __name__ == '__main__':
    main()
