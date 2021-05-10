import carelink_client
import argparse
import datetime
import time
import json


def writeJson(jsonobj, name):
   filename = name + "-" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + ".json"
   try:
      f = open(filename, "w")
      f.write(json.dumps(jsonobj,indent=3))
      f.close()
   except Exception as e:
      print("Error saving " + filename + ": " + str(e))
      return False
   else:
      return True


# Parse command line 
parser = argparse.ArgumentParser()
parser.add_argument('--username', '-u', type=str, help='CareLink username', required=True)
parser.add_argument('--password', '-p', type=str, help='CareLink password', required=True)
parser.add_argument('--country',  '-c', type=str, help='CareLink two letter country code', required=True)
parser.add_argument('--repeat',   '-r', type=int, help='Repeat request times', required=False)
parser.add_argument('--wait',     '-w', type=int, help='Wait minutes between repeated calls', required=False)
parser.add_argument('--data',     '-d', help='Save recent data', action='store_true')
parser.add_argument('--verbose',  '-v', help='Verbose mode', action='store_true')
args = parser.parse_args()

# Get parameters
username = args.username
password = args.password
country  = args.country
repeat   = 1 if args.repeat == None else args.repeat
wait     = 5 if args.wait == None else args.wait
data     = args.data
verbose  = args.verbose

#print("username = " + username)
#print("password = " + password)
#print("country  = " + country)
#print("repeat   = " + str(repeat))
#print("wait     = " + str(wait))
#print("data     = " + str(data))
#print("verbose  = " + str(verbose))


client = carelink_client.CareLinkClient(username, password, country)
if verbose:
   print("Client created!")
   
if client.login():
   for i in range(repeat):
      if verbose:
         print("Starting download, count:  " + str(i+1))
      # Recent data is requested
      if(data):
         try:
            for j in range(2):
               recentData = client.getRecentData()
               # Auth error
               if client.getLastResponseCode() == 403:
                  print("GetRecentData login error (response code 403). Trying again in 1 sec!")
                  time.sleep(1)
               # Get success
               elif client.getLastResponseCode() == 200:
                  # Data OK
                  if client.getLastDataSuccess():
                     if writeJson(recentData, "data"):
                        if verbose:
                           print("data saved!")
                  # Data error
                  else:
                     print("Data exception: " + "no details available" if client.getLastErrorMessage() == None else client.getLastErrorMessage())
                  # STOP!!!
                  break
               else:
                  print("Error, response code: " + str(client.getLastResponseCode()) + " Trying again in 1 sec!")
                  time.sleep(1)
         except Exception as e:
            print(e)
            
         if i < repeat - 1:
            if verbose:
               print("Waiting " + str(wait) + " minutes before next download!")
            time.sleep(wait * 60)
else:
   print("Client login error! Response code: " + str(client.getLastResponseCode()) + " Error message: " + str(client.getLastErrorMessage()))
