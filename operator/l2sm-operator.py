import itertools
import logging
import kopf
import json
import secrets
from kubernetes import client
import pymysql
import random
import time
import os
from typing import Annotated

import aiohttp

ip = "127.0.0.1"

#POPULATE DATABASE ENTRIES WHEN A NEW L2SM POD IS CREATED (A NEW NODE APPEARS)
@kopf.on.create('pods.v1', labels={'l2sm-component': 'l2-ps'})
def build_db(body, logger, annotations, **kwargs):
    db = pymysql.connect(host=ip,user="l2sm",password="l2sm;",db="L2SM")
    cur = db.cursor()
    #CREATE TABLES IF THEY DO NOT EXIST
    table1 = "CREATE TABLE IF NOT EXISTS networks (network TEXT NOT NULL, id TEXT NOT NULL, vlan TEXT NOT NULL);"
    table2 = "CREATE TABLE IF NOT EXISTS interfaces (interface TEXT NOT NULL, node TEXT NOT NULL, network TEXT, pod TEXT, mac TEXT);"
    table3 = "CREATE TABLE IF NOT EXISTS intents (mac_one TEXT, mac_two TEXT, id TEXT);"
    cur.execute(table1)
    cur.execute(table2)
    cur.execute(table3)
    db.commit()
    values = []
    #MODIFY THE END VALUE TO ADD MORE INTERFACES
    for i in range(1,11):
      values.append(['vpod'+str(i), body['spec']['nodeName'], '-1', '', ''])
    sql = "INSERT INTO interfaces (interface, node, network, pod, mac) VALUES (%s, %s, %s, %s, %s)"
    cur.executemany(sql, values)
    db.commit()
    db.close()
    logger.info(f"Node {body['spec']['nodeName']} has been registered in the operator")

#UPDATE DATABASE WHEN NETWORK IS CREATED, I.E: IS A MULTUS CRD WITH OUR DUMMY INTERFACE PRESENT IN ITS CONFIG
#@kopf.on.create('NetworkAttachmentDefinition', field="spec.config['device']", value='l2sm-vNet')
@kopf.on.create('NetworkAttachmentDefinition', when=lambda spec, **_: '"device": "l2sm-vNet"' in spec['config'])
def create_vn(spec, name, namespace, logger, **kwargs):
    db = pymysql.connect(host=ip,user="l2sm",password="l2sm;",db="L2SM")
    cur = db.cursor()
    id = secrets.token_hex(32)
    vlan = json.loads(spec['config'])

    # IF NO VLAN TAG IS PRESENT IN THE DESCRIPTOR, ADD A 0 (WHICH WILL BE USED AS THE VALUE FOR DEFAULT)
    if not "vlan" in vlan:
      sql = "INSERT INTO networks (network, id, vlan) VALUES ('%s', '%s', '0')" % (name.strip(), id.strip())
    else:
      sql = "INSERT INTO networks (network, id, vlan) VALUES ('%s', '%s', '%s')" % (name.strip(), id.strip(), vlan['vlan'])

    cur.execute(sql)
    db.commit()

    db.close()
    logger.info(f"Network has been created")

#ADD POD TO SRIOV BY CREATING A NEW ENTRY IN THE DB TABLE WITH THE MULTUS ANNOTATION NAME (USED TO FIND THE PCI LATER, SINCE IT IS ASSIGNED WHEN THE POD IS RUNNING, NOT BEFOREHAND)
# PATCH THE MULTUS ANNOTATION OF THE SRIOV WITH THE CORRESPONDING VLAN TAG THAT IS USED FOR THE VIRTUAL NETWORK
def addSriov(body, name, namespace, physical):
    node = body['spec']['nodeName']
    api = client.CustomObjectsApi()
    db = pymysql.connect(host=ip,user="l2sm",password="l2sm;",db="L2SM")
    cur = db.cursor()

    for inter, net in physical.items():
      sql = "INSERT INTO interfaces (interface, node, network, pod, mac) VALUES ('%s', '%s', '%s', '%s', '%s')" % (inter, node, net, name, '')
      cur.execute(sql)

      nsql = "SELECT vlan FROM networks WHERE network = '%s'" % (net)
      cur.execute(nsql)
      vlan = cur.fetchone()

      ret = api.get_namespaced_custom_object('k8s.cni.cncf.io', 'v1', namespace, 'network-attachment-definitions', inter)
      conf = json.loads(ret['spec']['config'])
      conf.update({"vlan": int(vlan[0])})
      ret['spec']['config'] = json.dumps(conf)
      api.patch_namespaced_custom_object('k8s.cni.cncf.io', 'v1', namespace, 'network-attachment-definitions', inter, ret)


    db.commit()
    db.close()
    return

