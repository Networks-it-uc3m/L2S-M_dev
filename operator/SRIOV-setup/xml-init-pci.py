import pymysql
import subprocess
import xml.etree.ElementTree as ET
import time
import os

#This code is used to find the pci interfaces in the host machine (basis for the init container) and write them
#in the operator database.
#The IP of the database is provided through an environment variable.

def get_pci_data():
    pci_array = []
    # Get all interfaces in the host though the command
    lshw_cmd = ['lshw', '-c', 'network', '-xml']
    proc = subprocess.Popen(lshw_cmd, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE)
    # Store the output and trun it into json format
    out = proc.communicate()[0]
    encoding = 'utf-8'
    root = ET.fromstring(out.decode(encoding))

    for node in root:
        if 'handle' in node.attrib:
            pci_array.append(node.attrib['handle'])
    
    # Check if the entry is a pci interface. If so, store its value.
    return pci_array

def main():

    pci = get_pci_data()
    values = []
    for i in range(0,len(pci)):
        values.append([pci[i], os.environ.get('NODE_NAME'), '-1', '', ''])

    if values:
        db = pymysql.connect(host=os.environ.get('L2SM_OPT_SERVICE_PORT_3306_TCP_ADDR'),user="l2sm",password="l2sm;",db="L2SM")
        cur = db.cursor()
        # For each entry, get the values that will be written in the database (array with multiple values)
        sql = "INSERT INTO interfaces (interface, node, network, pod, mac) VALUES (%s, %s, %s, %s, %s)"
        # Execute the entry per each one of the values created before
        cur.executemany(sql, values)
        db.commit()
        db.close()
        
    return 0

if __name__ == "__main__":
    main()
    time.sleep(3000000000)
