###############################################################################
#  
#  Carelink Client Proxy
#  
#  Description:
#
#    This program periodically downloads the available data from the 
#    Medtronic Carelink API. Then this data is provided via a simple
#    REST API to local clients:
#
#    Send a GET request to the following URI: 
#      http://<serveraddr>:8081/carelink/          # all Carelink data
#      http://<serveraddr>:8081/carelink/nohistory # no history data
#  
#  Author:
#
#    Ondrej Wisniewski (ondrej.wisniewski *at* gmail.com)
#  
#  Changelog:
#
#    08/06/2021 - Initial public release
#    27/07/2021 - Add logging, bug fixes
#    06/02/2022 - Download new data as soon as it is available
#    08/02/2022 - Fix HTTP API
#    24/05/2023 - Add patient parameter
#    12/10/2023 - Replace login parameters with initial token
#    27/10/2023 - Add Web GUI to insert auth token
#
#  Copyright 2021-2023, Ondrej Wisniewski 
#
###############################################################################

import carelink_client
import argparse
import time
import json
import sys
import signal
import threading 
import syslog
import logging as log
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http import HTTPStatus
from urllib.parse import parse_qs


VERSION = "0.8"

# Logging config
FORMAT = '[%(asctime)s:%(levelname)s] %(message)s'
log.basicConfig(format=FORMAT, datefmt='%Y-%m-%d %H:%M:%S', level=log.INFO)

# HTTP server settings
HOSTNAME = "0.0.0.0"
PORT     = 8081
GUIURL   = ""
APIURL   = "carelink"
OPT_NOHISTORY = "nohistory"

UPDATE_INTERVAL = 300
RETRY_INTERVAL  = 120

# Token handling
TOKENFILE = "/tmp/cookies.json"
g_token = ""
g_country = ""
wait_for_params = True

# Status messages
STATUS_INIT     = "Initialization"
STATUS_DO_LOGIN = "Performing login"
STATUS_LOGIN_OK = "Login successful"
STATUS_NEED_TKN = "Valid token required"
g_status = STATUS_INIT

recentData = None
verbose = False


#################################################
# The signal handler for the TERM signal
#################################################
def on_sigterm(signum, frame):
   # TODO: cleanup (if any)
   log.debug("exiting")
   syslog.syslog(syslog.LOG_NOTICE, "Exiting")
   sys.exit()


#################################################
# Get only essential data from json
#################################################
def get_essential_data(data):
   mydata = ""
   if data != None:      
      mydata = data.copy()
      try:
         del mydata["sgs"]
      except (KeyError,TypeError) as e:
         pass
      try:
         del mydata["markers"]
      except (KeyError,TypeError) as e:
         pass
      try:
         del mydata["limits"]
      except (KeyError,TypeError) as e:
         pass
      try:
         del mydata["notificationHistory"]
      except (KeyError,TypeError) as e:
         pass
   return mydata


#################################################
# Save user provided token
#################################################
def save_params(token,country):
   global g_token
   global g_country
   global wait_for_params
   g_token = token
   g_country = country
   wait_for_params = False
   log.info("Got new parameters")
   log.debug("Country: %s" % country)
   log.debug("Token:\n%s" % token)
   

def webgui(status,action=None,country=""):
   head =  '<!DOCTYPE html PUBLIC "-//W3C//DTD HTML 4.01//EN" "http://www.w3.org/TR/html4/strict.dtd"> \n \
            <html><head><title>Carelink Client Proxy</title> \n \
            <style></style> \n \
            </head> \n \
            <body><table style="text-align: left; width: 460px; background-color: #2196F3; font-family: Helvetica,Arial,sans-serif; font-weight: bold; color: white;" border="0" cellpadding="2" cellspacing="2"> \n \
            <tbody><tr><td> \n \
            <span style="vertical-align: top; font-size: 48px;">Carelink Client</span><br> \n \
            </td></tr></tbody></table><br> \n'
            
            
   body =  '<table style="text-align: left; width: 460px; background-color: white; font-family: Helvetica,Arial,sans-serif; font-size: 18px;" border="0" cellpadding="2" cellspacing="3"><tbody> \n \
            <tr style="font-size: 18px; font-weight: bold; background-color: lightgrey"> \n \
            <td style="width: 200px;">Status</td> \n \
            <td style="background-color: white;"></td><td style="background-color: white;"></td></tr> \n \
            <tr style="vertical-align: top; background-color: rgb(230, 230, 255);"> \n \
            <td style="width: 300px;">%s</td> \n \
            </tbody></table><br> \n' % (status)
            
   if action != None:
      body = body + '<form action="/%s" method="POST"> \n \
            <table style="text-align: left; width: 460px; background-color: white; font-family: Helvetica,Arial,sans-serif; font-size: 18px;" border="0" cellpadding="2" cellspacing="3"><tbody> \n \
            <tr style="font-size: 18px; font-weight: bold; background-color: lightgrey"> \n \
            <td style="width: 200px;">Parameters</td> \n \
            <td style="background-color: white;"></td><td style="background-color: white;"></td></tr> \n \
            <tr style="vertical-align: top; background-color: rgb(230, 230, 255);"> \n \
            <td style="width: 300px;">Token<br><span style="font-style: italic; font-size: 16px; color: grey;"><input type="text" size="30" id="ftoken" name="ftoken"></span></td> \n \
            <tr style="vertical-align: top; background-color: rgb(230, 230, 255);"> \n \
            <td style="width: 300px;">Country code<br><span style="font-style: italic; font-size: 16px; color: grey;"><input type="text" size="2" maxlength="2" value="%s" id="fcountry" name="fcountry"></span></td> \n \
            </tbody></table><br> \n \
            <input type="submit" value="Save"> \n \
            </form> \n' % (action,country)
