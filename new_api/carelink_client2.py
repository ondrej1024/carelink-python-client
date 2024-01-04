###############################################################################
#  
#  Carelink Client 2 library
#  
#  Description:
#
#    This library implements a client for the Medtronic Carelink API
#    as used by the official Carelink Connect Android app.
#  
#  Author:
#
#    Ondrej Wisniewski (ondrej.wisniewski *at* gmail.com)
#  
#  Changelog:
#
#    28/12/2023 - Initial version
#
#  Copyright 2023, Ondrej Wisniewski 
#
###############################################################################

# Workflow
# --------
#
# [0.1] GET access_token, refresh_token, mag-identifier from login procedure
# carelink_carepartner_api_login.py
#
# [0.2] GET base_urls (region=US or region=EU) and sso_config urls
# GET https://clcloud.minimed.eu/connect/carepartner/v6/discover/android/3.1
#
# [1] GET role from "baseUrlCareLink"
# GET /api/carepartner/v2/users/me
#
# [2] GET patientId from "baseUrlCareLink"
# GET /api/carepartner/v2/links/patients
#
# [3] GET data (providing username, role, patientId) from "baseUrlCumulus"
# POST /connect/carepartner/v6/display/message
#
# [4] REFRESH access_token, refresh_token from 
# sso_config['server']['hostname']:sso_config['server']['port']/sso_config['server']['prefix']/sso_config["oauth"]["system_endpoints"]["token_endpoint_path"]
# POST /auth/oauth/v2/token

import json
import requests
import time
import base64
import os
import logging as log
from datetime import datetime, timedelta

 
# Version string
VERSION = "1.0"

# Constants
DEFAULT_FILENAME="logindata.json"
CARELINK_CONFIG_URL = "https://clcloud.minimed.com/connect/carepartner/v6/discover/android/3.1"
AUTH_ERROR_CODES = [401,403]
COMMON_HEADERS = {
                  "Accept": "application/json",
                  "Content-Type": "application/json",
                  "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 10; Nexus 5X Build/QQ3A.200805.001)",
                 }

# Logging config
FORMAT = '[%(asctime)s:%(levelname)s] %(message)s'
log.basicConfig(format=FORMAT, datefmt='%Y-%m-%d %H:%M:%S', level=log.INFO)


