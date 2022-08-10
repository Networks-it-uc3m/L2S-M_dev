import pymysql
import subprocess
import xml.etree.ElementTree as ET
import os
import time

#This code is used to find the pci interfaces in the host machine (basis for the init container) and write them
#in the operator database.
#The IP of the database is provided through an environment variable.

    
def get_pci_data():

    # Get all interfaces in the host though the command
    lshw_cmd = ['lshw', '-c', 'network', '-xml']
    proc = subprocess.Popen(lshw_cmd, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE)
    # Store the output and trun it into json format
    out = proc.communicate()[0]
    encoding = 'utf-8'
    root = ET.fromstring(out.decode(encoding))

    pci = {}

    for node in root:
        if 'handle' in node.attrib:
            try:
                pci[node.attrib['handle']] = node.find('serial').text
            except Exception:
                pass

    return pci

def main():

    pci = get_pci_data()
    print(pci)

    if pci:
        db = pymysql.connect(host=os.environ.get('L2SM_OPT_SERVICE_PORT_3306_TCP_ADDR'),user="l2sm",password="l2sm;",db="L2SM")
        cur = db.cursor()
        # For each entry, get the values that will be written in the database (array with multiple values)
        table1 = "CREATE TABLE IF NOT EXISTS pci (pci TEXT, mac TEXT, node TEXT);"
        cur.execute(table1)
        db.commit()
        values = []
        for x in pci:
            values.append([x, pci[x], os.environ.get('NODE_NAME')])
        sql = "INSERT INTO pci (pci, mac, node) VALUES (%s, %s, %s)"
        cur.executemany(sql, values)
        db.commit()
        db.close()
        
    return 0

if __name__ == "__main__":
    main()
    time.sleep(3000000000)