#ADD POD TO VETH
def addVeth(body, name, namespace, network, physical, multusInt):
    #CHECK IF NODE HAS FREE VIRTUAL INTERFACES LEFT
    if physical:
      addSriov(body, name, namespace, physical)
    v1 = client.CoreV1Api()
    ret = v1.read_namespaced_pod(name, namespace)
    node = body['spec']['nodeName']

    db = pymysql.connect(host=ip,user="l2sm",password="l2sm;",db="L2SM")
    nsql = "SELECT * FROM interfaces WHERE node = '%s' AND network = '-1'" % (node.strip())
    cur = db.cursor()
    cur.execute(nsql)
    data = cur.fetchall()
    if not data or len(data)<len(network):
      db.close()
      raise kopf.PermanentError("l2sm could not deploy the pod: Node " + node.strip() + "has no free interfaces left")

    #IF THERE IS ALREADY A MULTUS ANNOTATION, APPEND IT TO THE END.
    interface_to_attach = []
    network_array = []
    j = 0
    for interface in data[0:len(network)]:
      network_array.append(multusInt[network[j]])
      multusInt[network[j]] = interface[0].strip()
      interface_to_attach.append(interface[0].strip())
      j = j + 1

    ret.metadata.annotations['k8s.v1.cni.cncf.io/networks'] = ', '.join(multusInt)

    #PATCH NETWORK WITH ANNOTATION
    v1.patch_namespaced_pod(name, namespace, ret)

    for m in range(len(network)):
      sql = "UPDATE interfaces SET network = '%s', pod = '%s' WHERE interface = '%s' AND node = '%s'" % (network_array[m], name, interface_to_attach[m], node)
      cur.execute(sql)

    db.commit()
    db.close()

    return network_array

#ASSIGN POD TO NETWORK (TRIGGERS ONLY IF ANNOTATION IS PRESENT)
@kopf.on.create('pods.v1', annotations={'k8s.v1.cni.cncf.io/networks': kopf.PRESENT})
def pod_vn(body, name, namespace, logger, annotations, **kwargs):
    #GET MULTUS INTERFACES IN THE DESCRIPTOR
    #IN QUARANTINE: SLOWER THAN MULTUS!!!!!
    time.sleep(random.uniform(0,2)) #Make sure the database is not consulted at the same time to avoid overlaping

    multusInt = annotations.get('k8s.v1.cni.cncf.io/networks').split(",")
    #VERIFY IF NETWORK IS PRESENT IN THE CLUSTER
    api = client.CustomObjectsApi()
    items = api.list_namespaced_custom_object('k8s.cni.cncf.io', 'v1', namespace, 'network-attachment-definitions').get('items')
    resources = []
    # NETWORK POSITION IN ANNOTATION
    network = []
    # SRIOV present in the annotation
    physical = {}

    #FIND OUR NETWORKS IN MULTUS
    for i in items:
      if '"device": "l2sm-vNet"' in i['spec']['config']:
        resources.append(i['metadata']['name'])

    for k in range(len(multusInt)):
      multusInt[k] = multusInt[k].strip()
      #IF THERE IS PHYSICAL INTERFACE, ADD TO THE PHYSICAL NETWORK (FORMAT => NETWORK:INTERFACE)
      if "#" in multusInt[k]:
        splitText = multusInt[k].split("#")
        if splitText[0] in resources:
          physical.update({splitText[1]:splitText[0]})
          multusInt[k] = splitText[1]
          
      elif multusInt[k] in resources:
        network.append(k)

    #IF THERE ARE NO NETWORKS, LET MULTUS HANDLE THIS
    if not network and not physical:
      return
    else:
      if network:
        #TODO: CALL THE ADD SRIOV INSIDE, SINCE THE POD IS PATCHED AS WELL -> PASS THE PHYSICAL AS WELL.
        network_array = addVeth(body, name, namespace, network, physical, multusInt)
        logger.info(f"Pod {name} attached to network {network_array}")
      elif physical:
        #network_array = addSriov(body, name, namespace, physical, multusInt)
        addSriov(body, name, namespace, physical)
        v1 = client.CoreV1Api()
        ret = v1.read_namespaced_pod(name, namespace)
        ret.metadata.annotations['k8s.v1.cni.cncf.io/networks'] = ', '.join(multusInt)
        v1.patch_namespaced_pod(name, namespace, ret)
        logger.info(f"Pod attached to SRIOV")