#   else:
#      body = body + '<button onClick="window.location.reload();">Reload</button>'
            
   tail =  '<span style="font-size: 16px; color: red; font-family: Helvetica,Arial,sans-serif;"></span><br> \n \
            <table style="text-align: left; width: 460px; background-color: #2196F3;" border="0" cellpadding="2" cellspacing="2"><tbody> \n \
            <tr><td style="vertical-align: top; text-align: center;"> \n \
            <span style="font-family: Helvetica,Arial,sans-serif; color: white;"><a style="text-decoration:none; color: white;" href=https://github.com/ondrej1024/carelink-python-client>carelink_client_proxy</a> | version %s | 2023</span></td></tr> \n \
            </tbody></table></body></html>' % VERSION
   
   html = head + body + tail
   return html


#################################################
# HTTP server methods
#################################################
class MyServer(BaseHTTPRequestHandler):
   
   def log_message(self, format, *args):
      #Disable logging
      pass

   def do_GET(self):
      # Security checks (if any)
      # TODO
      log.debug("received client GET request from %s" % (self.address_string()))
      #print(self.path)
      
      # Check request path
      if self.path.strip("/") == APIURL:
         # Get latest Carelink data (complete)
         response = json.dumps(recentData)
         status_code = HTTPStatus.OK
         content_type = "application/json"
         #print("All data requested")
      elif self.path.strip("/") == APIURL+'/'+OPT_NOHISTORY:
         # Get latest Carelink data without history
         response = json.dumps(get_essential_data(recentData))
         status_code = HTTPStatus.OK
         content_type = "application/json"
         #print("Only essential data requested")
      elif self.path == "/":
         # Show web GUI
         if g_status == STATUS_NEED_TKN:
            response = webgui(status=g_status, action=GUIURL, country=g_country)
         else:
            response = webgui(status=g_status)
         status_code = HTTPStatus.OK
         content_type = "text/html"
         #print("Setup web page requested")
      else:
         response = ""
         status_code = HTTPStatus.NOT_FOUND
         content_type = "text/html"
         #print("page not found")
      
      # Send response
      self.send_response(status_code)
      self.send_header("Content-type", content_type)
      self.send_header("Access-Control-Allow-Origin", "*")
      self.end_headers()
      try:
         self.wfile.write(bytes(response, "utf-8"))
      except BrokenPipeError:
         pass

   def do_POST(self):
      # Get request body
      content_length = int(self.headers['Content-Length'])
      body = self.rfile.read(content_length)
      log.debug("received client POST request from %s" % (self.address_string()))
      #print(body)

      # Check request path
      if self.path.strip("/") == GUIURL:
         # Save setup data
         try:
            qs = body.decode()
            token = parse_qs(qs)['ftoken'][0]
            country = parse_qs(qs)['fcountry'][0]
            if token == "" or token == None:
               raise
            save_params(token,country)
            time.sleep(2)
            response = webgui(status=g_status)
         except:
            response = webgui(status=g_status, action=GUIURL, country=g_country)
         status_code = HTTPStatus.OK
         content_type = "text/html"
         #print("Config data received")
      else:
         response = ""
         status_code = HTTPStatus.NOT_FOUND
   
      # Send response
      self.send_response(status_code)
      self.send_header("Content-type", content_type)
      self.send_header("Access-Control-Allow-Origin", "*")
      self.end_headers()
      try:
         self.wfile.write(bytes(response, "utf-8"))
      except BrokenPipeError:
         pass
      

#################################################
# Web server thread
#################################################
def webserver_thread():
   # Init web server
   webserver = ThreadingHTTPServer((HOSTNAME, PORT), MyServer)
   log.debug("HTTP server started at http://%s:%s" % (HOSTNAME, PORT))
   #syslog.syslog(syslog.LOG_NOTICE, "HTTP server started at http://"+HOSTNAME+":"+str(PORT))

   # Start server loop
   webserver.serve_forever()


#################################################
# Start web server as asynchronous thread
#################################################
def start_webserver():
   t = threading.Thread(target=webserver_thread, args=())
   t.daemon = True
   t.start()


