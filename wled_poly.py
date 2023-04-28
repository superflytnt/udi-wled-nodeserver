#!/usr/bin/env python3

"""
This is a NodeServer for WLED written by automationgeek (Jean-Francois Tremblay) 
based on the NodeServer template for Polyglot v2 written in Python2/3 by Einstein.42 (James Milne) milne.james@gmail.com.
Using this Python Library to control WLED by https://github.com/pctechjon/wledpy
"""

import udi_interface
import time
import json
import sys
import os
import zipfile
from wled import Wled
from threading import Thread

LOGGER = udi_interface.LOGGER

with open('server.json') as data:
    SERVERDATA = json.load(data)
try:
    VERSION = SERVERDATA['credits'][0]['version']
except (KeyError, ValueError):
    LOGGER.info('Version not found in server.json.')
    VERSION = '0.0.0'

class Controller(udi_interface.Node):

    def __init__(self, polyglot, primary, address, name):
        super(Controller, self).__init__(polyglot, primary, address, name)
        self.poly = polyglot
        self.discovery_thread = None
        self.do_poll = False
        self.name = 'WLED'
        self.myHost = None
        self.hb = 0

        polyglot.subscribe(polyglot.START, self.start, address)
        polyglot.subscribe(polyglot.CUSTOMPARAMS, self.parameterHandler)
        polyglot.subscribe(polyglot.POLL, self.poll)

        polyglot.ready()
        polyglot.addNode(self)
        
    def parameterHandler(self, params):
        self.poly.Notices.clear()
        try:
            
            # Get and set IP
            if 'host' in params :
                self.myHost = params['host']
                LOGGER.info('Custom IP address specified: {}'.format(self.myHost))
            else:
                LOGGER.error('Need to have ip address in custom param host')
                self.setDriver('ST', 0)
                return False                
                        
            if self.myHost != "":
                self.setDriver('ST', 1)
                self.discover()
                                                            
        except Exception as ex:
            LOGGER.error('Error starting WLED NodeServer: %s', str(ex))
            self.setDriver('ST', 0)
            return False

    def start(self):
        LOGGER.info('Started WLED for v2 NodeServer version %s', str(VERSION))

    def poll(self, polltype):
        if 'shortPoll' in polltype:
            if self.discovery_thread is not None:
                if self.discovery_thread.is_alive():
                    LOGGER.debug('Skipping shortPoll() while discovery in progress...')
                    return
                else:
                    self.discovery_thread = None
        
            self.setDriver('ST', 1)
            for node in self.poly.nodes():
                if  node.do_poll:
                    node.update()
        else:
            self.heartbeat()

    def query(self):
        for node in self.poly.nodes():
            node.reportDrivers()
        
    def heartbeat(self):
        LOGGER.debug('heartbeat: hb={}'.format(self.hb))
        if self.hb == 0:
            self.reportCmd("DON",2)
            self.hb = 1
        else:
            self.reportCmd("DOF",2)
            self.hb = 0
        
    def install_profile(self):
        try:
            self.poly.installprofile()
            LOGGER.info('Please restart the Admin Console for change to take effect')
        except Exception as ex:
            LOGGER.error('Error installing profile: %s', str(ex))
        return True
   
    def runDiscover(self,command):
        self.discover()
    
    def discover(self, *args, **kwargs):  
        if self.discovery_thread is not None:
            if self.discovery_thread.is_alive():
                LOGGER.info('Discovery is still in progress')
                return
        self.discovery_thread = Thread(target=self._discovery_process)
        self.discovery_thread.start()

    def _discovery_process(self):
        lstIp = self.myHost.split(',')
        id = 1
        for ip in lstIp:
            if not self.poly.getNode('wled' + str(id)):
                self.poly.addNode(WledNode(self.poly, self.address, 'wled' + str(id) , 'wled' + str(id), ip))
            id = id + 1 

    def delete(self):
        LOGGER.info('Deleting WLED')
        
    id = 'controller'
    commands = {'DISCOVERY' : runDiscover}
    drivers = [{'driver': 'ST', 'value': 0, 'uom': 2}]
    