# ([new_pod_mac1, ...], [old-macs-from-the-vn, ...])
def get_macs(name, db, cur) -> 'list[tuple[list[str], list[str]]]':
    nsql = "SELECT network FROM interfaces WHERE pod = '%s'" % (name)
    cur = db.cursor()
    cur.execute(nsql)
    data = cur.fetchall()

    networks = []
    sdn_arrays = []

    for k in range(len(data)):
      networks.append(data[k][0])
    
    netDict = list(dict.fromkeys(networks))

    for l in range(len(netDict)):
      netTuple = [] # Will be turned into a tuple later
      netArray = [] # Variable for the macs of other pods in the network
      podMacs = [] # Variable for the macs of the pod
      vsql = "SELECT mac FROM interfaces WHERE network = '%s' AND pod = '%s'" % (netDict[l], name)
      cur.execute(vsql)
      data = cur.fetchall()
      for m in range(len(data)):
        podMacs.append(data[m][0])

      netTuple.append(podMacs)

      wsql = "SELECT mac FROM interfaces WHERE network = '%s' AND pod != '%s'" % (netDict[l], name)
      cur.execute(wsql)
      macs = cur.fetchall()
      if len(macs) == 0:
        pass
      else:
        for i in range(len(macs)):
          netArray.append(macs[i][0])
      netTuple.append(netArray)
      sdn_arrays.append(tuple(netTuple))

    return sdn_arrays