#################################################
# Get auth token from cookie file
#################################################
def getToken(filename):
   token = None
   country = None
   try:
      f = open(filename, "r")
      cookies = json.load(f)
      f.close()
   except Exception as e:
      #print("Error opening " + filename + ": " + str(e))
      log.info("Error opening " + filename + ": " + str(e))
      return (None,None)

   try:
      for c in cookies:
         if c["Name raw"] == "auth_tmp_token":
            token = c["Content raw"]
         elif c["Name raw"] == "application_country":
            country = c["Content raw"]
   except IndexError:
      #print("Error reading data from " + filename)
      log.info("Error reading data from " + filename)
      return (None,None)
  
   return (token,country)


# Parse command line 
parser = argparse.ArgumentParser()
parser.add_argument('--tokenfile','-t', type=str, help='File containing token cookies (default: %s)' % TOKENFILE, required=False)
parser.add_argument('--country',  '-c', type=str, help='CareLink two letter country code', required=False)
parser.add_argument('--patient',  '-a', type=str, help='CareLink patient', required=False)
parser.add_argument('--wait',     '-w', type=int, help='Wait seconds between repeated calls (default 300)', required=False)
parser.add_argument('--verbose',  '-v', help='Verbose mode', action='store_true')
args = parser.parse_args()

# Get parameters from CLI
tokenfile = TOKENFILE if args.tokenfile == None else args.tokenfile
country_c = args.country
patient   = args.patient
wait      = UPDATE_INTERVAL if args.wait == None else args.wait
verbose   = args.verbose

# Get token and country from file
(token,country_t) = getToken(tokenfile)
if country_t:
   country = country_t
elif country_c:
   country = country_c
else:
   country = None

# Logging config (verbose)
if verbose:
   FORMAT = '[%(asctime)s:%(levelname)s] %(message)s'
   log.basicConfig(format=FORMAT, datefmt='%Y-%m-%d %H:%M:%S', level=log.DEBUG)
else:
   log.disable(level=log.DEBUG)

# Init syslog
syslog.openlog("carelink_client_proxy", syslog.LOG_PID|syslog.LOG_CONS, syslog.LOG_USER)
syslog.syslog(syslog.LOG_NOTICE, "Starting Carelink Client Proxy (version "+VERSION+")")

# Init signal handler
signal.signal(signal.SIGTERM, on_sigterm)
signal.signal(signal.SIGINT, on_sigterm)

# Start web server
start_webserver()

# Main process loop
while True:
   # Init Carelink client
   client = carelink_client.CareLinkClient(token, country, patient)
   g_status = STATUS_DO_LOGIN
   
   # Login to Carelink server
   if client.login():
      g_status = STATUS_LOGIN_OK

      # Infinite loop requesting Carelink data periodically
      i = 0
      while True:
         i += 1
         log.debug("Starting download " + str(i))
         try:
            for j in range(2):
               recentData = client.getRecentData()
               # Get success
               if client.getLastResponseCode() == HTTPStatus.OK:
                  # Data OK
                  if client.getLastDataSuccess():
                     log.debug("New data received")
                  # Data error
                  else:
                     #print("Data exception: " + "no details available" if client.getLastErrorMessage() == None else client.getLastErrorMessage())
                     log.info("Data exception: " + "no details available" if client.getLastErrorMessage() == None else client.getLastErrorMessage())
                  break
               else:
                  if j==1:
                     raise Exception("Too many errors")
                  #print("Error, response code: " + str(client.getLastResponseCode()) + " Trying again in 1 min")
                  log.info("Error, response code: " + str(client.getLastResponseCode()) + " Trying again in 1 min")
                  time.sleep(60)            
         except Exception as e:
            #print(e)
            log.info(e)
            syslog.syslog(syslog.LOG_ERR, "ERROR: %s" % (str(e)))
            recentData = None
            break
      
         # Calculate time until next reading
         if recentData != None:
            nextReading = int(recentData["lastConduitUpdateServerTime"]/1000) + wait
            tmoSeconds  = int(nextReading - time.time())
            #print("Next reading at {0}, {1} seconds from now\n".format(nextReading,tmoSeconds))
            if tmoSeconds < 0:
               tmoSeconds = RETRY_INTERVAL
         else:
            tmoSeconds = RETRY_INTERVAL
            #print("Retry reading {0} seconds from now\n".format(tmoSeconds))

         log.debug("Waiting " + str(tmoSeconds) + " seconds before next download!")
         time.sleep(tmoSeconds+10)

   #print("Client login error! Response code: " + str(client.getLastResponseCode()) + " Error message: " + str(client.getLastErrorMessage()))
   #syslog.syslog(syslog.LOG_ERR,"Client login error! Response code: " + str(client.getLastResponseCode()) + " Error message: " + str(client.getLastErrorMessage()))

   # Wait for new token
   #print("Valid token required")
   log.info(STATUS_NEED_TKN)
   g_status = STATUS_NEED_TKN
   wait_for_params = True
   while wait_for_params:
      time.sleep(0.1)
   token = g_token
   country = g_country

# Exit         
syslog.syslog(syslog.LOG_INFO, "Exit")
