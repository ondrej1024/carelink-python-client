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
#      http://<serveraddr>:8080/carelink/alldata   # all Carelink data
#      http://<serveraddr>:8080/carelink/nohistory # no history data
#  
#  Author:
#
#    Ondrej Wisniewski (ondrej.wisniewski *at* gmail.com)
#  
#  Changelog:
#
#    08/06/2021 - Initial public release
#
#  Copyright 2021, Ondrej Wisniewski 
#
###############################################################################

import carelink_client
import argparse
import time
import json
import sys
import signal
import threading 
from http.server import BaseHTTPRequestHandler, HTTPServer
from http import HTTPStatus


VERSION = "0.1"

# HTTP server settings
HOSTNAME = "0.0.0.0"
PORT     = 8080
BASEURI  = "carelink/"

recentData = None
verbose = False


#################################################
# Print verbose
#################################################
def printvbs(msg):
   if verbose:
      print(msg)


#################################################
# The signal handler for the TERM signal
#################################################
def on_sigterm(signum, frame):
   # TODO: cleanup (if any)
   printvbs("exiting")
   sys.exit()


def get_essential_data(data):
   mydata = data
   if "sgs" in mydata:
      del mydata["sgs"]
   if "markers" in mydata:
      del mydata["markers"]
   if "limits" in mydata:
      del mydata["limits"]
   if "notificationHistory" in mydata:
      del mydata["notificationHistory"]
   
   return mydata


#################################################
# HTTP server methods
#################################################
class MyServer(BaseHTTPRequestHandler):
   
   def log_message(self, format, *args):
      # Disable logging
      pass

   def do_GET(self):
      # Security checks (if any)
      # TODO
      printvbs("received client request from %s" % (self.address_string()))
      
      # Check request path
      if self.path.strip("/") == BASEURI+"alldata":
         # Get latest Carelink data (complete)
         response = json.dumps(recentData)
         status_code = HTTPStatus.OK
      elif self.path.strip("/") == BASEURI+"nohistory":
         # Get latest Carelink data without history
         response = json.dumps(get_essential_data(recentData))
         status_code = HTTPStatus.OK
      else:
         response = ""
         status_code = HTTPStatus.NOT_FOUND
      
      # Send response
      self.send_response(status_code)
      self.send_header("Content-type", "application/json")
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
   webserver = HTTPServer((HOSTNAME, PORT), MyServer)
   printvbs("HTTP server started at http://%s:%s" % (HOSTNAME, PORT))
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


# Parse command line 
parser = argparse.ArgumentParser()
parser.add_argument('--username', '-u', type=str, help='CareLink username', required=True)
parser.add_argument('--password', '-p', type=str, help='CareLink password', required=True)
parser.add_argument('--country',  '-c', type=str, help='CareLink two letter country code', required=True)
parser.add_argument('--wait',     '-w', type=int, help='Wait minutes between repeated calls (default 5min)', required=False)
parser.add_argument('--verbose',  '-v', help='Verbose mode', action='store_true')
args = parser.parse_args()

# Get parameters
username = args.username
password = args.password
country  = args.country
wait     = 5 if args.wait == None else args.wait
verbose  = args.verbose

# Init signal handler
signal.signal(signal.SIGTERM, on_sigterm)
signal.signal(signal.SIGINT, on_sigterm)

# Start web server
start_webserver()

# Create Carelink client
client = carelink_client.CareLinkClient(username, password, country)
printvbs("Client created!")

# First login to Carelink server
if client.login():
   # Infinite loop requesting Carelink data periodically
   i = 0
   while True:
      i += 1
      printvbs("Starting download " + str(i))
      try:
         for j in range(2):
            recentData = client.getRecentData()
            # Get success
            if client.getLastResponseCode() == HTTPStatus.OK:
               # Data OK
               if client.getLastDataSuccess():
                  printvbs("New data received")
               # Data error
               else:
                  print("Data exception: " + "no details available" if client.getLastErrorMessage() == None else client.getLastErrorMessage())
               break
            # Auth error
            elif client.getLastResponseCode() == HTTPStatus.FORBIDDEN:
               print("GetRecentData login error (status code FORBIDDEN). Trying again in 1 sec")
               time.sleep(1)
            else:
               print("Error, response code: " + str(client.getLastResponseCode()) + " Trying again in 1 sec")
               time.sleep(1)
      except Exception as e:
         print(e)
            
      printvbs("Waiting " + str(wait) + " minutes before next download!")
      time.sleep(wait * 60)
else:
   print("Client login error! Response code: " + str(client.getLastResponseCode()) + " Error message: " + str(client.getLastErrorMessage()))