#GET MACS FROM ANNOTATIONS (VPOD CASE) OR REMOTE POD (SRIOV CASE) AND GENERATE THE INTENTS
@kopf.on.update('pods.v1', annotations={'k8s.v1.cni.cncf.io/network-status': kopf.PRESENT, 'k8s.v1.cni.cncf.io/networks': kopf.PRESENT})
async def sdn_vn(body, name, namespace, logger, annotations, **kwargs):

    db = pymysql.connect(host=ip,user="l2sm",password="l2sm;",db="L2SM")
    # GET ALL INTERFACES ASSIGNED FOR THE POD
    nsql = "SELECT interface FROM interfaces WHERE pod = '%s'" % (name)
    cur = db.cursor()
    cur.execute(nsql)
    data = cur.fetchall()

    if not data:
      return
    
    #GET NETWORKS STATUS
    multus = json.loads(annotations['k8s.v1.cni.cncf.io/network-status'])
    devices = []

    for k in range(len(data)):
      devices.append(data[k][0])

    # IF NAMESPACE HAS THE NAMESPACE ATTACHED, GET THE SPLIT (SINCE THE NAMESPACE IS BEHIND THE INTERFACE ALWAYS (default/vpod1)). OTHERWISE, PROCCESSN IT AS IS.
    for i in multus:
      tempName = ''
      if len(i['name'].split('/')) == 1:
        tempName = i['name']
      else:
        tempName = i['name'].split('/')[1]

      if tempName in devices:
        # IF THE ANNOTATION CORRESPONDS TO A PCI INTERFACE (SRIOV)
        if "device-info" in i and i['device-info']['type'] == "pci":
          api = client.CustomObjectsApi()
          mult = api.get_namespaced_custom_object('k8s.cni.cncf.io', 'v1', namespace, 'network-attachment-definitions', tempName)
          conf = json.loads(mult['spec']['config'])
          # CHECK IF THE MAC ADDRESS MUST BE CONFIGURED BY MULTUS. IF SO, UPDATE THE PCI TABLE
          if 'mac' in conf:
            annotationMac = conf['mac']
            pciUpdate = "UPDATE pci SET mac = '%s' WHERE pci = '%s' and node = '%s'" % (annotationMac, "PCI:" + i['device-info']['pci']['pci-address'], body['spec']['nodeName'])
            cur.execute(pciUpdate)
            db.commit()
          
          # GET VLAN TAG VALUE IN MULTUS ANNOTATION (IF 0, USE -1 TO TELL ONOS THAT NO TAG IS USED)
          vlan = '/' + str(conf['vlan'])
          if vlan == '/0':
            vlan = '/-1'

          # GET THE MAC ADDRESS OF THE PCI IN ITS TABLE
          msql = "SELECT mac FROM pci WHERE pci = '%s' and node = '%s'" % ("PCI:" + i['device-info']['pci']['pci-address'], body['spec']['nodeName'])
          cur.execute(msql)
          val = cur.fetchone()

          # UPDATE THE MAC VALUE IN THE INTERFACES TABLE
          xsql = "UPDATE interfaces SET mac = '%s' WHERE pod = '%s' AND interface = '%s'" % (val[0] + vlan, name, tempName)
          cur.execute(xsql)

        # IF IT IS A VIRTUAL INTERFACE, GET THE MAC FROM THE ANNOTATION
        else:
          sql = "UPDATE interfaces SET mac = '%s' WHERE pod = '%s' AND interface = '%s'" % (i['mac'] + '/-1', name, tempName)
          cur.execute(sql)
    
    macList = get_macs(name, db, cur)
    logger.info(f"{macList}")

    sdnCon = OnosHost2HostConnectivityIntent(os.environ.get('CONTROLLER'))

    for net in macList:
      if len(net[1]) > 0:
        for one, two in itertools.product(net[0], net[1]):
          logger.info(f"Intent to perform: One {one} <-> Two {two} in {os.environ.get('CONTROLLER')}")
          intent_id = await sdnCon.create(one , two)
          logger.info(f"{intent_id}")
          jsql = "INSERT INTO intents (mac_one, mac_two, id) VALUES ('%s', '%s', '%s')" % (one, two, intent_id)
          cur.execute(jsql)
    
    db.commit()
    db.close()    



#UPDATE DATABASE WHEN POD IS DELETED (REMOVE ENTRY FROM DATABASE IF IT IS NOT A VPOD ANNOTATION)
@kopf.on.delete('pods.v1', annotations={'k8s.v1.cni.cncf.io/networks': kopf.PRESENT})
async def dpod_vn(name, logger, **kwargs):
    vpod = ['vpod1', 'vpod2', 'vpod3', 'vpod4', 'vpod5', 'vpod6', 'vpod7', 'vpod8', 'vpod9', 'vpod10']
    db = pymysql.connect(host=ip,user="l2sm",password="l2sm;",db="L2SM")
    cur = db.cursor()

    sdnCon = OnosHost2HostConnectivityIntent(os.environ.get('CONTROLLER'))

    msql = "SELECT interface, mac FROM interfaces WHERE pod = '%s'" % (name)
    cur.execute(msql)
    data = cur.fetchall()

    if not data:
      return

    # DELETE THE INTENTS FROM THE DATABASE
    for i in range(len(data)):
      isql = "SELECT id FROM intents WHERE mac_one = '%s' OR mac_two = '%s'" % (data[i][1], data[i][1])
      cur.execute(isql)
      intent = cur.fetchall()
      if intent:
        for k in range(len(intent)):
          await sdnCon.delete(intent[k][0])
          dsql = "DELETE from intents WHERE id = '%s'" % (intent[k][0])
          cur.execute(dsql)

      # EITHER UPDATE THE VIRTUAL INTERFACE OR DELETE THE PHYSICAL 
      if data[i][0] in vpod:
        sql = "UPDATE interfaces SET network = '-1', mac = '', pod = '' WHERE pod = '%s' AND interface = '%s'" % (name, data[i][0])
      else:
        sql = "DELETE from interfaces WHERE interface = '%s'" % (data[i][0])
      cur.execute(sql)


    db.commit()
    db.close()
    logger.info(f"Pod {name} removed")

