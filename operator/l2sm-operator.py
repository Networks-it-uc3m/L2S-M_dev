import kopf
import os
import sys
import json
import subprocess
import secrets
import kubernetes
from subprocess import CalledProcessError
from random import randrange
from kubernetes import client, config
import pymysql
import random
import time

ip = "127.0.0.1"

#POPULATE DATABASE ENTRIES WHEN A NEW L2SM POD IS CREATED (A NEW NODE APPEARS)
@kopf.on.create('pods.v1', labels={'l2sm-component': 'l2-ps'})
def build_db(body, logger, annotations, **kwargs):
    db = pymysql.connect(host=ip,user="l2sm",password="l2sm;",db="L2SM")
    cur = db.cursor()
    #CREATE TABLES IF THEY DO NOT EXIST
    table1 = "CREATE TABLE IF NOT EXISTS networks (network TEXT NOT NULL, id TEXT NOT NULL);"
    table2 = "CREATE TABLE IF NOT EXISTS interfaces (interface TEXT NOT NULL, node TEXT NOT NULL, network TEXT, pod TEXT, mac TEXT);"
    cur.execute(table1)
    cur.execute(table2)
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
    sql = "INSERT INTO networks (network, id) VALUES ('%s', '%s')" % (name.strip(), id.strip())
    cur.execute(sql)

    db.commit()
    db.close()
    logger.info(f"Network has been created")

#ADD POD TO SRIOV BY CREATING A NEW ENTRY IN THE DB TABLE WITH THE MULTUS ANNOTATION NAME (USED TO FIND THE PCI LATER, SINCE IT IS ASSIGNED WHEN THE POD IS RUNNING, NOT BEFOREHAND)
def addSriov(body, name, namespace, physical, v1):
    node = body['spec']['nodeName']
    ret = v1.read_namespaced_pod(name, namespace)

    db = pymysql.connect(host=ip,user="l2sm",password="l2sm;",db="L2SM")
    cur = db.cursor()

    for inter, net in physical.items():
      sql = "INSERT INTO interfaces (interface, node, network, pod, mac) VALUES ('%s', '%s', '%s', '%s', '%s')" % (inter, node, net, name, '')
      cur.execute(sql)

    db.commit()
    db.close()
    return

#ADD POD TO VETH
def addVeth(body, name, namespace, network, physical, multusInt):
    #CHECK IF NODE HAS FREE VIRTUAL INTERFACES LEFT
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

    addSriov(body, name, namespace, physical, v1)

    return network_array

#ASSIGN POD TO NETWORK (TRIGGERS ONLY IF ANNOTATION IS PRESENT)
@kopf.on.create('pods.v1', annotations={'k8s.v1.cni.cncf.io/networks': kopf.PRESENT})
def pod_vn(body, name, namespace, logger, annotations, **kwargs):
    #GET MULTUS INTERFACES IN THE DESCRIPTOR
    #IN QUARANTINE: SLOWER THAN MULTUS!!!!!
    time.sleep(random.uniform(0,0.8)) #Make sure the database is not consulted at the same time to avoid overlaping

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
        v1 = client.CoreV1Api()
        ret = v1.read_namespaced_pod(name, namespace)
        ret.metadata.annotations['k8s.v1.cni.cncf.io/networks'] = ', '.join(multusInt)
        v1.patch_namespaced_pod(name, namespace, ret)
        addSriov(body, name, namespace, physical, v1) 
        logger.info(f"Pod attached to SRIOV")

#GET MACS FROM ANNOTATIONS (VPOD CASE) OR REMOTE POD (SRIOV CASE) AND GENERATE THE INTENTS
@kopf.on.update('pods.v1', annotations={'k8s.v1.cni.cncf.io/network-status': kopf.PRESENT, 'k8s.v1.cni.cncf.io/networks': kopf.PRESENT})
def sdn_vn(body, name, namespace, logger, annotations, **kwargs):
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
        # IF IT IS AN SRIOV INTERFACE, ASK THE REMOTE POD FOR THE MAC.
        if "device-info" in i and i['device-info']['type'] == "pci":
          # getPHYMAC
          # cur.execute(sql)
          pass
        # IF IT IS A VIRTUAL INTERFACE, GET THE MAC FROM THE ANNOTATION
        else:
          sql = "UPDATE interfaces SET mac = '%s' WHERE pod = '%s' AND interface = '%s'" % (i['mac'], name, tempName)
          cur.execute(sql)
  
    db.commit()
    db.close()    



#UPDATE DATABASE WHEN POD IS DELETED (REMOVE ENTRY FROM DATABASE IF IT IS NOT A VPOD ANNOTATION)
@kopf.on.delete('pods.v1', annotations={'k8s.v1.cni.cncf.io/networks': kopf.PRESENT})
def dpod_vn(name, logger, **kwargs):
    vpod = ['vpod1', 'vpod2', 'vpod3', 'vpod4', 'vpod5', 'vpod6', 'vpod7', 'vpod8', 'vpod9', 'vpod10']
    db = pymysql.connect(host=ip,user="l2sm",password="l2sm;",db="L2SM")
    cur = db.cursor()
    msql = "SELECT interface FROM interfaces WHERE pod = '%s'" % (name)
    cur.execute(msql)
    data = cur.fetchall()

    if not data:
      return

    for i in range(len(data)):
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
def delete_vn(spec, name, logger, **kwargs):
    db = pymysql.connect(host=ip,user="l2sm",password="l2sm;",db="L2SM")
    cur = db.cursor()
    sql = "DELETE FROM networks WHERE network = '%s'" % (name)
    cur.execute(sql)
    db.commit()
    db.close()
    logger.info(f"Network has been deleted")

#DELETE DATABASE ENTRIES WHEN A NEW L2SM POD IS DELETED (A NEW NODE GETS OUT OF THE CLUSTER)
@kopf.on.delete('pods.v1', labels={'l2sm-component': 'l2-ps'})
def remove_node(body, logger, annotations, **kwargs):
    db = pymysql.connect(host=ip,user="l2sm",password="l2sm;",db="L2SM")
    cur = db.cursor()
    sql = "DELETE FROM interfaces WHERE node = '%s'" % (body['spec']['nodeName'])
    cur.execute(sql)
    db.commit()
    db.close()
    logger.info(f"Node {body['spec']['nodeName']} has been deleted from the cluster")