###########################################################
# Class CareLinkClient
###########################################################
class CareLinkClient(object):
   
   def __init__(self, tokenFile=DEFAULT_FILENAME):
      
      self.__version = VERSION
      
      # Authorization
      self.__tokenFile = tokenFile
      self.__tokenData = None
      self.__accessTokenPayload = None
      
      # API config
      self.__config = None
      
      # User info
      self.__username = None
      self.__user = None
      self.__patient = None 
      self.__country = None
      
      # API status
      self.__last_api_status = None
      
   ###########################################################
   # Class internal functions
   ###########################################################
   
   ###########################################################
   # Read token file
   ###########################################################
   def _read_token_file(self, filename):
      log.info("_read_token_file()")
      token_data = None
      if os.path.isfile(filename):
         try:
            token_data = json.loads(open(filename, "r").read())
         except json.JSONDecodeError:
            log.error("ERROR: failed parsing token file %s" % filename)

         if token_data is not None:
            required_fields = ["access_token", "refresh_token", "scope", "client_id", "client_secret", "mag-identifier"]
            for f in required_fields:
               if f not in token_data:
                  log.error("ERROR: field %s is missing from token file" % f)
      else:
         log.error("ERROR: token file %s not found" % filename)
      return token_data

   ###########################################################
   # Write token file
   ###########################################################
   def _write_token_file(self, obj, filename):
      log.info("_write_token_file()")
      with open(filename, 'w') as f:
         json.dump(obj, f, indent=4)

   ###########################################################
   # Get Carelink API config
   ###########################################################
   def _get_config(self, discovery_url, country):
      log.info("_get_config()")
      resp = requests.get(discovery_url)
      log.debug("   status: %d" % resp.status_code)
      data = resp.json()
      region = None
      config = None

      for c in data["supportedCountries"]:
         try:
            region = c[country.upper()]["region"]
            break
         except KeyError:
            pass
      if region is None:
         raise Exception("ERROR: country code %s is not supported" % country)
      log.debug("   region: %s" % region)
      
      for c in data["CP"]:
         if c["region"] == region:
            config = c
            break
      if config is None:
         raise Exception("ERROR: failed to get config base urls for region %s" % region)

      resp = requests.get(config["SSOConfiguration"])
      log.debug("   status: %d" % resp.status_code)
      sso_config = resp.json()
      sso_base_url = f"https://{sso_config['server']['hostname']}:{sso_config['server']['port']}/{sso_config['server']['prefix']}"
      token_url = sso_base_url + sso_config["oauth"]["system_endpoints"]["token_endpoint_path"]
      c["token_url"] = token_url
      return config
   
   ###########################################################
   # Get user data
   ###########################################################
   def _get_user(self, config, token_data):
      log.info("_get_user()")
      url = config["baseUrlCareLink"] + "/users/me"
      headers = COMMON_HEADERS
      headers["mag-identifier"] = token_data["mag-identifier"]
      headers["Authorization"] = "Bearer " + token_data["access_token"]
      self.__last_api_status = None
      resp = requests.get(url=url,headers=headers)
      self.__last_api_status = resp.status_code
      log.debug("   status: %d" % resp.status_code)
      try:
         user = resp.json()
      except IndexError:
         user = None
      return user

   ###########################################################
   # Get patient data
   ###########################################################
   def _get_patient(self, config, token_data):
      log.info("_get_patient()")
      url = config["baseUrlCareLink"] + "/links/patients"
      headers = COMMON_HEADERS
      headers["mag-identifier"] = token_data["mag-identifier"]
      headers["Authorization"] = "Bearer " + token_data["access_token"]
      self.__last_api_status = None
      resp = requests.get(url=url,headers=headers)
      self.__last_api_status = resp.status_code
      log.debug("   status: %d" % resp.status_code)
      try:
         patient = resp.json()[0]
      except IndexError:
         patient = None
      return patient

   ###########################################################
   # Get periodic pump and sensor data
   ###########################################################
   def _get_data(self, config, token_data, username, role, patientid):
      log.info("_get_data()")
      url = config["baseUrlCumulus"] + "/display/message"
      headers = COMMON_HEADERS
      headers["mag-identifier"] = token_data["mag-identifier"]
      headers["Authorization"] = "Bearer " + token_data["access_token"]
      data = {}
      data["username"] = username
      if role in ["CARE_PARTNER","CARE_PARTNER_OUS"]:
         data["role"] = "carepartner"
         data["patientId"] = patientid
      else:
         data["role"] = "patient"         
      #log.debug("url: %s" % url)
      #log.debug("headers: %s" % json.dumps(headers))
      #log.debug("data: %s" % json.dumps(data))
      
      self.__last_api_status = None
      resp = requests.post(url=url,headers=headers,data=json.dumps(data))
      self.__last_api_status = resp.status_code
      log.debug("   status: %d" % resp.status_code)
      return resp.json()

   ###########################################################
   # Do token data refresh
   ###########################################################
   def _do_refresh(self, config, token_data):
      log.info("_do_refresh()")
      token_url = config["token_url"]
      data = {
         "refresh_token": token_data["refresh_token"],
         "client_id":     token_data["client_id"],
         "client_secret": token_data["client_secret"],
         "grant_type":    "refresh_token"
         }
      headers = {
         "mag-identifier": token_data["mag-identifier"]
         }
      resp = requests.post(url=token_url, headers=headers, data=data)
      log.debug("   status: %d" % resp.status_code)
      if resp.status_code != 200:
         raise Exception("ERROR: failed to refresh token")
      new_data = resp.json()
      token_data["access_token"] = new_data["access_token"]
      token_data["refresh_token"] = new_data["refresh_token"]
      return token_data

   ###########################################################
   # Get access token payload 
   ###########################################################
   def _get_access_token_payload(self, token_data):
      log.info("_get_access_token_payload()")
      try:
         token = token_data["access_token"]
      except:
         log.debug("   no access token found")
         return None
      try:
         # Decode json web token payload
         payload_b64 = token.split('.')[1]
         payload_b64_bytes = payload_b64.encode()
         missing_padding = (4 - len(payload_b64_bytes) % 4) % 4
         if missing_padding:
            payload_b64_bytes += b'=' * missing_padding
         payload_bytes = base64.b64decode(payload_b64_bytes)
         payload = payload_bytes.decode()
         payload_json = json.loads(payload)
         #log.debug(payload_json)
      except:
         log.info("   malformed access token")
         return None
      return payload_json

   ###########################################################
   # Check access token validity
   ###########################################################
   def _is_token_valid(self, access_token_payload):
      log.info("_is_token_valid()")
      try:
         # Get expiration time stamp
         token_validto = access_token_payload["exp"]
      except:
         log.info("   missing data in access token")
         return False
      
      # Check expiration time stamp
      tdiff = token_validto - time.time()
      if tdiff < 0:
         log.info("   access token has expired %ds ago" % abs(tdiff))
         return False
      if tdiff < 600:
         log.info("   access token is about to expire in %ds" % abs(tdiff))
         return False
      
      # Token is valid
      auth_token_validto = datetime.utcfromtimestamp(token_validto).strftime('%a %b %d %H:%M:%S UTC %Y')
      log.info("   access token expires in %ds (%s)" % (tdiff,auth_token_validto))
      return True

   ###########################################################
   # Init static data
   ###########################################################
   def _init(self):
      self.__tokenData = self._read_token_file(self.__tokenFile)
      if self.__tokenData is None:
         return False
      self.__accessTokenPayload = self._get_access_token_payload(self.__tokenData)
      if self.__accessTokenPayload is None:
         return False
      try:
         self.__country = self.__accessTokenPayload["token_details"]["country"]
         self.__config = self._get_config(CARELINK_CONFIG_URL, self.__country)
         self.__username = self.__accessTokenPayload["token_details"]["preferred_username"]
         self.__user = self._get_user(self.__config, self.__tokenData)
         if self.__user["role"] in ["CARE_PARTNER","CARE_PARTNER_OUS"]:
            self.__patient = self._get_patient(self.__config, self.__tokenData)
      except Exception as e:
         log.error(e)
         if self.__last_api_status in [401,403]:
            try:
               self.__tokenData = self._do_refresh(self.__config, self.__tokenData)
               self.__accessTokenPayload = self._get_access_token_payload(self.__tokenData)
               self._write_token_file(self.__tokenData, self.__tokenFile)
            except Exception as e:
               log.error(e)
         return False
      return True


   ###########################################################
   # Class public functions
   ###########################################################

   ###########################################################
   # Init object
   ###########################################################
   def init(self):
      # First try
      if self._init() == False:
         # Second try (after token refresh)
         if self._init() == False:
            # Failed permanently
            log.error("ERROR: unable to initialize")
            return False
      return True
      
   ###########################################################
   # Print user info
   ###########################################################
   def printUserInfo(self):
      print("User Info:")
      print("   user:     %s (%s %s)" % (self.__username, self.__user["firstName"], self.__user["lastName"]))
      print("   role:     %s" % self.__user["role"])
      print("   country:  %s" % self.__country)
      if self.__patient is not None:
         print("   patient:  %s (%s %s)" % (self.__patient["username"],self.__patient["firstName"],self.__patient["lastName"]))
            
   ###########################################################
   # Get recent periodic pump data
   ###########################################################
   def getRecentData(self):
      # Check if access token is valid
      if not self._is_token_valid(self.__accessTokenPayload):
         self.__tokenData = self._do_refresh(self.__config, self.__tokenData)
         self.__accessTokenPayload = self._get_access_token_payload(self.__tokenData)
         self._write_token_file(self.__tokenData, self.__tokenFile)
         if not self._is_token_valid(self.__accessTokenPayload):
            log.error("ERROR: unable to get valid access token")
            return None
         
      if self.__patient is not None:
         patientId = self.__patient["username"]
      else:
         patientId = None
      
      # Get data: first try
      data = self._get_data(self.__config, 
                            self.__tokenData, 
                            self.__username,
                            self.__user["role"],
                            patientId)
      # Check API response
      if self.__last_api_status in AUTH_ERROR_CODES:
         # Try to refresh token
         self.__tokenData = self._do_refresh(self.__config, self.__tokenData)
         self.__accessTokenPayload = self._get_access_token_payload(self.__tokenData)
         self._write_token_file(self.__tokenData, self.__tokenFile)
         
         # Get data: second try 
         data = self._get_data(self.__config, 
                               self.__tokenData, 
                               self.__username,
                               self.__user["role"],
                               patientId)
         # Check API response
         if self.__last_api_status in AUTH_ERROR_CODES:
            # Failed permanently
            log.error("ERROR: unable to get data")
            return None
      return data

   ###########################################################
   # Get last API response code
   ###########################################################
   def getLastResponseCode(self):
      return self.__last_api_status
   
   ###########################################################
   # Get Client library version
   ###########################################################
   def getClientVersion(self):
      return self.__version