#UPDATE DATABASE WHEN NETWORK IS DELETED
@kopf.on.delete('NetworkAttachmentDefinition', when=lambda spec, **_: '"device": "l2sm-vNet"' in spec['config'])
def delete_vn(name, logger, **kwargs):
    db = pymysql.connect(host=ip,user="l2sm",password="l2sm;",db="L2SM")
    cur = db.cursor()
    sql = "DELETE FROM networks WHERE network = '%s'" % (name)
    cur.execute(sql)
    db.commit()
    db.close()
    logger.info(f"Network has been deleted")

#DELETE DATABASE ENTRIES WHEN A NEW L2SM POD IS DELETED (A NEW NODE GETS OUT OF THE CLUSTER)
@kopf.on.delete('pods.v1', labels={'l2sm-component': 'l2-ps'})
def remove_node(body, logger, **kwargs):
    db = pymysql.connect(host=ip,user="l2sm",password="l2sm;",db="L2SM")
    cur = db.cursor()
    sql = "DELETE FROM interfaces WHERE node = '%s'" % (body['spec']['nodeName'])
    cur.execute(sql)
    db.commit()
    db.close()
    logger.info(f"Node {body['spec']['nodeName']} has been deleted from the cluster")

#DELETE DATABASE ENTRIES WHEN A NEW L2SM POD IS DELETED (A NEW NODE GETS OUT OF THE CLUSTER)
@kopf.on.delete('pods.v1', labels={'l2sm-component': 'l2sm-pci'})
def remove_pci(body, logger, **kwargs):
    db = pymysql.connect(host=ip,user="l2sm",password="l2sm;",db="L2SM")
    cur = db.cursor()
    sql = "DELETE FROM pci WHERE node = '%s'" % (body['spec']['nodeName'])
    cur.execute(sql)
    db.commit()
    db.close()
    logger.info(f"PCI in {body['spec']['nodeName']} has been deleted from the cluster")


class OnosHost2HostConnectivityIntent:
    def __init__(self, address: str):
        self.address = address

    async def create(self, host1: str, host2: str, **opts: dict) -> str:
        """
        Create a connectivity intent in ONOS and returns the intent ID.
        The ``host1`` and ``host2`` arguments should represent a MAC address +
        port, e.g. "00:00:00:00:00:01/-1". When port is -1, no port filtering
        will be made.
        ``opts`` can be used to add arbitrary fields to the request payload.
        """
        url = f"{self.address}/onos/v1/intents"
        intent: dict = {
            "type": "HostToHostIntent",
            "appId": "org.onosproject.net.intent",
            "one": host1,
            "two": host2,
            **opts,
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=intent) as response:
                if response.status >= 400:
                    error = await response.read()
                    raise aiohttp.ClientError(error, {"intent": intent})
                location: str = response.headers["location"]
                _, _, intent_id = location.strip("/").rpartition("/")
                if not intent_id:
                    raise aiohttp.ClientError("Invalid response", response.headers)
                return intent_id

    async def delete(self, intent_id: str) -> dict:
        """Remove a connectivity intent from ONOS"""
        url = f"{self.address}/onos/v1/intents/org.onosproject.net.intent/{intent_id}"
        async with aiohttp.ClientSession() as session:
            async with session.delete(url) as response:
                if response.status >= 400:
                    error = await response.read()
                    raise aiohttp.ClientError(error)
                text = await response.text()
                return json.loads(text or "null")