class WledNode(udi_interface.Node):

    def __init__(self, controller, primary, address, name, ip):
        super(WledNode, self).__init__(controller, primary, address, name)
        self.poly = controller
        self.do_poll = True
        self.wled_ip = ip
        self.arrEffects = None
        self.my_wled = None
        
        try:
            self.my_wled = Wled(ip)
            self.my_wled.update()
            
        except Exception as ex:
            LOGGER.error('Error unable to connect to WLED: %s', str(ex))
            
        self.__saveEffetsList()
        self.__BuildProfile()

        
    def setOn(self, command):
        self.my_wled.turn_on()
        self.setDriver('ST', 100)

    def setOff(self, command):
        self.my_wled.turn_off()
        self.setDriver('ST', 0)
        
    def setBrightness(self, command):
        intBri = int(command.get('value'))
        self.my_wled.set_brightness(intBri)                                            
        self.setDriver('GV3', intBri)

    def setEffect(self, command):
        intEffect = int(command.get('value'))-1
        self.my_wled.set_effect(intEffect)
        self.setDriver('GV4', intEffect+1)
    
    def setColor(self,command):
        
        color = []
        
        query = command.get('query')
        color_r = int(query.get('R.uom100'))
        color_g = int(query.get('G.uom100'))
        color_b = int(query.get('B.uom100'))    
        
        color.append(color_r)
        color.append(color_g)
        color.append(color_b)
        
        self.my_wled.set_color(color)
        self.setDriver('GV6', color_r)
        self.setDriver('GV7', color_g)
        self.setDriver('GV8', color_b)

    def setCustomAPI(self, command):
	    api_command = command.get('value')
	    # Make a request to the WLED device using the custom API command
	    # (you may need to modify the following line depending on how the WLED library accepts custom API commands)
	    response = self.my_wled.send_request(api_command)
	    if response:
	        LOGGER.info(f'Successfully sent custom API command: {api_command}')
	    else:
	        LOGGER.error(f'Failed to send custom API command: {api_command}')
        
    def setProfile(self, command):
        self.__saveEffetsList()
        self.__BuildProfile()
    
    def query(self):
        self.reportDrivers()
    
    def update(self):
        self.__updateValue()

    def __updateValue(self):
        try:
            if self.my_wled.is_on() :
                self.setDriver('ST', 100)
            else:
                self.setDriver('ST', 0)
                
            self.setDriver('GV3', self.my_wled.get_brightness())
            self.setDriver('GV4', self.my_wled.get_effect()+1)
            self.setDriver('GV6', int(self.my_wled.get_color()[0]))
            self.setDriver('GV7', int(self.my_wled.get_color()[1]))
            self.setDriver('GV8', int(self.my_wled.get_color()[2]))
            
        except Exception as ex:
            LOGGER.error('Error updating WLED value: %s', str(ex))
    
    def __saveEffetsList(self):
        try:
            self.arrEffects = self.my_wled.get_effects()
        except Exception as ex:
            LOGGER.error('Unable to get WLED Effet List: %s', str(ex))
            
        #Write effectLists to Json
        try:
            with open(".effectLists.json", "w+") as outfile:
                json.dump(self.arrEffects, outfile)
        except IOError:
            LOGGER.error('Unable to write effectLists.json')
              
    def __getEffetsList(self):
        try:
            with open(".effectLists.json", "r") as infile:
                self.arrEffects = json.load(infile)
        except IOError:
            self.__saveEffetsList()
    
    def __BuildProfile(self):
        try:
            # Build File NLS from Template
            with open("profile/nls/en_us.template") as f:
                with open("profile/nls/en_us.txt", "w+") as f1:
                    for line in f:
                        f1.write(line) 
                    f1.write("\n") 
                f1.close()
            f.close()

            # Add Effect to NLS Profile        
            with open("profile/nls/en_us.txt", "a") as myfile:
                intCounter = 1
                for x in self.arrEffects:  
                    myfile.write("EFFECT_SEL-" + str(intCounter) + " = " + x + "\n")
                    intCounter = intCounter + 1
            myfile.close()

            intArrSize = len(self.arrEffects)
            if intArrSize is None or intArrSize == 0 :
                intArrSize = 1

            with open("profile/editor/editors.template") as f:
                with open("profile/editor/editors.xml", "w+") as f1:
                    for line in f:
                        f1.write(line) 
                    f1.write("\n") 
                f1.close()
            f.close()

            with open("profile/editor/editors.xml", "a") as myfile:
                myfile.write("\t<editor id=\"MEFFECT\">"  + "\n")
                myfile.write("\t\t<range uom=\"25\" subset=\"1-"+ str(intArrSize) + "\" nls=\"EFFECT_SEL\" />"  + "\n")
                myfile.write("\t</editor>" + "\n")
                myfile.write("</editors>")
            myfile.close()
        
        except Exception as ex:
            LOGGER.error('Error generating profile: %s', str(ex))
        
        self.poly.updateProfile()

        
    drivers = [{'driver': 'ST', 'value': 0, 'uom': 78},
               {'driver': 'GV3', 'value': 0, 'uom': 56},
               {'driver': 'GV4', 'value': 1, 'uom': 25},
               {'driver': 'GV6', 'value': 0, 'uom': 100},
               {'driver': 'GV7', 'value': 0, 'uom': 100},
               {'driver': 'GV8', 'value': 0, 'uom': 100}]
    
    id = 'WLED'
    commands = {
                    'QUERY': query,            
                    'DON': setOn,
                    'DOF': setOff,
                    'SET_PROFILE' : setProfile,
                    'SET_BRI': setBrightness,
                    'SET_EFFECT': setEffect,
                    'SET_COLORID':setColor
                }
    
if __name__ == "__main__":
    try:
        polyglot = udi_interface.Interface([])
        polyglot.start()
        polyglot.updateProfile()
        polyglot.setCustomParamsDoc()
        Controller(polyglot, 'controller', 'controller', 'WledNodeServer')
        polyglot.runForever()
    except (KeyboardInterrupt, SystemExit):
        sys.exit(0)
