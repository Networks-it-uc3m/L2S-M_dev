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

#UPDATE DATABASE WHEN NETWORK IS CREATED
@kopf.on.create('virtual-networks')
def create_vn(spec, name, logger, **kwargs):
    db = pymysql.connect(host="163.117.140.254",user="l2sm",password="l2sm;",db="L2SM")
    cur = db.cursor()
    network = spec.get('name')
    id = spec.get('id')
    sql = "INSERT INTO networks (network, id, metadata) VALUES ('%s', '%s', '%s')" % (network.strip(), id.strip(), name.strip())
    cur.execute(sql)
    db.commit()
    db.close()
    logger.info(f"Network has been created")


#ASSIGN POD TO NETWORK (TRIGGERS ONLY IF ANNOTATION IS PRESENT)
@kopf.on.create('pods.v1', annotations={'l2sm.k8s.conf.io/virtual-networks': kopf.PRESENT})
def pod_vn(body, name, namespace, logger, annotations, **kwargs):
    #GET NETWORK IN THE DESCRIPTOR
    network = annotations.get('l2sm.k8s.conf.io/virtual-networks')

    #VERIFY IF NETWORK IS PRESENT IN THE CLUSTER
    api = client.CustomObjectsApi()
    items = api.list_cluster_custom_object('l2sm.k8s.conf.io', 'v1', 'virtual-networks').get('items')
    resources = []
    for i in items:
      resources.append(i['metadata']['name'])
    if network not in resources:
      raise kopf.PermanentError("The pod could not be attached to network " + network + " since it was not defined in the cluster")

    #CHECK IF NODE HAS FREE VIRTUAL INTERFACES LEFT
    v1 = client.CoreV1Api()
    ret = v1.read_namespaced_pod(name, namespace)
    node = body['spec']['nodeName']

    nsql = "SELECT * FROM interfaces WHERE node = '%s' AND network = '-1'" % (node.strip())

    db = pymysql.connect(host="163.117.140.254",user="l2sm",password="l2sm;",db="L2SM")
    cur = db.cursor()

    cur.execute(nsql)
    data = cur.fetchone()
    if not data:
      db.close()
      raise kopf.PermanentError("l2sm could not deploy the pod: Node " + node.strip() + "has no free interfaces left")

    #IF THERE IS ALREADY A MULTUS ANNOTATION, APPEND IT TO THE END.
    interface_to_attach = data[0]
    if 'k8s.v1.cni.cncf.io/networks' not in ret.metadata.annotations:
      ret.metadata.annotations['k8s.v1.cni.cncf.io/networks'] = data[0].strip()
    else:
      ret.metadata.annotations['k8s.v1.cni.cncf.io/networks'].append(", " + data[0].strip())

    #PATCH NETWORK WITH ANNOTATION
    v1.patch_namespaced_pod(name, namespace, ret)

    #GET NETWORK NAME
    for j in items:
      if network in j['metadata']['name']:
        networkN = j['spec']['name']

    sql = "UPDATE interfaces SET network = '%s', pod = '%s' WHERE interface = '%s' AND node = '%s'" % (networkN.strip(), name, data[0], node)
    cur.execute(sql)
    db.commit()
    db.close()
    #HERE GOES SDN, THIS IS WHERE THE FUN BEGINS
    logger.info(f"Pod {name} attached to network {network} with name {networkN}")


#UPDATE DATABASE WHEN POD IS DELETED
@kopf.on.delete('pods.v1', annotations={'l2sm.k8s.conf.io/virtual-networks': kopf.PRESENT})
def dpod_vn(name, logger, **kwargs):
    db = pymysql.connect(host="163.117.140.254",user="l2sm",password="l2sm;",db="L2SM")
    cur = db.cursor()
    sql = "UPDATE interfaces SET network = '-1', pod = '' WHERE pod = '%s'" % (name)
    cur.execute(sql)
    db.commit()
    db.close()
    logger.info(f"Pod {name} removed")

#UPDATE DATABASE WHEN NETWORK IS DELETED
@kopf.on.delete('virtual-networks')
def delete_vn(spec, name, logger, **kwargs):
    db = pymysql.connect(host="163.117.140.254",user="l2sm",password="l2sm;",db="L2SM")
    cur = db.cursor()
    sql = "DELETE FROM networks WHERE id = '%s'" % (spec.get('id').strip())
    cur.execute(sql)
    db.commit()
    db.close()
    logger.info(f"Network has been deleted")
