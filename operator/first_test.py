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

@kopf.on.create('pods.v1', annotations={'l2sm.k8s.conf.io/virtual-networks': kopf.PRESENT})
def pod_vn(name, logger, annotations, **kwargs):
    network = annotations.get('l2sm.k8s.conf.io/virtual-networks')
    api = client.CustomObjectsApi()
    items = api.list_cluster_custom_object('l2sm.k8s.conf.io', 'v1', 'virtual-networks').get('items')
    for i in items:
      #TEST IF NETWORK IS IN THE CLUSTER: IF NOT PRESENT, STOP EXECUTION OF THE POD/DEPLOYMENT, OTHERWISE INFORM DATABASE AND PUT INTERFACES
      logger.info(f"ESTAMOS AQUI DEBUGEAND ESTO: {i['metadata']['name']}")
#    logger.info(f"Network has been used/updated")


@kopf.on.delete('virtual-networks')
def delete_vn(spec, name, logger, **kwargs):
    db = pymysql.connect(host="163.117.140.254",user="l2sm",password="l2sm;",db="L2SM")
    cur = db.cursor()
    sql = "DELETE FROM networks WHERE id = '%s'" % (spec.get('id').strip())
    cur.execute(sql)
    db.commit()
    db.close()
    logger.info(f"Network has been deleted")
